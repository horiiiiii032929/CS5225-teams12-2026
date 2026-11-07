"""Offline regressions for #19's coverage evaluator; no upstream calls.

Covers the failure cases Mani raised as [P2] on #97: a destination that does
not resolve, or a snapping comparison that fails, used to be printed and then
dropped, leaving an artifact whose `totalPairs` had silently shrunk while the
script still exited 0.
"""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
FEASIBILITY = ROOT / "docs/evaluation/feasibility"
sys.path.insert(0, str(FEASIBILITY))

from onemap.errors import NoRouteFound, UpstreamError  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "measure_route_coverage", FEASIBILITY / "scripts/measure_route_coverage.py"
)
assert spec and spec.loader
coverage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coverage)


def catalog_doc(aliases):
    return {
        "version": 1,
        "reviewed": {"reviewer": "test", "revision": "0" * 40},
        "weight_basis": "test fixture",
        "destinations": [
            {
                "alias": a,
                "group": "test",
                "weight": 1,
                "query": a,
                "label": a.upper(),
                "address": f"{a} ADDRESS",
                "stationKey": f"STN_{a.upper()}",
                "receipt": f"synthetic://{a}",
            }
            for a in aliases
        ],
    }


class FakeClient:
    """Only the four surfaces the evaluator touches."""

    token_hours_left = 70.0

    def __init__(self, *, no_results=(), no_station=(), search_raises=(),
                 route_raises=()):
        self.no_results = set(no_results)
        self.no_station = set(no_station)
        self.search_raises = set(search_raises)
        self.route_raises = dict(route_raises)
        self.stats = {"calls": 0, "retries": 0, "rate_limited": 0, "errors": 0}
        self._n = 0

    def search(self, query):
        self.stats["calls"] += 1
        alias = query.split()[0]
        if alias in self.search_raises:
            raise UpstreamError("upstream down", status=503)
        if alias in self.no_results:
            return {"results": []}
        self._n += 1
        return {"results": [{"LATITUDE": f"1.3{self._n}", "LONGITUDE": "103.8",
                             "SEARCHVAL": alias.upper()}]}

    def nearest_mrt(self, lat, lon, radius_m=2000):
        self.stats["calls"] += 1
        key = f"{lat},{lon}"
        if key in self.no_station:
            return [], None
        return ([{"stationKey": self.station_for(key), "codes": "XX1",
                  "lat": float(lat) + 0.001, "lon": 103.8}], None)

    # the fixture pins one station per geocoded coordinate
    def station_for(self, key):
        return f"STN_{key.split(',')[0].replace('.', '_')}"

    def route_pt(self, origin, dest):
        self.stats["calls"] += 1
        if dest in self.route_raises:
            raise self.route_raises[dest]
        return {"minutes": 30.0, "transfers": 1, "walkMetres": 200}


def run(client, aliases, extra_args=()):
    """Run main() against a temp catalog and temp evidence dir."""
    with tempfile.TemporaryDirectory() as tmp:
        cat = Path(tmp) / "destinations.json"
        cat.write_text(json.dumps(catalog_doc(aliases)), encoding="utf-8")
        out = Path(tmp) / "evidence"
        argv = ["measure_route_coverage.py", "--catalog", str(cat),
                "--out", str(out), "--towns", "2", "--dests", str(len(aliases)),
                "--snap-towns", "1", *extra_args]
        buf = io.StringIO()
        with patch.object(coverage, "OneMapClient", lambda token: client), \
             patch.object(coverage, "load_token", lambda arg: "token"), \
             patch.object(sys, "argv", argv), \
             contextlib.redirect_stdout(buf):
            code = coverage.main()
        artifacts = sorted(out.glob("coverage_*.json"))
        assert len(artifacts) == 1, artifacts
        return code, json.loads(artifacts[0].read_text()), buf.getvalue()


class CompletenessTests(unittest.TestCase):
    def test_a_complete_run_reports_complete_and_exits_zero(self):
        code, report, _ = run(FakeClient(), ["alpha", "beta"])
        c = report["completeness"]
        self.assertEqual(code, 0)
        self.assertTrue(c["complete"])
        self.assertEqual(c["plannedDestinations"], 2)
        self.assertEqual(c["resolvedDestinations"], 2)
        self.assertEqual(c["plannedPairs"], c["completedPairs"], 4)
        self.assertEqual(c["plannedSnapComparisons"], c["completedSnapComparisons"])
        self.assertEqual(c["destinationFailures"], [])
        self.assertEqual(c["snapComparisonFailures"], [])

    def test_a_destination_that_does_not_geocode_is_recorded_not_dropped(self):
        code, report, stdout = run(
            FakeClient(no_results=["beta"]), ["alpha", "beta"]
        )
        c = report["completeness"]
        self.assertEqual(code, 1, "an incomplete audit must not exit 0")
        self.assertFalse(c["complete"])
        self.assertEqual(c["plannedDestinations"], 2)
        self.assertEqual(c["resolvedDestinations"], 1)
        self.assertEqual(c["plannedPairs"], 4)
        self.assertEqual(c["completedPairs"], 2)
        self.assertEqual(
            [(f["destination"], f["stage"], f["errorType"])
             for f in c["destinationFailures"]],
            [("beta", "geocode", "NoResults")],
        )
        self.assertIn("不完整", stdout)

    def test_a_destination_with_no_station_in_radius_is_recorded(self):
        client = FakeClient()
        # the first geocode lands on 1.31; refuse a station there
        client.no_station = {"1.31,103.8"}
        code, report, _ = run(client, ["alpha", "beta"])
        c = report["completeness"]
        self.assertEqual(code, 1)
        self.assertFalse(c["complete"])
        self.assertEqual(
            [(f["destination"], f["stage"], f["errorType"])
             for f in c["destinationFailures"]],
            [("alpha", "nearest-station", "NoStationInRadius")],
        )

    def test_a_transient_search_failure_is_recorded_rather_than_raised(self):
        code, report, _ = run(
            FakeClient(search_raises=["alpha"]), ["alpha", "beta"]
        )
        c = report["completeness"]
        self.assertEqual(code, 1)
        self.assertEqual(
            [(f["destination"], f["stage"], f["errorType"])
             for f in c["destinationFailures"]],
            [("alpha", "geocode", "UpstreamError")],
        )

    def test_a_failed_snapping_comparison_is_retained_in_the_artifact(self):
        # fail only the exact-address leg of the second destination
        client = FakeClient(route_raises={
            "1.32,103.8": NoRouteFound("No route found", status=404)
        })
        code, report, _ = run(client, ["alpha", "beta"])
        c = report["completeness"]
        self.assertEqual(code, 1)
        self.assertFalse(c["complete"])
        self.assertEqual(c["plannedDestinations"], c["resolvedDestinations"], 2)
        self.assertEqual(c["completedPairs"], c["plannedPairs"], 4)
        self.assertEqual(c["plannedSnapComparisons"], 2)
        self.assertEqual(c["completedSnapComparisons"], 1)
        self.assertEqual(
            [(f["destination"], f["errorType"])
             for f in c["snapComparisonFailures"]],
            [("BETA", "NoRouteFound")],
        )

    def test_recorded_route_outcomes_do_not_make_a_run_incomplete(self):
        # an unavailable pair is an observation, not missing work
        client = FakeClient()
        client.route_raises = {}
        code, report, _ = run(client, ["alpha"])
        self.assertEqual(code, 0)
        self.assertTrue(report["completeness"]["complete"])
        self.assertEqual(report["coverage"]["errors"], 0)

    def test_the_published_november_run_is_retrospectively_complete(self):
        """The 5 Nov artifact predates these fields; verify it from its own counts."""
        path = (FEASIBILITY / "evidence/coverage_20261105T093324Z.json")
        report = json.loads(path.read_text())
        towns, dests = len(report["towns"]), len(report["destinations"])
        self.assertEqual(report["coverage"]["totalPairs"], towns * dests)
        self.assertEqual(
            len(report["snapError"]["rows"]), len(report["snapProbeTowns"]) * dests
        )
        self.assertEqual(report["coverage"]["errors"], 0)
        self.assertEqual(report["stationPinMismatches"], [])


if __name__ == "__main__":
    unittest.main()
