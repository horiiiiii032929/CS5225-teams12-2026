"""Local development server for the Lambda resolver.

Translates ASGI requests into API Gateway HTTP API (v2) events so `pnpm dev:api`
runs exactly the routes deployed to Lambda. Run with uvicorn (the `local` extra).
"""

import asyncio
import base64
import time
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from urllib.parse import parse_qsl

from aws_lambda_powertools.utilities.typing import LambdaContext

from flatsplit_api.handlers.http import app as resolver

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]

resolver.enable_swagger(path="/docs", title="FlatSplit API")


def _local_context(request_id: str) -> LambdaContext:
    context = LambdaContext()
    context._function_name = "flatsplit-api-local"
    context._memory_limit_in_mb = 256
    context._invoked_function_arn = (
        "arn:aws:lambda:local:000000000000:function:flatsplit-api-local"
    )
    context._aws_request_id = request_id
    return context


async def _read_body(receive: Receive) -> bytes:
    body = b""
    while True:
        message = await receive()
        chunk: bytes = message.get("body", b"")
        body += chunk
        if not message.get("more_body", False):
            return body


def _to_event(scope: Scope, body: bytes) -> dict[str, Any]:
    headers: dict[str, str] = {}
    for raw_name, raw_value in scope["headers"]:
        name, value = raw_name.decode("latin-1").lower(), raw_value.decode("latin-1")
        headers[name] = f"{headers[name]},{value}" if name in headers else value
    query_string = scope["query_string"].decode("latin-1")
    query: dict[str, str] = {}
    for key, value in parse_qsl(query_string, keep_blank_values=True):
        query[key] = f"{query[key]},{value}" if key in query else value
    client = scope.get("client") or ("127.0.0.1", 0)
    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": scope["path"],
        "rawQueryString": query_string,
        "headers": headers,
        "queryStringParameters": query or None,
        "requestContext": {
            "http": {
                "method": scope["method"],
                "path": scope["path"],
                "protocol": f"HTTP/{scope.get('http_version', '1.1')}",
                "sourceIp": client[0],
                "userAgent": headers.get("user-agent", ""),
            },
            "requestId": str(uuid.uuid4()),
            "stage": "$default",
            "timeEpoch": int(time.time() * 1000),
        },
        "body": base64.b64encode(body).decode() if body else None,
        "isBase64Encoded": bool(body),
    }


async def app(scope: Scope, receive: Receive, send: Send) -> None:
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    if scope["type"] != "http":
        return

    event = _to_event(scope, await _read_body(receive))
    context = _local_context(event["requestContext"]["requestId"])
    result = await asyncio.to_thread(resolver.resolve, event, context)

    body = result.get("body") or ""
    payload = base64.b64decode(body) if result.get("isBase64Encoded") else body.encode()
    headers = [
        (name.lower().encode(), str(value).encode())
        for name, value in (result.get("headers") or {}).items()
    ]
    headers += [
        (b"set-cookie", cookie.encode()) for cookie in result.get("cookies") or []
    ]
    await send(
        {
            "type": "http.response.start",
            "status": result["statusCode"],
            "headers": headers,
        }
    )
    await send({"type": "http.response.body", "body": payload})
