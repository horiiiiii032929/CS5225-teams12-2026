#!/usr/bin/env python3
"""Issue #15 — 用真的 OneMap 驗證 worker 的 routing client。

跟 #3 的可行性腳本不同:**這支不自己寫 HTTP**,而是直接呼叫
`services/api/src/flatsplit_api/routing.py` ——也就是部署上去的那份程式碼。
目的是回答「worker 真的打得出去、分類真的對得上」,而不是「OneMap 能不能用」
(後者 #3 已經答過了)。

兩段:

1. **配對**:#3 用過的 8 個鎮 → Kent Ridge,次一個工作日 08:30。
   跟 `docs/evaluation/feasibility/evidence/feasibility_20261011T103939Z.json`
   的 `routing.rows` 可以逐列對照(#3 當時 8/8、14.5–58.3 分)。
   同時記下 `itineraries` 與 `shortestWasFirst` ——#6 發現 numItineraries=1
   在 1/8 的配對會漏掉最短路線,所以「上游第一條是否最短」要持續量。
2. **錯誤分類**:拿 #3 已經記錄過會固定出現的四種輸入,加上一個壞 token,
   確認每一種真的落到 routing.py 說的那個例外類別:

   | 探針 | 預期 HTTP | 預期類別 |
   | --- | --- | --- |
   | 起訖點相同 | 404 | RoutingUnroutable / NO_ROUTE |
   | 座標在新加坡境外 | 400 | RoutingRejected / INVALID_ROUTE_REQUEST |
   | 日期在一年前 | 400 | RoutingRejected / INVALID_ROUTE_REQUEST |
   | 簽章錯誤的 token | 401/403 | RoutingCredential / CREDENTIAL_UNAVAILABLE |

   404 那條最重要:它必須是 terminal,而且**絕對不能變成 0 分鐘**(D06)。

   深夜 03:00 另外列為**只記錄不判定**的探針:#3 在 2026-10-11 量到 404,
   但 2026-10-20 這支量到的是一條 182.6 分鐘的過夜行程(見
   `raw/2026-10-20/live_routing_20261020T085658Z.json`)。上游改了,
   所以它不再是穩定的 404 來源;留著是因為它證明「深夜會回傳一條很長但有效的
   路線」,而 worker 永遠在 08:30 路由,不受這件事影響。

token 從環境或 `--env-file` 讀,**永遠不會寫進輸出**:只留 SHA-256 前 12 碼
指紋、JWT 的 user_id 與剩餘時數,跟 #3 的慣例一致。

跑法(repo root):
    ONEMAP_TOKEN=... python3 docs/evaluation/worker-routing/scripts/verify_live_routing.py
    python3 docs/evaluation/worker-routing/scripts/verify_live_routing.py --env-file ../issue3/.env
    python3 docs/evaluation/worker-routing/scripts/verify_live_routing.py --skip-probes
"""

import argparse
import base64
import hashlib
import json
import os
import pathlib
import re
import statistics
import sys
import time
from datetime import UTC, date, datetime, timedelta

SCRIPT_VERSION = "1.0.0"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "services" / "api" / "src"))

from flatsplit_api import routing  # noqa: E402
from flatsplit_api.routing import (  # noqa: E402
    RoutingCredential,
    RoutingError,
    RoutingRejected,
    RoutingUnroutable,
)

#: #3 量過的那 8 個鎮,照原順序,方便逐列對照。
SAMPLE_TOWNS = [
    "ANG MO KIO",
    "TAMPINES",
    "WOODLANDS",
    "JURONG WEST",
    "CLEMENTI",
    "PUNGGOL",
    "BEDOK",
    "YISHUN",
]
#: #3 的目的地:Kent Ridge(合約的 stationKey 與釘住的座標)。
DESTINATION = {"stationKey": "KENT_RIDGE", "lat": 1.2936, "lng": 103.7845}
#: 配對之間的間隔。3 併發 × p50 861ms ≈ 209/min,手跑更慢,離 300/min 很遠。
PACING_SECONDS = 0.5
#: #3 的 routing 延遲基準(ms),用來說明這次是快還是慢。
ISSUE3_LATENCY_MS = {"n": 8, "min": 109, "p50": 140, "p95": 233, "max": 233}
EXPECTED = {
    "RoutingUnroutable": "NO_ROUTE",
    "RoutingRejected": "INVALID_ROUTE_REQUEST",
    "RoutingCredential": "CREDENTIAL_UNAVAILABLE",
    "RoutingRetryable": "ROUTING_UNAVAILABLE",
}


def load_token(env_file):
    """環境變數優先,其次 --env-file。回傳的 token 不會進輸出。"""
    token = os.environ.get("ONEMAP_TOKEN", "").strip()
    if token:
        return token
    if env_file is None:
        sys.exit("沒有 token:設 ONEMAP_TOKEN 或給 --env-file")
    text = pathlib.Path(env_file).expanduser().read_text(encoding="utf-8")
    found = re.search(r'^\s*ONEMAP_TOKEN\s*=\s*"?([A-Za-z0-9._-]+)"?', text, re.M)
    if found is None:
        sys.exit(f"{env_file} 裡沒有 ONEMAP_TOKEN")
    return found.group(1)


def token_identity(token):
    """只留可追溯、但無法還原 token 的欄位。"""
    claims = {}
    parts = token.split(".")
    if len(parts) == 3:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        try:
            claims = json.loads(base64.urlsafe_b64decode(padded))
        except Exception:
            claims = {}
    left = routing.token_seconds_left(token)
    return {
        "fingerprint": hashlib.sha256(token.encode()).hexdigest()[:12],
        "userId": claims.get("user_id"),
        "hoursLeft": None if left is None else round(left / 3600, 1),
    }


def next_weekday(today):
    """跟 commute_jobs._routing_date 同一條規則:次一個工作日。"""
    day = today + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.isoformat()


def town_points():
    path = REPO_ROOT / "services" / "api" / "src" / "flatsplit_api" / "towns.json"
    return json.loads(path.read_text(encoding="utf-8"))


def measured(call):
    """跑一次,回傳 (結果或例外, 毫秒)。"""
    started = time.monotonic()
    try:
        return call(), round((time.monotonic() - started) * 1000)
    except RoutingError as exc:
        return exc, round((time.monotonic() - started) * 1000)


def classify(outcome):
    """例外 → 類別名與 routing.py 存進 cache 的 error 代碼。"""
    name = type(outcome).__name__
    return {"outcome": name, "errorCode": outcome.code, "message": str(outcome)}


def route_pairs(towns, routing_date, routing_time):
    points = town_points()
    rows = []
    for town in towns:
        point = points.get(town)
        if point is None:
            rows.append({"town": town, "status": "skipped", "note": "towns.json 沒有這個鎮"})
            continue
        if point.get("routable") is False:
            # TENGAH 之類:producer 本地就判 unavailable,不會進 queue。
            rows.append({"town": town, "status": "skipped", "note": "producer 本地判不可路由"})
            continue
        origin = {"lat": point["lat"], "lng": point["lon"]}
        outcome, elapsed_ms = measured(
            lambda: routing.route(
                origin,
                DESTINATION,
                routing_date=routing_date,
                routing_time=routing_time,
            )
        )
        row = {
            "town": town,
            "stationKey": point["stationKey"],
            "origin": origin,
            "elapsedMs": elapsed_ms,
        }
        if isinstance(outcome, RoutingError):
            rows.append({**row, "status": "failed", **classify(outcome)})
        else:
            rows.append(
                {
                    **row,
                    "status": "ok",
                    "minutes": outcome.minutes,
                    "transfers": outcome.transfers,
                    "walkMinutes": outcome.walk_minutes,
                    "itineraries": outcome.itineraries,
                    "shortestWasFirst": outcome.shortest_was_first,
                }
            )
        time.sleep(PACING_SECONDS)
    return rows


def failure_probes(routing_date, routing_time, token):
    """每個探針都要落到預期的例外類別,不然 verdict 就不是 PASS。"""
    kent_ridge = dict(DESTINATION)
    cases = [
        {
            "case": "起訖點相同",
            "expect": RoutingUnroutable,
            "call": lambda: routing.route(
                kent_ridge,
                kent_ridge,
                routing_date=routing_date,
                routing_time=routing_time,
            ),
        },
        {
            # 只記錄不判定:#3 的 404 在 2026-10-20 已經不重現(見模組 docstring)。
            "case": "深夜 03:00",
            "expect": None,
            "call": lambda: routing.route(
                {"lat": 1.369933, "lng": 103.849558},
                kent_ridge,
                routing_date=routing_date,
                routing_time="03:00:00",
            ),
        },
        {
            "case": "座標在新加坡境外(吉隆坡)",
            "expect": RoutingRejected,
            "call": lambda: routing.route(
                {"lat": 3.139003, "lng": 101.686855},
                kent_ridge,
                routing_date=routing_date,
                routing_time=routing_time,
            ),
        },
        {
            "case": "日期在一年前",
            "expect": RoutingRejected,
            "call": lambda: routing.route(
                {"lat": 1.369933, "lng": 103.849558},
                kent_ridge,
                routing_date=(date.fromisoformat(routing_date) - timedelta(days=400)).isoformat(),
                routing_time=routing_time,
            ),
        },
    ]
    rows = []
    for case in cases:
        outcome, elapsed_ms = measured(case["call"])
        expect = case["expect"]
        rows.append(
            {
                "case": case["case"],
                "expectedOutcome": None if expect is None else expect.__name__,
                "expectedErrorCode": None if expect is None else EXPECTED[expect.__name__],
                "elapsedMs": elapsed_ms,
                **(
                    classify(outcome)
                    if isinstance(outcome, RoutingError)
                    else {"outcome": "Route", "errorCode": None, "minutes": outcome.minutes}
                ),
                # None 代表「只記錄」:上游可能變,不拿它判 verdict。
                "asExpected": None if expect is None else isinstance(outcome, expect),
            }
        )
        time.sleep(PACING_SECONDS)

    # 壞 token:exp 給未來的,好讓 routing.py 的到期前置檢查放行,
    # 真正擋下來的必須是 OneMap 的 401/403。
    header, payload, _ = token.split(".")
    broken = f"{header}.{payload}.{'A' * 32}"
    os.environ["ONEMAP_TOKEN"] = broken
    try:
        outcome, elapsed_ms = measured(
            lambda: routing.route(
                {"lat": 1.369933, "lng": 103.849558},
                kent_ridge,
                routing_date=routing_date,
                routing_time=routing_time,
            )
        )
    finally:
        os.environ["ONEMAP_TOKEN"] = token
    rows.append(
        {
            "case": "簽章錯誤的 token",
            "expectedOutcome": "RoutingCredential",
            "expectedErrorCode": EXPECTED["RoutingCredential"],
            "elapsedMs": elapsed_ms,
            **(
                classify(outcome)
                if isinstance(outcome, RoutingError)
                else {"outcome": "Route", "errorCode": None, "minutes": outcome.minutes}
            ),
            "asExpected": isinstance(outcome, RoutingCredential),
        }
    )
    return rows


def latency(rows):
    samples = sorted(row["elapsedMs"] for row in rows if row.get("status") == "ok")
    if not samples:
        return None
    return {
        "n": len(samples),
        "min": samples[0],
        "p50": round(statistics.median(samples)),
        "p95": samples[min(len(samples) - 1, int(0.95 * (len(samples) - 1)))],
        "max": samples[-1],
    }


def main():
    parser = argparse.ArgumentParser(description="#15 worker routing 的真機驗證")
    parser.add_argument("--env-file", help="讀 ONEMAP_TOKEN 的 .env(不會被輸出)")
    parser.add_argument(
        "--out",
        default=None,
        help="輸出目錄,預設 docs/evaluation/worker-routing/raw/<今天>/",
    )
    parser.add_argument("--towns", nargs="*", default=SAMPLE_TOWNS)
    parser.add_argument("--time", default="08:30:00", dest="routing_time")
    parser.add_argument("--date", default=None, dest="routing_date")
    parser.add_argument("--skip-probes", action="store_true", help="只跑配對,不跑錯誤分類")
    args = parser.parse_args()

    token = load_token(args.env_file)
    os.environ["ONEMAP_TOKEN"] = token
    identity = token_identity(token)
    if identity["hoursLeft"] is not None and identity["hoursLeft"] <= 0:
        sys.exit("token 已過期,先換 secret 再跑")

    run_at = datetime.now(UTC)
    routing_date = args.routing_date or next_weekday(run_at.date())
    pairs = route_pairs(args.towns, routing_date, args.routing_time)
    probes = [] if args.skip_probes else failure_probes(routing_date, args.routing_time, token)

    routed = [row for row in pairs if row["status"] == "ok"]
    attempted = [row for row in pairs if row["status"] != "skipped"]
    summary = {
        "script": pathlib.Path(__file__).name,
        "scriptVersion": SCRIPT_VERSION,
        "issue": 15,
        "module": "services/api/src/flatsplit_api/routing.py",
        "source": routing.SOURCE,
        "runAt": run_at.isoformat(),
        "token": identity,
        "request": {
            "destination": DESTINATION,
            "routingDate": routing_date,
            "routingTime": args.routing_time,
            "numItineraries": routing.ITINERARIES,
            "maxWalkDistance": routing.MAX_WALK_METRES,
        },
        "pairs": {
            "rows": pairs,
            "coverage": f"{len(routed)}/{len(attempted)}",
            "minutesRange": (
                [min(r["minutes"] for r in routed), max(r["minutes"] for r in routed)]
                if routed
                else None
            ),
            "shortestWasFirst": sum(1 for r in routed if r["shortestWasFirst"]),
            "latencyMs": latency(pairs),
            "issue3LatencyMs": ISSUE3_LATENCY_MS,
        },
        "failureProbes": {
            "rows": probes,
            "allAsExpected": (
                all(row["asExpected"] for row in probes if row["asExpected"] is not None)
                if probes
                else None
            ),
        },
    }
    summary["verdict"] = (
        "PASS"
        if routed
        and len(routed) == len(attempted)
        and (args.skip_probes or summary["failureProbes"]["allAsExpected"])
        else "FAIL"
    )

    out_dir = pathlib.Path(
        args.out
        or REPO_ROOT
        / "docs"
        / "evaluation"
        / "worker-routing"
        / "raw"
        / run_at.date().isoformat()
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = run_at.strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"live_routing_{stamp}.json"
    path.write_text(
        json.dumps(summary, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"verdict: {summary['verdict']}  coverage: {summary['pairs']['coverage']}")
    for row in pairs:
        if row["status"] == "ok":
            print(
                f"  {row['town']:<12} {row['minutes']:>6} min  "
                f"transfers={row['transfers']}  itineraries={row['itineraries']}  "
                f"shortestWasFirst={row['shortestWasFirst']}  {row['elapsedMs']}ms"
            )
        else:
            print(f"  {row['town']:<12} {row['status']}  {row.get('errorCode') or row.get('note')}")
    for row in probes:
        mark = {True: "ok ", False: "BAD", None: "fyi"}[row["asExpected"]]
        print(f"  [{mark}] {row['case']:<24} → {row['outcome']} / {row['errorCode']}")
    print(f"written: {path.relative_to(REPO_ROOT)}")
    return 0 if summary["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
