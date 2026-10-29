"""Build versioned town/flat-type rent summaries from a validated HDB snapshot."""

from __future__ import annotations

import csv
import hashlib
import io
import random
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from flatsplit_api.rental_ingestion import EXPECTED_COLUMNS, ValidationSummary

BOOTSTRAP_REPLICATES = 10_000
SUMMARY_SCHEMA_VERSION = 1
SUMMARY_ALGORITHM_VERSION = "r7-block-bootstrap-v1"
MIN_BLOCKS_FOR_USABLE = 2
QUALITY_RELATIVE_WIDTH = 0.10
QualityStatus = Literal["USABLE", "LOW_CONFIDENCE"]


@dataclass(frozen=True)
class RentRecord:
    month: str
    town: str
    block: str
    street_name: str
    flat_type: str
    rent: int


@dataclass(frozen=True)
class RentSummary:
    town: str
    flat_type: str
    source_month_from: str
    source_month_to: str
    median: float
    p25: float
    p75: float
    count: int
    block_count: int
    median_ci95_low: float
    median_ci95_high: float
    median_ci95_relative_width: float
    quality_status: QualityStatus

    def item(
        self,
        *,
        snapshot_id: str,
        source_updated_at: str | None,
        source_dataset_id: str,
    ) -> dict[str, object]:
        """Return the DynamoDB-compatible summary item."""
        return {
            "pk": f"RENT#{snapshot_id}",
            "sk": f"TOWN#{self.town}#{self.flat_type}",
            "schemaVersion": SUMMARY_SCHEMA_VERSION,
            "snapshotId": snapshot_id,
            "sourceDatasetId": source_dataset_id,
            "sourceUpdatedAt": source_updated_at,
            "sourceMonthFrom": self.source_month_from,
            "sourceMonthTo": self.source_month_to,
            "period": f"{self.source_month_from}/{self.source_month_to}",
            "town": self.town,
            "flatType": self.flat_type,
            "currency": "SGD",
            "unit": "whole-flat/month",
            "statistic": f"trailing-12-month-{SUMMARY_ALGORITHM_VERSION}-quantiles",
            "median": self.median,
            "p25": self.p25,
            "p75": self.p75,
            "count": self.count,
            "blockCount": self.block_count,
            "bootstrapMethod": "block-cluster-percentile",
            "bootstrapReplicates": BOOTSTRAP_REPLICATES,
            "medianCi95Low": self.median_ci95_low,
            "medianCi95High": self.median_ci95_high,
            "medianCi95RelativeWidth": self.median_ci95_relative_width,
            "qualityStatus": self.quality_status,
        }


def _linear_quantile(sorted_values: list[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("Cannot calculate a quantile for an empty sample.")
    position = (len(sorted_values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return (
        sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction
    )


def _month_in_window(month: str, summary: ValidationSummary) -> bool:
    return summary.source_month_from <= month <= summary.source_month_to


def parse_window_records(
    body: bytes, validation: ValidationSummary
) -> list[RentRecord]:
    """Parse the validated CSV and retain only its complete trailing window."""
    text = body.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != EXPECTED_COLUMNS:
        raise ValueError("Source columns do not match the validated schema.")

    records: list[RentRecord] = []
    for row in reader:
        if not row or not any(row.values()):
            continue
        month = row["rent_approval_date"]
        if _month_in_window(month, validation):
            records.append(
                RentRecord(
                    month=month,
                    town=row["town"],
                    block=row["block"],
                    street_name=row["street_name"],
                    flat_type=row["flat_type"],
                    rent=int(row["monthly_rent"]),
                )
            )
    if not records:
        raise ValueError("Validated source contains no records in the summary window.")
    return records


def _block_bootstrap_medians(
    records: list[RentRecord], *, seed: int, replicates: int
) -> list[float]:
    blocks: dict[tuple[str, str], list[int]] = defaultdict(list)
    for record in records:
        blocks[record.street_name, record.block].append(record.rent)
    block_values = list(blocks.values())
    if len(block_values) == 1:
        median = float(_linear_quantile(sorted(block_values[0]), 0.5))
        return [median] * replicates

    ordered_rows = sorted(
        (rent, block_index)
        for block_index, values in enumerate(block_values)
        for rent in values
    )
    generator = random.Random(seed)
    block_count = len(block_values)
    medians: list[float] = []
    for _ in range(replicates):
        selections = [0] * block_count
        for _ in range(block_count):
            selections[generator.randrange(block_count)] += 1
        target = sum(
            len(values) * selections[index] for index, values in enumerate(block_values)
        )
        midpoint = (target - 1) / 2
        cumulative = 0
        lower: int | None = None
        upper: int | None = None
        for rent, block_index in ordered_rows:
            cumulative += selections[block_index]
            if lower is None and cumulative > midpoint:
                lower = rent
            if cumulative > midpoint + 0.5:
                upper = rent
                break
        if lower is None or upper is None:
            raise RuntimeError("Bootstrap sample was unexpectedly empty.")
        medians.append((lower + upper) / 2)
    return medians


def _seed_for(town: str, flat_type: str) -> int:
    digest = hashlib.sha256(f"rent-v1|{town}|{flat_type}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def aggregate_group(
    records: Iterable[RentRecord],
    *,
    source_month_from: str,
    source_month_to: str,
    bootstrap_replicates: int = BOOTSTRAP_REPLICATES,
) -> RentSummary:
    """Aggregate one non-empty town/flat-type group."""
    sample = list(records)
    if not sample:
        raise ValueError("Cannot aggregate an empty group.")
    values = sorted(float(record.rent) for record in sample)
    median = _linear_quantile(values, 0.5)
    bootstrap = sorted(
        _block_bootstrap_medians(
            sample,
            seed=_seed_for(sample[0].town, sample[0].flat_type),
            replicates=bootstrap_replicates,
        )
    )
    ci_low = _linear_quantile(bootstrap, 0.025)
    ci_high = _linear_quantile(bootstrap, 0.975)
    relative_width = (ci_high - ci_low) / median
    block_count = len({(record.street_name, record.block) for record in sample})
    return RentSummary(
        town=sample[0].town,
        flat_type=sample[0].flat_type,
        source_month_from=source_month_from,
        source_month_to=source_month_to,
        median=median,
        p25=_linear_quantile(values, 0.25),
        p75=_linear_quantile(values, 0.75),
        count=len(sample),
        block_count=block_count,
        median_ci95_low=ci_low,
        median_ci95_high=ci_high,
        median_ci95_relative_width=relative_width,
        quality_status=(
            "USABLE"
            if block_count >= MIN_BLOCKS_FOR_USABLE
            and relative_width <= QUALITY_RELATIVE_WIDTH
            else "LOW_CONFIDENCE"
        ),
    )


def aggregate_snapshot(
    body: bytes,
    validation: ValidationSummary,
    *,
    bootstrap_replicates: int = BOOTSTRAP_REPLICATES,
) -> list[RentSummary]:
    """Build one summary for every non-empty town/flat-type group."""
    groups: dict[tuple[str, str], list[RentRecord]] = defaultdict(list)
    for record in parse_window_records(body, validation):
        groups[record.town, record.flat_type].append(record)
    return [
        aggregate_group(
            records,
            source_month_from=validation.source_month_from,
            source_month_to=validation.source_month_to,
            bootstrap_replicates=bootstrap_replicates,
        )
        for _key, records in sorted(groups.items())
    ]
