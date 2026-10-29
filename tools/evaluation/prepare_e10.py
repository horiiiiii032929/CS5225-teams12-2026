#!/usr/bin/env python3
"""Prepare/check offline E10 study cards using the repository's real ranker.

Synthetic stimuli only; never reads participant records, credentials or services.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "services/api/src"
sys.path.insert(0, str(SOURCE))
from flatsplit_api import ranking  # noqa: E402

KIT = ROOT / "docs/evaluation/e10"


def table(rows: list[list[str]]) -> str:
    widths = [max(3, *(len(row[i]) for row in rows)) for i in range(len(rows[0]))]

    def line(row: list[str]) -> str:
        return (
            "| "
            + " | ".join(s.ljust(w) for s, w in zip(row, widths, strict=True))
            + " |"
        )

    return "\n".join(
        [line(rows[0]), line(["-" * w for w in widths]), *(line(r) for r in rows[1:])]
    )


def materials() -> dict[Path, str]:
    fixture = KIT / "data/study-fixtures.json"
    data = json.loads(fixture.read_text())
    if data.get("synthetic") is not True:
        raise ValueError("E10 cards must remain labelled synthetic")
    output: dict[Path, str] = {}
    ranker_hash = hashlib.sha256(Path(ranking.__file__).read_bytes()).hexdigest()
    key = [
        "# Moderator-only E10 answer key",
        "",
        "Synthetic study stimuli; no participant observations or real-data acceptance.",
        "Do not show this file, the fixture JSON or the other condition "
        "to participants.",
        "",
        f"- Fixture SHA-256: `{hashlib.sha256(fixture.read_bytes()).hexdigest()}`",
        f"- Ranker SHA-256: `{ranker_hash}`",
        "- Reproduce: `uv run --package flatsplit-api python "
        "tools/evaluation/prepare_e10.py --check`.",
        "",
    ]
    for scenario in data["scenarios"]:
        sid = scenario["id"]
        names = scenario["names"]
        members = [
            ranking.MemberInput(str(i), name, 1800, 60, f"S{i}")
            for i, name in enumerate(names)
        ]
        towns = scenario["towns"]
        rents = {
            t["town"]: ranking.RentSummary(
                median=t["rentPerPerson"] * 3,
                p25=t["rentPerPerson"] * 3,
                p75=t["rentPerPerson"] * 3,
                medianCi95Low=t["rentPerPerson"] * 3,
                medianCi95High=t["rentPerPerson"] * 3,
                count=100,
                qualityStatus="USABLE",
            )
            for t in towns
        }
        commutes = {
            (f"S{i}", t["town"]): ranking.Commute("ok", minutes)
            for t in towns
            for i, minutes in enumerate(t["minutes"])
        }
        results = {
            priority: ranking.rank_towns(
                members, list(rents), rents, commutes, priority
            )
            for priority in ("balanced", "fairness")
        }
        if any(len(r.ranked) != 3 or r.excluded for r in results.values()):
            raise ValueError(f"Scenario {sid} needs three feasible towns in both views")
        balanced = {r.town: r for r in results["balanced"].ranked}
        fair = {r.town: r for r in results["fairness"].ranked}
        if (
            results["balanced"].ranked[0].town != "AMBER"
            or results["fairness"].ranked[0].town != "BIRCH"
        ):
            raise ValueError(
                f"Scenario {sid} no longer demonstrates the intended rank change"
            )
        common = [
            [
                "Town",
                "Rent/person/month",
                "Average commute",
                "Balanced rank",
                "Fairer commutes rank",
            ],
            *[
                [
                    t["town"].title(),
                    f"S${t['rentPerPerson']:,}",
                    f"{balanced[t['town']].averageCommute:g} min",
                    str(balanced[t["town"]].rank),
                    str(fair[t["town"]].rank),
                ]
                for t in towns
            ],
        ]
        for condition in ("A", "B"):
            rows = [row.copy() for row in common]
            if condition == "B":
                rows[0] += [f"{name}'s commute" for name in names] + ["Commute gap"]
                for row, t in zip(rows[1:], towns, strict=True):
                    row += [f"{n:g} min" for n in t["minutes"]]
                    row += [f"{balanced[t['town']].commuteGap:g} min"]
            lines = [
                f"# Scenario {sid} — card {condition}",
                "",
                "**SYNTHETIC STUDY CARD.** Towns, rent and commute figures "
                "are fictional.",
                "This is a static comparison exercise, not the live FlatSplit "
                "app or a map of real towns.",
                "",
                f"Your flatmates are {', '.join(names)}. Each has a monthly "
                "budget of S$1,800 and a 60-minute commute limit.",
                "All three towns meet those limits. Rent is an equal split "
                "of a whole flat, excluding bills.",
                "",
                "The same group switches from Balanced to Fairer commutes. "
                "The columns show the two rankings; 1 is first.",
                "Use only the information on this card. It is okay to say "
                "that the information is insufficient.",
                "",
                table(rows),
                "",
                "1. Which town would you choose for this group, and why?",
                "2. Who has the longest commute in Amber? Can you tell from "
                "this card? Explain.",
                "3. Which town moves to first when the priority changes? "
                "What information supports your explanation?",
                "4. What, if anything, would you want to know before "
                "agreeing with your flatmates?",
                "",
                "After answering, tell the moderator you are finished. "
                "Do not open the other cards or answer key.",
                "",
            ]
            output[KIT / f"cards/{sid.lower()}-{condition.lower()}.md"] = "\n".join(
                lines
            )
        amber = balanced["AMBER"]
        birch = balanced["BIRCH"]
        person = members[int(amber.mostBurdenedMemberId)].name
        orders = {
            p: ", ".join(r.displayName for r in result.ranked)
            for p, result in results.items()
        }
        key += [
            f"## Scenario {sid}",
            "",
            f"- Balanced order: {orders['balanced']}.",
            f"- Fairer commutes order: {orders['fairness']}.",
            f"- Amber's longest commute: **{person}, {amber.longestCommute:g} min**; "
            f"gap {amber.commuteGap:g} min.",
            f"- Birch: longest {birch.longestCommute:g} min; "
            f"gap {birch.commuteGap:g} min; S$400/person/month more than Amber.",
            "- Card A: a member cannot be identified from the average alone. "
            "Record `not_observable` for member-identification accuracy; "
            "separately record whether the participant recognises the missing "
            "information. A guess is not evidence of understanding.",
            "- Card B: naming the member above and identifying the smaller "
            "Birch gap supports fairness understanding. Birch becomes first "
            "because the priority weights commute gap more heavily; every "
            "town remains feasible. Accept equivalent plain-language "
            "explanations, not only numeric recall.",
            "- A preference for Amber, Birch or Cedar is not right/wrong. "
            "Code whether the explanation uses the available rent/commute "
            "trade-off; do not reward agreement with the ranking.",
            "",
        ]
    output[KIT / "moderator-answer-key.md"] = "\n".join(key)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Check committed materials without writing"
    )
    args = parser.parse_args()
    for path, content in materials().items():
        if args.check:
            if not path.exists() or path.read_text() != content:
                raise SystemExit(f"Study material differs: {path.relative_to(ROOT)}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    print("E10 synthetic cards and answer key match the fixture and current ranker.")


if __name__ == "__main__":
    main()
