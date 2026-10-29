"""The queued commute worker (#15) against Moto, one pair per message.

Every completion here goes through contract A9's fence (`jobId` plus
`status = pending`), so the cases that matter are the ones where the fence
refuses: a duplicate SQS delivery, and a lease that a newer claim has taken
over. Both are normal outcomes, so neither may fail the message.

Retries are the queue's, not this handler's: a transient failure is reported
as a batch item failure until `ApproximateReceiveCount` reaches the redrive
count, and the final receive writes a terminal `unavailable` itself so the DLQ
keeps only what the handler could not account for.
"""

import json
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws
from mypy_boto3_dynamodb.service_resource import Table

from flatsplit_api import routing
from flatsplit_api.commute_results import CommuteResults
from flatsplit_api.handlers import commute_worker
from flatsplit_api.handlers.commute_worker import handler
from flatsplit_api.onemap import OneMapUnavailable
from flatsplit_api.ranking import (
    Commute,
    MemberInput,
    RentSummary,
    rank_towns,
)
from flatsplit_api.routing import (
    SOURCE,
    Route,
    RoutingCredential,
    RoutingRejected,
    RoutingRetryable,
    RoutingUnroutable,
)

STATION = "KENT_RIDGE"
TOWN = "QUEENSTOWN"
PROFILE = "pt-v1:2026-10"
KEY = {"pk": f"COMMUTE#{STATION}", "sk": f"TOWN#{TOWN}"}
NOW = datetime(2026, 10, 20, 8, 30, tzinfo=UTC)
ROUTE = Route(
    minutes=30.5, transfers=2, walk_minutes=5.0, itineraries=3, shortest_was_first=False
)
CONTEXT = SimpleNamespace(
    function_name="commute-worker-test",
    memory_limit_in_mb=256,
    invoked_function_arn="local",
    aws_request_id="commute-worker-test",
)


@dataclass
class Routes:
    """A stand-in for the routing call that records what the worker asked."""

    result: Route | Exception = ROUTE
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, origin: Any, destination: Any, **kwargs: Any) -> Route:
        self.calls.append({"origin": origin, "destination": destination, **kwargs})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def table() -> Iterator[Table]:
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name="ap-southeast-1")
        yield resource.create_table(
            TableName="commute-worker-test",
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


@pytest.fixture
def routes(monkeypatch: pytest.MonkeyPatch) -> Routes:
    stub = Routes()
    monkeypatch.setattr(commute_worker, "route", stub)
    return stub


@pytest.fixture
def store(table: Table, monkeypatch: pytest.MonkeyPatch) -> CommuteResults:
    results = CommuteResults(table, clock=lambda: NOW)
    monkeypatch.setattr(commute_worker, "_results", lambda: results)
    return results


def claim(table: Table, **attributes: Any) -> dict[str, Any]:
    """The item the producer leaves behind: a pending claim under a lease."""
    item: dict[str, Any] = {
        **KEY,
        "status": "pending",
        "jobId": "job-1",
        "routingProfileVersion": PROFILE,
        "routingDate": "2026-10-21",
        "routingTime": "08:30:00",
        "attempts": 0,
        "leaseExpiresAt": int(NOW.timestamp()) + 900,
        **attributes,
    }
    table.put_item(Item=item)
    return item


def payload(**overrides: Any) -> dict[str, Any]:
    """Payload v1, exactly as `commute_jobs.ensure` sends it."""
    return {
        "schemaVersion": 1,
        "jobId": "job-1",
        "stationKey": STATION,
        "town": TOWN,
        "origin": {"lat": 1.29455, "lng": 103.806077},
        "destination": {"lat": 1.2936, "lng": 103.7845},
        "routingProfileVersion": PROFILE,
        "routingDate": "2026-10-21",
        "routingTime": "08:30:00",
        "leaseExpiresAt": int(NOW.timestamp()) + 900,
        **overrides,
    }


def record(
    body: Any = None,
    *,
    receives: int = 1,
    message_id: str = "message-1",
    **overrides: Any,
) -> dict[str, Any]:
    raw = json.dumps(payload(**overrides)) if body is None else body
    return {
        "messageId": message_id,
        "body": raw,
        "attributes": {"ApproximateReceiveCount": str(receives)},
    }


def run(*records: dict[str, Any]) -> list[str]:
    response = handler({"Records": list(records)}, CONTEXT)  # type: ignore[arg-type]
    return [failure["itemIdentifier"] for failure in response["batchItemFailures"]]


def item(table: Table) -> dict[str, Any]:
    stored = table.get_item(Key=KEY, ConsistentRead=True).get("Item")
    assert stored is not None
    return stored


@pytest.mark.parametrize(
    ("response", "code"),
    [
        ({"error": "Invalid token"}, "CREDENTIAL_UNAVAILABLE"),
        ({"error": "Routing service unavailable"}, "ROUTING_UNAVAILABLE"),
        ({}, "ROUTING_UNAVAILABLE"),
    ],
)
def test_success_status_errors_retry_then_use_transient_terminal_accounting(
    table: Table,
    store: CommuteResults,
    monkeypatch: pytest.MonkeyPatch,
    response: dict[str, Any],
    code: str,
) -> None:
    def upstream(origin: Any, destination: Any, **kwargs: Any) -> Route:
        return routing.route(
            origin, destination, **kwargs, transport=lambda _: response
        )

    monkeypatch.setattr(commute_worker, "route", upstream)
    claim(table)
    assert run(record(receives=1)) == ["message-1"]
    assert item(table)["status"] == "pending"
    assert run(record(receives=3)) == []
    result = item(table)
    assert result["status"] == "unavailable"
    assert result["error"] == code
    assert int(result["retryAfter"]) == int(NOW.timestamp()) + 900
    assert "minutes" not in result


def test_a_routed_pair_is_recorded_once_and_the_message_is_deleted(
    table: Table, store: CommuteResults, routes: Routes
) -> None:
    claim(table)
    assert run(record()) == []
    stored = item(table)
    assert stored["status"] == "ok"
    assert stored["minutes"] == Decimal("30.5")  # Fractional minutes survive.
    assert stored["transfers"] == 2
    assert stored["walkMinutes"] == Decimal("5.0")
    assert stored["itineraries"] == 3
    assert stored["shortestWasFirst"] is False
    assert stored["computedAt"] == NOW.isoformat()
    assert stored["source"] == SOURCE
    assert stored["attempts"] == 1  # Taken from the receive count, not a write.
    # The claim's working state is gone and the baseline it belongs to is intact.
    assert "leaseExpiresAt" not in stored
    assert "error" not in stored and "retryAfter" not in stored
    assert stored["routingProfileVersion"] == PROFILE
    assert stored["routingDate"] == "2026-10-21"
    assert stored["routingTime"] == "08:30:00"


def test_the_pair_is_routed_with_the_points_the_producer_sent(
    table: Table, store: CommuteResults, routes: Routes
) -> None:
    claim(table)
    assert run(record()) == []
    assert routes.calls == [
        {
            "origin": {"lat": 1.29455, "lng": 103.806077},
            "destination": {"lat": 1.2936, "lng": 103.7845},
            "routing_date": "2026-10-21",
            "routing_time": "08:30:00",
        }
    ]


def test_each_message_is_routed_exactly_once(
    table: Table, store: CommuteResults, routes: Routes
) -> None:
    claim(table)
    run(record())
    assert len(routes.calls) == 1


def test_a_duplicate_delivery_does_not_overwrite_the_result(
    table: Table, store: CommuteResults, routes: Routes
) -> None:
    claim(table)
    run(record())
    first = item(table)
    routes.result = Route(
        minutes=99.0,
        transfers=0,
        walk_minutes=0.0,
        itineraries=1,
        shortest_was_first=True,
    )
    # A redelivery after the visibility timeout must not be a failure either.
    assert run(record(receives=2)) == []
    assert item(table) == first


def test_a_newer_claim_keeps_the_pair_and_the_late_result_is_discarded(
    table: Table, store: CommuteResults, routes: Routes
) -> None:
    claim(table, jobId="job-2")  # The lease expired and a search reclaimed it.
    assert run(record()) == []
    stored = item(table)
    assert stored["status"] == "pending"
    assert stored["jobId"] == "job-2"
    assert "minutes" not in stored


def test_a_result_for_a_pair_that_no_longer_exists_is_not_resurrected(
    table: Table, store: CommuteResults, routes: Routes
) -> None:
    """A send that failed is rolled back; its in-flight message must not undo that."""
    assert run(record()) == []
    assert table.get_item(Key=KEY, ConsistentRead=True).get("Item") is None


def test_an_already_finished_pair_is_left_alone(
    table: Table, store: CommuteResults, routes: Routes
) -> None:
    claim(table, status="ok", minutes=Decimal("12.0"))
    assert run(record()) == []
    assert item(table)["minutes"] == Decimal("12.0")


def test_no_route_closes_the_pair_for_a_day_without_a_minute_figure(
    table: Table, store: CommuteResults, routes: Routes
) -> None:
    claim(table)
    routes.result = RoutingUnroutable("no itinerary")
    assert run(record()) == []  # Terminal on the first receive: no retry at all.
    stored = item(table)
    assert stored["status"] == "unavailable"
    assert stored["error"] == "NO_ROUTE"
    # A day: the monthly baseline cannot have changed sooner.
    assert stored["retryAfter"] == int(NOW.timestamp()) + 86400
    assert "minutes" not in stored
    assert "leaseExpiresAt" not in stored
    assert stored["attempts"] == 1


def test_a_reclaimed_pair_keeps_no_numbers_from_the_attempt_that_failed(
    table: Table, store: CommuteResults, routes: Routes
) -> None:
    claim(
        table,
        minutes=Decimal("41.0"),
        transfers=1,
        walkMinutes=Decimal("3.0"),
        itineraries=2,
        shortestWasFirst=True,
    )
    routes.result = RoutingUnroutable("no itinerary")
    run(record())
    stored = item(table)
    assert stored["status"] == "unavailable"
    for attribute in ["minutes", "transfers", "walkMinutes", "itineraries"]:
        assert attribute not in stored


def test_a_request_we_built_wrongly_is_terminal_with_its_own_code(
    table: Table, store: CommuteResults, routes: Routes
) -> None:
    claim(table)
    routes.result = RoutingRejected("numItineraries must be between 1 and 3")
    assert run(record()) == []
    stored = item(table)
    assert stored["status"] == "unavailable"
    assert stored["error"] == "INVALID_ROUTE_REQUEST"
    assert stored["retryAfter"] == int(NOW.timestamp()) + 86400


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (RoutingRetryable("throttled"), "ROUTING_UNAVAILABLE"),
        (RoutingCredential("token expired"), "CREDENTIAL_UNAVAILABLE"),
    ],
)
def test_a_transient_failure_returns_to_the_queue_until_the_last_receive(
    table: Table,
    store: CommuteResults,
    routes: Routes,
    failure: Exception,
    code: str,
) -> None:
    claim(table)
    routes.result = failure
    for receives in [1, 2]:
        assert run(record(receives=receives)) == ["message-1"]
        stored = item(table)
        # Still claimed: the queue's visibility timeout is the backoff.
        assert stored["status"] == "pending"
        assert stored["attempts"] == 0

    assert run(record(receives=3)) == []  # The DLQ gets nothing to explain.
    stored = item(table)
    assert stored["status"] == "unavailable"
    assert stored["error"] == code
    # Short: throttling passes and a rotated token works at once.
    assert stored["retryAfter"] == int(NOW.timestamp()) + 900
    assert stored["attempts"] == 3


def test_a_pair_just_over_a_limit_is_not_rounded_into_feasibility(
    table: Table, store: CommuteResults, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The seam #18/#22 read across: what the worker stores, ranking compares.

    1,802 s is 30.03 minutes. Stored as 30.0 it would make `maxCommute: 30`
    feasible and put the town in the results, so the record keeps the whole
    value and only a reader rounds it.
    """

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def read(self) -> bytes:
            itinerary = {"duration": 1802, "transfers": 1, "walkTime": 300}
            return json.dumps({"plan": {"itineraries": [itinerary]}}).encode()

    # The real routing path, so the rounding under test is the one in
    # `_shortest` rather than a value this test chose.
    monkeypatch.setattr(routing, "resolve_token", lambda: "token")
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda request, timeout=None: Response()
    )
    claim(table)

    assert run(record()) == []
    stored = item(table)
    assert stored["status"] == "ok"
    minutes = float(stored["minutes"])
    assert minutes > 30

    member = MemberInput("a", "A", 2000, 30, STATION)
    rent = RentSummary(
        median=2000,
        p25=1800,
        p75=2200,
        medianCi95Low=1940,
        medianCi95High=2060,
        count=400,
        qualityStatus="USABLE",
    )
    ranking = rank_towns(
        [member], [TOWN], {TOWN: rent}, {(STATION, TOWN): Commute("ok", minutes)}
    )

    assert ranking.ranked == []
    [reason] = ranking.excluded[0].reasons
    assert (reason.code, reason.memberId) == ("OVER_COMMUTE", "a")


def test_a_credential_that_cannot_be_loaded_still_closes_the_pair(
    table: Table, store: CommuteResults, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real routing path, with an unreadable secret: #72's shape exactly.

    No routing stub here, because the defect was that `resolve_token`'s own
    error is not a `RoutingError`: it escaped `_process`, so the final receive
    reported a batch item failure and left the pair pending with no
    `retryAfter` for a DLQ consumer to interpret.
    """

    def unavailable() -> str:
        raise OneMapUnavailable("The OneMap credential could not be loaded.")

    monkeypatch.setattr(routing, "resolve_token", unavailable)
    claim(table)

    for receives in [1, 2]:
        assert run(record(receives=receives)) == ["message-1"]
        assert item(table)["status"] == "pending"

    assert run(record(receives=3)) == []
    stored = item(table)
    assert stored["status"] == "unavailable"
    assert stored["error"] == "CREDENTIAL_UNAVAILABLE"
    assert stored["retryAfter"] == int(NOW.timestamp()) + 900
    assert stored["attempts"] == 3
    assert "minutes" not in stored


def test_the_redrive_count_is_read_from_the_environment(
    table: Table, store: CommuteResults, routes: Routes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COMMUTE_MAX_RECEIVES", "5")
    claim(table)
    routes.result = RoutingRetryable("throttled")
    assert run(record(receives=3)) == ["message-1"]
    assert item(table)["status"] == "pending"
    assert run(record(receives=5)) == []
    assert item(table)["status"] == "unavailable"


@pytest.mark.parametrize("value", ["", "zero", "0", "-1"])
def test_an_unusable_redrive_count_falls_back_to_the_queue_default(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("COMMUTE_MAX_RECEIVES", value)
    assert commute_worker._max_receives() == commute_worker.DEFAULT_MAX_RECEIVES == 3


@pytest.mark.parametrize("receives", [None, "not-a-number", "0"])
def test_a_missing_receive_count_is_treated_as_the_first_delivery(
    table: Table, store: CommuteResults, routes: Routes, receives: Any
) -> None:
    claim(table)
    routes.result = RoutingRetryable("throttled")
    message = record()
    message["attributes"] = (
        {} if receives is None else {"ApproximateReceiveCount": receives}
    )
    assert run(message) == ["message-1"]  # Never terminal by accident.
    assert item(table)["status"] == "pending"


@pytest.mark.parametrize(
    "body",
    [
        None,
        "",
        "not json",
        "[]",
        '"a string"',
        json.dumps({"schemaVersion": 2, "jobId": "j", "stationKey": "s", "town": "t"}),
        json.dumps({"jobId": "job-1", "stationKey": STATION, "town": TOWN}),
        json.dumps({"schemaVersion": 1, "stationKey": STATION, "town": TOWN}),
        json.dumps({"schemaVersion": 1, "jobId": "job-1", "town": TOWN}),
        json.dumps({"schemaVersion": 1, "jobId": "job-1", "stationKey": STATION}),
        json.dumps(
            {"schemaVersion": 1, "jobId": " ", "stationKey": STATION, "town": TOWN}
        ),
    ],
)
def test_a_message_that_addresses_no_pair_is_kept_for_the_dead_letter_queue(
    table: Table, store: CommuteResults, routes: Routes, body: Any
) -> None:
    claim(table)
    message = record(body="" if body is None else body)
    if body is None:
        del message["body"]
    assert run(message) == ["message-1"]
    # Nothing was routed and nothing was written: the lease recovers the pair.
    assert routes.calls == []
    assert item(table)["status"] == "pending"


def test_a_payload_that_is_addressable_but_unroutable_closes_its_pair(
    table: Table, store: CommuteResults, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing date is a terminal answer about the pair, not an unkeyable message."""
    claim(table)
    assert run(record(routingDate=None)) == []
    stored = item(table)
    assert stored["status"] == "unavailable"
    assert stored["error"] == "INVALID_ROUTE_REQUEST"


def test_a_failed_completion_write_keeps_the_message(
    table: Table, store: CommuteResults, routes: Routes, monkeypatch: pytest.MonkeyPatch
) -> None:
    claim(table)

    def broken(**kwargs: Any) -> Any:
        raise ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException"}}, "UpdateItem"
        )

    monkeypatch.setattr(table, "update_item", broken)
    assert run(record()) == ["message-1"]
    assert item(table)["status"] == "pending"


def test_one_bad_record_does_not_drop_the_rest_of_the_batch(
    table: Table, store: CommuteResults, monkeypatch: pytest.MonkeyPatch
) -> None:
    for town in ["QUEENSTOWN", "CLEMENTI"]:
        table.put_item(
            Item={
                "pk": f"COMMUTE#{STATION}",
                "sk": f"TOWN#{town}",
                "status": "pending",
                "jobId": f"job-{town}",
                "routingProfileVersion": PROFILE,
                "attempts": 0,
            }
        )
    outcomes: dict[str, Route | Exception] = {
        "QUEENSTOWN": ROUTE,
        "CLEMENTI": RoutingRetryable("throttled"),
    }

    def route_the_job(job: commute_worker.Job) -> Route:
        outcome = outcomes[job.town]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(commute_worker, "_route", route_the_job)
    failures = run(
        record(message_id="ok-message", jobId="job-QUEENSTOWN"),
        record(message_id="retry-message", jobId="job-CLEMENTI", town="CLEMENTI"),
        record(message_id="unkeyable-message", body="not json"),
    )
    assert failures == ["retry-message", "unkeyable-message"]
    statuses = {
        town: table.get_item(
            Key={"pk": f"COMMUTE#{STATION}", "sk": f"TOWN#{town}"}, ConsistentRead=True
        )["Item"]["status"]
        for town in ["QUEENSTOWN", "CLEMENTI"]
    }
    assert statuses == {"QUEENSTOWN": "ok", "CLEMENTI": "pending"}


def test_an_empty_batch_is_answered_without_touching_anything(
    store: CommuteResults, routes: Routes
) -> None:
    assert handler({}, CONTEXT) == {"batchItemFailures": []}  # type: ignore[arg-type]
    assert handler({"Records": []}, CONTEXT) == {"batchItemFailures": []}  # type: ignore[arg-type]


def test_the_worker_refuses_to_start_without_a_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing table has to fail the message, so the queue keeps the job."""
    monkeypatch.delenv("TABLE_NAME", raising=False)
    commute_worker._results.cache_clear()  # It is cached for the container's life.
    with pytest.raises(RuntimeError, match="TABLE_NAME"):
        commute_worker._results()
