"""#14: the write side of `GET /places`, and the save it makes possible.

A lookup used to return a `placeId` it never stored, so `groups.py::_place`
could not resolve it and every preference save answered `Place not found or
expired.`. The read side and the transaction's `ttl > now` condition check were
already correct; nothing created the record they read.

These tests use the real lookup path with **no seeded place record**, which is
what the #16 handoff in the issue thread asked for: repeated lookups, a
replaced container, and an expired lookup cache. OneMap is stubbed with the
behaviour measured in #3 — in particular a station coordinate that moves
between calls, because `getNearestMrtStops` returns one entry per line code for
an interchange, in a varying order, up to ~100 m apart (re-measured at 133 m
against live OneMap on 20 October).

Several tests deliberately use a distinct query per lookup: identical queries
are served by the 24-hour query cache and never reach upstream, which would
make a pinning assertion pass for the wrong reason.
"""

import base64
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import boto3
import pytest
from moto import mock_aws
from mypy_boto3_dynamodb.service_resource import Table

import flatsplit_api.handlers.http as http
from flatsplit_api.groups import GroupStore
from flatsplit_api.onemap import find_places
from flatsplit_api.places import PLACE_TTL_SECONDS, PlaceStore

#: NUS, and the Kent Ridge exit this lookup happens to return (#3 evidence).
PLACE_LAT, PLACE_LNG = 1.2966, 103.7764
STATION_LAT, STATION_LNG = 1.2933, 103.7844
#: Another exit of the same physical station, about 200 m away and, from this
#: place, 755 m instead of 962 m. A later lookup offering a *closer* exit is
#: the sharpest case: the pin still has to win.
OTHER_EXIT_LAT, OTHER_EXIT_LNG = 1.2950, 103.7830
#: Straight-line metres from the place to each of the two exits.
PINNED_SNAP_METRES, CLOSER_SNAP_METRES = 962, 755

SEARCH: dict[str, Any] = {
    "found": 1,
    "totalNumPages": 1,
    "results": [
        {
            "SEARCHVAL": "NATIONAL UNIVERSITY OF SINGAPORE",
            "ADDRESS": "21 LOWER KENT RIDGE ROAD SINGAPORE 119077",
            "POSTAL": "119077",
            "LATITUDE": str(PLACE_LAT),
            "LONGITUDE": str(PLACE_LNG),
        }
    ],
}


@dataclass(frozen=True)
class FakeContext:
    function_name: str = "flatsplit-api-test"
    memory_limit_in_mb: int = 256
    invoked_function_arn: str = (
        "arn:aws:lambda:ap-southeast-1:000000000000:function:flatsplit-api-test"
    )
    aws_request_id: str = "test-request"


@dataclass
class Clock:
    now: datetime = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)

    def epoch(self) -> int:
        return int(self.now.timestamp())


@dataclass
class Reply:
    status: int
    body: dict[str, Any]


def stations(lat: float, lng: float, *, code: str = "CC24") -> list[dict[str, Any]]:
    return [
        {"id": code, "name": "KENT RIDGE MRT STATION", "lat": lat, "lon": lng},
        {
            "id": "CC25",
            "name": "HAW PAR VILLA MRT STATION",
            "lat": 1.2829,
            "lon": 103.7816,
        },
    ]


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def table(clock: Clock, monkeypatch: pytest.MonkeyPatch) -> Iterator[Table]:
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name="ap-southeast-1")
        created = resource.create_table(
            TableName="places-persistence-test",
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
        monkeypatch.setattr(
            http, "place_store", lambda: PlaceStore(created, clock=clock)
        )
        monkeypatch.setattr(
            http, "group_store", lambda: GroupStore(created, clock=clock)
        )
        yield created


class Lookup:
    """Runs `GET /places` against stubbed OneMap results, counting the calls.

    `calls` is what makes the query cache testable: a cache hit has to add
    nothing to it.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._monkeypatch = monkeypatch
        self.calls: list[str] = []

    def __call__(
        self,
        lat: float = STATION_LAT,
        lng: float = STATION_LNG,
        *,
        code: str = "CC24",
        query: str = "kent ridge",
        search: dict[str, Any] | None = None,
    ) -> Reply:
        payload = SEARCH if search is None else search

        def transport(path: str, params: dict[str, Any]) -> Any:
            self.calls.append(path)
            if path.endswith("search"):
                return payload
            return stations(lat, lng, code=code)

        self._monkeypatch.setattr(
            http, "find_places", lambda q: find_places(q, transport)
        )
        event = {
            "version": "2.0",
            "routeKey": "$default",
            "rawPath": "/api/places",
            "rawQueryString": "",
            "headers": {},
            "queryStringParameters": {"q": query},
            "requestContext": {
                "http": {
                    "method": "GET",
                    "path": "/api/places",
                    "sourceIp": "127.0.0.1",
                },
                "requestId": "test-request",
                "stage": "$default",
            },
            "isBase64Encoded": False,
        }
        response = http.handler(event, FakeContext())  # type: ignore[arg-type]
        return Reply(response["statusCode"], json.loads(response["body"]))


@pytest.fixture
def lookup(monkeypatch: pytest.MonkeyPatch) -> Lookup:
    return Lookup(monkeypatch)


def call(method: str, path: str, body: Any = None, token: str | None = None) -> Reply:
    headers = {"content-type": "application/json"}
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    event = {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": "",
        "headers": headers,
        "requestContext": {
            "http": {"method": method, "path": path, "sourceIp": "127.0.0.1"},
            "requestId": "test-request",
            "stage": "$default",
        },
        "body": base64.b64encode(json.dumps(body).encode()).decode(),
        "isBase64Encoded": True,
    }
    response = http.handler(event, FakeContext())  # type: ignore[arg-type]
    return Reply(response["statusCode"], json.loads(response["body"]))


def place_item(table: Table, place_id: str) -> dict[str, Any] | None:
    got: dict[str, Any] | None = table.get_item(
        Key={"pk": f"PLACE#{place_id}", "sk": "META"}, ConsistentRead=True
    ).get("Item")
    return got


def station_item(table: Table, key: str = "KENT_RIDGE") -> dict[str, Any] | None:
    got: dict[str, Any] | None = table.get_item(
        Key={"pk": f"STATION#{key}", "sk": "META"}, ConsistentRead=True
    ).get("Item")
    return got


# ------------------------------------------------------------------- writing


def test_a_lookup_stores_the_place_record(
    table: Table, clock: Clock, lookup: Lookup
) -> None:
    reply = lookup()

    assert reply.status == 200
    place = reply.body["places"][0]
    stored = place_item(table, place["placeId"])
    assert stored is not None, "the lookup returned a placeId it did not store"
    assert stored["label"] == "NATIONAL UNIVERSITY OF SINGAPORE"
    assert stored["address"] == "21 LOWER KENT RIDGE ROAD SINGAPORE 119077"
    assert float(stored["lat"]) == pytest.approx(PLACE_LAT)
    assert float(stored["lng"]) == pytest.approx(PLACE_LNG)
    assert stored["station"]["stationKey"] == "KENT_RIDGE"
    assert stored["ttl"] == clock.epoch() + PLACE_TTL_SECONDS


def test_a_lookup_pins_the_station_record(table: Table, lookup: Lookup) -> None:
    lookup()

    pinned = station_item(table)
    assert pinned is not None, "#15 has to route from a pinned coordinate"
    assert pinned["stationKey"] == "KENT_RIDGE"
    assert pinned["codes"] == ["CC24"]
    assert float(pinned["lat"]) == pytest.approx(STATION_LAT)
    assert "ttl" not in pinned, "a pin that expires is not a pin"


def test_the_place_record_expires_but_the_pin_does_not(
    table: Table, lookup: Lookup
) -> None:
    """The contract gives the place a 24-hour ttl; the station identity is permanent."""
    reply = lookup()

    stored = place_item(table, reply.body["places"][0]["placeId"])
    assert stored is not None
    assert "ttl" in stored
    pinned = station_item(table)
    assert pinned is not None
    assert "ttl" not in pinned


# -------------------------------------------------------------------- pinning


def test_repeated_lookups_do_not_move_the_pinned_coordinate(
    table: Table, clock: Clock, lookup: Lookup
) -> None:
    """Upstream returns a different exit each time; the stored identity cannot move."""
    first = lookup(STATION_LAT, STATION_LNG)
    place_id = first.body["places"][0]["placeId"]
    pinned = first.body["places"][0]["station"]
    assert pinned["snapMetres"] == PINNED_SNAP_METRES

    for index in range(5):
        clock.advance(minutes=10)
        # A distinct query each round, so every round really goes upstream
        # instead of being served by the query cache.
        again = lookup(
            OTHER_EXIT_LAT + index / 10_000,
            OTHER_EXIT_LNG,
            query=f"kent ridge {index}",
        )
        candidate = again.body["places"][0]
        assert candidate["placeId"] == place_id
        assert candidate["station"] == pinned, f"the coordinate moved on round {index}"
        assert candidate["station"]["snapMetres"] != CLOSER_SNAP_METRES, (
            "the snap was re-measured against this lookup's exit, not the pin"
        )

    record = station_item(table)
    assert record is not None
    assert float(record["lat"]) == pytest.approx(STATION_LAT)
    assert float(record["lng"]) == pytest.approx(STATION_LNG)


def test_a_replaced_container_reuses_the_pinned_coordinate(
    table: Table, clock: Clock, lookup: Lookup, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new Lambda container holds no state, so the pin has to come from the table."""
    first = lookup(STATION_LAT, STATION_LNG)
    pinned = first.body["places"][0]["station"]

    monkeypatch.setattr(http, "place_store", lambda: PlaceStore(table, clock=clock))
    # A different query, so the pin has to come from the table rather than
    # from the query cache.
    again = lookup(OTHER_EXIT_LAT, OTHER_EXIT_LNG, query="nus kent ridge")

    assert again.body["places"][0]["station"] == pinned
    assert again.body["places"][0]["placeId"] == first.body["places"][0]["placeId"]


def test_the_first_pin_wins_a_concurrent_lookup(table: Table, clock: Clock) -> None:
    """Two containers resolving the same station: the loser reuses the winner."""
    one = PlaceStore(table, clock=clock)
    two = PlaceStore(table, clock=clock)
    candidate = {
        "placeId": "pl_test",
        "label": "NUS",
        "address": "21 Lower Kent Ridge Road",
        "lat": PLACE_LAT,
        "lng": PLACE_LNG,
        "station": {
            "stationKey": "KENT_RIDGE",
            "codes": ["CC24"],
            "name": "Kent Ridge",
            "lat": STATION_LAT,
            "lng": STATION_LNG,
            "snapMetres": 0,
            "snapWarning": False,
        },
    }
    other = {
        **candidate,
        "station": {
            **candidate["station"],  # type: ignore[dict-item]
            "lat": OTHER_EXIT_LAT,
            "lng": OTHER_EXIT_LNG,
        },
    }

    winner = one.persist({"places": [candidate], "unsupported": []})
    loser = two.persist({"places": [other], "unsupported": []})

    assert winner["places"][0]["station"]["lat"] == pytest.approx(STATION_LAT)
    assert loser["places"][0]["station"]["lat"] == pytest.approx(STATION_LAT)
    record = station_item(table)
    assert record is not None
    assert float(record["lat"]) == pytest.approx(STATION_LAT)


def test_aliases_merge_without_moving_the_coordinate(
    table: Table, clock: Clock, lookup: Lookup
) -> None:
    """#6: `EW24 / NS1` splits into aliases; merging them must not re-pin."""
    lookup(STATION_LAT, STATION_LNG, code="CC24")
    # Another query reaching the same place, so the station is resolved again
    # and its new alias has to merge into the pinned record.
    lookup(OTHER_EXIT_LAT, OTHER_EXIT_LNG, code="NS1", query="nus")

    record = station_item(table)
    assert record is not None
    assert record["codes"] == ["CC24", "NS1"]
    assert float(record["lat"]) == pytest.approx(STATION_LAT)


def test_concurrent_alias_additions_are_not_lost(
    table: Table, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """@wkkuu's #65 finding: the read-modify-write merge dropped one alias.

    Two lookups resolving the same station both read `[CC1]`; one stored
    `[CC1, NS24]` and the other then stored `[CC1, NE6]`, dropping `NS24`
    while both lookups reported success. The coordinate was never at risk.

    This drives `_pin` directly and commits the competing writer between this
    writer's read and its write, which is the window a read-modify-write
    loses. It fails against `SET codes = :codes` and passes against the
    compare-and-swap on `codesRevision`.
    """
    one = PlaceStore(table, clock=clock)
    two = PlaceStore(table, clock=clock)
    base = {
        "stationKey": "DHOBY_GHAUT",
        "name": "Dhoby Ghaut",
        "lat": 1.298869,
        "lng": 103.845557,
    }
    one._pin(dict(base, codes=["CC1"]))

    original = table.update_item
    raced = {"done": False}

    def interleaved(**kwargs: Any) -> Any:
        if not raced["done"]:
            raced["done"] = True
            two._pin(dict(base, codes=["NS24"]))
        return original(**kwargs)

    monkeypatch.setattr(table, "update_item", interleaved)
    merged = one._pin(dict(base, codes=["NE6"]))

    assert raced["done"], "the competing writer never ran"
    record = station_item(table, "DHOBY_GHAUT")
    assert record is not None
    assert record["codes"] == ["CC1", "NE6", "NS24"], "an alias was lost"
    assert merged["codes"] == ["CC1", "NE6", "NS24"]
    assert float(record["lat"]) == pytest.approx(1.298869)
    assert int(record["codesRevision"]) == 2


def test_an_unchanged_alias_list_is_not_rewritten(
    table: Table, clock: Clock, lookup: Lookup
) -> None:
    """No new codes means no write, so the revision stays where it was."""
    lookup(STATION_LAT, STATION_LNG, code="CC24")
    before = station_item(table)
    assert before is not None

    lookup(OTHER_EXIT_LAT, OTHER_EXIT_LNG, code="CC24", query="nus")

    after = station_item(table)
    assert after is not None
    assert after["codesRevision"] == before["codesRevision"]
    assert after["codes"] == ["CC24"]


def test_a_pinned_station_beyond_the_bound_is_not_selectable(
    table: Table, lookup: Lookup
) -> None:
    """Re-measure the 1,000 m bound after pinning, not before."""
    table.put_item(
        Item={
            "pk": "STATION#KENT_RIDGE",
            "sk": "META",
            "stationKey": "KENT_RIDGE",
            "codes": ["CC24"],
            "name": "Kent Ridge",
            "lat": Decimal("1.2850"),
            "lng": Decimal("103.7900"),
            "pinnedAt": "2026-10-19T00:00:00+00:00",
        }
    )

    reply = lookup(STATION_LAT, STATION_LNG)

    assert reply.body["places"] == []
    assert reply.body["unsupported"][0]["code"] == "STATION_TOO_FAR"
    assert reply.body["unsupported"][0]["snapMetres"] > 1000
    assert reply.body["ambiguous"] is False


# --------------------------------------------------------------- query cache


def test_a_repeated_query_costs_no_upstream_calls(table: Table, lookup: Lookup) -> None:
    """Without this cache, a repeat of the same query cost six calls (#14).

    One search plus one nearest-station call per candidate: measured at six
    calls and ~800 ms for `kent ridge` against live OneMap on 20 October.
    """
    first = lookup()
    assert lookup.calls, "the first lookup has to reach upstream"
    before = len(lookup.calls)

    second = lookup()

    assert len(lookup.calls) == before, "a cached query must not reach upstream"
    assert second.body == first.body


def test_the_query_cache_is_case_insensitive(table: Table, lookup: Lookup) -> None:
    """One entry serves every spelling, because the upstream search ignores case.

    Measured 20 October: `kent ridge`, `KENT RIDGE`, `Kent Ridge` and
    `kEnT rIdGe` all returned found=80 with byte-identical results.
    """
    first = lookup(query="kent ridge")
    before = len(lookup.calls)

    second = lookup(query="Kent Ridge")

    assert len(lookup.calls) == before
    assert second.body == first.body


def test_the_query_cache_expires_after_24_hours(
    table: Table, clock: Clock, lookup: Lookup
) -> None:
    lookup()
    before = len(lookup.calls)

    clock.advance(hours=25)
    lookup()

    assert len(lookup.calls) > before, "a 25-hour-old query must be looked up again"


def test_an_expired_place_record_makes_the_query_cache_a_miss(
    table: Table, lookup: Lookup
) -> None:
    """Never serve a cached placeId that a save would reject.

    The alias can outlive a place record it points at, because that place may
    have been created by an earlier query and carry an older ttl. Serving it
    anyway would hand back exactly the unsaveable placeId this module exists to
    prevent, so a missing record is a miss rather than a partial answer.
    """
    place_id = lookup().body["places"][0]["placeId"]
    table.delete_item(Key={"pk": f"PLACE#{place_id}", "sk": "META"})
    before = len(lookup.calls)

    again = lookup()

    assert len(lookup.calls) > before
    assert again.body["places"][0]["placeId"] == place_id
    assert place_item(table, place_id) is not None, "the record is written again"


def test_a_query_with_no_results_is_cached_too(table: Table, lookup: Lookup) -> None:
    """A repeated typo should not keep spending quota."""
    empty: dict[str, Any] = {"found": 0, "totalNumPages": 0, "results": []}

    first = lookup(query="somewhere in tokyo", search=empty)
    before = len(lookup.calls)
    second = lookup(query="somewhere in tokyo", search=empty)

    assert first.body == {"places": [], "unsupported": [], "ambiguous": False}
    assert second.body == first.body
    assert len(lookup.calls) == before


def test_the_query_cache_does_not_slide(
    table: Table, clock: Clock, lookup: Lookup
) -> None:
    """A hit must not extend the ttl, or a stale result could live forever."""
    lookup()
    stored = table.get_item(
        Key={"pk": "PLACELOOKUP#kent ridge", "sk": "META"}, ConsistentRead=True
    ).get("Item")
    assert stored is not None
    expiry = stored["ttl"]

    clock.advance(hours=12)
    lookup()

    after = table.get_item(
        Key={"pk": "PLACELOOKUP#kent ridge", "sk": "META"}, ConsistentRead=True
    ).get("Item")
    assert after is not None
    assert after["ttl"] == expiry


# ------------------------------------------------------- the save it unblocks


def organiser(table: Table) -> tuple[str, str, str]:
    created = call(
        "POST",
        "/api/groups",
        {"groupName": "Our next chapter", "size": 3, "name": "Alex"},
    )
    assert created.status == 201, created.body
    return (
        created.body["group"]["groupId"],
        created.body["memberId"],
        created.body["memberToken"],
    )


def save(group_id: str, member_id: str, token: str, place_id: str) -> Reply:
    return call(
        "PUT",
        f"/api/groups/{group_id}/members/{member_id}",
        {"name": "Alex", "placeId": place_id, "budget": 1400, "maxCommute": 45},
        token,
    )


def test_a_preference_save_resolves_the_place_the_lookup_wrote(
    table: Table, lookup: Lookup
) -> None:
    """The original defect: this save used to fail with 404 and no seeded record."""
    place_id = lookup().body["places"][0]["placeId"]
    group_id, member_id, token = organiser(table)

    saved = save(group_id, member_id, token, place_id)

    assert saved.status == 200, saved.body
    member = saved.body["group"]["members"][0]
    assert member["ready"] is True
    assert member["destination"]["placeId"] == place_id
    assert member["destination"]["label"] == "NATIONAL UNIVERSITY OF SINGAPORE"
    assert member["destination"]["station"]["stationKey"] == "KENT_RIDGE"
    assert member["destination"]["station"]["lat"] == pytest.approx(STATION_LAT)


def test_a_saved_preference_survives_the_lookup_cache_expiry(
    table: Table, clock: Clock, lookup: Lookup
) -> None:
    """The member keeps its own copy, so a 24-hour place ttl cannot erase it."""
    place_id = lookup().body["places"][0]["placeId"]
    group_id, member_id, token = organiser(table)
    assert save(group_id, member_id, token, place_id).status == 200

    clock.advance(hours=25)
    table.delete_item(Key={"pk": f"PLACE#{place_id}", "sk": "META"})  # TTL deletion

    reread = call("GET", f"/api/groups/{group_id}", token=token)

    assert reread.status == 200
    member = reread.body["group"]["members"][0]
    assert member["destination"]["station"]["stationKey"] == "KENT_RIDGE"


def test_an_expired_place_cannot_start_a_new_save(
    table: Table, clock: Clock, lookup: Lookup
) -> None:
    """An expired placeId fails honestly instead of inventing a destination."""
    place_id = lookup().body["places"][0]["placeId"]
    group_id, member_id, token = organiser(table)

    clock.advance(hours=25)
    rejected = save(group_id, member_id, token, place_id)

    assert rejected.status == 404
    assert rejected.body["error"]["code"] == "NOT_FOUND"


def test_a_relookup_after_expiry_restores_the_place_and_saves(
    table: Table, clock: Clock, lookup: Lookup
) -> None:
    """The whole acceptance scenario: expiry, a new container, then a save."""
    first = lookup(STATION_LAT, STATION_LNG)
    place_id = first.body["places"][0]["placeId"]
    pinned = first.body["places"][0]["station"]
    group_id, member_id, token = organiser(table)

    clock.advance(hours=25)
    table.delete_item(Key={"pk": f"PLACE#{place_id}", "sk": "META"})
    lookup.calls.clear()
    again = lookup(OTHER_EXIT_LAT, OTHER_EXIT_LNG)

    assert lookup.calls, "the 24-hour query cache should have expired as well"
    assert again.body["places"][0]["placeId"] == place_id
    assert again.body["places"][0]["station"] == pinned, "the pin survived expiry"

    saved = save(group_id, member_id, token, place_id)

    assert saved.status == 200, saved.body
    destination = saved.body["group"]["members"][0]["destination"]
    assert destination["station"]["lat"] == pytest.approx(STATION_LAT)
