import asyncio
import json
from typing import Any

import pytest

from flatsplit_api.local import app


async def call(path: str, query: bytes = b"") -> tuple[int, bytes]:
    sent: list[dict[str, Any]] = []
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": query,
        "headers": [(b"host", b"127.0.0.1:8000")],
        "client": ("127.0.0.1", 50000),
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Any) -> None:
        sent.append(dict(message))

    await app(scope, receive, send)
    return sent[0]["status"], sent[1]["body"]


@pytest.mark.parametrize("path", ["/health", "/api/health"])
def test_local_server_runs_the_lambda_routes(path: str) -> None:
    status, body = asyncio.run(call(path))

    assert status == 200
    assert json.loads(body)["status"] == "ok"
