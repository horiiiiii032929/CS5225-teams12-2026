#!/usr/bin/env python3
"""FlatSplit cost model — AWS serverless vs AWS always-on VM vs on-premise.

Issue #45 (Compare AWS and on-premise hosting costs), experiment E9 in
docs/evaluation-plan.md. Every number comes from the three JSON files next to
this script; nothing is hardcoded here, so refining the model means editing a
JSON field, re-running, and committing the new evidence file.

Usage:
    python3 cost_model.py                  # writes evidence/cost_model_<utc>.{md,json,csv}
    python3 cost_model.py --print          # also prints the markdown to stdout
    python3 cost_model.py --scale 10       # sensitivity: multiply demand by 10

Stdlib only, Python 3.11+.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE.parent / "evidence"
GIB = 1024**3


def load(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# usage derivation: user-level assumptions -> billable units
# --------------------------------------------------------------------------
def derive_usage(
    scenario: dict, shared: dict, facts: dict, measured: dict, scale: float
) -> dict:
    groups = scenario["groups_per_month"] * scale
    members = groups * scenario["members_per_group"]
    joins = members - groups  # the organiser is created with the group, not by joining
    searches = groups * scenario["searches_per_group"]
    polls = searches * scenario["result_polls_per_search"]
    places = members * scenario["places_lookups_per_member"]
    places_warm = places * scenario["places_lookup_cache_hit_ratio"]
    places_cold = places - places_warm
    prefs = members * scenario["preference_saves_per_member"]
    group_reads = members * 2  # opening the shared link

    burst_requests = 0.0
    if scenario.get("burst_events_per_month"):
        peak = scenario["burst_peak_rps"]
        burst_requests = scenario["burst_events_per_month"] * (
            peak * scenario["burst_hold_seconds"]
            + 0.5 * peak * scenario.get("burst_ramp_seconds", 0)
        )

    api_requests = (
        groups + joins + places + prefs + searches + polls + group_reads + burst_requests
    )

    # Commute pairs. A pair whose COMMUTE# record is already usable costs one read
    # inside the search's own request budget and nothing else: measured, the handler
    # returns before writing or sending. A miss on a routable town writes one claim
    # and sends exactly one message; a miss on the non-routable town (TENGAH) writes
    # the unavailable record and sends nothing.
    stations = shared["distinct_member_stations_per_group"]
    miss = 1 - scenario["commute_cache_hit_ratio"]
    jobs = searches * stations * facts["towns_routable"] * miss
    non_routable_writes = (
        searches * stations * facts["non_routable_pairs_per_member_station"] * miss
    )

    lambda_api_invocations = api_requests
    lambda_worker_invocations = jobs
    lambda_other = shared["monthly_ingest_runs"]
    lambda_invocations = lambda_api_invocations + lambda_worker_invocations + lambda_other

    mem_gb = shared["lambda_memory_mb"] / 1024
    gb_seconds = mem_gb * (
        (api_requests - places) * shared["lambda_api_duration_ms"] / 1000
        + places_cold * shared["lambda_places_cold_duration_ms"] / 1000
        + places_warm * shared["lambda_places_warm_duration_ms"] / 1000
        + lambda_worker_invocations * shared["lambda_worker_duration_ms"] / 1000
        + lambda_other * 5.0
    )

    # Per-request DynamoDB counts are measured; see workloads.json measured_operations.
    cold, warm = measured["places_lookup_cold"], measured["places_lookup_warm"]
    start = measured["search_start"]
    ddb_read_requests = (
        places_cold * cold["ddb_reads"]
        + places_warm * warm["ddb_reads"]
        + groups * measured["group_create"]["ddb_reads"]
        + joins * measured["member_join"]["ddb_reads"]
        + prefs * measured["preference_save"]["ddb_reads"]
        + group_reads * measured["group_read"]["ddb_reads"]
        + searches * start["ddb_reads"]
        + polls * measured["search_poll"]["ddb_reads"]
    )

    def billed_writes(op: dict, suffix: str = "") -> int:
        """Mutations plus condition checks.

        A transaction's `ConditionCheck` changes nothing, so it is counted apart
        from the mutations, but AWS bills it as a transactional write and it
        consumes one of the transaction's 100 action slots. Both therefore cost
        write units.
        """
        return (
            op[f"ddb_write_mutations{suffix}"] + op[f"ddb_condition_checks{suffix}"]
        )

    ddb_writes = (
        places_cold * cold["ddb_writes"]
        + groups * billed_writes(measured["group_create"])
        + joins * billed_writes(measured["member_join"])
        + prefs * billed_writes(measured["preference_save"])
        + searches * billed_writes(start, "_fixed")
        + (jobs + non_routable_writes) * start["ddb_writes_per_pair_record"]
        + jobs  # one result write per job by #15's worker (assumed; #74 in review)
        + shared["monthly_ingest_runs"] * shared["rent_snapshot_items"]
    )

    cf_requests = api_requests + scenario["web_page_loads_per_month"] * scale * shared[
        "web_asset_requests_per_cold_load"
    ]
    cf_gb_out = (
        scenario["web_page_loads_per_month"] * scale * shared["web_page_bytes"]
        + api_requests * shared["api_response_kb"] * 1024
    ) / GIB
    cf_gb_to_origin = api_requests * shared["api_response_kb"] * 1024 / GIB

    sqs_requests = jobs * shared["sqs_requests_per_job"] + shared[
        "sqs_idle_poll_requests_per_month"
    ]
    cold_starts = lambda_invocations * shared["cold_start_share"]
    log_gb = lambda_invocations * shared["log_bytes_per_invocation"] / GIB
    onemap_lookup_calls = places_cold * cold["onemap_calls"]

    return {
        "groups": groups,
        "members": members,
        "searches": searches,
        "result_polls": polls,
        "api_requests": api_requests,
        "burst_requests": burst_requests,
        "places_lookups": places,
        "places_lookups_cold": places_cold,
        "places_lookups_warm": places_warm,
        "commute_jobs": jobs,
        "commute_pair_writes": jobs + non_routable_writes,
        "onemap_routing_calls": jobs,
        "onemap_lookup_calls": onemap_lookup_calls,
        "onemap_calls": jobs + onemap_lookup_calls,
        "lambda_invocations": lambda_invocations,
        "lambda_gb_seconds": gb_seconds,
        "ddb_read_requests": ddb_read_requests,
        "ddb_rru": ddb_read_requests * shared["ddb_rru_per_read_request"],
        "ddb_writes": ddb_writes,
        "ddb_wru": ddb_writes * shared["ddb_wru_per_write"],
        "cloudfront_requests": cf_requests,
        "cloudfront_gb_out": cf_gb_out,
        "cloudfront_gb_to_origin": cf_gb_to_origin,
        "sqs_requests": sqs_requests,
        "cold_starts": cold_starts,
        "cloudwatch_log_gb": log_gb,
    }


def line(service: str, driver: str, gross: float, free: float = 0.0, free_kind: str = "") -> dict:
    return {
        "service": service,
        "driver": driver,
        "gross_usd": round(gross, 4),
        "free_tier_usd": round(min(free, gross), 4),
        "net_usd": round(max(gross - free, 0.0), 4),
        "free_tier_kind": free_kind,
    }


# --------------------------------------------------------------------------
# option A: AWS serverless (what the team actually deployed)
# --------------------------------------------------------------------------
def aws_serverless(u: dict, p: dict, shared: dict) -> list[dict]:
    L, A, D = p["lambda"], p["api_gateway_http"], p["dynamodb_on_demand"]
    S3, CF, Q = p["s3_standard"], p["cloudfront"], p["sqs_standard"]
    SM, CW = p["secrets_manager"], p["cloudwatch"]
    out = []

    out.append(line(
        "Lambda requests",
        f"{u['lambda_invocations']:,.0f} invocations",
        u["lambda_invocations"] * L["request_per_request"],
        min(u["lambda_invocations"], L["free_requests_per_month"]) * L["request_per_request"],
        "always free",
    ))
    out.append(line(
        "Lambda compute (arm64)",
        f"{u['lambda_gb_seconds']:,.0f} GB-s @256 MB",
        u["lambda_gb_seconds"] * L["arm64_gb_second"],
        min(u["lambda_gb_seconds"], L["free_gb_seconds_per_month"]) * L["arm64_gb_second"],
        "always free",
    ))
    out.append(line(
        "API Gateway HTTP API",
        f"{u['api_requests']:,.0f} requests",
        u["api_requests"] * A["request_per_request"],
        min(u["api_requests"], A["free_requests_per_month"]) * A["request_per_request"],
        "12 months only",
    ))
    out.append(line(
        "DynamoDB reads",
        f"{u['ddb_rru']:,.0f} RRU",
        u["ddb_rru"] * D["read_request_unit"],
    ))
    out.append(line(
        "DynamoDB writes",
        f"{u['ddb_wru']:,.0f} WRU",
        u["ddb_wru"] * D["write_request_unit"],
    ))
    size = shared["ddb_table_size_gb"]
    out.append(line(
        "DynamoDB storage",
        f"{size} GB",
        size * D["storage_gb_month"],
        min(size, D["free_storage_gb"]) * D["storage_gb_month"],
        "25 GB always free",
    ))
    out.append(line("DynamoDB PITR", f"{size} GB", size * D["pitr_gb_month"]))
    s3_gb = shared["web_build_size_mb"] / 1024 + shared["s3_raw_rent_gb"]
    out.append(line(
        "S3 storage (web build + raw rent files)",
        f"{s3_gb:.3f} GB",
        s3_gb * S3["storage_gb_month"],
        min(s3_gb, S3["free_storage_gb"]) * S3["storage_gb_month"],
        "12 months only",
    ))
    out.append(line(
        "CloudFront data transfer out",
        f"{u['cloudfront_gb_out']:.2f} GB",
        u["cloudfront_gb_out"] * CF["data_transfer_out_gb"],
        min(u["cloudfront_gb_out"], CF["free_data_transfer_gb_per_month"]) * CF["data_transfer_out_gb"],
        "1 TB always free",
    ))
    out.append(line(
        "CloudFront HTTPS requests",
        f"{u['cloudfront_requests']:,.0f} requests",
        u["cloudfront_requests"] / 10000 * CF["https_request_per_10000"],
        min(u["cloudfront_requests"], CF["free_https_requests_per_month"]) / 10000
        * CF["https_request_per_10000"],
        "10M always free",
    ))
    out.append(line(
        "CloudFront -> origin transfer",
        f"{u['cloudfront_gb_to_origin']:.2f} GB",
        u["cloudfront_gb_to_origin"] * CF["data_transfer_to_origin_gb"],
    ))
    out.append(line(
        "SQS requests (jobs + idle long polls)",
        f"{u['sqs_requests']:,.0f} requests",
        u["sqs_requests"] * Q["request_per_request"],
        min(u["sqs_requests"], Q["free_requests_per_month"]) * Q["request_per_request"],
        "1M always free",
    ))
    out.append(line(
        "Secrets Manager",
        f"{shared['secrets_count']} secret + {u['cold_starts']:,.0f} API calls",
        shared["secrets_count"] * SM["secret_per_month"]
        + u["cold_starts"] / 10000 * SM["api_per_10000"],
    ))
    out.append(line(
        "CloudWatch logs ingest",
        f"{u['cloudwatch_log_gb']:.2f} GB",
        u["cloudwatch_log_gb"] * CW["logs_ingest_gb_standard_class"],
        min(u["cloudwatch_log_gb"], CW["free_logs_ingest_gb_per_month"])
        * CW["logs_ingest_gb_standard_class"],
        "5 GB always free",
    ))
    out.append(line(
        "CloudWatch logs storage (1-week retention)",
        f"{u['cloudwatch_log_gb'] * 7 / 30:.2f} GB-month",
        u["cloudwatch_log_gb"] * 7 / 30 * CW["logs_storage_gb_month"],
    ))
    metrics = shared["cloudwatch_custom_metrics"]
    out.append(line(
        "CloudWatch custom metrics",
        f"{metrics} metrics",
        metrics * CW["custom_metric_per_month_first_10k"],
        min(metrics, CW["free_custom_metrics"]) * CW["custom_metric_per_month_first_10k"],
        "10 always free",
    ))
    alarms = shared["cloudwatch_alarms"]
    out.append(line(
        "CloudWatch alarms",
        f"{alarms} alarms",
        alarms * CW["alarm_per_month_standard_resolution"],
        min(alarms, CW["free_alarms"]) * CW["alarm_per_month_standard_resolution"],
        "10 always free",
    ))
    dash = shared["cloudwatch_dashboards"]
    out.append(line(
        "CloudWatch dashboard",
        f"{dash} dashboard",
        dash * CW["dashboard_per_month"],
        min(dash, CW["free_dashboards"]) * CW["dashboard_per_month"],
        "3 always free",
    ))
    out.append(line("AWS Budgets", "1 cost budget", p["aws_budgets"]["monthly"]))
    return out


# --------------------------------------------------------------------------
# option B: AWS always-on VM (same code under uvicorn, cloud-hosted)
# --------------------------------------------------------------------------
def aws_vm(u: dict, p: dict, shared: dict, nodes: int) -> list[dict]:
    E, CW, S3, D = p["ec2"], p["cloudwatch"], p["s3_standard"], p["dynamodb_on_demand"]
    hours = E["hours_per_month"]
    gb_out = u["cloudfront_gb_out"]
    billable_out = max(gb_out - E["free_data_transfer_out_gb_per_month"], 0)
    disk_gb = 20
    return [
        line(f"EC2 t4g.small x{nodes} (24x7)", f"{nodes * hours:,.0f} instance-hours",
             nodes * hours * E["t4g_small_linux_on_demand_hour"]),
        line("EBS gp3", f"{nodes * disk_gb} GB", nodes * disk_gb * E["ebs_gp3_gb_month"]),
        line("Internet data transfer out", f"{gb_out:.2f} GB (first 100 GB free)",
             billable_out * E["data_transfer_out_gb"]),
        line("DynamoDB (same data layer)", f"{u['ddb_rru']:,.0f} RRU + {u['ddb_wru']:,.0f} WRU",
             u["ddb_rru"] * D["read_request_unit"] + u["ddb_wru"] * D["write_request_unit"]
             + shared["ddb_table_size_gb"] * (D["storage_gb_month"] + D["pitr_gb_month"])),
        line("S3 (backups + raw files)", f"{shared['s3_raw_rent_gb'] * 2:.2f} GB",
             shared["s3_raw_rent_gb"] * 2 * S3["storage_gb_month"]),
        line("CloudWatch (agent logs, alarms, dashboard)", "same observability set",
             u["cloudwatch_log_gb"] * CW["logs_ingest_gb_standard_class"]
             + shared["cloudwatch_alarms"] * CW["alarm_per_month_standard_resolution"]
             + shared["cloudwatch_dashboards"] * CW["dashboard_per_month"]),
    ]


# --------------------------------------------------------------------------
# option C: on-premise
# --------------------------------------------------------------------------
def onprem(o: dict, nodes: int) -> list[dict]:
    rate = o["meta"]["sgd_per_usd"]
    months = o["meta"]["depreciation_months"]
    cap = o["capex_sgd"]
    capex_sgd = (
        cap["server_unit"] * nodes
        + cap["ups"] + cap["network_switch_router"] + cap["backup_disks"] + cap["spare_parts_buffer"]
    )
    pw = o["power"]
    avg_w = pw["watts_idle_per_node"] * (1 - pw["load_duty_cycle"]) + pw["watts_load_per_node"] * pw["load_duty_cycle"]
    kwh = avg_w * nodes * 730 / 1000 * pw["pue"]
    elec_sgd = kwh * o["meta"]["electricity_sgd_per_kwh"]
    op = o["opex_sgd_per_month"]
    eff = o["operational_effort"]
    effort_sgd = eff["hours_per_month"] * eff["rate_sgd_per_hour"]
    rows = [
        line(f"Hardware depreciation ({nodes} node(s) + UPS/switch/disks, {months} mo)",
             f"S${capex_sgd:,.0f} capex", capex_sgd / months / rate),
        line("Electricity (incl. PUE)", f"{kwh:,.1f} kWh/month @ S${o['meta']['electricity_sgd_per_kwh']}/kWh",
             elec_sgd / rate),
        line("Room cooling share", "assumption", op["aircon_room_share"] / rate),
        line("Business internet + static IP", "assumption", op["internet_business_fibre_static_ip"] / rate),
        line("Offsite backup", "nightly dumps to object storage", op["offsite_backup"] / rate),
        line("Domain + TLS", "Let's Encrypt = 0", op["domain_and_tls"] / rate),
        line("Operational effort",
             f"{eff['hours_per_month']} h/month @ S${eff['rate_sgd_per_hour']}/h", effort_sgd / rate),
    ]
    return rows


def total(rows: list[dict], key: str = "net_usd") -> float:
    # math.fsum, not sum: a line-item total feeds a figure rounded to four
    # decimals, and the bursty VM total lands exactly on a rounding boundary
    # (57.7041 / 6,000 searches x 1,000 = 9.61735). CPython 3.12 gave sum()
    # compensated summation, so sum() returns 57.7041 there and
    # 57.70409999999999 on 3.11, the model's documented minimum -- the same
    # model would publish 9.6174 or 9.6173 depending on who ran it. fsum
    # avoids that sum() version difference; it agrees on 9.6174 on CPython
    # 3.9, 3.11, 3.12 and 3.13, the versions this was verified against.
    # Python documents fsum's accuracy as platform-dependent, so this is the
    # demonstrated claim, not universal decimal arithmetic.
    return math.fsum(r[key] for r in rows)


def md_table(rows: list[dict], show_free: bool = True) -> str:
    if show_free:
        out = ["| Line item | Driver | List price (US$) | Free tier (US$) | Payable (US$) |",
               "|---|---|---:|---:|---:|"]
        for r in rows:
            free = "-" if r["free_tier_usd"] == 0 else f"-{r['free_tier_usd']:.2f}"
            out.append(f"| {r['service']} | {r['driver']} | {r['gross_usd']:.2f} | "
                       f"{free} | {r['net_usd']:.2f} |")
        out.append(f"| **Total** | | **{total(rows, 'gross_usd'):.2f}** | "
                   f"**-{total(rows, 'free_tier_usd'):.2f}** | **{total(rows):.2f}** |")
    else:
        out = ["| Line item | Driver | US$/month |", "|---|---|---:|"]
        for r in rows:
            out.append(f"| {r['service']} | {r['driver']} | {r['net_usd']:.2f} |")
        out.append(f"| **Total** | | **{total(rows):.2f}** |")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.0, help="multiply all demand by this factor")
    ap.add_argument("--print", action="store_true", dest="echo")
    args = ap.parse_args()

    prices = load("prices_ap_southeast_1.json")
    wl = load("workloads.json")
    op = load("onprem.json")
    shared, facts = wl["shared_assumptions"], wl["meta"]["fixed_facts"]
    measured = wl["measured_operations"]

    cap = op["capacity"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result: dict = {
        "generated_utc": stamp,
        "issue": 45,
        "experiment": "E9",
        "scale": args.scale,
        "status": wl["meta"]["status"],
        "price_source": prices["meta"]["source"],
        "scenarios": {},
    }
    md = [
        f"# FlatSplit cost model output — {stamp}",
        "",
        f"Demand scale factor: **x{args.scale}**. Status: **partially measured** "
        "(per-request operation counts measured 20 and 27 October 2026; demand, Lambda "
        "duration for non-lookup routes, cold-start share and log volume still "
        "assumed, and still owned by #30 and #34).",
        "",
        f"Prices: {prices['meta']['source']}",
        "",
    ]

    for key, sc in wl["scenarios"].items():
        u = derive_usage(sc, shared, facts, measured, args.scale)
        peak = sc.get("burst_peak_rps", cap["target_peak_rps"]) if key == "bursty" else None
        peak_rps = cap["target_peak_rps"] if key == "bursty" else max(
            2, math.ceil(u["api_requests"] / (30 * 24 * 3600) * 20)
        )
        nodes = math.ceil(peak_rps / cap["sustained_rps_per_node"]) + cap["redundancy_nodes"]

        a = aws_serverless(u, prices, shared)
        b = aws_vm(u, prices, shared, nodes)
        c = onprem(op, nodes)
        per_1k = lambda rows: total(rows) / u["searches"] * 1000 if u["searches"] else 0.0

        result["scenarios"][key] = {
            "label": sc["label"],
            "usage": {k: round(v, 3) for k, v in u.items()},
            "nodes_for_onprem_and_vm": nodes,
            "peak_rps_assumed": peak_rps,
            "aws_serverless": {"lines": a, "list_price_usd": round(total(a, "gross_usd"), 2),
                               "free_tier_usd": round(total(a, "free_tier_usd"), 2),
                               "payable_usd": round(total(a), 2),
                               "usd_per_1000_searches": round(per_1k(a), 4)},
            "aws_always_on_vm": {"lines": b, "payable_usd": round(total(b), 2),
                                 "usd_per_1000_searches": round(per_1k(b), 4)},
            "on_premise": {"lines": c, "payable_usd": round(total(c), 2),
                           "usd_per_1000_searches": round(per_1k(c), 4)},
        }

        md += [
            f"## {sc['label']}",
            "",
            f"Monthly usage: {u['groups']:,.0f} groups, {u['searches']:,.0f} searches, "
            f"{u['api_requests']:,.0f} API requests, {u['commute_jobs']:,.0f} commute jobs "
            f"and {u['cloudwatch_log_gb']:.2f} GB of logs. OneMap sees "
            f"{u['onemap_calls']:,.0f} calls: {u['onemap_routing_calls']:,.0f} routing "
            f"calls plus {u['onemap_lookup_calls']:,.0f} from destination lookups "
            f"({u['places_lookups_cold']:,.0f} cold lookups x "
            f"{measured['places_lookup_cold']['onemap_calls']} measured calls each). "
            f"Commute cache hit ratio assumed {sc['commute_cache_hit_ratio']:.0%}, "
            f"lookup cache {sc['places_lookup_cache_hit_ratio']:.0%}.",
            "",
            "### A. AWS serverless (deployed architecture)",
            "",
            md_table(a),
            "",
            "### B. AWS always-on VM (same handler under uvicorn)",
            "",
            f"Sized at {nodes} x t4g.small for an assumed peak of {peak_rps} req/s "
            f"and {cap['sustained_rps_per_node']} req/s per node (PLACEHOLDER from #30/E2).",
            "",
            md_table(b, show_free=False),
            "",
            "### C. On-premise",
            "",
            md_table(c, show_free=False),
            "",
            "### Comparison",
            "",
            "| Option | US$/month | US$ per 1,000 searches |",
            "|---|---:|---:|",
            f"| A. AWS serverless (payable) | {total(a):.2f} | {per_1k(a):.3f} |",
            f"| A. AWS serverless (list price, no free tier) | {total(a, 'gross_usd'):.2f} | "
            f"{total(a, 'gross_usd') / u['searches'] * 1000 if u['searches'] else 0:.3f} |",
            f"| B. AWS always-on VM | {total(b):.2f} | {per_1k(b):.3f} |",
            f"| C. On-premise | {total(c):.2f} | {per_1k(c):.3f} |",
            "",
        ]

    # ---- sensitivity to demand on the typical scenario ----
    md += ["## Sensitivity to demand (typical scenario scaled)", "",
           "| Demand | AWS serverless payable | AWS serverless list price | On-premise | Nodes |",
           "|---|---:|---:|---:|---:|"]
    sens = []
    for f in (0.0, 0.1, 1.0, 10.0, 100.0):
        sc = wl["scenarios"]["typical"]
        u = (
            derive_usage(sc, shared, facts, measured, f)
            if f
            else derive_usage(
                {**sc, "groups_per_month": 0, "web_page_loads_per_month": 0},
                shared, facts, measured, 1.0,
            )
        )
        peak_rps = max(2, math.ceil(u["api_requests"] / (30 * 24 * 3600) * 20))
        nodes = math.ceil(peak_rps / cap["sustained_rps_per_node"]) + cap["redundancy_nodes"]
        a, c = aws_serverless(u, prices, shared), onprem(op, nodes)
        sens.append({"scale": f, "aws_payable_usd": round(total(a), 2),
                     "aws_list_usd": round(total(a, "gross_usd"), 2),
                     "onprem_usd": round(total(c), 2), "nodes": nodes,
                     "searches": round(u["searches"])})
        label = "idle (no users)" if f == 0 else f"x{f:g}"
        md.append(f"| {label} | {total(a):.2f} | {total(a, 'gross_usd'):.2f} | {total(c):.2f} | {nodes} |")
    result["sensitivity"] = sens
    md += ["", "Idle row: no users at all for a month — the serverless cost that remains is "
               "Secrets Manager, CloudWatch and DynamoDB PITR, not compute.", ""]

    EVIDENCE.mkdir(exist_ok=True)
    (EVIDENCE / f"cost_model_{stamp}.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8")
    md_text = "\n".join(md)
    (EVIDENCE / f"cost_model_{stamp}.md").write_text(md_text, encoding="utf-8")

    csv_rows = ["scenario,option,line_item,driver,list_price_usd,free_tier_usd,payable_usd"]
    for key, s in result["scenarios"].items():
        for opt in ("aws_serverless", "aws_always_on_vm", "on_premise"):
            for r in s[opt]["lines"]:
                item = r["service"].replace(",", ";")
                drv = r["driver"].replace(",", ";")
                csv_rows.append(
                    f"{key},{opt},{item},{drv},{r['gross_usd']},{r['free_tier_usd']},{r['net_usd']}")
    (EVIDENCE / f"cost_model_{stamp}.csv").write_text("\n".join(csv_rows) + "\n", encoding="utf-8")

    print(f"wrote evidence/cost_model_{stamp}.{{md,json,csv}}")
    for key, s in result["scenarios"].items():
        print(f"  {s['label']}: serverless payable US${s['aws_serverless']['payable_usd']:.2f}/mo "
              f"(list US${s['aws_serverless']['list_price_usd']:.2f}), "
              f"VM US${s['aws_always_on_vm']['payable_usd']:.2f}, "
              f"on-prem US${s['on_premise']['payable_usd']:.2f}")
    if args.echo:
        print()
        print(md_text)


if __name__ == "__main__":
    main()
