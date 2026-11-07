## #27 eval drill receipt

**Marker:** `drill-27-20261107T034815Z`
**Stage revision:** `e2d3780e28028574f8ee3dd990c10257be9f8029`
**Operator:** @lukerspace
**Principal:** `arn:aws:sts::553455762180:assumed-role/FlatSplit-eval-Drill27/botocore-session-1794023252` in account `553455762180`

### Phase A - unkeyable job to the DLQ

Injected body:

```json
{
  "schemaVersion": 0,
  "drill": "drill-27-20261107T034815Z",
  "issue": 27,
  "note": "Synthetic unkeyable payload for the #27 DLQ drill. Never re-drive.",
  "operator": "lukerspace",
  "revision": "e2d3780e28028574f8ee3dd990c10257be9f8029"
}
```

Queue depths over the session (`visible in-flight`):

```
[2026-11-07T03:48:29Z / 11:48:29 SGT] src=0	0 dlq=0	0
[2026-11-07T03:48:41Z / 11:48:41 SGT] src=0	0 dlq=0	0
[2026-11-07T03:48:52Z / 11:48:52 SGT] src=0	1 dlq=0	0
[2026-11-07T03:49:04Z / 11:49:04 SGT] src=0	1 dlq=0	0
[2026-11-07T03:49:15Z / 11:49:15 SGT] src=0	1 dlq=0	0
[2026-11-07T03:49:27Z / 11:49:27 SGT] src=0	1 dlq=0	0
[2026-11-07T03:49:38Z / 11:49:38 SGT] src=0	1 dlq=0	0
[2026-11-07T03:49:50Z / 11:49:50 SGT] src=0	1 dlq=0	0
[2026-11-07T03:50:01Z / 11:50:01 SGT] src=0	1 dlq=0	0
[2026-11-07T03:50:13Z / 11:50:13 SGT] src=0	1 dlq=0	0
[2026-11-07T03:50:24Z / 11:50:24 SGT] src=0	1 dlq=0	0
[2026-11-07T03:50:36Z / 11:50:36 SGT] src=0	1 dlq=0	0
[2026-11-07T03:50:47Z / 11:50:47 SGT] src=0	1 dlq=0	0
[2026-11-07T03:50:59Z / 11:50:59 SGT] src=0	1 dlq=0	0
[2026-11-07T03:51:10Z / 11:51:10 SGT] src=0	1 dlq=0	0
[2026-11-07T03:51:21Z / 11:51:21 SGT] src=0	1 dlq=0	0
[2026-11-07T03:51:33Z / 11:51:33 SGT] src=0	1 dlq=0	0
[2026-11-07T03:51:44Z / 11:51:44 SGT] src=0	1 dlq=0	0
[2026-11-07T03:51:56Z / 11:51:56 SGT] src=0	1 dlq=0	0
[2026-11-07T03:52:07Z / 11:52:07 SGT] src=0	1 dlq=0	0
[2026-11-07T03:52:19Z / 11:52:19 SGT] src=0	1 dlq=0	0
[2026-11-07T03:52:30Z / 11:52:30 SGT] src=0	1 dlq=0	0
[2026-11-07T03:52:42Z / 11:52:42 SGT] src=0	1 dlq=0	0
[2026-11-07T03:52:53Z / 11:52:53 SGT] src=0	1 dlq=0	0
[2026-11-07T03:53:05Z / 11:53:05 SGT] src=0	1 dlq=0	0
[2026-11-07T03:53:16Z / 11:53:16 SGT] src=0	1 dlq=0	0
[2026-11-07T03:53:28Z / 11:53:28 SGT] src=0	1 dlq=0	0
[2026-11-07T03:53:39Z / 11:53:39 SGT] src=0	1 dlq=0	0
[2026-11-07T03:53:51Z / 11:53:51 SGT] src=0	1 dlq=0	0
[2026-11-07T03:54:02Z / 11:54:02 SGT] src=0	1 dlq=0	0
[2026-11-07T03:54:14Z / 11:54:14 SGT] src=0	1 dlq=0	0
[2026-11-07T03:54:26Z / 11:54:26 SGT] src=0	1 dlq=0	0
[2026-11-07T03:54:37Z / 11:54:37 SGT] src=0	1 dlq=0	0
[2026-11-07T03:54:49Z / 11:54:49 SGT] src=0	1 dlq=0	0
[2026-11-07T03:55:00Z / 11:55:00 SGT] src=0	1 dlq=0	0
[2026-11-07T03:55:12Z / 11:55:12 SGT] src=0	1 dlq=0	0
[2026-11-07T03:55:23Z / 11:55:23 SGT] src=0	1 dlq=0	0
[2026-11-07T03:55:35Z / 11:55:35 SGT] src=0	1 dlq=0	0
[2026-11-07T03:55:47Z / 11:55:47 SGT] src=0	1 dlq=0	0
[2026-11-07T03:55:58Z / 11:55:58 SGT] src=0	1 dlq=0	0
[2026-11-07T03:56:10Z / 11:56:10 SGT] src=0	1 dlq=0	0
[2026-11-07T03:56:21Z / 11:56:21 SGT] src=0	1 dlq=0	0
[2026-11-07T03:56:33Z / 11:56:33 SGT] src=0	1 dlq=0	0
[2026-11-07T03:56:44Z / 11:56:44 SGT] src=0	1 dlq=0	0
[2026-11-07T03:56:56Z / 11:56:56 SGT] src=0	1 dlq=0	0
[2026-11-07T03:57:07Z / 11:57:07 SGT] src=0	1 dlq=0	0
[2026-11-07T03:57:19Z / 11:57:19 SGT] src=0	1 dlq=0	0
[2026-11-07T03:57:30Z / 11:57:30 SGT] src=0	1 dlq=0	0
[2026-11-07T03:57:42Z / 11:57:42 SGT] src=0	0 dlq=0	0
[2026-11-07T03:57:53Z / 11:57:53 SGT] src=0	0 dlq=1	0
```

DLQ message, read under a 60-second inspection lease and not deleted:

- `ApproximateReceiveCount`: **4**
- `SentTimestamp`: 1794023297063
- `ApproximateFirstReceiveTimestamp`: 1794023297072

Worker log entries carrying the marker, one per delivery **to the worker**. This count,
not the `ApproximateReceiveCount` above, is the pass condition: the 60-second inspection
lease increments that attribute itself.

- `Unusable commute job` entries: **3**
  - 2026-11-07T03:48:18.982000Z
  - 2026-11-07T03:51:17.120000Z
  - 2026-11-07T03:54:17.112000Z

Alarm transitions. The stack's SNS topic has no subscribers, so each one is read
from alarm history rather than from a notification:

```
--- FlatSplit-eval-CommuteAlarmsCommuteDlqNotEmptyF7769442-pqGC0L7DfpRz
------------------------------------------------------------------------
|                         DescribeAlarmHistory                         |
+-----------------------------------+----------------------------------+
|                at                 |             summary              |
+-----------------------------------+----------------------------------+
|  2026-11-07T12:07:32.199000+08:00 |  Alarm updated from ALARM to OK  |
|  2026-11-07T11:59:32.200000+08:00 |  Alarm updated from OK to ALARM  |
+-----------------------------------+----------------------------------+
--- FlatSplit-eval-CommuteAlarmsCommuteJobsStalledBD017C6C-spDtpagUajN9
--- FlatSplit-eval-CommuteAlarmsOneMapTokenRefreshFailing2F3BF79B-EZFmy862pO18
--- FlatSplit-eval-CommuteAlarmsOneMapTokenExpiringE2BD398F-XbS8tBohAc1q
--- FlatSplit-eval-CommuteAlarmsRentIngestionFailed77352AD1-IaiMNEomPgSd
```

### Phase B - permanently rejected job

```json
{
  "schemaVersion": 1,
  "jobId": "128035d3-bb1b-4a5f-bb1b-c6239faa5f02",
  "stationKey": "DRILL27",
  "town": "DRILL",
  "origin": {
    "lat": "not-a-number",
    "lng": "not-a-number"
  },
  "destination": {
    "lat": "not-a-number",
    "lng": "not-a-number"
  },
  "routingProfileVersion": "drill",
  "routingDate": "2026-11-06",
  "routingTime": "08:30:00",
  "drill": "drill-27-20261107T034815Z",
  "issue": 27,
  "note": "Synthetic permanent-rejection payload for E5 Phase B. Never re-drive.",
  "operator": "lukerspace",
  "revision": "e2d3780e28028574f8ee3dd990c10257be9f8029"
}
```

Expected: exactly one delivery, `attempts: 1`, the message deleted rather than
redelivered, and the DLQ depth unchanged. The terminal write is **refused** by
`_write`'s `jobId`/`pending` fence, because only the API's enqueue creates that
claim, so the worker logs `A newer claim or result owns this pair; terminal write
skipped` and **no item is created**. That log line plus the queue state is the
zero-retry evidence; there is no record to read back and nothing to clean up.

Observed, from the same step-5 capture:

```
2026-11-07T04:00:16.263000Z  {"level":"WARNING","location":"_terminal:184","message":"A newer claim or result owns this pair; terminal write skipped","timestamp":"2026-11-07 04:00:16,263+0000","service":"flatsplit-commute-worker","cold_start":true,"function_name":"FlatSplit-eval-ApiCommuteWorkerDCCDFB3E-q5NINW3MSCpw","function_memory_size":"256","function_arn":"arn:aws:lambda:ap-southeast-1:553455762180:function:FlatSplit-eval-ApiCommuteWorkerDCCDFB3E-q5NINW3MSCpw","function_request_id":"fc9ec3e9-5fea-5fc7-90b6-a081fb97b2e4","jobId":"128035d3-bb1b-4a5f-bb1b-c6239faa5f02","stationKey":"DRILL27","town":"DRILL","attempts":1,"routingError":"INVALID_ROUTE_REQUEST","reason":"The job's lat is not a number.","xray_trace_id":"1-6aeea24e-f755a65ed8ecd341fa51e6a4"}
```

### Cleanup

- [2026-11-07T04:01:09Z / 12:01:09 SGT] deleted our drill message
- [2026-11-07T04:01:32Z / 12:01:32 SGT] final DLQ depth (visible / in-flight): 0	1
- [2026-11-07T04:01:33Z / 12:01:33 SGT] final source depth: 0	0
- [2026-11-07T04:01:33Z / 12:01:33 SGT] DLQ-empty check time above is the timestamp to quote on #30.
- BOTH QUEUES CONFIRMED EMPTY at 12:01:46 SGT
- BACK TO OK

### What this establishes, and what it does not

Per the pre-registered procedure in `docs/evaluation/e5/procedure.md`, this session supplies
E5's DLQ and attempt bounds, the measured alarm delay, and zero retries on a permanent error.
It does **not** establish jobs recovered by retry, the token-warning alarm, or the honest
unavailable/retry UI, and W4's injected transient routing failures cannot be run by this
route at all. **E5 is not complete after this session.**
