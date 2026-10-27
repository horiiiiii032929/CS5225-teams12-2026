"""The shared OneMap call budget (C7, #74 review P1).

`maxConcurrency` bounds in-flight calls, not calls per minute, so the
property under test is the one concurrency cannot give: a backlog of fast
responses stops at the worker's share and leaves the reserved headroom for an
interactive lookup, with the count shared across containers.
"""

import json
import urllib.request
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws
from mypy_boto3_dynamodb.service_resource import Table

from flatsplit_api import call_budget, onemap, routing
from flatsplit_api.call_budget import (
    TOTAL_CALLS,
    WORKER_CALLS,
    BudgetExhausted,
    CallBudget,
)
from flatsplit_api.commute_results import CommuteResults
from flatsplit_api.handlers import commute_worker
from flatsplit_api.onemap import OneMapRateLimited
from flatsplit_api.routing import RoutingRetryable

STATION = "KENT_RIDGE"
TOWN = "QUEENSTOWN"
NOW = 1_793_000_000.0
CONTEXT = SimpleNamespace(
    function_name="budget-test",
    memory_limit_in_mb=256,
    invoked_function_arn="local",
    aws_request_id="budget-test",
)


@pytest.fixture
def table() -> Iterator[Table]:
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name="ap-southeast-1")
        yield resource.create_table(
            TableName="budget-test",
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


def budget(table: Table, *, now: float = NOW) -> CallBudget:
    return CallBudget(table, clock=lambda: now)


def test_the_window_counts_every_reservation() -> None:
    assert WORKER_CALLS + call_budget.LOOKUP_HEADROOM == TOTAL_CALLS


def test_a_reservation_counts_and_the_ceiling_refuses(table: Table) -> None:
    shared = budget(table)
    assert [shared.reserve(ceiling=3) for _ in range(3)] == [1, 2, 3]
    with pytest.raises(BudgetExhausted):
        shared.reserve(ceiling=3)


def test_the_count_is_shared_between_containers(table: Table) -> None:
    """Two Lambda instances are two objects against one item."""
    first, second = budget(table), budget(table)
    first.reserve(ceiling=2)
    second.reserve(ceiling=2)
    with pytest.raises(BudgetExhausted):
        first.reserve(ceiling=2)


def test_the_next_window_starts_again(table: Table) -> None:
    budget(table).reserve(ceiling=1)
    with pytest.raises(BudgetExhausted):
        budget(table).reserve(ceiling=1)
    assert budget(table, now=NOW + 60).reserve(ceiling=1) == 1


def test_the_headroom_is_what_the_worker_cannot_spend(table: Table) -> None:
    """The C7 property: a full worker share still leaves a lookup its quota."""
    shared = budget(table)
    for _ in range(WORKER_CALLS):
        shared.reserve(ceiling=WORKER_CALLS)

    with pytest.raises(BudgetExhausted):
        shared.reserve(ceiling=WORKER_CALLS)

    for _ in range(call_budget.LOOKUP_HEADROOM):
        shared.reserve(ceiling=TOTAL_CALLS)
    with pytest.raises(BudgetExhausted):
        shared.reserve(ceiling=TOTAL_CALLS)


def test_a_full_window_returns_the_routing_job_to_the_queue(
    table: Table, monkeypatch: pytest.MonkeyPatch
) -> None:
    shared = budget(table)
    monkeypatch.setattr(call_budget, "from_environment", lambda: shared)
    for _ in range(WORKER_CALLS):
        shared.reserve(ceiling=WORKER_CALLS)
    monkeypatch.setattr(routing, "resolve_token", lambda: "token")
    called: list[Any] = []
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda request, timeout=None: called.append(request)
    )

    with pytest.raises(RoutingRetryable):
        routing.http_get({"routeType": "pt"})
    assert called == []  # Quota is not spent to be told it is spent.


def test_an_unreadable_counter_fails_the_routing_call_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unmetered quota is the worse outcome; the queue brings the pair back."""

    class Broken:
        def reserve(self, *, ceiling: int) -> int:
            raise ClientError(
                {"Error": {"Code": "ProvisionedThroughputExceededException"}},
                "UpdateItem",
            )

    monkeypatch.setattr(call_budget, "from_environment", lambda: Broken())
    monkeypatch.setattr(routing, "resolve_token", lambda: "token")
    with pytest.raises(RoutingRetryable, match="budget"):
        routing.http_get({"routeType": "pt"})


def test_a_full_window_throttles_a_lookup(
    table: Table, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`/places` may use the headroom, and is throttled only at the top."""
    shared = budget(table)
    monkeypatch.setattr(call_budget, "from_environment", lambda: shared)
    for _ in range(TOTAL_CALLS):
        shared.reserve(ceiling=TOTAL_CALLS)
    monkeypatch.setattr(onemap, "resolve_token", lambda: "token")

    with pytest.raises(OneMapRateLimited):
        onemap.http_get("/api/common/elastic/search", {"searchVal": "kent ridge"})


def test_an_unreadable_counter_lets_a_lookup_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reserved headroom is what makes failing open acceptable here."""

    class Broken:
        def reserve(self, *, ceiling: int) -> int:
            raise ClientError({"Error": {"Code": "InternalServerError"}}, "UpdateItem")

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"found": 0, "results": []}).encode()

    monkeypatch.setattr(call_budget, "from_environment", lambda: Broken())
    monkeypatch.setattr(onemap, "resolve_token", lambda: "token")
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda request, timeout=None: Response()
    )

    assert onemap.http_get("/api/common/elastic/search", {"searchVal": "x"}) == {
        "found": 0,
        "results": [],
    }


def test_a_backlog_of_fast_responses_stops_at_the_worker_share(
    table: Table, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case `maxConcurrency` cannot bound: instant replies, one window.

    Every message is routable and answers immediately, so nothing but the
    budget can stop the drain. The worker spends its 200 and returns the rest
    to the queue, and the 50 reserved calls are still there for a lookup.
    """
    shared = budget(table)
    monkeypatch.setattr(call_budget, "from_environment", lambda: shared)
    monkeypatch.setattr(routing, "resolve_token", lambda: "token")
    monkeypatch.setattr(commute_worker, "_results", lambda: CommuteResults(table))
    calls: list[Any] = []

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def read(self) -> bytes:
            itinerary = {"duration": 1830, "transfers": 1, "walkTime": 300}
            return json.dumps({"plan": {"itineraries": [itinerary]}}).encode()

    def instant(request: Any, timeout: float | None = None) -> Response:
        calls.append(request)
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", instant)

    backlog = WORKER_CALLS + 60
    records = []
    for index in range(backlog):
        town = f"TOWN{index}"
        table.put_item(
            Item={
                "pk": f"COMMUTE#{STATION}",
                "sk": f"TOWN#{town}",
                "status": "pending",
                "jobId": f"job-{index}",
                "attempts": 0,
            }
        )
        records.append(
            {
                "messageId": f"message-{index}",
                "body": json.dumps(
                    {
                        "schemaVersion": 1,
                        "jobId": f"job-{index}",
                        "stationKey": STATION,
                        "town": town,
                        "origin": {"lat": 1.29455, "lng": 103.806077},
                        "destination": {"lat": 1.2936, "lng": 103.7845},
                        "routingDate": "2026-10-28",
                        "routingTime": "08:30:00",
                    }
                ),
                "attributes": {"ApproximateReceiveCount": "1"},
            }
        )

    response = commute_worker.handler({"Records": records}, CONTEXT)  # type: ignore[arg-type]

    assert len(calls) == WORKER_CALLS
    assert len(response["batchItemFailures"]) == backlog - WORKER_CALLS
    # The headroom survived a drain that would otherwise have spent it.
    assert shared.reserve(ceiling=TOTAL_CALLS) == WORKER_CALLS + 1
