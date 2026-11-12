"""Validated inputs and safe storage views for the #12 HTTP handoff.

GroupState contains group/member state, not search summaries. The HTTP/search
layer composes latestSearch; token hashes and name reservations never leave storage.
"""

import unicodedata
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

from flatsplit_api.models import Place


def _display_name(value: object) -> object:
    return (
        unicodedata.normalize("NFC", value.strip()) if isinstance(value, str) else value
    )


MemberName = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=30),
    BeforeValidator(_display_name),
]
GroupName = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=40),
    BeforeValidator(_display_name),
]


class CreateGroupRequest(BaseModel):
    groupName: GroupName
    size: Annotated[int, Field(strict=True, ge=2, le=5)]
    name: MemberName


class JoinGroupRequest(BaseModel):
    name: MemberName
    retryToken: (
        Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9_-]{43}$")]
        | None
    ) = Field(default=None, repr=False)


class PreferencesRequest(BaseModel):
    name: MemberName
    placeId: Annotated[str, StringConstraints(strict=True, min_length=1)]
    budget: Annotated[float, Field(strict=True, ge=300, le=5000, allow_inf_nan=False)]
    maxCommute: Annotated[int, Field(strict=True, ge=10, le=120)]


class MemberState(BaseModel):
    memberId: str
    name: str
    isOrganiser: bool
    ready: bool
    destination: Place | None
    budget: float | None
    maxCommute: int | None


class GroupState(BaseModel):
    groupId: str
    groupName: str
    size: int
    revision: int
    members: list[MemberState]
    readyCount: int
    allReady: bool
    createdAt: datetime
    expiresAt: datetime


class Membership(BaseModel):
    """Only create/join return credentials; never log or persist this object."""

    model_config = ConfigDict(frozen=True)

    group: GroupState
    memberId: str
    memberToken: str = Field(repr=False)
    inviteToken: str | None = Field(default=None, repr=False)
