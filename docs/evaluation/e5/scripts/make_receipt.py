#!/usr/bin/env python3
"""Turn the drill evidence directory into the #27 receipt body. Offline, no AWS."""
import json, os, sys

ev = sys.argv[1]
REV = "e2d3780e28028574f8ee3dd990c10257be9f8029"

def rd(name, as_json=True):
    p = os.path.join(ev, name)
    if not os.path.exists(p):
        return None
    text = open(p).read().strip()
    if not as_json:
        return text
    try:
        return json.loads(text)
    except Exception:
        return text

out = ["## #27 eval drill receipt", ""]
out.append("**Marker:** `%s`" % (rd("marker.txt", False) or "?"))
out.append("**Stage revision:** `%s`" % REV)
out.append("**Operator:** @lukerspace")
ident = rd("identity.json")
if isinstance(ident, dict):
    out.append("**Principal:** `%s` in account `%s`"
               % (ident.get("Arn", "?"), ident.get("Account", "?")))

out += ["", "### Phase A - unkeyable job to the DLQ", ""]
body = rd("injected_body.json")
if body:
    out += ["Injected body:", "", "```json", json.dumps(body, indent=2), "```", ""]
watch = rd("watch.log", False)
if watch:
    out += ["Queue depths over the session (`visible in-flight`):", "", "```", watch, "```", ""]
msg = rd("dlq_message.json")
if isinstance(msg, dict) and msg.get("Messages"):
    a = msg["Messages"][0].get("Attributes", {})
    out += ["DLQ message, read under a 60-second inspection lease and not deleted:", "",
            "- `ApproximateReceiveCount`: **%s**" % a.get("ApproximateReceiveCount"),
            "- `SentTimestamp`: %s" % a.get("SentTimestamp"),
            "- `ApproximateFirstReceiveTimestamp`: %s" % a.get("ApproximateFirstReceiveTimestamp"), ""]
hist = rd("alarm_history.txt", False)
if hist:
    out += ["Alarm transitions. The stack's SNS topic has no subscribers, so each one is read",
            "from alarm history rather than from a notification:", "", "```", hist[:3000], "```", ""]

out += ["### Phase B - permanently rejected job", ""]
bodyb = rd("injected_body_phaseB.json")
if bodyb:
    out += ["```json", json.dumps(bodyb, indent=2), "```", "",
            "Expected: exactly one delivery, `attempts: 1`, the message deleted rather than",
            "redelivered, and the DLQ depth unchanged. The terminal write is **refused** by",
            "`_write`'s `jobId`/`pending` fence, because only the API's enqueue creates that",
            "claim, so the worker logs `A newer claim or result owns this pair; terminal write",
            "skipped` and **no item is created**. That log line plus the queue state is the",
            "zero-retry evidence; there is no record to read back and nothing to clean up.", ""]

out += ["### Cleanup", ""]
log = rd("drill.log", False) or ""
for line in log.splitlines():
    if any(k in line for k in ("deleted", "final ", "DLQ-empty", "WARNING")):
        out.append("- %s" % line)

out += ["", "### What this establishes, and what it does not", "",
        "Per the pre-registered procedure in `docs/evaluation/e5/procedure.md`, this session supplies",
        "E5's DLQ and attempt bounds, the measured alarm delay, and zero retries on a permanent error.",
        "It does **not** establish jobs recovered by retry, the token-warning alarm, or the honest",
        "unavailable/retry UI, and W4's injected transient routing failures cannot be run by this",
        "route at all. **E5 is not complete after this session.**"]

dest = os.path.join(ev, "receipt.md")
with open(dest, "w") as fh:
    fh.write("\n".join(out) + "\n")
print("receipt written:", dest)
