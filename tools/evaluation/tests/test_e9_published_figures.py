"""Offline check that E9's chapter quotes the evidence run it cites.

Every figure in `docs/evaluation/e9/cost-model.md` is written by hand, while the
numbers come from `model/cost_model.py`. Three stale figures survived the
5 November correction because nothing tied the prose back to its own evidence.
This test does that tying for the two machine-readable tables: the comparison
table and the sensitivity table. No upstream calls, no model re-run.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
E9 = ROOT / "docs/evaluation/e9"
CHAPTER = E9 / "cost-model.md"
EVIDENCE = E9 / "evidence"


def chapter_text() -> str:
    return CHAPTER.read_text(encoding="utf-8")


def cited_run_stem(text: str) -> str:
    """The evidence run the comparison section says it was generated from."""
    match = re.search(
        r"raw output in `evidence/(cost_model_\d{8}T\d{6}Z)\.\{md,json,csv\}`", text
    )
    assert match, "the comparison section must cite its evidence run"
    return match.group(1)


def table_rows(text: str, header_fragment: str) -> dict[str, list[str]]:
    """Rows of the first Markdown table whose header contains the fragment."""
    rows: dict[str, list[str]] = {}
    seen_header = False
    for line in text.splitlines():
        stripped = line.strip()
        if not seen_header:
            seen_header = header_fragment in stripped and stripped.startswith("|")
            continue
        if not stripped.startswith("|"):
            break
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):
            continue
        rows[cells[0]] = cells[1:]
    assert rows, f"no table found for {header_fragment!r}"
    return rows


def money(cell: str) -> float:
    return round(float(cell.replace("**", "").replace(",", "").strip()), 2)


class PublishedFigureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = chapter_text()
        cls.stem = cited_run_stem(cls.text)
        cls.data = json.loads((EVIDENCE / f"{cls.stem}.json").read_text("utf-8"))

    def test_the_cited_run_exists_and_is_the_newest_one(self):
        for suffix in ("md", "json", "csv"):
            self.assertTrue(
                (EVIDENCE / f"{self.stem}.{suffix}").is_file(),
                f"{self.stem}.{suffix} is cited but missing",
            )
        newest = max(p.stem for p in EVIDENCE.glob("cost_model_*.json"))
        self.assertEqual(
            self.stem, newest, "the chapter cites an older run than the newest kept"
        )

    def test_comparison_table_matches_the_cited_run(self):
        rows = table_rows(self.text, "Quiet US$/mo")
        scenarios = [
            self.data["scenarios"][name] for name in ("quiet", "typical", "bursty")
        ]

        def check(label: str, values: list[float], per_1000: float | None) -> None:
            cells = rows[label]
            for column, (cell, expected) in enumerate(zip(cells, values)):
                self.assertEqual(
                    money(cell), round(expected, 2), f"{label!r} column {column}"
                )
            if per_1000 is not None:
                self.assertEqual(money(cells[3]), round(per_1000, 2), f"{label!r} /1k")

        serverless = [s["aws_serverless"] for s in scenarios]
        check(
            "A. AWS serverless — **payable**",
            [s["payable_usd"] for s in serverless],
            serverless[1]["usd_per_1000_searches"],
        )
        check(
            "A. AWS serverless — list price, free tier removed",
            [s["list_price_usd"] for s in serverless],
            serverless[1]["list_price_usd"],
        )
        vm = [s["aws_always_on_vm"] for s in scenarios]
        check(
            "B. AWS always-on VM",
            [s["payable_usd"] for s in vm],
            vm[1]["usd_per_1000_searches"],
        )
        onprem = [s["on_premise"] for s in scenarios]
        check(
            "C. On-premise — likely effort",
            [s["payable_usd"] for s in onprem],
            onprem[1]["usd_per_1000_searches"],
        )
        uni = [s["university_vm"] for s in scenarios]
        check(
            "D. University VM — likely effort",
            [s["payable_usd"] for s in uni],
            uni[1]["usd_per_1000_searches"],
        )

        for label, lines in (
            ("C. On-premise — effort band", onprem),
            ("D. University VM — effort band", uni),
        ):
            for column, scenario in enumerate(lines):
                low, high = rows[label][column].split("–")
                self.assertEqual(
                    (money(low), money(high)),
                    (
                        round(scenario["payable_usd_low_effort"], 2),
                        round(scenario["payable_usd_high_effort"], 2),
                    ),
                    f"{label!r} column {column}",
                )

    def test_sensitivity_table_matches_the_cited_run(self):
        rows = table_rows(self.text, "Demand (typical scaled)")
        by_scale = {row["scale"]: row for row in self.data["sensitivity"]}
        labels = {
            "idle — nobody uses it for a month": 0.0,
            "×0.1": 0.1,
            "×1 (1,000 searches)": 1.0,
            "×10": 10.0,
            "×100 (100,000 searches)": 100.0,
        }
        for label, scale in labels.items():
            expected = by_scale[scale]
            payable, list_price, onprem, uni, nodes = rows[label]
            self.assertEqual(money(payable), round(expected["aws_payable_usd"], 2), label)
            self.assertEqual(money(list_price), round(expected["aws_list_usd"], 2), label)
            self.assertEqual(money(onprem), round(expected["onprem_usd"], 2), label)
            self.assertEqual(money(uni), round(expected["university_vm_usd"], 2), label)
            self.assertEqual(int(nodes), expected["nodes"], label)


if __name__ == "__main__":
    unittest.main()
