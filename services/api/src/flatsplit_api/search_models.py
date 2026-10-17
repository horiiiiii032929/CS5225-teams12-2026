"""Public search/status responses from the shared API contract."""

from typing import Literal

from pydantic import BaseModel

from flatsplit_api.ranking import AreaResult, Priority, Weights


class SearchProgress(BaseModel):
    total: int
    resolved: int
    unavailable: int


class SearchDataInfo(BaseModel):
    rentPeriod: str
    rentSource: str = "HDB rental approvals (data.gov.sg)"
    flatType: str
    commuteBasis: str = "Public transport, weekday 08:30 departure; station-to-station"


class SearchView(BaseModel):
    searchId: str
    groupRevision: int
    status: Literal["pending", "complete", "stale"]
    progress: SearchProgress
    priority: Priority
    weights: Weights
    data: SearchDataInfo
    ranked: list[AreaResult]
    excluded: list[AreaResult]
