"""Publish immutable rent summaries and the current snapshot pointer."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from flatsplit_api.rent_summary import (
    SUMMARY_ALGORITHM_VERSION,
    SUMMARY_SCHEMA_VERSION,
    aggregate_snapshot,
)
from flatsplit_api.rental_ingestion import (
    DATASET_ID,
    DownloadedSource,
    ValidationSummary,
)


def _ddb_value(value: object) -> object:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: _ddb_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_ddb_value(item) for item in value]
    return value


def _fixed_utc_timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("The raw rent pointer has no retrieval timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            "The raw rent pointer has an invalid retrieval timestamp."
        ) from exc
    if parsed.tzinfo is None:
        raise ValueError("The raw rent pointer retrieval timestamp has no timezone.")
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class RentSummaryPublisher:
    """Write a complete immutable snapshot before advancing `RENT/CURRENT`."""

    def __init__(self, table: Any) -> None:
        self._table = table

    @staticmethod
    def snapshot_id(source: DownloadedSource, validation: ValidationSummary) -> str:
        digest = hashlib.sha256(source.body).hexdigest()[:12]
        return (
            f"rent-v{SUMMARY_SCHEMA_VERSION}-{SUMMARY_ALGORITHM_VERSION}-"
            f"{validation.source_month_to}-{digest}"
        )

    def publish(
        self,
        source: DownloadedSource,
        validation: ValidationSummary,
        validated_at: datetime,
        raw_pointer: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        snapshot_id = self.snapshot_id(source, validation)
        raw_retrieved_at = _fixed_utc_timestamp(raw_pointer.get("retrievedAt"))
        summaries = aggregate_snapshot(source.body, validation)
        source_updated_at = (
            source.metadata.last_updated_at if source.metadata is not None else None
        )
        for summary in summaries:
            item = summary.item(
                snapshot_id=snapshot_id,
                source_updated_at=source_updated_at,
                source_dataset_id=DATASET_ID,
            )
            self._table.put_item(Item=_ddb_value(item))

        pointer: dict[str, object] = {
            "pk": "RENT",
            "sk": "CURRENT",
            "schemaVersion": 1,
            "snapshotId": snapshot_id,
            "period": f"{validation.source_month_from}/{validation.source_month_to}",
            "sourceMonthTo": validation.source_month_to,
            "validatedAt": validated_at.isoformat().replace("+00:00", "Z"),
            "rawRetrievedAt": raw_retrieved_at,
            "summaryCount": len(summaries),
            "rawSnapshotId": raw_pointer.get("snapshotId"),
        }
        self._table.put_item(
            Item=_ddb_value(pointer),
            ConditionExpression=(
                "attribute_not_exists(pk) OR sourceMonthTo < :source_month OR "
                "(sourceMonthTo = :source_month AND "
                "attribute_exists(rawRetrievedAt) AND "
                "rawRetrievedAt < :raw_retrieved_at)"
            ),
            ExpressionAttributeValues={
                ":source_month": validation.source_month_to,
                ":raw_retrieved_at": raw_retrieved_at,
            },
        )
        return pointer
