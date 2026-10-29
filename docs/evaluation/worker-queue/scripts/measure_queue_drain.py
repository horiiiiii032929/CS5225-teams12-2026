"""Drive #15's worker off a real queue and measure what the unit tests cannot.

Issue #15's second acceptance criterion asks for concurrency, rate limits and
repeat-job deduplication "verified with sample jobs". The unit suite proves the
handler's logic and `test_search_api.py` runs it once per message in-process,
but neither exercises a queue: there is no visibility timeout, no
`ApproximateReceiveCount` that SQS itself incremented, no redrive, and no two
invocations in flight at once. This script supplies those.

What actually runs here, unmodified and configured only through environment
variables, is the deployed code: `handlers/http.py` claims the pairs and sends
payload v1 through `storage.py`, and `handlers/commute_worker.py` consumes it
and closes each claim through `commute_results.py`. Concurrency is emulated the
way the event source is configured -- `--concurrency` worker *processes*, each
taking one message at a time, matching `batchSize: 1` and a Lambda container's
process isolation -- and each process is a real client of a real queue.

Two things are stand-ins, and no conclusion here may ignore them:

- **AWS is Moto in server mode**, not AWS. Its queue semantics were probed
  before use and do behave (receive counts increment, an undeleted message
  returns after its visibility timeout, and the third receive redrives to the
  DLQ), but it is not a measurement of AWS SQS, and it says nothing about
  whether Lambda's event-source `maxConcurrency` holds the rate in production.
- **OneMap is replayed, not called.** The token expired on 23 October and this
  script mints none. Each routing call sleeps for a latency drawn from the eight
  per-pair timings actually recorded against live OneMap on 20 October
  (`../worker-routing/raw/2026-10-20/`, p50 992 ms), so the rate figure is
  grounded in a real measurement of the upstream rather than invented -- but it
  is a replay, and a live drain could differ.

Run it as `README.md` describes; it needs a `moto_server` to point at.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import boto3

#: Mirrors `COMMUTE_MAX_RECEIVES` / `maxReceiveCount` in infra/aws/src/api.ts.
MAX_RECEIVES = 3
#: The source queue's deployed visibility timeout, also from infra/aws/src/api.ts.
VISIBILITY_SECONDS = 180
#: OneMap's published ceiling, from docs/evaluation/feasibility/.
ONEMAP_CALLS_PER_MINUTE = 300
#: Where the replayed latencies come from.
LATENCY_EVIDENCE = (
    Path(__file__).resolve().parents[2]
    / "worker-routing"
    / "raw"
    / "2026-10-20"
    / "live_routing_20261020T085658Z.json"
)

CONTEXT = SimpleNamespace(
    function_name="commute-worker-harness",
    memory_limit_in_mb=256,
    invoked_function_arn="local",
    aws_request_id="commute-worker-harness",
)


# --------------------------------------------------------------------------
# replayed upstream
# --------------------------------------------------------------------------


def replay_latencies() -> list[int]:
    """The per-pair routing times measured against live OneMap on 20 October."""
    evidence = json.loads(LATENCY_EVIDENCE.read_text())
    rows = evidence["pairs"]["rows"]
    return [int(row["elapsedMs"]) for row in rows]


def stub_route(mode: str, latencies: Sequence[int], seed: int) -> Any:
    """Replace routing's transport, keeping every other code path real.

    `route()` still parses payload v1's coordinates, converts the date, picks
    the shortest of the itineraries and classifies failures; only the HTTP call
    is replaced, which is also what skips the token pre-flight.
    """
    from flatsplit_api.routing import RoutingRetryable, route

    rng = random.Random(seed)

    def transport(_params: dict[str, Any]) -> Any:
        time.sleep(rng.choice(latencies) / 1000)
        if mode == "retryable":
            raise RoutingRetryable("Replayed upstream throttling (HTTP 429).")
        # One itinerary in OneMap's routing shape, 30.5 minutes (#3).
        return {
            "plan": {
                "itineraries": [{"duration": 1830, "transfers": 1, "walkTime": 300}]
            }
        }

    def routed(origin: Any, destination: Any, **kwargs: Any) -> Any:
        return route(origin, destination, transport=transport, **kwargs)

    return routed


# --------------------------------------------------------------------------
# the worker process
# --------------------------------------------------------------------------


def run_worker(args: argparse.Namespace) -> None:
    """One emulated Lambda container: receive one message, invoke, delete.

    Appends every message it handled to `--events-out` as JSON lines, so the
    parent can reconstruct what overlapped with what. A file rather than stdout,
    because the handler's own Powertools logger also writes JSON there.
    """
    from flatsplit_api.handlers import commute_worker

    events = Path(args.events_out).open("a")

    commute_worker.route = stub_route(  # type: ignore[assignment]
        args.route_mode, replay_latencies(), args.seed
    )
    sqs = boto3.client("sqs", endpoint_url=args.endpoint)
    idle = 0
    while idle < args.idle_receives:
        received = sqs.receive_message(
            QueueUrl=args.queue_url,
            MaxNumberOfMessages=1,  # batchSize: 1
            AttributeNames=["All"],
            WaitTimeSeconds=1,
        ).get("Messages", [])
        if not received:
            idle += 1
            continue
        idle = 0
        message = received[0]
        receives = int(message["Attributes"]["ApproximateReceiveCount"])
        event = {
            "Records": [
                {
                    "messageId": message["MessageId"],
                    "body": message["Body"],
                    "attributes": message["Attributes"],
                }
            ]
        }
        started = time.time()
        response = commute_worker.handler(event, CONTEXT)  # type: ignore[arg-type]
        ended = time.time()
        retried = bool(response["batchItemFailures"])
        if not retried:
            sqs.delete_message(
                QueueUrl=args.queue_url, ReceiptHandle=message["ReceiptHandle"]
            )
        body = json.loads(message["Body"])
        events.write(
            json.dumps(
                {
                    "worker": args.worker_id,
                    "messageId": message["MessageId"],
                    "jobId": body.get("jobId"),
                    "town": body.get("town"),
                    "stationKey": body.get("stationKey"),
                    "receiveCount": receives,
                    "startedAt": started,
                    "endedAt": ended,
                    "returnedToQueue": retried,
                    "body": message["Body"],
                }
            )
            + "\n"
        )
        events.flush()
    events.close()


# --------------------------------------------------------------------------
# provisioning
# --------------------------------------------------------------------------


def provision_table(endpoint: str, name: str) -> Any:
    resource = boto3.resource("dynamodb", endpoint_url=endpoint)
    resource.create_table(
        TableName=name,
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return resource.Table(name)


def provision_queue(endpoint: str, name: str, *, visibility: int) -> tuple[str, str]:
    """A source queue and its DLQ, with the deployed redrive policy."""
    sqs = boto3.client("sqs", endpoint_url=endpoint)
    dlq = sqs.create_queue(QueueName=f"{name}-dlq")["QueueUrl"]
    arn = sqs.get_queue_attributes(QueueUrl=dlq, AttributeNames=["QueueArn"])[
        "Attributes"
    ]["QueueArn"]
    queue = sqs.create_queue(
        QueueName=name,
        Attributes={
            "VisibilityTimeout": str(visibility),
            "RedrivePolicy": json.dumps(
                {"deadLetterTargetArn": arn, "maxReceiveCount": str(MAX_RECEIVES)}
            ),
        },
    )["QueueUrl"]
    return queue, dlq


def seed_fixtures(table: Any, stations: Sequence[str]) -> None:
    """Synthetic place and rent records: #10 and #14 are not this issue."""
    now = int(time.time())
    for station in stations:
        table.put_item(
            Item={
                "pk": f"PLACE#{station}",
                "sk": "META",
                "label": station,
                "address": "Singapore",
                "station": {
                    "stationKey": station,
                    "codes": [],
                    "name": station,
                    "lat": Decimal("1.2936"),
                    "lng": Decimal("103.7845"),
                    "snapMetres": 0,
                    "snapWarning": False,
                },
                "ttl": now + 86400,
            }
        )
    table.put_item(
        Item={
            "pk": "RENT",
            "sk": "CURRENT",
            "schemaVersion": 1,
            "snapshotId": "harness",
            "period": "2025-10/2026-09",
        }
    )
    for town, median in [("CLEMENTI", 2400), ("QUEENSTOWN", 3000)]:
        table.put_item(
            Item={
                "pk": "RENT#harness",
                "sk": f"TOWN#{town}#3-ROOM",
                "schemaVersion": 1,
                "town": town,
                "flatType": "3-ROOM",
                "median": median,
                "p25": median - 100,
                "p75": median + 100,
                "medianCi95Low": median - 50,
                "medianCi95High": median + 50,
                "count": 200,
                "qualityStatus": "USABLE",
            }
        )


# --------------------------------------------------------------------------
# the real HTTP path, used to enqueue
# --------------------------------------------------------------------------


def call(
    method: str, path: str, token: str | None = None, body: Any = None
) -> tuple[int, dict[str, Any]]:
    """Invoke the deployed resolver, exactly as API Gateway would."""
    from flatsplit_api.handlers import http

    event = {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": "",
        "queryStringParameters": None,
        "headers": {
            "content-type": "application/json",
            **({"authorization": f"Bearer {token}"} if token else {}),
        },
        "requestContext": {
            "http": {"method": method, "path": path},
            "requestId": "queue-harness",
            "stage": "$default",
        },
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
    }
    response = http.handler(event, CONTEXT)  # type: ignore[arg-type]
    return response["statusCode"], json.loads(response["body"])


def start_search(station: str) -> tuple[str, str, str]:
    """A real two-member group on one station, then a real search submission."""
    status, created = call(
        "POST",
        "/groups",
        body={"groupName": "Queue harness", "size": 2, "name": "Alex"},
    )
    assert status == 201, created
    gid = created["group"]["groupId"]
    invite = created["group"]["inviteToken"]
    members = [created]
    status, joined = call("POST", f"/groups/{gid}/members", invite, {"name": "Sam"})
    assert status == 201, joined
    members.append(joined)
    for index, member in enumerate(members):
        status, saved = call(
            "PUT",
            f"/groups/{gid}/members/{member['memberId']}",
            member["memberToken"],
            {
                "name": "Alex" if index == 0 else "Sam",
                "placeId": station,
                # Above the seeded medians, so a resolved pair can actually be
                # ranked and the drain is shown through to a result.
                "budget": 3200,
                "maxCommute": 45,
            },
        )
        assert status == 200, saved
    token = members[0]["memberToken"]
    status, started = call("POST", f"/groups/{gid}/searches", token)
    assert status in (200, 201), started
    return gid, started["searchId"], token


# --------------------------------------------------------------------------
# scenarios
# --------------------------------------------------------------------------


def queue_depth(sqs: Any, queue_url: str) -> int:
    attributes = sqs.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=[
            "ApproximateNumberOfMessages",
            "ApproximateNumberOfMessagesNotVisible",
        ],
    )["Attributes"]
    return int(attributes["ApproximateNumberOfMessages"]) + int(
        attributes["ApproximateNumberOfMessagesNotVisible"]
    )


def drain(
    args: argparse.Namespace, queue_url: str, concurrency: int, *, mode: str = "ok"
) -> list[dict[str, Any]]:
    """Run `concurrency` worker processes until the queue stops delivering."""
    children = []
    # Per-invocation records are intermediate: the parent folds them into the
    # evidence file, so they belong in a temporary directory, not beside it.
    logs = Path(tempfile.mkdtemp(prefix="commute-worker-harness-"))
    for worker_id in range(concurrency):
        out = logs / f"worker-{concurrency}-{worker_id}.jsonl"
        out.write_text("")
        children.append(
            (
                out,
                subprocess.Popen(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--role",
                        "worker",
                        "--endpoint",
                        args.endpoint,
                        "--queue-url",
                        queue_url,
                        "--worker-id",
                        str(worker_id),
                        "--route-mode",
                        mode,
                        "--seed",
                        str(args.seed + worker_id),
                        "--idle-receives",
                        str(args.idle_receives),
                        "--events-out",
                        str(out),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env={**os.environ},
                ),
            )
        )
    events: list[dict[str, Any]] = []
    for out, child in children:
        _, err = child.communicate()
        if child.returncode != 0:
            raise RuntimeError(f"A worker process failed:\n{err}")
        for line in out.read_text().splitlines():
            if line.strip():
                events.append(json.loads(line))
    return events


def max_in_flight(events: Sequence[Mapping[str, Any]]) -> int:
    """The most invocations whose [start, end) windows actually overlapped."""
    edges: list[tuple[float, int]] = []
    for event in events:
        edges.append((float(event["startedAt"]), 1))
        edges.append((float(event["endedAt"]), -1))
    edges.sort()
    current = peak = 0
    for _, delta in edges:
        current += delta
        peak = max(peak, current)
    return peak


def pairs_for(table: Any, station: str) -> list[dict[str, Any]]:
    from boto3.dynamodb.conditions import Key

    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": Key("pk").eq(f"COMMUTE#{station}")
    }
    while True:
        page = table.query(**kwargs)
        items.extend(page.get("Items", []))
        token = page.get("LastEvaluatedKey")
        if not token:
            return items
        kwargs["ExclusiveStartKey"] = token


def receive_one(sqs: Any, queue_url: str, *, wait: int = 2) -> dict[str, Any] | None:
    messages = sqs.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=1,
        AttributeNames=["All"],
        WaitTimeSeconds=wait,
    ).get("Messages", [])
    return messages[0] if messages else None


def invoke_once(sqs: Any, queue_url: str, message: Mapping[str, Any]) -> bool:
    """Invoke the handler for one received message; True if it was deleted."""
    from flatsplit_api.handlers import commute_worker

    event = {
        "Records": [
            {
                "messageId": message["MessageId"],
                "body": message["Body"],
                "attributes": message["Attributes"],
            }
        ]
    }
    response = commute_worker.handler(event, CONTEXT)  # type: ignore[arg-type]
    if response["batchItemFailures"]:
        return False
    sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
    return True


def jsonable(value: Any) -> Any:
    """DynamoDB hands back Decimal; evidence has to be plain JSON."""
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float | str):
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return str(value)


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------


def measure_drain(
    args: argparse.Namespace, concurrency: int, table: Any, sqs: Any, run_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]], str, str]:
    """One real search, drained by `concurrency` worker processes.

    Returns the measurements, the per-invocation events, and the queue pair, so
    a caller can go on to replay a message or inspect the DLQ.
    """
    queue_url, dlq_url = provision_queue(
        args.endpoint,
        f"CommuteJobs-{run_id}-c{concurrency}",
        visibility=VISIBILITY_SECONDS,
    )
    os.environ["COMMUTE_QUEUE_URL"] = queue_url
    gid, search_id, token = start_search("KENT_RIDGE")
    enqueued = queue_depth(sqs, queue_url)
    started = time.time()
    events = drain(args, queue_url, concurrency, mode="ok")
    wall = time.time() - started
    pairs = pairs_for(table, "KENT_RIDGE")
    resolved = [item for item in pairs if item["status"] == "ok"]
    window = max(e["endedAt"] for e in events) - min(e["startedAt"] for e in events)
    durations = sorted((e["endedAt"] - e["startedAt"]) * 1000 for e in events)
    rate = len(events) / window * 60 if window else None
    status_code, status_body = call("GET", f"/groups/{gid}/searches/{search_id}", token)
    measured = {
        "concurrency": concurrency,
        "messagesEnqueuedByProducer": enqueued,
        "invocations": len(events),
        "pairRecords": len(pairs),
        "pairsOk": len(resolved),
        "pairsUnavailable": len([i for i in pairs if i["status"] == "unavailable"]),
        "pairsPending": len([i for i in pairs if i["status"] == "pending"]),
        "redeliveries": len([e for e in events if e["receiveCount"] > 1]),
        "wallSeconds": round(wall, 2),
        "busyWindowSeconds": round(window, 2),
        "maxObservedInFlight": max_in_flight(events),
        "invocationMsP50": round(statistics.median(durations), 1),
        "invocationMsMin": round(durations[0], 1),
        "invocationMsMax": round(durations[-1], 1),
        "achievedCallsPerMinute": round(rate, 1) if rate else None,
        "headroomUnderCap": round(ONEMAP_CALLS_PER_MINUTE - rate, 1) if rate else None,
        "perWorkerInvocations": {
            str(worker): len([e for e in events if e["worker"] == worker])
            for worker in sorted({e["worker"] for e in events})
        },
        "searchStatusAfterDrain": {
            "httpStatus": status_code,
            "status": status_body.get("status"),
            "progress": status_body.get("progress"),
            "rankedTowns": len(status_body.get("ranked") or []),
            "excludedTowns": len(status_body.get("excluded") or []),
            "topTown": (status_body.get("ranked") or [{}])[0].get("town"),
        },
        "dlqDepth": queue_depth(sqs, dlq_url),
        "sampleRecord": jsonable(
            next(
                (item for item in resolved if item["sk"] == "TOWN#CLEMENTI"),
                resolved[0] if resolved else None,
            )
        ),
    }
    return measured, events, queue_url, dlq_url


def new_world(args: argparse.Namespace, run_id: str) -> tuple[Any, Any]:
    """A fresh table and SQS client, so no run inherits another's cache."""
    from flatsplit_api import storage
    from flatsplit_api.handlers import commute_worker

    table_name = f"flatsplit-queue-harness-{run_id}"
    os.environ["TABLE_NAME"] = table_name
    os.environ["DYNAMODB_ENDPOINT_URL"] = args.endpoint
    os.environ["SQS_ENDPOINT_URL"] = args.endpoint
    os.environ["COMMUTE_MAX_RECEIVES"] = str(MAX_RECEIVES)
    # A Lambda container reads TABLE_NAME once and caches its store; this
    # process plays several containers in turn, so the caches have to go.
    storage.group_store.cache_clear()
    storage._sqs_client.cache_clear()
    commute_worker._results.cache_clear()
    table = provision_table(args.endpoint, table_name)
    seed_fixtures(table, ["KENT_RIDGE", "ONE_NORTH"])
    return table, boto3.client("sqs", endpoint_url=args.endpoint)


def run_sweep(args: argparse.Namespace) -> int:
    """Measure the drain rate at several concurrencies.

    This is what turns `maxConcurrency: 3` from an arithmetic choice into a
    measured one: the handler has no rate limiter, so if the achieved rate does
    not track concurrency, the claim that concurrency alone bounds the call rate
    is wrong.
    """
    levels = [int(level) for level in args.sweep.split(",")]
    report: dict[str, Any] = {
        "script": Path(__file__).name,
        "scriptVersion": "1.0.0",
        "issue": 15,
        "mode": "sweep",
        "runAt": datetime.now(UTC).isoformat(),
        "question": (
            "Does the achieved routing rate track the event source's "
            "concurrency, and where does it meet OneMap's published cap?"
        ),
        "stands_in_for": stand_ins(args, replay_latencies()),
        "config": {
            "onemapCallsPerMinuteCap": ONEMAP_CALLS_PER_MINUTE,
            "deployedConcurrency": 3,
            "visibilitySeconds": VISIBILITY_SECONDS,
        },
        "levels": [],
    }
    for level in levels:
        run_id = uuid.uuid4().hex[:8]
        table, sqs = new_world(args, run_id)
        measured, _events, _queue, _dlq = measure_drain(args, level, table, sqs, run_id)
        print(
            f"  concurrency {level}: {measured['achievedCallsPerMinute']} calls/min, "
            f"{measured['wallSeconds']}s wall, "
            f"max in flight {measured['maxObservedInFlight']}"
        )
        report["levels"].append(measured)

    rates = [level["achievedCallsPerMinute"] for level in report["levels"]]
    deployed = next(
        (level for level in report["levels"] if level["concurrency"] == 3), None
    )
    checks = {
        "every level drained its search completely": all(
            level["pairsPending"] == 0 for level in report["levels"]
        ),
        "every level honoured its concurrency": all(
            level["maxObservedInFlight"] == level["concurrency"]
            for level in report["levels"]
        ),
        "the rate rises with concurrency": rates == sorted(rates),
        "the deployed concurrency stays under the cap": deployed is not None
        and deployed["achievedCallsPerMinute"] < ONEMAP_CALLS_PER_MINUTE,
    }
    for name, passed in checks.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
    report["perCallCapacity"] = {
        "callsPerMinutePerWorker": [
            round(level["achievedCallsPerMinute"] / level["concurrency"], 1)
            for level in report["levels"]
        ],
        "concurrencyThatWouldMeetTheCap": round(
            ONEMAP_CALLS_PER_MINUTE / (rates[0] / report["levels"][0]["concurrency"]),
            1,
        )
        if rates and rates[0]
        else None,
    }
    report["verdict"] = "PASS" if all(checks.values()) else "FAIL"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"\nverdict: {report['verdict']}\nevidence: {out}")
    return 0 if report["verdict"] == "PASS" else 1


def stand_ins(args: argparse.Namespace, latencies: Sequence[int]) -> dict[str, Any]:
    return {
        "aws": "moto server (not AWS); queue semantics probed before use",
        "onemap": {
            "mode": "replayed latency, stubbed reply",
            "source": "docs/evaluation/worker-routing/raw/2026-10-20/",
            "latenciesMs": list(latencies),
            "reason": "the shared OneMap token expired on 2026-10-23",
        },
        "concurrency": (
            "one worker process per concurrent slot, one message each, "
            "emulating the event source's batchSize 1 and maxConcurrency; "
            "Lambda's own scaling is not under test"
        ),
    }


def run_parent(args: argparse.Namespace) -> int:
    if args.sweep:
        return run_sweep(args)
    run_id = uuid.uuid4().hex[:8]

    from flatsplit_api.handlers import commute_worker

    latencies = replay_latencies()
    table, sqs = new_world(args, run_id)
    report: dict[str, Any] = {
        "script": Path(__file__).name,
        "scriptVersion": "1.0.0",
        "issue": 15,
        "runAt": datetime.now(UTC).isoformat(),
        "runId": run_id,
        "stands_in_for": stand_ins(args, latencies),
        "config": {
            "maxReceives": MAX_RECEIVES,
            "visibilitySeconds": VISIBILITY_SECONDS,
            "shortVisibilitySeconds": args.short_visibility,
            "concurrency": args.concurrency,
            "onemapCallsPerMinuteCap": ONEMAP_CALLS_PER_MINUTE,
        },
        "scenarios": {},
    }

    # ---------------- A: drain a real search at concurrency N ----------------
    measured, events, queue_url, dlq_url = measure_drain(
        args, args.concurrency, table, sqs, run_id
    )
    measured["question"] = (
        "At the configured concurrency, how fast does a real search's queue "
        "drain, and what routing rate does that imply?"
    )
    report["scenarios"]["drain"] = measured

    # ---------------- B: a duplicate delivery of a resolved pair ----------------
    # The parent invokes the handler directly from here on, so its routing has
    # to be replaced too; otherwise it would call OneMap with the expired token.
    commute_worker.route = stub_route("ok", latencies, args.seed)  # type: ignore[assignment]
    sample = next((e for e in events if not e["returnedToQueue"]), None)
    assert sample is not None, "the drain produced no completed message to replay"
    key = {"pk": f"COMMUTE#{sample['stationKey']}", "sk": f"TOWN#{sample['town']}"}
    before = table.get_item(Key=key)["Item"]
    sqs.send_message(QueueUrl=queue_url, MessageBody=sample["body"])
    duplicate = receive_one(sqs, queue_url)
    assert duplicate is not None, "the duplicate was not delivered"
    deleted = invoke_once(sqs, queue_url, duplicate)
    after = table.get_item(Key=key)["Item"]
    report["scenarios"]["duplicate_delivery"] = {
        "question": (
            "Does redelivering the exact payload of an already-resolved pair "
            "change the stored result?"
        ),
        "pair": f"{sample['stationKey']}/{sample['town']}",
        "jobId": sample["jobId"],
        "messageDeletedNotRetried": deleted,
        "recordUnchanged": jsonable(before) == jsonable(after),
        "computedAtBefore": str(before.get("computedAt")),
        "computedAtAfter": str(after.get("computedAt")),
        "attemptsBefore": int(before.get("attempts", -1)),
        "attemptsAfter": int(after.get("attempts", -1)),
        "dlqDepth": queue_depth(sqs, dlq_url),
    }

    # ---------------- C and D: exhaustion and the DLQ ----------------
    short_url, short_dlq = provision_queue(
        args.endpoint,
        f"CommuteJobs-short-{run_id}",
        visibility=args.short_visibility,
    )
    os.environ["COMMUTE_QUEUE_URL"] = short_url
    start_search("ONE_NORTH")
    # The search enqueues every routable pair, but this scenario needs exactly
    # one message in the queue: the other 25 would otherwise accumulate receive
    # counts while waiting and redrive into the DLQ, which scenario D asserts
    # on. So capture one real payload v1, purge the queue, and put it back.
    first = receive_one(sqs, short_url, wait=5)
    assert first is not None, "the producer enqueued nothing on the short queue"
    target = json.loads(first["Body"])
    sqs.purge_queue(QueueUrl=short_url)
    time.sleep(1)
    sqs.send_message(QueueUrl=short_url, MessageBody=first["Body"])
    commute_worker.route = stub_route(  # type: ignore[assignment]
        "retryable", latencies, args.seed
    )
    receipts: list[dict[str, Any]] = []
    while len(receipts) < MAX_RECEIVES:
        message = receive_one(sqs, short_url, wait=2)
        if message is None:
            time.sleep(0.5)
            continue
        receipts.append(
            {
                "receiveCount": int(message["Attributes"]["ApproximateReceiveCount"]),
                "deleted": invoke_once(sqs, short_url, message),
            }
        )
        if len(receipts) < MAX_RECEIVES:
            time.sleep(args.short_visibility + 0.5)
    exhausted = table.get_item(
        Key={"pk": f"COMMUTE#{target['stationKey']}", "sk": f"TOWN#{target['town']}"}
    )["Item"]
    report["scenarios"]["retry_exhaustion"] = {
        "question": (
            "With routing failing transiently, does the queue redeliver and "
            "does the worker close the pair itself on its final receive?"
        ),
        "pair": f"{target['stationKey']}/{target['town']}",
        "receives": receipts,
        "status": exhausted["status"],
        "error": exhausted.get("error"),
        "attempts": int(exhausted.get("attempts", -1)),
        "retryAfterIsEpochSeconds": isinstance(exhausted.get("retryAfter"), int)
        or str(exhausted.get("retryAfter", "")).isdigit(),
        "retryAfterSecondsFromNow": int(exhausted.get("retryAfter", 0))
        - int(time.time()),
        "carriesNoMinutes": "minutes" not in exhausted,
        "dlqDepth": queue_depth(sqs, short_dlq),
    }

    unkeyable = json.dumps({"schemaVersion": 9, "jobId": "nope"})
    sqs.send_message(QueueUrl=short_url, MessageBody=unkeyable)
    attempts = 0
    while attempts < MAX_RECEIVES:
        message = receive_one(sqs, short_url, wait=2)
        if message is None:
            break
        if json.loads(message["Body"]).get("schemaVersion") != 9:
            continue
        attempts += 1
        invoke_once(sqs, short_url, message)
        time.sleep(args.short_visibility + 0.5)
    # SQS moves an over-counted message on the next receive attempt, not when
    # the previous one lapses, so the redrive needs one more (empty) poll.
    redrive_poll = receive_one(sqs, short_url, wait=2)
    report["scenarios"]["unaccountable_payload"] = {
        "question": "Where does a message the handler cannot key end up?",
        "payload": unkeyable,
        "receivesBeforeRedrive": attempts,
        "stillDeliverableAfterRedrive": redrive_poll is not None,
        "sourceQueueDepth": queue_depth(sqs, short_url),
        "dlqDepth": queue_depth(sqs, short_dlq),
    }

    report["verdict"] = verdict(report)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n")
    print(json.dumps(report["scenarios"], indent=2, default=str))
    print(f"\nverdict: {report['verdict']}\nevidence: {out}")
    return 0 if report["verdict"] == "PASS" else 1


def verdict(report: Mapping[str, Any]) -> str:
    """Only the assertions this harness can honestly make."""
    drained = report["scenarios"]["drain"]
    duplicate = report["scenarios"]["duplicate_delivery"]
    exhaustion = report["scenarios"]["retry_exhaustion"]
    unaccountable = report["scenarios"]["unaccountable_payload"]
    checks = {
        "every enqueued message was invoked": drained["invocations"]
        >= drained["messagesEnqueuedByProducer"],
        "every routable pair stored a route": drained["pairsPending"] == 0,
        "the drain used the configured concurrency": drained["maxObservedInFlight"]
        == report["config"]["concurrency"],
        "the achieved rate stayed under OneMap's cap": (
            drained["achievedCallsPerMinute"] or 0
        )
        < report["config"]["onemapCallsPerMinuteCap"],
        "a clean drain left the DLQ empty": drained["dlqDepth"] == 0,
        "the drained search reads back as complete": drained["searchStatusAfterDrain"][
            "status"
        ]
        == "complete",
        "the completed search ranked at least one town": drained[
            "searchStatusAfterDrain"
        ]["rankedTowns"]
        > 0,
        "a duplicate delivery changed nothing": duplicate["recordUnchanged"],
        "a duplicate was still deleted, not retried": duplicate[
            "messageDeletedNotRetried"
        ],
        "the queue redelivered until the redrive count": [
            r["receiveCount"] for r in exhaustion["receives"]
        ]
        == list(range(1, MAX_RECEIVES + 1)),
        "the final receive closed the pair as unavailable": exhaustion["status"]
        == "unavailable",
        "an unavailable pair carries no minutes": exhaustion["carriesNoMinutes"],
        "exhaustion did not reach the DLQ": exhaustion["dlqDepth"] == 0,
        "an unaccountable payload did reach the DLQ": unaccountable["dlqDepth"] == 1,
    }
    failed = [name for name, passed in checks.items() if not passed]
    for name, passed in checks.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
    return "PASS" if not failed else "FAIL"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=["parent", "worker"], default="parent")
    parser.add_argument("--endpoint", default="http://127.0.0.1:5001")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument(
        "--sweep",
        help=(
            "Comma-separated concurrencies to measure the drain rate at, "
            "e.g. 1,2,3,4,6. Runs only the drain, once per level."
        ),
    )
    parser.add_argument("--seed", type=int, default=15)
    parser.add_argument("--idle-receives", type=int, default=4)
    parser.add_argument("--short-visibility", type=int, default=2)
    parser.add_argument(
        "--out",
        default=str(
            Path(__file__).resolve().parents[1]
            / "raw"
            / datetime.now(UTC).strftime("%Y-%m-%d")
            / f"queue_drain_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        ),
    )
    parser.add_argument("--queue-url")
    parser.add_argument("--worker-id", type=int, default=0)
    parser.add_argument("--route-mode", choices=["ok", "retryable"], default="ok")
    parser.add_argument("--events-out")
    args = parser.parse_args(argv)
    if args.role == "worker":
        run_worker(args)
        return 0
    return run_parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
