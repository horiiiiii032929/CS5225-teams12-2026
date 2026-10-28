"""Verdicts and records for the deployed #29 journey (tools/e2e/summarize.py)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from summarize import main, read_junit, verdict  # noqa: E402

# Shapes pytest's --junitxml writes for a pass, a skip and a failure.
PASS = '<testcase classname="e2e" name="test_group_journey[2]" time="1.0"/>'
SKIP = (
    '<testcase classname="e2e" name="test_search_journey[2]" time="1.0">'
    '<skipped type="pytest.skip" message="tests/e2e/test_group_journey.py:184: '
    'Deployed API has no published rent snapshot until #10."/></testcase>'
)
FAIL = (
    '<testcase classname="e2e" name="test_search_journey[5]" time="1.0">'
    '<failure message="AssertionError: assert 503 == 201">trace</failure></testcase>'
)


def junit(*cases: str) -> str:
    body = "".join(cases)
    return f'<testsuites><testsuite name="pytest">{body}</testsuite></testsuites>'


class SummarizeTest(unittest.TestCase):
    def run_main(self, xml: str | None, *extra: str) -> tuple[int, dict[str, Any], str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "e2e.xml"
            if xml is not None:
                report.write_text(xml)
            out, summary = root / "record.json", root / "summary.md"
            code = main(
                [
                    str(report),
                    "--revision",
                    "b4a4434",
                    "--api-url",
                    "https://example.test/api",
                    "--web-asset",
                    "index-abc.js",
                    "--json-out",
                    str(out),
                    "--summary-out",
                    str(summary),
                    *extra,
                ]
            )
            return code, json.loads(out.read_text()), summary.read_text()

    def test_all_passing_is_pass(self) -> None:
        code, record, summary = self.run_main(junit(PASS, PASS))
        self.assertEqual((code, record["verdict"]), (0, "PASS"))
        self.assertIn("Deployed e2e: **PASS**", summary)
        self.assertEqual(record["revision"], "b4a4434")
        self.assertEqual(record["web_asset"], "index-abc.js")

    def test_skips_are_incomplete_never_pass(self) -> None:
        code, record, summary = self.run_main(junit(PASS, SKIP))
        self.assertEqual((code, record["verdict"]), (0, "INCOMPLETE"))
        skipped = [o for o in record["outcomes"] if o["status"] == "skipped"]
        reason = "Deployed API has no published rent snapshot until #10."
        self.assertEqual(skipped[0]["detail"], reason)
        self.assertIn("not acceptance", summary)

    def test_require_complete_turns_incomplete_into_failure(self) -> None:
        code, record, _ = self.run_main(junit(PASS, SKIP), "--require-complete")
        self.assertEqual((code, record["verdict"]), (1, "INCOMPLETE"))

    def test_any_failure_fails_even_with_skips(self) -> None:
        code, record, summary = self.run_main(junit(PASS, SKIP, FAIL))
        self.assertEqual((code, record["verdict"]), (1, "FAIL"))
        self.assertIn("assert 503 == 201", summary)

    def test_missing_or_empty_report_is_a_failed_run(self) -> None:
        for xml in (None, junit()):
            code, record, _ = self.run_main(xml)
            self.assertEqual((code, record["verdict"]), (1, "FAIL"))

    def test_errors_count_as_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "e2e.xml"
            path.write_text(
                junit(
                    '<testcase name="test_x"><error message="fixture boom"/></testcase>'
                )
            )
            outcomes = read_junit(path)
        self.assertEqual(verdict(outcomes), "FAIL")
        self.assertEqual(outcomes[0].detail, "fixture boom")

    def test_table_cells_escape_pipes(self) -> None:
        failure = '<testcase name="u"><failure message="a | b"/></testcase>'
        _, _, summary = self.run_main(junit(failure))
        self.assertIn("a \\| b", summary)


if __name__ == "__main__":
    unittest.main()
