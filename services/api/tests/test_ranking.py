"""#21 constraint filtering and #22 fairness ranking."""

from decimal import Decimal

import pytest

from flatsplit_api.ranking import (
    Commute,
    MemberInput,
    PendingRoutesError,
    Priority,
    RentSummary,
    display_name,
    rank_towns,
)

# The wireframe's fictional fixtures (apps/web/src/features/wireframes/model.ts):
# whole-flat rent and minutes to each destination. Not HDB or OneMap data.
WIREFRAME_AREAS: dict[str, tuple[int, dict[str, int]]] = {
    "QUEENSTOWN": (3600, {"nus": 22, "one-north": 18, "raffles": 27}),
    "CLEMENTI": (3300, {"nus": 12, "one-north": 22, "raffles": 42}),
    "BUKIT MERAH": (3900, {"nus": 33, "one-north": 27, "raffles": 17}),
    "JURONG EAST": (3000, {"nus": 30, "one-north": 38, "raffles": 55}),
    "BISHAN": (3750, {"nus": 45, "one-north": 35, "raffles": 27}),
    "TOA PAYOH": (3450, {"nus": 38, "one-north": 30, "raffles": 23}),
}
SAMPLE_GROUP = [
    MemberInput("alex", "Alex", 1400, 45, "nus"),
    MemberInput("jamie", "Jamie", 1300, 45, "one-north"),
    MemberInput("sam", "Sam", 1400, 45, "raffles"),
]

# Produced by running the wireframe's evaluateAreas on sampleGroup() for each
# priority: (display name, feasible, score). Excluded scores are hypothetical.
WIREFRAME_RESULTS: dict[Priority, list[tuple[str, bool, int]]] = {
    "balanced": [
        ("Queenstown", True, 67),
        ("Toa Payoh", True, 63),
        ("Bukit Merah", True, 62),
        ("Clementi", True, 61),
        ("Bishan", True, 58),
        ("Jurong East", False, 58),
    ],
    "fairness": [
        ("Queenstown", True, 76),
        ("Toa Payoh", True, 71),
        ("Bukit Merah", True, 70),
        ("Bishan", True, 67),
        ("Clementi", True, 64),
        ("Jurong East", False, 63),
    ],
    "budget": [
        ("Clementi", True, 53),
        ("Queenstown", True, 52),
        ("Toa Payoh", True, 51),
        ("Bukit Merah", True, 47),
        ("Bishan", True, 46),
        ("Jurong East", False, 53),
    ],
}


def usable(median: float) -> RentSummary:
    return RentSummary(
        median=median,
        p25=median * 0.9,
        p75=median * 1.1,
        medianCi95Low=median * 0.97,
        medianCi95High=median * 1.03,
        count=400,
        qualityStatus="USABLE",
    )


def wireframe_inputs() -> tuple[
    list[str], dict[str, RentSummary], dict[tuple[str, str], Commute]
]:
    towns = list(WIREFRAME_AREAS)
    rents = {town: usable(rent) for town, (rent, _) in WIREFRAME_AREAS.items()}
    commutes = {
        (station, town): Commute("ok", minutes)
        for town, (_, times) in WIREFRAME_AREAS.items()
        for station, minutes in times.items()
    }
    return towns, rents, commutes


def one_town(
    members: list[MemberInput],
    rent: RentSummary | None,
    minutes: dict[str, Commute],
    town: str = "QUEENSTOWN",
) -> tuple[list[str], dict[str, RentSummary], dict[tuple[str, str], Commute]]:
    rents = {town: rent} if rent is not None else {}
    commutes = {(station, town): commute for station, commute in minutes.items()}
    return [town], rents, commutes


@pytest.mark.parametrize("priority", ["balanced", "fairness", "budget"])
def test_matches_the_wireframe_ranking(priority: Priority) -> None:
    towns, rents, commutes = wireframe_inputs()

    result = rank_towns(SAMPLE_GROUP, towns, rents, commutes, priority)

    ranked = [(a.displayName, True, a.score) for a in result.ranked]
    expected = WIREFRAME_RESULTS[priority]
    assert ranked == [row for row in expected if row[1]]
    assert [a.rank for a in result.ranked] == list(range(1, len(ranked) + 1))
    assert [(a.displayName, a.score) for a in result.excluded] == [
        (name, None) for name, feasible, _ in expected if not feasible
    ]


def test_queenstown_explanation_fields() -> None:
    towns, rents, commutes = wireframe_inputs()

    top = rank_towns(SAMPLE_GROUP, towns, rents, commutes).ranked[0]

    assert top.town == "QUEENSTOWN"
    assert top.wholeFlatRent == 3600
    assert top.rentPerPerson == 1200
    assert top.averageCommute == 22.33
    assert (top.longestCommute, top.shortestCommute, top.commuteGap) == (27, 18, 9)
    assert top.mostBurdenedMemberId == "sam"
    assert [
        (m.memberId, m.commuteMinutes, m.budgetHeadroom, m.commuteHeadroom)
        for m in top.members
    ] == [
        ("alex", 22, 200, 23),
        ("jamie", 18, 100, 27),
        ("sam", 27, 200, 18),
    ]
    assert top.reasons == []


def test_excluded_town_explains_who_and_by_how_much() -> None:
    towns, rents, commutes = wireframe_inputs()

    excluded = rank_towns(SAMPLE_GROUP, towns, rents, commutes).excluded[0]

    assert excluded.town == "JURONG EAST"
    assert [(r.code, r.memberId, r.amount, r.message) for r in excluded.reasons] == [
        ("OVER_COMMUTE", "sam", 10, "Sam's commute exceeds their limit by 10 min")
    ]
    assert excluded.members[2].commuteHeadroom == -10


def test_limits_are_inclusive_and_compared_unrounded() -> None:
    members = [
        MemberInput("a", "A", 1000, 30, "s1"),
        MemberInput("b", "B", Decimal("1000.00"), 40, "s2"),
    ]
    ok = {"s1": Commute("ok", 30), "s2": Commute("ok", 40)}

    exact = rank_towns(members, *one_town(members, usable(2000), ok))
    assert [a.town for a in exact.ranked] == ["QUEENSTOWN"]
    assert [m.budgetHeadroom for m in exact.ranked[0].members] == [0, 0]

    # S$0.005 over per person: shown rounded up, still infeasible.
    over = rank_towns(members, *one_town(members, usable(2000.01), ok))
    assert over.ranked == []
    assert [(r.code, r.amount) for r in over.excluded[0].reasons] == [
        ("OVER_BUDGET", 1),
        ("OVER_BUDGET", 1),
    ]
    assert over.excluded[0].reasons[0].message == "Over A's budget by S$1/month"

    late = {"s1": Commute("ok", 31), "s2": Commute("ok", 40)}
    one_minute = rank_towns(members, *one_town(members, usable(2000), late))
    assert [(r.code, r.memberId, r.amount) for r in one_minute.excluded[0].reasons] == [
        ("OVER_COMMUTE", "a", 1)
    ]


def test_fractional_minutes_are_kept_unrounded() -> None:
    members = [
        MemberInput("a", "A", 1000, 45, "s1"),
        MemberInput("b", "B", 1000, 30, "s2"),
    ]
    fractional = {"s1": Commute("ok", 30.5), "s2": Commute("ok", 18.25)}

    feasible = rank_towns(members, *one_town(members, usable(2000), fractional))
    area = feasible.ranked[0]
    assert [(m.commuteMinutes, m.commuteHeadroom) for m in area.members] == [
        (30.5, 14.5),
        (18.25, 11.75),
    ]
    assert (area.longestCommute, area.shortestCommute, area.commuteGap) == (
        30.5,
        18.25,
        12.25,
    )
    assert area.averageCommute == 24.38
    assert area.mostBurdenedMemberId == "a"

    # Half a minute over is still over: never truncated to the limit.
    late = {"s1": Commute("ok", 30.5), "s2": Commute("ok", 30.5)}
    excluded = rank_towns(members, *one_town(members, usable(2000), late))
    assert excluded.ranked == []
    [reason] = excluded.excluded[0].reasons
    assert (reason.code, reason.memberId, reason.amount) == ("OVER_COMMUTE", "b", 0.5)
    assert reason.message == "B's commute exceeds their limit by 1 min"
    assert excluded.excluded[0].members[1].commuteHeadroom == -0.5


def test_unavailable_route_is_never_zero_minutes() -> None:
    members = SAMPLE_GROUP
    minutes = {
        "nus": Commute("ok", 10),
        "one-north": Commute("unavailable"),
        "raffles": Commute("ok", 10),
    }

    result = rank_towns(members, *one_town(members, usable(3000), minutes))

    area = result.excluded[0]
    assert result.ranked == []
    assert [(r.code, r.memberId) for r in area.reasons] == [
        ("ROUTE_UNAVAILABLE", "jamie")
    ]
    assert area.score is None
    assert area.averageCommute is None and area.commuteGap is None
    assert area.mostBurdenedMemberId is None
    jamie = area.members[1]
    assert (jamie.routeStatus, jamie.commuteMinutes, jamie.commuteHeadroom) == (
        "unavailable",
        None,
        None,
    )


def test_missing_rent_summary_is_excluded_with_null_rent_fields() -> None:
    ok = {m.stationKey: Commute("ok", 20) for m in SAMPLE_GROUP}

    area = rank_towns(SAMPLE_GROUP, *one_town(SAMPLE_GROUP, None, ok)).excluded[0]

    assert [r.code for r in area.reasons] == ["RENT_UNAVAILABLE"]
    assert area.wholeFlatRent is None and area.rentPerPerson is None
    assert area.rentSampleSize is None and area.rentQualityStatus is None
    assert all(m.budgetHeadroom is None for m in area.members)


def test_low_confidence_rent_is_shown_but_cannot_affect_affordability() -> None:
    weak = RentSummary(
        median=6000,
        p25=5000,
        p75=7000,
        medianCi95Low=5000,
        medianCi95High=7200,
        count=12,
        qualityStatus="LOW_CONFIDENCE",
    )
    ok = {m.stationKey: Commute("ok", 20) for m in SAMPLE_GROUP}

    area = rank_towns(SAMPLE_GROUP, *one_town(SAMPLE_GROUP, weak, ok)).excluded[0]

    # Over every budget, yet only the quality reason applies.
    assert [r.code for r in area.reasons] == ["RENT_LOW_CONFIDENCE"]
    assert (area.wholeFlatRent, area.rentPerPerson, area.rentSampleSize) == (
        6000,
        2000,
        12,
    )
    assert area.rentQualityStatus == "LOW_CONFIDENCE"
    assert all(m.budgetHeadroom is None for m in area.members)
    assert area.score is None


def test_exclusion_order_puts_scored_towns_before_unscored() -> None:
    members = [MemberInput("a", "A", 900, 30, "s")]
    towns = ["YISHUN", "BEDOK", "ANG MO KIO", "TAMPINES"]
    rents = {
        "YISHUN": usable(1000),  # over budget, scored
        "BEDOK": usable(950),  # over budget, scored higher
        "TAMPINES": usable(800),  # feasible
    }
    commutes = {(m.stationKey, t): Commute("ok", 20) for m in members for t in towns}

    result = rank_towns(members, towns, rents, commutes)

    assert [a.town for a in result.ranked] == ["TAMPINES"]
    # ANG MO KIO has no rent, so it is unscored and comes last.
    assert [a.town for a in result.excluded] == ["BEDOK", "YISHUN", "ANG MO KIO"]


def test_ties_break_by_display_name_and_earliest_joiner() -> None:
    members = [
        MemberInput("first", "First", 2000, 60, "s1"),
        MemberInput("second", "Second", 2000, 60, "s2"),
    ]
    towns = ["WOODLANDS", "BEDOK"]
    rents = {town: usable(2000) for town in towns}
    commutes = {(s, t): Commute("ok", 30) for s in ("s1", "s2") for t in towns}

    result = rank_towns(members, towns, rents, commutes)

    assert [a.displayName for a in result.ranked] == ["Bedok", "Woodlands"]
    assert result.ranked[0].score == result.ranked[1].score
    assert result.ranked[0].mostBurdenedMemberId == "first"


def test_score_rounds_half_up_and_never_drops_below_zero() -> None:
    member = [MemberInput("a", "A", 5000, 120, "s")]
    # cost = 0.35 * 1000/2000 + 0.35 * 0/90 + 0.3 * 0/90 = 0.175 -> 82.5 -> 83
    half = rank_towns(member, *one_town(member, usable(1000), {"s": Commute("ok", 0)}))
    assert half.ranked[0].score == 83

    costly = rank_towns(
        member, *one_town(member, usable(5000), {"s": Commute("ok", 120)}), "budget"
    )
    assert costly.ranked[0].score == 0


def test_pending_or_missing_routes_are_rejected() -> None:
    member = [MemberInput("a", "A", 1000, 30, "s")]

    with pytest.raises(PendingRoutesError):
        rank_towns(member, *one_town(member, usable(900), {"s": Commute("pending")}))
    with pytest.raises(PendingRoutesError):
        rank_towns(member, *one_town(member, usable(900), {}))


def test_ranking_is_deterministic_and_input_order_independent() -> None:
    towns, rents, commutes = wireframe_inputs()

    first = rank_towns(SAMPLE_GROUP, towns, rents, commutes)
    second = rank_towns(SAMPLE_GROUP, list(reversed(towns)), rents, commutes)

    assert first == second


def test_display_names_keep_hdb_punctuation() -> None:
    assert display_name("KALLANG/WHAMPOA") == "Kallang/Whampoa"
    assert display_name("ANG MO KIO") == "Ang Mo Kio"
    assert display_name("CENTRAL") == "Central"
