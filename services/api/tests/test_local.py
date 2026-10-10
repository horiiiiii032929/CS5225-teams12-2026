import asyncio
import json
import threading
from typing import Any

import pytest
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver

import flatsplit_api.local as local
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


def test_overlapping_requests_keep_their_own_resolver_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = APIGatewayHttpResolver()
    entered = threading.Event()
    release = threading.Event()

    @resolver.get("/probe/<name>")
    def probe(name: str) -> dict[str, str]:
        if name == "first":
            entered.set()
            assert release.wait(timeout=2)
        return {"name": resolver.current_event.query_string_parameters["name"]}

    monkeypatch.setattr(local, "resolver", resolver)

    async def overlapping() -> list[tuple[int, bytes]]:
        first = asyncio.create_task(call("/probe/first", b"name=first"))
        assert await asyncio.to_thread(entered.wait, 2)
        second = asyncio.create_task(call("/probe/second", b"name=second"))
        try:
            # Give the second request time to overlap the deliberately held first.
            await asyncio.sleep(0.05)
        finally:
            release.set()
        return list(await asyncio.gather(first, second))

    responses = asyncio.run(overlapping())

    assert [status for status, _ in responses] == [200, 200]
    assert [json.loads(body)["name"] for _, body in responses] == ["first", "second"]
