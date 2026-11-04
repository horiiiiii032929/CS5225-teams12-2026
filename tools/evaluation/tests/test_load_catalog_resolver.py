"""#30 catalog resolver: pinned selections and the reviewed destination list."""

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools/load" / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


resolver = load_module("load_catalog_resolver", "resolve_catalog.py")
generator = load_module("load_generator_for_resolver", "generate.py")
REVIEWED = json.loads((ROOT / "tools/load/destinations.json").read_text())
PINNED = {
    "alias": "mapletreeBC",
    "label": "MAPLETREE BUSINESS CITY",
    "address": "10 PASIR PANJANG ROAD MAPLETREE BUSINESS CITY SINGAPORE 117438",
    "stationKey": "LABRADOR_PARK",
}


def place(
    pid, address=PINNED["address"], station="LABRADOR_PARK", label=PINNED["label"]
):
    return {
        "placeId": pid,
        "label": label,
        "address": address,
        "station": {"stationKey": station, "lat": 1.27, "lng": 103.80},
    }


class SelectTests(unittest.TestCase):
    def test_selects_the_pinned_candidate_among_same_label_results(self):
        other = place(
            "pl_other", address="20 PASIR PANJANG ROAD MAPLETREE BUSINESS CITY"
        )
        self.assertEqual(
            resolver.select(PINNED, [other, place("pl_pinned")])["placeId"], "pl_pinned"
        )

    def test_refuses_a_changed_or_ambiguous_selection(self):
        cases = {
            "missing": [],
            "station changed": [place("a", station="HAW_PAR_VILLA")],
            "label changed": [place("a", label="MAPLETREE BUSINESS CITY II")],
            "address changed": [place("a", address="30 PASIR PANJANG ROAD")],
            "ambiguous": [place("a"), place("b")],
        }
        for name, places in cases.items():
            with self.subTest(name), self.assertRaises(resolver.SelectionError):
                resolver.select(PINNED, places)


class ReviewedListTests(unittest.TestCase):
    def test_reviewed_list_has_thirty_distinct_pinned_destinations(self):
        destinations = REVIEWED["destinations"]
        self.assertEqual(len(destinations), 30)
        self.assertEqual(len({d["alias"] for d in destinations}), 30)
        self.assertEqual(len({d["receipt"] for d in destinations}), 30)
        for d in destinations:
            with self.subTest(d["alias"]):
                self.assertTrue(d["label"] and d["address"] and d["stationKey"])
                self.assertIn(d["weight"], range(1, 6))
        self.assertIn("not measured", REVIEWED["weight_basis"])

    def test_resolved_catalog_is_accepted_by_the_generator(self):
        def lookup(query):
            d = next(d for d in REVIEWED["destinations"] if d["query"] == query)
            return [
                {
                    "placeId": f"pl_{d['alias']}",
                    "label": d["label"],
                    "address": d["address"],
                    "station": {
                        "stationKey": d["stationKey"],
                        "lat": 1.3,
                        "lng": 103.8,
                    },
                }
            ]

        catalog = resolver.build_catalog(
            REVIEWED, lookup, target="eval", reviewer="test", revision="test", pause=0
        )
        generator.validate_catalog(catalog)
        self.assertEqual(
            catalog["destinations"][0]["place_ids"], {"eval": "pl_nusKentRidge"}
        )
        plan = generator.build_plan("W1", catalog=catalog)
        self.assertEqual(len(plan["arrivals"]), 1200)


if __name__ == "__main__":
    unittest.main()
