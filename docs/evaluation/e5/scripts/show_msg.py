#!/usr/bin/env python3
"""Print an SQS receive-message result, or emit receipt handles tagged ours/other."""
import json, sys

path = sys.argv[1]
try:
    data = json.load(open(path))
except Exception:
    sys.exit(0)
messages = data.get("Messages") or []

if "--handles" in sys.argv:
    mark = sys.argv[sys.argv.index("--handles") + 1]
    for m in messages:
        print(m["ReceiptHandle"], "ours" if mark in m.get("Body", "") else "other")
    sys.exit(0)

if not messages:
    print("no message visible (a lease may be holding it)")
    sys.exit(0)
m = messages[0]
a = m.get("Attributes", {})
print("receiveCount :", a.get("ApproximateReceiveCount"))
print("firstReceive :", a.get("ApproximateFirstReceiveTimestamp"))
print("sent         :", a.get("SentTimestamp"))
try:
    print("body         :", json.dumps(json.loads(m["Body"]), indent=2))
except Exception:
    print("body         :", m["Body"][:500])
