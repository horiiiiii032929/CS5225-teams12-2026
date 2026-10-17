"""Lazily built DynamoDB-backed stores, configured from the Lambda environment.

`TABLE_NAME` is set by CDK. For local development, point it at the dev table with
AWS credentials, or at DynamoDB Local with `DYNAMODB_ENDPOINT_URL`.
"""

import os
from functools import cache

import boto3

from flatsplit_api.errors import ApiError
from flatsplit_api.groups import GroupStore


@cache
def group_store() -> GroupStore:
    table_name = os.environ.get("TABLE_NAME", "").strip()
    if not table_name:
        raise ApiError(503, "SERVICE_UNAVAILABLE", "Group storage is not configured.")
    endpoint = os.environ.get("DYNAMODB_ENDPOINT_URL", "").strip() or None
    resource = boto3.resource("dynamodb", endpoint_url=endpoint)
    return GroupStore(resource.Table(table_name))
