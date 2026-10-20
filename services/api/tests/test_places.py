"""`GET /places` (#14).

The OneMap behaviour asserted here is the behaviour measured in #3, not what
OneMap documents: two calls per lookup, HTTP 200 with an `error` field while a
token is unhealthy, and HTML bodies on 429 and 403.
"""

import builtins
import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import boto3
import pytest
from moto import mock_aws
from mypy_boto3_dynamodb.service_resource import Table

from flatsplit_api import onemap
from flatsplit_api.handlers import http as http_handler
from flatsplit_api.handlers.http import handler
from flatsplit_api.onemap import (
    OneMapRateLimited,
    OneMapUnavailable,
    find_places,
    normalise_query,
    station_display_name,
)
from flatsplit_api.places import PlaceStore


@dataclass(frozen=True)
class FakeContext:
    function_name: str = "flatsplit-api-test"
    memory_limit_in_mb: int = 256
    invoked_function_arn: str = (
        "arn:aws:lambda:ap-southeast-1:000000000000:function:flatsplit-api-test"
    )
    aws_request_id: str = "test-request"


def places_event(query: str | None) -> dict[str, Any]:
    params = {} if query is None else {"q": query}
    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": "/api/places",
        "rawQueryString": "",
        "headers": {},
        "queryStringParameters": params or None,
        "requestContext": {
            "http": {"method": "GET", "path": "/api/places", "sourceIp": "127.0.0.1"},
            "requestId": "test-request",
            "stage": "$default",
        },
        "isBase64Encoded": False,
    }


def call(query: str | None) -> tuple[int, Any]:
    response = handler(places_event(query), FakeContext())  # type: ignore[arg-type]
    return response["statusCode"], json.loads(response["body"])


@pytest.fixture(autouse=True)
def place_table(monkeypatch: pytest.MonkeyPatch) -> Iterator[Table]:
    """#14 stores every selectable candidate, so a lookup needs the table.

    Persistence itself is covered by `test_places_persistence.py`; this fixture
    only keeps the lookup behaviour here reachable through the handler.
    """
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name="ap-southeast-1")
        created = resource.create_table(
            TableName="places-lookup-test",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        monkeypatch.setattr(http_handler, "place_store", lambda: PlaceStore(created))
        yield created


# --------------------------------------------------------------- OneMap stubs

KENT_RIDGE_SEARCH: dict[str, Any] = {
    "found": 1,
    "totalNumPages": 1,
    "results": [
        {
            "SEARCHVAL": "NATIONAL UNIVERSITY OF SINGAPORE",
            "ADDRESS": "21 LOWER KENT RIDGE ROAD SINGAPORE 119077",
            "POSTAL": "119077",
            "LATITUDE": "1.2966",
            "LONGITUDE": "103.7764",
        }
    ],
}

KENT_RIDGE_STATIONS: list[dict[str, Any]] = [
    {"id": "CC24", "name": "KENT RIDGE MRT STATION", "lat": 1.2933, "lon": 103.7844},
    {"id": "CC25", "name": "HAW PAR VILLA MRT STATION", "lat": 1.2829, "lon": 103.7816},
]


def stub_transport(
    search: Any, stations: Any
) -> tuple[Any, list[tuple[str, dict[str, Any]]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def transport(path: str, params: dict[str, Any]) -> Any:
        calls.append((path, params))
        return search if path == onemap.SEARCH_PATH else stations

    return transport, calls


# ------------------------------------------------------------------ validation


@pytest.mark.parametrize("query", [None, "", "  ", "ab", " a "])
def test_short_query_is_rejected_with_the_contract_error_body(
    query: str | None,
) -> None:
    status, body = call(query)

    assert status == 422
    assert body["error"]["code"] == "VALIDATION_FAILED"
    assert body["error"]["details"] == [
        {"field": "q", "message": "Enter at least 3 characters."}
    ]


def test_query_over_one_hundred_characters_is_rejected() -> None:
    status, body = call("x" * 101)

    assert status == 422
    assert body["error"]["code"] == "VALIDATION_FAILED"


def test_whitespace_is_collapsed_before_the_length_check() -> None:
    assert normalise_query("  kent   ridge  ") == "kent ridge"


# -------------------------------------------------------------------- lookups


def test_a_lookup_returns_the_contract_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    transport, _ = stub_transport(KENT_RIDGE_SEARCH, KENT_RIDGE_STATIONS)
    monkeypatch.setattr(
        http_handler, "find_places", lambda query: find_places(query, transport)
    )

    status, body = call("kent ridge")

    assert status == 200
    assert len(body["places"]) == 1
    place = body["places"][0]
    assert place["label"] == "NATIONAL UNIVERSITY OF SINGAPORE"
    assert place["placeId"].startswith("pl_")
    assert place["station"]["name"] == "Kent Ridge"
    assert place["station"]["stationKey"] == "KENT_RIDGE"
    assert 800 <= place["station"]["snapMetres"] <= 1000


def test_one_lookup_costs_two_onemap_calls() -> None:
    transport, calls = stub_transport(KENT_RIDGE_SEARCH, KENT_RIDGE_STATIONS)

    find_places("kent ridge", transport)

    assert [path for path, _ in calls] == [onemap.SEARCH_PATH, onemap.NEAREST_PATH]


def test_no_match_returns_an_empty_list_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, _ = stub_transport({"found": 0, "results": []}, [])
    monkeypatch.setattr(
        http_handler, "find_places", lambda query: find_places(query, transport)
    )

    status, body = call("somewhere in tokyo")

    assert status == 200
    assert body == {"places": [], "unsupported": [], "ambiguous": False}


def test_at_most_five_candidates_are_returned() -> None:
    first: dict[str, Any] = KENT_RIDGE_SEARCH["results"][0]
    many = {
        "found": 12,
        "results": [dict(first, POSTAL=f"11907{index}") for index in range(12)],
    }
    transport, _ = stub_transport(many, KENT_RIDGE_STATIONS)

    assert len(find_places("nus", transport)["places"]) == onemap.MAX_RESULTS


def test_candidates_are_not_collapsed_to_one() -> None:
    """#3: taking the top hit silently chose the wrong station for three towns."""
    two = {
        "found": 2,
        "results": [
            dict(KENT_RIDGE_SEARCH["results"][0], SEARCHVAL="PASIR RIS MRT STATION"),
            dict(
                KENT_RIDGE_SEARCH["results"][0],
                SEARCHVAL="PASIR RIS EAST MRT STATION",
                POSTAL="519999",
            ),
        ],
    }
    transport, _ = stub_transport(two, KENT_RIDGE_STATIONS)

    places = find_places("pasir ris", transport)["places"]

    assert len(places) == 2
    assert {place["label"] for place in places} == {
        "PASIR RIS MRT STATION",
        "PASIR RIS EAST MRT STATION",
    }


def test_a_place_with_no_station_in_radius_is_not_offered() -> None:
    transport, _ = stub_transport(KENT_RIDGE_SEARCH, [])

    assert find_places("kent ridge", transport)["places"] == []


def test_place_id_is_stable_across_lookups() -> None:
    transport, _ = stub_transport(KENT_RIDGE_SEARCH, KENT_RIDGE_STATIONS)

    first = find_places("kent ridge", transport)["places"]
    second = find_places("KENT RIDGE", transport)["places"]

    assert first[0]["placeId"] == second[0]["placeId"]


def test_the_nearest_station_wins_not_the_first_listed() -> None:
    reversed_order = list(reversed(KENT_RIDGE_STATIONS))
    transport, _ = stub_transport(KENT_RIDGE_SEARCH, reversed_order)

    places = find_places("kent ridge", transport)["places"]

    assert places[0]["station"]["name"] == "Kent Ridge"


def test_an_unhealthy_token_still_serves_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Grace period (#3): search returns 200 with an `error` field and data."""
    with_warning = dict(
        KENT_RIDGE_SEARCH,
        error="Authentication token expired. Token is valid for 3 days",
    )
    transport, _ = stub_transport(with_warning, KENT_RIDGE_STATIONS)
    monkeypatch.setattr(
        http_handler, "find_places", lambda query: find_places(query, transport)
    )

    status, body = call("kent ridge")

    assert status == 200
    assert len(body["places"]) == 1


def test_a_non_json_search_body_is_an_upstream_failure() -> None:
    transport, _ = stub_transport("<html>blocked by WAF</html>", [])

    with pytest.raises(OneMapUnavailable):
        find_places("kent ridge", transport)


# --------------------------------------------------------------- upstream errors


def test_throttling_surfaces_as_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def throttled(query: str) -> list[dict[str, Any]]:
        raise OneMapRateLimited("Too Many Requests")

    monkeypatch.setattr(http_handler, "find_places", throttled)

    status, body = call("kent ridge")

    assert status == 429
    assert body["error"]["code"] == "RATE_LIMITED"


def test_upstream_failure_surfaces_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(query: str) -> list[dict[str, Any]]:
        raise OneMapUnavailable("OneMap is unreachable")

    monkeypatch.setattr(http_handler, "find_places", broken)

    status, body = call("kent ridge")

    assert status == 503
    assert body["error"]["code"] == "UPSTREAM_UNAVAILABLE"


# ---------------------------------------------------------------------- helpers


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("KENT RIDGE MRT STATION", "Kent Ridge"),
        ("KENT RIDGE MRT STATION (CC24)", "Kent Ridge"),
        ("DHOBY GHAUT MRT STATION", "Dhoby Ghaut"),
        ("JURONG EAST MRT STATION (EW24 / NS1)", "Jurong East"),
    ],
)
def test_station_names_are_made_readable(raw: str, expected: str) -> None:
    assert station_display_name(raw) == expected


def test_combined_station_codes_are_split() -> None:
    """Jurong East's raw id is literally the string "EW24 / NS1" (#3)."""
    transport, _ = stub_transport(
        KENT_RIDGE_SEARCH,
        [
            {
                "id": "EW24 / NS1",
                "name": "JURONG EAST MRT STATION",
                "lat": 1.2966,
                "lon": 103.7764,
            }
        ],
    )

    places = find_places("jurong east", transport)["places"]

    assert places[0]["station"]["stationKey"] == "JURONG_EAST"
    assert places[0]["station"]["codes"] == ["EW24", "NS1"]


def test_unknown_routes_use_the_contract_error_body() -> None:
    event = places_event(None)
    event["rawPath"] = "/api/missing"
    event["requestContext"]["http"]["path"] = "/api/missing"

    response = handler(event, FakeContext())  # type: ignore[arg-type]

    assert response["statusCode"] == 404
    assert json.loads(response["body"])["error"]["code"] == "NOT_FOUND"


def test_a_rounded_distance_does_not_bypass_the_hard_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, _ = stub_transport(KENT_RIDGE_SEARCH, KENT_RIDGE_STATIONS)
    monkeypatch.setattr(onemap, "haversine_metres", lambda *args: 1000.4)
    monkeypatch.setattr(
        http_handler, "find_places", lambda query: find_places(query, transport)
    )

    status, body = call("kent ridge")

    assert status == 200
    assert body["places"] == []
    assert body["unsupported"][0]["code"] == "STATION_TOO_FAR"
    assert body["unsupported"][0]["snapMetres"] == 1000


def test_a_missing_station_is_distinct_from_no_search_match() -> None:
    transport, _ = stub_transport(KENT_RIDGE_SEARCH, [])
    found = find_places("kent ridge", transport)
    assert found["places"] == []
    assert found["unsupported"][0]["code"] == "NO_STATION"


def test_duplicate_hits_do_not_use_the_five_candidate_budget() -> None:
    first = KENT_RIDGE_SEARCH["results"][0]
    transport, calls = stub_transport(
        {"results": [first] * 5 + [dict(first, POSTAL="119099")]},
        KENT_RIDGE_STATIONS,
    )
    found = find_places("kent ridge", transport)
    assert len(found["places"]) == 2
    assert found["ambiguous"] is True
    assert len(calls) == 3


def test_interchange_aliases_share_one_physical_identity() -> None:
    entries = [
        {"id": code, "name": "DHOBY GHAUT MRT STATION", "lat": 1.2966, "lon": 103.7764}
        for code in ["NS24", "CC1", "NE6"]
    ]
    for ordered in [entries, list(reversed(entries))]:
        transport, _ = stub_transport(KENT_RIDGE_SEARCH, ordered)
        station = find_places("dhoby ghaut", transport)["places"][0]["station"]
        assert station["stationKey"] == "DHOBY_GHAUT"
        assert station["codes"] == ["CC1", "NE6", "NS24"]


def test_lookup_stops_before_sequential_timeouts_exceed_lambda_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter([0.0, 0.0, 8.1])
    monkeypatch.setattr(time, "monotonic", lambda: next(clock))
    transport, calls = stub_transport(KENT_RIDGE_SEARCH, KENT_RIDGE_STATIONS)
    with pytest.raises(OneMapUnavailable, match="request budget"):
        find_places("kent ridge", transport)
    assert len(calls) == 1


@pytest.mark.parametrize("latitude", ["nan", "inf", "95"])
def test_invalid_upstream_coordinates_are_not_a_successful_empty_result(
    latitude: str,
) -> None:
    first = dict(KENT_RIDGE_SEARCH["results"][0], LATITUDE=latitude)
    transport, _ = stub_transport({"results": [first]}, [])
    with pytest.raises(OneMapUnavailable, match="coordinates"):
        find_places("kent ridge", transport)


def test_non_json_station_response_is_an_upstream_error() -> None:
    transport, _ = stub_transport(KENT_RIDGE_SEARCH, "<html>blocked</html>")
    with pytest.raises(OneMapUnavailable, match="station search"):
        find_places("kent ridge", transport)


def test_control_characters_are_rejected_before_upstream_access() -> None:
    status, body = call("kent\x00ridge")
    assert status == 422
    assert body["error"]["code"] == "VALIDATION_FAILED"


def test_secret_provider_failure_is_a_public_upstream_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def broken_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "aws_lambda_powertools.utilities":
            raise ImportError("provider unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.delenv("ONEMAP_TOKEN", raising=False)
    monkeypatch.setenv("ONEMAP_SECRET_NAME", "test-only-secret")
    monkeypatch.setattr(builtins, "__import__", broken_import)
    with pytest.raises(OneMapUnavailable, match="could not be loaded"):
        onemap.resolve_token()


def test_credential_loading_uses_the_upstream_request_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter([0.0, 5.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(onemap, "resolve_token", lambda: "test-only")
    with pytest.raises(OneMapUnavailable, match="Credential loading"):
        onemap.http_get(onemap.SEARCH_PATH, {}, timeout=4.0)
