"""#72 scheduled OneMap token refresh, including the #82 review regressions."""

import base64
import http.server
import json
import threading
import time
import urllib.request
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws

import flatsplit_api.handlers.onemap_token_refresh as refresh_handler
import flatsplit_api.onemap_token_refresh as refresh
from flatsplit_api.onemap_token_refresh import (
    RENEW_WITHIN_SECONDS,
    RefreshError,
    check_token,
    fetch_token,
    read_credentials,
    refresh_token,
    token_expiry,
)

TOKEN_SECRET = "onemap-token"
CREDENTIALS_SECRET = "onemap-credentials"
PASSWORD = "SyntheticPassword-DoNotLog"


def part(value: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def jwt(exp: Any) -> str:
    """An unsigned JWT-shaped token; refresh reads `exp` but not the signature."""
    return f"{part({'alg': 'RS256'})}.{part({'iss': 'OneMap', 'exp': exp})}.sig"


OLD_TOKEN = jwt(int(time.time()) + 3600)
NEW_TOKEN = jwt(int(time.time()) + 3 * 24 * 3600)


@pytest.fixture
def client() -> Iterator[Any]:
    with mock_aws():
        sm = boto3.client("secretsmanager", region_name="ap-southeast-1")
        sm.create_secret(Name=TOKEN_SECRET, SecretString=OLD_TOKEN)
        sm.create_secret(
            Name=CREDENTIALS_SECRET,
            SecretString=json.dumps(
                {"email": "team@example.com", "password": PASSWORD}
            ),
        )
        yield sm


def current(client: Any) -> str:
    value: str = client.get_secret_value(
        SecretId=TOKEN_SECRET, VersionStage="AWSCURRENT"
    )["SecretString"]
    return value


def test_refresh_stores_a_checked_token_as_current(client: Any) -> None:
    logins: list[tuple[str, str]] = []
    checked: list[str] = []

    def fetch(email: str, password: str) -> str:
        logins.append((email, password))
        return NEW_TOKEN

    expiry = refresh_token(
        client, TOKEN_SECRET, CREDENTIALS_SECRET, fetch=fetch, check=checked.append
    )
    assert current(client) == NEW_TOKEN
    assert logins == [("team@example.com", PASSWORD)]
    assert checked == [NEW_TOKEN]
    assert expiry == token_expiry(NEW_TOKEN)


@pytest.mark.parametrize(
    "credentials",
    ['{"email": "a@b.c"}', "not json", '["a", "b"]', '{"email": "", "password": "x"}'],
)
def test_malformed_credentials_fail_without_logging_in(
    client: Any, credentials: str
) -> None:
    client.put_secret_value(SecretId=CREDENTIALS_SECRET, SecretString=credentials)
    with pytest.raises(RefreshError, match="credentials secret"):
        refresh_token(
            client,
            TOKEN_SECRET,
            CREDENTIALS_SECRET,
            fetch=lambda *_: pytest.fail("no login expected"),
        )
    assert current(client) == OLD_TOKEN


def test_failed_login_or_check_keeps_the_current_token(client: Any) -> None:
    def refused(*_: str) -> str:
        raise RefreshError("OneMap login failed: HTTP 401.")

    with pytest.raises(RefreshError, match="401"):
        refresh_token(client, TOKEN_SECRET, CREDENTIALS_SECRET, fetch=refused)

    def rejected(_: str) -> None:
        raise RefreshError("OneMap rejected the new token: HTTP 401.")

    with pytest.raises(RefreshError, match="rejected"):
        refresh_token(
            client,
            TOKEN_SECRET,
            CREDENTIALS_SECRET,
            fetch=lambda *_: NEW_TOKEN,
            check=rejected,
        )
    assert current(client) == OLD_TOKEN


def test_fetch_token_posts_credentials_and_reads_access_token() -> None:
    sent: list[urllib.request.Request] = []

    def send(request: urllib.request.Request) -> tuple[int, Any]:
        sent.append(request)
        return 200, {"access_token": NEW_TOKEN, "expiry_timestamp": "1"}

    assert fetch_token("a@b.c", PASSWORD, send) == NEW_TOKEN
    assert sent[0].full_url == "https://www.onemap.gov.sg/api/auth/post/getToken"
    assert json.loads(sent[0].data) == {"email": "a@b.c", "password": PASSWORD}  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("status", "payload"),
    [
        # Review regression: a provider error that echoes the submission.
        (401, {"error": f"Bad login for a@b.c / {PASSWORD}"}),
        (200, {"error": PASSWORD}),
        (502, None),
    ],
)
def test_login_failures_never_carry_provider_text(status: int, payload: Any) -> None:
    with pytest.raises(RefreshError) as exc:
        fetch_token("a@b.c", PASSWORD, lambda _: (status, payload))
    assert str(exc.value) == f"OneMap login failed: HTTP {status}."


@pytest.mark.parametrize("token", ["", "not-a-jwt", "a.!!!.c", "a.e30.c"])
def test_token_expiry_rejects_non_jwts(token: str) -> None:
    with pytest.raises(RefreshError, match="not a JWT"):
        token_expiry(token)


def test_malformed_expiry_does_not_chain_its_value() -> None:
    # Review regression: a ValueError chained under the fixed message leaked
    # the offending claim through the logged traceback.
    with pytest.raises(RefreshError) as exc:
        token_expiry(jwt(PASSWORD))
    assert exc.value.__cause__ is None and exc.value.__suppress_context__


def test_check_token_requires_life_and_onemap_acceptance() -> None:
    now = time.time()
    seen: list[urllib.request.Request] = []

    def accepted(request: urllib.request.Request) -> tuple[int, Any]:
        seen.append(request)
        return 200, [{"name": "KENT RIDGE MRT STATION"}]

    check_token(jwt(int(now + 60)), accepted, lambda: now)
    assert "/api/public/nearbysvc/getNearestMrtStops?" in seen[0].full_url
    with pytest.raises(RefreshError, match="expired"):
        check_token(jwt(int(now - 60)), accepted, lambda: now)
    with pytest.raises(RefreshError, match="HTTP 401"):
        check_token(
            jwt(int(now + 3 * 24 * 3600)),
            lambda _: (401, {"message": "Unauthorized"}),
            lambda: now,
        )


class _Recorder(http.server.BaseHTTPRequestHandler):
    """Loopback server: redirects when given `redirect`, else records the call."""

    redirect: str | None = None
    received: list[str | None]

    def do_GET(self) -> None:
        if self.redirect:
            self.send_response(302)
            self.send_header("Location", self.redirect + self.path)
            self.end_headers()
            return
        self.received.append(self.headers.get("Authorization"))
        body = b"[]"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: Any) -> None:
        pass


def _serve(handler: type[_Recorder]) -> http.server.HTTPServer:
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_authenticated_check_never_follows_a_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Review regression: urllib's default redirect handling delivered the
    # pending token to a second origin, and its 200 [] passed the check.
    class Other(_Recorder):
        received: list[str | None] = []

    target = _serve(Other)

    class First(_Recorder):
        received: list[str | None] = []
        redirect = f"http://127.0.0.1:{target.server_port}"

    origin = _serve(First)
    try:
        monkeypatch.setattr(
            refresh, "BASE_URL", f"http://127.0.0.1:{origin.server_port}"
        )
        with pytest.raises(RefreshError, match="HTTP 302"):
            check_token(jwt(int(time.time()) + 3 * 24 * 3600))
        assert Other.received == []
    finally:
        origin.shutdown()
        target.shutdown()


def context() -> Any:
    return type(
        "Context",
        (),
        {
            "function_name": "refresh-test",
            "memory_limit_in_mb": 128,
            "invoked_function_arn": "arn:aws:lambda:local:0:function:refresh-test",
            "aws_request_id": "refresh-test",
        },
    )()


def test_handler_requires_both_secret_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ONEMAP_SECRET_NAME", raising=False)
    monkeypatch.setenv("ONEMAP_CREDENTIALS_SECRET_NAME", CREDENTIALS_SECRET)
    with pytest.raises(RuntimeError, match="are required"):
        refresh_handler.handler({}, context())


@pytest.mark.parametrize(
    ("raised", "reason"),
    [
        (
            RefreshError("OneMap login failed: HTTP 401."),
            "OneMap login failed: HTTP 401.",
        ),
        # Anything unexpected is reported by type only, never by its message.
        (ValueError(f"leaked {PASSWORD}"), "Unexpected ValueError."),
    ],
)
def test_handler_failures_are_credential_safe(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    raised: Exception,
    reason: str,
) -> None:
    monkeypatch.setenv("ONEMAP_SECRET_NAME", TOKEN_SECRET)
    monkeypatch.setenv("ONEMAP_CREDENTIALS_SECRET_NAME", CREDENTIALS_SECRET)
    monkeypatch.setattr(boto3, "client", lambda *_a, **_k: None)

    def fail(*_: Any, **__: Any) -> int:
        raise raised

    monkeypatch.setattr(refresh_handler, "refresh_token", fail)
    with pytest.raises(RuntimeError) as exc:
        refresh_handler.handler({}, context())
    assert str(exc.value) == f"OneMap token refresh failed: {reason}"
    assert exc.value.__cause__ is None and exc.value.__suppress_context__
    # Every logged field, not just the message, must be free of the password.
    logged = [vars(record) for record in caplog.records]
    assert [r.get("reason") for r in logged if r.get("reason")] == [reason]
    assert PASSWORD not in repr(logged)


def test_handler_reports_the_new_expiry(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONEMAP_SECRET_NAME", TOKEN_SECRET)
    monkeypatch.setenv("ONEMAP_CREDENTIALS_SECRET_NAME", CREDENTIALS_SECRET)
    monkeypatch.setattr(boto3, "client", lambda *_a, **_k: client)
    monkeypatch.setattr(refresh, "fetch_token", lambda *_: NEW_TOKEN)
    monkeypatch.setattr(refresh, "check_token", lambda _: None)
    monkeypatch.setattr(
        refresh_handler,
        "refresh_token",
        lambda c, t, s, force: refresh_token(
            c, t, s, force=force, fetch=refresh.fetch_token, check=refresh.check_token
        ),
    )
    result = refresh_handler.handler({}, context())
    assert current(client) == NEW_TOKEN
    assert result["expiresAt"].startswith(
        time.strftime("%Y-%m-%d", time.gmtime(token_expiry(NEW_TOKEN)))
    )


def versions(client: Any) -> int:
    listed = client.list_secret_version_ids(SecretId=TOKEN_SECRET)
    return len(listed["Versions"])


def no_login(*_: str) -> str:
    pytest.fail("no login expected")


def test_a_token_with_days_left_needs_no_login(client: Any) -> None:
    client.put_secret_value(SecretId=TOKEN_SECRET, SecretString=NEW_TOKEN)
    before = versions(client)
    expiry = refresh_token(client, TOKEN_SECRET, CREDENTIALS_SECRET, fetch=no_login)
    assert expiry == token_expiry(NEW_TOKEN)
    assert versions(client) == before


def test_force_logs_in_however_long_the_token_has_left(client: Any) -> None:
    client.put_secret_value(SecretId=TOKEN_SECRET, SecretString=NEW_TOKEN)
    other = jwt(int(time.time()) + 2 * 24 * 3600)
    refresh_token(
        client,
        TOKEN_SECRET,
        CREDENTIALS_SECRET,
        force=True,
        fetch=lambda *_: other,
        check=lambda _: None,
    )
    assert current(client) == other


def test_getting_the_same_valid_token_back_is_success(client: Any) -> None:
    """OneMap reuses a valid token: 16.9 h left failed every run on 31 October."""
    token = jwt(int(time.time() + RENEW_WITHIN_SECONDS - 3600))
    client.put_secret_value(SecretId=TOKEN_SECRET, SecretString=token)
    before = versions(client)

    def not_checked(_: str) -> None:
        pytest.fail("a stored token needs no probe")

    expiry = refresh_token(
        client,
        TOKEN_SECRET,
        CREDENTIALS_SECRET,
        fetch=lambda *_: token,
        check=not_checked,
    )
    assert expiry == token_expiry(token)
    assert current(client) == token
    assert versions(client) == before


def test_getting_an_expired_token_back_fails(client: Any) -> None:
    expired = jwt(int(time.time()) - 60)
    client.put_secret_value(SecretId=TOKEN_SECRET, SecretString=expired)
    with pytest.raises(RefreshError, match="expired"):
        refresh_token(
            client, TOKEN_SECRET, CREDENTIALS_SECRET, fetch=lambda *_: expired
        )


def test_a_new_token_replaces_an_expired_one(client: Any) -> None:
    client.put_secret_value(
        SecretId=TOKEN_SECRET, SecretString=jwt(int(time.time()) - 60)
    )
    refresh_token(
        client,
        TOKEN_SECRET,
        CREDENTIALS_SECRET,
        fetch=lambda *_: NEW_TOKEN,
        check=lambda _: None,
    )
    assert current(client) == NEW_TOKEN


def test_the_cdk_placeholder_counts_as_expired(client: Any) -> None:
    client.put_secret_value(SecretId=TOKEN_SECRET, SecretString="random-placeholder")
    refresh_token(
        client,
        TOKEN_SECRET,
        CREDENTIALS_SECRET,
        fetch=lambda *_: NEW_TOKEN,
        check=lambda _: None,
    )
    assert current(client) == NEW_TOKEN


@pytest.mark.parametrize(
    ("event", "force"),
    [({"source": "aws.events"}, False), ({}, True)],
)
def test_only_the_schedule_may_skip_the_login(
    monkeypatch: pytest.MonkeyPatch, event: dict[str, Any], force: bool
) -> None:
    monkeypatch.setenv("ONEMAP_SECRET_NAME", TOKEN_SECRET)
    monkeypatch.setenv("ONEMAP_CREDENTIALS_SECRET_NAME", CREDENTIALS_SECRET)
    monkeypatch.setattr(boto3, "client", lambda *_a, **_k: None)
    seen: list[bool] = []

    def record(*_: Any, force: bool) -> int:
        seen.append(force)
        return int(time.time())

    monkeypatch.setattr(refresh_handler, "refresh_token", record)
    refresh_handler.handler(event, context())
    assert seen == [force]


def test_read_credentials_returns_the_pair(client: Any) -> None:
    assert read_credentials(client, CREDENTIALS_SECRET) == (
        "team@example.com",
        PASSWORD,
    )
