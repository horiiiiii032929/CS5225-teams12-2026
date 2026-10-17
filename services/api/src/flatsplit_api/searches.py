"""Authenticated search snapshots, recoverable commute jobs and derived status.

A revision reservation makes simultaneous POSTs converge on one search. Search
records and their two lookup items share the group's fixed logical expiry.
"""

from __future__ import annotations

import json
import math
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from random import uniform
from time import sleep
from typing import TYPE_CHECKING, Any, Literal, cast

from boto3.dynamodb.conditions import Key

from flatsplit_api.commute_jobs import CommuteJobs, routing_profile
from flatsplit_api.errors import ApiError, not_found
from flatsplit_api.group_models import GroupState
from flatsplit_api.group_views import SearchSummary
from flatsplit_api.groups import GroupStore
from flatsplit_api.models import Station
from flatsplit_api.ranking import (
    WEIGHTS,
    Commute,
    MemberInput,
    Priority,
    RouteStatus,
    rank_towns,
)
from flatsplit_api.search_data import TOWN_POINTS, SearchDataReader
from flatsplit_api.search_models import SearchDataInfo, SearchProgress, SearchView

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table


class SearchStore:
    def __init__(
        self,
        table: Table,
        groups: GroupStore,
        reader: SearchDataReader,
        jobs: CommuteJobs,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.table = table
        self.groups = groups
        self.reader = reader
        self.jobs = jobs
        self._clock = clock or (lambda: datetime.now(UTC))
        # As in GroupStore, the resource client marshals native transaction values.
        self._client: Any = table.meta.client

    def _get(self, group_id: str, sk: str) -> dict[str, Any] | None:
        return cast(
            dict[str, Any] | None,
            self.table.get_item(
                Key={"pk": f"GROUP#{group_id}", "sk": sk}, ConsistentRead=True
            ).get("Item"),
        )

    def _search(self, group_id: str, search_id: str) -> dict[str, Any]:
        pointer = self._get(group_id, f"SEARCH_ID#{search_id}")
        item = self._get(group_id, pointer["searchKey"]) if pointer else None
        if item is None or item["ttl"] <= int(self._clock().timestamp()):
            raise not_found("Search not found or expired.")
        return item

    def _create(self, group: GroupState, token: str | None) -> dict[str, Any]:
        pk = f"GROUP#{group.groupId}"
        revision_key = f"SEARCH_REV#{group.revision}"
        reservation = self._get(group.groupId, revision_key)
        if reservation is not None:
            return self._search(group.groupId, reservation["searchId"])
        pin = self.reader.pin(group.size)
        now = self._clock().astimezone(UTC)
        search_id = f"s_{secrets.token_urlsafe(16)}"
        created_at = now.isoformat(timespec="microseconds")
        stations = {
            m.destination.station.stationKey: m.destination.station
            for m in group.members
            if m.destination is not None
        }
        item = {
            "pk": pk,
            "sk": f"SEARCH#{created_at}#{search_id}",
            "searchId": search_id,
            "groupRevision": group.revision,
            "createdAt": created_at,
            "ttl": int(group.expiresAt.timestamp()),
            "rentSnapshotId": pin.snapshot_id,
            "rentPeriod": pin.period,
            "flatType": pin.flat_type,
            "routingProfileVersion": routing_profile(now),
            "stations": [
                json.loads(station.model_dump_json(), parse_float=Decimal)
                for station in stations.values()
            ],
            "pairs": [
                {"stationKey": station, "town": town}
                for station in stations
                for town in TOWN_POINTS
            ],
        }
        puts = [
            item,
            {
                "pk": pk,
                "sk": revision_key,
                "searchId": search_id,
                "searchKey": item["sk"],
                "ttl": item["ttl"],
            },
            {
                "pk": pk,
                "sk": f"SEARCH_ID#{search_id}",
                "searchKey": item["sk"],
                "ttl": item["ttl"],
            },
        ]
        try:
            self._client.transact_write_items(
                TransactItems=[
                    {
                        "ConditionCheck": {
                            "TableName": self.table.name,
                            "Key": {"pk": pk, "sk": "META"},
                            "ConditionExpression": "revision = :rev AND #ttl > :now",
                            "ExpressionAttributeNames": {"#ttl": "ttl"},
                            "ExpressionAttributeValues": {
                                ":rev": group.revision,
                                ":now": int(now.timestamp()),
                            },
                        }
                    },
                    *[
                        {
                            "Put": {
                                "TableName": self.table.name,
                                "Item": value,
                                "ConditionExpression": "attribute_not_exists(pk)",
                            }
                        }
                        for value in puts
                    ],
                ]
            )
        except self._client.exceptions.TransactionCanceledException as exc:
            codes = {
                reason.get("Code", "None")
                for reason in exc.response.get("CancellationReasons", [])
            }
            conflicts = {"ConditionalCheckFailed", "TransactionConflict"}
            if codes & conflicts and codes <= conflicts | {"None"}:
                reservation = self._get(group.groupId, revision_key)
                if reservation is not None:
                    return self._search(group.groupId, reservation["searchId"])
                if codes <= {"TransactionConflict", "None"}:
                    # A competing transaction may not have committed its
                    # reservation yet. Retry from a fresh authorised group read.
                    raise
                # Distinguish expired/invalid access from a retryable snapshot race.
                self.groups.read(group.groupId, token)
                raise ApiError(
                    409, "CONFLICT", "Group changed. Start the search again."
                ) from exc
            raise
        return item

    def start(self, group_id: str, token: str | None) -> SearchView:
        for attempt in range(3):
            group = self.groups.read(group_id, token)
            if not group.allReady:
                raise ApiError(
                    409, "GROUP_NOT_READY", "Every member must save preferences first."
                )
            try:
                item = self._create(group, token)
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
                if attempt == 2:
                    raise ApiError(
                        409, "CONFLICT", "Search is busy. Start the search again."
                    ) from exc
                sleep(uniform(0.02, 0.1))
            else:
                break
        profile = routing_profile(self._clock())
        if item["routingProfileVersion"] < profile:
            # A repeat keeps its search/rent snapshot, but refreshes the monthly
            # routing profile. Older invocations cannot roll a newer profile back.
            try:
                self.table.update_item(
                    Key={"pk": item["pk"], "sk": item["sk"]},
                    UpdateExpression="SET routingProfileVersion = :profile",
                    ConditionExpression=(
                        "routingProfileVersion < :profile AND #ttl > :now"
                    ),
                    ExpressionAttributeNames={"#ttl": "ttl"},
                    ExpressionAttributeValues={
                        ":profile": profile,
                        ":now": int(self._clock().timestamp()),
                    },
                )
            except self._client.exceptions.ConditionalCheckFailedException:
                pass  # Another repeat may already have advanced this profile.
            item = self._search(group_id, item["searchId"])
        return self._view(group, item, "balanced", recover=True, retry_unavailable=True)

    def read(
        self, group_id: str, search_id: str, token: str | None, priority: Priority
    ) -> SearchView:
        group = self.groups.read(group_id, token)
        return self._view(
            group, self._search(group_id, search_id), priority, recover=True
        )

    def _current(self, group: GroupState, item: dict[str, Any]) -> bool:
        meta = self._get(group.groupId, "META")
        if meta is None or meta["ttl"] <= int(self._clock().timestamp()):
            raise not_found("Group not found or expired.")
        return bool(
            meta["revision"] == item["groupRevision"]
            and group.revision == item["groupRevision"]
            and item["routingProfileVersion"] == routing_profile(self._clock())
        )

    def _routes(
        self,
        item: dict[str, Any],
        *,
        recover: bool,
        retry_unavailable: bool = False,
    ) -> dict[tuple[str, str], Commute]:
        stations = {
            value["stationKey"]: Station.model_validate(value)
            for value in item["stations"]
        }
        rows = self.reader.commutes(list(stations))
        routes = {}
        for pair in item["pairs"]:
            station, town = pair["stationKey"], pair["town"]
            row = rows.get((station, town))
            if recover:
                row = self.jobs.ensure(
                    stations[station],
                    town,
                    TOWN_POINTS[town],
                    item["routingProfileVersion"],
                    row,
                    retry_unavailable=retry_unavailable,
                )
            status = row.get("status") if row else None
            if (
                not row
                or row.get("routingProfileVersion") != item["routingProfileVersion"]
            ):
                status = "pending"
            minutes = None
            if status == "ok":
                value = row.get("minutes") if row else None
                if not isinstance(value, (int, float, Decimal)) or isinstance(
                    value, bool
                ):
                    raise ApiError(
                        503, "SERVICE_UNAVAILABLE", "Cached route is invalid."
                    )
                minutes = float(value)
                if not math.isfinite(minutes) or minutes < 0:
                    raise ApiError(
                        503, "SERVICE_UNAVAILABLE", "Cached route is invalid."
                    )
            elif status != "unavailable":
                status = "pending"
            routes[(station, town)] = Commute(cast(RouteStatus, status), minutes)
        return routes

    def _view(
        self,
        group: GroupState,
        item: dict[str, Any],
        priority: Priority,
        *,
        recover: bool,
        retry_unavailable: bool = False,
    ) -> SearchView:
        current = self._current(group, item)
        routes = (
            self._routes(item, recover=recover, retry_unavailable=retry_unavailable)
            if current
            else {}
        )
        progress = SearchProgress(
            total=len(item["pairs"]),
            resolved=sum(route.status != "pending" for route in routes.values()),
            unavailable=sum(route.status == "unavailable" for route in routes.values()),
        )
        response = SearchView(
            searchId=item["searchId"],
            groupRevision=item["groupRevision"],
            status="stale" if not current else "pending",
            progress=progress,
            priority=priority,
            weights=WEIGHTS[priority],
            data=SearchDataInfo(
                rentPeriod=item["rentPeriod"], flatType=item["flatType"]
            ),
            ranked=[],
            excluded=[],
        )
        if current and progress.resolved == progress.total:
            members = [
                MemberInput(
                    member.memberId,
                    member.name,
                    member.budget,
                    member.maxCommute,
                    member.destination.station.stationKey,
                )
                for member in group.members
                if member.destination is not None
                and member.budget is not None
                and member.maxCommute is not None
            ]
            ranking = rank_towns(
                members,
                list(TOWN_POINTS),
                self.reader.rents(item["rentSnapshotId"], item["flatType"]),
                routes,
                priority,
            )
            response.status = "complete"
            response.ranked = ranking.ranked
            response.excluded = ranking.excluded
        # Withhold results if preferences changed while the data was loading.
        if not self._current(group, item):
            response.status = "stale"
            response.ranked = []
            response.excluded = []
        return response

    def summary(self, group: GroupState) -> SearchSummary | None:
        rows = self.table.query(
            KeyConditionExpression=Key("pk").eq(f"GROUP#{group.groupId}")
            & Key("sk").begins_with("SEARCH#"),
            ScanIndexForward=False,
            Limit=1,
            ConsistentRead=True,
        ).get("Items", [])
        if not rows:
            return None
        item = rows[0]
        status: Literal["pending", "complete", "stale"] = "stale"
        if self._current(group, item):
            routes = self._routes(item, recover=False)
            status = (
                "pending"
                if any(r.status == "pending" for r in routes.values())
                else "complete"
            )
        return SearchSummary.model_validate(
            {
                "searchId": item["searchId"],
                "status": status,
                "createdAt": item["createdAt"],
            }
        )
