"""Scheduled renewal of the OneMap token in Secrets Manager (#72).

OneMap issues a three-day JWT from `POST /api/auth/post/getToken` given the
account's email and password, and has no refresh endpoint. Until now the
token in `OneMapTokenSecret` was replaced by hand, and `/places` failed for
days whenever nobody did (23-28 October). An EventBridge rule now runs
`refresh_token` every 12 hours:

1. read `{"email", "password"}` from the separate credentials secret;
2. log in to OneMap;
3. refuse a token that is not a JWT, expires within 24 hours, or that OneMap
   rejects on a cheap authenticated call;
4. only then write it as the token secret's new `AWSCURRENT` value.

Any failure leaves the current token untouched, and the next run, 12 hours
later, tries again while the old token still has days to live. Readers keep
using `onemap.resolve_token`, whose 15-minute cache picks up the new value.

This is a scheduled Lambda rather than Secrets Manager rotation on purpose:
rotation runs `testSecret` against a placeholder during every deployment, so
a deploy could fail before the credentials were ever stored (#82 review).

Error messages are fixed text plus HTTP status codes. Provider response text
is never included and exception chains are suppressed, because OneMap's
error body is not a safe place to assume the submitted password is absent.
"""

import base64
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from flatsplit_api.onemap import BASE_URL, NEAREST_PATH, _decode

TOKEN_PATH = "/api/auth/post/getToken"
#: A new token with less life than this is refused: runs are 12 hours apart,
#: so anything shorter could expire before the next attempt.
MIN_REMAINING_SECONDS = 24 * 60 * 60
#: Kent Ridge MRT. The check only needs a cheap authenticated endpoint.
_PROBE = {"latitude": 1.29330, "longitude": 103.78452, "radius_in_meters": 500}

Send = Callable[[urllib.request.Request], tuple[int, Any]]


class RefreshError(Exception):
    """A refresh that must fail. Its message is safe to log as is."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        # Never carry the password or a bearer token to another origin; a
        # redirect is a failed call, not a different endpoint to trust.
        return None


_opener = urllib.request.build_opener(_NoRedirect())


def _send(request: urllib.request.Request) -> tuple[int, Any]:
    try:
        with _opener.open(request, timeout=10) as response:
            return response.status, _decode(response.read())
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, None  # The body is never read into a message.
    except (urllib.error.URLError, TimeoutError):
        raise RefreshError("OneMap is unreachable.") from None


def token_expiry(token: str) -> int:
    """The JWT's `exp` claim. The signature is OneMap's to check, not ours."""
    try:
        payload = token.split(".")[1]
        decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        return int(json.loads(decoded)["exp"])
    except (IndexError, KeyError, TypeError, ValueError):
        raise RefreshError("OneMap returned a token that is not a JWT.") from None


def fetch_token(email: str, password: str, send: Send = _send) -> str:
    """Log in to OneMap."""
    request = urllib.request.Request(
        f"{BASE_URL}{TOKEN_PATH}",
        data=json.dumps({"email": email, "password": password}).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    status, payload = send(request)
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if status != 200 or not isinstance(token, str) or not token:
        raise RefreshError(f"OneMap login failed: HTTP {status}.")
    return token


def check_token(
    token: str, send: Send = _send, now: Callable[[], float] = time.time
) -> None:
    """Refuse a token that expires too soon or that OneMap does not accept."""
    remaining = token_expiry(token) - now()
    if remaining < MIN_REMAINING_SECONDS:
        raise RefreshError(f"New token expires in {remaining / 3600:.1f} h.")
    request = urllib.request.Request(
        f"{BASE_URL}{NEAREST_PATH}?{urlencode(_PROBE)}",
        headers={"Authorization": token, "Accept": "application/json"},
    )
    status, payload = send(request)
    if status != 200 or not isinstance(payload, list):
        raise RefreshError(f"OneMap rejected the new token: HTTP {status}.")


def read_credentials(client: Any, secret_id: str) -> tuple[str, str]:
    raw = client.get_secret_value(SecretId=secret_id)["SecretString"]
    try:
        credentials = json.loads(raw)
        email, password = credentials["email"], credentials["password"]
    except (KeyError, TypeError, ValueError):
        raise RefreshError(
            'The credentials secret must be {"email": ..., "password": ...}.'
        ) from None
    if not (
        isinstance(email, str) and isinstance(password, str) and email and password
    ):
        raise RefreshError("The credentials secret has an empty email or password.")
    return email, password


def refresh_token(
    client: Any,
    token_secret_id: str,
    credentials_secret_id: str,
    *,
    fetch: Callable[[str, str], str] = fetch_token,
    check: Callable[[str], None] = check_token,
) -> int:
    """Store a fresh, checked token as AWSCURRENT; return its expiry."""
    email, password = read_credentials(client, credentials_secret_id)
    token = fetch(email, password)
    check(token)
    client.put_secret_value(SecretId=token_secret_id, SecretString=token)
    return token_expiry(token)
