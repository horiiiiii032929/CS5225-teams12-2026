import csv
import io

from flatsplit_api.rent_summary import (
    RentRecord,
    aggregate_group,
    aggregate_snapshot,
    parse_window_records,
)
from flatsplit_api.rental_ingestion import ValidationSummary

VALIDATION = ValidationSummary(
    row_count=6,
    observed_month_from="2025-01",
    source_month_from="2025-01",
    source_month_to="2025-03",
    town_count=1,
    flat_type_count=1,
)


def csv_body(rows: list[list[str]]) -> bytes:
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
    writer.writerows(rows)
    return output.getvalue().encode()


def test_parse_window_records_excludes_rows_outside_trailing_window() -> None:
    body = csv_body(
        [
            ["2024-12", "BEDOK", "1", "ROAD", "4-ROOM", "1000"],
            ["2025-01", "BEDOK", "1", "ROAD", "4-ROOM", "2000"],
            ["2025-02", "BEDOK", "1", "ROAD", "4-ROOM", "3000"],
            ["2025-03", "BEDOK", "2", "ROAD", "4-ROOM", "4000"],
        ]
    )

    records = parse_window_records(body, VALIDATION)

    assert [record.rent for record in records] == [2000, 3000, 4000]


def test_aggregation_uses_linear_quantiles_and_records_shape() -> None:
    records = [
        # Two clusters make the bootstrap deterministic but non-degenerate.
        RentRecord("2025-01", "BEDOK", "1", "ROAD A", "4-ROOM", 1000),
        RentRecord("2025-02", "BEDOK", "1", "ROAD A", "4-ROOM", 2000),
        RentRecord("2025-03", "BEDOK", "2", "ROAD B", "4-ROOM", 3000),
    ]

    summary = aggregate_group(
        records,
        source_month_from="2025-01",
        source_month_to="2025-03",
        bootstrap_replicates=100,
    )

    assert summary.median == 2000
    assert summary.p25 == 1500
    assert summary.p75 == 2500
    assert summary.count == 3
    assert summary.block_count == 2
    assert summary.quality_status in {"USABLE", "LOW_CONFIDENCE"}


def test_single_block_group_is_retained_but_low_confidence() -> None:
    summary = aggregate_group(
        [
            RentRecord("2025-01", "TENGAH", "1", "ROAD A", "5-ROOM", 3000),
            RentRecord("2025-02", "TENGAH", "1", "ROAD A", "5-ROOM", 3000),
        ],
        source_month_from="2025-01",
        source_month_to="2025-02",
        bootstrap_replicates=100,
    )

    assert summary.block_count == 1
    assert summary.median_ci95_relative_width == 0
    assert summary.quality_status == "LOW_CONFIDENCE"


def test_snapshot_aggregates_non_empty_groups_and_is_reproducible() -> None:
    body = csv_body(
        [
            ["2025-01", "BEDOK", "1", "ROAD A", "4-ROOM", "2000"],
            ["2025-02", "BEDOK", "1", "ROAD A", "4-ROOM", "2200"],
            ["2025-03", "BEDOK", "2", "ROAD B", "4-ROOM", "2400"],
        ]
    )

    first = aggregate_snapshot(body, VALIDATION, bootstrap_replicates=100)
    second = aggregate_snapshot(body, VALIDATION, bootstrap_replicates=100)

    assert len(first) == 1
    assert first == second
    assert (
        first[0].item(
            snapshot_id="rent-v1-2025-03-test",
            source_updated_at="2025-04-01T00:00:00Z",
            source_dataset_id="dataset",
        )["sk"]
        == "TOWN#BEDOK#4-ROOM"
    )
