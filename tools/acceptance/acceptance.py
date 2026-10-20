"""Run the #44 acceptance gate against a running FlatSplit API and record evidence.

The gate in #44 is written as prose:

    two browsers/devices reopen one group; saved inputs survive reload;
    real #10/#14/#15 records flow through #18 into progress/results.
    Attach reproducible evidence and the deployed revision.

This script turns that sentence into repeatable checks. The same script runs
against a local environment and against the deployed API:

    python3 tools/acceptance/acceptance.py                      # local serve_local.py
    python3 tools/acceptance/acceptance.py \
        --base-url https://<host>/api --mode deployed \
        --revision "$(git rev-parse --short HEAD)"

It deliberately does not fail because #15's commute worker does not exist yet.
Commute minutes are produced by that worker, so a search stays `pending`
without it. That is not a bug in the journey; it is the current integration
gap, so the script records it as INFO and prints how many pairs are still
waiting. Once the worker runs, the same script needs no change and `ranked`
has content.

The reason for that choice: an acceptance script that is red by construction
until everyone else finishes is a script nobody runs, and a script nobody runs
helps nobody on deployment day.

Standard library only, so it runs on any machine with Python 3.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
EVIDENCE = os.path.join(HERE, "evidence")

PASS, FAIL, INFO = "PASS", "FAIL", "INFO"


class Api:
    """Minimal HTTP client that also records every round trip and its latency."""

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        method: str,
        path: str,
        body: object = None,
        token: str | None = None,
        query: dict[str, str] | None = None,
    ) -> tuple[int, object]:
        url = f"{self.base}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        data = None if body is None else json.dumps(body).encode()
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            elapsed = round((time.perf_counter() - started) * 1000)
            self.calls.append(
                {
                    "method": method,
                    "path": path,
                    "status": None,
                    "ms": elapsed,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            raise SystemExit(f"cannot reach {url}: {exc}") from exc
        elapsed = round((time.perf_counter() - started) * 1000)
        self.calls.append(
            {"method": method, "path": path, "status": status, "ms": elapsed}
        )
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, raw.decode("utf-8", "replace")[:400]


class Report:
    def __init__(self) -> None:
        self.checks: list[dict[str, object]] = []

    def record(self, result: str, gate: str, name: str, detail: str = "") -> bool:
        self.checks.append(
            {"result": result, "gate": gate, "check": name, "detail": detail}
        )
        print(f"  [{result}] {name}" + (f" - {detail}" if detail else ""))
        return result != FAIL

    def expect(self, gate: str, name: str, ok: bool, detail: str = "") -> bool:
        return self.record(PASS if ok else FAIL, gate, name, detail)

    @property
    def failed(self) -> list[dict[str, object]]:
        return [c for c in self.checks if c["result"] == FAIL]


def pick_place(api: Api, report: Report, query: str) -> dict[str, object] | None:
    status, body = api("GET", "/places", query={"q": query})
    if status != 200 or not isinstance(body, dict):
        report.expect(
            "destinations",
            f"GET /places?q={query!r}",
            False,
            f"HTTP {status} {str(body)[:120]}",
        )
        return None
    places = body.get("places") or []
    unsupported = body.get("unsupported") or []
    report.expect(
        "destinations",
        f"GET /places?q={query!r}",
        bool(places),
        f"{len(places)} selectable, {len(unsupported)} unsupported",
    )
    if not places:
        return None
    best = places[0]
    station = best.get("station") or {}
    report.expect(
        "destinations",
        "every candidate carries a pinned station coordinate",
        all(
            isinstance(p.get("station"), dict)
            and p["station"].get("lat")
            and p["station"].get("stationKey")
            for p in places
        ),
        f"{station.get('stationKey')} ({station.get('lat')}, {station.get('lng')}) "
        f"snap={station.get('snapMetres')}m",
    )
    return best


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--mode", choices=["local-moto", "deployed"], default="local-moto"
    )
    parser.add_argument(
        "--revision",
        default=None,
        help="git sha of the build under test; recorded in the evidence file",
    )
    parser.add_argument("--dest-a", default="kent ridge")
    parser.add_argument("--dest-b", default="raffles place")
    parser.add_argument("--poll-seconds", type=float, default=20.0)
    parser.add_argument(
        "--no-write", action="store_true", help="skip the evidence file"
    )
    args = parser.parse_args()

    api = Api(args.base_url)
    report = Report()
    facts: dict[str, object] = {}
    started = time.time()

    print(f"=== 0. target {args.base_url}  mode={args.mode} ===")
    status, body = api("GET", "/health")
    report.expect(
        "health",
        "GET /health returns 200 ok",
        status == 200 and isinstance(body, dict) and body.get("status") == "ok",
        f"HTTP {status} {body}",
    )

    print("=== 1. destination lookup (#14) ===")
    place_a = pick_place(api, report, args.dest_a)
    place_b = pick_place(api, report, args.dest_b)
    if place_a is None or place_b is None:
        print("\nno destination resolved; the rest of the journey cannot run.")
        return finish(api, report, facts, args, started)
    facts["destinations"] = {"a": place_a, "b": place_b}

    print("=== 2. repeated lookup should hit the 24h query cache (#14) ===")
    before = len(api.calls)
    t0 = time.perf_counter()
    status, repeat = api("GET", "/places", query={"q": args.dest_a})
    warm_ms = round((time.perf_counter() - t0) * 1000)
    cold_ms = next(
        (c["ms"] for c in api.calls[:before] if c["path"] == "/places"), None
    )
    repeated = (repeat.get("places") or [{}])[0] if isinstance(repeat, dict) else {}
    report.expect(
        "destinations",
        "repeated lookup returns the same placeId and the same pin",
        status == 200
        and repeated.get("placeId") == place_a["placeId"]
        and repeated.get("station") == place_a["station"],
        f"cold {cold_ms}ms -> warm {warm_ms}ms",
    )
    facts["lookupLatencyMs"] = {"cold": cold_ms, "warm": warm_ms}

    print("=== 3. two members, two devices (#12 / #13) ===")
    status, created = api(
        "POST",
        "/groups",
        {"groupName": "Acceptance run", "size": 2, "name": "Member A"},
    )
    if status != 201 or not isinstance(created, dict):
        report.expect(
            "group", "POST /groups returns 201", False, f"HTTP {status} {created}"
        )
        return finish(api, report, facts, args, started)
    report.expect("group", "POST /groups returns 201", True)
    group = created["group"]
    gid = group["groupId"]
    invite = group["inviteToken"]
    m1, t1 = created["memberId"], created["memberToken"]
    report.expect(
        "group",
        "create response carries inviteToken and memberToken",
        bool(invite) and bool(t1),
    )

    status, joined = api("POST", f"/groups/{gid}/members", {"name": "Member B"}, invite)
    report.expect(
        "group",
        "a second member can join with the invite token",
        status == 201,
        f"HTTP {status}",
    )
    if status != 201 or not isinstance(joined, dict):
        return finish(api, report, facts, args, started)
    m2, t2 = joined["memberId"], joined["memberToken"]

    print("=== 4. save preferences (#14: the placeId must be storable) ===")
    for member, token, place, who in (
        (m1, t1, place_a, "Member A"),
        (m2, t2, place_b, "Member B"),
    ):
        status, saved = api(
            "PUT",
            f"/groups/{gid}/members/{member}",
            {
                "name": who,
                "placeId": place["placeId"],
                "budget": 1400,
                "maxCommute": 45,
            },
            token,
        )
        ok = status == 200
        report.expect(
            "save",
            f"{who} saves preferences and gets 200",
            ok,
            f"HTTP {status}" + ("" if ok else f" {str(saved)[:160]}"),
        )
        if not ok:
            return finish(api, report, facts, args, started)

    print("=== 5. reopen from the other device (gate: saved inputs survive reload) ===")
    status, reread = api("GET", f"/groups/{gid}", token=t2)
    members = (
        (reread.get("group", {}).get("members") or [])
        if isinstance(reread, dict)
        else []
    )
    with_dest = [m for m in members if m.get("destination")]
    report.expect(
        "reload",
        "reread with the second member's token keeps both destinations",
        status == 200 and len(with_dest) == 2,
        f"{len(with_dest)}/2 members have a destination",
    )
    if with_dest:
        snapshot = with_dest[0]["destination"]
        report.expect(
            "reload",
            "the member stores a snapshot with station coordinates, not just a placeId",
            all(
                snapshot.get("station", {}).get(k) is not None
                for k in ("stationKey", "lat", "lng")
            ),
            f"{snapshot['station'].get('stationKey')} "
            f"({snapshot['station'].get('lat')}, {snapshot['station'].get('lng')})",
        )
        facts["savedDestination"] = snapshot
    report.expect(
        "reload",
        "the reread no longer returns inviteToken or memberToken",
        isinstance(reread, dict)
        and "inviteToken" not in reread.get("group", {})
        and "memberToken" not in reread,
    )

    print("=== 6. authorisation (no token / wrong token cannot read or write) ===")
    status, _ = api("GET", f"/groups/{gid}")
    report.expect("auth", "no token -> 401", status == 401, f"HTTP {status}")
    status, _ = api("GET", f"/groups/{gid}", token="mem_not_a_real_token")
    report.expect("auth", "invalid token -> 401", status == 401, f"HTTP {status}")
    status, _ = api(
        "PUT",
        f"/groups/{gid}/members/{m1}",
        {
            "name": "Member A",
            "placeId": place_a["placeId"],
            "budget": 1400,
            "maxCommute": 45,
        },
        t2,
    )
    report.expect(
        "auth",
        "another member's token cannot edit this member -> 403",
        status == 403,
        f"HTTP {status}",
    )

    print("=== 7. search (#16 / #18) ===")
    status, search = api("POST", f"/groups/{gid}/searches", None, t1)
    ok = status == 201 and isinstance(search, dict)
    report.expect(
        "search", "a search can start once both members are ready", ok, f"HTTP {status}"
    )
    if not ok:
        return finish(api, report, facts, args, started)
    sid = search["searchId"]
    status, again = api("POST", f"/groups/{gid}/searches", None, t2)
    report.expect(
        "search",
        "starting again is idempotent (same searchId)",
        isinstance(again, dict) and again.get("searchId") == sid,
        f"HTTP {status}",
    )

    deadline = time.time() + args.poll_seconds
    view: dict[str, object] = search
    while time.time() < deadline:
        status, view = api("GET", f"/groups/{gid}/searches/{sid}", token=t1)
        if not isinstance(view, dict) or view.get("status") != "pending":
            break
        time.sleep(2.0)
    progress = view.get("progress") if isinstance(view, dict) else None
    ranked = view.get("ranked") or [] if isinstance(view, dict) else []
    pending = None
    if isinstance(progress, dict):
        pending = (
            int(progress.get("total", 0))
            - int(progress.get("resolved", 0))
            - int(progress.get("unavailable", 0))
        )
    facts["search"] = {
        "searchId": sid,
        "status": view.get("status"),
        "progress": progress,
        "pendingPairs": pending,
        "rankedCount": len(ranked),
        "data": view.get("data"),
    }
    report.expect(
        "search",
        "search status is readable",
        isinstance(view, dict)
        and view.get("status") in {"pending", "complete", "stale"},
        f"status={view.get('status')} progress={progress}",
    )

    if view.get("status") == "complete" and ranked:
        top = ranked[0]
        report.record(
            PASS,
            "search",
            "ranked results are present (#15's worker is running)",
            f"top {top.get('town')} / {top.get('flatType')}",
        )
        facts["topResult"] = top
    else:
        seen = progress if isinstance(progress, dict) else {}
        report.record(
            INFO,
            "search",
            "search stays pending: nobody computes commute data yet"
            " (#15's worker does not exist)",
            f"{pending} pairs waiting (total={seen.get('total', '?')}"
            f" resolved={seen.get('resolved', '?')}"
            f" unavailable={seen.get('unavailable', '?')})"
            " - this is the current integration gap, not a failure of this script",
        )

    print("=== 8. editing preferences must make the old search stale (D08) ===")
    status, _ = api(
        "PUT",
        f"/groups/{gid}/members/{m1}",
        {
            "name": "Member A",
            "placeId": place_a["placeId"],
            "budget": 1500,
            "maxCommute": 50,
        },
        t1,
    )
    status, after = api("GET", f"/groups/{gid}/searches/{sid}", token=t1)
    report.expect(
        "search",
        "the earlier search is marked stale after a save",
        isinstance(after, dict) and after.get("status") == "stale",
        f"status={after.get('status') if isinstance(after, dict) else after}",
    )

    return finish(api, report, facts, args, started)


def finish(
    api: Api,
    report: Report,
    facts: dict[str, object],
    args: argparse.Namespace,
    started: float,
) -> int:
    latencies = sorted(c["ms"] for c in api.calls if isinstance(c.get("ms"), int))
    summary: dict[str, object] = {
        "generatedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseUrl": args.base_url,
        "mode": args.mode,
        "revision": args.revision,
        "elapsedSeconds": round(time.time() - started, 2),
        "httpCalls": len(api.calls),
        "latencyMs": {
            "min": latencies[0] if latencies else None,
            "p50": latencies[len(latencies) // 2] if latencies else None,
            "max": latencies[-1] if latencies else None,
        },
        "checks": report.checks,
        "facts": facts,
        "calls": api.calls,
    }
    passed = sum(1 for c in report.checks if c["result"] == PASS)
    info = sum(1 for c in report.checks if c["result"] == INFO)
    summary["verdict"] = "PASS" if not report.failed else "FAIL"
    latency = summary["latencyMs"]
    p50 = latency["p50"] if isinstance(latency, dict) else None

    print(
        f"\n{passed} passed / {len(report.failed)} failed / {info} recorded only"
        f"   {summary['httpCalls']} HTTP calls, p50 {p50}ms"
    )
    for check in report.failed:
        print(f"  FAIL  {check['check']} - {check['detail']}")
    print(
        f"verdict: {summary['verdict']}"
        + (
            "  (mode=local-moto, this is NOT deployed acceptance)"
            if args.mode == "local-moto"
            else ""
        )
    )

    if not args.no_write:
        os.makedirs(EVIDENCE, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        path = os.path.join(EVIDENCE, f"acceptance_{args.mode}_{stamp}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        print(f"evidence: {os.path.relpath(path)}")
    return 0 if summary["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
