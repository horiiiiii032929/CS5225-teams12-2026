"""#29 group-to-results journey: create, share the link, join, edit, reload,
search and read ranked results.

Uses only the public HTTP contract, so it runs unchanged against a deployed API
(see conftest). Locally the search results are fixture-backed: seeded synthetic
rent and injected commute minutes, never real HDB or OneMap data.
"""

import time
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Literal

import pytest

from .conftest import (
    DEFAULT_MINUTES,
    SEARCH_TIMEOUT_SECONDS,
    SEEDED_MINUTES,
    Api,
    LambdaApi,
    Reply,
)

NAMES = ["Alex", "Jamie", "Sam", "Priya", "Wei"]


#: docs/api-contract.md: the HDB towns every search ranks or explains.
TOWNS = 27
#: The flat type a search uses for each group size (search_data._FLAT_TYPES).
FLAT_TYPES = {2: "3-ROOM", 5: "5-ROOM"}


@dataclass(frozen=True)
class Member:
    memberId: str
    memberToken: str
    name: str


@dataclass(frozen=True)
class Journey:
    gid: str
    invite: str
    members: list[Member]


def _no_credentials(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            assert key not in {
                "memberToken",
                "inviteToken",
                "tokenHash",
                "inviteTokenHash",
            }, f"Unexpected credential field: {key}"
            _no_credentials(child)
    elif isinstance(value, list):
        for child in value:
            _no_credentials(child)


def _ok(
    reply: Reply,
    status: int = 200,
    *,
    credentials: Literal["create", "join"] | None = None,
) -> dict[str, Any]:
    assert reply.status == status, reply.body
    assert reply.headers.get("cache-control") == "no-store"
    public = dict(reply.body)
    if credentials is not None:
        public.pop("memberToken", None)
    if credentials == "create":
        public["group"] = dict(public["group"])
        public["group"].pop("inviteToken", None)
    _no_credentials(public)
    return reply.body


def _preferences(name: str, place_id: str, index: int) -> dict[str, Any]:
    return {
        "name": name,
        "placeId": place_id,
        "budget": 1200 + 50 * index,
        "maxCommute": 30 + 5 * index,
    }


def _save(api: Api, gid: str, member: Member, body: dict[str, Any]) -> Reply:
    reply = api.call(
        "PUT", f"/groups/{gid}/members/{member.memberId}", body, member.memberToken
    )
    if api.remote and reply.status == 404 and "Place" in str(reply.body):
        pytest.skip("Deployed API cannot resolve placeIds until #14 persists places.")
    return reply


@pytest.mark.parametrize("size", [2, 5])
def test_group_journey(api: Api, place_id: str, size: int) -> None:
    _group_journey(api, place_id, size)


def _group_journey(api: Api, place_id: str, size: int) -> Journey:
    # Create: the organiser gets both credentials, once.
    created = _ok(
        api.call(
            "POST",
            "/groups",
            {"groupName": f"E2E flat for {size}", "size": size, "name": NAMES[0]},
        ),
        201,
        credentials="create",
    )
    gid = created["group"]["groupId"]
    invite = created["group"]["inviteToken"]
    members = [Member(created["memberId"], created["memberToken"], NAMES[0])]
    assert created["group"]["members"][0]["isOrganiser"] is True

    # Link: the invite token joins but cannot read; reload never re-exposes it.
    assert api.call("GET", f"/groups/{gid}", token=invite).status == 403
    organiser_view = _ok(
        api.call("GET", f"/groups/{gid}", token=members[0].memberToken)
    )
    assert "inviteToken" not in organiser_view["group"]

    # Join through the link until the group is full.
    for name in NAMES[1:size]:
        joined = _ok(
            api.call("POST", f"/groups/{gid}/members", {"name": name}, invite),
            201,
            credentials="join",
        )
        assert "inviteToken" not in joined["group"]
        members.append(Member(joined["memberId"], joined["memberToken"], name))
    full = api.call("POST", f"/groups/{gid}/members", {"name": "Late"}, invite)
    assert (full.status, full.body["error"]["code"]) == (409, "GROUP_FULL")

    # Invalid input is rejected without changing the group.
    bad = _save(
        api, gid, members[0], {**_preferences(NAMES[0], place_id, 0), "budget": 100}
    )
    assert (bad.status, bad.body["error"]["code"]) == (422, "VALIDATION_FAILED")

    # Edit: every member saves preferences and becomes ready.
    for index, member in enumerate(members):
        saved = _ok(_save(api, gid, member, _preferences(member.name, place_id, index)))
        assert saved["group"]["readyCount"] == index + 1
    # One revision for creation, then one per join and one per save.
    revision = 1 + (size - 1) + size
    assert saved["group"]["allReady"] is True
    assert saved["group"]["revision"] == revision

    # A later edit (rename and new limits) bumps the revision and stays ready.
    renamed = _ok(
        _save(
            api,
            gid,
            members[-1],
            {**_preferences("Renamed", place_id, 0), "maxCommute": 60},
        )
    )
    assert renamed["group"]["revision"] == revision + 1
    assert renamed["group"]["allReady"] is True

    # Reload: every member sees the same saved state.
    views = [
        _ok(api.call("GET", f"/groups/{gid}", token=m.memberToken))["group"]
        for m in members
    ]
    assert all(view == views[0] for view in views)
    group = views[0]
    assert group["revision"] == revision + 1
    assert [m["name"] for m in group["members"]] == [*NAMES[: size - 1], "Renamed"]
    assert [m["ready"] for m in group["members"]] == [True] * size
    assert group["members"][-1]["maxCommute"] == 60
    assert all(m["destination"]["placeId"] == place_id for m in group["members"])
    return Journey(gid, invite, members)


def _start(api: Api, gid: str, token: str) -> Reply:
    reply = api.call("POST", f"/groups/{gid}/searches", token=token)
    if api.remote and reply.status == 503 and "Rental" in str(reply.body):
        pytest.skip("Deployed API has no published rent snapshot until #10.")
    return reply


def _results(
    api: Api, gid: str, sid: str, token: str, priority: str | None = None
) -> dict[str, Any]:
    """The search once it has left `pending`; remote searches wait for #15."""
    path = f"/groups/{gid}/searches/{sid}"
    if priority is not None:
        path += f"?priority={priority}"
    deadline = time.monotonic() + (SEARCH_TIMEOUT_SECONDS if api.remote else 0)
    while True:
        body = _ok(api.call("GET", path, token=token))
        if body["status"] != "pending":
            return body
        if not api.remote:
            pytest.fail(f"Local search still pending: {body['progress']}")
        if time.monotonic() >= deadline:
            pytest.skip("Routes still pending: the deployed stack needs #15's worker.")
        time.sleep(5)


def _check_results(result: dict[str, Any], group: dict[str, Any]) -> None:
    """Contract invariants that hold for real and fixture data alike."""
    size = len(group["members"])
    limits = {m["memberId"]: m for m in group["members"]}
    assert result["status"] == "complete"
    assert result["progress"]["resolved"] == result["progress"]["total"]
    assert result["data"]["flatType"] == FLAT_TYPES[size]
    ranked, excluded = result["ranked"], result["excluded"]
    towns = [area["town"] for area in ranked + excluded]
    assert len(towns) == len(set(towns)) == TOWNS
    assert [area["rank"] for area in ranked] == list(range(1, len(ranked) + 1))
    # Score descending, ties broken by display name (docs/api-contract.md).
    order = [(-area["score"], area["displayName"]) for area in ranked]
    assert order == sorted(order)
    for area in ranked:
        assert area["reasons"] == []
        assert area["rentPerPerson"] == pytest.approx(area["wholeFlatRent"] / size)
        assert [m["memberId"] for m in area["members"]] == list(limits)
        for outcome in area["members"]:
            member = limits[outcome["memberId"]]
            assert outcome["routeStatus"] == "ok"
            assert outcome["commuteMinutes"] <= member["maxCommute"]
            assert outcome["budgetHeadroom"] >= 0
        longest = max(m["commuteMinutes"] for m in area["members"])
        assert area["longestCommute"] == longest
    for area in excluded:
        assert area["reasons"] and area["rank"] is None and area["score"] is None


def _check_seeded_results(result: dict[str, Any], group: dict[str, Any]) -> None:
    """Exact expectations for the synthetic rent and minutes seeded locally."""
    ranked = {area["town"]: area for area in result["ranked"]}
    # The order comes from the score and its tie-break, checked above.
    assert set(ranked) == {"CLEMENTI", "QUEENSTOWN", "BUKIT MERAH"}
    alex = group["members"][0]["memberId"]
    # Inclusive limits, compared unrounded: exactly at budget and at the limit.
    assert ranked["QUEENSTOWN"]["members"][0]["budgetHeadroom"] == 0
    assert ranked["QUEENSTOWN"]["members"][0]["commuteMinutes"] == 25.5
    assert ranked["BUKIT MERAH"]["members"][0]["commuteHeadroom"] == 0
    reasons = {
        area["town"]: {(r["code"], r["memberId"]) for r in area["reasons"]}
        for area in result["excluded"]
    }
    # Only Alex's 30-minute limit is under JURONG EAST's 35 minutes.
    assert reasons["JURONG EAST"] == {("OVER_COMMUTE", alex)}
    per_person = next(
        area["rentPerPerson"] for area in result["excluded"] if area["town"] == "BISHAN"
    )
    assert reasons["BISHAN"] == {
        ("OVER_BUDGET", m["memberId"])
        for m in group["members"]
        if m["budget"] < per_person
    }
    assert reasons["TENGAH"] == {
        ("ROUTE_UNAVAILABLE", m["memberId"]) for m in group["members"]
    } | {("RENT_UNAVAILABLE", None)}
    unseeded = set(reasons) - {"JURONG EAST", "BISHAN", "TENGAH"}
    assert len(unseeded) == TOWNS - len(ranked) - 3
    assert all(reasons[town] == {("RENT_UNAVAILABLE", None)} for town in unseeded)


@pytest.mark.parametrize("size", [2, 5])
def test_search_journey(api: Api, place_id: str, size: int) -> None:
    journey = _group_journey(api, place_id, size)
    gid, members = journey.gid, journey.members
    token = members[0].memberToken
    path = f"/groups/{gid}/searches"

    # Start: the invite link cannot search; a ready member can.
    assert api.call("POST", path, token=journey.invite).status == 403
    started = _ok(_start(api, gid, token), 201)
    sid = started["searchId"]
    # Everyone shares one destination: one station x every town.
    assert started["progress"]["total"] == TOWNS
    if started["status"] == "pending":
        assert started["ranked"] == started["excluded"] == []
    # Starting again, from any member, joins the same search.
    again = _ok(api.call("POST", path, token=members[-1].memberToken), 201)
    assert again["searchId"] == sid

    if isinstance(api, LambdaApi):
        # TENGAH resolves as unavailable without routing, so 26 jobs go out.
        assert len(api.jobs) == TOWNS - 1
        api.complete_routes(SEEDED_MINUTES, DEFAULT_MINUTES)

    group = _ok(api.call("GET", f"/groups/{gid}", token=token))["group"]
    result = _results(api, gid, sid, token)
    _check_results(result, group)
    if not api.remote:
        _check_seeded_results(result, group)

    # Priority reweights the score; feasibility does not change.
    fairness = _results(api, gid, sid, token, priority="fairness")
    _check_results(fairness, group)
    assert fairness["priority"] == "fairness"
    assert fairness["weights"] != result["weights"]
    assert {a["town"] for a in fairness["ranked"]} == {
        a["town"] for a in result["ranked"]
    }

    # Every member's reload shows the finished search.
    for member in members:
        view = _ok(api.call("GET", f"/groups/{gid}", token=member.memberToken))
        latest = view["group"]["latestSearch"]
        assert (latest["searchId"], latest["status"]) == (sid, "complete")

    # An edit makes the results stale and withholds them; a new search starts.
    edited = _ok(
        _save(
            api,
            gid,
            members[0],
            {**_preferences(NAMES[0], place_id, 0), "maxCommute": 31},
        )
    )
    assert edited["group"]["latestSearch"]["status"] == "stale"
    stale = _ok(api.call("GET", f"{path}/{sid}", token=token))
    assert stale["status"] == "stale"
    assert stale["ranked"] == stale["excluded"] == []
    fresh = _ok(_start(api, gid, token), 201)
    assert fresh["searchId"] != sid
    assert fresh["groupRevision"] == result["groupRevision"] + 1


@pytest.mark.parametrize(
    ("method", "location"),
    [
        ("GET", "envelope"),
        ("PUT", "envelope"),
        ("POST", "group"),
        ("GET", "member"),
        ("PUT", "member"),
        ("POST", "member"),
    ],
)
@pytest.mark.parametrize("field", ["memberToken", "inviteToken"])
def test_journey_rejects_leaked_credentials(
    api: Api,
    place_id: str,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    location: str,
    field: str,
) -> None:
    if api.remote:
        pytest.skip("Response mutations use only the isolated local API.")
    original = api.call

    def leaking(
        verb: str, path: str, body: Any = None, token: str | None = None
    ) -> Reply:
        reply = original(verb, path, body, token)
        if verb != method or reply.status not in (200, 201):
            return reply
        mutated = deepcopy(reply.body)
        target = mutated
        if location == "group":
            target = mutated["group"]
            # inviteToken belongs only in this exact create response location.
            if field == "inviteToken" and path == "/groups":
                return reply
        elif location == "member":
            target = mutated["group"]["members"][0]
        target[field] = "synthetic-leaked-credential"
        return replace(reply, body=mutated)

    monkeypatch.setattr(api, "call", leaking)
    with pytest.raises(AssertionError, match="credential"):
        test_search_journey(api, place_id, 2)
