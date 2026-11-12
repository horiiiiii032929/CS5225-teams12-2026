import csv
import io
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from botocore.exceptions import ClientError

from flatsplit_api.rental_ingestion import (
    DATASET_ID,
    EXPECTED_COLUMNS,
    EXPECTED_FLAT_TYPES,
    DataGovClient,
    DatasetMetadata,
    DownloadedSource,
    IngestionError,
    S3SnapshotWriter,
    SnapshotValidationError,
    ValidationSummary,
    expected_towns,
    run_ingestion,
    validate_source,
)

MONTHS = [
    f"{year:04d}-{month:02d}"
    for year, month in (
        (2025, 10),
        (2025, 11),
        (2025, 12),
        (2026, 1),
        (2026, 2),
        (2026, 3),
        (2026, 4),
        (2026, 5),
        (2026, 6),
        (2026, 7),
        (2026, 8),
        (2026, 9),
    )
]


def source_csv(
    *,
    towns: set[str] | frozenset[str] | None = None,
    months: list[str] | None = None,
    rent: str = "3000",
    header: tuple[str, ...] = EXPECTED_COLUMNS,
    duplicate_first_row: bool = False,
) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(header)
    rows: list[list[str]] = []
    for month in months or MONTHS:
        for town in sorted(towns or expected_towns()):
            for flat_type in sorted(EXPECTED_FLAT_TYPES):
                rows.append([month, town, "5", "GHIM MOH RD", flat_type, rent])
    if duplicate_first_row:
        rows.append(rows[0])
    writer.writerows(rows)
    return output.getvalue().encode()


def test_valid_source_has_reviewed_shape_and_keeps_repeated_rows() -> None:
    summary = validate_source(source_csv(duplicate_first_row=True))

    assert summary == ValidationSummary(
        row_count=12 * 27 * 6 + 1,
        observed_month_from="2025-10",
        source_month_from="2025-10",
        source_month_to="2026-09",
        town_count=27,
        flat_type_count=6,
    )


def test_renamed_column_rejects_the_whole_snapshot() -> None:
    renamed = ("approval_month", *EXPECTED_COLUMNS[1:])

    with pytest.raises(SnapshotValidationError, match="six-column schema"):
        validate_source(source_csv(header=renamed))


def test_missing_town_rejects_the_whole_snapshot() -> None:
    towns = expected_towns() - {"TENGAH"}

    with pytest.raises(SnapshotValidationError, match="TENGAH"):
        validate_source(source_csv(towns=towns))


@pytest.mark.parametrize("rent", ["-1", "0", "3000.5", "SGD 3000"])
def test_non_positive_or_non_integral_rent_is_rejected(rent: str) -> None:
    with pytest.raises(SnapshotValidationError, match="monthly_rent"):
        validate_source(source_csv(rent=rent))


def test_incomplete_trailing_year_is_rejected() -> None:
    months = [month for month in MONTHS if month != "2026-04"]

    with pytest.raises(SnapshotValidationError, match="2026-04"):
        validate_source(source_csv(months=months))


class FakeClient(DataGovClient):
    def __init__(self, source: DownloadedSource) -> None:
        self.source = source

    def download(self) -> DownloadedSource:
        return self.source


class FakeWriter:
    def __init__(self) -> None:
        self.valid: list[ValidationSummary] = []
        self.rejected: list[str] = []

    def write_valid(
        self,
        source: DownloadedSource,
        summary: ValidationSummary,
        retrieved_at: datetime,
    ) -> Mapping[str, Any]:
        del source, retrieved_at
        self.valid.append(summary)
        return {"snapshotId": "valid"}

    def write_rejected(
        self,
        source: DownloadedSource,
        reason: str,
        retrieved_at: datetime,
    ) -> Mapping[str, Any]:
        del source, retrieved_at
        self.rejected.append(reason)
        return {"status": "rejected"}


def test_invalid_download_is_preserved_but_never_published() -> None:
    writer = FakeWriter()
    source = DownloadedSource(source_csv(rent="-1"))

    with pytest.raises(SnapshotValidationError):
        run_ingestion(
            FakeClient(source),
            writer,
            now=lambda: datetime(2026, 10, 19, tzinfo=UTC),
        )

    assert writer.valid == []
    assert len(writer.rejected) == 1


def test_metadata_coverage_must_match_latest_source_month() -> None:
    writer = FakeWriter()
    source = DownloadedSource(
        source_csv(),
        metadata=DatasetMetadata(
            created_at="2021-10-12T12:09:55+08:00",
            last_updated_at="2026-10-02T10:06:14+08:00",
            coverage_start="2021-01-01T08:00:00+08:00",
            coverage_end="2026-08-01T08:00:00+08:00",
            dataset_size=10_440_420,
            source_format="CSV",
        ),
    )

    with pytest.raises(SnapshotValidationError, match="coverage end"):
        run_ingestion(
            FakeClient(source),
            writer,
            now=lambda: datetime(2026, 10, 19, tzinfo=UTC),
        )

    assert writer.valid == []
    assert len(writer.rejected) == 1


class FakeS3:
    def __init__(self) -> None:
        self.puts: list[dict[str, Any]] = []
        self.current: bytes | None = None
        self.current_etag = '"current-etag"'

    def put_object(self, **kwargs: Any) -> None:
        self.puts.append(kwargs)
        if kwargs["Key"] == "raw/current.json":
            if kwargs.get("IfNoneMatch") == "*" and self.current is not None:
                raise ClientError(
                    {"Error": {"Code": "PreconditionFailed"}}, "PutObject"
                )
            self.current = kwargs["Body"]

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["Key"] == "raw/current.json"
        if self.current is None:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey"}},
                "GetObject",
            )
        return {"Body": io.BytesIO(self.current), "ETag": self.current_etag}


def test_valid_s3_write_updates_current_pointer_last() -> None:
    s3 = FakeS3()
    writer = S3SnapshotWriter(s3, "bucket")
    source = DownloadedSource(
        source_csv(),
        metadata=DatasetMetadata(
            created_at="2021-10-12T12:09:55+08:00",
            last_updated_at="2026-10-02T10:06:14+08:00",
            coverage_start="2021-01-01T08:00:00+08:00",
            coverage_end="2026-09-01T08:00:00+08:00",
            dataset_size=10_440_420,
            source_format="CSV",
        ),
        content_type="text/csv",
        etag='"source-etag"',
        last_modified="Fri, 02 Oct 2026 02:06:14 GMT",
    )
    summary = validate_source(source.body)

    pointer = writer.write_valid(
        source, summary, datetime(2026, 10, 19, 1, 2, 3, tzinfo=UTC)
    )

    keys = [item["Key"] for item in s3.puts]
    assert keys[-1] == "raw/current.json"
    assert keys[0].endswith(".csv")
    assert keys[1].endswith(".manifest.json")
    assert s3.puts[0]["IfNoneMatch"] == "*"
    assert s3.puts[1]["IfNoneMatch"] == "*"
    assert "IfMatch" not in s3.puts[-1]
    assert s3.puts[-1]["IfNoneMatch"] == "*"
    assert pointer["sourceMonthTo"] == "2026-09"
    manifest = json.loads(s3.puts[1]["Body"])
    assert manifest["rowCount"] == 12 * 27 * 6
    assert manifest["sourceHeaders"]["etag"] == '"source-etag"'
    assert manifest["sourceUpdatedAt"] == "2026-10-02T10:06:14+08:00"
    assert manifest["sourceMetadata"]["datasetSize"] == 10_440_420


def test_first_writer_cannot_overwrite_pointer_created_after_its_read() -> None:
    newer = {"sourceMonthTo": "2026-10", "retrievedAt": "2026-10-20T00:00:00Z"}

    class ConcurrentCreate(FakeS3):
        def get_object(self, **kwargs: Any) -> dict[str, Any]:
            try:
                return super().get_object(**kwargs)
            except ClientError:
                self.current = json.dumps(newer).encode()
                raise

    s3 = ConcurrentCreate()
    source = DownloadedSource(source_csv())
    with pytest.raises(IngestionError, match="changed during ingestion"):
        S3SnapshotWriter(s3, "bucket").write_valid(
            source, validate_source(source.body), datetime(2026, 10, 19, tzinfo=UTC)
        )
    assert s3.current is not None
    assert json.loads(s3.current) == newer


def test_trailing_blank_csv_rows_are_ignored() -> None:
    body = source_csv() + b"\n"

    summary = validate_source(body)

    assert summary.row_count == 12 * 27 * 6


def test_older_valid_snapshot_cannot_replace_current_pointer() -> None:
    s3 = FakeS3()
    writer = S3SnapshotWriter(s3, "bucket")
    current = {
        "sourceMonthTo": "2026-09",
        "retrievedAt": "2026-10-20T00:00:00Z",
    }
    s3.current = (json.dumps(current) + "\n").encode()
    older_months = [
        f"{year:04d}-{month:02d}"
        for year, month in (
            (2025, 9),
            (2025, 10),
            (2025, 11),
            (2025, 12),
            (2026, 1),
            (2026, 2),
            (2026, 3),
            (2026, 4),
            (2026, 5),
            (2026, 6),
            (2026, 7),
            (2026, 8),
        )
    ]
    summary = validate_source(source_csv(months=older_months))

    with pytest.raises(IngestionError, match="older than the current"):
        writer.write_valid(
            DownloadedSource(source_csv(months=older_months)),
            summary,
            datetime(2026, 10, 19, 1, 2, 3, tzinfo=UTC),
        )

    assert sum(item["Key"] == "raw/current.json" for item in s3.puts) == 0


def test_rejected_s3_write_never_touches_current_pointer() -> None:
    s3 = FakeS3()
    writer = S3SnapshotWriter(s3, "bucket")

    writer.write_rejected(
        DownloadedSource(b"not,csv\n"),
        "Source columns changed.",
        datetime(2026, 10, 19, 1, 2, 3, tzinfo=UTC),
    )

    keys = [item["Key"] for item in s3.puts]
    assert all(key.startswith("rejected/") for key in keys)
    assert "raw/current.json" not in keys
    manifest = json.loads(s3.puts[1]["Body"])
    assert manifest["status"] == "REJECTED"
    assert manifest["reason"] == "Source columns changed."


class FakeResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.body = io.BytesIO(body)
        self.headers = headers or {}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self.body.read(size)


def test_data_gov_client_uses_initiate_poll_then_export() -> None:
    urls: list[str] = []
    responses = iter(
        [
            FakeResponse(
                json.dumps(
                    {
                        "code": 0,
                        "data": {
                            "datasetId": ("d_c9f57187485a850908655db0e8cfe651"),
                            "createdAt": "2021-10-12T12:09:55+08:00",
                            "name": "Renting Out of Flats from Jan 2021",
                            "lastUpdatedAt": "2026-10-02T10:06:14+08:00",
                            "managedBy": "Housing & Development Board",
                            "coverageStart": "2021-01-01T08:00:00+08:00",
                            "coverageEnd": "2026-09-01T08:00:00+08:00",
                            "format": "CSV",
                            "datasetSize": 10_440_420,
                            "columnMetadata": {
                                "order": list(EXPECTED_COLUMNS),
                                "map": {column: column for column in EXPECTED_COLUMNS},
                            },
                        },
                    }
                ).encode()
            ),
            FakeResponse(b'{"code":0,"data":{"message":"initiated"}}'),
            FakeResponse(b'{"code":0,"data":{"status":"processing"}}'),
            FakeResponse(
                b'{"code":0,"data":{"url":"https://download.example/rent.csv"}}'
            ),
            FakeResponse(
                b"rent_approval_date,town\n",
                {"Content-Type": "text/csv", "ETag": '"abc"'},
            ),
        ]
    )
    sleeps: list[float] = []

    def open_response(request: Any, *, timeout: float) -> FakeResponse:
        del timeout
        urls.append(request.full_url)
        return next(responses)

    downloaded = DataGovClient(opener=open_response, sleep=sleeps.append).download()

    assert urls[0].endswith("/metadata")
    assert urls[1].endswith("/initiate-download")
    assert urls[2].endswith("/poll-download")
    assert urls[3].endswith("/poll-download")
    assert urls[4] == "https://download.example/rent.csv"
    assert sleeps == [15.0]
    assert downloaded.body == b"rent_approval_date,town\n"
    assert downloaded.etag == '"abc"'
    assert downloaded.metadata is not None
    assert downloaded.metadata.last_updated_at == "2026-10-02T10:06:14+08:00"


def test_data_gov_client_fails_immediately_on_export_error_code() -> None:
    def open_response(request: Any, *, timeout: float) -> FakeResponse:
        del request, timeout
        return FakeResponse(b'{"code":4,"data":{}}')

    with pytest.raises(IngestionError, match="error code 4"):
        DataGovClient(opener=open_response)._get_json("https://example.test/export")


def test_data_gov_client_reports_poll_exhaustion() -> None:
    metadata = {
        "code": 0,
        "data": {
            "datasetId": DATASET_ID,
            "createdAt": "2021-10-12T12:09:55+08:00",
            "name": "Renting Out of Flats from Jan 2021",
            "lastUpdatedAt": "2026-10-02T10:06:14+08:00",
            "managedBy": "Housing & Development Board",
            "coverageStart": "2021-01-01T08:00:00+08:00",
            "coverageEnd": "2026-09-01T08:00:00+08:00",
            "format": "CSV",
            "datasetSize": 10_440_420,
            "columnMetadata": {
                "order": list(EXPECTED_COLUMNS),
                "map": {column: column for column in EXPECTED_COLUMNS},
            },
        },
    }
    responses = iter(
        [
            FakeResponse(json.dumps(metadata).encode()),
            FakeResponse(b'{"code":0,"data":{"message":"initiated"}}'),
            *[
                FakeResponse(b'{"code":0,"data":{"status":"processing"}}')
                for _ in range(9)
            ],
        ]
    )
    sleeps: list[float] = []

    def open_response(request: Any, *, timeout: float) -> FakeResponse:
        del request, timeout
        return next(responses)

    with pytest.raises(IngestionError, match="not ready before the deadline"):
        DataGovClient(opener=open_response, sleep=sleeps.append).download()

    assert sleeps == [15.0] * 8
