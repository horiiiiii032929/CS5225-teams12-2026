#!/usr/bin/env python3
"""Summarize projected k6 JSONL; reject malformed evidence without reflecting it."""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import generate as workload

MANIFEST_KEYS = {
    "kind",
    "run_id",
    "target",
    "workload",
    "mode",
    "seed",
    "trace_sha256",
    "catalog_sha256",
    "source_revision",
    "standard",
    "vus",
    "duration_ms",
    "start_utc",
}
SAMPLE_KEYS = {
    "kind",
    "run_id",
    "target",
    "phase",
    "cohort",
    "ordinal",
    "op",
    "planned_ms",
    "start_ms",
    "end_ms",
    "duration_ms",
    "status",
    "outcome",
    "search_status",
    "worker",
}
OUTCOMES = (
    "success",
    "http_error",
    "invalid_response",
    "pending",
    "stale",
    "empty",
    "dropped",
)


def validate_manifest(manifest, plan):
    workload.exact(manifest, MANIFEST_KEYS, "manifest")
    workload.require(manifest["kind"] == "manifest", "manifest.kind")
    workload.alias(manifest["run_id"], "manifest.run_id")
    workload.alias(manifest["target"], "manifest.target")
    workload.text(manifest["source_revision"], "manifest.source_revision", limit=256)
    workload.require(manifest["mode"] in ("local", "eval"), "manifest.mode")
    workload.require(type(manifest["standard"]) is bool, "manifest.standard")
    workload.integer(manifest["seed"], "manifest.seed")
    workload.integer(manifest["vus"], "manifest.vus", minimum=1)
    workload.number(manifest["duration_ms"], "manifest.duration_ms", positive=True)
    for key in (
        "workload",
        "seed",
        "trace_sha256",
        "catalog_sha256",
        "standard",
        "vus",
        "duration_ms",
    ):
        workload.require(manifest[key] == plan[key], "manifest.plan")
    catalog = plan["catalog"]
    workload.require(catalog is not None, "manifest.catalog")
    workload.require(
        all(
            manifest["target"] in entry["place_ids"]
            for entry in catalog["destinations"]
        ),
        "manifest.target",
    )
    if manifest["mode"] == "eval":
        workload.require(
            plan["standard"] and catalog["kind"] == "reviewed-public", "manifest.mode"
        )
    stamp = manifest["start_utc"]
    workload.require(
        isinstance(stamp, str)
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", stamp)
        is not None,
        "manifest.start_utc",
    )
    try:
        workload.require(
            datetime.fromisoformat(stamp.replace("Z", "+00:00")).tzinfo == UTC,
            "manifest.start_utc",
        )
    except ValueError as error:
        raise workload.ValidationError("manifest.start_utc") from error


def validate_sample(row, manifest, plan):
    workload.exact(row, SAMPLE_KEYS, "sample")
    workload.require(row["kind"] == "sample", "sample.kind")
    workload.require(
        row["run_id"] == manifest["run_id"] and row["target"] == manifest["target"],
        "sample.identity",
    )
    workload.require(row["phase"] in ("setup", "measured"), "sample.phase")
    workload.require(
        row["op"] in ("create", "join", "save", "search", "read"), "sample.op"
    )
    workload.require(row["outcome"] in OUTCOMES, "sample.outcome")
    workload.require(
        row["search_status"] in ("complete", "pending", "stale", "unknown"),
        "sample.search_status",
    )
    workload.integer(row["worker"], "sample.worker", minimum=0)
    workload.require(row["worker"] < plan["vus"], "sample.worker")
    for key in ("start_ms", "end_ms", "duration_ms"):
        workload.require(workload.number(row[key], "sample.time") >= 0, "sample.time")
    workload.require(row["end_ms"] >= row["start_ms"], "sample.time")
    workload.require(
        math.isclose(
            row["duration_ms"], row["end_ms"] - row["start_ms"], rel_tol=0, abs_tol=1e-6
        ),
        "sample.duration_ms",
    )
    workload.integer(row["status"], "sample.status")
    workload.require(row["status"] == 0 or 100 <= row["status"] <= 599, "sample.status")
    if row["phase"] == "setup":
        workload.require(
            row["ordinal"] is None
            and row["planned_ms"] is None
            and row["cohort"] == "setup"
            and row["outcome"] != "dropped",
            "sample.setup",
        )
    else:
        ordinal = workload.integer(row["ordinal"], "sample.ordinal", minimum=0)
        workload.require(ordinal < len(plan["arrivals"]), "sample.ordinal")
        arrival = plan["arrivals"][ordinal]
        workload.number(row["planned_ms"], "sample.planned_ms")
        workload.require(
            row["planned_ms"] == arrival["at_ms"]
            and row["op"] == arrival["op"]
            and row["worker"] == ordinal % plan["vus"],
            "sample.plan",
        )
        workload.require(row["start_ms"] + 1e-6 >= row["planned_ms"], "sample.start_ms")
        workload.require(
            row["cohort"] == ("warm-complete" if row["op"] == "read" else "mixed"),
            "sample.cohort",
        )
    outcome, status = row["outcome"], row["status"]
    if outcome == "dropped":
        workload.require(
            row["phase"] == "measured"
            and status == 0
            and row["duration_ms"] == 0
            and row["start_ms"] == row["end_ms"]
            and row["search_status"] == "unknown",
            "sample.dropped",
        )
    elif outcome == "http_error":
        workload.require(
            not 200 <= status < 300 and row["search_status"] == "unknown",
            "sample.http_error",
        )
    else:
        workload.require(200 <= status < 300, "sample.status")
        if outcome in ("pending", "stale"):
            workload.require(
                row["op"] in ("search", "read") and row["search_status"] == outcome,
                "sample.search_status",
            )
        elif outcome == "empty":
            workload.require(
                row["op"] in ("search", "read") and row["search_status"] == "complete",
                "sample.search_status",
            )
        elif outcome == "success":
            workload.require(
                row["search_status"]
                == ("complete" if row["op"] in ("search", "read") else "unknown"),
                "sample.search_status",
            )
        else:
            workload.require(row["search_status"] == "unknown", "sample.search_status")


def percentiles(rows, field="duration_ms", subtract=None):
    durations = sorted(
        row[field] - (row[subtract] if subtract else 0)
        for row in rows
        if row["outcome"] == "success"
        and (subtract is None or row[subtract] is not None)
    )
    return {
        name: durations[math.ceil(len(durations) * percentile) - 1]
        if durations
        else None
        for name, percentile in (("p50", 0.50), ("p95", 0.95), ("p99", 0.99))
    }


def metrics(rows, planned=0):
    outcomes = Counter(row["outcome"] for row in rows)
    return {
        "planned": planned,
        "observed": len(rows),
        "started": sum(row["outcome"] != "dropped" for row in rows),
        "successful": outcomes["success"],
        "dropped": outcomes["dropped"],
        "http_errors": outcomes["http_error"],
        "pending": outcomes["pending"],
        "stale": outcomes["stale"],
        "empty": outcomes["empty"],
        "invalid": outcomes["invalid_response"],
        "status_counts": dict(
            sorted(Counter(str(row["status"]) for row in rows).items())
        ),
        "outcome_counts": {outcome: outcomes[outcome] for outcome in OUTCOMES},
        "successful_http_duration_ms": percentiles(rows),
        "successful_arrival_latency_ms": percentiles(rows, "end_ms", "planned_ms"),
        "successful_queue_delay_ms": percentiles(rows, "start_ms", "planned_ms"),
    }


def summarize(plan, records):
    workload.validate_plan(plan)
    iterator = iter(records)
    try:
        manifest = next(iterator)
    except StopIteration as error:
        raise workload.ValidationError("manifest.missing") from error
    validate_manifest(manifest, plan)
    setup, measured, seen = [], [], set()
    groups = defaultdict(list)
    for row in iterator:
        validate_sample(row, manifest, plan)
        if row["phase"] == "measured":
            workload.require(row["ordinal"] not in seen, "sample.duplicate")
            seen.add(row["ordinal"])
            measured.append(row)
            timed_phase = plan["arrivals"][row["ordinal"]]["phase"]
        else:
            workload.require(not seen, "sample.setup_order")
            setup.append(row)
            timed_phase = "setup"
        groups[
            (row["phase"], row["cohort"], row["op"], timed_phase, row["outcome"])
        ].append(row)
    missing = [
        arrival["ordinal"]
        for arrival in plan["arrivals"]
        if arrival["ordinal"] not in seen
    ]
    group_summaries = []
    for key, rows in sorted(groups.items()):
        phase, cohort, op, timed_phase, outcome = key
        group_summaries.append(
            {
                "phase": phase,
                "cohort": cohort,
                "op": op,
                "timed_phase": timed_phase,
                "outcome": outcome,
                **metrics(rows, len(rows) if phase == "measured" else 0),
            }
        )
    for (cohort, op, timed_phase), count in sorted(
        Counter(
            (
                "warm-complete"
                if plan["arrivals"][ordinal]["op"] == "read"
                else "mixed",
                plan["arrivals"][ordinal]["op"],
                plan["arrivals"][ordinal]["phase"],
            )
            for ordinal in missing
        ).items()
    ):
        group_summaries.append(
            {
                "phase": "measured",
                "cohort": cohort,
                "op": op,
                "timed_phase": timed_phase,
                "outcome": "missing",
                **metrics([], count),
            }
        )
    hold_seconds = 300 * plan["scale"] if plan["workload"] == "W2" else None
    hold_successful = sum(
        row["outcome"] == "success"
        and plan["arrivals"][row["ordinal"]]["phase"] == "hold"
        for row in measured
    )
    hold_operations = Counter(
        row["op"]
        for row in measured
        if row["outcome"] == "success"
        and plan["arrivals"][row["ordinal"]]["phase"] == "hold"
    )
    setup_metrics = metrics(setup)
    setup_metrics["errors"] = len(setup) - setup_metrics["successful"]
    measured_metrics = metrics(measured, len(plan["arrivals"]))
    measured_metrics["missing"] = len(missing)
    measured_metrics["max_lateness_ms"] = max(
        (max(0, row["start_ms"] - row["planned_ms"]) for row in measured), default=None
    )
    truncated_tail = getattr(records, "truncated_tail", False)
    complete = not missing and not truncated_tail
    return {
        "version": 1,
        "complete": complete,
        "evidence_status": "complete" if complete else "incomplete",
        "truncated_tail": truncated_tail,
        "run_id": manifest["run_id"],
        "target": manifest["target"],
        "mode": manifest["mode"],
        "workload": plan["workload"],
        "seed": plan["seed"],
        "standard": plan["standard"],
        "scale": plan["scale"],
        "vus": plan["vus"],
        "duration_ms": plan["duration_ms"],
        "trace_sha256": plan["trace_sha256"],
        "catalog_sha256": plan["catalog_sha256"],
        "missing_ordinals": missing,
        "setup": setup_metrics,
        "measured": measured_metrics,
        "groups": group_summaries,
        "hold": {
            "seconds": hold_seconds,
            "successful": hold_successful if hold_seconds is not None else None,
            "successful_per_second": hold_successful / hold_seconds
            if hold_seconds is not None
            else None,
            "by_operation": {
                operation: {
                    "successful": hold_operations[operation],
                    "successful_per_second": hold_operations[operation] / hold_seconds,
                }
                for operation in ("create", "join", "save", "read")
            }
            if hold_seconds is not None
            else {},
        },
        "latency_basis": (
            "successful eligible HTTP duration and planned-arrival-to-completion "
            "wall-clock latency; failures/drops/missing reported separately, "
            "not successful latency samples; clock regressions excluded"
        ),
        "capacity_claim": (
            "offered versus started under finite VUs; not maximum capacity"
        ),
        "lambda_cold_classification": "unknown",
        "init_billing_telemetry": "unavailable",
    }


def _truncated_sample(source, manifest):
    """Recognize only an unfinished flat sample prefix; never retain its contents."""
    source = source.strip()
    if not source.startswith("{") or manifest is None:
        return False
    decoder = json.JSONDecoder()
    strings = {
        "kind": ("sample",),
        "run_id": (manifest.get("run_id"),),
        "target": (manifest.get("target"),),
        "phase": ("setup", "measured"),
        "cohort": ("setup", "warm-complete", "mixed"),
        "op": ("create", "join", "save", "search", "read"),
        "outcome": OUTCOMES,
        "search_status": ("complete", "pending", "stale", "unknown"),
    }
    nullable = {"ordinal", "planned_ms"}
    seen = set()
    rest = source[1:].lstrip()
    while rest:
        try:
            key, end = decoder.raw_decode(rest)
        except json.JSONDecodeError:
            # JSON.stringify emits these field names without escapes.
            return (not seen and '"kind"'.startswith(rest)) or (
                "kind" in seen
                and any(
                    ('"' + key + '"').startswith(rest) for key in SAMPLE_KEYS - seen
                )
            )
        if not isinstance(key, str) or key not in SAMPLE_KEYS or key in seen:
            return False
        seen.add(key)
        rest = rest[end:].lstrip()
        if not rest:
            return "kind" in seen
        if not rest.startswith(":"):
            return False
        rest = rest[1:].lstrip()
        if not rest:
            return "kind" in seen
        try:
            value, end = decoder.raw_decode(rest)
        except json.JSONDecodeError:
            if "kind" not in seen:
                return False
            if key in strings:
                return any(
                    isinstance(value, str) and json.dumps(value).startswith(rest)
                    for value in strings[key]
                )
            return (key in nullable and "null".startswith(rest)) or re.fullmatch(
                r"(?:0|[1-9][0-9]*)(?:\.[0-9]*)?(?:[eE][+-]?[0-9]*)?", rest
            ) is not None
        if key in strings:
            if value not in strings[key]:
                return False
        elif value is None:
            if key not in nullable:
                return False
        elif type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            return False
        suffix = rest[end:].lstrip()
        if not suffix:
            return True
        if not suffix.startswith(","):
            # raw_decode can consume the integer part of an unfinished exponent.
            return (
                key not in strings
                and re.fullmatch(
                    r"(?:0|[1-9][0-9]*)(?:\.[0-9]*)?(?:[eE][+-]?[0-9]*)?", rest
                )
                is not None
            )
        rest = suffix[1:].lstrip()
    return not seen or "kind" in seen


class Records:
    def __init__(self, path):
        self.path = path
        self.truncated_tail = False

    def __iter__(self):
        manifest = None
        with Path(self.path).open(encoding="utf-8") as source:
            for line in source:
                workload.require(bool(line.strip()), "jsonl.blank")
                try:
                    row = workload.parse_json(line)
                except workload.ValidationError:
                    if not line.endswith("\n") and _truncated_sample(line, manifest):
                        self.truncated_tail = True
                        return
                    raise
                if manifest is None:
                    manifest = row
                yield row


def read_records(path):
    return Records(path)


def main(argv=None):
    try:
        parser = workload.SafeArgumentParser(description=__doc__)
        parser.add_argument("--plan", type=Path, required=True)
        parser.add_argument("--samples", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        args = parser.parse_args(argv)
        summary = summarize(workload.load_json(args.plan), read_records(args.samples))
        workload.write_json_atomic(
            args.output, summary, protected=(args.plan, args.samples)
        )
        return 0 if summary["complete"] else 1
    except workload.ValidationError as error:
        print("load summary: invalid " + str(error), file=sys.stderr)
        return 2
    except (
        OSError,
        UnicodeError,
        ValueError,
        OverflowError,
        RecursionError,
        TypeError,
    ):
        print("load summary: invalid input or output", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
