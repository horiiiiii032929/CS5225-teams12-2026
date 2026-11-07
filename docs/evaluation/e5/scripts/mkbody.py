#!/usr/bin/env python3
"""Build a drill payload. Keeps JSON out of the shell script."""
import json, sys, uuid

kind, mark, revision = sys.argv[1], sys.argv[2], sys.argv[3]
if kind == "unkeyable":
    print(json.dumps({
        "schemaVersion": 0, "drill": mark, "issue": 27,
        "note": "Synthetic unkeyable payload for the #27 DLQ drill. Never re-drive.",
        "operator": "lukerspace", "revision": revision}))
elif kind == "rejected":
    print(json.dumps({
        "schemaVersion": 1, "jobId": str(uuid.uuid4()),
        "stationKey": "DRILL27", "town": "DRILL",
        "origin": {"lat": "not-a-number", "lng": "not-a-number"},
        "destination": {"lat": "not-a-number", "lng": "not-a-number"},
        "routingProfileVersion": "drill",
        "routingDate": "2026-11-06", "routingTime": "08:30:00",
        "drill": mark, "issue": 27,
        "note": "Synthetic permanent-rejection payload for E5 Phase B. Never re-drive.",
        "operator": "lukerspace", "revision": revision}))
else:
    sys.exit("unknown payload kind: %s" % kind)
