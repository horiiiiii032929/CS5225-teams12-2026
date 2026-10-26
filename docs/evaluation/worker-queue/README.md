# Commute worker: queue behaviour and concurrency (#15)

Issue #15's second acceptance criterion asks for concurrency, rate limits and
repeat-job deduplication "verified with sample jobs". The unit suite proves the
handler's logic and `test_search_api.py` invokes it once per message in-process,
but neither exercises a queue: nothing there has a visibility timeout, a receive
count that SQS incremented, a redrive policy, or two invocations in flight at
once. This directory holds the runs that do.

`scripts/measure_queue_drain.py` starts a real search through the deployed
resolver, lets the merged producer enqueue payload v1 onto a real queue, and
drains it with one worker **process** per concurrent slot — each process a
separate client of that queue, matching `batchSize: 1` and a Lambda container's
process isolation. Nothing in `services/api` is modified to make this run; the
code is configured entirely through `TABLE_NAME`, `DYNAMODB_ENDPOINT_URL`,
`SQS_ENDPOINT_URL` and `COMMUTE_QUEUE_URL`, as CDK configures it.

## What the runs on 2026-10-26 found

Evidence: [`raw/2026-10-26/`](raw/2026-10-26/). Both runs report `PASS`.

### The deployed configuration, drained end to end

A real two-member search on one pinned station enqueued **26** messages and the
workers made **26** invocations — one per message, no redelivery. All **27** pair
records closed: 26 routed, one terminal `unavailable` (TENGAH, which the
producer marks locally), none left `pending`. The next `GET` read back
`complete` with progress 27/27, two ranked towns and CLEMENTI first.

| At `maxConcurrency: 3`    | Measured            |
| ------------------------- | ------------------- |
| Wall time for 26 pairs    | 13.96 s             |
| Max invocations in flight | 3                   |
| Invocation p50            | 1,027.7 ms          |
| Achieved routing rate     | **165.0 calls/min** |
| Headroom under 300/min    | 135.0 calls/min     |
| Work split across workers | 8 / 8 / 10          |
| DLQ after a clean drain   | empty               |

A representative stored record, which is what #16/#18 read:

```json
{
  "pk": "COMMUTE#KENT_RIDGE",
  "sk": "TOWN#CLEMENTI",
  "status": "ok",
  "jobId": "e72e765b-c360-40a6-aec3-f6d916331066",
  "routingProfileVersion": "pt-v1:2026-10",
  "routingDate": "2026-10-27",
  "routingTime": "08:30:00",
  "attempts": 1,
  "minutes": 30.5,
  "transfers": 1,
  "walkMinutes": 5,
  "itineraries": 1,
  "shortestWasFirst": true,
  "computedAt": "2026-10-26T01:56:05.215911+00:00",
  "source": "onemap:routingsvc/route?routeType=pt"
}
```

### Why the concurrency is 3, measured rather than argued

The handler has no rate limiter on purpose: concurrency is meant to be the only
limit. That claim is testable — if the achieved rate did not track concurrency,
it would be false. Draining the same 26-pair search at five concurrencies:

| Concurrency | Achieved calls/min | Wall time | Per worker |
| ----------- | ------------------ | --------- | ---------- |
| 1           | 61.2               | 29.94 s   | 61.2       |
| 2           | 118.7              | 17.63 s   | 59.4       |
| **3**       | **166.8**          | 13.90 s   | 55.6       |
| 4           | 245.5              | 10.88 s   | 61.4       |
| 6           | **324.7**          | 9.44 s    | 54.1       |

Per-worker throughput stays near 55–61 calls/min across the range, so the rate
really is set by concurrency and nothing else. OneMap's published 300/min cap is
reached at about **concurrency 4.9**, and the measured rate at 6 exceeds it.
Three leaves roughly a 45% margin, which is why the event source is set there and
why a second, token-bucket limiter would only have to be kept in step with this
one.

### Deduplication, exhaustion, and what reaches the DLQ

| Scenario                                                   | Result                                                                                                                                                                                                                                                                    |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The exact payload of an already-resolved pair, redelivered | The fenced write was refused and the record did not change — same `computedAt`, same `attempts: 1`. The message was still deleted, not retried, and the DLQ stayed empty.                                                                                                 |
| Routing failing transiently, to exhaustion                 | The queue redelivered at receive counts 1, 2, 3. On the third the worker wrote the terminal result itself: `unavailable`, `ROUTING_UNAVAILABLE`, `attempts: 3`, `retryAfter` 900 s ahead as an epoch second, and **no** minutes left on the record. The DLQ stayed empty. |
| A payload the handler cannot key (`schemaVersion: 9`)      | Failed three receives, then redrove. Source queue empty, DLQ depth 1.                                                                                                                                                                                                     |

Together these are the deduplication half of the acceptance criterion: a
duplicate delivery, a lease reclaimed by a newer claim and an already-finished
pair are all refused by one condition, and a refusal is a normal outcome rather
than a message failure.

## What these runs are not

- **AWS is Moto in server mode.** Its queue semantics were probed before being
  relied on — receive counts increment, an undeleted message returns after its
  visibility timeout, and the third receive redrives — but this is not a
  measurement of AWS SQS, and it does not show that Lambda's event-source
  `maxConcurrency` holds the rate in production. The harness supplies the
  concurrency itself; AWS's scaling is not under test.
- **OneMap is replayed, not called.** The shared token expired on 23 October
  (#72) and this script mints none. Each routing call sleeps for a latency drawn
  from the eight per-pair timings recorded against live OneMap on 20 October
  (`../worker-routing/`, p50 992 ms), so the rate figures rest on a real
  measurement of the upstream — but a live drain could differ, and the 429 path
  is still unprovoked.
- **Not a deployed result.** No AWS account was contacted. Queue drain on real
  infrastructure, DLQ redrive, alarms and cost remain #27's E4/E5.
- Rent and place records are synthetic fixtures; #10 and #14 own the real ones.

## Running it

It needs a Moto server to point at. Moto's server extra is a harness-only
dependency and is deliberately not in the repository's dev group:

```sh
uv run --with 'moto[server]' moto_server -H 127.0.0.1 -p 5001 &

export AWS_ACCESS_KEY_ID=harness AWS_SECRET_ACCESS_KEY=harness
export AWS_DEFAULT_REGION=ap-southeast-1

# the four scenarios above
uv run --package flatsplit-api python \
  docs/evaluation/worker-queue/scripts/measure_queue_drain.py

# the concurrency sweep
uv run --package flatsplit-api python \
  docs/evaluation/worker-queue/scripts/measure_queue_drain.py --sweep 1,2,3,4,6
```

Each run writes a timestamped JSON file under `raw/<date>/` and exits non-zero
if any of its checks fail. `--concurrency`, `--short-visibility` and `--seed`
are available; the deployed values for the redrive count and the source queue's
visibility timeout are constants in the script, kept in step with
`infra/aws/src/api.ts`.
