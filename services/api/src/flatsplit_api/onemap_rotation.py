"""Automatic renewal of the OneMap token in Secrets Manager (#72).

OneMap issues a three-day JWT from `POST /api/auth/post/getToken` given the
account's email and password, and has no refresh endpoint. Until now the
token in `OneMapTokenSecret` was replaced by hand, and `/places` failed for
days whenever nobody did (21-28 October). Secrets Manager rotation calls this
module on a schedule with its standard four steps:

- `createSecret`: log in with the separate credentials secret and stage the
  new token as `AWSPENDING`.
- `setSecret`: nothing to do; OneMap issues tokens and stores nothing for us.
- `testSecret`: refuse a token that is malformed, expires too soon, or that
  OneMap rejects on a cheap authenticated call.
- `finishSecret`: move `AWSCURRENT` to the new version.

Readers keep using `AWSCURRENT` through `onemap.resolve_token`, whose 15-minute
cache picks up the new value. The old token stays valid until its own expiry,
so the switch has no gap. If a step fails, `AWSCURRENT` is untouched and the
next scheduled rotation tries again.
"""

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from aws_lambda_powertools import Logger

from flatsplit_api.onemap import BASE_URL, NEAREST_PATH, TIMEOUT_SECONDS, _decode

logger = Logger(child=True)

TOKEN_PATH = "/api/auth/post/getToken"
#: A token with less life than this is refused: rotation runs every 12 hours,
#: so anything shorter could expire before the next attempt.
MIN_REMAINING_SECONDS = 24 * 60 * 60
#: Kent Ridge MRT. The test call only needs an authenticated cheap endpoint.
_PROBE = {"latitude": 1.29330, "longitude": 103.78452, "radius_in_meters": 500}

Post = Callable[[str, dict[str, Any]], tuple[int, Any]]
Get = Callable[[str, dict[str, Any], str], tuple[int, Any]]


class RotationError(Exception):
    """A rotation step that must fail the invocation (and leave CURRENT alone)."""


def _http_post(path: str, body: dict[str, Any]) -> tuple[int, Any]:
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, _decode(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _decode(exc.read())
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RotationError(f"OneMap is unreachable: {exc}") from exc


def _http_get(path: str, params: dict[str, Any], token: str) -> tuple[int, Any]:
    request = urllib.request.Request(
        f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}",
        headers={"Authorization": token, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, _decode(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _decode(exc.read())
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RotationError(f"OneMap is unreachable: {exc}") from exc


def token_expiry(token: str) -> int:
    """The JWT's `exp` claim. The signature is OneMap's to check, not ours."""
    try:
        payload = token.split(".")[1]
        claims = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )
        return int(claims["exp"])
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise RotationError("OneMap returned a token that is not a JWT.") from exc


def fetch_token(email: str, password: str, post: Post = _http_post) -> str:
    """Log in to OneMap. Error bodies never include the credentials we sent."""
    status, payload = post(TOKEN_PATH, {"email": email, "password": password})
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if status != 200 or not isinstance(token, str) or not token:
        detail = payload.get("error") if isinstance(payload, dict) else None
        raise RotationError(f"OneMap getToken returned HTTP {status}: {detail}")
    return token


def check_token(
    token: str, get: Get = _http_get, now: Callable[[], float] = time.time
) -> None:
    """Refuse a token that expires too soon or that OneMap does not accept."""
    remaining = token_expiry(token) - now()
    if remaining < MIN_REMAINING_SECONDS:
        raise RotationError(f"New token expires in {remaining / 3600:.1f} h.")
    status, payload = get(NEAREST_PATH, _PROBE, token)
    if status != 200 or not isinstance(payload, list):
        raise RotationError(f"OneMap rejected the new token: HTTP {status}.")


class Rotator:
    """The four Secrets Manager rotation steps for the OneMap token secret."""

    def __init__(
        self,
        client: Any,
        credentials_secret_id: str,
        *,
        fetch: Callable[[str, str], str] = fetch_token,
        check: Callable[[str], None] = check_token,
    ) -> None:
        self.client = client
        self.credentials_secret_id = credentials_secret_id
        self._fetch = fetch
        self._check = check

    def handle(self, event: dict[str, Any]) -> None:
        secret_id, version, step = (
            event["SecretId"],
            event["ClientRequestToken"],
            event["Step"],
        )
        stages = self.client.describe_secret(SecretId=secret_id).get(
            "VersionIdsToStages", {}
        )
        # Secrets Manager's own preconditions for a rotation it started.
        if version not in stages:
            raise RotationError("Rotation version is not staged on the secret.")
        if "AWSCURRENT" in stages[version]:
            logger.info("Rotation version is already current", extra={"step": step})
            return
        if "AWSPENDING" not in stages[version]:
            raise RotationError("Rotation version is not AWSPENDING.")

        steps = {
            "createSecret": self._create,
            "setSecret": lambda *_: None,
            "testSecret": self._test,
            "finishSecret": self._finish,
        }
        if step not in steps:
            raise RotationError(f"Unknown rotation step: {step}")
        steps[step](secret_id, version, stages)
        logger.info("Rotation step completed", extra={"step": step})

    def _create(self, secret_id: str, version: str, _: dict[str, list[str]]) -> None:
        try:
            self.client.get_secret_value(
                SecretId=secret_id, VersionId=version, VersionStage="AWSPENDING"
            )
            return  # A retried createSecret must not log in again.
        except self.client.exceptions.ResourceNotFoundException:
            pass
        raw = self.client.get_secret_value(SecretId=self.credentials_secret_id)
        try:
            credentials = json.loads(raw["SecretString"])
            email, password = credentials["email"], credentials["password"]
        except (KeyError, TypeError, ValueError) as exc:
            raise RotationError(
                'The credentials secret must be {"email": ..., "password": ...}.'
            ) from exc
        token = self._fetch(email, password)
        self.client.put_secret_value(
            SecretId=secret_id,
            ClientRequestToken=version,
            SecretString=token,
            VersionStages=["AWSPENDING"],
        )

    def _test(self, secret_id: str, version: str, _: dict[str, list[str]]) -> None:
        pending = self.client.get_secret_value(
            SecretId=secret_id, VersionId=version, VersionStage="AWSPENDING"
        )["SecretString"]
        self._check(pending)

    def _finish(
        self, secret_id: str, version: str, stages: dict[str, list[str]]
    ) -> None:
        current = next(
            (vid for vid, names in stages.items() if "AWSCURRENT" in names), None
        )
        self.client.update_secret_version_stage(
            SecretId=secret_id,
            VersionStage="AWSCURRENT",
            MoveToVersionId=version,
            **({"RemoveFromVersionId": current} if current else {}),
        )
