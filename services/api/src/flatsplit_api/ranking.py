"""Group constraint filtering (#21) and fairness ranking (#22).

Pure functions with no storage access: the search read path (#18) loads the
group's members, the pinned rent snapshot and the commute matrix, then calls
`rank_towns`. Rules follow docs/api-contract.md ("Feasibility and ranking"):

- A town is feasible only when its rent summary is USABLE and, for every member,
  rentPerPerson <= budget and commuteMinutes <= maxCommute (both inclusive,
  compared unrounded; commute minutes may be fractional).
- cost = wRent * rentPerPerson/2000 + wAvg * averageCommute/90 + wGap * gap/90
  and score = max(0, round-half-up(100 * (1 - cost))). The arithmetic order
  mirrors the wireframe's `evaluateAreas` so both produce identical scores.
- Ranked towns sort by score descending, then display name. Excluded towns with
  complete, usable inputs follow by their hypothetical score; towns missing
  usable rent or routes come last, by display name.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

Priority = Literal["balanced", "fairness", "budget"]
RouteStatus = Literal["ok", "pending", "unavailable"]
QualityStatus = Literal["USABLE", "LOW_CONFIDENCE"]
ReasonCode = Literal[
    "OVER_BUDGET",
    "OVER_COMMUTE",
    "ROUTE_UNAVAILABLE",
    "RENT_UNAVAILABLE",
    "RENT_LOW_CONFIDENCE",
]

#: Fixed scales make scores comparable across priorities (wireframe baseline, D07).
RENT_SCALE = 2000
COMMUTE_SCALE = 90


class Weights(BaseModel):
    rent: float
    averageCommute: float
    commuteGap: float


WEIGHTS: dict[Priority, Weights] = {
    "balanced": Weights(rent=0.35, averageCommute=0.35, commuteGap=0.3),
    "fairness": Weights(rent=0.2, averageCommute=0.25, commuteGap=0.55),
    "budget": Weights(rent=0.7, averageCommute=0.2, commuteGap=0.1),
}


@dataclass(frozen=True)
class MemberInput:
    """One ready member, in join order."""

    memberId: str
    name: str
    budget: float | Decimal
    maxCommute: int
    stationKey: str


@dataclass(frozen=True)
class RentSummary:
    """The fields of a `RENT#<snapshotId>` item that results expose."""

    median: float | Decimal
    p25: float | Decimal
    p75: float | Decimal
    medianCi95Low: float | Decimal
    medianCi95High: float | Decimal
    count: int
    qualityStatus: QualityStatus


@dataclass(frozen=True)
class Commute:
    """A `COMMUTE#<stationKey>/TOWN#<town>` item; minutes only when status is ok."""

    status: RouteStatus
    minutes: float | None = None


class MemberOutcome(BaseModel):
    memberId: str
    commuteMinutes: float | None
    routeStatus: RouteStatus
    budgetHeadroom: float | None
    commuteHeadroom: float | None


class Reason(BaseModel):
    code: ReasonCode
    memberId: str | None
    amount: float | None
    message: str


class AreaResult(BaseModel):
    town: str
    displayName: str
    rank: int | None
    score: int | None
    wholeFlatRent: float | None
    rentPerPerson: float | None
    rentP25: float | None
    rentP75: float | None
    rentMedianCi95Low: float | None
    rentMedianCi95High: float | None
    rentSampleSize: int | None
    rentQualityStatus: QualityStatus | None
    averageCommute: float | None
    longestCommute: float | None
    shortestCommute: float | None
    commuteGap: float | None
    mostBurdenedMemberId: str | None
    members: list[MemberOutcome]
    reasons: list[Reason]


class Ranking(BaseModel):
    priority: Priority
    weights: Weights
    ranked: list[AreaResult]
    excluded: list[AreaResult]


class PendingRoutesError(ValueError):
    """Results exist only once every route is resolved (contract status rules)."""


def display_name(town: str) -> str:
    """`KALLANG/WHAMPOA` -> `Kallang/Whampoa`; HDB keys stay the identity."""
    return town.title()


def _round_half_up(value: float) -> int:
    # JavaScript's Math.round, which the wireframe uses; Python's round() would
    # round halves to even and break score parity.
    return math.floor(value + 0.5)


def _money(value: float) -> str:
    return f"S${math.ceil(value):,}"


@dataclass
class _Evaluated:
    result: AreaResult
    sort_score: int | None


def _evaluate(
    town: str,
    members: Sequence[MemberInput],
    rent: RentSummary | None,
    commutes: Mapping[tuple[str, str], Commute],
    weights: Weights,
) -> _Evaluated:
    name = display_name(town)
    size = len(members)
    reasons: list[Reason] = []

    usable_rent = rent is not None and rent.qualityStatus == "USABLE"
    per_person = float(rent.median) / size if rent is not None else None
    if rent is None:
        reasons.append(
            Reason(
                code="RENT_UNAVAILABLE",
                memberId=None,
                amount=None,
                message=f"No rent data for this flat type in {name}.",
            )
        )
    elif not usable_rent:
        reasons.append(
            Reason(
                code="RENT_LOW_CONFIDENCE",
                memberId=None,
                amount=None,
                message=f"Too few consistent rents in {name} to compare budgets.",
            )
        )

    outcomes: list[MemberOutcome] = []
    times: list[float] = []
    for member in members:
        commute = commutes.get((member.stationKey, town))
        if commute is None or commute.status == "pending":
            raise PendingRoutesError(
                f"Route {member.stationKey} -> {town} is not resolved yet."
            )
        budget = float(member.budget)
        headroom = (
            budget - per_person if usable_rent and per_person is not None else None
        )
        if headroom is not None and headroom < 0:
            reasons.append(
                Reason(
                    code="OVER_BUDGET",
                    memberId=member.memberId,
                    amount=math.ceil(-headroom),
                    message=(
                        f"Over {member.name}'s budget by {_money(-headroom)}/month"
                    ),
                )
            )

        minutes = commute.minutes if commute.status == "ok" else None
        if minutes is None:
            reasons.append(
                Reason(
                    code="ROUTE_UNAVAILABLE",
                    memberId=member.memberId,
                    amount=None,
                    message=f"No public-transport route found for {member.name}.",
                )
            )
        else:
            times.append(minutes)
            if minutes > member.maxCommute:
                over = minutes - member.maxCommute
                reasons.append(
                    Reason(
                        code="OVER_COMMUTE",
                        memberId=member.memberId,
                        amount=over,
                        message=(
                            f"{member.name}'s commute exceeds their limit by "
                            f"{math.ceil(over)} min"
                        ),
                    )
                )
        outcomes.append(
            MemberOutcome(
                memberId=member.memberId,
                commuteMinutes=minutes,
                routeStatus=commute.status,
                budgetHeadroom=headroom,
                commuteHeadroom=(
                    member.maxCommute - minutes if minutes is not None else None
                ),
            )
        )

    all_routes = len(times) == size
    average = longest = shortest = gap = None
    burdened = None
    if all_routes:
        total = 0.0
        for minutes in times:
            total += minutes
        average = total / size
        longest, shortest = max(times), min(times)
        gap = longest - shortest
        # Ties go to the earliest joiner: index() finds the first longest commute.
        burdened = members[times.index(longest)].memberId

    sort_score = None
    if usable_rent and all_routes and per_person is not None:
        assert average is not None and gap is not None
        cost = (
            weights.rent * (per_person / RENT_SCALE)
            + weights.averageCommute * (average / COMMUTE_SCALE)
            + weights.commuteGap * (gap / COMMUTE_SCALE)
        )
        sort_score = max(0, _round_half_up((1 - cost) * 100))

    feasible = not reasons
    return _Evaluated(
        AreaResult(
            town=town,
            displayName=name,
            rank=None,
            score=sort_score if feasible else None,
            wholeFlatRent=float(rent.median) if rent is not None else None,
            rentPerPerson=per_person,
            rentP25=float(rent.p25) if rent is not None else None,
            rentP75=float(rent.p75) if rent is not None else None,
            rentMedianCi95Low=float(rent.medianCi95Low) if rent is not None else None,
            rentMedianCi95High=(
                float(rent.medianCi95High) if rent is not None else None
            ),
            rentSampleSize=rent.count if rent is not None else None,
            rentQualityStatus=rent.qualityStatus if rent is not None else None,
            averageCommute=round(average, 2) if average is not None else None,
            longestCommute=longest,
            shortestCommute=shortest,
            commuteGap=gap,
            mostBurdenedMemberId=burdened,
            members=outcomes,
            reasons=reasons,
        ),
        sort_score,
    )


def rank_towns(
    members: Sequence[MemberInput],
    towns: Sequence[str],
    rents: Mapping[str, RentSummary],
    commutes: Mapping[tuple[str, str], Commute],
    priority: Priority = "balanced",
) -> Ranking:
    """Filter and rank `towns` for a fully ready group.

    `rents` maps town to the summary for the group's flat type (missing towns
    have no summary). `commutes` maps (stationKey, town) to that route.
    Raises PendingRoutesError if any needed route is missing or still pending.
    """
    if not members:
        raise ValueError("A group needs at least one member to rank towns.")
    weights = WEIGHTS[priority]
    evaluated = [
        _evaluate(town, members, rents.get(town), commutes, weights) for town in towns
    ]

    feasible = sorted(
        (e for e in evaluated if not e.result.reasons),
        key=lambda e: (-(e.sort_score or 0), e.result.displayName),
    )
    scored_exclusions = sorted(
        (e for e in evaluated if e.result.reasons and e.sort_score is not None),
        key=lambda e: (-(e.sort_score or 0), e.result.displayName),
    )
    unscored_exclusions = sorted(
        (e for e in evaluated if e.result.reasons and e.sort_score is None),
        key=lambda e: e.result.displayName,
    )

    ranked = [
        e.result.model_copy(update={"rank": position})
        for position, e in enumerate(feasible, start=1)
    ]
    return Ranking(
        priority=priority,
        weights=weights,
        ranked=ranked,
        excluded=[e.result for e in scored_exclusions + unscored_exclusions],
    )
