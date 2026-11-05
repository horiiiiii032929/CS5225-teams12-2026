#!/usr/bin/env python3
"""Issue #19 — 路線覆蓋率與「吸附站 vs 精確地址」誤差。

對應 #19 的驗收條件：

  1. 針對代表性的鎮與目的地回報覆蓋率
  2. 缺失路線標記為 unavailable；搜尋誠實降級並可重試

同時產出評估實驗 **E8**（「我們的數字可不可信」）要的證據：
以地鐵站代表目的地，和用精確地址相比差幾分鐘。

目的地預設來自 **#30 已審閱的目的地清單** `tools/load/destinations.json`：
每一筆都有審過的 label、完整地址與釘好的 stationKey。這取代了 v1.0.0 用
搜尋字串當目的地的做法——那個做法讓 SIT 解析成 DigiPen、Tampines Hub 解析
成社會服務中心，所以 10/14 那次 20×20 不能算完成的稽核。舊行為保留在
`--legacy-queries` 底下，讓既有證據仍可重現。

跑法：
    python3 scripts/measure_route_coverage.py                  # 預設 8 鎮 × 5 目的地
    python3 scripts/measure_route_coverage.py --full           # 全部鎮 × 全部目的地
    python3 scripts/measure_route_coverage.py --towns 5 --dests 3
    python3 scripts/measure_route_coverage.py --full --legacy-queries   # v1.0.0 的清單
"""

import argparse
import json
import math
import pathlib
import statistics
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from onemap import OneMapClient, TOWNS, TOWN_COORDS  # noqa: E402
from onemap.config import load_token  # noqa: E402
from onemap.errors import NoRouteFound, OneMapError  # noqa: E402

SCRIPT_VERSION = "1.1.0"

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
REVIEWED_CATALOG = REPO_ROOT / "tools/load/destinations.json"

# v1.0.0 的暫定清單，只在 --legacy-queries 下使用。
# 評估計畫 W1 的「30 個常見目的地」代表樣本
DESTINATIONS = [
    "National University of Singapore",
    "Nanyang Technological University",
    "Raffles Place MRT Station",
    "Changi Business Park",
    "one-north MRT Station",
    "Singapore Management University",
    "Mapletree Business City",
    "Singapore General Hospital",
    # 擴充到 20 個（E8 要求 "Sample of 20 towns and 20 destinations"）。
    # 類別依 W1 定義：大學、CBD、商業園區，另補區域中心。
    # 暫定清單 —— 評估計畫說正式的 30 個目的地要由 tools/load/ 的種子腳本產生，
    # 那份清單落地後應取代這裡。
    "Singapore University of Technology and Design",
    "Singapore Institute of Technology",
    "Singapore University of Social Sciences",
    "Marina Bay Financial Centre",
    "Tanjong Pagar MRT Station",
    "Shenton Way",
    "International Business Park",
    "Singapore Science Park",
    "Paya Lebar Quarter",
    "Jurong East MRT Station",
    "Tampines Hub",
    "Woodlands MRT Station",
]


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def resolve_destinations(client, names):
    """每個目的地取得「精確座標」和「吸附後的地鐵站座標」。"""
    out = []
    for name in names:
        res = client.search(name)
        if not res["results"]:
            print(f"  ✗ {name}: 查無地點")
            continue
        top = res["results"][0]
        lat, lon = float(top["LATITUDE"]), float(top["LONGITUDE"])
        stations, _ = client.nearest_mrt(lat, lon, radius_m=2000)
        if not stations:
            print(f"  ✗ {name}: 2km 內沒有地鐵站")
            continue
        st = stations[0]
        walk = haversine_m(lat, lon, st["lat"], st["lon"])
        out.append({
            "name": name, "label": top["SEARCHVAL"],
            "exact": f"{lat},{lon}",
            "stationKey": st["stationKey"], "codes": st["codes"],
            "station": f"{st['lat']},{st['lon']}",
            "walkMetres": round(walk),
        })
        print(f"  ✓ {name[:38]:38s} → {st['stationKey']:16s} "
              f"{st['codes']}  直線 {walk:.0f}m")
    return out


def load_reviewed_catalog(path):
    doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    entries = doc.get("destinations") or []
    if not entries:
        raise SystemExit(f"{path} 沒有 destinations")
    return doc, entries


def resolve_reviewed(client, entries):
    """用 #30 審過的地址做地理編碼，終點站用審過的 stationKey，不猜。

    與 `resolve_destinations()` 的差別就是 #55 記下的那個缺陷：那支拿使用者
    可能輸入的「查詢字串」當目的地，回傳的第一筆未必是想去的地方。這裡改用
    審閱過的完整地址，並且**要求**最近站清單裡出現審過的 stationKey；
    找不到就照實記 `stationPinned: false`，讓分歧看得見而不是被吃掉。
    """
    out = []
    for entry in entries:
        address = entry["address"]
        res = client.search(address)
        if not res["results"]:
            print(f"  ✗ {entry['alias']}: 地址查無結果")
            continue
        top = res["results"][0]
        lat, lon = float(top["LATITUDE"]), float(top["LONGITUDE"])
        stations, _ = client.nearest_mrt(lat, lon, radius_m=2500)
        if not stations:
            print(f"  ✗ {entry['alias']}: 2.5km 內沒有地鐵站")
            continue
        pinned = next(
            (s for s in stations if s["stationKey"] == entry["stationKey"]), None
        )
        st = pinned or stations[0]
        walk = haversine_m(lat, lon, st["lat"], st["lon"])
        geocoded_label = top.get("SEARCHVAL", "")
        out.append({
            "name": entry["label"], "alias": entry["alias"],
            "group": entry.get("group"),
            "label": geocoded_label,
            "reviewedLabel": entry["label"],
            "reviewedAddress": address,
            "reviewedStationKey": entry["stationKey"],
            "stationPinned": pinned is not None,
            "exact": f"{lat},{lon}",
            "stationKey": st["stationKey"], "codes": st["codes"],
            "station": f"{st['lat']},{st['lon']}",
            "walkMetres": round(walk),
        })
        flag = "" if pinned else f"  ⚠ 審定站 {entry['stationKey']} 不在最近站清單"
        print(f"  ✓ {entry['alias'][:22]:22s} → {st['stationKey']:16s} "
              f"{st['codes']}  直線 {walk:.0f}m{flag}")
    return out


def main():
    ap = argparse.ArgumentParser(description="Issue #19 覆蓋率與吸附誤差")
    ap.add_argument("--token")
    ap.add_argument("--towns", type=int, default=8, help="取幾個鎮（--full 時忽略）")
    ap.add_argument("--dests", type=int, default=5, help="取幾個目的地（--full 時忽略）")
    ap.add_argument("--full", action="store_true", help="全部鎮 × 全部目的地")
    ap.add_argument("--snap-towns", type=int, default=3,
                    help="精確地址 vs 吸附站要從幾個鎮量（預設 3）")
    ap.add_argument("--legacy-queries", action="store_true",
                    help="用 v1.0.0 的搜尋字串清單，而不是 #30 審過的目的地")
    ap.add_argument("--catalog", default=str(REVIEWED_CATALOG))
    ap.add_argument("--out", default="evidence")
    args = ap.parse_args()

    client = OneMapClient(load_token(args.token))
    towns = TOWNS if args.full else TOWNS[:args.towns]

    if args.legacy_queries:
        source = {"kind": "legacy-queries", "note":
                  "v1.0.0 的搜尋字串；標籤是查詢，不是審過的地點（#55）"}
        dest_names = DESTINATIONS if args.full else DESTINATIONS[:args.dests]
        planned = len(dest_names)
    else:
        catalog, entries = load_reviewed_catalog(args.catalog)
        if not args.full:
            entries = entries[:args.dests]
        source = {
            "kind": "reviewed-catalog",
            "file": str(pathlib.Path(args.catalog).relative_to(REPO_ROOT)),
            "version": catalog.get("version"),
            "reviewed": catalog.get("reviewed"),
        }
        planned = len(entries)

    print(f"Issue #19 覆蓋率量測 v{SCRIPT_VERSION}")
    print(f"  目的地來源：{source['kind']}")
    print(f"  {len(towns)} 鎮 × {planned} 目的地 = {len(towns)*planned} 組配對")
    print(f"  token 剩餘 {client.token_hours_left:.1f} 小時\n")

    print("[1] 解析目的地並吸附到地鐵站")
    if args.legacy_queries:
        dests = resolve_destinations(client, dest_names)
    else:
        dests = resolve_reviewed(client, entries)

    print(f"\n[2] 計算 {len(towns)*len(dests)} 組通勤（吸附站為終點）")
    pairs, unavailable, errors = [], [], []
    for town in towns:
        for dest in dests:
            try:
                route = client.route_pt(TOWN_COORDS[town], dest["station"])
                pairs.append({
                    "town": town, "destination": dest["name"],
                    "stationKey": dest["stationKey"], "status": "ok",
                    "minutes": route["minutes"], "transfers": route["transfers"],
                    "walkMetres": route["walkMetres"],
                })
            except NoRouteFound as exc:
                pairs.append({"town": town, "destination": dest["name"],
                              "stationKey": dest["stationKey"],
                              "status": "unavailable", "error": str(exc)})
                unavailable.append((town, dest["name"]))
            except OneMapError as exc:
                pairs.append({"town": town, "destination": dest["name"],
                              "stationKey": dest["stationKey"],
                              "status": "error", "error": str(exc),
                              "httpStatus": exc.status})
                errors.append((town, dest["name"], type(exc).__name__))
        ok = sum(1 for p in pairs if p["town"] == town and p["status"] == "ok")
        print(f"  {town:16s} {ok}/{len(dests)} 可達")

    probe_towns = towns[:max(1, args.snap_towns)]
    print(f"\n[3] 吸附站 vs 精確地址的誤差（實驗 E8），起點 {len(probe_towns)} 鎮")
    deltas = []
    for probe_town in probe_towns:
        for dest in dests:
            try:
                exact = client.route_pt(TOWN_COORDS[probe_town], dest["exact"])
                snapped = client.route_pt(TOWN_COORDS[probe_town], dest["station"])
                delta = snapped["minutes"] - exact["minutes"]
                deltas.append({
                    "fromTown": probe_town,
                    "destination": dest["name"], "stationKey": dest["stationKey"],
                    "exactMinutes": exact["minutes"],
                    "snappedMinutes": snapped["minutes"],
                    "deltaMinutes": round(delta, 1),
                    "walkMetres": dest["walkMetres"],
                })
                print(f"  {probe_town:14s} {dest['name'][:30]:30s} "
                      f"精確={exact['minutes']:5.1f}  吸附={snapped['minutes']:5.1f}  "
                      f"誤差={delta:+5.1f} min")
            except OneMapError as exc:
                print(f"  {probe_town:14s} {dest['name'][:30]:30s} "
                      f"{type(exc).__name__}: {exc}")

    total = len(pairs)
    ok_n = sum(1 for p in pairs if p["status"] == "ok")
    abs_deltas = [abs(d["deltaMinutes"]) for d in deltas]
    report = {
        "script": "measure_route_coverage.py", "version": SCRIPT_VERSION,
        "issue": 19, "experiment": "E8",
        "runAt": datetime.now(timezone.utc).isoformat(),
        "destinationSource": source,
        "routeBasis": {"date": "10-13-2026", "time": "08:30:00",
                       "mode": "TRANSIT", "note": "client defaults, unchanged"},
        "towns": towns, "destinations": dests,
        "snapProbeTowns": probe_towns,
        "stationPinMismatches": [
            d["alias"] for d in dests
            if d.get("stationPinned") is False
        ],
        "coverage": {
            "totalPairs": total, "ok": ok_n,
            "unavailable": len(unavailable), "errors": len(errors),
            "coveragePct": round(ok_n / total * 100, 1) if total else 0.0,
            "unavailablePairs": unavailable,
        },
        "snapError": {
            "rows": deltas,
            "medianAbsMinutes": round(statistics.median(abs_deltas), 1) if abs_deltas else None,
            "maxAbsMinutes": round(max(abs_deltas), 1) if abs_deltas else None,
        },
        "pairs": pairs,
        "clientStats": client.stats,
    }
    outdir = pathlib.Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = outdir / f"coverage_{stamp}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print("\n" + "=" * 70)
    print(f"覆蓋率：{ok_n}/{total} = {report['coverage']['coveragePct']}%  "
          f"(unavailable={len(unavailable)}, error={len(errors)})")
    if abs_deltas:
        print(f"吸附誤差：中位數 {report['snapError']['medianAbsMinutes']} min，"
              f"最大 {report['snapError']['maxAbsMinutes']} min")
    print(f"證據：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
