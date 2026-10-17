"""#29 group journey: create, share the link, join, edit and reload.

Uses only the public HTTP contract, so it runs unchanged against a deployed API
(see conftest). Search and results steps are added once #18 and #23 provide
them.
"""

from dataclasses import dataclass
from typing import Any

import pytest

from .conftest import Api, Reply

NAMES = ["Alex", "Jamie", "Sam", "Priya", "Wei"]


@dataclass(frozen=True)
class Member:
    memberId: str
    memberToken: str
    name: str


def _ok(reply: Reply, status: int = 200) -> dict[str, Any]:
    assert reply.status == status, reply.body
    assert reply.headers.get("cache-control") == "no-store"
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
    # Create: the organiser gets both credentials, once.
    created = _ok(
        api.call(
            "POST",
            "/groups",
            {"groupName": f"E2E flat for {size}", "size": size, "name": NAMES[0]},
        ),
        201,
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
            api.call("POST", f"/groups/{gid}/members", {"name": name}, invite), 201
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
