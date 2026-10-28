"""#72 OneMap token rotation: the four Secrets Manager steps on Moto."""

import base64
import json
import time
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws

import flatsplit_api.handlers.onemap_rotation as rotation_handler
from flatsplit_api.onemap_rotation import (
    MIN_REMAINING_SECONDS,
    RotationError,
    Rotator,
    check_token,
    fetch_token,
    token_expiry,
)

TOKEN_SECRET = "onemap-token"
CREDENTIALS_SECRET = "onemap-credentials"
NEW_VERSION = "11111111-2222-3333-4444-555555555555"


def jwt(exp: float) -> str:
    """An unsigned JWT-shaped token; rotation reads `exp` but not the signature."""

    def part(value: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{part({'alg': 'RS256'})}.{part({'iss': 'OneMap', 'exp': int(exp)})}.sig"


OLD_TOKEN = jwt(time.time() + 3600)
NEW_TOKEN = jwt(time.time() + 3 * 24 * 3600)


@pytest.fixture
def client() -> Iterator[Any]:
    with mock_aws():
        sm = boto3.client("secretsmanager", region_name="ap-southeast-1")
        sm.create_secret(Name=TOKEN_SECRET, SecretString=OLD_TOKEN)
        sm.create_secret(
            Name=CREDENTIALS_SECRET,
            SecretString=json.dumps({"email": "team@example.com", "password": "pw"}),
        )
        yield sm


def stage_pending(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real Secrets Manager labels the new version AWSPENDING before
    `createSecret` runs; Moto cannot hold a label without a value, so add it."""
    real = client.describe_secret

    def describe(**kwargs: Any) -> dict[str, Any]:
        result: dict[str, Any] = real(**kwargs)
        stages = result.setdefault("VersionIdsToStages", {})
        stages.setdefault(NEW_VERSION, ["AWSPENDING"])
        return result

    monkeypatch.setattr(client, "describe_secret", describe)


def event(step: str) -> dict[str, str]:
    return {"SecretId": TOKEN_SECRET, "ClientRequestToken": NEW_VERSION, "Step": step}


def current(client: Any) -> str:
    # Explicit stage: Moto's default read does not follow a moved AWSCURRENT
    # label, while real Secrets Manager (and resolve_token) always serve it.
    value: str = client.get_secret_value(
        SecretId=TOKEN_SECRET, VersionStage="AWSCURRENT"
    )["SecretString"]
    return value


def test_full_rotation_promotes_a_checked_token(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    logins: list[tuple[str, str]] = []
    checked: list[str] = []

    def fetch(email: str, password: str) -> str:
        logins.append((email, password))
        return NEW_TOKEN

    (original,) = client.describe_secret(SecretId=TOKEN_SECRET)["VersionIdsToStages"]
    rotator = Rotator(client, CREDENTIALS_SECRET, fetch=fetch, check=checked.append)
    stage_pending(client, monkeypatch)
    for step in ["createSecret", "setSecret", "testSecret"]:
        rotator.handle(event(step))
        # Readers keep the old token until finishSecret.
        assert current(client) == OLD_TOKEN
    rotator.handle(event("finishSecret"))

    assert current(client) == NEW_TOKEN
    assert logins == [("team@example.com", "pw")]
    assert checked == [NEW_TOKEN]
    stages = client.describe_secret(SecretId=TOKEN_SECRET)["VersionIdsToStages"]
    assert "AWSCURRENT" in stages[NEW_VERSION]
    assert stages[original] == ["AWSPREVIOUS"]
    # Once current, any repeated step is a no-op rather than a second login.
    rotator.handle(event("createSecret"))
    assert len(logins) == 1


def test_retried_create_does_not_log_in_again(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    logins: list[str] = []

    def fetch(email: str, _password: str) -> str:
        logins.append(email)
        return NEW_TOKEN

    rotator = Rotator(client, CREDENTIALS_SECRET, fetch=fetch)
    stage_pending(client, monkeypatch)
    rotator.handle(event("createSecret"))
    rotator.handle(event("createSecret"))
    assert len(logins) == 1


@pytest.mark.parametrize(
    "credentials", ['{"email": "a@b.c"}', "not json", '["a", "b"]']
)
def test_malformed_credentials_fail_without_staging_or_logging_in(
    client: Any, monkeypatch: pytest.MonkeyPatch, credentials: str
) -> None:
    client.put_secret_value(SecretId=CREDENTIALS_SECRET, SecretString=credentials)
    rotator = Rotator(
        client, CREDENTIALS_SECRET, fetch=lambda *_: pytest.fail("no login expected")
    )
    stage_pending(client, monkeypatch)
    with pytest.raises(RotationError, match="credentials secret"):
        rotator.handle(event("createSecret"))
    assert current(client) == OLD_TOKEN


def test_failed_login_or_check_leaves_the_current_token(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(*_: str) -> str:
        raise RotationError("OneMap getToken returned HTTP 401")

    stage_pending(client, monkeypatch)
    with pytest.raises(RotationError, match="401"):
        Rotator(client, CREDENTIALS_SECRET, fetch=refused).handle(event("createSecret"))
    assert current(client) == OLD_TOKEN

    def rejected(_: str) -> None:
        raise RotationError("OneMap rejected the new token")

    rotator = Rotator(
        client, CREDENTIALS_SECRET, fetch=lambda *_: NEW_TOKEN, check=rejected
    )
    rotator.handle(event("createSecret"))
    with pytest.raises(RotationError, match="rejected"):
        rotator.handle(event("testSecret"))
    assert current(client) == OLD_TOKEN


@pytest.mark.parametrize(
    ("stages", "message"),
    [({}, "not staged"), ({NEW_VERSION: ["AWSPREVIOUS"]}, "not AWSPENDING")],
)
def test_rotation_preconditions(
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
    stages: dict[str, list[str]],
    message: str,
) -> None:
    monkeypatch.setattr(
        client, "describe_secret", lambda **_: {"VersionIdsToStages": stages}
    )
    with pytest.raises(RotationError, match=message):
        Rotator(client, CREDENTIALS_SECRET).handle(event("createSecret"))


def test_unknown_step_is_refused(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    stage_pending(client, monkeypatch)
    with pytest.raises(RotationError, match="Unknown rotation step"):
        Rotator(client, CREDENTIALS_SECRET).handle(event("bogusSecret"))


def test_fetch_token_posts_credentials_and_reads_access_token() -> None:
    sent: list[tuple[str, dict[str, Any]]] = []

    def post(path: str, body: dict[str, Any]) -> tuple[int, Any]:
        sent.append((path, body))
        return 200, {"access_token": NEW_TOKEN, "expiry_timestamp": "1"}

    assert fetch_token("a@b.c", "secret-pw", post) == NEW_TOKEN
    assert sent == [
        ("/api/auth/post/getToken", {"email": "a@b.c", "password": "secret-pw"})
    ]


@pytest.mark.parametrize(
    ("status", "payload"),
    [
        (401, {"error": "Invalid email or password."}),
        (200, {"expiry_timestamp": "1"}),
        (502, None),
    ],
)
def test_fetch_token_failures_never_echo_the_password(
    status: int, payload: Any
) -> None:
    with pytest.raises(RotationError) as exc:
        fetch_token("a@b.c", "secret-pw", lambda *_: (status, payload))
    assert f"HTTP {status}" in str(exc.value)
    assert "secret-pw" not in str(exc.value)


def test_check_token_requires_life_and_onemap_acceptance() -> None:
    now = time.time()
    calls: list[str] = []

    def accepted(path: str, params: dict[str, Any], token: str) -> tuple[int, Any]:
        calls.append(path)
        return 200, [{"name": "KENT RIDGE MRT STATION"}]

    check_token(jwt(now + MIN_REMAINING_SECONDS + 60), accepted, lambda: now)
    assert calls == ["/api/public/nearbysvc/getNearestMrtStops"]

    with pytest.raises(RotationError, match="expires in"):
        check_token(jwt(now + 3600), accepted, lambda: now)
    with pytest.raises(RotationError, match="HTTP 401"):
        check_token(
            jwt(now + 3 * 24 * 3600),
            lambda *_: (401, {"message": "Unauthorized"}),
            lambda: now,
        )


@pytest.mark.parametrize("token", ["", "not-a-jwt", "a.!!!.c", "a.e30.c"])
def test_token_expiry_rejects_non_jwts(token: str) -> None:
    with pytest.raises(RotationError, match="not a JWT"):
        token_expiry(token)


def test_handler_requires_the_credentials_secret_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ONEMAP_CREDENTIALS_SECRET_NAME", raising=False)
    context = type(
        "Context",
        (),
        {
            "function_name": "rotation-test",
            "memory_limit_in_mb": 128,
            "invoked_function_arn": "arn:aws:lambda:local:0:function:rotation-test",
            "aws_request_id": "rotation-test",
        },
    )()
    with pytest.raises(RuntimeError, match="ONEMAP_CREDENTIALS_SECRET_NAME"):
        rotation_handler.handler(event("createSecret"), context)
