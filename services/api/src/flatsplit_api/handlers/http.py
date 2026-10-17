"""HTTP API Lambda: routes requests from API Gateway (HTTP API, payload v2)."""

import json
import re
from typing import Any

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, Response
from aws_lambda_powertools.event_handler.exceptions import NotFoundError
from aws_lambda_powertools.utilities.typing import LambdaContext
from botocore.exceptions import ClientError, HTTPClientError
from botocore.exceptions import ConnectionError as BotocoreConnectionError
from pydantic import BaseModel, ValidationError

from flatsplit_api.errors import ApiError, not_found, validation_failed
from flatsplit_api.group_models import (
    CreateGroupRequest,
    JoinGroupRequest,
    PreferencesRequest,
)
from flatsplit_api.group_views import (
    CreatedGroupResponse,
    GroupResponse,
    MembershipResponse,
    created_response,
    group_response,
    joined_response,
)
from flatsplit_api.models import HealthResponse, PlacesResponse
from flatsplit_api.onemap import (
    OneMapRateLimited,
    OneMapUnavailable,
    find_places,
    normalise_query,
)
from flatsplit_api.storage import group_store

logger = Logger()

# CloudFront forwards browser requests as /api/...; local Vite strips the prefix.
app = APIGatewayHttpResolver(strip_prefixes=["/api"], enable_validation=True)

#: docs/api-contract.md: `q` is 3-100 characters.
QUERY_MIN_LENGTH = 3
QUERY_MAX_LENGTH = 100


def _error_response(error: ApiError) -> Response[str]:
    return Response(
        status_code=error.status_code,
        content_type="application/json",
        body=json.dumps(error.body()),
    )


# Powertools does not annotate exception_handler, so mypy sees an untyped
# decorator here.
@app.exception_handler(ApiError)  # type: ignore[untyped-decorator]
def handle_api_error(exc: ApiError) -> Response[str]:
    return _error_response(exc)


@app.exception_handler(ClientError)  # type: ignore[untyped-decorator]
def handle_storage_error(exc: ClientError) -> Response[str]:
    # Log only the provider's error code: request values may include token hashes.
    logger.error(
        "Storage request failed",
        extra={"error_code": exc.response.get("Error", {}).get("Code")},
    )
    return _storage_unavailable()


# Connect failures, read timeouts and dropped connections never reach DynamoDB,
# so they are not ClientErrors but must still return the contract's 503.
@app.exception_handler([BotocoreConnectionError, HTTPClientError])  # type: ignore[untyped-decorator]
def handle_storage_transport_error(exc: Exception) -> Response[str]:
    # The class name is enough; messages can include endpoint URLs.
    logger.error("Storage unreachable", extra={"error_type": type(exc).__name__})
    return _storage_unavailable()


def _storage_unavailable() -> Response[str]:
    return _error_response(
        ApiError(503, "SERVICE_UNAVAILABLE", "Storage is busy. Try again shortly.")
    )


@app.not_found
def handle_not_found(_exc: NotFoundError) -> Response[str]:
    # Keeps unknown routes on the contract's single error body.
    return _error_response(not_found("Unknown route."))


@app.get("/health")
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/places")
def places() -> PlacesResponse:
    """Return explicit selectable/unsupported candidates; never auto-select."""
    raw = app.current_event.get_query_string_value(name="q", default_value="") or ""
    if any(ord(char) < 32 or ord(char) == 127 for char in raw):
        raise validation_failed("q", "Control characters are not allowed.")
    query = normalise_query(raw)

    if len(query) < QUERY_MIN_LENGTH:
        raise validation_failed("q", f"Enter at least {QUERY_MIN_LENGTH} characters.")
    if len(query) > QUERY_MAX_LENGTH:
        raise validation_failed("q", f"Use at most {QUERY_MAX_LENGTH} characters.")

    try:
        found = find_places(query)
    except OneMapRateLimited as exc:
        logger.warning("OneMap throttled the lookup")
        raise ApiError(
            429, "RATE_LIMITED", "Too many destination lookups. Try again shortly."
        ) from exc
    except OneMapUnavailable as exc:
        logger.warning("OneMap lookup failed")
        raise ApiError(
            503,
            "UPSTREAM_UNAVAILABLE",
            "Destination search is unavailable. Try again shortly.",
        ) from exc

    return PlacesResponse.model_validate(found)


# Group IDs and member IDs are 22-character URL-safe tokens; anything else cannot
# exist, so it is answered without a storage round trip.
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_BEARER = re.compile(r"Bearer\s+(\S+)", re.IGNORECASE)


def _json(model: BaseModel, status_code: int = 200) -> Response[str]:
    # Group responses can carry credentials, so no browser or proxy may cache them.
    return Response(
        status_code=status_code,
        content_type="application/json",
        body=model.model_dump_json(),
        headers={"Cache-Control": "no-store"},
    )


def _body[T: BaseModel](model: type[T]) -> T:
    try:
        data = json.loads(app.current_event.decoded_body or "")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ApiError(400, "BAD_REQUEST", "The request body must be JSON.") from exc
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ApiError(
            422,
            "VALIDATION_FAILED",
            "The request failed validation.",
            [
                {
                    "field": ".".join(str(part) for part in error["loc"]) or "body",
                    "message": error["msg"],
                }
                for error in exc.errors()
            ],
        ) from exc


def _bearer() -> str | None:
    header = app.current_event.headers.get("authorization")
    match = _BEARER.fullmatch(header.strip()) if header else None
    return match.group(1) if match else None


def _id(value: str, what: str) -> str:
    if not _ID.fullmatch(value):
        raise not_found(f"{what} not found.")
    return value


def _documented(status: int, model: type[BaseModel]) -> dict[int, Any]:
    return {
        status: {
            "description": "Success",
            "content": {"application/json": {"model": model}},
        }
    }


def _request(model: type[BaseModel]) -> dict[str, Any]:
    # `_body` parses requests itself to keep the contract's 400/422 envelope and
    # check IDs first, so Powertools cannot infer the body. The request models
    # are flat, so their schemas inline without $defs.
    return {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": model.model_json_schema()}},
        }
    }


@app.post(
    "/groups",
    responses=_documented(201, CreatedGroupResponse),
    openapi_extensions=_request(CreateGroupRequest),
)
def create_group() -> Response[str]:
    membership = group_store().create(_body(CreateGroupRequest))
    return _json(created_response(membership), 201)


@app.get("/groups/<group_id>", responses=_documented(200, GroupResponse))
def read_group(group_id: str) -> Response[str]:
    state = group_store().read(_id(group_id, "Group"), _bearer())
    return _json(group_response(state))


@app.post(
    "/groups/<group_id>/members",
    responses=_documented(201, MembershipResponse),
    openapi_extensions=_request(JoinGroupRequest),
)
def join_group(group_id: str) -> Response[str]:
    gid = _id(group_id, "Group")
    membership = group_store().join(gid, _bearer(), _body(JoinGroupRequest))
    return _json(joined_response(membership), 201)


@app.put(
    "/groups/<group_id>/members/<member_id>",
    responses=_documented(200, GroupResponse),
    openapi_extensions=_request(PreferencesRequest),
)
def save_preferences(group_id: str, member_id: str) -> Response[str]:
    gid = _id(group_id, "Group")
    mid = _id(member_id, "Member")
    state = group_store().save_preferences(
        gid, mid, _bearer(), _body(PreferencesRequest)
    )
    return _json(group_response(state))


@logger.inject_lambda_context
def handler(event: dict[str, Any], context: LambdaContext) -> dict[str, Any]:
    return app.resolve(event, context)
