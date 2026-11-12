"""Group/token behavior against Moto's DynamoDB transaction emulator (no AWS calls)."""

import hashlib
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
from pydantic import ValidationError

from flatsplit_api.errors import ApiError
from flatsplit_api.group_models import (
    CreateGroupRequest,
    GroupState,
    JoinGroupRequest,
    Membership,
    PreferencesRequest,
)
from flatsplit_api.groups import GROUP_LIFETIME, GroupStore


@dataclass
class Clock:
    now: datetime = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def table() -> Iterator[Table]:
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name="ap-southeast-1")
        yield resource.create_table(
            TableName="groups-test",
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
def store(table: Table, clock: Clock) -> GroupStore:
    return GroupStore(table, clock=clock)


def create(store: GroupStore, size: int = 3) -> Membership:
    return store.create(
        CreateGroupRequest(groupName="  Our place  ", size=size, name=" Alex ")
    )


def join(store: GroupStore, group: Membership, name: str = "Jamie") -> Membership:
    return store.join(
        group.group.groupId, group.inviteToken, JoinGroupRequest(name=name)
    )


def items(table: Table, group: Membership) -> list[dict[str, Any]]:
    return table.query(
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": f"GROUP#{group.group.groupId}"},
        ConsistentRead=True,
    )["Items"]


def seed_place(table: Table, clock: Clock, *, expired: bool = False) -> None:
    table.put_item(
        Item={
            "pk": "PLACE#pl_nus",
            "sk": "META",
            "label": "National University of Singapore",
            "address": "21 Lower Kent Ridge Road",
            "station": {
                "stationKey": "KENT_RIDGE",
                "codes": ["CC24"],
                "name": "Kent Ridge",
                "lat": Decimal("1.2936"),
                "lng": Decimal("103.7845"),
                "snapMetres": 900,
                "snapWarning": True,
            },
            "ttl": int(clock.now.timestamp()) + (-1 if expired else 86400),
        }
    )


def preferences(name: str = "Alex") -> PreferencesRequest:
    return PreferencesRequest(
        name=name, placeId="pl_nus", budget=1400.25, maxCommute=45
    )


def save(store: GroupStore, member: Membership, name: str = "Alex") -> GroupState:
    return store.save_preferences(
        member.group.groupId, member.memberId, member.memberToken, preferences(name)
    )


def interleave(
    store: GroupStore, monkeypatch: pytest.MonkeyPatch, action: Callable[[], Any]
) -> None:
    """Commit a competing mutation after the caller's read, before its transaction."""
    original = store._client.transact_write_items
    fired = False

    def transact(**kwargs: Any) -> Any:
        nonlocal fired
        if not fired:
            fired = True
            action()
        return original(**kwargs)

    monkeypatch.setattr(store._client, "transact_write_items", transact)


def test_create_persists_only_hashed_credentials_and_fixed_expiry(
    store: GroupStore, table: Table, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    group = create(store)
    assert group.inviteToken is not None
    assert group.group.groupName == "Our place"
    assert group.group.members[0].name == "Alex"
    assert group.group.members[0].isOrganiser
    assert group.group.revision == 1
    assert not group.group.allReady
    assert group.group.expiresAt == clock.now + GROUP_LIFETIME
    assert len(group.group.groupId) == len(group.memberId) == 22
    assert len(group.memberToken) == len(group.inviteToken or "") == 43
    stored = items(table, group)
    meta = next(i for i in stored if i["sk"] == "META")
    member = next(i for i in stored if i["sk"].startswith("MEMBER#"))
    assert (
        meta["inviteTokenHash"]
        == hashlib.sha256((group.inviteToken or "").encode()).hexdigest()
    )
    assert member["tokenHash"] == hashlib.sha256(group.memberToken.encode()).hexdigest()
    assert {i["ttl"] for i in stored} == {
        Decimal(int(group.group.expiresAt.timestamp()))
    }
    clock.now += timedelta(days=1)
    reloaded = store.read(group.group.groupId, group.memberToken)
    public = reloaded.model_dump_json()
    for secret in [
        group.memberToken,
        group.inviteToken,
        member["tokenHash"],
        meta["inviteTokenHash"],
    ]:
        assert secret not in public
    for token in [group.memberToken, group.inviteToken]:
        assert token not in json.dumps(stored, default=str)
        assert token not in caplog.text
        assert token not in repr(group)
    assert reloaded.expiresAt == group.group.expiresAt


@pytest.mark.parametrize(
    "token_kind,code,status",
    [
        ("missing", "UNAUTHORIZED", 401),
        ("invalid", "UNAUTHORIZED", 401),
        ("other_group", "UNAUTHORIZED", 401),
        ("invite", "FORBIDDEN", 403),
    ],
)
def test_only_own_group_members_can_read_or_save(
    store: GroupStore, token_kind: str, code: str, status: int
) -> None:
    group = create(store)
    other = create(store)
    tokens = {
        "missing": None,
        "invalid": "bad-token",
        "other_group": other.memberToken,
        "invite": group.inviteToken,
    }
    operations: list[Callable[[], Any]] = [
        lambda: store.read(group.group.groupId, tokens[token_kind]),
        lambda: store.save_preferences(
            group.group.groupId, group.memberId, tokens[token_kind], preferences()
        ),
    ]
    for operation in operations:
        with pytest.raises(ApiError) as exc:
            operation()
        assert (exc.value.status_code, exc.value.code) == (status, code)
        assert "Our place" not in json.dumps(exc.value.body())
        assert group.memberToken not in json.dumps(exc.value.body())


def test_member_cannot_join_or_edit_another_member(store: GroupStore) -> None:
    group = create(store)
    member = join(store, group)
    with pytest.raises(ApiError) as exc:
        store.join(group.group.groupId, group.memberToken, JoinGroupRequest(name="Sam"))
    assert exc.value.code == "FORBIDDEN"
    with pytest.raises(ApiError) as exc:
        store.save_preferences(
            group.group.groupId, member.memberId, group.memberToken, preferences()
        )
    assert exc.value.code == "FORBIDDEN"


def test_join_order_revision_and_capacity_with_a_frozen_clock(
    store: GroupStore,
) -> None:
    group = create(store)
    join(store, group, "Jamie")
    last = join(store, group, "Sam")
    assert [m.name for m in last.group.members] == ["Alex", "Jamie", "Sam"]
    assert last.group.revision == 3
    assert last.inviteToken is None
    with pytest.raises(ApiError) as exc:
        join(store, group, "Extra")
    assert exc.value.code == "GROUP_FULL"
    assert store.read(group.group.groupId, group.memberToken).revision == 3


@pytest.mark.parametrize(
    "first,duplicate",
    [
        ("Jamie", "  jAMIE "),
        ("Café", "Cafe\u0301"),
        ("Straße", "STRASSE"),
        ("Ｊａｍｉｅ", "Jamie"),
    ],
)
def test_unicode_normalized_names_are_unique(
    store: GroupStore, first: str, duplicate: str
) -> None:
    group = create(store, size=5)
    join(store, group, first)
    with pytest.raises(ApiError) as exc:
        join(store, group, duplicate)
    assert exc.value.code == "VALIDATION_FAILED"
    assert exc.value.details is not None
    assert exc.value.details[0]["field"] == "name"
    assert store.read(group.group.groupId, group.memberToken).revision == 2


def test_last_slot_race_rolls_back_loser_without_orphan_records(
    store: GroupStore, table: Table, monkeypatch: pytest.MonkeyPatch
) -> None:
    group = create(store, size=2)
    interleave(store, monkeypatch, lambda: join(store, group, "Winner"))
    with pytest.raises(ApiError) as exc:
        join(store, group, "Loser")
    assert exc.value.code == "GROUP_FULL"
    state = store.read(group.group.groupId, group.memberToken)
    assert [m.name for m in state.members] == ["Alex", "Winner"]
    assert state.revision == 2
    stored = items(table, group)
    assert not any(
        i.get("nameKey") == "loser" or i["sk"] == "NAME#loser" for i in stored
    )
    assert next(i for i in stored if i["sk"] == "META")["memberCount"] == 2


def test_overlapping_joins_with_capacity_both_commit_in_order(
    store: GroupStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    group = create(store)
    interleave(store, monkeypatch, lambda: join(store, group, "First"))
    result = join(store, group, "Second")
    assert [m.name for m in result.group.members] == ["Alex", "First", "Second"]
    assert result.group.revision == 3


def test_overlapping_retries_return_one_membership(
    store: GroupStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    group = create(store, size=2)
    request = JoinGroupRequest(name="Jamie", retryToken="R" * 43)
    completed: list[Membership] = []

    def replay() -> None:
        completed.append(store.join(group.group.groupId, group.inviteToken, request))

    interleave(store, monkeypatch, replay)
    response = store.join(group.group.groupId, group.inviteToken, request)
    assert response == completed[0]
    assert response.group.revision == 2
    assert len(response.group.members) == 2


def test_same_name_race_is_validation_not_a_partial_join(
    store: GroupStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    group = create(store, size=5)
    interleave(store, monkeypatch, lambda: join(store, group, "Ｊａｍｉｅ"))
    with pytest.raises(ApiError) as exc:
        join(store, group, "Jamie")
    assert exc.value.code == "VALIDATION_FAILED"
    assert store.read(group.group.groupId, group.memberToken).revision == 2


@pytest.mark.parametrize("operation", ["read", "join", "save"])
def test_expiry_is_enforced_without_ttl_deletion(
    store: GroupStore, table: Table, clock: Clock, operation: str
) -> None:
    group = create(store)
    clock.now = group.group.expiresAt
    operations: dict[str, Callable[[], Any]] = {
        "read": lambda: store.read(group.group.groupId, None),
        "join": lambda: join(store, group),
        "save": lambda: save(store, group),
    }
    with pytest.raises(ApiError) as exc:
        operations[operation]()
    assert (exc.value.status_code, exc.value.code) == (404, "NOT_FOUND")
    assert next(i for i in items(table, group) if i["sk"] == "META")["revision"] == 1


def test_unknown_group_is_not_found_even_without_token(store: GroupStore) -> None:
    with pytest.raises(ApiError) as exc:
        store.read("unknown", None)
    assert exc.value.code == "NOT_FOUND"


@pytest.mark.parametrize("operation", ["join", "save"])
def test_transaction_rechecks_group_expiry(
    store: GroupStore,
    table: Table,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    group = create(store)
    seed_place(table, clock)
    interleave(
        store,
        monkeypatch,
        lambda: table.update_item(
            Key={"pk": f"GROUP#{group.group.groupId}", "sk": "META"},
            UpdateExpression="SET #ttl = :expired",
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={":expired": int(clock.now.timestamp())},
        ),
    )
    with pytest.raises(ApiError) as exc:
        join(store, group) if operation == "join" else save(store, group)
    assert exc.value.code == "NOT_FOUND"
    stored = items(table, group)
    assert next(i for i in stored if i["sk"] == "META")["revision"] == 1
    assert [i["name"] for i in stored if i["sk"].startswith("MEMBER#")] == ["Alex"]
    assert not next(i for i in stored if i["sk"].startswith("MEMBER#"))["ready"]


def test_preference_save_renames_atomically_and_increments_revision(
    store: GroupStore, table: Table, clock: Clock
) -> None:
    group = create(store)
    seed_place(table, clock)
    state = save(store, group, "Al")
    assert state.revision == 2
    assert state.readyCount == 1
    assert not state.allReady
    member = state.members[0]
    assert (member.name, member.budget, member.maxCommute) == ("Al", 1400.25, 45)
    assert member.destination is not None
    assert member.destination.station.stationKey == "KENT_RIDGE"
    assert member.destination.station.snapWarning
    assert state.expiresAt == group.group.expiresAt
    assert "NAME#alex" not in {i["sk"] for i in items(table, group)}
    assert "NAME#al" in {i["sk"] for i in items(table, group)}
    # Reusing a released name is permitted; the new reservation stays exclusive.
    join(store, group, "Alex")
    with pytest.raises(ApiError) as exc:
        join(store, group, "AL")
    assert exc.value.code == "VALIDATION_FAILED"
    assert store.read(group.group.groupId, group.memberToken).revision == 3


def test_all_ready_requires_full_membership_and_each_member_saved(
    store: GroupStore, table: Table, clock: Clock
) -> None:
    group = create(store, size=2)
    seed_place(table, clock)
    assert not save(store, group).allReady
    member = join(store, group)
    assert not member.group.allReady
    state = save(store, member, "Jamie")
    assert state.allReady
    assert state.readyCount == 2
    assert state.revision == 4
    assert save(store, member, "JAMIE").revision == 5


@pytest.mark.parametrize("expired", [False, True])
def test_missing_or_expired_place_cannot_mark_member_ready(
    store: GroupStore, table: Table, clock: Clock, expired: bool
) -> None:
    group = create(store)
    if expired:
        seed_place(table, clock, expired=True)
    with pytest.raises(ApiError) as exc:
        save(store, group)
    assert exc.value.code == "NOT_FOUND"
    state = store.read(group.group.groupId, group.memberToken)
    assert state.revision == 1
    assert not state.members[0].ready


def test_competing_renames_cannot_take_the_same_name(
    store: GroupStore, table: Table, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    group = create(store)
    member = join(store, group)
    seed_place(table, clock)
    interleave(store, monkeypatch, lambda: save(store, member, "Target"))
    with pytest.raises(ApiError) as exc:
        save(store, group, "target")
    assert exc.value.code == "VALIDATION_FAILED"
    state = store.read(group.group.groupId, group.memberToken)
    assert state.revision == 3
    assert [(m.name, m.ready) for m in state.members] == [
        ("Alex", False),
        ("Target", True),
    ]
    assert {i["sk"] for i in items(table, group) if i["sk"].startswith("NAME#")} == {
        "NAME#alex",
        "NAME#target",
    }


def test_concurrent_self_rename_returns_conflict_without_leaking_reservations(
    store: GroupStore, table: Table, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    group = create(store)
    seed_place(table, clock)
    interleave(store, monkeypatch, lambda: save(store, group, "First"))
    with pytest.raises(ApiError) as exc:
        save(store, group, "Second")
    assert (exc.value.status_code, exc.value.code) == (409, "CONFLICT")
    state = store.read(group.group.groupId, group.memberToken)
    assert state.revision == 2
    assert state.members[0].name == "First"
    assert {i["sk"] for i in items(table, group) if i["sk"].startswith("NAME#")} == {
        "NAME#first"
    }


def test_group_query_paginates_before_authorization(
    store: GroupStore, table: Table
) -> None:
    group = create(store, size=5)
    members = [group, *(join(store, group, f"Member {i}") for i in range(3))]
    for item in items(table, group):
        if item["sk"].startswith("MEMBER#"):
            table.update_item(
                Key={"pk": item["pk"], "sk": item["sk"]},
                UpdateExpression="SET payload = :padding",
                ExpressionAttributeValues={":padding": "x" * 300_000},
            )
    state = store.read(group.group.groupId, members[-1].memberToken)
    assert [m.name for m in state.members] == [
        "Alex",
        "Member 0",
        "Member 1",
        "Member 2",
    ]
    assert state.revision == 4


@pytest.mark.parametrize(
    "values",
    [
        {"groupName": " ", "size": 3, "name": "Alex"},
        {"groupName": "x" * 41, "size": 3, "name": "Alex"},
        {"groupName": "Group", "size": 1, "name": "Alex"},
        {"groupName": "Group", "size": 6, "name": "Alex"},
        {"groupName": "Group", "size": True, "name": "Alex"},
        {"groupName": "Group", "size": "3", "name": "Alex"},
        {"groupName": "Group", "size": 3, "name": " "},
        {"groupName": "Group", "size": 3, "name": "x" * 31},
    ],
)
def test_invalid_group_fields_are_rejected(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        CreateGroupRequest.model_validate(values)


@pytest.mark.parametrize(
    "field,value",
    [
        ("budget", 299),
        ("budget", 5001),
        ("budget", float("nan")),
        ("budget", "1400"),
        ("budget", True),
        ("maxCommute", 9),
        ("maxCommute", 121),
        ("maxCommute", 45.5),
        ("maxCommute", True),
    ],
)
def test_invalid_preferences_are_rejected(field: str, value: Any) -> None:
    values = {"name": "Alex", "placeId": "pl_nus", "budget": 1400, "maxCommute": 45}
    with pytest.raises(ValidationError):
        PreferencesRequest.model_validate({**values, field: value})


def test_unknown_member_is_not_found_after_authentication(store: GroupStore) -> None:
    group = create(store)
    with pytest.raises(ApiError) as exc:
        store.save_preferences(
            group.group.groupId, "unknown", group.memberToken, preferences()
        )
    assert (exc.value.status_code, exc.value.code) == (404, "NOT_FOUND")


def test_subsecond_creation_has_exact_fixed_lifetime(
    store: GroupStore, clock: Clock
) -> None:
    clock.now = clock.now.replace(microsecond=987654)
    group = create(store)
    assert group.group.expiresAt - group.group.createdAt == GROUP_LIFETIME


def test_place_expiry_during_save_rolls_back_preferences_and_revision(
    store: GroupStore, table: Table, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    group = create(store)
    seed_place(table, clock)
    interleave(
        store,
        monkeypatch,
        lambda: table.update_item(
            Key={"pk": "PLACE#pl_nus", "sk": "META"},
            UpdateExpression="SET #ttl = :expired",
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={":expired": int(clock.now.timestamp())},
        ),
    )
    with pytest.raises(ApiError) as exc:
        save(store, group, "New name")
    assert exc.value.code == "NOT_FOUND"
    state = store.read(group.group.groupId, group.memberToken)
    assert state.revision == 1
    assert state.members[0].name == "Alex"
    assert not state.members[0].ready


@pytest.mark.parametrize("operation", ["join", "save"])
@pytest.mark.parametrize(
    "codes",
    [
        ["ThrottlingError"],
        ["TransactionConflict", "ProvisionedThroughputExceeded"],
        ["TransactionConflict", "ConditionalCheckFailed"],
        ["None"],
        [],
    ],
)
def test_non_conflict_cancellations_are_not_retried_or_reclassified(
    store: GroupStore,
    table: Table,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    codes: list[str],
) -> None:
    group = create(store)
    seed_place(table, clock)
    error_type = store._client.exceptions.TransactionCanceledException
    calls = 0

    def fail(**kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise error_type(
            {
                "Error": {"Code": "TransactionCanceledException"},
                "CancellationReasons": [{"Code": code} for code in codes],
            },
            "TransactWriteItems",
        )

    monkeypatch.setattr(store._client, "transact_write_items", fail)
    with pytest.raises(error_type):
        join(store, group) if operation == "join" else save(store, group)
    assert calls == 1
    state = store.read(group.group.groupId, group.memberToken)
    assert state.revision == 1
    assert [m.name for m in state.members] == ["Alex"]
    assert not state.members[0].ready


def conflict(store: GroupStore) -> Any:
    return store._client.exceptions.TransactionCanceledException(
        {
            "Error": {"Code": "TransactionCanceledException"},
            "CancellationReasons": [{"Code": "TransactionConflict"}, {"Code": "None"}],
        },
        "TransactWriteItems",
    )


@pytest.mark.parametrize("operation", ["join", "save"])
def test_transaction_conflict_then_success_commits_exactly_once(
    store: GroupStore,
    table: Table,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    group = create(store)
    seed_place(table, clock)
    original = store._client.transact_write_items
    delays: list[float] = []
    calls = 0

    def transact(**kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise conflict(store)
        return original(**kwargs)

    monkeypatch.setattr(store._client, "transact_write_items", transact)
    monkeypatch.setattr("flatsplit_api.groups.sleep", delays.append)
    if operation == "join":
        member = join(store, group)
        state = store.read(group.group.groupId, member.memberToken)
        assert [m.name for m in state.members] == ["Alex", "Jamie"]
        assert len(items(table, group)) == 5
    else:
        state = save(store, group, "New name")
        assert state.members[0].name == "New name"
        assert state.members[0].budget == 1400.25
        assert state.members[0].ready
        assert {
            i["sk"] for i in items(table, group) if i["sk"].startswith("NAME#")
        } == {"NAME#new name"}
    assert state.revision == 2
    assert calls == 2
    assert len(delays) == 1 and 0.02 <= delays[0] <= 0.1


@pytest.mark.parametrize("operation", ["join", "save"])
def test_transaction_conflict_exhaustion_returns_409_without_mutation(
    store: GroupStore,
    table: Table,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    group = create(store)
    seed_place(table, clock)
    delays: list[float] = []
    calls = 0

    def fail(**kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise conflict(store)

    monkeypatch.setattr(store._client, "transact_write_items", fail)
    monkeypatch.setattr("flatsplit_api.groups.sleep", delays.append)
    with pytest.raises(ApiError) as exc:
        join(store, group) if operation == "join" else save(store, group, "New name")
    assert (exc.value.status_code, exc.value.code) == (409, "CONFLICT")
    state = store.read(group.group.groupId, group.memberToken)
    assert state.revision == 1
    assert [m.name for m in state.members] == ["Alex"]
    assert not state.members[0].ready
    assert len(items(table, group)) == 3
    assert calls == 3
    assert len(delays) == 2 and all(0.02 <= delay <= 0.1 for delay in delays)


@pytest.mark.parametrize("operation", ["join", "save"])
def test_group_expiry_is_rechecked_after_conflict_backoff(
    store: GroupStore,
    table: Table,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    group = create(store)
    seed_place(table, clock)

    def fail(**kwargs: Any) -> Any:
        raise conflict(store)

    def expire(delay: float) -> None:
        clock.now = group.group.expiresAt

    monkeypatch.setattr(store._client, "transact_write_items", fail)
    monkeypatch.setattr("flatsplit_api.groups.sleep", expire)
    with pytest.raises(ApiError) as exc:
        join(store, group) if operation == "join" else save(store, group)
    assert exc.value.code == "NOT_FOUND"
    stored = items(table, group)
    assert next(i for i in stored if i["sk"] == "META")["revision"] == 1
    assert not next(i for i in stored if i["sk"].startswith("MEMBER#"))["ready"]


def test_place_expiry_is_rechecked_after_conflict_backoff(
    store: GroupStore,
    table: Table,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = create(store)
    seed_place(table, clock)

    def fail(**kwargs: Any) -> Any:
        raise conflict(store)

    def expire(delay: float) -> None:
        clock.now += timedelta(days=1)

    monkeypatch.setattr(store._client, "transact_write_items", fail)
    monkeypatch.setattr("flatsplit_api.groups.sleep", expire)
    with pytest.raises(ApiError) as exc:
        save(store, group, "New name")
    assert exc.value.code == "NOT_FOUND"
    state = store.read(group.group.groupId, group.memberToken)
    assert state.revision == 1
    assert state.members[0].name == "Alex"
    assert not state.members[0].ready


def test_last_slot_taken_during_conflict_is_not_retried_as_a_stale_join(
    store: GroupStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    group = create(store, size=2)
    original = store._client.transact_write_items
    fired = False

    def transact(**kwargs: Any) -> Any:
        nonlocal fired
        if not fired:
            fired = True
            join(store, group, "Winner")
            raise conflict(store)
        return original(**kwargs)

    monkeypatch.setattr(store._client, "transact_write_items", transact)
    monkeypatch.setattr("flatsplit_api.groups.sleep", lambda delay: None)
    with pytest.raises(ApiError) as exc:
        join(store, group, "Loser")
    assert exc.value.code == "GROUP_FULL"
    state = store.read(group.group.groupId, group.memberToken)
    assert [m.name for m in state.members] == ["Alex", "Winner"]
    assert state.revision == 2


def test_name_taken_during_conflict_is_not_overwritten_by_retry(
    store: GroupStore,
    table: Table,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = create(store)
    member = join(store, group)
    seed_place(table, clock)
    original = store._client.transact_write_items
    fired = False

    def transact(**kwargs: Any) -> Any:
        nonlocal fired
        if not fired:
            fired = True
            save(store, member, "Target")
            raise conflict(store)
        return original(**kwargs)

    monkeypatch.setattr(store._client, "transact_write_items", transact)
    monkeypatch.setattr("flatsplit_api.groups.sleep", lambda delay: None)
    with pytest.raises(ApiError) as exc:
        save(store, group, "target")
    assert exc.value.code == "VALIDATION_FAILED"
    state = store.read(group.group.groupId, group.memberToken)
    assert [(m.name, m.ready) for m in state.members] == [
        ("Alex", False),
        ("Target", True),
    ]
    assert state.revision == 3
