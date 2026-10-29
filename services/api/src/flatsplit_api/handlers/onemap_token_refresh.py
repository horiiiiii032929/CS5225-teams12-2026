"""Scheduled Lambda that renews the OneMap token every 12 hours (#72)."""

import os
from datetime import UTC, datetime
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

from flatsplit_api.onemap_token_refresh import RefreshError, refresh_token

logger = Logger()


@logger.inject_lambda_context(clear_state=True)
def handler(event: dict[str, Any], context: LambdaContext) -> dict[str, str]:
    del event, context
    token_secret = os.environ.get("ONEMAP_SECRET_NAME", "").strip()
    credentials = os.environ.get("ONEMAP_CREDENTIALS_SECRET_NAME", "").strip()
    if not token_secret or not credentials:
        raise RuntimeError(
            "ONEMAP_SECRET_NAME and ONEMAP_CREDENTIALS_SECRET_NAME are required."
        )
    try:
        expiry = refresh_token(
            boto3.client("secretsmanager"), token_secret, credentials
        )
    except RefreshError as exc:
        # These messages are fixed text plus status codes, safe to log.
        reason = str(exc)
    except Exception as exc:
        # Anything else (SDK, network) is reported by type only, so no
        # library message or chained cause can carry a credential into logs.
        reason = f"Unexpected {type(exc).__name__}."
    else:
        expires = datetime.fromtimestamp(expiry, UTC).isoformat()
        logger.info("OneMap token refreshed", extra={"expiresAt": expires})
        return {"expiresAt": expires}
    logger.error("OneMap token refresh failed", extra={"reason": reason})
    # Fail the invocation (Errors metric, async retry) without a traceback
    # that could include the original exception.
    raise RuntimeError(f"OneMap token refresh failed: {reason}") from None
