"""Offline load-plan and privacy/evidence regressions; no service or provider calls."""

import contextlib
import copy
import importlib.util
import io
import json
import math
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools/load"))


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools/load" / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generator = load_module("load_generator", "generate.py")
summary = load_module("load_summary", "summarize.py")


def synthetic_catalog():
    # Explicit test-only local IDs, not reviewed destination candidates.
    return {
        "version": 1,
        "kind": "synthetic-local",
        "review": {
            "reviewer": "test-reviewer",
            "revision": "test-revision",
            "weight_basis": "test-only",
        },
        "destinations": [
            {
                "alias": "localA",
                "weight": 1,
                "selection_receipt": "synthetic://localA",
                "station": {"stationKey": "TEST_STATION", "lat": 1.3, "lng": 103.8},
                "place_ids": {"local": "test-place-A"},
            }
        ],
    }


def reviewed_catalog():
    catalog = synthetic_catalog()
    catalog["kind"] = "reviewed-public"
    template = catalog["destinations"][0]
    catalog["destinations"] = []
    for index in range(30):
        destination = copy.deepcopy(template)
        destination["alias"] = f"destination{index}"
        destination["selection_receipt"] = f"https://example.org/destination/{index}"
        catalog["destinations"].append(destination)
    return catalog


def evidence(plan):
    manifest = {
        "kind": "manifest",
        "run_id": "testRun",
        "target": "local",
        "mode": "local",
        "source_revision": "test-revision",
        "start_utc": "2026-10-28T00:00:00.000Z",
        **{
            key: plan[key]
            for key in (
                "workload",
                "seed",
                "trace_sha256",
                "catalog_sha256",
                "standard",
                "vus",
                "duration_ms",
            )
        },
    }
    samples = []
    for arrival in plan["arrivals"]:
        start = arrival["at_ms"] + 3
        duration = arrival["ordinal"] + 1
        samples.append(
            {
                "kind": "sample",
                "run_id": "testRun",
                "target": "local",
                "phase": "measured",
                "cohort": "warm-complete" if arrival["op"] == "read" else "mixed",
                "ordinal": arrival["ordinal"],
                "op": arrival["op"],
                "planned_ms": arrival["at_ms"],
                "start_ms": start,
                "end_ms": start + duration,
                "duration_ms": duration,
                "status": 200,
                "outcome": "success",
                "search_status": "complete" if arrival["op"] == "read" else "unknown",
                "worker": arrival["ordinal"] % plan["vus"],
            }
        )
    return [manifest, *samples]


class PlanTests(unittest.TestCase):
    def test_pinned_standard_arrival_counts_and_rate_boundaries(self):
        w1 = generator.build_plan("W1")
        self.assertTrue(w1["standard"])
        self.assertEqual(len(w1["arrivals"]), 1200)
        self.assertEqual(Counter(row["op"] for row in w1["arrivals"]), {"read": 1200})
        self.assertEqual(w1["arrivals"][0]["at_ms"], 250)
        self.assertEqual(w1["arrivals"][-1]["at_ms"], 599750)
        w2 = generator.build_plan("W2")
        self.assertEqual(len(w2["arrivals"]), 16530)
        self.assertEqual(
            Counter(row["op"] for row in w2["arrivals"]),
            {"create": 1653, "join": 3306, "save": 6612, "read": 4959},
        )
        self.assertEqual(
            Counter(row["phase"] for row in w2["arrivals"]),
            {"ramp": 1530, "hold": 15000},
        )
        self.assertLess(w2["arrivals"][1529]["at_ms"], 60000)
        self.assertEqual(w2["arrivals"][1530]["at_ms"], 60010)
        self.assertEqual(w2["arrivals"][-1]["at_ms"], 359990)
        for ordinal in (0, 100, 1529):
            seconds = w2["arrivals"][ordinal]["at_ms"] / 1000
            self.assertAlmostEqual(
                seconds + 49 * seconds**2 / 120, ordinal + 0.5, places=7
            )
        for start in range(0, len(w2["arrivals"]), 10):
            self.assertEqual(
                Counter(row["op"] for row in w2["arrivals"][start : start + 10]),
                {"create": 1, "join": 2, "save": 4, "read": 3},
            )

    def test_seed_replay_and_catalog_do_not_change_operation_schedule(self):
        plain = generator.build_plan("W2", scale=0.01)
        self.assertEqual(plain, generator.build_plan("W2", scale=0.01))
        catalogued = generator.build_plan("W2", scale=0.01, catalog=synthetic_catalog())
        self.assertEqual(
            [
                {key: row[key] for key in ("ordinal", "at_ms", "phase", "op")}
                for row in plain["arrivals"]
            ],
            [
                {key: row[key] for key in ("ordinal", "at_ms", "phase", "op")}
                for row in catalogued["arrivals"]
            ],
        )
        self.assertTrue(
            all(row["destination"] == "localA" for row in catalogued["arrivals"])
        )
        self.assertTrue(all(row["destination"] is None for row in plain["arrivals"]))
        self.assertNotEqual(plain["trace_sha256"], catalogued["trace_sha256"])
        other = generator.build_plan("W2", seed=522531, scale=0.01)
        self.assertNotEqual(
            [row["op"] for row in plain["arrivals"]],
            [row["op"] for row in other["arrivals"]],
        )
        self.assertEqual(
            [row["at_ms"] for row in plain["arrivals"]],
            [row["at_ms"] for row in other["arrivals"]],
        )

    def test_weighted_destination_selection_replays_without_uniformizing_weights(self):
        catalog = synthetic_catalog()
        second = copy.deepcopy(catalog["destinations"][0])
        second.update(alias="localB", selection_receipt="synthetic://localB", weight=1)
        catalog["destinations"][0]["weight"] = 9
        catalog["destinations"].append(second)
        plan = generator.build_plan("W1", catalog=catalog)
        counts = Counter(row["destination"] for row in plan["arrivals"])
        self.assertGreater(counts["localA"], counts["localB"] * 3)
        self.assertGreater(counts["localB"], 0)
        self.assertEqual(
            plan["trace_sha256"],
            generator.build_plan("W1", catalog=catalog)["trace_sha256"],
        )

    def test_scaled_smoke_preserves_rates_and_whole_operation_blocks(self):
        w1 = generator.build_plan("W1", scale=0.01)
        w2 = generator.build_plan("W2", scale=0.01)
        self.assertFalse(w1["standard"])
        self.assertFalse(w2["standard"])
        self.assertEqual((len(w1["arrivals"]), w1["duration_ms"]), (12, 6000))
        self.assertEqual((len(w2["arrivals"]), w2["duration_ms"]), (160, 3600))
        self.assertEqual(w1["arrivals"][0]["at_ms"], 250)
        self.assertEqual(
            Counter(row["op"] for row in w2["arrivals"]),
            {"create": 16, "join": 32, "save": 64, "read": 48},
        )
        self.assertTrue(
            all(
                left["at_ms"] < right["at_ms"]
                for left, right in zip(w2["arrivals"], w2["arrivals"][1:], strict=False)
            )
        )
        self.assertLess(w2["arrivals"][-1]["at_ms"], w2["duration_ms"])

    def test_invalid_numeric_inputs_and_empty_smoke_are_rejected(self):
        for scale in (False, 0, -1, math.nan, math.inf, 1e-30):
            with (
                self.subTest(scale=scale),
                self.assertRaises(generator.ValidationError),
            ):
                generator.build_plan("W2", scale=scale)
        for values in ({"seed": True}, {"seed": 2**53}, {"vus": True}, {"vus": 0}):
            with (
                self.subTest(values=values),
                self.assertRaises(generator.ValidationError),
            ):
                generator.build_plan("W1", **values)

    def test_numeric_hash_contract_preserves_float_precision_types_and_zero(self):
        self.assertEqual(
            generator.digest({"value": 1}), generator.digest({"value": 1.0})
        )
        self.assertEqual(
            generator.digest({"a": 0.0, "b": [2, True]}),
            generator.digest({"b": [2.0, True], "a": -0.0}),
        )
        self.assertNotEqual(
            generator.digest({"value": 1}), generator.digest({"value": "1"})
        )
        self.assertNotEqual(
            generator.digest({"value": 1}), generator.digest({"value": True})
        )
        self.assertEqual(
            generator.hash_projection([1, -0.0, True, None]),
            ["3ff0000000000000", "0000000000000000", True, None],
        )
        self.assertEqual(generator.digest(10**21), generator.digest(1e21))
        self.assertNotEqual(
            generator.digest(1.30000000001), generator.digest(1.30000000002)
        )
        self.assertNotEqual(generator.digest(1e-300), generator.digest(0))

    def test_catalog_requires_unique_reviewed_destinations_not_unique_stations(self):
        catalog = reviewed_catalog()
        generator.validate_catalog(catalog)
        for mutation in (
            lambda value: value["destinations"].pop(),
            lambda value: value["destinations"][1].update(alias="destination0"),
            lambda value: value["destinations"][1].update(
                selection_receipt="https://example.org/destination/0"
            ),
        ):
            invalid = copy.deepcopy(catalog)
            mutation(invalid)
            with self.assertRaises(generator.ValidationError):
                generator.validate_catalog(invalid)

    def test_catalog_rejects_credentials_unsafe_receipts_and_invalid_numbers(self):
        mutations = [
            lambda value: value.update(token="private-canary"),
            lambda value: value["review"].update(api_key="private-canary"),
            lambda value: value["destinations"][0]["station"].update(
                memberToken="private-canary"
            ),
            lambda value: value["destinations"][0].update(weight=True),
            lambda value: value["destinations"][0].update(weight=0),
            lambda value: value["destinations"][0].update(weight=math.nan),
            lambda value: value["destinations"][0].update(weight=math.inf),
            lambda value: value["destinations"][0]["station"].update(lat=90.1),
            lambda value: value["destinations"][0]["station"].update(lng=False),
            lambda value: value["destinations"][0].update(
                place_ids={"local": "not/a/place"}
            ),
        ]
        for mutation in mutations:
            invalid = synthetic_catalog()
            mutation(invalid)
            with self.assertRaises(generator.ValidationError):
                generator.validate_catalog(invalid)
        for receipt in (
            "http://example.org/a",
            "https://user:private-canary@example.org/a",
            "https://example.org/a?token=private-canary",
            "https://example.org/a#private-canary",
            "https://127.0.0.1/a",
            "https://127.0.0.1./a",
            "https://localhost./a",
            "https://example.org/a b",
            "https://service.internal/a",
        ):
            invalid = reviewed_catalog()
            invalid["destinations"][0]["selection_receipt"] = receipt
            with (
                self.subTest(receipt=receipt),
                self.assertRaises(generator.ValidationError),
            ):
                generator.validate_catalog(invalid)
        bounds = synthetic_catalog()
        bounds["destinations"][0]["station"].update(lat=-90, lng=180)
        generator.validate_catalog(bounds)
        overflow = reviewed_catalog()
        for destination in overflow["destinations"]:
            destination["weight"] = 1e308
        with self.assertRaises(generator.ValidationError):
            generator.validate_catalog(overflow)

    def test_cli_errors_never_echo_values_or_overwrite_input(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.json"
            catalog.write_text(json.dumps(synthetic_catalog()))
            before = catalog.read_text()
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(
                    generator.main(
                        [
                            "--workload",
                            "W1",
                            "--catalog",
                            str(catalog),
                            "--output",
                            str(catalog),
                        ]
                    ),
                    2,
                )
                self.assertEqual(
                    generator.main(
                        [
                            "--workload",
                            "W1",
                            "--vus",
                            "private-canary",
                            "--output",
                            str(catalog),
                        ]
                    ),
                    2,
                )
            self.assertNotIn("private-canary", stderr.getvalue())
            self.assertEqual(catalog.read_text(), before)


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.plan = generator.build_plan(
            "W1", scale=0.01, vus=2, catalog=synthetic_catalog()
        )
        self.records = evidence(self.plan)

    def test_complete_successful_cohort_reports_nearest_rank_latency(self):
        result = summary.summarize(self.plan, self.records)
        self.assertTrue(result["complete"])
        self.assertEqual(result["measured"]["planned"], 12)
        self.assertEqual(result["measured"]["started"], 12)
        self.assertEqual(result["measured"]["successful"], 12)
        self.assertEqual(
            result["measured"]["successful_http_duration_ms"],
            {"p50": 6, "p95": 12, "p99": 12},
        )
        self.assertEqual(result["measured"]["max_lateness_ms"], 3)
        self.assertEqual(result["groups"][0]["cohort"], "warm-complete")
        self.assertEqual(result["groups"][0]["timed_phase"], "steady")
        self.assertIsNone(result["hold"]["successful_per_second"])
        self.assertEqual(result["lambda_cold_classification"], "unknown")

    def test_fast_failures_pending_stale_and_dropped_are_not_success_latency(self):
        for row, outcome in zip(
            self.records[1:5],
            ("http_error", "pending", "stale", "dropped"),
            strict=True,
        ):
            row.update(
                outcome=outcome,
                duration_ms=0.01,
                search_status=outcome if outcome in ("pending", "stale") else "unknown",
            )
            row["end_ms"] = row["start_ms"] + row["duration_ms"]
            if outcome == "http_error":
                row["status"] = 503
            if outcome == "dropped":
                row.update(status=0, duration_ms=0, end_ms=row["start_ms"])
        result = summary.summarize(self.plan, self.records)
        measured = result["measured"]
        self.assertTrue(result["complete"])
        self.assertEqual(
            (
                measured["started"],
                measured["successful"],
                measured["http_errors"],
                measured["pending"],
                measured["stale"],
                measured["dropped"],
            ),
            (11, 8, 1, 1, 1, 1),
        )
        self.assertEqual(
            measured["successful_http_duration_ms"], {"p50": 8, "p95": 12, "p99": 12}
        )
        failed_groups = [
            group for group in result["groups"] if group["outcome"] != "success"
        ]
        self.assertTrue(
            all(
                group["successful_http_duration_ms"]["p50"] is None
                for group in failed_groups
            )
        )

    def test_no_success_has_no_invented_latency(self):
        for row in self.records[1:]:
            row.update(
                status=500,
                outcome="http_error",
                search_status="unknown",
                duration_ms=0.01,
            )
            row["end_ms"] = row["start_ms"] + row["duration_ms"]
        result = summary.summarize(self.plan, self.records)
        self.assertEqual(result["measured"]["successful"], 0)
        self.assertEqual(
            result["measured"]["successful_http_duration_ms"],
            {"p50": None, "p95": None, "p99": None},
        )

    def test_setup_errors_are_separate_from_measured_metrics(self):
        setup = copy.deepcopy(self.records[1])
        setup.update(
            phase="setup",
            cohort="setup",
            ordinal=None,
            planned_ms=None,
            start_ms=0,
            end_ms=1,
            duration_ms=1,
            op="create",
            status=500,
            outcome="http_error",
            search_status="unknown",
        )
        result = summary.summarize(
            self.plan, [self.records[0], setup, *self.records[1:]]
        )
        self.assertEqual(result["setup"]["errors"], 1)
        self.assertEqual(result["setup"]["http_errors"], 1)
        self.assertEqual(result["measured"]["successful"], 12)

    def test_hold_throughput_uses_full_scaled_hold_not_observation_span(self):
        plan = generator.build_plan(
            "W2", scale=0.01, vus=2, catalog=synthetic_catalog()
        )
        records = evidence(plan)
        failed = next(
            row
            for row in records[1:]
            if row["op"] == "save"
            and plan["arrivals"][row["ordinal"]]["phase"] == "hold"
        )
        failed.update(status=503, outcome="http_error", search_status="unknown")
        result = summary.summarize(plan, records)
        successes = sum(row["phase"] == "hold" for row in plan["arrivals"]) - 1
        self.assertEqual(result["hold"]["seconds"], 3)
        self.assertEqual(result["hold"]["successful_per_second"], successes / 3)
        saved = (
            sum(
                row["phase"] == "hold" and row["op"] == "save"
                for row in plan["arrivals"]
            )
            - 1
        )
        self.assertEqual(result["hold"]["by_operation"]["save"]["successful"], saved)
        self.assertEqual(
            result["hold"]["by_operation"]["save"]["successful_per_second"],
            saved / 3,
        )
        self.assertEqual(
            {group["timed_phase"] for group in result["groups"]}, {"ramp", "hold"}
        )

    def test_interrupted_run_is_explicitly_incomplete_and_cli_nonzero(self):
        records = self.records[:-2]
        result = summary.summarize(self.plan, records)
        self.assertFalse(result["complete"])
        self.assertEqual(result["evidence_status"], "incomplete")
        self.assertEqual(result["missing_ordinals"], [10, 11])
        self.assertEqual(result["measured"]["missing"], 2)
        with tempfile.TemporaryDirectory() as directory:
            plan, samples, output = (
                Path(directory) / name
                for name in ("plan.json", "samples.jsonl", "summary.json")
            )
            plan.write_text(json.dumps(self.plan))
            samples.write_text("".join(json.dumps(row) + "\n" for row in records))
            self.assertEqual(
                summary.main(
                    [
                        "--plan",
                        str(plan),
                        "--samples",
                        str(samples),
                        "--output",
                        str(output),
                    ]
                ),
                1,
            )
            self.assertFalse(json.loads(output.read_text())["complete"])

    def test_duplicate_missing_manifest_plan_mismatch_and_invalid_rows_rejected(self):
        cases = []
        cases.append([*self.records, copy.deepcopy(self.records[1])])
        cases.append(self.records[1:])
        cases.append([self.records[0], self.records[0], *self.records[1:]])
        for key, value in (
            ("op", "join"),
            ("planned_ms", 1),
            ("ordinal", True),
            ("worker", 1),
            ("status", 500),
            ("duration_ms", math.nan),
            ("duration_ms", 100),
            ("search_status", "pending"),
            ("phase", "unknown"),
            ("cohort", "mixed"),
        ):
            records = copy.deepcopy(self.records)
            records[1][key] = value
            cases.append(records)
        records = copy.deepcopy(self.records)
        records[0]["trace_sha256"] = "0" * 64
        cases.append(records)
        records = copy.deepcopy(self.records)
        records[0]["mode"] = "eval"
        cases.append(records)
        for index, records in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(ValueError):
                summary.summarize(self.plan, records)

    def test_rehashed_but_non_workload_trace_and_credential_plan_are_rejected(self):
        altered = copy.deepcopy(self.plan)
        altered["arrivals"][0]["at_ms"] += 1
        altered["trace_sha256"] = generator.digest(altered["arrivals"])
        with self.assertRaises(ValueError):
            summary.summarize(altered, evidence(altered))
        altered = copy.deepcopy(self.plan)
        altered["arrivals"][0]["memberToken"] = "private-canary"
        altered["trace_sha256"] = generator.digest(altered["arrivals"])
        with self.assertRaises(ValueError):
            summary.summarize(altered, evidence(altered))

    def test_projection_rejects_leaky_fields_and_does_not_copy_metadata(self):
        for key in ("body", "headers", "memberToken", "inviteToken", "error", "url"):
            records = copy.deepcopy(self.records)
            records[1][key] = {"secret": "private-canary"}
            with self.subTest(key=key), self.assertRaises(ValueError):
                summary.summarize(self.plan, records)
        self.records[0]["source_revision"] = "private-canary"
        self.plan["catalog"]["review"]["reviewer"] = "private-canary"
        # Regenerate because catalog review is committed by its hash.
        plan = generator.build_plan(
            "W1", scale=0.01, vus=2, catalog=self.plan["catalog"]
        )
        records = evidence(plan)
        records[0]["source_revision"] = "private-canary"
        result = summary.summarize(plan, records)
        self.assertNotIn("private-canary", json.dumps(result))
        self.assertNotIn("test-place-A", json.dumps(result))
        self.assertNotIn("selection_receipt", json.dumps(result))

    def test_malformed_input_preserves_existing_output_and_never_echoes_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            plan, samples, output = (
                Path(directory) / name
                for name in ("plan.json", "samples.jsonl", "summary.json")
            )
            plan.write_text(json.dumps(self.plan))
            output.write_text("existing-summary")
            stderr = io.StringIO()
            for contents in (
                "private-canary",
                '{"kind":"manifest","kind":"private-canary"}\n',
                "\n",
                "".join(
                    json.dumps(row) + "\n"
                    for row in [
                        *self.records,
                        {"kind": "sample", "body": "private-canary"},
                    ]
                ),
            ):
                samples.write_text(contents)
                with contextlib.redirect_stderr(stderr):
                    self.assertEqual(
                        summary.main(
                            [
                                "--plan",
                                str(plan),
                                "--samples",
                                str(samples),
                                "--output",
                                str(output),
                            ]
                        ),
                        2,
                    )
                self.assertEqual(output.read_text(), "existing-summary")
            self.assertNotIn("private-canary", stderr.getvalue())

    def test_valid_summary_cannot_overwrite_raw_evidence_or_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            plan, samples = (
                Path(directory) / name for name in ("plan.json", "samples.jsonl")
            )
            plan.write_text(json.dumps(self.plan))
            samples.write_text("".join(json.dumps(row) + "\n" for row in self.records))
            for output in (plan, samples):
                before = output.read_text()
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(
                        summary.main(
                            [
                                "--plan",
                                str(plan),
                                "--samples",
                                str(samples),
                                "--output",
                                str(output),
                            ]
                        ),
                        2,
                    )
                self.assertEqual(output.read_text(), before)


if __name__ == "__main__":
    unittest.main()
