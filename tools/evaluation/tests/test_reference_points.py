"""Offline regressions for the rental-to-routing handoff; no upstream calls."""

import contextlib
import csv
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
FEASIBILITY = ROOT / "docs/evaluation/feasibility"
sys.path.insert(0, str(FEASIBILITY))

from onemap.towns import TOWN_REFERENCE_POINTS  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "build_town_points", FEASIBILITY / "scripts/build_town_points.py"
)
assert spec and spec.loader
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ReferencePointTests(unittest.TestCase):
    def test_frontend_map_uses_the_same_verified_reference_coordinates(self):
        source = json.loads(
            (ROOT / "services/api/src/flatsplit_api/towns.json").read_text()
        )
        public = json.loads(
            (
                ROOT / "apps/web/src/features/groups/town-reference-points.json"
            ).read_text()
        )
        self.assertEqual(
            public,
            {
                town: {key: point[key] for key in ("stationName", "lat", "lon")}
                for town, point in source.items()
                if point["routable"]
            },
        )
        self.assertNotIn("TENGAH", public)

    def test_reference_keys_cover_the_reviewed_rental_source(self):
        with (ROOT / "docs/evaluation/e8/rent-audit-2026-q2.csv").open() as source:
            rental_towns = {row["town"] for row in csv.DictReader(source)}
        projection = json.loads((FEASIBILITY / "data/towns.json").read_text())
        self.assertEqual(set(TOWN_REFERENCE_POINTS), rental_towns)
        self.assertEqual(set(projection), rental_towns)
        self.assertFalse(TOWN_REFERENCE_POINTS["TENGAH"]["routable"])
        for town, point in TOWN_REFERENCE_POINTS.items():
            self.assertEqual(projection[town]["stationKey"], point["stationKey"])
            self.assertEqual(projection[town]["lat"], point["lat"])
            self.assertEqual(projection[town]["lon"], point["lon"])

    def test_regeneration_rejects_a_similar_but_wrong_station(self):
        class FakeClient:
            def search(self, query):
                name = (
                    "PASIR RIS EAST MRT STATION"
                    if query.startswith("PASIR RIS ")
                    else query
                )
                return {
                    "results": [
                        {"SEARCHVAL": name, "LATITUDE": "1.3", "LONGITUDE": "103.8"}
                    ]
                }

        output = io.StringIO()
        with (
            patch.object(builder, "OneMapClient", return_value=FakeClient()),
            patch.object(builder, "load_token", return_value="test-only"),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(builder.main(), 1)
        self.assertEqual(output.getvalue(), "")

    def test_regeneration_preserves_the_explicit_unavailable_town(self):
        class FakeClient:
            def search(self, query):
                return {
                    "results": [
                        {"SEARCHVAL": query, "LATITUDE": "1.3", "LONGITUDE": "103.8"}
                    ]
                }

        output = io.StringIO()
        with (
            patch.object(builder, "OneMapClient", return_value=FakeClient()),
            patch.object(builder, "load_token", return_value="test-only"),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(builder.main(), 0)
        table = json.loads(output.getvalue())
        self.assertEqual(set(table), set(TOWN_REFERENCE_POINTS))
        self.assertEqual(table["TENGAH"], TOWN_REFERENCE_POINTS["TENGAH"])


if __name__ == "__main__":
    unittest.main()
