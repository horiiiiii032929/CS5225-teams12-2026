"""Scheduled renewal of the OneMap token in Secrets Manager (#72).

OneMap issues a three-day JWT from `POST /api/auth/post/getToken` given the
account's email and password, and has no refresh endpoint. Until now the
token in `OneMapTokenSecret` was replaced by hand, and `/places` failed for
days whenever nobody did (23-28 October).

A login does not renew anything: while the account's token is valid, OneMap
returns that same token (observed 29-31 October: logins a day apart returned
one token issued 28 October). So a new token only exists once the old one has
expired, and the schedule's job is to notice that quickly. An EventBridge rule
runs `refresh_token` every 15 minutes:

1. stop if the stored token has more than 24 hours left, without logging in;
2. read `{"email", "password"}` from the separate credentials secret;
3. log in to OneMap. Getting the stored token back is success, with no write;
4. otherwise refuse a token that is not a JWT, has expired, or that OneMap
   rejects on a cheap authenticated call;
5. only then write it as the token secret's new `AWSCURRENT` value.

Logging in through the last 24 hours exercises the credentials before they are
needed, so a changed password raises the alarm while the token still works.
Each expiry still leaves a gap of up to 15 minutes before the next run, plus
up to 15 more for readers using `onemap.resolve_token`, whose cache picks up
the new value. Any failure leaves the current token untouched.

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
#: A scheduled run with more life than this left does not log in at all.
RENEW_WITHIN_SECONDS = 24 * 60 * 60
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
    """Refuse a token that has expired or that OneMap does not accept."""
    if token_expiry(token) <= now():
        raise RefreshError("OneMap returned an expired token.")
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


def _stored_expiry(token: str) -> int:
    """The stored token's expiry; CDK's placeholder counts as long expired."""
    try:
        return token_expiry(token)
    except RefreshError:
        return 0


def refresh_token(
    client: Any,
    token_secret_id: str,
    credentials_secret_id: str,
    *,
    force: bool = False,
    fetch: Callable[[str, str], str] = fetch_token,
    check: Callable[[str], None] = check_token,
    now: Callable[[], float] = time.time,
) -> int:
    """Keep a valid token as AWSCURRENT; return its expiry.

    `force` logs in however long the stored token has left, so a changed
    account takes effect at once.
    """
    stored = client.get_secret_value(SecretId=token_secret_id)["SecretString"]
    stored_expiry = _stored_expiry(stored)
    if not force and stored_expiry - now() > RENEW_WITHIN_SECONDS:
        return stored_expiry
    email, password = read_credentials(client, credentials_secret_id)
    token = fetch(email, password)
    if token == stored:
        if stored_expiry <= now():
            raise RefreshError("OneMap returned an expired token.")
        return stored_expiry
    check(token)
    client.put_secret_value(SecretId=token_secret_id, SecretString=token)
    return token_expiry(token)
