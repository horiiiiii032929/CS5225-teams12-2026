"""Scheduled/manual Lambda entry point for raw HDB rental ingestion."""

import os
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext
from botocore.config import Config

from flatsplit_api.rent_publication import RentSummaryPublisher
from flatsplit_api.rental_ingestion import (
    DataGovClient,
    S3SnapshotWriter,
    run_ingestion,
)

logger = Logger()


@logger.inject_lambda_context(clear_state=True)
def handler(event: dict[str, Any], context: LambdaContext) -> dict[str, Any]:
    """Ingest one export; exceptions intentionally mark the invocation failed."""
    del event, context
    bucket = os.environ.get("RENT_RAW_BUCKET", "").strip()
    table_name = os.environ.get("RENT_TABLE_NAME", "").strip()
    if not bucket or not table_name:
        raise RuntimeError("RENT_RAW_BUCKET and RENT_TABLE_NAME are required.")
    s3 = boto3.client(
        "s3",
        config=Config(
            connect_timeout=2,
            read_timeout=30,
            retries={"total_max_attempts": 3, "mode": "standard"},
        ),
    )
    table = boto3.resource("dynamodb").Table(table_name)
    publisher = RentSummaryPublisher(table)
    try:
        pointer = run_ingestion(
            DataGovClient(),
            S3SnapshotWriter(s3, bucket),
            publish=publisher.publish,
        )
    except Exception:
        logger.exception("HDB rental ingestion failed")
        raise
    logger.info(
        "HDB rental ingestion completed",
        extra={
            "snapshot_id": pointer["snapshotId"],
            "source_month_to": pointer["sourceMonthTo"],
        },
    )
    return dict(pointer)
