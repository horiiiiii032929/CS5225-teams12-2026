"""Public #12 response shapes composed from GroupStore results (docs/api-contract.md).

Credentials appear only in the create/join models. GroupView has no inviteToken
field at all, so a read or save response cannot carry one by accident.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from flatsplit_api.group_models import GroupState, Membership, MemberState


class SearchSummary(BaseModel):
    searchId: str
    status: Literal["pending", "complete", "stale"]
    createdAt: datetime


class GroupView(BaseModel):
    groupId: str
    groupName: str
    size: int
    revision: int
    members: list[MemberState]
    readyCount: int
    allReady: bool
    # Searches arrive with #16/#18; until then no group has one.
    latestSearch: SearchSummary | None
    createdAt: datetime
    expiresAt: datetime


class CreatedGroupView(GroupView):
    inviteToken: str


class GroupResponse(BaseModel):
    group: GroupView


class MembershipResponse(BaseModel):
    group: GroupView
    memberId: str
    memberToken: str


class CreatedGroupResponse(BaseModel):
    group: CreatedGroupView
    memberId: str
    memberToken: str


def group_view(state: GroupState) -> GroupView:
    return GroupView(**state.model_dump(), latestSearch=None)


def group_response(state: GroupState) -> GroupResponse:
    return GroupResponse(group=group_view(state))


def created_response(membership: Membership) -> CreatedGroupResponse:
    if membership.inviteToken is None:
        raise ValueError("A created group must carry its invite token.")
    return CreatedGroupResponse(
        group=CreatedGroupView(
            **group_view(membership.group).model_dump(),
            inviteToken=membership.inviteToken,
        ),
        memberId=membership.memberId,
        memberToken=membership.memberToken,
    )


def joined_response(membership: Membership) -> MembershipResponse:
    return MembershipResponse(
        group=group_view(membership.group),
        memberId=membership.memberId,
        memberToken=membership.memberToken,
    )
