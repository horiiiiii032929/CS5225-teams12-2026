"""Lazily built DynamoDB-backed stores, configured from the Lambda environment.

`TABLE_NAME` is set by CDK. For local development, point it at the dev table with
AWS credentials, or at DynamoDB Local with `DYNAMODB_ENDPOINT_URL`.
"""

import json
import os
from functools import cache
from typing import Any

import boto3
from botocore.config import Config

from flatsplit_api.commute_jobs import CommuteJobs
from flatsplit_api.errors import ApiError
from flatsplit_api.groups import GroupStore
from flatsplit_api.places import PlaceStore
from flatsplit_api.search_data import SearchDataReader
from flatsplit_api.searches import SearchStore


def _table(purpose: str) -> Any:
    table_name = os.environ.get("TABLE_NAME", "").strip()
    if not table_name:
        raise ApiError(
            503, "SERVICE_UNAVAILABLE", f"{purpose} storage is not configured."
        )
    endpoint = os.environ.get("DYNAMODB_ENDPOINT_URL", "").strip() or None
    resource = boto3.resource("dynamodb", endpoint_url=endpoint)
    return resource.Table(table_name)


@cache
def group_store() -> GroupStore:
    return GroupStore(_table("Group"))


@cache
def place_store() -> PlaceStore:
    """#14 writes the place and station records a preference save reads."""
    return PlaceStore(_table("Place"))


@cache
def _sqs_client() -> Any:
    return boto3.client(
        "sqs",
        endpoint_url=os.environ.get("SQS_ENDPOINT_URL", "").strip() or None,
        config=Config(
            connect_timeout=1,
            read_timeout=2,
            retries={"total_max_attempts": 2, "mode": "standard"},
        ),
    )


def _send_job(job: dict[str, Any]) -> None:
    queue_url = os.environ.get("COMMUTE_QUEUE_URL", "").strip()
    if not queue_url:
        raise ApiError(503, "SERVICE_UNAVAILABLE", "Commute queue is not configured.")
    _sqs_client().send_message(QueueUrl=queue_url, MessageBody=json.dumps(job))


def search_store(groups: GroupStore) -> SearchStore:
    return SearchStore(
        groups.table,
        groups,
        SearchDataReader(groups.table),
        CommuteJobs(groups.table, _send_job),
    )
