"""#12 group HTTP API through the Lambda handler, backed by Moto's DynamoDB."""

import base64
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import boto3
import pytest
from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)
from moto import mock_aws
from mypy_boto3_dynamodb.service_resource import Table

import flatsplit_api.handlers.http as http
import flatsplit_api.storage as storage
from flatsplit_api.groups import GroupStore


@dataclass(frozen=True)
class FakeContext:
    function_name: str = "flatsplit-api-test"
    memory_limit_in_mb: int = 256
    invoked_function_arn: str = (
        "arn:aws:lambda:ap-southeast-1:000000000000:function:flatsplit-api-test"
    )
    aws_request_id: str = "test-request"


@dataclass
class Clock:
    now: datetime = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@dataclass
class Reply:
    status: int
    headers: dict[str, str]
    body: dict[str, Any]


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def table(clock: Clock, monkeypatch: pytest.MonkeyPatch) -> Iterator[Table]:
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name="ap-southeast-1")
        created = resource.create_table(
            TableName="groups-api-test",
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
        store = GroupStore(created, clock=clock)
        monkeypatch.setattr(http, "group_store", lambda: store)
        yield created


def call(
    method: str,
    path: str,
    body: Any = None,
    token: str | None = None,
    *,
    raw_body: str | None = None,
) -> Reply:
    headers = {"content-type": "application/json"}
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    text = raw_body if raw_body is not None else json.dumps(body)
    event = {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": "",
        "headers": headers,
        "requestContext": {
            "http": {"method": method, "path": path, "sourceIp": "127.0.0.1"},
            "requestId": "test-request",
            "stage": "$default",
        },
        "body": base64.b64encode(text.encode()).decode(),
        "isBase64Encoded": True,
    }
    response = http.handler(event, FakeContext())  # type: ignore[arg-type]
    return Reply(
        response["statusCode"],
        {k.lower(): v for k, v in (response.get("headers") or {}).items()},
        json.loads(response["body"]),
    )


def create(size: int = 3, name: str = "Alex") -> Reply:
    reply = call(
        "POST",
        "/api/groups",
        {"groupName": "Our next chapter", "size": size, "name": name},
    )
    assert reply.status == 201, reply.body
    return reply


def join(created: Reply, name: str) -> Reply:
    gid = created.body["group"]["groupId"]
    return call(
        "POST",
        f"/api/groups/{gid}/members",
        {"name": name},
        created.body["group"]["inviteToken"],
    )


def seed_place(table: Table, clock: Clock) -> None:
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
                "snapMetres": 650,
                "snapWarning": False,
            },
            "ttl": int(clock.now.timestamp()) + 86400,
        }
    )


def preferences(name: str) -> dict[str, Any]:
    return {"name": name, "placeId": "pl_nus", "budget": 1400, "maxCommute": 45}


def test_create_returns_credentials_once_and_is_uncacheable(table: Table) -> None:
    reply = create()

    group = reply.body["group"]
    assert reply.headers["cache-control"] == "no-store"
    assert group["groupName"] == "Our next chapter"
    assert group["size"] == 3
    assert group["revision"] == 1
    assert group["latestSearch"] is None
    assert group["inviteToken"] and reply.body["memberToken"]
    assert group["members"][0]["isOrganiser"] is True
    assert reply.body["memberId"] == group["members"][0]["memberId"]

    reread = call(
        "GET", f"/api/groups/{group['groupId']}", token=reply.body["memberToken"]
    )
    assert reread.status == 200
    assert "inviteToken" not in reread.body["group"]
    assert "memberToken" not in reread.body
    assert reread.body["group"]["members"] == group["members"]


@pytest.mark.parametrize("size", [2, 5])
def test_full_journey_for_two_and_five_members(
    table: Table, clock: Clock, size: int
) -> None:
    seed_place(table, clock)
    created = create(size=size)
    gid = created.body["group"]["groupId"]
    members = [(created.body["memberId"], created.body["memberToken"], "Alex")]
    for index in range(1, size):
        joined = join(created, f"Member {index}")
        assert joined.status == 201, joined.body
        assert "inviteToken" not in joined.body["group"]
        members.append(
            (joined.body["memberId"], joined.body["memberToken"], f"Member {index}")
        )

    assert join(created, "One too many").body["error"]["code"] == "GROUP_FULL"

    for member_id, token, name in members:
        saved = call(
            "PUT", f"/api/groups/{gid}/members/{member_id}", preferences(name), token
        )
        assert saved.status == 200, saved.body

    final = call("GET", f"/groups/{gid}", token=members[-1][1])
    assert final.body["group"]["allReady"] is True
    assert final.body["group"]["readyCount"] == size
    # One revision for creation, one per join, one per save.
    assert final.body["group"]["revision"] == 1 + 2 * (size - 1) + 1
    destination = final.body["group"]["members"][0]["destination"]
    assert destination["station"]["stationKey"] == "KENT_RIDGE"


def test_full_group_is_conflict(table: Table) -> None:
    created = create(size=2)
    assert join(created, "Jamie").status == 201

    full = join(created, "Sam")
    assert full.status == 409
    assert full.body["error"]["code"] == "GROUP_FULL"


def test_duplicate_name_is_validation_error(table: Table) -> None:
    created = create()

    duplicate = join(created, "  alex ")
    assert duplicate.status == 422
    assert duplicate.body["error"]["details"][0]["field"] == "name"


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"groupName": "", "size": 3, "name": "Alex"}, "groupName"),
        ({"groupName": "Flat", "size": 6, "name": "Alex"}, "size"),
        ({"groupName": "Flat", "size": "3", "name": "Alex"}, "size"),
        ({"groupName": "Flat", "size": 3, "name": "A" * 31}, "name"),
        ({"groupName": "Flat", "size": 3}, "name"),
    ],
)
def test_invalid_create_lists_the_field(
    table: Table, body: dict[str, Any], field: str
) -> None:
    reply = call("POST", "/api/groups", body)

    assert reply.status == 422
    assert reply.body["error"]["code"] == "VALIDATION_FAILED"
    assert field in [detail["field"] for detail in reply.body["error"]["details"]]


@pytest.mark.parametrize(
    ("field", "value"),
    [("budget", 299), ("budget", 5001), ("maxCommute", 9), ("maxCommute", 45.5)],
)
def test_invalid_preferences_are_rejected_before_storage(
    table: Table, field: str, value: Any
) -> None:
    created = create()
    gid, mid = created.body["group"]["groupId"], created.body["memberId"]

    reply = call(
        "PUT",
        f"/api/groups/{gid}/members/{mid}",
        {**preferences("Alex"), field: value},
        created.body["memberToken"],
    )
    assert reply.status == 422
    assert reply.body["error"]["details"][0]["field"] == field


def test_malformed_json_is_bad_request(table: Table) -> None:
    reply = call("POST", "/api/groups", raw_body="{not json")

    assert reply.status == 400
    assert reply.body["error"]["code"] == "BAD_REQUEST"


def test_tokens_are_checked_on_every_route(table: Table, clock: Clock) -> None:
    seed_place(table, clock)
    created = create()
    gid = created.body["group"]["groupId"]
    invite = created.body["group"]["inviteToken"]
    jamie = join(created, "Jamie")

    assert call("GET", f"/api/groups/{gid}").status == 401
    assert call("GET", f"/api/groups/{gid}", token="wrong").status == 401
    # The invite link may only join.
    assert call("GET", f"/api/groups/{gid}", token=invite).status == 403
    # A member token cannot join again.
    member_join = call(
        "POST", f"/api/groups/{gid}/members", {"name": "Sam"}, jamie.body["memberToken"]
    )
    assert member_join.status == 403
    # Jamie cannot edit Alex.
    edit_other = call(
        "PUT",
        f"/api/groups/{gid}/members/{created.body['memberId']}",
        preferences("Alex"),
        jamie.body["memberToken"],
    )
    assert edit_other.status == 403


def test_authorization_scheme_is_case_insensitive(table: Table) -> None:
    created = create()
    gid = created.body["group"]["groupId"]
    event_token = created.body["memberToken"]

    reply = call("GET", f"/api/groups/{gid}", token=event_token)
    assert reply.status == 200

    lower = http.handler(
        {
            "version": "2.0",
            "routeKey": "$default",
            "rawPath": f"/api/groups/{gid}",
            "rawQueryString": "",
            "headers": {"authorization": f"bearer {event_token}"},
            "requestContext": {
                "http": {"method": "GET", "path": f"/api/groups/{gid}"},
                "requestId": "test-request",
                "stage": "$default",
            },
            "isBase64Encoded": False,
        },
        FakeContext(),  # type: ignore[arg-type]
    )
    assert lower["statusCode"] == 200


@pytest.mark.parametrize("gid", ["missing-group", "bad id!", "x" * 65])
def test_unknown_or_malformed_group_is_not_found(table: Table, gid: str) -> None:
    reply = call("GET", f"/api/groups/{gid.replace(' ', '%20')}", token="any")

    assert reply.status == 404
    assert reply.body["error"]["code"] == "NOT_FOUND"


def test_expired_group_is_not_found_on_reload(table: Table, clock: Clock) -> None:
    created = create()
    gid = created.body["group"]["groupId"]

    clock.now += timedelta(days=30, seconds=1)
    reply = call("GET", f"/api/groups/{gid}", token=created.body["memberToken"])

    assert reply.status == 404


def test_save_requires_a_resolved_place(table: Table) -> None:
    created = create()
    gid, mid = created.body["group"]["groupId"], created.body["memberId"]

    reply = call(
        "PUT",
        f"/api/groups/{gid}/members/{mid}",
        preferences("Alex"),
        created.body["memberToken"],
    )
    assert reply.status == 404
    assert "Place" in reply.body["error"]["message"]


def test_storage_faults_use_the_error_envelope(
    table: Table, monkeypatch: pytest.MonkeyPatch
) -> None:
    def throttled() -> GroupStore:
        raise ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException"}}, "Query"
        )

    monkeypatch.setattr(http, "group_store", throttled)
    reply = call("GET", "/api/groups/abc", token="any")

    assert reply.status == 503
    assert reply.body["error"]["code"] == "SERVICE_UNAVAILABLE"


@pytest.mark.parametrize(
    "fault",
    [
        EndpointConnectionError(endpoint_url="https://dynamodb.example"),
        ConnectTimeoutError(endpoint_url="https://dynamodb.example"),
        ReadTimeoutError(endpoint_url="https://dynamodb.example"),
        ConnectionClosedError(endpoint_url="https://dynamodb.example"),
    ],
    ids=type,
)
def test_storage_transport_faults_are_service_unavailable(
    table: Table, monkeypatch: pytest.MonkeyPatch, fault: Exception
) -> None:
    def unreachable() -> GroupStore:
        raise fault

    monkeypatch.setattr(http, "group_store", unreachable)
    reply = call("GET", "/api/groups/abc", token="secret-token")

    assert reply.status == 503
    assert reply.body["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "secret-token" not in json.dumps(reply.body)


@pytest.mark.parametrize(
    ("method", "path", "model", "required"),
    [
        ("post", "/groups", "CreateGroupRequest", ["groupName", "size", "name"]),
        ("post", "/groups/{group_id}/members", "JoinGroupRequest", ["name"]),
        (
            "put",
            "/groups/{group_id}/members/{member_id}",
            "PreferencesRequest",
            ["name", "placeId", "budget", "maxCommute"],
        ),
    ],
)
def test_openapi_documents_request_bodies(
    method: str, path: str, model: str, required: list[str]
) -> None:
    operation = http.app.get_openapi_schema().model_dump(
        by_alias=True, exclude_none=True
    )["paths"][path][method]

    body = operation["requestBody"]
    schema = body["content"]["application/json"]["schema"]
    assert body["required"] is True
    assert schema["title"] == model
    assert schema["required"] == required


def test_openapi_request_body_keeps_constraints() -> None:
    operation = http.app.get_openapi_schema().model_dump(
        by_alias=True, exclude_none=True
    )["paths"]["/groups/{group_id}/members/{member_id}"]["put"]
    props = operation["requestBody"]["content"]["application/json"]["schema"][
        "properties"
    ]

    assert (props["budget"]["minimum"], props["budget"]["maximum"]) == (300, 5000)
    assert (props["maxCommute"]["minimum"], props["maxCommute"]["maximum"]) == (
        10,
        120,
    )


def test_missing_table_configuration_is_service_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TABLE_NAME", raising=False)
    storage.group_store.cache_clear()
    monkeypatch.setattr(http, "group_store", storage.group_store)

    reply = call("POST", "/api/groups", {"groupName": "Flat", "size": 2, "name": "A"})

    assert reply.status == 503
    assert reply.body["error"]["code"] == "SERVICE_UNAVAILABLE"
