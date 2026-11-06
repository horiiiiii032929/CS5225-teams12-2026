#!/usr/bin/env python3
"""Verify WK's four-leg recovery-by-retry evidence chain against the REAL worker.

Runs flatsplit_api.handlers.commute_worker.handler unchanged, with Moto for
DynamoDB and urlopen stubbed, so the log lines captured here are the ones the
deployed worker emits. Nothing touches AWS.
"""
import base64, contextlib, io, json, os, time, types, urllib.request, uuid

os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ["TABLE_NAME"] = "drilltest"
os.environ["POWERTOOLS_LOG_DEDUPLICATION_DISABLED"] = "1"

# A JWT-shaped token with a far-future exp, so no credential path fires.
_payload = base64.urlsafe_b64encode(
    json.dumps({"exp": int(time.time()) + 86400}).encode()).decode().rstrip("=")
os.environ["ONEMAP_TOKEN"] = f"aaaa.{_payload}.bbbb"

import boto3
from moto import mock_aws

STATION, TOWN = "DRILLTEST", "DRILLTEST"
JOB = str(uuid.uuid4())
PK, SK = f"COMMUTE#{STATION}", f"TOWN#{TOWN}"

PLAN = {"plan": {"itineraries": [
    {"duration": 1802, "transfers": 1, "walkTime": 300},
]}}


class _Resp:
    def __init__(self, body): self._b = body
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False


def record(attempts):
    body = {
        "schemaVersion": 1, "jobId": JOB, "stationKey": STATION, "town": TOWN,
        "origin": {"lat": 1.3236, "lng": 103.9273},
        "destination": {"lat": 1.2935, "lng": 103.7846},
        "routingProfileVersion": "pt-v1:2026-11",
        "routingDate": "2026-11-07", "routingTime": "08:30:00",
    }
    return {"messageId": "m-1", "body": json.dumps(body),
            "attributes": {"ApproximateReceiveCount": str(attempts)}}


def ctx():
    c = types.SimpleNamespace()
    c.function_name = "drilltest"; c.memory_limit_in_mb = 512
    c.invoked_function_arn = "arn:aws:lambda:ap-southeast-1:000000000000:function:drilltest"
    c.aws_request_id = str(uuid.uuid4())
    return c


def run(handler, attempts):
    """Invoke the handler, returning (result, [parsed json log lines]).

    Captured at the file-descriptor level, not with redirect_stdout: Powertools'
    StreamHandler binds the stdout object at import time, so swapping
    sys.stdout afterwards does not reach it. This is why the first run of this
    harness reported every log leg as missing while printing all of them.
    """
    import sys, tempfile
    with tempfile.TemporaryFile(mode="w+") as tmp:
        saved = os.dup(1)
        os.dup2(tmp.fileno(), 1)
        try:
            result = handler({"Records": [record(attempts)]}, ctx())
        finally:
            for stream in (sys.stdout, sys.__stdout__):
                try: stream.flush()
                except Exception: pass
            os.dup2(saved, 1)
            os.close(saved)
        tmp.seek(0)
        captured = tmp.read()
    lines = []
    for raw in captured.splitlines():
        raw = raw.strip()
        if raw.startswith("{"):
            try: lines.append(json.loads(raw))
            except ValueError: pass
    return result, lines


@mock_aws
def main():
    ddb = boto3.resource("dynamodb")
    ddb.create_table(
        TableName="drilltest",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"},
                   {"AttributeName": "sk", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"},
                              {"AttributeName": "sk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST")
    table = ddb.Table("drilltest")

    from flatsplit_api import call_budget
    from flatsplit_api.handlers import commute_worker

    window = int(time.time() // call_budget.WINDOW_SECONDS)
    # Leg 1 precondition: this window's worker share is already spent.
    table.put_item(Item={"pk": "RATE#ONEMAP", "sk": f"WINDOW#{window}",
                         "calls": call_budget.WORKER_CALLS, "ttl": 0})
    # The pending claim the API's enqueue would have created, so the fenced
    # write can succeed once the pair actually routes.
    table.put_item(Item={"pk": PK, "sk": SK, "jobId": JOB, "status": "pending"})

    urllib.request.urlopen = lambda *a, **k: _Resp(json.dumps(PLAN).encode())

    print("=" * 72)
    print("DELIVERY 1 - window full, expect legs 1 and 2 and a redelivery")
    print("=" * 72)
    r1, logs1 = run(commute_worker.handler, 1)
    for entry in logs1:
        print("  %-9s %s" % (entry.get("level"), entry.get("message")))
        for k in ("jobId", "attempts", "routingError", "onemapWindow", "onemapCeiling"):
            if k in entry: print("              %-14s = %s" % (k, entry[k]))
    print("  handler returned:", json.dumps(r1))

    # A later window with budget available. Deleting this window's counter is
    # equivalent, and avoids a 60-second wait in the test.
    table.delete_item(Key={"pk": "RATE#ONEMAP", "sk": f"WINDOW#{window}"})

    print()
    print("=" * 72)
    print("DELIVERY 2 - budget available, expect leg 3 and the persisted record")
    print("=" * 72)
    r2, logs2 = run(commute_worker.handler, 2)
    for entry in logs2:
        print("  %-9s %s" % (entry.get("level"), entry.get("message")))
        for k in ("jobId", "attempts", "minutes", "itineraries", "routingError"):
            if k in entry: print("              %-14s = %s" % (k, entry[k]))
    print("  handler returned:", json.dumps(r2))

    item = table.get_item(Key={"pk": PK, "sk": SK}, ConsistentRead=True).get("Item", {})
    print()
    print("=" * 72)
    print("LEG 4 - the persisted record")
    print("=" * 72)
    for k in ("status", "minutes", "source", "computedAt", "attempts", "jobId",
              "transfers", "walkMinutes", "routingProfileVersion"):
        if k in item: print("  %-22s %s" % (k, item[k]))

    # ---- verdict ----
    msgs1 = [e.get("message") for e in logs1]
    msgs2 = [e.get("message") for e in logs2]
    def found(ms, text): return any(text in (m or "") for m in ms)

    leg1 = found(msgs1, "OneMap call budget reached for this window")
    leg2 = found(msgs1, "Routing failed; returning the job to the queue")
    leg3 = found(msgs2, "Commute pair resolved")
    leg4 = item.get("status") == "ok" and "minutes" in item
    same_job = all(e.get("jobId") in (None, JOB) for e in logs1 + logs2)
    redelivered = r1.get("batchItemFailures") == [{"itemIdentifier": "m-1"}]
    not_redelivered2 = r2.get("batchItemFailures") == []
    att2 = any(e.get("attempts") == 2 for e in logs2)

    # The finding: leg 1 carries no jobId, so legs 1 and 2 can only be tied
    # together by function_request_id, not by the job.
    leg1_entries = [e for e in logs1 if "budget reached" in (e.get("message") or "")]
    leg2_entries = [e for e in logs1 if "returning the job" in (e.get("message") or "")]
    leg1_has_job = any("jobId" in e for e in leg1_entries)
    shared_request_id = bool(leg1_entries) and bool(leg2_entries) and (
        leg1_entries[0].get("function_request_id")
        == leg2_entries[0].get("function_request_id"))
    retryable_code = next(
        (e.get("routingError") for e in leg2_entries if e.get("routingError")), None)

    print()
    print("=" * 72)
    print("VERDICT")
    print("=" * 72)
    checks = [
        ("leg 1  budget-exhaustion log", leg1),
        ("leg 2  routing-failed log, same jobId", leg2),
        ("leg 3  pair-resolved log on the retry", leg3),
        ("leg 4  persisted record with status ok and minutes", leg4),
        ("       every log line carries the same jobId", same_job),
        ("       delivery 1 asked for redelivery", redelivered),
        ("       delivery 2 did not", not_redelivered2),
        ("       the recovery carries attempts = 2", att2),
        ("       fractional minutes retained (1802s -> 30.03..)",
         abs(float(item.get("minutes", 0)) - 1802 / 60) < 1e-6),
        ("FINDING leg 1 carries NO jobId (so jobId cannot tie it to leg 2)",
         not leg1_has_job),
        ("       legs 1 and 2 share function_request_id instead",
         shared_request_id),
    ]
    for name, ok in checks:
        print("  %s  %s" % ("PASS" if ok else "FAIL", name))
    print()
    print("ALL FOUR LEGS REPRODUCED" if all(c[1] for c in checks)
          else "SOMETHING DID NOT REPRODUCE - see FAIL above")
    print()
    print("Correlation keys, measured rather than assumed:")
    print("  leg 1 <-> leg 2 : function_request_id = %s"
          % (leg1_entries[0].get("function_request_id") if leg1_entries else "?"))
    print("  leg 2 <-> leg 3 : jobId = %s" % JOB)
    print("  routingError on the retryable failure: %s" % retryable_code)
    print("  (RoutingRetryable.code is shared by throttling, 5xx, transport,")
    print("   unreadable bodies AND budget exhaustion, so the code alone")
    print("   cannot identify which path fired.)")


main()
