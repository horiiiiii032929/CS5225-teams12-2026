"""The shared OneMap call budget contract C7 requires.

`maxConcurrency: 3` bounds how many routing calls are *in flight*, not how
many happen per minute. Three busy workers at the measured cached-route p50 of
154 ms would permit roughly 1,100 calls/min, well past the 250/min C7
configures and the 300/min OneMap publishes, so concurrency alone cannot
enforce the budget: a queue of warm pairs is exactly the case where it fails.

Two things therefore share one counter:

- the worker's routing calls, which stop at `WORKER_CALLS`;
- `/places` lookups, which stop at `TOTAL_CALLS`.

The gap between them is the headroom C7 reserves for user lookups: a worker
backlog can spend 200 calls in a minute but never the last 50, so an
interactive destination search still has quota while a drain is running. One
fixed 60-second window per epoch minute, keyed in the shared table, is what
makes the budget hold *across containers* rather than per Lambda instance.

The reservation is taken before the call, so a call that fails still counts.
C7 says actual calls, and a 429 or a 500 has already reached OneMap.

Refusal is a normal outcome, not an error: the worker returns its message to
the queue, whose visibility timeout is the pacing, and a lookup gives up the
way it does for any upstream failure. A counter that is unreachable for some
other reason is treated differently by each caller, and deliberately: the
worker fails closed, because the queue will bring the pair back, while a
lookup proceeds, because the headroom above exists for it and a table hiccup
must not take down a user-facing read.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from decimal import Decimal
from functools import cache
from typing import TYPE_CHECKING

import boto3
from aws_lambda_powertools import Logger
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

logger = Logger(child=True)

#: C7's configured client guard, below OneMap's published 300/min quota.
TOTAL_CALLS = 250
#: Reserved for interactive `/places` lookups; the worker cannot spend these.
LOOKUP_HEADROOM = 50
#: What a drain may spend in one window.
WORKER_CALLS = TOTAL_CALLS - LOOKUP_HEADROOM
#: A fixed window, not a sliding one: one counter item per epoch minute.
WINDOW_SECONDS = 60
#: Long enough that a late reservation cannot land on an expired item.
WINDOW_TTL_SECONDS = 15 * 60

_NAMES = {"#calls": "calls", "#ttl": "ttl"}
_UPDATE = "ADD #calls :one SET #ttl = if_not_exists(#ttl, :ttl)"
_WITHIN = "attribute_not_exists(#calls) OR #calls < :ceiling"


class BudgetExhausted(Exception):
    """This window's share is spent; the caller decides what that means."""


class CallBudget:
    """A fixed-window call counter shared by every OneMap caller."""

    def __init__(
        self, table: Table, *, clock: Callable[[], float] | None = None
    ) -> None:
        self.table = table
        self._clock = clock or time.time

    def window(self) -> int:
        return int(self._clock() // WINDOW_SECONDS)

    def reserve(self, *, ceiling: int) -> int:
        """Claim one call below `ceiling`, returning the window's count.

        Raises `BudgetExhausted` when the window is full, and `ClientError`
        for anything else, so the caller can choose to fail closed or open.
        """
        window = self.window()
        try:
            response = self.table.update_item(
                Key={"pk": "RATE#ONEMAP", "sk": f"WINDOW#{window}"},
                UpdateExpression=_UPDATE,
                ConditionExpression=_WITHIN,
                ExpressionAttributeNames=_NAMES,
                ExpressionAttributeValues={
                    ":one": 1,
                    ":ceiling": ceiling,
                    ":ttl": int(window * WINDOW_SECONDS) + WINDOW_TTL_SECONDS,
                },
                ReturnValues="UPDATED_NEW",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                logger.warning(
                    "OneMap call budget reached for this window",
                    extra={"onemapWindow": window, "onemapCeiling": ceiling},
                )
                raise BudgetExhausted(
                    f"The OneMap call budget of {ceiling} per minute is spent."
                ) from exc
            raise
        calls = response.get("Attributes", {}).get("calls")
        return int(calls) if isinstance(calls, (int, float, Decimal)) else 1


def reserve(budget: CallBudget | None, *, ceiling: int) -> None:
    """Reserve a call when a budget is configured; a no-op when it is not.

    Local development and the unit suite run without the shared table, and
    the guard is a deployed control, so its absence is logged rather than
    turned into a failure that only ever fires off AWS.
    """
    if budget is None:
        logger.debug("No OneMap call budget is configured; call not counted")
        return
    budget.reserve(ceiling=ceiling)


@cache
def from_environment() -> CallBudget | None:
    """The shared counter, or None where no table is configured."""
    table_name = os.environ.get("TABLE_NAME", "").strip()
    if not table_name:
        return None
    endpoint = os.environ.get("DYNAMODB_ENDPOINT_URL", "").strip() or None
    resource = boto3.resource("dynamodb", endpoint_url=endpoint)
    return CallBudget(resource.Table(table_name))


def spend(ceiling: int) -> None:
    """Count one OneMap call against the shared window."""
    reserve(from_environment(), ceiling=ceiling)
