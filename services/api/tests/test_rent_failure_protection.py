"""A rejected monthly rent file cannot change data used by searches."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import boto3
import pytest
from moto import mock_aws
from mypy_boto3_dynamodb.service_resource import Table

import flatsplit_api.handlers.ingest_rent as ingest_rent
from flatsplit_api import ranking
from flatsplit_api.rent_publication import RentSummaryPublisher
from flatsplit_api.rental_ingestion import (
    DataGovClient,
    DownloadedSource,
    SnapshotValidationError,
    ValidationSummary,
    run_ingestion,
)
from flatsplit_api.search_data import SearchDataReader


class InvalidClient(DataGovClient):
    def download(self) -> DownloadedSource:
        return DownloadedSource(
            b"rent_approval_date,town,block,street_name,flat_type,rent\n"
        )


class RejectedWriter:
    def __init__(self) -> None:
        self.reasons: list[str] = []

    def write_valid(
        self,
        source: DownloadedSource,
        summary: ValidationSummary,
        retrieved_at: datetime,
    ) -> Mapping[str, Any]:
        del source, summary, retrieved_at
        pytest.fail("an invalid source must not be written as valid")

    def write_rejected(
        self,
        source: DownloadedSource,
        reason: str,
        retrieved_at: datetime,
    ) -> Mapping[str, Any]:
        del source, retrieved_at
        self.reasons.append(reason)
        return {"status": "rejected"}


@pytest.fixture
def table() -> Iterator[Table]:
    with mock_aws():
        yield boto3.resource("dynamodb", region_name="ap-southeast-1").create_table(
            TableName="rent-failure-protection-test",
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


def seed_last_valid_snapshot(table: Table) -> None:
    table.put_item(
        Item={
            "pk": "RENT",
            "sk": "CURRENT",
            "schemaVersion": 1,
            "snapshotId": "snapshot-a",
            "period": "2025-10/2026-09",
        }
    )
    table.put_item(
        Item={
            "pk": "RENT#snapshot-a",
            "sk": "TOWN#QUEENSTOWN#4-ROOM",
            "schemaVersion": 1,
            "town": "QUEENSTOWN",
            "flatType": "4-ROOM",
            "median": Decimal("4150"),
            "p25": Decimal("3800"),
            "p75": Decimal("4400"),
            "medianCi95Low": Decimal("4000"),
            "medianCi95High": Decimal("4225"),
            "count": 433,
            "qualityStatus": "USABLE",
        }
    )


def recommendation(rents: dict[str, ranking.RentSummary]) -> ranking.Ranking:
    members = [
        ranking.MemberInput("one", "One", 3000, 60, "KENT_RIDGE"),
        ranking.MemberInput("two", "Two", 3000, 60, "KENT_RIDGE"),
        ranking.MemberInput("three", "Three", 3000, 60, "KENT_RIDGE"),
    ]
    return ranking.rank_towns(
        members,
        ["QUEENSTOWN"],
        rents,
        {("KENT_RIDGE", "QUEENSTOWN"): ranking.Commute("ok", 20)},
    )


def test_bad_file_preserves_pointer_and_search_result(table: Table) -> None:
    seed_last_valid_snapshot(table)
    reader = SearchDataReader(table)
    pin_before = reader.pin(3)
    rents_before = reader.rents(pin_before.snapshot_id, pin_before.flat_type)
    result_before = recommendation(rents_before)
    pointer_before = table.get_item(
        Key={"pk": "RENT", "sk": "CURRENT"}, ConsistentRead=True
    )["Item"]
    writer = RejectedWriter()

    with pytest.raises(SnapshotValidationError, match="six-column schema"):
        run_ingestion(
            InvalidClient(),
            writer,
            now=lambda: datetime(2026, 11, 3, tzinfo=UTC),
            publish=RentSummaryPublisher(table).publish,
        )

    pointer_after = table.get_item(
        Key={"pk": "RENT", "sk": "CURRENT"}, ConsistentRead=True
    )["Item"]
    pin_after = reader.pin(3)
    rents_after = reader.rents(pin_after.snapshot_id, pin_after.flat_type)
    result_after = recommendation(rents_after)
    assert len(writer.reasons) == 1
    assert pointer_after == pointer_before
    assert pin_after == pin_before
    assert rents_after == rents_before
    assert result_after == result_before


def test_handler_logs_failure_signal_and_raises(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("RENT_RAW_BUCKET", "rent-bucket")
    monkeypatch.setenv("RENT_TABLE_NAME", "rent-table")
    monkeypatch.setattr(boto3, "client", lambda *_a, **_k: object())

    class Resource:
        @staticmethod
        def Table(name: str) -> object:
            assert name == "rent-table"
            return object()

    monkeypatch.setattr(boto3, "resource", lambda *_a, **_k: Resource())

    def reject(*_args: Any, **_kwargs: Any) -> Mapping[str, Any]:
        raise SnapshotValidationError("Source columns changed.")

    monkeypatch.setattr(ingest_rent, "run_ingestion", reject)
    context = type(
        "Context",
        (),
        {
            "function_name": "rent-ingestion-test",
            "memory_limit_in_mb": 1024,
            "invoked_function_arn": "arn:aws:lambda:local:0:function:rent-test",
            "aws_request_id": "rent-test",
        },
    )()

    with pytest.raises(SnapshotValidationError, match="Source columns changed"):
        ingest_rent.handler({}, context)

    failures = [
        record
        for record in caplog.records
        if getattr(record, "rentIngestionFailed", False)
    ]
    assert len(failures) == 1
    assert failures[0].getMessage() == "HDB rental ingestion failed"
