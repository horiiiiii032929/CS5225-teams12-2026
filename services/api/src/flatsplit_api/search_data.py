"""Pinned rent snapshots and raw commute records for search orchestration.

Only the immutable snapshot named by a search is queried on result reads. The
packaged town projection is versioned alongside the API, not loaded from docs.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal
from importlib.resources import files
from typing import TYPE_CHECKING, Any, cast

from boto3.dynamodb.conditions import Key

from flatsplit_api import ranking
from flatsplit_api.errors import ApiError

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

TOWN_POINTS: dict[str, dict[str, Any]] = json.loads(
    files("flatsplit_api").joinpath("towns.json").read_text(encoding="utf-8")
)

_FLAT_TYPES = {2: "3-ROOM", 3: "4-ROOM", 4: "5-ROOM", 5: "5-ROOM"}
_PERIOD = re.compile(r"\d{4}-(?:0[1-9]|1[0-2])/\d{4}-(?:0[1-9]|1[0-2])")
_RENT_AMOUNTS = ("median", "p25", "p75", "medianCi95Low", "medianCi95High")


@dataclass(frozen=True)
class RentPin:
    snapshot_id: str
    period: str
    flat_type: str


def _unavailable() -> ApiError:
    return ApiError(503, "SERVICE_UNAVAILABLE", "Rental data is unavailable.")


def _positive_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float, Decimal))
        and not isinstance(value, bool)
        and (value.is_finite() if isinstance(value, Decimal) else math.isfinite(value))
        and value > 0
    )


def _rent_summary(item: dict[str, Any]) -> ranking.RentSummary:
    """Reject corrupt evidence instead of converting it into a missing summary."""
    if not all(_positive_number(item.get(field)) for field in _RENT_AMOUNTS):
        raise _unavailable()
    count = item.get("count", 0)
    quality = item.get("qualityStatus")
    if (
        not _positive_number(count)
        or count != int(count)
        or quality not in ("USABLE", "LOW_CONFIDENCE")
        or not item["p25"] <= item["median"] <= item["p75"]
        or item["medianCi95Low"] > item["medianCi95High"]
    ):
        raise _unavailable()
    return ranking.RentSummary(
        median=item["median"],
        p25=item["p25"],
        p75=item["p75"],
        medianCi95Low=item["medianCi95Low"],
        medianCi95High=item["medianCi95High"],
        count=int(count),
        qualityStatus=cast("ranking.QualityStatus", quality),
    )


class SearchDataReader:
    def __init__(self, table: Table) -> None:
        self.table = table
        # The resource client retains native-value marshalling for paginator calls.
        self._client: Any = table.meta.client

    def pin(self, size: int) -> RentPin:
        flat_type = _FLAT_TYPES[size]
        item = self.table.get_item(
            Key={"pk": "RENT", "sk": "CURRENT"}, ConsistentRead=True
        ).get("Item")
        if not item:
            raise _unavailable()
        snapshot_id = item.get("snapshotId")
        period = item.get("period")
        if (
            not isinstance(snapshot_id, str)
            or not snapshot_id.strip()
            or not isinstance(period, str)
            or _PERIOD.fullmatch(period) is None
            or period[:7] > period[8:]
            or item.get("schemaVersion", 1) != 1
        ):
            raise _unavailable()
        return RentPin(snapshot_id, period, flat_type)

    def _town_items(self, partition: str) -> Iterator[dict[str, Any]]:
        for page in self._client.get_paginator("query").paginate(
            TableName=self.table.name,
            KeyConditionExpression=Key("pk").eq(partition)
            & Key("sk").begins_with("TOWN#"),
            ConsistentRead=True,
        ):
            yield from page.get("Items", [])

    def rents(self, snapshot_id: str, flat_type: str) -> dict[str, ranking.RentSummary]:
        summaries: dict[str, ranking.RentSummary] = {}
        for item in self._town_items(f"RENT#{snapshot_id}"):
            if item.get("flatType") != flat_type:
                # A matching key with a missing/wrong attribute is corrupt, not absent.
                if item["sk"].endswith(f"#{flat_type}"):
                    raise _unavailable()
                continue
            town = item.get("town")
            if (
                not isinstance(town, str)
                or not town.strip()
                or item["sk"] != f"TOWN#{town}#{flat_type}"
                or item.get("schemaVersion", 1) != 1
            ):
                raise _unavailable()
            summaries[town] = _rent_summary(item)
        return summaries

    def commutes(
        self, station_keys: Sequence[str]
    ) -> dict[tuple[str, str], dict[str, Any]]:
        records: dict[tuple[str, str], dict[str, Any]] = {}
        for station in dict.fromkeys(station_keys):
            for item in self._town_items(f"COMMUTE#{station}"):
                records[station, item["sk"].removeprefix("TOWN#")] = item
        return records
