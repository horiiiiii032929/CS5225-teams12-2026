"""Download and preserve validated HDB rental source snapshots for issue #9."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any, Protocol

from botocore.exceptions import ClientError

DATASET_ID = "d_c9f57187485a850908655db0e8cfe651"
DATASET_TITLE = "Renting Out of Flats from Jan 2021"
PUBLISHER = "Housing & Development Board"
API_BASE_URL = "https://api-open.data.gov.sg/v1/public/api/datasets"
METADATA_BASE_URL = "https://api-production.data.gov.sg/v2/public/api/datasets"
EXPECTED_COLUMNS = (
    "rent_approval_date",
    "town",
    "block",
    "street_name",
    "flat_type",
    "monthly_rent",
)
EXPECTED_FLAT_TYPES = {
    "1-ROOM",
    "2-ROOM",
    "3-ROOM",
    "4-ROOM",
    "5-ROOM",
    "EXECUTIVE",
}
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_JSON_BYTES = 1024 * 1024
POLL_ATTEMPTS = 9
POLL_INTERVAL_SECONDS = 15.0
_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])\Z")


class IngestionError(RuntimeError):
    """The upstream export or snapshot write could not complete."""


class SnapshotValidationError(IngestionError):
    """The downloaded source is not safe to publish as the current snapshot."""


@dataclass(frozen=True)
class DatasetMetadata:
    created_at: str
    last_updated_at: str
    coverage_start: str
    coverage_end: str
    dataset_size: int
    source_format: str


@dataclass(frozen=True)
class DownloadedSource:
    body: bytes
    metadata: DatasetMetadata | None = None
    content_type: str | None = None
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True)
class ValidationSummary:
    row_count: int
    observed_month_from: str
    source_month_from: str
    source_month_to: str
    town_count: int
    flat_type_count: int


class SnapshotWriter(Protocol):
    def write_valid(
        self,
        source: DownloadedSource,
        summary: ValidationSummary,
        retrieved_at: datetime,
    ) -> Mapping[str, Any]: ...

    def write_rejected(
        self,
        source: DownloadedSource,
        reason: str,
        retrieved_at: datetime,
    ) -> Mapping[str, Any]: ...


def expected_towns() -> frozenset[str]:
    """Return the reviewed 27-town source inventory, including TENGAH."""
    raw = files("flatsplit_api").joinpath("hdb_rental_towns.json").read_text()
    values: Any = json.loads(raw)
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise RuntimeError("The packaged HDB town inventory is invalid.")
    return frozenset(values)


def _month_index(value: str) -> int:
    year, month = (int(part) for part in value.split("-"))
    return year * 12 + month - 1


def _format_month(index: int) -> str:
    year, zero_based_month = divmod(index, 12)
    return f"{year:04d}-{zero_based_month + 1:02d}"


def validate_source(body: bytes) -> ValidationSummary:
    """Validate the source profile without dropping or rewriting any row."""
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SnapshotValidationError("Source is not valid UTF-8 CSV.") from exc

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader)
    except StopIteration as exc:
        raise SnapshotValidationError("Source CSV is empty.") from exc
    except csv.Error as exc:
        raise SnapshotValidationError("Source CSV header is malformed.") from exc
    if tuple(header) != EXPECTED_COLUMNS:
        raise SnapshotValidationError(
            "Source columns do not match the reviewed six-column schema."
        )

    months: set[str] = set()
    towns: set[str] = set()
    flat_types: set[str] = set()
    row_count = 0
    try:
        for line_number, row in enumerate(reader, start=2):
            if not row or not any(row):
                continue
            if len(row) != len(EXPECTED_COLUMNS):
                raise SnapshotValidationError(
                    f"Row {line_number} does not contain exactly six fields."
                )
            for column, value in zip(EXPECTED_COLUMNS, row, strict=True):
                if not value or value != value.strip():
                    raise SnapshotValidationError(
                        f"Row {line_number} has a blank or padded {column}."
                    )

            month, town, _block, _street, flat_type, rent = row
            if not _MONTH.fullmatch(month):
                raise SnapshotValidationError(
                    f"Row {line_number} has an invalid rent_approval_date."
                )
            if flat_type not in EXPECTED_FLAT_TYPES:
                raise SnapshotValidationError(
                    f"Row {line_number} has an unexpected flat_type."
                )
            if not rent.isascii() or not rent.isdigit() or int(rent) <= 0:
                raise SnapshotValidationError(
                    f"Row {line_number} has an invalid monthly_rent."
                )
            months.add(month)
            towns.add(town)
            flat_types.add(flat_type)
            row_count += 1
    except csv.Error as exc:
        raise SnapshotValidationError("Source CSV body is malformed.") from exc

    if row_count == 0:
        raise SnapshotValidationError("Source CSV contains no data rows.")
    if towns != expected_towns():
        missing = sorted(expected_towns() - towns)
        unexpected = sorted(towns - expected_towns())
        raise SnapshotValidationError(
            f"Town inventory changed (missing={missing}, unexpected={unexpected})."
        )
    if flat_types != EXPECTED_FLAT_TYPES:
        raise SnapshotValidationError("Source does not contain all six flat types.")

    latest_index = max(_month_index(month) for month in months)
    source_month_from_index = latest_index - 11
    required_months = {
        _format_month(index)
        for index in range(source_month_from_index, latest_index + 1)
    }
    if not required_months.issubset(months):
        missing_months = sorted(required_months - months)
        raise SnapshotValidationError(
            f"Trailing 12 source months are incomplete (missing={missing_months})."
        )

    return ValidationSummary(
        row_count=row_count,
        observed_month_from=min(months, key=_month_index),
        source_month_from=_format_month(source_month_from_index),
        source_month_to=_format_month(latest_index),
        town_count=len(towns),
        flat_type_count=len(flat_types),
    )


class DataGovClient:
    """Bounded client for data.gov.sg's initiate/poll whole-dataset export."""

    def __init__(
        self,
        *,
        opener: Callable[..., Any] = urllib.request.urlopen,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._open = opener
        self._sleep = sleep

    @staticmethod
    def _read_bounded(response: Any, limit: int) -> bytes:
        body: bytes = response.read(limit + 1)
        if len(body) > limit:
            raise IngestionError("Upstream response exceeds the configured size limit.")
        return body

    def _get_json(self, url: str) -> Mapping[str, Any]:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "FlatSplit-rental-ingestion/1",
            },
        )
        try:
            with self._open(request, timeout=15.0) as response:
                raw = self._read_bounded(response, MAX_JSON_BYTES)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise IngestionError("data.gov.sg export API is unavailable.") from exc
        try:
            payload: Any = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IngestionError("data.gov.sg returned malformed JSON.") from exc
        if not isinstance(payload, dict):
            raise IngestionError("data.gov.sg returned an unexpected API response.")
        code = payload.get("code")
        if code not in (None, 0):
            detail = payload.get("errorMsg")
            suffix = f": {detail}" if isinstance(detail, str) and detail else ""
            raise IngestionError(
                f"data.gov.sg export API returned error code {code}{suffix}."
            )
        error = payload.get("errorMsg")
        if isinstance(error, str) and error.strip():
            raise IngestionError("data.gov.sg rejected the export request.")
        return payload

    def _metadata(self) -> DatasetMetadata:
        payload = self._get_json(f"{METADATA_BASE_URL}/{DATASET_ID}/metadata")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise IngestionError("data.gov.sg returned incomplete dataset metadata.")
        if (
            data.get("datasetId") != DATASET_ID
            or data.get("name") != DATASET_TITLE
            or data.get("managedBy") != PUBLISHER
            or data.get("format") != "CSV"
        ):
            raise IngestionError("data.gov.sg dataset identity or format changed.")

        columns = data.get("columnMetadata")
        order = columns.get("order") if isinstance(columns, dict) else None
        mapping = columns.get("map") if isinstance(columns, dict) else None
        if not isinstance(order, list) or not isinstance(mapping, dict):
            raise IngestionError("data.gov.sg column metadata is incomplete.")
        names = tuple(mapping.get(column_id) for column_id in order)
        if names != EXPECTED_COLUMNS:
            raise IngestionError("data.gov.sg metadata no longer matches the schema.")

        def required_text(key: str) -> str:
            value = data.get(key)
            if not isinstance(value, str) or not value:
                raise IngestionError("data.gov.sg dataset metadata is incomplete.")
            return value

        dataset_size = data.get("datasetSize")
        if not isinstance(dataset_size, int) or dataset_size <= 0:
            raise IngestionError("data.gov.sg dataset metadata is incomplete.")
        return DatasetMetadata(
            created_at=required_text("createdAt"),
            last_updated_at=required_text("lastUpdatedAt"),
            coverage_start=required_text("coverageStart"),
            coverage_end=required_text("coverageEnd"),
            dataset_size=dataset_size,
            source_format="CSV",
        )

    def download(self) -> DownloadedSource:
        metadata = self._metadata()
        dataset_url = f"{API_BASE_URL}/{DATASET_ID}"
        self._get_json(f"{dataset_url}/initiate-download")

        export_url: str | None = None
        for attempt in range(POLL_ATTEMPTS):
            payload = self._get_json(f"{dataset_url}/poll-download")
            data = payload.get("data")
            candidate = data.get("url") if isinstance(data, dict) else None
            if isinstance(candidate, str) and candidate.startswith("https://"):
                export_url = candidate
                break
            if attempt + 1 < POLL_ATTEMPTS:
                self._sleep(POLL_INTERVAL_SECONDS)
        if export_url is None:
            raise IngestionError(
                "data.gov.sg export was not ready before the deadline."
            )

        request = urllib.request.Request(
            export_url,
            headers={
                "Accept": "text/csv,application/octet-stream",
                "User-Agent": "FlatSplit-rental-ingestion/1",
            },
        )
        try:
            with self._open(request, timeout=60.0) as response:
                body = self._read_bounded(response, MAX_SOURCE_BYTES)
                headers = response.headers
                return DownloadedSource(
                    body=body,
                    metadata=metadata,
                    content_type=headers.get("Content-Type"),
                    etag=headers.get("ETag"),
                    last_modified=headers.get("Last-Modified"),
                )
        except (urllib.error.URLError, TimeoutError) as exc:
            raise IngestionError("The data.gov.sg CSV export is unavailable.") from exc


class S3SnapshotWriter:
    """Write immutable evidence first and replace the last-good pointer last."""

    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    @staticmethod
    def _json(value: Mapping[str, Any]) -> bytes:
        return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()

    def _put_immutable(self, key: str, body: bytes, content_type: str) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            IfNoneMatch="*",
        )

    def _current_pointer(self) -> tuple[dict[str, Any] | None, str | None]:
        try:
            response = self._client.get_object(
                Bucket=self._bucket,
                Key="raw/current.json",
            )
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code not in {"404", "NoSuchKey", "NotFound"}:
                raise IngestionError(
                    "Could not read the current rent pointer."
                ) from exc
            return None, None
        try:
            raw = response["Body"].read()
            pointer = json.loads(raw)
        except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IngestionError("The current rent pointer is malformed.") from exc
        if not isinstance(pointer, dict):
            raise IngestionError("The current rent pointer is malformed.")
        etag = response.get("ETag")
        if etag is not None and not isinstance(etag, str):
            raise IngestionError("The current rent pointer has an invalid ETag.")
        return pointer, etag

    @staticmethod
    def _is_older_than_current(
        pointer: Mapping[str, Any],
        summary: ValidationSummary,
        retrieved_at: datetime,
    ) -> bool:
        current_month = pointer.get("sourceMonthTo")
        if not isinstance(current_month, str) or not _MONTH.fullmatch(current_month):
            raise IngestionError(
                "The current rent pointer has an invalid source month."
            )
        current_index = _month_index(current_month)
        new_index = _month_index(summary.source_month_to)
        if current_index != new_index:
            return current_index > new_index

        current_retrieved = pointer.get("retrievedAt")
        if not isinstance(current_retrieved, str):
            return False
        try:
            current_time = datetime.fromisoformat(
                current_retrieved.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise IngestionError(
                "The current rent pointer has an invalid timestamp."
            ) from exc
        if current_time.tzinfo is None:
            raise IngestionError("The current rent pointer timestamp has no timezone.")
        return current_time > retrieved_at

    @staticmethod
    def _source_metadata(metadata: DatasetMetadata | None) -> dict[str, Any] | None:
        if metadata is None:
            return None
        return {
            "createdAt": metadata.created_at,
            "lastUpdatedAt": metadata.last_updated_at,
            "coverageStart": metadata.coverage_start,
            "coverageEnd": metadata.coverage_end,
            "datasetSize": metadata.dataset_size,
            "format": metadata.source_format,
        }

    def write_valid(
        self,
        source: DownloadedSource,
        summary: ValidationSummary,
        retrieved_at: datetime,
    ) -> Mapping[str, Any]:
        digest = hashlib.sha256(source.body).hexdigest()
        timestamp = retrieved_at.strftime("%Y%m%dT%H%M%SZ")
        prefix = (
            f"raw/source_month={summary.source_month_to}/"
            f"retrieved_at={timestamp}/{digest}"
        )
        raw_key = f"{prefix}.csv"
        manifest_key = f"{prefix}.manifest.json"
        snapshot_id = f"hdb-rent-raw-v1-{summary.source_month_to}-{digest[:12]}"
        manifest: dict[str, Any] = {
            "manifestVersion": 1,
            "status": "VALIDATED",
            "snapshotId": snapshot_id,
            "datasetId": DATASET_ID,
            "datasetTitle": DATASET_TITLE,
            "publisher": PUBLISHER,
            "sourceUpdatedAt": (
                source.metadata.last_updated_at if source.metadata else None
            ),
            "sourceMetadata": self._source_metadata(source.metadata),
            "retrievedAt": retrieved_at.isoformat().replace("+00:00", "Z"),
            "sha256": digest,
            "rawObjectKey": raw_key,
            "sourceHeaders": {
                "contentType": source.content_type,
                "etag": source.etag,
                "lastModified": source.last_modified,
            },
            **{
                "rowCount": summary.row_count,
                "observedMonthFrom": summary.observed_month_from,
                "sourceMonthFrom": summary.source_month_from,
                "sourceMonthTo": summary.source_month_to,
                "townCount": summary.town_count,
                "flatTypeCount": summary.flat_type_count,
            },
        }
        self._put_immutable(raw_key, source.body, "text/csv")
        self._put_immutable(manifest_key, self._json(manifest), "application/json")
        pointer = {
            "manifestVersion": 1,
            "snapshotId": snapshot_id,
            "sourceMonthTo": summary.source_month_to,
            "retrievedAt": manifest["retrievedAt"],
            "sha256": digest,
            "rawObjectKey": raw_key,
            "manifestObjectKey": manifest_key,
        }
        current, etag = self._current_pointer()
        if current is not None and self._is_older_than_current(
            current, summary, retrieved_at
        ):
            raise IngestionError(
                "The candidate rent snapshot is older than the current snapshot."
            )
        put_kwargs: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": "raw/current.json",
            "Body": self._json(pointer),
            "ContentType": "application/json",
        }
        if etag is not None:
            put_kwargs["IfMatch"] = etag
        try:
            self._client.put_object(**put_kwargs)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {
                "409",
                "412",
                "ConditionalRequestConflict",
                "PreconditionFailed",
            }:
                raise IngestionError(
                    "The current rent pointer changed during ingestion; retry."
                ) from exc
            raise
        return pointer

    def write_rejected(
        self,
        source: DownloadedSource,
        reason: str,
        retrieved_at: datetime,
    ) -> Mapping[str, Any]:
        digest = hashlib.sha256(source.body).hexdigest()
        timestamp = retrieved_at.strftime("%Y%m%dT%H%M%SZ")
        prefix = f"rejected/retrieved_at={timestamp}/{digest}"
        raw_key = f"{prefix}.csv"
        manifest_key = f"{prefix}.manifest.json"
        manifest = {
            "manifestVersion": 1,
            "status": "REJECTED",
            "datasetId": DATASET_ID,
            "datasetTitle": DATASET_TITLE,
            "publisher": PUBLISHER,
            "sourceUpdatedAt": (
                source.metadata.last_updated_at if source.metadata else None
            ),
            "sourceMetadata": self._source_metadata(source.metadata),
            "retrievedAt": retrieved_at.isoformat().replace("+00:00", "Z"),
            "sha256": digest,
            "rawObjectKey": raw_key,
            "reason": reason,
            "sourceHeaders": {
                "contentType": source.content_type,
                "etag": source.etag,
                "lastModified": source.last_modified,
            },
        }
        self._put_immutable(raw_key, source.body, "text/csv")
        self._put_immutable(manifest_key, self._json(manifest), "application/json")
        return {"rawObjectKey": raw_key, "manifestObjectKey": manifest_key}


def run_ingestion(
    client: DataGovClient,
    writer: SnapshotWriter,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    publish: Callable[
        [DownloadedSource, ValidationSummary, datetime, Mapping[str, Any]], object
    ]
    | None = None,
) -> Mapping[str, Any]:
    """Fetch once, preserving rejected bytes without changing last-good state."""
    retrieved_at = now()
    if retrieved_at.tzinfo is None:
        raise ValueError("Ingestion timestamps must be timezone-aware.")
    source = client.download()
    try:
        summary = validate_source(source.body)
    except SnapshotValidationError as exc:
        writer.write_rejected(source, str(exc), retrieved_at)
        raise
    if source.metadata is not None:
        coverage_month = source.metadata.coverage_end[:7]
        if not _MONTH.fullmatch(coverage_month):
            reason = "Source metadata has an invalid coverage end month."
            writer.write_rejected(source, reason, retrieved_at)
            raise SnapshotValidationError(reason)
        if coverage_month != summary.source_month_to:
            reason = "Source metadata coverage end does not match the latest CSV month."
            writer.write_rejected(source, reason, retrieved_at)
            raise SnapshotValidationError(reason)
    pointer = writer.write_valid(source, summary, retrieved_at)
    if publish is not None:
        publish(source, summary, retrieved_at, pointer)
    return pointer
