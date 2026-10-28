"""Secrets Manager rotation Lambda for the OneMap token (#72)."""

import os
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

from flatsplit_api.onemap_rotation import Rotator

logger = Logger()


@logger.inject_lambda_context(clear_state=True)
def handler(event: dict[str, Any], context: LambdaContext) -> None:
    """Run one rotation step; an exception fails it and keeps AWSCURRENT."""
    del context
    credentials = os.environ.get("ONEMAP_CREDENTIALS_SECRET_NAME", "").strip()
    if not credentials:
        raise RuntimeError("ONEMAP_CREDENTIALS_SECRET_NAME is not configured.")
    try:
        Rotator(boto3.client("secretsmanager"), credentials).handle(event)
    except Exception:
        # Rotation errors carry status codes and OneMap's error text, never
        # the credentials or a token, so the exception is safe to log.
        logger.exception(
            "OneMap token rotation failed", extra={"step": event.get("Step")}
        )
        raise
