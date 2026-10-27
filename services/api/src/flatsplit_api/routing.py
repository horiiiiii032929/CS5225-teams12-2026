"""OneMap public-transport routing for the queued commute worker (#15).

`/places` keeps its own transport in `onemap.py` because a user-facing read and
a queued job need opposite failure handling: the read gives up at once, while a
job is allowed to come back later. What differs here is the classification, and
it follows #3's live measurements rather than OneMap's documentation:

- No observed 429 carried `Retry-After`, so the retry schedule is ours. The
  worker's schedule is the queue's visibility timeout, not a sleep inside a
  billed invocation, so this module only decides whether an error may be
  retried at all.
- `numItineraries` above three is rejected with HTTP 400, and one itinerary
  missed the shortest route in one of eight sampled pairs (#6, 14 October).
  Three are requested and the smallest duration wins, so "shortest" is read
  from the durations instead of trusting OneMap's ordering.
- 404 describes the pair, not the call. It is terminal, and the pair must never
  be stored as zero minutes (D06, #19).
- 401/403 describe our credential, not the pair. A three-day token with no
  renewal makes that a routine failure, so it is classified apart from both.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from aws_lambda_powertools import Logger
from botocore.exceptions import ClientError

from flatsplit_api import call_budget
from flatsplit_api.onemap import BASE_URL, OneMapUnavailable, resolve_token

logger = Logger(child=True)

ROUTE_PATH = "/api/public/routingsvc/route"
#: Recorded on every stored result so a cached minute can be traced to its call.
SOURCE = "onemap:routingsvc/route?routeType=pt"
#: #3 measured routing p50 861 ms serially and 7.3 s worst case under load.
TIMEOUT_SECONDS = 20.0
#: More than three is rejected with 400 "must be between 1 and 3" (#3).
ITINERARIES = 3
#: #3 routed with this bound, and it matches the 1,000 m station-snapping bound.
MAX_WALK_METRES = 1000
#: A three-day token with no renewal: warn while a drain can still be stopped.
TOKEN_WARNING_SECONDS = 6 * 3600

_TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]")
#: 408 and 429 are the only 4xx that a later attempt can clear.
_RETRYABLE_STATUS = frozenset({408, 429})


class RoutingError(Exception):
    """Base failure, carrying the `error` code the worker stores on the pair."""

    code = "ROUTING_FAILED"


class RoutingRetryable(RoutingError):
    """Transient: throttling, 5xx, transport and unreadable bodies."""

    code = "ROUTING_UNAVAILABLE"


class RoutingUnroutable(RoutingError):
    """Terminal for this pair: OneMap has no public-transport route for it."""

    code = "NO_ROUTE"


class RoutingRejected(RoutingUnroutable):
    """Terminal and our fault: OneMap refused the request we built.

    A subclass of `RoutingUnroutable` so the worker's terminal branch catches
    both, because no delay makes a rejected request valid either. The distinct
    code keeps "we sent nonsense" out of the pair's no-route statistics.
    """

    code = "INVALID_ROUTE_REQUEST"


class RoutingCredential(RoutingError):
    """Our token, not the pair: nothing about this pair should be cached long."""

    code = "CREDENTIAL_UNAVAILABLE"


@dataclass(frozen=True)
class Route:
    """The shortest of the itineraries OneMap returned for one pair."""

    minutes: float
    transfers: int
    walk_minutes: float
    itineraries: int
    #: False when OneMap's first itinerary was not the shortest. #6 found that
    #: in 1 of 8 sampled pairs, which is why three are requested.
    shortest_was_first: bool


class Transport(Protocol):
    """Seam for tests: one routing GET, returning decoded JSON."""

    def __call__(self, params: dict[str, Any]) -> Any: ...


def token_seconds_left(token: str, *, now: float | None = None) -> float | None:
    """Seconds until the JWT's `exp`, or None when it carries no expiry.

    The signature is not verified; that is OneMap's job. Only `exp` is read,
    because a silently expired token is what #3 recorded: `/places` keeps
    answering 200 during the grace period, so nothing else reveals it.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, binascii.Error):
        return None
    expires_at = claims.get("exp") if isinstance(claims, dict) else None
    if not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool):
        return None
    return float(expires_at) - (time.time() if now is None else now)


def _token() -> str:
    """Resolve the token and refuse to spend quota on an expired one.

    `resolve_token` raises `/places`'s own `OneMapUnavailable` for a missing,
    empty or unreadable secret. That is outside this module's hierarchy, so it
    would escape the worker's terminal handling and leave the pair `pending`
    with no `retryAfter` even on the final receive. It is the same class of
    failure as an expired token - ours, not the pair's - so it arrives as
    `RoutingCredential`: retried while receives remain, then closed honestly.
    """
    try:
        token = resolve_token()
    except OneMapUnavailable as exc:
        raise RoutingCredential("The OneMap credential could not be loaded.") from exc
    left = token_seconds_left(token)
    if left is None:
        return token
    if left <= 0:
        raise RoutingCredential(
            "The OneMap token expired. Rotate the secret: there is no renewal."
        )
    if left < TOKEN_WARNING_SECONDS:
        logger.warning(
            "OneMap token is close to expiry",
            extra={"onemapTokenHoursLeft": round(left / 3600, 2)},
        )
    return token


def _spend_budget() -> None:
    """Count this call against C7's shared 250/min guard, below the worker's share.

    The budget is spent before the request, because C7 counts actual calls and
    a failed one has already reached OneMap. A full window is not an error
    about the pair: the message goes back to the queue, whose visibility
    timeout is the pacing this module deliberately does not implement itself.
    An unreadable counter fails the same way - closed - because the queue will
    bring the pair back, and spending unmetered quota is the worse outcome.
    """
    try:
        call_budget.spend(call_budget.WORKER_CALLS)
    except call_budget.BudgetExhausted as exc:
        raise RoutingRetryable(str(exc)) from exc
    except ClientError as exc:
        raise RoutingRetryable(f"The OneMap call budget is unreadable: {exc}") from exc


def _decode(raw: bytes) -> Any:
    """Parse JSON defensively: 429 and 403 bodies are sometimes HTML (#3)."""
    text = raw.decode("utf-8", "replace").lstrip()
    if not text.startswith(("{", "[")):
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _classify(status: int, payload: Any, fallback: str) -> RoutingError:
    message = fallback
    if isinstance(payload, dict):
        for key in ("error", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                message = value
                break
    if status in (401, 403):
        return RoutingCredential(message)
    if status == 404:
        # Unconditional: a routing 404 is "no route", never zero minutes.
        return RoutingUnroutable(message)
    if status in _RETRYABLE_STATUS:
        return RoutingRetryable(message)
    if 400 <= status < 500:
        return RoutingRejected(message)
    return RoutingRetryable(message)


def http_get(params: dict[str, Any], *, timeout: float = TIMEOUT_SECONDS) -> Any:
    """One routing GET. Retries belong to the queue, so there are none here."""
    _spend_budget()
    token = _token()
    url = f"{BASE_URL}{ROUTE_PATH}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url, headers={"Authorization": token, "Accept": "application/json"}
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = _decode(response.read())
    except urllib.error.HTTPError as exc:
        error = _classify(
            exc.code, _decode(exc.read()), f"OneMap returned HTTP {exc.code}."
        )
        logger.warning(
            "Routing call failed",
            extra={
                "upstreamStatus": exc.code,
                "routingError": error.code,
                "routingLatencyMs": round((time.monotonic() - started) * 1000),
            },
        )
        raise error from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RoutingRetryable(f"OneMap is unreachable: {exc}") from exc
    logger.info(
        "Routing call succeeded",
        extra={"routingLatencyMs": round((time.monotonic() - started) * 1000)},
    )
    if payload is None:
        raise RoutingRetryable("OneMap routing returned an unreadable body.")
    return payload


def _coordinate(point: Any, key: str, limit: float) -> float:
    value = point.get(key) if isinstance(point, dict) else None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise RoutingRejected(f"The job's {key} is not a number.") from exc
    if not math.isfinite(number) or abs(number) > limit:
        raise RoutingRejected(f"The job's {key} is outside the valid range.")
    return number


def _point(point: Any) -> str:
    return f"{_coordinate(point, 'lat', 90)},{_coordinate(point, 'lng', 180)}"


def _onemap_date(routing_date: Any) -> str:
    """OneMap wants MM-DD-YYYY; the contract's job carries ISO YYYY-MM-DD."""
    if not isinstance(routing_date, str):
        raise RoutingRejected("The job has no routing date.")
    try:
        return date.fromisoformat(routing_date).strftime("%m-%d-%Y")
    except ValueError as exc:
        raise RoutingRejected(
            f"The job's routing date {routing_date!r} is not a date."
        ) from exc


def _seconds(itinerary: Any) -> float:
    value = itinerary.get("duration") if isinstance(itinerary, dict) else None
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        # A shape change upstream, not an answer about this pair: retry, and
        # let the DLQ hold it for a person if it keeps happening.
        raise RoutingRetryable("OneMap returned an itinerary without a duration.")
    return float(value)


def _minutes(itinerary: dict[str, Any], key: str) -> float:
    value = itinerary.get(key)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        return 0.0
    return round(value / 60, 1)


def _shortest(payload: Any) -> Route:
    plan = payload.get("plan") if isinstance(payload, dict) else None
    itineraries = plan.get("itineraries") if isinstance(plan, dict) else None
    if not isinstance(itineraries, list) or not itineraries:
        # #3 saw 404 for an unroutable pair, but a 200 with an empty plan is
        # the same answer about the pair and must reach the same place.
        raise RoutingUnroutable("OneMap returned no itinerary for this pair.")
    durations = [_seconds(itinerary) for itinerary in itineraries]
    best = min(range(len(durations)), key=durations.__getitem__)
    itinerary = itineraries[best]
    transfers = itinerary.get("transfers")
    return Route(
        # Unrounded: #18/#22 compare this with each member's maxCommute, and
        # rounding 1,802 s to 30.0 would make a 30-minute limit feasible
        # (api-contract.md: fractional values retained for comparisons).
        # Display rounding belongs to the reader, not to the stored result.
        minutes=durations[best] / 60,
        transfers=transfers if isinstance(transfers, int) and transfers >= 0 else 0,
        walk_minutes=_minutes(itinerary, "walkTime"),
        itineraries=len(itineraries),
        shortest_was_first=durations[0] == durations[best],
    )


def route(
    origin: Any,
    destination: Any,
    *,
    routing_date: Any,
    routing_time: Any,
    transport: Transport | None = None,
) -> Route:
    """Route one pair and return its shortest itinerary.

    `origin` is the packaged town point and `destination` the pinned station,
    exactly as the contract's payload v1 carries them.
    """
    if not isinstance(routing_time, str) or _TIME.fullmatch(routing_time) is None:
        raise RoutingRejected("The job has no HH:MM:SS routing time.")
    params: dict[str, Any] = {
        "start": _point(origin),
        "end": _point(destination),
        "routeType": "pt",
        "date": _onemap_date(routing_date),
        "time": routing_time,
        "mode": "TRANSIT",
        "maxWalkDistance": MAX_WALK_METRES,
        "numItineraries": ITINERARIES,
    }
    payload = http_get(params) if transport is None else transport(params)
    return _shortest(payload)
