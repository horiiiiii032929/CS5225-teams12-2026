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
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
EVIDENCE = os.path.join(HERE, "evidence")

PASS, FAIL, INFO = "PASS", "FAIL", "INFO"

#: Any key whose name folds to one of these carries a capability, wherever it
#: appears. The gate has to reject them at any depth, not only at the top of a
#: response: an issued token nested inside a member or a snapshot is just as
#: leaked, and this evidence file is meant to be attached to an issue.
CREDENTIAL_KEYS = frozenset(
    {
        "invitetoken",
        "membertoken",
        "token",
        "accesstoken",
        "refreshtoken",
        "authorization",
        "password",
        "secret",
        "apikey",
        "credentials",
    }
)
REDACTED = "<redacted>"


def finite(value: object) -> bool:
    """A real number, so 0.0 counts and None, True and NaN do not."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def station_pinned(place: object) -> bool:
    """A candidate carries a station key and both of its coordinates.

    Checking latitude alone passed a candidate whose `lng` had been removed,
    and a truthiness test would also pass a zero coordinate.
    """
    if not isinstance(place, dict):
        return False
    station = place.get("station")
    if not isinstance(station, dict):
        return False
    return (
        isinstance(station.get("stationKey"), str)
        and bool(station["stationKey"])
        and finite(station.get("lat"))
        and finite(station.get("lng"))
    )


def same_point(got: object, want: object) -> bool:
    """One coordinate that survived storage unchanged.

    A pin is written as a `Decimal` and read back as a float, so `==` is the
    wrong test; 1e-9 degrees is about a tenth of a millimetre, so anything a
    person would call a different place is still a mismatch. Finiteness alone
    was not a preservation test at all: Member B's (1.284, 103.8515) could be
    replaced with (8.12345, 111.12345) and the reload stage still passed.
    """
    if not (finite(got) and finite(want)):
        return False
    return abs(float(got) - float(want)) <= 1e-9  # type: ignore[arg-type]


def saved_mismatches(member: object, want: dict[str, object]) -> list[str]:
    """Every field of a saved preference the reread did not give back intact.

    Counting destinations was not enough: a reread that gave Member B Member
    A's destination, or lost B's budget and commute limit, satisfied "both
    have a destination". Neither was requiring finite coordinates, which any
    other finite pair also satisfies.
    """
    member = member if isinstance(member, dict) else {}
    snapshot = member.get("destination")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    station = snapshot.get("station")
    station = station if isinstance(station, dict) else {}
    place = want.get("place")
    place = place if isinstance(place, dict) else {}
    wanted = place.get("station")
    wanted = wanted if isinstance(wanted, dict) else {}

    mismatches: list[str] = []
    if snapshot.get("placeId") != place.get("placeId"):
        mismatches.append("placeId")
    if station.get("stationKey") != wanted.get("stationKey"):
        mismatches.append("stationKey")
    if not same_point(station.get("lat"), wanted.get("lat")):
        mismatches.append("station lat")
    if not same_point(station.get("lng"), wanted.get("lng")):
        mismatches.append("station lng")
    if member.get("budget") != want.get("budget"):
        mismatches.append("budget")
    if member.get("maxCommute") != want.get("maxCommute"):
        mismatches.append("maxCommute")
    return mismatches


def credential_fields(value: object, path: str = "") -> list[str]:
    """Every path in `value` whose key names a credential, at any depth."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            here = f"{path}.{key}" if path else str(key)
            if str(key).replace("_", "").replace("-", "").lower() in CREDENTIAL_KEYS:
                found.append(here)
            found += credential_fields(item, here)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found += credential_fields(item, f"{path}[{index}]")
    return found


def redact(value: object) -> object:
    """Copy `value` with every credential field replaced.

    Applied to anything API-derived before it is printed or written, because
    the evidence file is an attachment and stdout is pasted into issues.
    """
    if isinstance(value, dict):
        return {
            key: (
                REDACTED
                if str(key).replace("_", "").replace("-", "").lower() in CREDENTIAL_KEYS
                else redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def detail_of(body: object, limit: int = 160) -> str:
    """A short, redacted rendering of a response for a check's detail line.

    A failing response is still a response: the 500 body of a creation request
    carries the tokens it had already issued, and it used to reach stdout and
    the evidence file through the failure detail.
    """
    if isinstance(body, (dict, list)):
        text = json.dumps(redact(body), ensure_ascii=False, sort_keys=True)
    else:
        text = str(body)
    return text[:limit]


def shown(value: object, limit: int = 80) -> str:
    """One response-derived value, rendered for a detail line.

    A scalar prints as itself. Anything else is redacted first, because a
    malformed response can put a whole object where a count belonged:
    `progress.unavailable = {"memberToken": ...}` used to reach stdout and
    `checks[].detail` through an f-string, and the structural `redact` at the
    end cannot take a credential back out of a string.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return str(value)
    return detail_of(value, limit)


def pending_pairs(progress: object) -> int | None:
    """Pairs with no answer yet.

    `resolved` counts every pair that reached a terminal state, including the
    unavailable ones, so subtracting both double-counts them: it reported 50
    of 52 pending, then -2 once the pairs resolved and -54 when every route
    came back unavailable.
    """
    if not isinstance(progress, dict):
        return None
    total, resolved = progress.get("total"), progress.get("resolved")
    if not finite(total) or not finite(resolved):
        return None
    return int(total) - int(resolved)  # type: ignore[arg-type]


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

    def no_credentials(self, gate: str, name: str, body: object) -> bool:
        """Fail if an API response carries an issued credential at any depth.

        The detail names the paths and never the values, so a response shape
        that starts leaking is reported in evidence that is still safe to
        attach. A response the gate never inspects cannot be caught by the
        redaction at the end: `redact` rewrites structure, and a value already
        formatted into a detail string is past saving.
        """
        leaked = credential_fields(body)
        return self.expect(
            gate, name, not leaked, f"leaked: {leaked}" if leaked else ""
        )

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
            f"HTTP {status} {detail_of(body, 120)}",
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
    unpinned = [p.get("placeId") for p in places if not station_pinned(p)]
    report.expect(
        "destinations",
        "every candidate carries a station key and both coordinates",
        not unpinned,
        f"{shown(station.get('stationKey'))} "
        f"({shown(station.get('lat'))}, {shown(station.get('lng'))}) "
        f"snap={shown(station.get('snapMetres'))}m"
        + (f"; unpinned: {shown(unpinned)}" if unpinned else ""),
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
        f"HTTP {status} {detail_of(body)}",
    )

    print("=== 1. destination lookup (#14) ===")
    place_a = pick_place(api, report, args.dest_a)
    place_b = pick_place(api, report, args.dest_b)
    if place_a is None or place_b is None:
        print("\nno destination resolved; the rest of the journey cannot run.")
        return finish(api, report, facts, args, started)
    facts["destinations"] = {"a": redact(place_a), "b": redact(place_b)}

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
            "group",
            "POST /groups returns 201",
            False,
            f"HTTP {status} {detail_of(created)}",
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
            f"HTTP {status}" + ("" if ok else f" {detail_of(saved)}"),
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
    by_id = {m.get("memberId"): m for m in members if isinstance(m, dict)}
    # What each member saved in stage 4. Counting destinations was not enough:
    # a reread that gave Member B Member A's destination, or lost B's budget
    # and commute limit, satisfied "both have a destination".
    expected = {
        m1: {"name": "Member A", "place": place_a, "budget": 1400, "maxCommute": 45},
        m2: {"name": "Member B", "place": place_b, "budget": 1400, "maxCommute": 45},
    }
    ids_match = set(expected) <= set(by_id)
    report.expect(
        "reload",
        "the reread returns both members by id",
        status == 200 and ids_match,
        f"{len(by_id)} members, ids {'match' if ids_match else 'differ'}",
    )
    for member_id, want in expected.items():
        member = by_id.get(member_id) or {}
        snapshot = member.get("destination") if isinstance(member, dict) else None
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        station = snapshot.get("station")
        station = station if isinstance(station, dict) else {}
        # The pin has to be the one stage 1 handed out, not merely a pair of
        # numbers: swapping Member B's coordinates for another finite pair,
        # keeping placeId and stationKey, used to pass.
        mismatches = saved_mismatches(member, want)
        report.expect(
            "reload",
            f"{want['name']} reloads the destination and limits they saved",
            not mismatches,
            f"{shown(station.get('stationKey'))} "
            f"({shown(station.get('lat'))}, {shown(station.get('lng'))})"
            + (f"; wrong: {', '.join(mismatches)}" if mismatches else ""),
        )
        facts.setdefault("savedDestinations", {})[member_id] = redact(snapshot)  # type: ignore[index]
    report.no_credentials(
        "reload", "the reread carries no issued credential at any depth", reread
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
    excluded = view.get("excluded") or [] if isinstance(view, dict) else []
    pending = pending_pairs(progress)
    search_status = view.get("status") if isinstance(view, dict) else None
    facts["search"] = {
        "searchId": sid,
        "status": search_status,
        "progress": progress,
        "pendingPairs": pending,
        "rankedCount": len(ranked),
        "excludedCount": len(excluded),
        "data": redact(view.get("data") if isinstance(view, dict) else None),
    }
    report.expect(
        "search",
        "search status is readable",
        search_status in {"pending", "complete", "stale"},
        f"status={shown(search_status)} progress={detail_of(progress, 200)}",
    )
    # The search view was never inspected for credentials, and its raw
    # `progress` went into the detail line as it stood: an injected
    # `progress.memberToken` reached stdout and the evidence file and the run
    # still passed. Nothing a search returns should carry a capability.
    report.no_credentials(
        "search", "the search view carries no issued credential at any depth", view
    )

    # Branch on the status, not on "complete and ranked". Collapsing the rest
    # into one else reported a finished search whose towns were all excluded,
    # and a search that was already stale, as "nobody computes commute data".
    seen = progress if isinstance(progress, dict) else {}
    counts = (
        f"total={shown(seen.get('total', '?'))}"
        f" resolved={shown(seen.get('resolved', '?'))}"
        f" unavailable={shown(seen.get('unavailable', '?'))} pending={pending}"
    )
    if search_status == "complete" and ranked:
        top = ranked[0]
        report.record(
            PASS,
            "search",
            "ranked results are present (#15's worker is running)",
            f"top {shown(top.get('town'))} / {shown(top.get('flatType'))}; {counts}"
            if isinstance(top, dict)
            else f"{shown(top)}; {counts}",
        )
        facts["topResult"] = redact(top)
    elif search_status == "complete":
        reasons = sorted(
            {
                shown(r.get("code"), 40)
                for area in excluded
                if isinstance(area, dict)
                for r in (area.get("reasons") or [])
                if isinstance(r, dict)
            }
        )
        report.record(
            PASS,
            "search",
            "the search finished and every town was excluded, honestly",
            f"{len(excluded)} towns excluded, reasons {reasons or '[]'}; {counts}"
            " - a completed search with no feasible town is a real answer,"
            " not a missing worker",
        )
        facts["exclusionReasons"] = reasons
    elif search_status == "pending":
        report.record(
            INFO,
            "search",
            "search stays pending: nobody computes commute data yet"
            " (#15's worker is not deployed)",
            f"{pending} pairs waiting ({counts})"
            " - this is the current integration gap, not a failure of this script",
        )
    else:
        # Stage 8 makes a search stale on purpose. Arriving here already stale
        # means the staleness came from somewhere else, so neither this stage
        # nor stage 8 can be evaluated.
        report.expect(
            "search",
            "the search is not stale before stage 8 edits a preference",
            False,
            f"status={shown(search_status)}; {counts}",
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
        f"status={shown(after.get('status'))}"
        if isinstance(after, dict)
        else detail_of(after, 120),
    )
    report.no_credentials(
        "search", "the stale search view carries no issued credential", after
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
    # Last line of defence before stdout and the attachable file: a response
    # shape that changes, or a field nobody anticipated, must not leak a
    # capability into evidence that gets pasted into an issue.
    safe = redact(summary)
    assert isinstance(safe, dict)
    summary = safe
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
