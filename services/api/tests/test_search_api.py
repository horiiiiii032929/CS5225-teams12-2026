"""Search submission/status through the HTTP handler and real Moto SDK calls."""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws
from mypy_boto3_dynamodb.service_resource import Table

import flatsplit_api.handlers.http as http
import flatsplit_api.searches as searches
from flatsplit_api.commute_jobs import CommuteJobs, routing_profile
from flatsplit_api.groups import GroupStore
from flatsplit_api.search_data import SearchDataReader
from flatsplit_api.searches import SearchStore


@dataclass
class Clock:
    now: datetime = datetime(2026, 10, 19, 8, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@dataclass
class Setup:
    table: Table
    clock: Clock
    groups: GroupStore
    searches: SearchStore
    jobs: list[dict[str, Any]]


def call(
    method: str,
    path: str,
    token: str | None = None,
    body: Any = None,
    priority: str | None = None,
) -> tuple[int, dict[str, Any]]:
    event = {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": "",
        "queryStringParameters": {"priority": priority}
        if priority is not None
        else None,
        "headers": {
            "content-type": "application/json",
            **({"authorization": f"Bearer {token}"} if token is not None else {}),
        },
        "requestContext": {
            "http": {"method": method, "path": path},
            "requestId": "search-test",
            "stage": "$default",
        },
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
    }
    context = SimpleNamespace(
        function_name="search-test",
        memory_limit_in_mb=256,
        invoked_function_arn="local",
        aws_request_id="search-test",
    )
    response = http.handler(event, context)  # type: ignore[arg-type]
    if response["statusCode"] in (200, 201):
        assert response["headers"]["Cache-Control"] == "no-store"
    return response["statusCode"], json.loads(response["body"])


def pin(table: Table, snapshot: str = "snapshot-a") -> None:
    table.put_item(
        Item={
            "pk": "RENT",
            "sk": "CURRENT",
            "schemaVersion": 1,
            "snapshotId": snapshot,
            "period": "2025-10/2026-09",
        }
    )
    for town, median in [("CLEMENTI", 2400), ("QUEENSTOWN", 3000)]:
        table.put_item(
            Item={
                "pk": f"RENT#{snapshot}",
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


@pytest.fixture
def setup(monkeypatch: pytest.MonkeyPatch) -> Iterator[Setup]:
    with mock_aws():
        table = boto3.resource("dynamodb", region_name="ap-southeast-1").create_table(
            TableName="search-api",
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
        clock = Clock()
        groups = GroupStore(table, clock=clock)
        jobs: list[dict[str, Any]] = []
        searches = SearchStore(
            table,
            groups,
            SearchDataReader(table),
            CommuteJobs(table, jobs.append, clock=clock),
            clock=clock,
        )
        monkeypatch.setattr(http, "group_store", lambda: groups)
        monkeypatch.setattr(http, "search_store", lambda _groups: searches)
        for station in ["KENT_RIDGE", "ONE_NORTH"]:
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
                    "ttl": int(clock.now.timestamp()) + 86400,
                }
            )
        pin(table)
        yield Setup(table, clock, groups, searches, jobs)


def group(
    size: int = 2, *, ready: bool = True
) -> tuple[str, list[dict[str, Any]], str]:
    status, created = call(
        "POST",
        "/groups",
        body={"groupName": "Shared search", "size": size, "name": "Alex"},
    )
    assert status == 201
    gid = created["group"]["groupId"]
    invite = created["group"]["inviteToken"]
    members = [created]
    for i in range(1, size):
        status, joined = call(
            "POST", f"/groups/{gid}/members", invite, {"name": f"Member {i}"}
        )
        assert status == 201
        members.append(joined)
    if ready:
        for i, member in enumerate(members):
            status, _ = save(gid, member, i)
            assert status == 200
    return gid, members, invite


def save(gid: str, member: dict[str, Any], i: int = 0) -> tuple[int, dict[str, Any]]:
    return call(
        "PUT",
        f"/groups/{gid}/members/{member['memberId']}",
        member["memberToken"],
        {
            "name": "Alex" if i == 0 else f"Member {i}",
            "placeId": "KENT_RIDGE" if i % 2 == 0 else "ONE_NORTH",
            "budget": 1600,
            "maxCommute": 45,
        },
    )


def finish(setup: Setup) -> None:
    for job in setup.jobs:
        setup.table.update_item(
            Key={"pk": f"COMMUTE#{job['stationKey']}", "sk": f"TOWN#{job['town']}"},
            UpdateExpression="SET #status = :ok, minutes = :minutes",
            ConditionExpression="jobId = :job AND #status = :pending",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":ok": "ok",
                ":minutes": Decimal("30.5"),
                ":job": job["jobId"],
                ":pending": "pending",
            },
        )


@pytest.mark.parametrize("size", [2, 5])
def test_pending_complete_pinned_results_and_reload(setup: Setup, size: int) -> None:
    gid, members, _ = group(size)
    token = members[0]["memberToken"]
    status, started = call("POST", f"/groups/{gid}/searches", token)
    assert status == 201
    assert started["status"] == "pending"
    assert started["progress"] == {"total": 54, "resolved": 2, "unavailable": 2}
    assert started["ranked"] == started["excluded"] == []
    assert len(setup.jobs) == 52  # Both stations' TENGAH pairs resolve without routing.
    assert all(
        member["memberToken"] not in json.dumps(setup.jobs) for member in members
    )
    sid = started["searchId"]
    assert call("POST", f"/groups/{gid}/searches", token)[1]["searchId"] == sid
    assert len(setup.jobs) == 52
    pin(setup.table, "snapshot-b")
    setup.table.delete_item(Key={"pk": "RENT#snapshot-b", "sk": "TOWN#CLEMENTI#3-ROOM"})
    finish(setup)
    status, result = call(
        "GET", f"/groups/{gid}/searches/{sid}", token, priority="fairness"
    )
    assert status == 200 and result["status"] == "complete"
    assert result["progress"] == {"total": 54, "resolved": 54, "unavailable": 2}
    assert result["priority"] == "fairness"
    assert result["data"]["flatType"] == ("3-ROOM" if size == 2 else "5-ROOM")
    if size == 2:
        clementi = next(area for area in result["ranked"] if area["town"] == "CLEMENTI")
        assert clementi["wholeFlatRent"] == 2400
        assert clementi["members"][0]["commuteMinutes"] == 30.5
    else:
        assert result["ranked"] == []  # No 5-room summaries, never invented zero rent.
    assert (
        call("GET", f"/groups/{gid}", token)[1]["group"]["latestSearch"]["status"]
        == "complete"
    )
    assert len(setup.jobs) == 52


def test_not_ready_and_token_scopes_are_enforced(setup: Setup) -> None:
    gid, members, invite = group(ready=False)
    path = f"/groups/{gid}/searches"
    assert call("POST", path)[0] == 401
    assert call("POST", path, invite)[0] == 403
    assert (
        call("POST", path, members[0]["memberToken"])[1]["error"]["code"]
        == "GROUP_NOT_READY"
    )
    assert setup.jobs == []


def test_edits_make_search_and_group_summary_stale(setup: Setup) -> None:
    gid, members, _ = group()
    token = members[0]["memberToken"]
    old = call("POST", f"/groups/{gid}/searches", token)[1]
    status, edited = save(gid, members[0])
    assert status == 200
    assert edited["group"]["latestSearch"]["status"] == "stale"
    result = call("GET", f"/groups/{gid}/searches/{old['searchId']}", token)[1]
    assert result["status"] == "stale"
    assert result["ranked"] == result["excluded"] == []
    new = call("POST", f"/groups/{gid}/searches", token)[1]
    assert new["searchId"] != old["searchId"]
    assert new["groupRevision"] == old["groupRevision"] + 1
    assert len(setup.jobs) == 52


def test_concurrent_starts_converge_on_one_search(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    gid, members, _ = group()
    token = members[0]["memberToken"]
    original = setup.table.meta.client.transact_write_items
    raced: list[Any] = []

    def competing(**kwargs: Any) -> Any:
        if not raced:
            raced.append(None)
            raced[0] = setup.searches.start(gid, token)
        return original(**kwargs)

    monkeypatch.setattr(setup.table.meta.client, "transact_write_items", competing)
    result = setup.searches.start(gid, token)
    assert result.searchId == raced[0].searchId
    assert len(setup.jobs) == 52


def test_status_reclaims_expired_lease_without_retrying_unavailable(
    setup: Setup,
) -> None:
    gid, members, _ = group()
    token = members[0]["memberToken"]
    started = call("POST", f"/groups/{gid}/searches", token)[1]
    job = setup.jobs[0]
    key = {"pk": f"COMMUTE#{job['stationKey']}", "sk": f"TOWN#{job['town']}"}
    setup.table.update_item(
        Key=key,
        UpdateExpression="SET #status = :status, retryAfter = :retry",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status": "unavailable",
            ":retry": int(setup.clock.now.timestamp()),
        },
    )
    setup.clock.now += timedelta(minutes=16)
    status, current = call(
        "GET", f"/groups/{gid}/searches/{started['searchId']}", token
    )
    assert status == 200 and current["progress"]["unavailable"] == 3
    assert (
        len(setup.jobs) == 103
    )  # Recover 51 expired leases, not the unavailable pair.
    assert (
        call("POST", f"/groups/{gid}/searches", token)[1]["searchId"]
        == started["searchId"]
    )
    assert len(setup.jobs) == 104  # Explicit repeat retries that one eligible pair.


def test_monthly_refresh_preserves_id_but_invalidates_old_routes(setup: Setup) -> None:
    gid, members, _ = group()
    token = members[0]["memberToken"]
    started = call("POST", f"/groups/{gid}/searches", token)[1]
    finish(setup)
    setup.clock.now = datetime(2026, 11, 1, 8, tzinfo=UTC)
    old = call("GET", f"/groups/{gid}/searches/{started['searchId']}", token)[1]
    assert old["status"] == "stale" and old["ranked"] == []
    refreshed = call("POST", f"/groups/{gid}/searches", token)[1]
    assert (
        refreshed["searchId"] == started["searchId"]
        and refreshed["status"] == "pending"
    )
    assert len(setup.jobs) == 104
    assert all(
        job["routingProfileVersion"] == routing_profile(setup.clock.now)
        for job in setup.jobs[52:]
    )


def test_enqueue_failure_is_503_and_retry_recovers_same_search(setup: Setup) -> None:
    gid, members, _ = group()
    token = members[0]["memberToken"]
    path = f"/groups/{gid}/searches"

    def failed(_job: dict[str, Any]) -> None:
        raise ClientError({"Error": {"Code": "ServiceUnavailable"}}, "SendMessage")

    setup.searches.jobs = CommuteJobs(setup.table, failed, clock=setup.clock)
    assert call("POST", path, token)[1]["error"]["code"] == "SERVICE_UNAVAILABLE"
    summary = call("GET", f"/groups/{gid}", token)[1]["group"]["latestSearch"]
    setup.searches.jobs = CommuteJobs(setup.table, setup.jobs.append, clock=setup.clock)
    status, recovered = call("POST", path, token)
    assert status == 201 and recovered["searchId"] == summary["searchId"]
    assert len(setup.jobs) == 52


def test_search_ids_priority_and_expiry(setup: Setup) -> None:
    gid, members, invite = group()
    token = members[0]["memberToken"]
    started = call("POST", f"/groups/{gid}/searches", token)[1]
    path = f"/groups/{gid}/searches/{started['searchId']}"
    assert call("GET", path, invite)[0] == 403
    assert (
        call("GET", path, token, priority="unknown")[1]["error"]["code"]
        == "VALIDATION_FAILED"
    )
    assert call("GET", f"/groups/{gid}/searches/missing", token)[0] == 404
    other_gid, other_members, _ = group()
    assert call("GET", path, other_members[0]["memberToken"])[0] == 401
    assert (
        call(
            "GET",
            f"/groups/{other_gid}/searches/{started['searchId']}",
            other_members[0]["memberToken"],
        )[0]
        == 404
    )
    setup.clock.now += timedelta(days=31)
    assert call("GET", path, token)[0] == 404
    assert call("POST", f"/groups/{gid}/searches", token)[0] == 404


def test_edit_during_result_loading_withholds_results(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    gid, members, _ = group()
    token = members[0]["memberToken"]
    started = call("POST", f"/groups/{gid}/searches", token)[1]
    finish(setup)
    original = setup.searches.reader.rents

    def changed(snapshot_id: str, flat_type: str) -> Any:
        result = original(snapshot_id, flat_type)
        assert save(gid, members[0])[0] == 200
        return result

    monkeypatch.setattr(setup.searches.reader, "rents", changed)
    status, result = call("GET", f"/groups/{gid}/searches/{started['searchId']}", token)
    assert status == 200 and result["status"] == "stale"
    assert result["ranked"] == result["excluded"] == []


def test_transient_reservation_conflict_retries_with_fresh_state(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(searches, "sleep", lambda _: None)
    gid, members, _ = group()
    token = members[0]["memberToken"]
    before = setup.groups.read(gid, token).revision
    original = setup.table.meta.client.transact_write_items
    collided = False

    def busy(**kwargs: Any) -> Any:
        nonlocal collided
        if not collided:
            collided = True
            assert save(gid, members[0])[0] == 200
            raise setup.table.meta.client.exceptions.TransactionCanceledException(
                {
                    "Error": {"Code": "TransactionCanceledException"},
                    "CancellationReasons": [{"Code": "TransactionConflict"}],
                },
                "TransactWriteItems",
            )
        return original(**kwargs)

    monkeypatch.setattr(setup.table.meta.client, "transact_write_items", busy)
    status, result = call("POST", f"/groups/{gid}/searches", token)
    assert status == 201 and result["groupRevision"] == before + 1
    repeat = call("POST", f"/groups/{gid}/searches", token)[1]
    assert repeat["searchId"] == result["searchId"]
    assert len(setup.jobs) == 52


@pytest.mark.parametrize(
    ("codes", "expected_status", "expected_code", "attempts"),
    [
        (["TransactionConflict", "None"], 409, "CONFLICT", 3),
        (["ProvisionedThroughputExceeded", "None"], 503, "SERVICE_UNAVAILABLE", 1),
        (
            ["TransactionConflict", "ProvisionedThroughputExceeded"],
            503,
            "SERVICE_UNAVAILABLE",
            1,
        ),
    ],
)
def test_reservation_retry_bound_and_provider_faults(
    setup: Setup,
    monkeypatch: pytest.MonkeyPatch,
    codes: list[str],
    expected_status: int,
    expected_code: str,
    attempts: int,
) -> None:
    gid, members, _ = group()
    token = members[0]["memberToken"]
    path = f"/groups/{gid}/searches"
    original = setup.table.meta.client.transact_write_items
    failures = 0

    def unavailable(**_kwargs: Any) -> Any:
        nonlocal failures
        failures += 1
        raise setup.table.meta.client.exceptions.TransactionCanceledException(
            {
                "Error": {"Code": "TransactionCanceledException"},
                "CancellationReasons": [{"Code": code} for code in codes],
            },
            "TransactWriteItems",
        )

    monkeypatch.setattr(searches, "sleep", lambda _: None)
    monkeypatch.setattr(setup.table.meta.client, "transact_write_items", unavailable)
    status, result = call("POST", path, token)
    assert status == expected_status and result["error"]["code"] == expected_code
    assert failures == attempts and setup.jobs == []
    monkeypatch.setattr(setup.table.meta.client, "transact_write_items", original)
    status, recovered = call("POST", path, token)
    assert status == 201 and recovered["status"] == "pending"
    assert len(setup.jobs) == 52
