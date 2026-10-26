"""OneMap public-transport routing for the queued worker (#15).

What is asserted is #3's measured behaviour rather than OneMap's documentation:
no observed 429 carried `Retry-After`, `numItineraries` above three is refused
with 400, and one itinerary missed the shortest route in 1 of 8 sampled pairs
(#6). A routing 404 describes the pair, so it is terminal here and must never
reach the cache as zero minutes (D06, #19); 401/403 describe our token instead,
which a three-day JWT with no renewal makes a routine failure.
"""

import base64
import io
import json
import time
import urllib.error
import urllib.request
from email.message import Message
from typing import Any

import pytest

from flatsplit_api import routing
from flatsplit_api.routing import (
    RoutingCredential,
    RoutingError,
    RoutingRejected,
    RoutingRetryable,
    RoutingUnroutable,
    route,
    token_seconds_left,
)

ORIGIN = {"lat": 1.29455, "lng": 103.806077}
DESTINATION = {"lat": 1.2936, "lng": 103.7845}
DATE = "2026-10-21"
TIME = "08:30:00"


def leg(seconds: float, *, transfers: int = 1, walk: float = 300.0) -> dict[str, Any]:
    return {"duration": seconds, "transfers": transfers, "walkTime": walk}


def plan(*itineraries: dict[str, Any]) -> dict[str, Any]:
    return {"plan": {"itineraries": list(itineraries)}}


def stub(payload: Any) -> tuple[routing.Transport, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    def transport(params: dict[str, Any]) -> Any:
        calls.append(params)
        return payload

    return transport, calls


def routed(
    payload: Any, *, routing_date: Any = DATE, routing_time: Any = TIME
) -> tuple[routing.Route, list[dict[str, Any]]]:
    transport, calls = stub(payload)
    resolved = route(
        ORIGIN,
        DESTINATION,
        routing_date=routing_date,
        routing_time=routing_time,
        transport=transport,
    )
    return resolved, calls


def jwt(expires_at: Any) -> str:
    claims = {} if expires_at is None else {"exp": expires_at}
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{body}.signature"


class Response:
    """Minimal `urlopen` result: a context manager with a readable body."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def transport_error(code: int, body: bytes = b'{"error":"upstream said so"}') -> Any:
    def failing(request: Any, timeout: float | None = None) -> Response:
        raise urllib.error.HTTPError(
            request.full_url, code, "upstream", Message(), io.BytesIO(body)
        )

    return failing


@pytest.fixture(autouse=True)
def token(monkeypatch: pytest.MonkeyPatch) -> str:
    """A token good for a day, so expiry is only in play where it is tested."""
    value = jwt(time.time() + 86400)
    monkeypatch.setattr(routing, "resolve_token", lambda: value)
    return value


def test_three_itineraries_are_requested_and_the_shortest_one_wins() -> None:
    resolved, calls = routed(plan(leg(2400), leg(1830, transfers=2), leg(2100)))
    assert resolved.minutes == 30.5
    assert resolved.transfers == 2
    assert resolved.walk_minutes == 5.0
    assert resolved.itineraries == 3
    # The reason three are requested: #6 found OneMap's first is not always it.
    assert resolved.shortest_was_first is False
    assert calls[0]["numItineraries"] == 3


def test_an_upstream_order_that_was_already_shortest_is_recorded_as_such() -> None:
    resolved, _ = routed(plan(leg(1830), leg(2400)))
    assert resolved.minutes == 30.5
    assert resolved.shortest_was_first is True


def test_the_request_carries_the_bounds_measured_in_issue_3() -> None:
    _, calls = routed(plan(leg(1830)))
    assert calls[0] == {
        "start": "1.29455,103.806077",
        "end": "1.2936,103.7845",
        "routeType": "pt",
        # OneMap wants MM-DD-YYYY; the contract's payload carries ISO.
        "date": "10-21-2026",
        "time": TIME,
        "mode": "TRANSIT",
        "maxWalkDistance": 1000,
        "numItineraries": 3,
    }


def test_a_two_hundred_with_an_empty_plan_is_the_same_answer_as_a_404() -> None:
    for payload in [{"plan": {"itineraries": []}}, {"plan": {}}, {}]:
        with pytest.raises(RoutingUnroutable):
            routed(payload)


def test_an_itinerary_without_a_duration_is_retried_not_cached_as_zero() -> None:
    with pytest.raises(RoutingRetryable, match="without a duration"):
        routed(plan({"transfers": 1}))
    with pytest.raises(RoutingRetryable):
        routed(plan(leg(-60)))


def test_a_missing_walk_time_or_transfer_count_does_not_fail_the_pair() -> None:
    resolved, _ = routed(plan({"duration": 1800}))
    assert (resolved.minutes, resolved.transfers, resolved.walk_minutes) == (
        30.0,
        0,
        0.0,
    )


@pytest.mark.parametrize(
    "routing_date", ["2026-13-01", "21-10-2026", "", None, 20261021]
)
def test_a_job_whose_date_is_not_a_date_is_our_bug_not_the_pairs(
    routing_date: Any,
) -> None:
    transport, calls = stub(plan(leg(1830)))
    with pytest.raises(RoutingRejected):
        route(
            ORIGIN,
            DESTINATION,
            routing_date=routing_date,
            routing_time=TIME,
            transport=transport,
        )
    assert calls == []  # Quota is not spent on a request we know is invalid.


@pytest.mark.parametrize("routing_time", ["08:30", "24:00:00", "8:30:00", None])
def test_a_job_without_a_full_clock_time_is_refused_before_the_call(
    routing_time: Any,
) -> None:
    transport, calls = stub(plan(leg(1830)))
    with pytest.raises(RoutingRejected, match="HH:MM:SS"):
        route(
            ORIGIN,
            DESTINATION,
            routing_date=DATE,
            routing_time=routing_time,
            transport=transport,
        )
    assert calls == []


@pytest.mark.parametrize(
    "point",
    [
        {"lat": "nan", "lng": 103.8},
        {"lat": float("inf"), "lng": 103.8},
        {"lat": 95.0, "lng": 103.8},
        {"lat": 1.3, "lng": 181.0},
        {"lat": 1.3},
        "1.3,103.8",
    ],
)
def test_coordinates_that_cannot_be_routed_are_refused_before_the_call(
    point: Any,
) -> None:
    transport, calls = stub(plan(leg(1830)))
    with pytest.raises(RoutingRejected):
        route(
            point,
            DESTINATION,
            routing_date=DATE,
            routing_time=TIME,
            transport=transport,
        )
    assert calls == []


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (404, RoutingUnroutable),
        (400, RoutingRejected),
        (422, RoutingRejected),
        (401, RoutingCredential),
        (403, RoutingCredential),
        (408, RoutingRetryable),
        (429, RoutingRetryable),
        (500, RoutingRetryable),
        (502, RoutingRetryable),
        (503, RoutingRetryable),
    ],
)
def test_each_upstream_status_lands_in_its_own_class(
    monkeypatch: pytest.MonkeyPatch, status: int, expected: type[RoutingError]
) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", transport_error(status))
    with pytest.raises(expected) as raised:
        routing.http_get({"routeType": "pt"})
    assert type(raised.value) is expected
    assert str(raised.value) == "upstream said so"


def test_a_routing_404_is_terminal_and_is_never_a_zero_minute_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", transport_error(404, b"not found"))
    with pytest.raises(RoutingUnroutable) as raised:
        route(ORIGIN, DESTINATION, routing_date=DATE, routing_time=TIME)
    # Terminal, but not the "we sent nonsense" code: the pair has no route.
    assert raised.value.code == "NO_ROUTE"
    assert not isinstance(raised.value, RoutingRejected)


def test_a_rejected_request_keeps_its_own_code_out_of_no_route_statistics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", transport_error(400))
    with pytest.raises(RoutingUnroutable) as raised:
        routing.http_get({"numItineraries": 9})
    # Terminal like a 404 (no delay makes it valid) with a distinguishable code.
    assert raised.value.code == "INVALID_ROUTE_REQUEST"


@pytest.mark.parametrize(
    "failure",
    [urllib.error.URLError("connection reset"), TimeoutError("timed out")],
)
def test_transport_failures_are_retryable(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    def failing(request: Any, timeout: float | None = None) -> Response:
        raise failure

    monkeypatch.setattr(urllib.request, "urlopen", failing)
    with pytest.raises(RoutingRetryable):
        routing.http_get({"routeType": "pt"})


def test_an_html_body_on_a_two_hundred_is_retryable_not_a_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout=None: Response(b"<html>blocked</html>"),
    )
    with pytest.raises(RoutingRetryable, match="unreadable"):
        routing.http_get({"routeType": "pt"})


def test_an_html_error_body_still_classifies_by_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # #3 recorded HTML bodies on 429 and 403; the status is what we classify on.
    monkeypatch.setattr(
        urllib.request, "urlopen", transport_error(429, b"<html>slow down</html>")
    )
    with pytest.raises(RoutingRetryable, match="HTTP 429"):
        routing.http_get({"routeType": "pt"})


def test_the_live_call_sends_the_token_and_the_routing_path(
    monkeypatch: pytest.MonkeyPatch, token: str
) -> None:
    seen: list[Any] = []

    def capture(request: Any, timeout: float | None = None) -> Response:
        seen.append((request, timeout))
        return Response(json.dumps(plan(leg(1830))).encode())

    monkeypatch.setattr(urllib.request, "urlopen", capture)
    resolved = route(ORIGIN, DESTINATION, routing_date=DATE, routing_time=TIME)
    assert resolved.minutes == 30.5
    request, timeout = seen[0]
    assert request.full_url.startswith(
        "https://www.onemap.gov.sg/api/public/routingsvc/route?"
    )
    assert request.get_header("Authorization") == token
    assert timeout == routing.TIMEOUT_SECONDS


def test_an_expired_token_fails_without_spending_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(routing, "resolve_token", lambda: jwt(time.time() - 1))
    called: list[Any] = []

    def capture(request: Any, timeout: float | None = None) -> Response:
        called.append(request)
        return Response(b"{}")

    monkeypatch.setattr(urllib.request, "urlopen", capture)
    with pytest.raises(RoutingCredential, match="expired"):
        routing.http_get({"routeType": "pt"})
    assert called == []


def test_a_token_near_expiry_warns_but_is_still_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A long drain should be stoppable before the token dies mid-queue."""
    monkeypatch.setattr(routing, "resolve_token", lambda: jwt(time.time() + 3600))
    warnings: list[Any] = []
    monkeypatch.setattr(
        routing.logger, "warning", lambda *args, **kwargs: warnings.append(kwargs)
    )
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout=None: Response(json.dumps(plan(leg(1830))).encode()),
    )
    assert routing.http_get({"routeType": "pt"})["plan"]["itineraries"]
    assert warnings[0]["extra"]["onemapTokenHoursLeft"] == 1.0


@pytest.mark.parametrize("token_value", ["not-a-jwt", "a.b", "a.!!!!.c", "a.e30.c"])
def test_a_token_whose_expiry_cannot_be_read_is_used_anyway(
    monkeypatch: pytest.MonkeyPatch, token_value: str
) -> None:
    """Only OneMap can judge a token; an unreadable `exp` must not block work."""
    monkeypatch.setattr(routing, "resolve_token", lambda: token_value)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout=None: Response(json.dumps(plan(leg(1830))).encode()),
    )
    assert token_seconds_left(token_value) is None
    assert routing.http_get({"routeType": "pt"}) is not None


def test_token_seconds_left_reads_the_expiry_without_verifying_the_signature() -> None:
    assert token_seconds_left(jwt(1_800_000_000), now=1_799_999_100) == 900.0
    assert token_seconds_left(jwt(1_799_999_000), now=1_800_000_000) == -1000.0
    for unusable in [jwt(True), jwt("1800000000"), jwt(None), jwt([1])]:
        assert token_seconds_left(unusable) is None
