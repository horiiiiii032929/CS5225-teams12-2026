"""Turn the deployed #29 journey's JUnit XML into a recorded verdict.

The `Deployed e2e` workflow runs `services/api/tests/e2e` against a deployed
API and calls this to decide and record the outcome for that build:

- FAIL: any test failed or errored.
- INCOMPLETE: nothing failed, but steps were skipped because the deployment
  lacks a dependency (e.g. no published rent until #10). This is readiness
  evidence, never acceptance, so it is never reported as PASS.
- PASS: every selected test ran and passed.

It writes Markdown for the GitHub job summary and a JSON record kept as a
workflow artifact. Standard library only, so it runs before any setup step.
"""

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class Outcome:
    test: str
    status: str  # passed | failed | skipped
    detail: str = ""


@dataclass
class Record:
    revision: str
    api_url: str
    web_asset: str
    verdict: str
    recorded_at: str
    outcomes: list[Outcome] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(o.status == status for o in self.outcomes)


def read_junit(path: Path) -> list[Outcome]:
    outcomes = []
    for case in ET.parse(path).getroot().iter("testcase"):
        name = case.get("name", "?")
        problem = case.find("failure")
        if problem is None:
            problem = case.find("error")
        skipped = case.find("skipped")
        if problem is not None:
            message = problem.get("message") or (problem.text or "").strip()
            outcomes.append(Outcome(name, "failed", message.splitlines()[0][:300]))
        elif skipped is not None:
            # pytest records the skip reason as "path:line: reason".
            reason = skipped.get("message", "").rsplit(": ", 1)[-1]
            outcomes.append(Outcome(name, "skipped", reason))
        else:
            outcomes.append(Outcome(name, "passed"))
    return outcomes


def verdict(outcomes: list[Outcome]) -> str:
    if not outcomes or any(o.status == "failed" for o in outcomes):
        return "FAIL"  # No tests at all is a broken run, not a pass.
    if any(o.status == "skipped" for o in outcomes):
        return "INCOMPLETE"
    return "PASS"


def markdown(record: Record) -> str:
    lines = [
        f"## Deployed e2e: **{record.verdict}**",
        "",
        f"- Revision: `{record.revision}`",
        f"- API: {record.api_url}",
        f"- Web asset served: `{record.web_asset}`",
        f"- Recorded: {record.recorded_at}",
        f"- Passed {record.count('passed')}, failed {record.count('failed')}, "
        f"skipped {record.count('skipped')}",
        "",
        "| Test | Result | Detail |",
        "| --- | --- | --- |",
    ]
    for outcome in record.outcomes:
        detail = outcome.detail.replace("|", "\\|")
        lines.append(f"| `{outcome.test}` | {outcome.status} | {detail} |")
    if record.verdict == "INCOMPLETE":
        lines += [
            "",
            "Skipped steps mean the deployment is missing a dependency. This run "
            "is readiness evidence, not acceptance.",
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("junit", type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--web-asset", default="unknown")
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="exit non-zero on INCOMPLETE as well as FAIL",
    )
    args = parser.parse_args(argv)

    outcomes = read_junit(args.junit) if args.junit.exists() else []
    record = Record(
        revision=args.revision,
        api_url=args.api_url,
        web_asset=args.web_asset,
        verdict=verdict(outcomes),
        recorded_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        outcomes=outcomes,
    )
    args.json_out.write_text(json.dumps(asdict(record), indent=2) + "\n")
    text = markdown(record)
    if args.summary_out:
        with args.summary_out.open("a", encoding="utf-8") as summary:
            summary.write(text)
    print(text)
    if record.verdict == "FAIL":
        return 1
    return 1 if record.verdict == "INCOMPLETE" and args.require_complete else 0


if __name__ == "__main__":
    sys.exit(main())
