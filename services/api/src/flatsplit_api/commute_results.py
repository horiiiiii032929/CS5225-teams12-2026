"""The only write that ends a commute claim (contract A9).

`commute_jobs.py` owns the claim; this owns its completion. Every update is
conditioned on the claim's `jobId` and on the pair still being `pending`, so a
duplicate SQS delivery, a slow attempt whose lease has since been reclaimed,
and an already-finished pair are all left untouched. A refused write is a
normal outcome, not an error: it means the message has nothing left to do.

Routing metadata written by the producer (`routingProfileVersion`,
`routingDate`, `routingTime`) is never touched, so a reader can still tell
which baseline a cached minute belongs to.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from flatsplit_api.routing import SOURCE, Route

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

#: Every attribute is aliased. DynamoDB rejects reserved words in expressions
#: and Moto does not, so an unaliased name would pass tests and fail deployed.
_NAMES = {
    "#status": "status",
    "#jobId": "jobId",
    "#attempts": "attempts",
    "#minutes": "minutes",
    "#transfers": "transfers",
    "#walkMinutes": "walkMinutes",
    "#itineraries": "itineraries",
    "#shortestWasFirst": "shortestWasFirst",
    "#computedAt": "computedAt",
    "#source": "source",
    "#error": "error",
    "#retryAfter": "retryAfter",
    "#leaseExpiresAt": "leaseExpiresAt",
}

_OK = (
    "SET #status = :ok, #minutes = :minutes, #transfers = :transfers, "
    "#walkMinutes = :walkMinutes, #itineraries = :itineraries, "
    "#shortestWasFirst = :shortestWasFirst, #computedAt = :computedAt, "
    "#source = :source, #attempts = :attempts "
    "REMOVE #error, #retryAfter, #leaseExpiresAt"
)
_UNAVAILABLE = (
    "SET #status = :unavailable, #error = :error, #retryAfter = :retryAfter, "
    "#computedAt = :computedAt, #source = :source, #attempts = :attempts "
    # A reclaimed pair keeps the previous attempt's numbers. Removing them
    # stops an unavailable pair from carrying a minute figure at all.
    "REMOVE #minutes, #transfers, #walkMinutes, #itineraries, "
    "#shortestWasFirst, #leaseExpiresAt"
)


class CommuteResults:
    def __init__(
        self, table: Table, *, clock: Callable[[], datetime] | None = None
    ) -> None:
        self.table = table
        self._clock = clock or (lambda: datetime.now(UTC))

    def _write(
        self,
        station_key: str,
        town: str,
        job_id: str,
        expression: str,
        values: dict[str, Any],
    ) -> bool:
        """Apply a fenced completion; False when another claim or result won.

        `update_item` creates a missing item, so the condition also stops a
        claim that was rolled back after a failed send from being resurrected
        by its own in-flight message.
        """
        try:
            self.table.update_item(
                Key={"pk": f"COMMUTE#{station_key}", "sk": f"TOWN#{town}"},
                UpdateExpression=expression,
                ConditionExpression="#jobId = :jobId AND #status = :pending",
                ExpressionAttributeNames=_NAMES,
                ExpressionAttributeValues={
                    ":jobId": job_id,
                    ":pending": "pending",
                    **values,
                },
            )
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            return False
        return True

    def store_ok(
        self, station_key: str, town: str, job_id: str, route: Route, attempts: int
    ) -> bool:
        """Record minutes for a routed pair. Fractional minutes are retained."""
        return self._write(
            station_key,
            town,
            job_id,
            _OK,
            {
                ":ok": "ok",
                # Decimal, because DynamoDB stores no binary floating point.
                ":minutes": Decimal(str(route.minutes)),
                ":transfers": route.transfers,
                ":walkMinutes": Decimal(str(route.walk_minutes)),
                ":itineraries": route.itineraries,
                ":shortestWasFirst": route.shortest_was_first,
                ":computedAt": self._clock().astimezone(UTC).isoformat(),
                ":source": SOURCE,
                ":attempts": attempts,
            },
        )

    def store_unavailable(
        self,
        station_key: str,
        town: str,
        job_id: str,
        *,
        error: str,
        retry_after_seconds: int,
        attempts: int,
    ) -> bool:
        """Close a pair without a route. `retryAfter` is an epoch second (A9)."""
        now = self._clock().astimezone(UTC)
        return self._write(
            station_key,
            town,
            job_id,
            _UNAVAILABLE,
            {
                ":unavailable": "unavailable",
                ":error": error,
                ":retryAfter": int(now.timestamp()) + retry_after_seconds,
                ":computedAt": now.isoformat(),
                ":source": SOURCE,
                ":attempts": attempts,
            },
        )
