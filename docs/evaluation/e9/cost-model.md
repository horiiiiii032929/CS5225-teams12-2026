# FlatSplit hosting cost model: AWS versus on-premise

**Issue:** [#45 — Compare AWS and on-premise hosting costs](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/45) · **Experiment:** E9 in [evaluation-plan.md](https://github.com/horiiiiii032929/CS5225-teams12-2026/blob/main/docs/evaluation-plan.md)
**Draft:** 12 October 2026 · **Updated:** 5 November 2026 · **Owner:** Ming (@lukerspace) · **Reviewer:** Mani (@saravanamani1999) · **Status:** Partially measured — per-request operations and one shared-dev usage window measured; tagged bill and demand volumes remain open
**Repository path:** `docs/evaluation/e9/cost-model.md` (the original draft proposed `docs/evaluation/E9-cost/cost-model.md`; D-E5 now uses lowercase experiment IDs)

The demand figures are assumptions. What each request _costs in AWS operations_ is no longer an assumption: on 20 October 2026 every DynamoDB, SQS and OneMap call was counted per request against the real Lambda resolver, and those counts replaced the design budgets the model used before (see [Measured per-request operations](#measured-per-request-operations-20-october-2026)). Issue #34's [3 November deployed receipt](deployed-usage-2026-11-03.md) adds one 124-hour shared-dev observation of durations, logs, queue traffic, table size, failures and rent coverage. It does not establish monthly demand or an actual tagged bill. The on-premise figures are an estimate built on stated assumptions, **not a quote** (required wording, evaluation-plan limitations).

## Status reconciliation — 20 October 2026

The runnable model and dated 12/14 October outputs are preserved, including the original tables below. They are assumption-based scenarios, not the current deployed bill. This documentation update does not change model inputs, rerun the model or recalculate historical totals. The original architecture/driver discussion below describes the model baseline, including components that are still planned.

Before publishing a refreshed result, the model owner must reconcile these inputs:

Three of the five are now closed by [Measured per-request operations](#measured-per-request-operations-20-october-2026), which replaced the budgeted figures and reran the model; they are kept here with their outcome rather than deleted.

- **DynamoDB — closed.** The old 7/8-request budget is superseded. The implemented complete status path uses eight calls for two distinct stations and 11 for five when partitions fit one page; claims, submission, pagination and retries add work. Measure the actual workload in #30 instead of treating the old fixed budget as a current fact.
- **Routing — closed.** Main resolves non-routable TENGAH directly to `unavailable`; it does not enqueue that pair. There are 27 town records but 26 routable town pairs per distinct destination station. The JSON's statement that TENGAH is enqueued is historical and must be corrected with the next model revision. The historical 187,200-job table and 194,400-job prose use different town counts; neither is a measured monthly total.
- **Destination lookup — closed.** [Ming's 20 October evidence](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/45#issuecomment-6286439604) reports cold lookup cost of `1 + N` upstream calls and repeat-query cache hits of zero for open PR #65. Its Kent Ridge sample used six calls cold and zero warm, through a local handler with live OneMap and Moto. Candidate count and distinct-query/cache-hit rate must drive the lookup estimate; a fixed two-call assumption is superseded. Sample timings are not deployed p95/capacity evidence, and the query cache is not merged on main.
- **Runtime/admission — still open.** Main's HTTP Lambda timeout is 30 seconds, not the draft's 10. CDK now defines 100 requests/s, burst 200 for `eval` only; other stages retain 20/40. Verify actual deployed configuration and authorisation before W2; configuration does not establish capacity or a 500 ms result.
- **Resource scope — still open.** The worker/event-source mapping, scheduled ingestion, custom metrics, dashboard and queue/DLQ alarms are not implemented on main. Their model costs remain planned assumptions; SQS idle-poll volume is not an observed charge. Budget alerts are conditional on `budgetEmail` configuration.

Payer-side cost-tag status/history, account allowances, actual worker/usage measurements (#34), node throughput (#30) and final price refresh remain outstanding. The 14 October linked-account billing access denial remains the recorded limitation. See the [measurement requests](evidence/measurement-requests.md) and [deployment handoff](../../aws-dev-handoff.md); no billing or deployment change is claimed.

## Historical model baseline — 12–14 October 2026

## What this answers

E9 asks: _what does FlatSplit cost on AWS compared with on-premise, for the same workload and the same service goals?_ The model therefore has to produce four things, which are the acceptance criteria of #45:

1. Comparable quiet, typical and bursty workload scenarios, with documented assumptions.
2. Normal AWS hosting cost against an on-premise model covering hardware, electricity, storage/backups and operational effort, with free-tier credits shown **separately**.
3. The main cost drivers and the sensitivity to demand, refined with measured usage.
4. A comparison and its evidence, linkable from the final report (#36, #38).

## Four options, not two

The report's claim is about hosting _models_, so a bare "AWS versus a box" comparison would be unfair in both directions: it would credit serverless with the free tier while charging on-premise for a machine sized for the peak. The model therefore prices four options on the same workload:

| Option                  | What it is                                                                                                                               | Why it is in the comparison                                                                                        |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| **A. AWS serverless**   | The deployed architecture: CloudFront + S3, HTTP API, Lambda (arm64, 256 MB), DynamoDB on-demand, SQS + DLQ, Secrets Manager, CloudWatch | What we actually built (T1, T8, T9 in the technique matrix)                                                        |
| **B. AWS always-on VM** | The same Powertools handler under uvicorn on `t4g.small` instances, 24×7, still using DynamoDB and S3                                    | Isolates "serverless versus always-on" from "cloud versus on-premise". This is the cloud twin of the D-E2 baseline |
| **C. On-premise**       | Owned hardware sized for the W2 peak, in a room we power and cool, patched by a person                                                   | The textbook on-premise alternative: capex, power, cooling, a line                                                 |
| **D. University VM**    | The same uvicorn handler on a VM the institution already owns and powers, at no marginal cost to the team                                | **The realistic on-premise alternative in an NUS context.** Added 3 November 2026                                  |

B is the honest middle column: it shows how much of the saving comes from AWS and how much comes from _not paying for idle capacity_.

**D exists because C on its own is the wrong strawman.** Option C models _buying_ hardware, and no student team in a university would do that — they would ask for a VM. Beating a strawman is worth nothing in a report, so option D removes everything the institution pays for (hardware depreciation, electricity, room cooling, the business line with a static IP — **US$157.56/month, 64.7% of option C at quiet and typical demand, two nodes and likely effort**) and leaves operational effort exactly where it was.

That share is **derived per scenario, not fixed**, and the model reports it rather than asserting it: option C grows with the node count the peak demands while option D does not, and option D keeps the whole operational-effort line, so the share moves with both. At the same two nodes it is 83.5% at low effort and 37.9% at high effort; in the burst scenario's three nodes it is US$188.93, or 68.7% at likely effort. A fixed percentage was published here until 5 November 2026 and was not reproducible from the model's own line items; `institutional_share()` in `model/cost_model.py` now computes it from options C and D, and the generated evidence quotes it with its scenario, node count and effort band attached.

That is the point of including it. **D isolates people from hardware**, and what it shows is that the on-premise cost which survives institutional generosity is the human one. At likely effort, option D is US$85.94/month against option A's US$0.96 — a margin of ~90× rather than ~254×. The conclusion holds, honestly, with a smaller margin, which is a better result to publish than a larger margin against an opponent nobody would field.

Option D is also where this model is most exposed, and the limitations are named rather than buried: public reachability through a campus network is an unpriced administrative dependency (a firewall exception or an institutional reverse proxy), the allocation is not a contract and can be reclaimed or re-imaged on someone else's schedule, and there is no availability story or support SLA. `model/onprem.json`'s `university_vm.excluded_but_named` lists all four.

## Workload scenarios (provisional)

Scenarios are defined in `model/workloads.json` and derive billable units from user-level assumptions, so one edit changes every table. Monthly figures, not peak figures, except where stated.

|                                              |             Quiet |    Typical |                            Bursty |
| -------------------------------------------- | ----------------: | ---------: | --------------------------------: |
| Maps to                                      | between semesters |  W1 Steady |           W2 Burst + W3 Long tail |
| Groups created / month                       |                50 |        500 |                             3,000 |
| Members per group                            |                 3 |          3 |                                 3 |
| Searches / month                             |               100 |      1,000 |                             6,000 |
| Result polls per search                      |                20 |         20 |                                20 |
| API requests / month                         |             3,450 |     34,500 |                           273,000 |
| Destination lookups / month                  |               600 |      6,000 |                            36,000 |
| Lookup cache hit ratio (assumed)             |               20% |        40% |                               50% |
| Commute cache hit ratio (assumed)            |               80% |        90% |                               60% |
| Commute jobs / month                         |             1,560 |      7,800 |                           187,200 |
| **OneMap calls / month** (routing + lookups) |         **4,440** | **29,400** |                       **295,200** |
| Burst events / month                         |                 0 |          0 | 4 × (1→50 req/s ramp, 5 min hold) |
| Peak admitted rate used for sizing           |                 — |          — |                   50 req/s (D-E1) |

The OneMap row changed the most. The model used to equate OneMap calls with commute jobs; measurement shows a cold destination lookup costs **six** calls of its own (one search plus one nearest-station call per candidate), so at typical demand **lookups make up 21,600 of the 29,400 calls — nearly three times the routing traffic**. API requests fall slightly because the organiser is now counted as created with the group rather than joining it.

Fixed facts behind the derivation, taken from the team's merged documents rather than invented: 27 HDB towns each represented by one MRT station ([backend-design.md](https://github.com/horiiiiii032929/CS5225-teams12-2026/blob/main/docs/backend-design.md)); 3 distinct member stations × 27 towns = 81 commute pairs per search; Lambda is arm64 at 256 MB with a 10 s timeout ([infra/aws/src/api.ts](https://github.com/horiiiiii032929/CS5225-teams12-2026/blob/main/infra/aws/src/api.ts)); the HTTP API stage throttles at 20 req/s burst 40, so admitting W2's 50 req/s needs an explicit eval-stage limit (D-E1, D-E2).

Two of those facts are now confirmed by the handler itself rather than by a document. A two-member search wrote 54 pair records (2 × 27) and sent exactly 52 SQS messages (2 × 26), reporting two pairs unavailable — one TENGAH pair per member station, which is the 27/26 routable split from the #2 data profile. And a first search reads 7 times, not the 8 budgeted in [api-contract.md](https://github.com/horiiiiii032929/CS5225-teams12-2026/blob/main/docs/api-contract.md) (A1/A6/A7), while each later result read costs exactly the 7 the contract predicted.

**Assumptions that must still be replaced by measurements**, each marked `_source: assumed` in `model/workloads.json`: Lambda duration outside the lookup path (120 ms), cold-start share (5%), RRU per read request (2.0), WRU per write (1.5), both cache hit ratios, the demand volumes themselves, and `sustained_rps_per_node` for options B and C. Three entries left this list on 3 November, when #34's deployed receipt measured the worker duration (990.307 ms, was an assumed 900 ms), log volume per invocation (595 B, was an assumed 2,048 B) and the per-item byte rate (437 B/item, replacing a flat 0.5 GB table); the stored-item stock they feed is no longer assumed either, since it is now read off the implemented group TTL and commute key shape. See `evidence/measurement-requests.md` (next to this file) for who owns each one.

## Measured per-request operations (20 and 26 October 2026)

`model/measure_operations.py` drives API Gateway v2 events through the real resolver in `flatsplit_api.handlers.http`, with Moto standing in for DynamoDB and SQS, and counts every botocore call, the items each one mutates, each transaction's `ConditionCheck` actions separately, and every OneMap round trip. Raw output: `evidence/measured-operations-20261027.json` is the current run — all nine rows, live OneMap, decoded queries, with [#65](https://github.com/horiiiiii032929/CS5225-teams12-2026/pull/65) merged. Kept for history: `evidence/measured-operations-20261020.json` (the first run, `/places` measured with #65 checked out at `c6f7e0c` and an un-decoded query) and `evidence/measured-operations-20261026.json` (the six rows that do not touch OneMap, with `--seeded-place`).

| Request                     | DynamoDB reads | Write mutations | Condition checks | OneMap calls | SQS sends |   Duration |
| --------------------------- | -------------: | --------------: | ---------------: | -----------: | --------: | ---------: |
| `GET /places` (cold)        |            3-5 |            9-11 |                0 |            6 |         0 | 658-873 ms |
| `GET /places` (cache hit)   |              5 |               0 |                0 |            0 |         0 |      17 ms |
| `POST /groups`              |              1 |               3 |                0 |            0 |         0 |      36 ms |
| `POST /groups/{id}/members` |              2 |               3 |                0 |            0 |         0 |      18 ms |
| `PUT .../members/{id}`      |              4 |               2 |                1 |            0 |         0 |      28 ms |
| `GET /groups/{id}`          |              2 |               0 |                0 |            0 |         0 |      10 ms |
| `POST .../searches` (first) |              7 |              57 |                1 |            0 |        52 |     283 ms |
| `POST .../searches` (again) |              8 |               0 |                0 |            0 |         0 |      94 ms |
| `GET .../searches/{id}`     |              7 |               0 |                0 |            0 |         0 |      93 ms |

Five corrections came out of this, and the first two are the reason the model's DynamoDB lines moved:

1. **A search start writes one record per pair, not two per job.** The old model charged `jobs x 2`; measurement shows one `PutItem` for every pair that has no usable cached result - 54 of them for a two-member search - plus a four-action transaction. A pair with a usable `COMMUTE#` record at the same routing profile returns from the read before writing or sending anything, so the cache hit ratio removes the write and the message together.
2. **A cold destination lookup writes 9-11 items** (one `PLACE#` per candidate, one `STATION#` per distinct station, one `PLACELOOKUP#`) and makes six OneMap calls. The old model charged it one read and nothing else.
3. **The enqueue is not batched**: exactly one `SendMessage` per enqueued pair.
4. **A cache hit is free of upstream cost**: five reads, no writes, no OneMap call, 15-18 ms against 557-697 ms. That is what makes the lookup cache hit ratio the lever on OneMap quota.
5. **A transaction's mutations and its condition checks are different things.** The earlier table counted every `TransactWriteItems` action as a written item, which overstated the mutations: a preference save is two Updates plus one `ConditionCheck` on the destination's ttl, and a search start is three Puts plus one check. The 26 October run measures them apart. AWS still bills a `ConditionCheck` as a transactional write and it still consumes one of the transaction's 100 action slots ([the limit is 100 actions or 4 MB](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html#transaction-apis-txwriteitems), not 25), so the model charges mutations plus checks - which raised the search start from 3 to 4 fixed write units and moved the bursty scenario by one cent, to US$2.49 payable. The accounting is now right; the conclusion was never sensitive to it.

Durations here are laptop durations against Moto, so only the lookup paths feed the model: their cost is real upstream network time, which Lambda pays too. Everything else keeps the assumed 120 ms pending #30. Moto is not DynamoDB, so these are request, item and action counts, not consumed capacity; the RRU/WRU conversion stays with #34.

**The `/places` rows are no longer provisional.** They carried their 20 October values until 27 October, because the measurement script built its query parameters without URL-decoding them: that run searched OneMap for the literal `kent+ridge` rather than the `kent ridge` an `encodeURIComponent` client produces. The script now decodes with `urllib.parse.parse_qsl`, and on 27 October both rows were re-measured against live OneMap with [#65](https://github.com/horiiiiii032929/CS5225-teams12-2026/pull/65) merged, so the warm row is a real cache hit rather than a second cold call. **The counts did not move.** A cold lookup still makes 6 OneMap calls and writes 9 to 11 items, and the decoded queries return the same candidates as the encoded ones: `kent ridge` 4 selectable plus 1 `STATION_TOO_FAR`, `raffles place` 5 selectable. Only the durations differ - 658-873 ms cold against 557-697 ms on 20 October, and 17 ms warm - which is laptop network variance, not a behaviour change. Measured twice in succession with byte-identical counts. Everything downstream of `/places` was re-measured on 26 October with a seeded destination record and is unaffected.

## AWS cost drivers and their on-premise counterparts

| AWS line item                               | What drives it                                                                           | On-premise counterpart                                                                                    |
| ------------------------------------------- | ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| Lambda requests + GB-seconds                | invocations × duration × memory                                                          | A share of the server's purchase price and its idle power                                                 |
| API Gateway HTTP API requests               | every `/api/*` call                                                                      | The same server's web listener (no separate charge, no separate scaling either)                           |
| DynamoDB RRU/WRU                            | measured: 7 reads per search read, 1 write per uncached pair, 9–11 per cold lookup       | PostgreSQL on the same box: no per-request charge, but disk, tuning, backups and a restore drill          |
| DynamoDB storage + PITR                     | table size; PITR is charged per GB-month                                                 | RAID/mirrored disks plus a backup schedule somebody has to verify                                         |
| S3 + CloudFront                             | web build size, page loads, data transfer out                                            | Bandwidth on the business line, plus no global edge at all                                                |
| SQS requests                                | measured 1 send per enqueued pair, +2 assumed (receive/delete), **plus idle long polls** | A local queue (Redis/RabbitMQ) to install, monitor and restart                                            |
| Secrets Manager                             | 1 secret per month, flat                                                                 | A file with 600 permissions and a rotation habit                                                          |
| CloudWatch logs, metrics, alarms, dashboard | log GB ingested, custom metric count, alarm count                                        | Prometheus/Grafana or nothing; if nothing, the comparison is not like-for-like and the report must say so |
| AWS Budgets                                 | free                                                                                     | No equivalent; cost is sunk at purchase                                                                   |

Two drivers are easy to miss and both are in the model: **CloudWatch is the largest payable serverless line at prototype scale** (custom metrics beyond the 10 free, and the dashboard beyond the 3 free), and **SQS long-poll receives are billed even when nobody uses the app** — an idle serverless deployment is cheap, but not exactly zero.

## On-premise model

Full assumptions in `model/onprem.json`. Sizing follows D-E2: one node is a `t4g.small`-class machine (2 vCPU / 2 GiB) running the same handler under two isolated uvicorn workers, and the cluster is sized for the **W2 peak**, with one spare node because a single box has no availability story.

| Category                               | Assumption                                                                                                |        Monthly (US$) |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------- | -------------------: |
| Hardware depreciation                  | 2 × S$1,200 node + UPS S$350 + switch S$250 + backup disks S$200 + spares S$150, 36-month straight line   |                72.70 |
| Electricity                            | 15 W idle / 45 W load, 15% duty cycle, PUE 1.5, S$0.3191/kWh (SP Group household tariff, Q3 2026)         |                10.65 |
| Room cooling share                     | assumption beyond PUE                                                                                     |                11.72 |
| Business internet + static IP          | needed for a public endpoint                                                                              |                62.50 |
| Offsite backup                         | nightly dumps to object storage                                                                           |                 6.25 |
| Domain + TLS                           | Let's Encrypt = 0                                                                                         |                 1.56 |
| Operational effort                     | 4 h/month × S$25/h likely; **ranged 2 h × S$15 to 8 h × S$40** (patching, TLS, restore drills, incidents) | 78.12 (23.44–250.00) |
| **Total (quiet and typical, 2 nodes)** |                                                                                                           |           **243.50** |
| **Total (bursty, 3 nodes)**            |                                                                                                           |           **274.87** |

Named but excluded, so the reader can judge the bias: room rent and physical security (assumed free on campus), hardware failure beyond the spares buffer, DDoS protection (CloudFront includes Shield Standard), the one-off time to build a deployment pipeline, and the cost of downtime — the single-box model has no SLA.

## Comparison (model output, updated 5 November 2026)

Generated by `model/cost_model.py`; raw output in `evidence/cost_model_20261105T035414Z.{md,json,csv}`.
Every superseded run is kept, so a figure quoted in an earlier issue stays locatable. Newest first:

- `cost_model_20261103T052836Z.*` — the run these figures replace. It used the same measured inputs; what is corrected here is that it derived the stored-item stock from a retention policy the stack does not implement, and published a fixed institutional-share percentage. Both are in [The 5 November corrections](#the-5-november-corrections).
- `cost_model_20261027T013441Z.*` — the last run before #34's deployed receipt. What that receipt's measured inputs moved is in [The 3 November correction](#the-3-november-correction).
- `cost_model_20261020T103456Z.*` — the run before transaction mutations and condition checks were counted apart.
- `cost_model_20261014T072020Z.*` — the assumption-only version, before any per-request operation was counted.
- `cost_model_20261012T062840Z.*` — the run quoted in #45 (it assumed 26 towns).

| Option                                            |  Quiet US$/mo | Typical US$/mo | Bursty US$/mo | US$ per 1,000 searches (typical) |
| ------------------------------------------------- | ------------: | -------------: | ------------: | -------------------------------: |
| A. AWS serverless — **payable**                   |          0.82 |           0.96 |          2.09 |                             0.96 |
| A. AWS serverless — list price, free tier removed |          5.09 |           5.70 |         10.43 |                             5.70 |
| B. AWS always-on VM                               |         38.31 |          38.44 |         56.92 |                            38.44 |
| C. On-premise — likely effort                     |        243.50 |         243.50 |        274.87 |                           243.50 |
| C. On-premise — effort band                       | 188.81–415.38 |  188.81–415.38 | 220.18–446.74 |                                — |
| D. University VM — likely effort                  |         85.94 |          85.94 |         85.94 |                            85.94 |
| D. University VM — effort band                    |  31.25–257.81 |   31.25–257.81 |  31.25–257.81 |                                — |

Measuring the operation counts moved the serverless total by **+5% at typical demand and +13% in the burst**, all of it in DynamoDB: writes went from US$0.03 to US$0.07 typical and US$0.47 to US$0.71 bursty, reads from US$0.04 to US$0.06 and US$0.27 to US$0.33. Counting each transaction's condition check as the billed write it is added one more fixed write unit per search, which is the one cent between the 20 October bursty figure and this one. Nothing in the comparison's conclusion changes — the gap to option C is still roughly two orders of magnitude — which is itself the useful result: **the on-premise comparison was never sensitive to the per-request accounting**, so the remaining uncertainty that matters is `sustained_rps_per_node` on the on-premise side, not AWS usage.

Free-tier allowances are listed per line item in the generated tables, never netted silently. At typical demand the free tier covers US$4.74 of US$5.70, so **the cloud-versus-on-premise conclusion does not depend on the free tier**: even at list price, option A is roughly 43× cheaper than option C. Both figures were left stale by the 3 November re-run and are corrected here; see [The 5 November corrections](#the-5-november-corrections).

### The 3 November correction

Issue #34's [deployed receipt](deployed-usage-2026-11-03.md) measured, for the first time, the AWS-side inputs this model had been guessing at. Re-running against them moved typical demand from **US$1.27 to US$0.96**. The deltas are isolated one input at a time against the 27 October run:

| Input                               | Published | 3 November |  Δ typical | Δ at ×100 | How it is now known            |
| ----------------------------------- | --------: | ---------: | ---------: | --------: | ------------------------------ |
| `cloudwatch_custom_metrics`         |        12 |          2 |     −0.600 |     −0.60 | counted in the tree            |
| `secrets_count`                     |         1 |          2 | **+0.400** | **+0.40** | counted in the tree            |
| `ddb_table_size_gb` → per-item rate |    0.5 GB | 437 B/item |     −0.113 |     −0.09 | measured (#34)                 |
| `log_bytes_per_invocation`          |     2,048 |        595 |     −0.000 | **−2.19** | measured (#34)                 |
| `sqs_idle_poll_requests_per_month`  |   650,000 |   ~285,189 |     −0.000 |     −0.15 | projected from measured (#34)  |
| `lambda_worker_duration_ms`         |       900 |    990.307 |     −0.000 |     −0.00 | measured (#34)                 |
| `cloudwatch_alarms`                 |         6 |          5 |      0.000 |      0.00 | counted; inside free allowance |
| **Combined**                        |           |            | **−0.313** | **−2.63** |                                |

Four things in that table are worth carrying into the report.

**The measured part of the model held; the assumed part did not.** The per-request operation counts instrumented on 20 and 27 October needed no correction. Every error was in the demand-independent overhead that had never been measured — how many metrics we emit, how many secrets we hold, how big the table is, how much we log per invocation.

**One correction went the wrong way, and it is the one that now dominates.** `secrets_count` was 1 and the stack has had two secrets since #82 added `OneMapCredentials`. Secrets Manager has no permanent free tier, so this adds US$0.40/month to every scenario — and once the spurious US$0.60 custom-metric charge is removed, credential storage becomes 84% of the payable bill at typical demand. This was found by re-running the model against #34's inputs, not by #34 itself.

**Two measured values were deliberately not adopted, and the reasons are part of the method.** #34 measured the deployed table at 0.000292 GB. That is accurate and it is the wrong figure for a monthly scenario: it measures a dev table holding the team's own test data, not a term's worth of groups, so adopting it would understate a real deployment as badly as 0.5 GB overstated it. Instead the measured **unit rate** — 292,216 bytes over ~668 items, about 437 B/item — now feeds a stated item-stock derivation in `derive_usage()`, the same technique #34 used to turn CloudWatch `IncomingBytes` into bytes per invocation. Similarly, #34's `ListMetrics` observation of one custom metric is a lower bound, because a metric with no recent datapoint is not returned; counting the tree gives the upper bound of two, and both sit inside the 10-metric allowance, so the two bounds agree on the only thing that affects the bill.

**The storage line cannot change the conclusion, and the model says so.** DynamoDB storage sits inside the 25 GB always-free allowance at every item count the model produces, so the only payable part is PITR, under US$0.002/month in every scenario. The derivation is documented for completeness rather than for precision; `ddb_bytes_per_item_source` in `workloads.json` states this explicitly so that nobody later mistakes the item-stock model for a result.

The derived stock is dominated by a **saturating cache**, not by user data: a `COMMUTE#` record is keyed by station and town, so the stock is bounded by the stations that exist (~170) × 27 towns, whatever the demand. At typical demand that is 4,590 of 8,151 items; group and member records — the part that does scale with users — are 2,000, and the retained rent snapshots are 1,561. Of the inputs in that derivation, two are now **read off the implemented lifecycle** (`group_lifetime_days`, and the key shape behind `commute_profile_source`) and one remains a **design decision** (`rent_snapshots_retained`, which is correct because `RENT#` items carry no `ttl`). Two known undercounts are named rather than modelled: DynamoDB deletes an expired item within about 48 hours of its `ttl` rather than at it, and `GROUP#` revision, `PLACE#`, `STATION#` and `PLACELOOKUP#` items are omitted as immaterial.

### The 5 November corrections

@horiiiiii032929's review of `ede4223` raised two [P2] findings against the 3 November run. Both are confirmed in the code and corrected here; neither changes the comparison's conclusion, which is itself worth recording.

**1. The stored-item stock described a retention policy the stack does not implement.** The 3 November derivation multiplied the group/member stock by twelve months and the commute cache by twelve retained profile months, and the chapter stated that no retention is enforced. Both are wrong about the deployed code:

- `services/api/src/flatsplit_api/groups.py` sets `GROUP_LIFETIME = timedelta(days=30)`, writes that `ttl` onto the group record and copies it onto every member record; `infra/aws/src/data.ts` sets `timeToLiveAttribute: 'ttl'`. Group and member records are therefore **deleted about a month after creation**, so the steady-state stock is one month's arrivals, not a year's.
- `services/api/src/flatsplit_api/commute_jobs.py` writes a pair with `put_item` to `{pk: COMMUTE#<station>, sk: TOWN#<town>}`. `routingProfileVersion` is an **attribute** of that item, not part of the key, so a newer profile **replaces** the previous record. Superseded profiles cannot accumulate.

Typical demand falls from 80,641 items to **8,151**, and 0.0352 GB to 0.0036 GB. The payable effect is DynamoDB PITR, US$0.0080 → US$0.0008/month; the typical total stays US$0.96 and the bursty total moves US$2.10 → US$2.09. The twelve-month figure is kept as an explicitly separated hypothetical (`ddb_items_if_retained`, driven by `hypothetical_retention_months`) so that a retention change can be read off the model instead of assumed into it — it reproduces the pre-correction stock exactly, which is how the earlier published figures stay locatable.

**2. The institutional share of option C was asserted as a fixed 88% and is not reproducible.** The two-node likely-effort totals are option C US$243.5022 and option D US$85.9375, so the removed infrastructure is US$157.5647, or **64.71% of option C** — not 88%. The claim also appeared in `cost_model.py`'s generated Markdown and in `onprem.json`. It is now derived by `institutional_share()` and always published with the scenario, node count and effort band that produced it, because the share genuinely moves: 83.45% at low effort, 37.93% at high effort, and 68.73% in the burst scenario's three nodes.

Reconciling those two corrections also caught two figures that the 3 November re-run had left behind: the free tier covers US$4.74 of US$5.70 at typical demand (not US$7.56 of US$8.83), so option A at list price is about 43× cheaper than option C, not 28×.

### Observed shared-dev burst rates

#34's receipt records three worker bursts on the deployed stack. They belong in the report with their provenance attached, and the wording below is deliberate — it follows @wkkuu's correction in #45 on 3 November, and the restrictions are his:

| Start (UTC)  | Jobs / distinct pairs | Stations                | Wall time |  Observed rate |
| ------------ | --------------------: | ----------------------- | --------: | -------------: |
| 30 Oct 10:16 |               26 / 26 | Kent Ridge              |  17.595 s |  88.7 jobs/min |
| 1 Nov 12:06  |               26 / 26 | Kent Ridge              |  15.873 s |  98.3 jobs/min |
| 1 Nov 12:19  |               78 / 78 | Bedok, Expo, Telok Ayer |  37.003 s | 126.5 jobs/min |

**These are observed shared-dev burst rates. They are not a lower bound on sustainable capacity.** They are short natural bursts produced by the team's own activity, not a controlled saturation or endurance test: no run was driven to the point where throughput stopped improving, and none lasted long enough to show whether the rate holds. An earlier draft of this chapter was going to call them a lower bound on worker capacity. That would have been wrong — a 17-second burst says nothing about what the worker sustains, and the phrase would have implied a floor the evidence does not establish.

Three further limits matter for where these numbers may be used:

- **They measure worker jobs per minute, not HTTP requests per second.** Different path, different unit. The worker consumes an SQS queue at `maxConcurrency: 3`; the figure the node sizing needs is admitted request rate on the read path.
- **They cannot replace #30 and cannot determine the node counts for options B or C.** `sustained_rps_per_node` stays a placeholder, and `capacity.target_peak_rps` stays assumed, until a separate authorized evaluation on the isolated stack supplies them. Nothing in #34 changes that, and nothing in this chapter should read as though it did.
- **They say nothing about OneMap quota, and the quota discussion below does not use them.** A received or completed queue message does not by itself establish one provider call: a delivery that fails before the routing call, a redelivery of the same job, and a pair already in the cache all move jobs per minute without matching provider calls one for one. The budget they would have to be compared against is **C7's shared 250 calls/min** (`services/api/src/flatsplit_api/call_budget.py`), and `/places` lookups spend it too. No provider-call or budget measurement exists for the same windows as these three bursts, so the rates cannot establish quota compliance or headroom.

What they are, then, is narrow but real: a dated, deployed observation that the queue drains at all, which before 30 October no evidence in this repository showed.

### Main cost drivers

| Option                               | Dominant driver                                                                               | Share              |
| ------------------------------------ | --------------------------------------------------------------------------------------------- | ------------------ |
| A. AWS serverless, quiet (payable)   | **Secrets Manager** — two secrets at US$0.40 each, plus API calls                             | 0.80 of 0.82 (97%) |
| A. AWS serverless, typical (payable) | **Secrets Manager** (0.81), then DynamoDB reads + writes + PITR (0.13)                        | 0.81 of 0.96 (84%) |
| A. AWS serverless, bursty (payable)  | **DynamoDB** reads + writes + PITR (1.04) overtakes Secrets Manager (0.92)                    | 1.04 of 2.09 (50%) |
| A. AWS serverless (list price)       | CloudWatch dashboard (US$3.00), then custom metrics (US$0.60)                                 | ~63% typical       |
| B. AWS always-on VM                  | EC2 instance-hours, billed whether or not anyone searches                                     | ~80%               |
| C. On-premise                        | Operational effort and the business internet line — **people and connectivity, not hardware** | ~58%               |
| D. University VM                     | **Operational effort alone** — 78.12 of 85.94 at likely effort                                | 91%                |

Compute is not the cost driver in any option at this scale. That is the finding worth putting in the report: for a bursty, low-average workload, hosting cost is dominated by _fixed_ commitments (a person, a line, a box, a secret), and the serverless model has the fewest of them.

**After the 3 November correction the point is sharper, and it is worth stating plainly in the report.** At quiet and typical demand, essentially the whole payable AWS bill is **two Secrets Manager secrets** — 97% and 84% respectively. Every Lambda invocation, every API Gateway request, every byte through CloudFront, the whole log volume, the alarms and the custom metrics all fall inside the always-free allowances at this scale. What we actually pay AWS for is holding one OneMap access token and one OneMap account login, at a flat US$0.40 per secret per month that does not move with demand at all.

There is an irony there that belongs in the report rather than being quietly left out: the credential automation built in #72 and #89 — the thing that stops `/places` breaking every three days — is also the single largest line in the AWS bill. It is still the right engineering decision, because the alternative cost a ~7-hour outage on 31 October and several multi-day ones before that. But it is a concrete, measured example of the thing cloud-cost work keeps running into, which is that at small scale the bill is shaped by fixed per-resource charges and operational choices, not by usage.

Only in the burst scenario does a usage-scaling line take over: DynamoDB reads, writes and PITR reach US$1.04 of US$2.09, because per-pair writes scale with demand while a secret does not.

### Sensitivity to demand

| Demand (typical scaled)           | A. serverless payable | A. list price | C. on-premise | D. university VM | On-prem nodes |
| --------------------------------- | --------------------: | ------------: | ------------: | ---------------: | ------------: |
| idle — nobody uses it for a month |                  0.80 |          5.02 |        243.50 |            85.94 |             2 |
| ×0.1                              |                  0.82 |          5.08 |        243.50 |            85.94 |             2 |
| ×1 (1,000 searches)               |                  0.96 |          5.70 |        243.50 |            85.94 |             2 |
| ×10                               |                  2.36 |         11.81 |        243.50 |            85.94 |             2 |
| ×100 (100,000 searches)           |                 20.75 |         72.90 |        274.87 |            85.94 |             3 |

Option D is flat at every demand level, and that is not a modelling shortcut — it is the consequence of the institution absorbing the capacity. Nothing in option D is sized by us, so nothing in it responds to demand. The honest reading is that option D trades a cost curve for a dependency: it never gets more expensive, and it also never guarantees it will still be there.

Option A tracks demand almost linearly and costs **US$0.80/month when idle**; option C is a step function that charges the same whether traffic is zero or 10× higher, then jumps when the peak needs another node.

**The idle row is the decisive one for this application, and the correction strengthened it.** FlatSplit is seasonal — near-idle between semesters. An empty month costs US$0.80 on option A and US$243.50 on option C, a factor of about **304×** for doing nothing. That is an argument about the shape of the workload, not about AWS being cheap, and it is the argument the report should lead with. Note also that US$0.80 of that US$0.80 is the two secrets: the architecture's true idle cost, excluding credential storage, rounds to zero.

The break-even is far beyond anything this project would reach. On-premise also steps up with demand, so both sides move: at ×500 of typical demand serverless list price is US$344.45 against on-premise US$400.33, and the two cross at roughly **×650** (US$446.28 against US$431.69; ×700: US$480.22 against US$463.06). Payable serverless has not crossed on-premise even at ×700 (US$330.38 against US$463.06). There is no crossover to report inside any plausible range for this application.

**The constraint that bites first is not cost.** The bursty scenario implies **295,200 OneMap calls per month**: 187,200 routing jobs (6,000 searches × 3 stations × 26 routable towns × 40% miss) plus 108,000 from destination lookups (18,000 cold lookups × 6 measured calls). Routing dominates the burst, but at typical demand the ratio inverts: 21,600 lookup calls against 7,800 routing calls, because the commute cache is assumed 90% warm while a 24-hour lookup cache is not. OneMap publishes 300 calls/min, and the implementation holds itself to a tighter figure: C7's **shared 250 calls/min budget**, which worker routing and `/places` lookups draw from the same counter (`call_budget.py`). #3 did not establish a sustained safe rate; assess feasibility with the three-worker concurrency cap and measured drain/lookup latency, not a calls/min division, and never from worker jobs per minute, which is a different unit on a different path. Two measured facts now bound this: a cold lookup costs exactly six calls and a cached one costs zero, so the lookup cache hit ratio — an assumption nobody has measured yet — is the single biggest lever on OneMap quota, and it belongs in #3/#27's follow-up rather than in the cost model.

The routing call count per job is no longer assumed: the implemented #15 worker makes **one routing call per delivery**, and asking for three itineraries is still one call. A job is delivered again only on a transient failure, so the worst case is three calls for a job that keeps being throttled (`COMMUTE_MAX_RECEIVES`), while a terminal failure such as a 404 spends exactly one. [Draining a real queue](../worker-queue/) at the event source's concurrency cap of three measured **165 calls/min** — below the 180 the 992 ms routing p50 alone implies, because each invocation also writes its result — and OneMap's published 300/min is reached at about concurrency five. Drain time, not a calls/min division, is what decides feasibility: at the measured rate one fully cold search's 78 pairs clear in about 28 seconds, and the bursty scenario's 187,200 routing jobs are about 19 hours of worker time spread over the month. Those two durations are this model's arithmetic over the measured rate, not separately measured drains. The harness emulates AWS and replays OneMap's latency, so E4 (#27) still has to confirm the rate on real infrastructure.

## Open questions for the team

1. **Account type (still open, and now the last unanswered cost input).** Is the deployment account a new-account credit-plan AWS account or an AWS Academy/classroom account? The always-free allowances used here (Lambda 1M requests, CloudFront 1 TB, SQS 1M requests, DynamoDB 25 GB) differ from the 12-month ones (API Gateway, S3). #34's 3 November receipt could not confirm this — it records the account's applicable credit/free-tier terms as unconfirmed — and without a tagged bill there is no way to settle it from inside the linked account. The report states the payable column as conditional on standard always-free allowances and shows the list-price column alongside it, which is why the conclusion does not depend on the answer.
2. **Cost allocation tag — answered, and the answer is no.** A read-only Cost Explorer check on 3 November (#34) returned no usable value for the `project` tag, confirming the 14 October `AccessDeniedException` on `ce:ListCostAllocationTags`. FlatSplit spend cannot be separated from anything else in account `553455762180` without a management/payer-account operator activating the tag. **This is treated as final for this project** and written up as a finding: a linked account cannot validate its own costs against a tagged bill without payer-account cooperation. The original note is kept below for the record.

   **Original note.** `infra/aws/src/app.ts` already tags every resource `project=flatsplit`, `stage=<stage>`. The tag must be activated as a cost allocation tag before Cost Explorer can filter by it. Late activation does not necessarily lose earlier tagged spend: [AWS supports management-account tag backfill for up to twelve months](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/cost-allocation-backfill.html), provided the tag was already assigned to the resource during that period. Backfill cannot invent historical resource tags, applies the current activation status of all tag keys, and billing views refresh after processing. Record activation/backfill eligibility and the actual available measurement window. Owner: the billing-authorised management/payer-account operator, to be identified in #4; do not assume the application deployer has billing access.

3. **`sustained_rps_per_node`** (still a placeholder of 25 req/s) is the single number that decides how many nodes options B and C need. #30/E2 must measure it under W2 with the 500 ms target in force. It **stays marked assumed until a separate authorized evaluation supplies it**; the observed shared-dev burst rates above do not substitute for it, because they measure worker jobs/min on a different path and were never driven to saturation. `capacity.target_peak_rps` is assumed on the same basis. Note that option D is unaffected by either, since nothing in it is sized by us — so the realistic on-premise comparison no longer depends on #30.
4. **Operational effort — done.** Asked in #45 on 1 November with no reply, decided by default and now **implemented as a range**: 2 h at S$15/h to 8 h at S$40/h, likely 4 h at S$25/h, carried through options C and D and the sensitivity output. A single judgement call driving the largest line in both self-hosted options is now visibly a judgement call. Mani can still move the band's endpoints before 5 November; the structure is in place either way.
5. **Headline metric — decided by default on 3 November.** Both are generated; the report and slides lead with **US$/month** and keep US$ per 1,000 searches as a secondary column, since the seasonal-idle argument is the strongest finding and only makes sense per month. Overridable before 5 November.
6. **Option D — done.** A university-hosted VM is now priced alongside option C, which stays, so nothing is lost. US$85.94/month at likely effort (band US$31.25–257.81), of which 91% is operational effort. Its four unpriced dependencies — public reachability through a campus network, no availability story, an allocation that is not a contract, and no support SLA — are named in `model/onprem.json` under `university_vm.excluded_but_named` rather than absorbed into the number.

## Limitations to state in the report

- The on-premise model is an estimate from stated assumptions, not a quote; hardware prices, the electricity tariff (household, not non-residential) and the SGD/USD rate of 1.28 are all assumptions.
- The free tier is shown separately, but which allowances apply depends on the account type (open question 1).
- Serverless usage figures mix measured and assumed inputs. As of 3 November, per-request operation counts, worker duration, log volume, DynamoDB bytes per item, idle SQS polling, secret count, alarm count and custom-metric count are measured or counted from the deployed stack or the tree; monthly demand, peak request rate, cold-start share and the two cache hit ratios remain assumed. Each input in `model/workloads.json` carries a `_source` string saying which it is. The AWS totals could still move by a factor of a few on the assumed inputs — though not by the ~250× that separates the options at typical demand.
- The comparison prices the same _workload_, not the same _availability_. Option A is multi-AZ by default; option C is one room with one spare machine; option D is a single VM with no spare at all. The model charges neither self-hosted option anything for that gap.
- Option D assumes the university VM is free to the team, publicly reachable and not reclaimed. None of the three is established. If the allocation is internally billed, or needs an institutional gateway to serve traffic, option D's figure moves and the administrative dependency is the real cost. It is included because excluding it would leave the report arguing against buying hardware, which nobody proposed.
- CloudWatch dashboard pricing (US$3.00/dashboard/month) is AWS's published list price and is the only figure not taken from the Price List API export.

## Reproducing this

```bash
cd docs/evaluation/e9/model
python3 cost_model.py            # writes ../evidence/cost_model_<utc>.{md,json,csv}
python3 cost_model.py --scale 10 # demand sensitivity

# re-measure the per-request operation counts after a handler change
# (needs the dev dependency group for Moto)
export ONEMAP_TOKEN=...   # the /places rows call live OneMap and spend quota
uv run --package flatsplit-api python docs/evaluation/e9/model/measure_operations.py

# without a token: the six rows that never touch OneMap, against a seeded
# destination record. The three /places rows are skipped, not estimated.
uv run --package flatsplit-api python \
  docs/evaluation/e9/model/measure_operations.py --seeded-place
```

Prices come from the AWS Price List bulk API for `ap-southeast-1` (publication date 1 October 2026), captured in `model/prices_ap_southeast_1.json` with the source URL; CloudFront values use the `AP-` usage-type prefix (Asia Pacific price class, which serves Singapore). Refresh before the final report and commit the new file so the figures in the report are reproducible.
