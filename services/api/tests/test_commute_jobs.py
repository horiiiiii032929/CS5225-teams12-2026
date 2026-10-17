"""Producer claims and enqueue recovery against Moto, without a live worker."""

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import boto3
import pytest
from moto import mock_aws
from mypy_boto3_dynamodb.service_resource import Table

from flatsplit_api.commute_jobs import CommuteJobs, routing_profile
from flatsplit_api.models import Station

PROFILE = "pt-v1:2026-10"
TOWN = "QUEENSTOWN"
POINT = {"lat": Decimal("1.29455"), "lon": Decimal("103.806077"), "routable": True}
KEY = {"pk": "COMMUTE#KENT_RIDGE", "sk": "TOWN#QUEENSTOWN"}


@dataclass
class Clock:
    now: datetime = datetime(2026, 10, 16, 16, 30, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def station() -> Station:
    return Station(
        stationKey="KENT_RIDGE",
        codes=["CC24"],
        name="Kent Ridge",
        lat=1.2936,
        lng=103.7845,
        snapMetres=900,
        snapWarning=True,
    )


@pytest.fixture
def table() -> Iterator[Table]:
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name="ap-southeast-1")
        yield resource.create_table(
            TableName="commute-jobs-test",
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


def seed(table: Table, clock: Clock, **attributes: Any) -> dict[str, Any]:
    item = {
        **KEY,
        "status": "pending",
        "jobId": "previous-claim",
        "routingProfileVersion": PROFILE,
        "leaseExpiresAt": int(clock.now.timestamp()) + 900,
        "attempts": 2,
        **attributes,
    }
    table.put_item(Item=item)
    return item


def interleave(
    table: Table, monkeypatch: pytest.MonkeyPatch, action: Callable[[], Any]
) -> None:
    """Commit a winner after the supplied cache read, before the claim write."""
    original = table.put_item
    fired = False

    def put(**kwargs: Any) -> Any:
        nonlocal fired
        if not fired:
            fired = True
            action()
        return original(**kwargs)

    monkeypatch.setattr(table, "put_item", put)


def test_claim_contains_pinned_routing_inputs_without_member_data(
    table: Table, station: Station, clock: Clock
) -> None:
    sent: list[dict[str, Any]] = []
    jobs = CommuteJobs(table, sent.append, clock=clock)
    claimed = jobs.ensure(station, TOWN, POINT, PROFILE, None)

    assert claimed["status"] == "pending"
    assert claimed["attempts"] == 0
    assert claimed["leaseExpiresAt"] == int(clock.now.timestamp()) + 900
    assert table.get_item(Key=KEY, ConsistentRead=True)["Item"] == claimed
    assert sent == [
        {
            "schemaVersion": 1,
            "jobId": claimed["jobId"],
            "stationKey": "KENT_RIDGE",
            "town": "QUEENSTOWN",
            "origin": {"lat": 1.29455, "lng": 103.806077},
            "destination": {"lat": 1.2936, "lng": 103.7845},
            "routingProfileVersion": PROFILE,
            "routingDate": "2026-10-19",
            "routingTime": "08:30:00",
            "leaseExpiresAt": claimed["leaseExpiresAt"],
        }
    ]
    assert json.loads(json.dumps(sent[0]))["origin"] == {
        "lat": 1.29455,
        "lng": 103.806077,
    }


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 9, 30, 15, 59, tzinfo=UTC), "pt-v1:2026-09"),
        (datetime(2026, 9, 30, 16, 0, tzinfo=UTC), "pt-v1:2026-10"),
        (datetime(2026, 12, 31, 16, 0, tzinfo=UTC), "pt-v1:2027-01"),
    ],
)
def test_monthly_profile_uses_singapore_calendar(now: datetime, expected: str) -> None:
    assert routing_profile(now) == expected


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 10, 15, 0, 0, tzinfo=UTC), "2026-10-16"),
        (datetime(2026, 10, 16, 0, 0, tzinfo=UTC), "2026-10-19"),
        (datetime(2026, 10, 17, 0, 0, tzinfo=UTC), "2026-10-19"),
        (datetime(2026, 10, 18, 0, 0, tzinfo=UTC), "2026-10-19"),
    ],
)
def test_job_uses_next_singapore_weekday(
    table: Table, station: Station, now: datetime, expected: str
) -> None:
    sent: list[dict[str, Any]] = []
    jobs = CommuteJobs(table, sent.append, clock=lambda: now)
    item = jobs.ensure(station, TOWN, POINT, PROFILE, None)
    assert item["routingDate"] == expected
    assert sent[0]["routingDate"] == expected


@pytest.mark.parametrize("supply_existing", [True, False])
def test_active_claim_is_deduplicated_even_with_stale_missing_read(
    table: Table, station: Station, clock: Clock, supply_existing: bool
) -> None:
    sent: list[dict[str, Any]] = []
    jobs = CommuteJobs(table, sent.append, clock=clock)
    first = jobs.ensure(station, TOWN, POINT, PROFILE, None)
    current = jobs.ensure(
        station, TOWN, POINT, PROFILE, first if supply_existing else None
    )
    assert current == first
    assert [payload["jobId"] for payload in sent] == [first["jobId"]]
    assert table.get_item(Key=KEY, ConsistentRead=True)["Item"] == first


@pytest.mark.parametrize("status", ["pending", "ok", "unavailable"])
def test_conditional_loser_returns_winner_without_sending(
    table: Table,
    station: Station,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    sent: list[dict[str, Any]] = []
    jobs = CommuteJobs(table, sent.append, clock=clock)
    winner: dict[str, Any] = {
        **KEY,
        "jobId": "winner",
        "status": status,
        "routingProfileVersion": PROFILE,
        "leaseExpiresAt": int(clock.now.timestamp()) + 900,
        "retryAfter": int(clock.now.timestamp()) + 3600,
    }
    interleave(table, monkeypatch, lambda: table.put_item(Item=winner))
    assert jobs.ensure(station, TOWN, POINT, PROFILE, None) == winner
    assert sent == []
    assert table.get_item(Key=KEY, ConsistentRead=True)["Item"] == winner


@pytest.mark.parametrize("lease_offset", [-1, 0])
def test_expired_pending_lease_gets_fresh_claim(
    table: Table, station: Station, clock: Clock, lease_offset: int
) -> None:
    previous = seed(
        table, clock, leaseExpiresAt=int(clock.now.timestamp()) + lease_offset
    )
    sent: list[dict[str, Any]] = []
    jobs = CommuteJobs(table, sent.append, clock=clock, lease_seconds=120)
    current = jobs.ensure(station, TOWN, POINT, PROFILE, previous)
    assert current["jobId"] != previous["jobId"]
    assert current["status"] == "pending"
    assert current["attempts"] == 0
    assert current["leaseExpiresAt"] == int(clock.now.timestamp()) + 120
    assert [payload["jobId"] for payload in sent] == [current["jobId"]]


@pytest.mark.parametrize("supply_existing", [True, False])
def test_valid_ok_result_is_never_requeued_on_repeat(
    table: Table, station: Station, clock: Clock, supply_existing: bool
) -> None:
    previous = seed(
        table,
        clock,
        status="ok",
        minutes=24,
        leaseExpiresAt=int(clock.now.timestamp()) - 1,
    )
    sent: list[dict[str, Any]] = []
    jobs = CommuteJobs(table, sent.append, clock=clock)
    assert (
        jobs.ensure(
            station,
            TOWN,
            POINT,
            PROFILE,
            previous if supply_existing else None,
            retry_unavailable=True,
        )
        == previous
    )
    assert sent == []


@pytest.mark.parametrize(
    ("explicit", "retry_offset", "requeued"),
    [(False, -1, False), (False, 0, False), (True, 1, False), (True, 0, True)],
)
def test_unavailable_retries_only_on_explicit_repeat_after_delay(
    table: Table,
    station: Station,
    clock: Clock,
    explicit: bool,
    retry_offset: int,
    requeued: bool,
) -> None:
    previous = seed(
        table,
        clock,
        status="unavailable",
        retryAfter=int(clock.now.timestamp()) + retry_offset,
    )
    sent: list[dict[str, Any]] = []
    jobs = CommuteJobs(table, sent.append, clock=clock)
    current = jobs.ensure(
        station, TOWN, POINT, PROFILE, previous, retry_unavailable=explicit
    )
    if requeued:
        assert current["status"] == "pending"
        assert current["jobId"] != previous["jobId"]
        assert [payload["jobId"] for payload in sent] == [current["jobId"]]
    else:
        assert current == previous
        assert sent == []
    assert table.get_item(Key=KEY, ConsistentRead=True)["Item"] == current


@pytest.mark.parametrize("status", ["ok", "pending", "unavailable"])
def test_older_profile_is_refreshed_even_for_resolved_or_active_items(
    table: Table, station: Station, clock: Clock, status: str
) -> None:
    previous = seed(
        table,
        clock,
        status=status,
        routingProfileVersion="pt-v1:2026-09",
        retryAfter=int(clock.now.timestamp()) + 3600,
    )
    sent: list[dict[str, Any]] = []
    jobs = CommuteJobs(table, sent.append, clock=clock)
    current = jobs.ensure(station, TOWN, POINT, PROFILE, previous)
    assert current["routingProfileVersion"] == PROFILE
    assert current["status"] == "pending"
    assert current["jobId"] != previous["jobId"]
    assert [payload["jobId"] for payload in sent] == [current["jobId"]]


@pytest.mark.parametrize("supply_existing", [True, False])
@pytest.mark.parametrize("status", ["ok", "pending", "unavailable"])
def test_old_request_cannot_overwrite_newer_profile_even_when_retry_is_due(
    table: Table,
    station: Station,
    clock: Clock,
    supply_existing: bool,
    status: str,
) -> None:
    newer = seed(
        table,
        clock,
        status=status,
        routingProfileVersion="pt-v1:2026-11",
        leaseExpiresAt=int(clock.now.timestamp()) - 1,
        retryAfter=int(clock.now.timestamp()) - 1,
    )
    sent: list[dict[str, Any]] = []
    jobs = CommuteJobs(table, sent.append, clock=clock)
    current = jobs.ensure(
        station,
        TOWN,
        POINT,
        PROFILE,
        newer if supply_existing else None,
        retry_unavailable=True,
    )
    assert current == newer
    assert sent == []
    assert table.get_item(Key=KEY, ConsistentRead=True)["Item"] == newer


@pytest.mark.parametrize("invalid", ["pt-v1:2026-1", "pt-v1:2026-13", "pt-v2:2026-10"])
def test_unsupported_request_profile_cannot_claim(
    table: Table, station: Station, clock: Clock, invalid: str
) -> None:
    sent: list[dict[str, Any]] = []
    jobs = CommuteJobs(table, sent.append, clock=clock)
    with pytest.raises(ValueError, match="pt-v1:YYYY-MM"):
        jobs.ensure(station, TOWN, POINT, invalid, None)
    assert "Item" not in table.get_item(Key=KEY, ConsistentRead=True)
    assert sent == []


def test_enqueue_failure_releases_only_its_pending_claim(
    table: Table, station: Station, clock: Clock
) -> None:
    failure = RuntimeError("SQS unavailable")

    def fail(payload: dict[str, Any]) -> None:
        raise failure

    jobs = CommuteJobs(table, fail, clock=clock)
    with pytest.raises(RuntimeError) as caught:
        jobs.ensure(station, TOWN, POINT, PROFILE, None)
    assert caught.value is failure
    assert "Item" not in table.get_item(Key=KEY, ConsistentRead=True)


@pytest.mark.parametrize("completed", [False, True])
def test_enqueue_failure_preserves_newer_claim_or_completed_result(
    table: Table, station: Station, clock: Clock, completed: bool
) -> None:
    failure = RuntimeError("SQS send failed after concurrent update")
    winner: dict[str, Any] = {}

    def fail(payload: dict[str, Any]) -> None:
        winner.update(
            **KEY,
            jobId=payload["jobId"] if completed else "newer-claim",
            status="ok" if completed else "pending",
            routingProfileVersion=PROFILE,
            leaseExpiresAt=int(clock.now.timestamp()) + 900,
        )
        table.put_item(Item=winner)
        raise failure

    jobs = CommuteJobs(table, fail, clock=clock)
    with pytest.raises(RuntimeError) as caught:
        jobs.ensure(station, TOWN, POINT, PROFILE, None)
    assert caught.value is failure
    assert table.get_item(Key=KEY, ConsistentRead=True)["Item"] == winner


def test_cleanup_failure_preserves_send_error_and_lease_can_recover(
    table: Table,
    station: Station,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = RuntimeError("SQS unavailable")

    def fail(payload: dict[str, Any]) -> None:
        raise failure

    def cleanup_failure(**kwargs: Any) -> Any:
        raise RuntimeError("DynamoDB cleanup unavailable")

    monkeypatch.setattr(table, "delete_item", cleanup_failure)
    jobs = CommuteJobs(table, fail, clock=clock, lease_seconds=60)
    with pytest.raises(RuntimeError) as caught:
        jobs.ensure(station, TOWN, POINT, PROFILE, None)
    assert caught.value is failure
    abandoned = table.get_item(Key=KEY, ConsistentRead=True)["Item"]
    assert abandoned["status"] == "pending"
    clock.now += timedelta(seconds=60)
    sent: list[dict[str, Any]] = []
    recovered = CommuteJobs(table, sent.append, clock=clock).ensure(
        station, TOWN, POINT, PROFILE, abandoned
    )
    assert recovered["jobId"] != abandoned["jobId"]
    assert [payload["jobId"] for payload in sent] == [recovered["jobId"]]


def test_nonroutable_point_is_honestly_resolved_without_coordinates_or_queue(
    table: Table, station: Station, clock: Clock
) -> None:
    sent: list[dict[str, Any]] = []
    jobs = CommuteJobs(table, sent.append, clock=clock)
    point = {"routable": False}
    item = jobs.ensure(station, "TENGAH", point, PROFILE, None)
    assert item["status"] == "unavailable"
    assert item["error"] == "NON_ROUTABLE_TOWN"
    assert item["computedAt"] == clock.now.isoformat()
    assert item["routingProfileVersion"] == PROFILE
    assert item["routingDate"] == "2026-10-19"
    assert item["routingTime"] == "08:30:00"
    assert item["retryAfter"] > int(clock.now.timestamp())
    assert "minutes" not in item
    assert "leaseExpiresAt" not in item
    assert jobs.ensure(station, "TENGAH", point, PROFILE, None) == item
    assert (
        jobs.ensure(station, "TENGAH", point, PROFILE, item, retry_unavailable=True)
        == item
    )
    assert sent == []
    assert (
        table.get_item(
            Key={"pk": "COMMUTE#KENT_RIDGE", "sk": "TOWN#TENGAH"},
            ConsistentRead=True,
        )["Item"]
        == item
    )


def test_permanent_nonroutable_reference_does_not_retry_even_with_due_retry_after(
    table: Table, station: Station, clock: Clock
) -> None:
    previous = seed(
        table,
        clock,
        status="unavailable",
        retryAfter=int(clock.now.timestamp()) - 1,
    )
    sent: list[dict[str, Any]] = []
    jobs = CommuteJobs(table, sent.append, clock=clock)
    assert (
        jobs.ensure(
            station,
            TOWN,
            {"routable": False},
            PROFILE,
            previous,
            retry_unavailable=True,
        )
        == previous
    )
    assert sent == []
