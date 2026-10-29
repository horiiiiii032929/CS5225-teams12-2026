"""Commute worker Lambda (#15): one queued station-town pair per message.

The producer (#16) claims a pair and sends payload v1; this consumes the same
`CommuteJobs` queue, routes the pair once and ends the claim with a fenced
write. Three things are deliberately absent:

- **No retry loop.** A transient failure returns the message to the queue, so
  the schedule is the source queue's 180-second visibility and three receives.
  Sleeping inside the invocation would be billed, would hold one of only three
  concurrent slots, and would risk the visibility timeout.
- **No rate limiter of its own.** C7's 250 calls/min is shared with
  `/places`, so it cannot live in this handler: it is one counter per minute
  in the table (`call_budget.py`), and a routing call reserves against it
  first. A token bucket inside the invocation would bound one instance of
  three and could not reserve the lookup headroom at all. `maxConcurrency: 3`
  stays as a resource bound, not the rate: a drain off a real queue measured
  165 calls/min at three in flight, with per-worker throughput near 55-61
  from one slot to six (docs/evaluation/worker-queue/), which bounds in-flight
  work but not a window of fast cached replies.
- **No fan-in counter.** Search status is derived when it is read, so a worker
  never reports progress; it resolves its own pair and nothing else.

On its final receive the worker records a terminal `unavailable` itself rather
than leaving the pair `pending` for a DLQ consumer to interpret. The DLQ then
holds only what this handler could not account for: a payload that cannot be
traced to a cache item, a crash, or a completion write that failed.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

from flatsplit_api.commute_results import CommuteResults
from flatsplit_api.routing import (
    Route,
    RoutingError,
    RoutingUnroutable,
    route,
)

logger = Logger()

#: Keep in step with the source queue's redrive policy in infra/aws/src/api.ts.
DEFAULT_MAX_RECEIVES = 3
#: A day: the monthly routing baseline cannot change sooner, so an earlier
#: repeat would spend quota to be told the same thing.
UNROUTABLE_RETRY_SECONDS = 86400
#: Short: throttling passes and a rotated token works immediately, so an
#: explicit repeat should be allowed to try again soon.
TRANSIENT_RETRY_SECONDS = 900


class Unkeyable(Exception):
    """A message that cannot be traced to a cache item; only the DLQ holds it."""


@dataclass(frozen=True)
class Job:
    """The part of payload v1 that identifies the pair being resolved."""

    job_id: str
    station_key: str
    town: str
    payload: Mapping[str, Any]


@cache
def _results() -> CommuteResults:
    """Build the result store from the Lambda environment.

    Deliberately not in `storage.py`: those stores raise the HTTP contract's
    503 `ApiError`, and a worker has no response to shape. A missing table has
    to fail the message so the queue keeps it.
    """
    table_name = os.environ.get("TABLE_NAME", "").strip()
    if not table_name:
        raise RuntimeError("TABLE_NAME is not configured for the commute worker.")
    endpoint = os.environ.get("DYNAMODB_ENDPOINT_URL", "").strip() or None
    resource = boto3.resource("dynamodb", endpoint_url=endpoint)
    return CommuteResults(resource.Table(table_name))


def _max_receives() -> int:
    """The redrive count, so the final attempt can be recognised."""
    try:
        value = int(os.environ.get("COMMUTE_MAX_RECEIVES", "").strip())
    except ValueError:
        return DEFAULT_MAX_RECEIVES
    return value if value > 0 else DEFAULT_MAX_RECEIVES


def _text(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise Unkeyable(f"The job has no {field}.")
    return value


def _parse(body: Any) -> Job:
    """Read the identity of a job, or refuse the message outright.

    Only the three fields that address the cache item are required here. A
    payload that is addressable but unroutable (no coordinates, no date) is a
    terminal result for that pair, not an unkeyable message, so those fields
    are validated by the routing call instead.
    """
    if not isinstance(body, str):
        raise Unkeyable("The message has no body.")
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise Unkeyable("The message body is not JSON.") from exc
    if not isinstance(payload, dict):
        raise Unkeyable("The message body is not an object.")
    if payload.get("schemaVersion") != 1:
        raise Unkeyable(
            f"Unsupported payload version {payload.get('schemaVersion')!r}."
        )
    return Job(
        job_id=_text(payload, "jobId"),
        station_key=_text(payload, "stationKey"),
        town=_text(payload, "town"),
        payload=payload,
    )


def _receives(record: Mapping[str, Any]) -> int:
    """How many times SQS has delivered this message, counting this one."""
    attributes = record.get("attributes")
    raw = (
        attributes.get("ApproximateReceiveCount")
        if isinstance(attributes, dict)
        else None
    )
    try:
        return max(1, int(raw))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1


def _route(job: Job) -> Route:
    return route(
        job.payload.get("origin"),
        job.payload.get("destination"),
        routing_date=job.payload.get("routingDate"),
        routing_time=job.payload.get("routingTime"),
    )


def _fields(job: Job, attempts: int) -> dict[str, Any]:
    return {
        "jobId": job.job_id,
        "stationKey": job.station_key,
        "town": job.town,
        "attempts": attempts,
    }


def _terminal(
    results: CommuteResults,
    job: Job,
    exc: RoutingError,
    *,
    retry_after_seconds: int,
    attempts: int,
) -> None:
    written = results.store_unavailable(
        job.station_key,
        job.town,
        job.job_id,
        error=exc.code,
        retry_after_seconds=retry_after_seconds,
        attempts=attempts,
    )
    logger.warning(
        "Commute pair closed without a route"
        if written
        else "A newer claim or result owns this pair; terminal write skipped",
        extra={**_fields(job, attempts), "routingError": exc.code, "reason": str(exc)},
    )


def _process(
    record: Mapping[str, Any], results: CommuteResults, max_receives: int
) -> bool:
    """Resolve one message. True asks the queue to deliver it again."""
    attempts = _receives(record)
    try:
        job = _parse(record.get("body"))
    except Unkeyable as exc:
        # Nothing here addresses a cache item, so no pair can be closed. The
        # message is kept failing so the DLQ preserves it for inspection; the
        # claim's lease is what lets the pair recover meanwhile.
        logger.error("Unusable commute job", extra={"reason": str(exc)})
        return True

    try:
        resolved = _route(job)
    except RoutingUnroutable as exc:
        # The pair, or the request we built for it: no delay changes either.
        _terminal(
            results,
            job,
            exc,
            retry_after_seconds=UNROUTABLE_RETRY_SECONDS,
            attempts=attempts,
        )
        return False
    except RoutingError as exc:
        if attempts < max_receives:
            logger.warning(
                "Routing failed; returning the job to the queue",
                extra={**_fields(job, attempts), "routingError": exc.code},
            )
            return True
        _terminal(
            results,
            job,
            exc,
            retry_after_seconds=TRANSIENT_RETRY_SECONDS,
            attempts=attempts,
        )
        return False

    if results.store_ok(job.station_key, job.town, job.job_id, resolved, attempts):
        logger.info(
            "Commute pair resolved",
            extra={
                **_fields(job, attempts),
                "minutes": resolved.minutes,
                "itineraries": resolved.itineraries,
                "shortestWasFirst": resolved.shortest_was_first,
            },
        )
    else:
        logger.info(
            "A newer claim or result owns this pair; result discarded",
            extra=_fields(job, attempts),
        )
    return False


@logger.inject_lambda_context
def handler(event: dict[str, Any], context: LambdaContext) -> dict[str, Any]:
    """Resolve the batch, reporting only the messages that need another go."""
    results = _results()
    max_receives = _max_receives()
    failures: list[dict[str, str]] = []
    for record in event.get("Records") or []:
        message_id = str(record.get("messageId", ""))
        try:
            retry = _process(record, results, max_receives)
        except Exception:
            # A completion write that fails must not delete its message, and
            # one bad record must not drop the rest of the batch.
            logger.exception("Commute job failed", extra={"messageId": message_id})
            retry = True
        if retry:
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}
