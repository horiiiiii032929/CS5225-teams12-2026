#!/usr/bin/env python3
"""Measure the per-request AWS operation counts the cost model needs (#45, E9).

`cost_model.py` used to multiply demand by a *budgeted* number of DynamoDB
requests taken from `docs/api-contract.md`. This script replaces those budgets
with measurements: it drives API Gateway v2 events through the real resolver in
`flatsplit_api.handlers.http`, with Moto standing in for DynamoDB and SQS and
live OneMap upstream, and counts every botocore API call, the items inside each
transaction, and every OneMap round trip, per request.

    export ONEMAP_TOKEN=...        # /places calls live OneMap and spends quota
    uv run --package flatsplit-api python docs/evaluation/e9/model/measure_operations.py

Writes `../evidence/measured-operations-<date>.json`, whose counts are copied
into `workloads.json` under `measured_operations`.

What this is not: Moto is not DynamoDB, so these are request and item counts,
not consumed capacity — the RRU/WRU conversion stays an assumption owned by
#34. Durations are laptop durations, so only the OneMap-bound lookup paths feed
the model, where real upstream network time dominates. The `/places` rows need
the persistent places work from #14; without it the lookup writes are zero and
the preference save fails.
"""

import base64
import json
import os
import subprocess
import sys
import time
from collections import Counter
from decimal import Decimal
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
EVIDENCE = os.path.join(os.path.dirname(HERE), "evidence")

sys.path.insert(0, os.path.join(REPO, "services", "api", "src"))
os.environ["TABLE_NAME"] = "flatsplit-measure"
os.environ["AWS_DEFAULT_REGION"] = "ap-southeast-1"
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("POWERTOOLS_LOG_LEVEL", "CRITICAL")

import urllib.request  # noqa: E402

import boto3  # noqa: E402
import botocore.client  # noqa: E402
from moto import mock_aws  # noqa: E402

READ_OPS = {"GetItem", "Query", "Scan", "BatchGetItem", "TransactGetItems"}
WRITE_OPS = {"PutItem", "UpdateItem", "DeleteItem", "BatchWriteItem", "TransactWriteItems"}

calls: Counter[str] = Counter()
items: Counter[str] = Counter()
_real_api = botocore.client.BaseClient._make_api_call
_real_urlopen = urllib.request.urlopen


def _counting_api(self: Any, operation_name: str, api_params: dict) -> Any:
    """Count one AWS API call, and the items inside a batch or transaction."""
    service = self.meta.service_model.service_name
    key = f"{service}:{operation_name}"
    calls[key] += 1
    count = 1
    if operation_name in {"TransactWriteItems", "TransactGetItems"}:
        count = len(api_params.get("TransactItems", []))
    elif operation_name == "BatchGetItem":
        count = sum(len(v.get("Keys", [])) for v in api_params.get("RequestItems", {}).values())
    elif operation_name == "BatchWriteItem":
        count = sum(len(v) for v in api_params.get("RequestItems", {}).values())
    items[key] += count
    return _real_api(self, operation_name, api_params)


def _counting_urlopen(*args: Any, **kwargs: Any) -> Any:
    calls["onemap:http"] += 1
    items["onemap:http"] += 1
    return _real_urlopen(*args, **kwargs)


botocore.client.BaseClient._make_api_call = _counting_api  # type: ignore[method-assign]
urllib.request.urlopen = _counting_urlopen  # type: ignore[assignment]

#: `POST /searches` returns 503 without a `RENT/CURRENT` pointer and publishing
#: real summaries is #10, so the measurement seeds its own. These are synthetic
#: numbers; only the operation counts are measured, never the rent itself.
SYNTHETIC_RENT = {
    "ANG MO KIO": {"3-ROOM": (2500, 2300, 2800, 180), "4-ROOM": (3000, 2800, 3300, 210)},
    "TAMPINES": {"3-ROOM": (2600, 2400, 2850, 240), "4-ROOM": (3100, 2900, 3400, 260)},
    "JURONG WEST": {"3-ROOM": (2450, 2250, 2700, 220), "4-ROOM": (2900, 2700, 3150, 230)},
    "BEDOK": {"3-ROOM": (2550, 2350, 2800, 200), "4-ROOM": (3050, 2850, 3300, 190)},
    "WOODLANDS": {"3-ROOM": (2400, 2200, 2650, 210), "4-ROOM": (2850, 2650, 3100, 220)},
}
SNAPSHOT = "synthetic-local-v1"
PERIOD = "2025-10/2026-09"


def seed_rent(table: Any) -> None:
    table.put_item(
        Item={
            "pk": "RENT", "sk": "CURRENT", "schemaVersion": 1, "snapshotId": SNAPSHOT,
            "period": PERIOD, "sourceMonthTo": PERIOD.split("/")[1],
            "validatedAt": "2026-10-20T00:00:00Z", "syntheticLocalFixture": True,
        }
    )
    for town, by_type in SYNTHETIC_RENT.items():
        for flat_type, (median, p25, p75, half_width) in by_type.items():
            table.put_item(
                Item={
                    "pk": f"RENT#{SNAPSHOT}", "sk": f"TOWN#{town}#{flat_type}",
                    "schemaVersion": 1, "town": town, "flatType": flat_type,
                    "currency": "SGD", "unit": "month", "statistic": "median",
                    "period": PERIOD, "median": Decimal(str(median)),
                    "p25": Decimal(str(p25)), "p75": Decimal(str(p75)),
                    "medianCi95Low": Decimal(str(median - half_width)),
                    "medianCi95High": Decimal(str(median + half_width)),
                    "count": 120, "blockCount": 40, "qualityStatus": "USABLE",
                    "syntheticLocalFixture": True,
                }
            )


def code_revision() -> str:
    """The revision measured, with a dirty flag: the counts belong to a build."""
    try:
        head = subprocess.run(
            ["git", "-C", REPO, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        changed = subprocess.run(
            ["git", "-C", REPO, "status", "--porcelain", "services/api/src"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return f"{head}+dirty" if changed else head
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


class Context:
    function_name = "flatsplit-api-measure"
    memory_limit_in_mb = 256
    invoked_function_arn = "arn:aws:lambda:ap-southeast-1:000000000000:function:measure"
    aws_request_id = "measure"


MEASURED: list[dict[str, object]] = []


def request(
    label: str,
    method: str,
    path: str,
    body: Any = None,
    token: str | None = None,
    query: str = "",
) -> dict:
    import flatsplit_api.handlers.http as http

    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    text = json.dumps(body) if body is not None else ""
    event = {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": query,
        "headers": headers,
        "queryStringParameters": dict(p.split("=", 1) for p in query.split("&") if p) or None,
        "requestContext": {
            "http": {"method": method, "path": path, "sourceIp": "127.0.0.1"},
            "requestId": "measure",
            "stage": "$default",
        },
        "body": base64.b64encode(text.encode()).decode(),
        "isBase64Encoded": True,
    }
    before_calls, before_items = Counter(calls), Counter(items)
    started = time.perf_counter()
    response = http.handler(event, Context())  # type: ignore[arg-type]
    elapsed = round((time.perf_counter() - started) * 1000)
    delta_calls, delta_items = calls - before_calls, items - before_items

    def total(source: Counter[str], ops: set[str]) -> int:
        return sum(
            v for k, v in source.items()
            if k.startswith("dynamodb:") and k.split(":", 1)[1] in ops
        )

    row = {
        "label": label,
        "method": method,
        "path": path + (f"?{query}" if query else ""),
        "status": response["statusCode"],
        "ms": elapsed,
        "ddbReadCalls": total(delta_calls, READ_OPS),
        "ddbWriteCalls": total(delta_calls, WRITE_OPS),
        "ddbReadItems": total(delta_items, READ_OPS),
        "ddbWriteItems": total(delta_items, WRITE_OPS),
        "onemapCalls": delta_calls.get("onemap:http", 0),
        "sqsCalls": sum(v for k, v in delta_calls.items() if k.startswith("sqs:")),
        "ops": dict(sorted(delta_calls.items())),
    }
    MEASURED.append(row)
    print(
        f"{label:<34} HTTP {row['status']}  {row['ms']:>5}ms  "
        f"ddb read {row['ddbReadCalls']}  write {row['ddbWriteCalls']} calls "
        f"/ {row['ddbWriteItems']} items  onemap {row['onemapCalls']}  sqs {row['sqsCalls']}"
    )
    return json.loads(response["body"]) if response.get("body") else {}


def main() -> int:
    if not os.environ.get("ONEMAP_TOKEN"):
        print("warning: no ONEMAP_TOKEN, so /places returns 503 and its rows are missing")
    with mock_aws():
        ddb = boto3.resource("dynamodb")
        ddb.create_table(
            TableName="flatsplit-measure",
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
        queue = boto3.client("sqs").create_queue(QueueName="flatsplit-measure-queue")
        os.environ["COMMUTE_QUEUE_URL"] = queue["QueueUrl"]
        seed_rent(ddb.Table("flatsplit-measure"))
        calls.clear()
        items.clear()

        first = request("places cold (A)", "GET", "/api/places", query="q=kent+ridge")
        request("places warm (A, cache hit)", "GET", "/api/places", query="q=kent+ridge")
        second = request("places cold (B)", "GET", "/api/places", query="q=raffles+place")
        place_a = first["places"][0]["placeId"]
        place_b = second["places"][0]["placeId"]
        print(
            f"   candidates: A={len(first['places'])} selectable "
            f"+ {len(first.get('unsupported', []))} unsupported, "
            f"B={len(second['places'])} selectable "
            f"+ {len(second.get('unsupported', []))} unsupported"
        )

        created = request(
            "group create", "POST", "/api/groups",
            {"groupName": "Cost measurement", "size": 2, "name": "Member A"},
        )
        gid = created["group"]["groupId"]
        member_a, token_a = created["memberId"], created["memberToken"]
        joined = request(
            "member join", "POST", f"/api/groups/{gid}/members",
            {"name": "Member B"}, created["group"]["inviteToken"],
        )
        member_b, token_b = joined["memberId"], joined["memberToken"]

        request(
            "preference save (first)", "PUT", f"/api/groups/{gid}/members/{member_a}",
            {"name": "Member A", "placeId": place_a, "budget": 1400, "maxCommute": 45},
            token_a,
        )
        request(
            "preference save (second)", "PUT", f"/api/groups/{gid}/members/{member_b}",
            {"name": "Member B", "placeId": place_b, "budget": 1400, "maxCommute": 45},
            token_b,
        )
        request("group read (shared link)", "GET", f"/api/groups/{gid}", token=token_a)
        search = request(
            "search start (first)", "POST", f"/api/groups/{gid}/searches", None, token_a
        )
        sid = search["searchId"]
        request(
            "search start (repeat, idempotent)", "POST",
            f"/api/groups/{gid}/searches", None, token_b,
        )
        request("search poll", "GET", f"/api/groups/{gid}/searches/{sid}", token=token_a)
        request("search poll (again)", "GET", f"/api/groups/{gid}/searches/{sid}", token=token_a)

        print("\ntotals by operation:")
        for key in sorted(calls):
            print(f"  {key:<34} {calls[key]:>4} calls  {items[key]:>4} items")

        stamp = time.strftime("%Y%m%d", time.gmtime())
        os.makedirs(EVIDENCE, exist_ok=True)
        path = os.path.join(EVIDENCE, f"measured-operations-{stamp}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "generatedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "issue": 45,
                    "experiment": "E9",
                    "mode": "local-moto + live OneMap",
                    "codeRevision": code_revision(),
                    "caveats": (
                        "Request and item counts, not consumed capacity. Durations are "
                        "laptop durations; only the OneMap-bound lookup paths feed the "
                        "model. No commute worker exists (#15), so its result write and "
                        "routing call remain assumed."
                    ),
                    "requests": MEASURED,
                    "totalCalls": dict(sorted(calls.items())),
                    "totalItems": dict(sorted(items.items())),
                },
                handle, indent=2, sort_keys=True,
            )
            handle.write("\n")
        print(f"\nwrote {os.path.relpath(path, REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
