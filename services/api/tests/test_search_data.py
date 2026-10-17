"""Search input behavior against local DynamoDB; no provider or AWS calls."""

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import boto3
import pytest
from moto import mock_aws
from mypy_boto3_dynamodb.service_resource import Table

from flatsplit_api import ranking
from flatsplit_api.errors import ApiError
from flatsplit_api.search_data import RentPin, SearchDataReader


@pytest.fixture
def table() -> Iterator[Table]:
    with mock_aws():
        yield boto3.resource("dynamodb", region_name="ap-southeast-1").create_table(
            TableName="search-inputs-test",
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


def summary(
    town: str = "QUEENSTOWN", flat_type: str = "4-ROOM", **changes: Any
) -> dict[str, Any]:
    return {
        "pk": "RENT#snapshot-a",
        "sk": f"TOWN#{town}#{flat_type}",
        "town": town,
        "flatType": flat_type,
        "median": Decimal("4150.125"),
        "p25": Decimal("3800.25"),
        "p75": Decimal("4400.75"),
        "medianCi95Low": Decimal("4000.375"),
        "medianCi95High": Decimal("4200.625"),
        "count": 433,
        "qualityStatus": "USABLE",
        **changes,
    }


def pointer(table: Table, snapshot_id: str = "snapshot-a") -> None:
    table.put_item(
        Item={
            "pk": "RENT",
            "sk": "CURRENT",
            "schemaVersion": 1,
            "snapshotId": snapshot_id,
            "period": "2025-10/2026-09",
        }
    )


def paginate_one_item(
    table: Table, monkeypatch: pytest.MonkeyPatch
) -> list[dict[str, Any]]:
    """Exercise the real paginator while forcing service-side page boundaries."""
    client: Any = table.meta.client
    requests: list[dict[str, Any]] = []
    query = client.query
    get_paginator = client.get_paginator

    def observed_query(**kwargs: Any) -> Any:
        requests.append(kwargs)
        return query(**kwargs)

    def paginator(operation: str) -> Any:
        result = get_paginator(operation)
        paginate = result.paginate

        def pages(**kwargs: Any) -> Any:
            return paginate(**kwargs, PaginationConfig={"PageSize": 1})

        monkeypatch.setattr(result, "paginate", pages)
        return result

    monkeypatch.setattr(client, "query", observed_query)
    monkeypatch.setattr(client, "get_paginator", paginator)
    return requests


def test_pinned_snapshot_survives_pointer_flip(table: Table) -> None:
    pointer(table)
    table.put_item(Item=summary())
    table.put_item(Item=summary(pk="RENT#snapshot-b", median=Decimal("4300")))
    reader = SearchDataReader(table)
    pin = reader.pin(3)
    pointer(table, "snapshot-b")

    assert pin == RentPin("snapshot-a", "2025-10/2026-09", "4-ROOM")
    assert reader.rents(pin.snapshot_id, pin.flat_type)["QUEENSTOWN"].median == Decimal(
        "4150.125"
    )
    assert reader.pin(3).snapshot_id == "snapshot-b"


@pytest.mark.parametrize(
    ("size", "flat_type"), [(2, "3-ROOM"), (3, "4-ROOM"), (4, "5-ROOM"), (5, "5-ROOM")]
)
def test_pin_selects_occupancy_flat_type(
    table: Table, size: int, flat_type: str
) -> None:
    pointer(table)
    assert SearchDataReader(table).pin(size).flat_type == flat_type


@pytest.mark.parametrize(
    "item",
    [
        None,
        {},
        {"snapshotId": "", "period": "2025-10/2026-09"},
        {"snapshotId": "snapshot-a"},
        {"snapshotId": "snapshot-a", "period": "2025-13/2026-09"},
        {"snapshotId": "snapshot-a", "period": "2026-10/2026-09"},
        {"snapshotId": "snapshot-a", "period": "2025-10/2026-09", "schemaVersion": 2},
    ],
)
def test_unusable_pointer_is_service_unavailable(
    table: Table, item: dict[str, Any] | None
) -> None:
    if item is not None:
        table.put_item(Item={"pk": "RENT", "sk": "CURRENT", **item})
    with pytest.raises(ApiError) as error:
        SearchDataReader(table).pin(3)
    assert (error.value.status_code, error.value.code) == (503, "SERVICE_UNAVAILABLE")


def test_rents_paginate_filter_exact_type_and_preserve_fractions(
    table: Table, monkeypatch: pytest.MonkeyPatch
) -> None:
    table.put_item(Item=summary("BEDOK"))
    table.put_item(Item=summary("QUEENSTOWN"))
    # A different flat type must not overwrite the requested summary or be validated.
    table.put_item(Item=summary("QUEENSTOWN", "5-ROOM", median="not-a-number"))
    table.put_item(Item={"pk": "RENT#snapshot-a", "sk": "META"})
    requests = paginate_one_item(table, monkeypatch)
    rents = SearchDataReader(table).rents("snapshot-a", "4-ROOM")

    assert set(rents) == {"BEDOK", "QUEENSTOWN"}
    assert rents["BEDOK"] == ranking.RentSummary(
        median=Decimal("4150.125"),
        p25=Decimal("3800.25"),
        p75=Decimal("4400.75"),
        medianCi95Low=Decimal("4000.375"),
        medianCi95High=Decimal("4200.625"),
        count=433,
        qualityStatus="USABLE",
    )
    assert len(requests) == 3


def test_low_confidence_is_evidence_not_missing_or_rankable(table: Table) -> None:
    table.put_item(
        Item=summary(
            qualityStatus="LOW_CONFIDENCE",
            medianCi95Low=Decimal("3500.125"),
            medianCi95High=Decimal("4500.625"),
        )
    )
    rents = SearchDataReader(table).rents("snapshot-a", "4-ROOM")
    assert "BEDOK" not in rents
    members = [
        ranking.MemberInput("one", "One", 3000, 90, "KENT_RIDGE"),
        ranking.MemberInput("two", "Two", 3000, 90, "KENT_RIDGE"),
    ]
    result = ranking.rank_towns(
        members,
        ["QUEENSTOWN", "BEDOK"],
        rents,
        {
            ("KENT_RIDGE", town): ranking.Commute("ok", 20)
            for town in ("QUEENSTOWN", "BEDOK")
        },
    )
    assert result.ranked == []
    excluded = {area.town: area for area in result.excluded}
    low = excluded["QUEENSTOWN"]
    assert low.wholeFlatRent == 4150.125
    assert low.rentPerPerson == 2075.0625
    assert low.rentP25 == 3800.25
    assert low.rentP75 == 4400.75
    assert low.rentMedianCi95Low == 3500.125
    assert low.rentMedianCi95High == 4500.625
    assert low.rentSampleSize == 433
    assert low.rentQualityStatus == "LOW_CONFIDENCE"
    assert low.score is None
    assert all(member.budgetHeadroom is None for member in low.members)
    assert [reason.code for reason in low.reasons] == ["RENT_LOW_CONFIDENCE"]
    assert excluded["BEDOK"].wholeFlatRent is None
    assert [reason.code for reason in excluded["BEDOK"].reasons] == ["RENT_UNAVAILABLE"]


@pytest.mark.parametrize(
    "changes",
    [
        {"median": None},
        {"p25": "3800"},
        {"p75": -1},
        {"medianCi95Low": True},
        {"medianCi95High": 1},
        {"count": Decimal("2.5")},
        {"qualityStatus": "UNKNOWN"},
        {"town": "BEDOK"},
        {"flatType": "5-ROOM"},
    ],
)
def test_corrupt_selected_rent_fails_closed(
    table: Table, changes: dict[str, Any]
) -> None:
    item = summary()
    item.update(changes)
    table.put_item(Item=item)
    with pytest.raises(ApiError) as error:
        SearchDataReader(table).rents("snapshot-a", "4-ROOM")
    assert (error.value.status_code, error.value.code) == (503, "SERVICE_UNAVAILABLE")


def test_commutes_paginate_distinct_stations_and_keep_raw_claim_state(
    table: Table, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected: dict[tuple[str, str], dict[str, Any]] = {}
    for station in ("KENT_RIDGE", "BUONA_VISTA"):
        for town, status in (("BEDOK", "ok"), ("QUEENSTOWN", "pending")):
            item = {
                "pk": f"COMMUTE#{station}",
                "sk": f"TOWN#{town}",
                "status": status,
                "minutes": Decimal("27.125") if status == "ok" else None,
                "jobId": "claim-one",
                "leaseExpiresAt": 1792000000,
                "profile": "pt-v1:2026-10",
            }
            table.put_item(Item=item)
            expected[station, town] = item
        table.put_item(Item={"pk": f"COMMUTE#{station}", "sk": "META"})
    requests = paginate_one_item(table, monkeypatch)

    records = SearchDataReader(table).commutes(
        ["KENT_RIDGE", "KENT_RIDGE", "BUONA_VISTA"]
    )

    assert records == expected
    assert len(requests) == 4
