import csv
import io
from datetime import UTC, datetime
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from flatsplit_api.rent_publication import RentSummaryPublisher
from flatsplit_api.rental_ingestion import (
    DatasetMetadata,
    DownloadedSource,
    ValidationSummary,
)


class FakeTable:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def put_item(self, **kwargs: Any) -> None:
        self.items.append(kwargs)


def source_body() -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "rent_approval_date",
            "town",
            "block",
            "street_name",
            "flat_type",
            "monthly_rent",
        ]
    )
    writer.writerows(
        [
            ["2025-01", "BEDOK", "1", "ROAD A", "4-ROOM", "2000"],
            ["2025-02", "BEDOK", "1", "ROAD A", "4-ROOM", "2200"],
            ["2025-03", "BEDOK", "2", "ROAD B", "4-ROOM", "2400"],
        ]
    )
    return output.getvalue().encode()


def moto_table() -> Any:
    resource = boto3.resource("dynamodb", region_name="ap-southeast-1")
    return resource.create_table(
        TableName="rent-publication-test",
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


def metadata_source() -> DownloadedSource:
    return DownloadedSource(
        source_body(),
        metadata=DatasetMetadata(
            created_at="2025-01-01T00:00:00Z",
            last_updated_at="2025-04-01T00:00:00Z",
            coverage_start="2025-01",
            coverage_end="2025-03",
            dataset_size=3,
            source_format="CSV",
        ),
    )


def test_publisher_writes_summaries_before_current_pointer() -> None:
    source = DownloadedSource(source_body())
    validation = ValidationSummary(
        row_count=3,
        observed_month_from="2025-01",
        source_month_from="2025-01",
        source_month_to="2025-03",
        town_count=1,
        flat_type_count=1,
    )
    table = FakeTable()

    pointer = RentSummaryPublisher(table).publish(
        source,
        validation,
        datetime(2025, 4, 1, tzinfo=UTC),
        {
            "snapshotId": "hdb-rent-raw-test",
            "retrievedAt": "2025-04-01T00:00:00Z",
        },
    )

    assert str(pointer["snapshotId"]).startswith(
        "rent-v1-r7-block-bootstrap-v1-2025-03-"
    )
    assert len(table.items) == 2
    assert table.items[0]["Item"]["pk"].startswith(
        "RENT#rent-v1-r7-block-bootstrap-v1-2025-03-"
    )
    assert table.items[-1]["Item"]["pk"] == "RENT"
    assert table.items[-1]["ConditionExpression"] == (
        "attribute_not_exists(pk) OR sourceMonthTo < :source_month OR "
        "(sourceMonthTo = :source_month AND "
        "attribute_exists(rawRetrievedAt) AND "
        "rawRetrievedAt < :raw_retrieved_at)"
    )
    assert table.items[-1]["ExpressionAttributeValues"] == {
        ":source_month": "2025-03",
        ":raw_retrieved_at": "2025-04-01T00:00:00.000000Z",
    }


@pytest.mark.parametrize(
    ("first_retrieved", "second_retrieved", "second_succeeds"),
    [
        ("2025-04-01T00:00:00.100000Z", "2025-04-01T00:00:00Z", False),
        ("2025-04-01T00:00:00Z", "2025-04-01T00:00:00.100000Z", True),
    ],
)
def test_same_month_pointer_fence_orders_variable_precision_timestamps(
    first_retrieved: str, second_retrieved: str, second_succeeds: bool
) -> None:
    with mock_aws():
        table = moto_table()
        publisher = RentSummaryPublisher(table)
        source = metadata_source()
        validation = ValidationSummary(
            row_count=3,
            observed_month_from="2025-01",
            source_month_from="2025-01",
            source_month_to="2025-03",
            town_count=1,
            flat_type_count=1,
        )
        publisher.publish(
            source,
            validation,
            datetime(2025, 4, 1, tzinfo=UTC),
            {"snapshotId": "raw-first", "retrievedAt": first_retrieved},
        )

        if second_succeeds:
            publisher.publish(
                source,
                validation,
                datetime(2025, 4, 1, tzinfo=UTC),
                {"snapshotId": "raw-second", "retrievedAt": second_retrieved},
            )
        else:
            with pytest.raises(ClientError) as error:
                publisher.publish(
                    source,
                    validation,
                    datetime(2025, 4, 1, tzinfo=UTC),
                    {"snapshotId": "raw-second", "retrievedAt": second_retrieved},
                )
            assert (
                error.value.response["Error"]["Code"]
                == "ConditionalCheckFailedException"
            )

        current = table.get_item(Key={"pk": "RENT", "sk": "CURRENT"})["Item"]
        expected = second_retrieved if second_succeeds else first_retrieved
        expected = (
            datetime.fromisoformat(expected.replace("Z", "+00:00"))
            .astimezone(UTC)
            .strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        )
        assert current["rawRetrievedAt"] == expected
