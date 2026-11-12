"""DynamoDB group persistence; no HTTP routes or AWS configuration side effects.

Construct GroupStore with a boto3 DynamoDB Table. Resource clients marshal native
Python values in transactions. All group writes share the original fixed TTL.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from random import uniform
from time import sleep
from typing import TYPE_CHECKING, Any

from flatsplit_api.errors import ApiError, not_found, validation_failed
from flatsplit_api.group_models import (
    CreateGroupRequest,
    GroupState,
    JoinGroupRequest,
    Membership,
    MemberState,
    PreferencesRequest,
)
from flatsplit_api.models import Place

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

GROUP_LIFETIME = timedelta(days=30)


def _hash(token: str | None) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def _name_key(name: str) -> str:
    return unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", name).casefold())


def _unauthorized() -> ApiError:
    return ApiError(401, "UNAUTHORIZED", "A valid token for this group is required.")


def _forbidden() -> ApiError:
    return ApiError(403, "FORBIDDEN", "This token cannot perform that operation.")


def _duplicate_name() -> ApiError:
    return validation_failed("name", "This name is already used in the group.")


@dataclass
class _Snapshot:
    meta: dict[str, Any]
    members: list[dict[str, Any]]


class GroupStore:
    def __init__(
        self, table: Table, *, clock: Callable[[], datetime] | None = None
    ) -> None:
        self.table = table
        # boto3-stubs describes a low-level client; a resource client additionally
        # installs native-value marshalling, including for TransactWriteItems.
        self._client: Any = table.meta.client
        self._clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        return self._clock().astimezone(UTC)

    def _load(self, group_id: str) -> _Snapshot:
        items: list[dict[str, Any]] = []
        for page in self._client.get_paginator("query").paginate(
            TableName=self.table.name,
            KeyConditionExpression="pk = :pk",
            ExpressionAttributeValues={":pk": f"GROUP#{group_id}"},
            ConsistentRead=True,
        ):
            items.extend(page.get("Items", []))
        meta = next((item for item in items if item["sk"] == "META"), None)
        if meta is None or meta["ttl"] <= int(self._now().timestamp()):
            raise not_found("Group not found or expired.")
        return _Snapshot(meta, [i for i in items if i["sk"].startswith("MEMBER#")])

    @staticmethod
    def _member(snapshot: _Snapshot, token: str | None) -> dict[str, Any]:
        digest = _hash(token)
        for member in snapshot.members:
            if hmac.compare_digest(member["tokenHash"], digest):
                return member
        if hmac.compare_digest(snapshot.meta["inviteTokenHash"], digest):
            raise _forbidden()
        raise _unauthorized()

    @staticmethod
    def _invite(snapshot: _Snapshot, token: str | None) -> None:
        digest = _hash(token)
        if hmac.compare_digest(snapshot.meta["inviteTokenHash"], digest):
            return
        if any(hmac.compare_digest(m["tokenHash"], digest) for m in snapshot.members):
            raise _forbidden()
        raise _unauthorized()

    @staticmethod
    def _view(group_id: str, snapshot: _Snapshot) -> GroupState:
        members = [
            MemberState(
                memberId=m["memberId"],
                name=m["name"],
                isOrganiser=m["memberId"] == snapshot.meta["organiserMemberId"],
                ready=m["ready"],
                destination=m["destination"],
                budget=m["budget"],
                maxCommute=m["maxCommute"],
            )
            for m in snapshot.members
        ]
        ready_count = sum(m.ready for m in members)
        return GroupState(
            groupId=group_id,
            groupName=snapshot.meta["groupName"],
            size=snapshot.meta["size"],
            revision=snapshot.meta["revision"],
            members=members,
            readyCount=ready_count,
            allReady=len(members) == snapshot.meta["size"]
            and ready_count == len(members),
            createdAt=snapshot.meta["createdAt"],
            expiresAt=datetime.fromtimestamp(int(snapshot.meta["ttl"]), UTC),
        )

    def read(self, group_id: str, token: str | None) -> GroupState:
        snapshot = self._load(group_id)
        self._member(snapshot, token)
        return self._view(group_id, snapshot)

    @staticmethod
    def _new_member(
        pk: str, name: str, ttl: int, joined_at: datetime, token: str | None = None
    ) -> tuple[dict[str, Any], str]:
        member_id = secrets.token_urlsafe(16)
        token = token if token is not None else secrets.token_urlsafe(32)
        return {
            "pk": pk,
            "sk": f"MEMBER#{joined_at.isoformat(timespec='microseconds')}#{member_id}",
            "memberId": member_id,
            "name": name,
            "nameKey": _name_key(name),
            "tokenHash": _hash(token),
            "ready": False,
            "placeId": None,
            "destination": None,
            "budget": None,
            "maxCommute": None,
            "ttl": ttl,
        }, token

    def _put(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "Put": {
                "TableName": self.table.name,
                "Item": item,
                "ConditionExpression": "attribute_not_exists(pk)",
            }
        }

    def _reservation(self, member: dict[str, Any]) -> dict[str, Any]:
        return self._put(
            {
                "pk": member["pk"],
                "sk": f"NAME#{member['nameKey']}",
                "memberId": member["memberId"],
                "ttl": member["ttl"],
            }
        )

    def create(self, request: CreateGroupRequest) -> Membership:
        now = self._now().replace(microsecond=0)
        ttl = int((now + GROUP_LIFETIME).timestamp())
        group_id = secrets.token_urlsafe(16)
        pk = f"GROUP#{group_id}"
        invite_token = secrets.token_urlsafe(32)
        member, member_token = self._new_member(pk, request.name, ttl, now)
        meta = {
            "pk": pk,
            "sk": "META",
            "groupName": request.groupName,
            "size": request.size,
            "revision": 1,
            "memberCount": 1,
            "organiserMemberId": member["memberId"],
            "inviteTokenHash": _hash(invite_token),
            "createdAt": now.isoformat(),
            "ttl": ttl,
        }
        self._client.transact_write_items(
            TransactItems=[
                self._put(meta),
                self._put(member),
                self._reservation(member),
            ]
        )
        return Membership(
            group=self.read(group_id, member_token),
            memberId=member["memberId"],
            memberToken=member_token,
            inviteToken=invite_token,
        )

    @staticmethod
    def _check_join(snapshot: _Snapshot, name: str) -> None:
        if snapshot.meta["memberCount"] >= snapshot.meta["size"]:
            raise ApiError(409, "GROUP_FULL", "This group has no places left.")
        if any(m["nameKey"] == _name_key(name) for m in snapshot.members):
            raise _duplicate_name()

    def _retry_conflicts[T](self, operation: Callable[[], T]) -> T:
        attempts = 0
        while True:
            try:
                return operation()
            except self._client.exceptions.TransactionCanceledException as exc:
                codes = {
                    reason.get("Code", "None")
                    for reason in exc.response.get("CancellationReasons", [])
                }
                if "TransactionConflict" not in codes or not codes <= {
                    "TransactionConflict",
                    "None",
                }:
                    raise
                attempts += 1
                if attempts == 3:
                    raise ApiError(
                        409, "CONFLICT", "The group is busy. Try again shortly."
                    ) from exc
                sleep(uniform(0.02, 0.1))
                # Retry the operation, not its stale transaction: expiry, capacity,
                # permissions and name reservations must be checked again.

    def join(
        self, group_id: str, token: str | None, request: JoinGroupRequest
    ) -> Membership:
        return self._retry_conflicts(lambda: self._join_once(group_id, token, request))

    def _join_once(
        self, group_id: str, token: str | None, request: JoinGroupRequest
    ) -> Membership:
        retry_member_token = None
        if request.retryToken is not None:
            # A retry can recover the exact capability without storing its value
            # or giving a second invite holder access based on a name alone.
            digest = hmac.digest(
                request.retryToken.encode(),
                f"flatsplit:join:v1:{group_id}".encode(),
                "sha256",
            )
            retry_member_token = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        snapshot = self._load(group_id)
        while True:
            self._invite(snapshot, token)
            if retry_member_token is not None:
                token_hash = _hash(retry_member_token)
                existing = next(
                    (
                        m
                        for m in snapshot.members
                        if hmac.compare_digest(m["tokenHash"], token_hash)
                    ),
                    None,
                )
                if existing is not None:
                    return Membership(
                        group=self._view(group_id, snapshot),
                        memberId=existing["memberId"],
                        memberToken=retry_member_token,
                    )
            self._check_join(snapshot, request.name)
            # A count CAS serializes joins (at most four can succeed). It also lets
            # us choose a strictly increasing timestamp even on tied/backward clocks.
            last_join = datetime.fromisoformat(snapshot.members[-1]["sk"].split("#")[1])
            now = self._now()
            joined_at = max(now, last_join + timedelta(microseconds=1))
            member, member_token = self._new_member(
                snapshot.meta["pk"],
                request.name,
                int(snapshot.meta["ttl"]),
                joined_at,
                retry_member_token,
            )
            update = {
                "Update": {
                    "TableName": self.table.name,
                    "Key": {"pk": snapshot.meta["pk"], "sk": "META"},
                    "UpdateExpression": "ADD memberCount :one, revision :one",
                    "ConditionExpression": (
                        "memberCount = :count AND memberCount < #size "
                        "AND #ttl > :now AND inviteTokenHash = :hash"
                    ),
                    "ExpressionAttributeNames": {"#size": "size", "#ttl": "ttl"},
                    "ExpressionAttributeValues": {
                        ":one": 1,
                        ":count": snapshot.meta["memberCount"],
                        ":now": int(now.timestamp()),
                        ":hash": _hash(token),
                    },
                }
            }
            try:
                self._client.transact_write_items(
                    TransactItems=[update, self._put(member), self._reservation(member)]
                )
            except self._client.exceptions.TransactionCanceledException as exc:
                # Only classify failed conditions. Throttling/conflicts/provider
                # faults must not be disguised as validation or capacity errors.
                if not self._conditional_failure(exc):
                    raise
                current = self._load(group_id)
                if current.meta["memberCount"] == snapshot.meta["memberCount"]:
                    self._invite(current, token)
                    self._check_join(current, request.name)
                    raise
                snapshot = current
                continue
            return Membership(
                group=self.read(group_id, member_token),
                memberId=member["memberId"],
                memberToken=member_token,
            )

    @staticmethod
    def _conditional_failure(error: Any) -> bool:
        codes = {
            r.get("Code", "None") for r in error.response.get("CancellationReasons", [])
        }
        return "ConditionalCheckFailed" in codes and codes <= {
            "None",
            "ConditionalCheckFailed",
        }

    @staticmethod
    def _own_member(
        snapshot: _Snapshot, token: str | None, member_id: str
    ) -> dict[str, Any]:
        member = GroupStore._member(snapshot, token)
        if not any(m["memberId"] == member_id for m in snapshot.members):
            raise not_found("Member not found.")
        if member["memberId"] != member_id:
            raise _forbidden()
        return member

    def _place(self, place_id: str) -> Place:
        item: dict[str, Any] | None = self.table.get_item(
            Key={"pk": f"PLACE#{place_id}", "sk": "META"}, ConsistentRead=True
        ).get("Item")
        if item is None or item["ttl"] <= int(self._now().timestamp()):
            raise not_found(
                "Place not found or expired. Search for the destination again."
            )
        return Place.model_validate({**item, "placeId": place_id})

    def save_preferences(
        self,
        group_id: str,
        member_id: str,
        token: str | None,
        request: PreferencesRequest,
    ) -> GroupState:
        return self._retry_conflicts(
            lambda: self._save_preferences_once(group_id, member_id, token, request)
        )

    def _save_preferences_once(
        self,
        group_id: str,
        member_id: str,
        token: str | None,
        request: PreferencesRequest,
    ) -> GroupState:
        snapshot = self._load(group_id)
        member = self._own_member(snapshot, token, member_id)
        name_key = _name_key(request.name)
        if any(
            m["nameKey"] == name_key and m["memberId"] != member_id
            for m in snapshot.members
        ):
            raise _duplicate_name()
        destination = self._place(request.placeId)
        # JSON conversion preserves decimal money/coordinate values for DynamoDB.
        stored_destination = json.loads(
            destination.model_dump_json(), parse_float=Decimal
        )
        now = int(self._now().timestamp())
        operations = [
            {
                "Update": {
                    "TableName": self.table.name,
                    "Key": {"pk": snapshot.meta["pk"], "sk": "META"},
                    "UpdateExpression": "ADD revision :one",
                    "ConditionExpression": "#ttl > :now",
                    "ExpressionAttributeNames": {"#ttl": "ttl"},
                    "ExpressionAttributeValues": {":one": 1, ":now": now},
                }
            },
            {
                "Update": {
                    "TableName": self.table.name,
                    "Key": {"pk": member["pk"], "sk": member["sk"]},
                    "UpdateExpression": (
                        "SET #name = :name, nameKey = :key, placeId = :place, "
                        "destination = :destination, budget = :budget, "
                        "maxCommute = :commute, ready = :ready"
                    ),
                    "ConditionExpression": "tokenHash = :hash AND nameKey = :oldKey",
                    "ExpressionAttributeNames": {"#name": "name"},
                    "ExpressionAttributeValues": {
                        ":name": request.name,
                        ":key": name_key,
                        ":place": request.placeId,
                        ":destination": stored_destination,
                        ":budget": Decimal(str(request.budget)),
                        ":commute": request.maxCommute,
                        ":ready": True,
                        ":hash": _hash(token),
                        ":oldKey": member["nameKey"],
                    },
                }
            },
            {
                "ConditionCheck": {
                    "TableName": self.table.name,
                    "Key": {"pk": f"PLACE#{request.placeId}", "sk": "META"},
                    "ConditionExpression": "#ttl > :now",
                    "ExpressionAttributeNames": {"#ttl": "ttl"},
                    "ExpressionAttributeValues": {":now": now},
                }
            },
        ]
        if name_key != member["nameKey"]:
            operations.extend(
                [
                    self._reservation({**member, "nameKey": name_key}),
                    {
                        "Delete": {
                            "TableName": self.table.name,
                            "Key": {
                                "pk": member["pk"],
                                "sk": f"NAME#{member['nameKey']}",
                            },
                            "ConditionExpression": "memberId = :id",
                            "ExpressionAttributeValues": {":id": member_id},
                        }
                    },
                ]
            )
        try:
            self._client.transact_write_items(TransactItems=operations)
        except self._client.exceptions.TransactionCanceledException as exc:
            if not self._conditional_failure(exc):
                raise
            current = self._load(group_id)
            current_member = self._own_member(current, token, member_id)
            self._place(request.placeId)
            if any(
                m["nameKey"] == name_key and m["memberId"] != member_id
                for m in current.members
            ):
                raise _duplicate_name() from exc
            if current_member["nameKey"] != member["nameKey"]:
                raise ApiError(
                    409,
                    "CONFLICT",
                    "Your name changed during this save. Reload and try again.",
                ) from exc
            raise
        return self.read(group_id, token)
