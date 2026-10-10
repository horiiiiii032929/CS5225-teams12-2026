import json
from dataclasses import dataclass
from typing import Any

import pytest

from flatsplit_api.handlers.http import handler


@dataclass(frozen=True)
class FakeContext:
    function_name: str = "flatsplit-api-test"
    memory_limit_in_mb: int = 256
    invoked_function_arn: str = (
        "arn:aws:lambda:ap-southeast-1:000000000000:function:flatsplit-api-test"
    )
    aws_request_id: str = "test-request"


def http_event(method: str, path: str) -> dict[str, Any]:
    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {},
        "requestContext": {
            "http": {"method": method, "path": path, "sourceIp": "127.0.0.1"},
            "requestId": "test-request",
            "stage": "$default",
        },
        "isBase64Encoded": False,
    }


@pytest.mark.parametrize("path", ["/health", "/api/health"])
def test_health_is_served_with_and_without_cloudfront_prefix(path: str) -> None:
    response = handler(http_event("GET", path), FakeContext())  # type: ignore[arg-type]

    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"status": "ok", "service": "flatsplit-api"}


def test_unknown_route_returns_404() -> None:
    response = handler(http_event("GET", "/api/missing"), FakeContext())  # type: ignore[arg-type]

    assert response["statusCode"] == 404
