# FlatSplit evaluation plan: AWS techniques and shared experiments

**Issue:** [#46 — Coordinate AWS techniques and shared evaluation experiments](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/46)
**Draft:** 10 October 2026 · **Owner:** @shyamgj1900 · **Reviewer:** @wkkuu · **Status:** Proposed. Decisions D-E1 to D-E7 need agreement by 12 October.

This plan shows how we will demonstrate that each AWS technique in FlatSplit solves a real application problem, with a baseline to compare against. It covers the five evidence areas in #46: users and fairness understanding, data quality and cache efficiency, latency and scaling, failure recovery, and hosting cost. Architecture and API details are in [backend-design.md](backend-design.md) and [api-contract.md](api-contract.md).

Nothing in this document is a result. Targets are hypotheses until an experiment records evidence.

## Technique matrix

| ID  | AWS technique                                                            | Application problem it addresses                                                | Experiment |
| --- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------- | ---------- |
| T1  | Serverless request path: Lambda + HTTP API + DynamoDB on-demand          | Demand is bursty (semester start, group invites) and near zero most of the time | E1, E2     |
| T2  | Precomputed rent summaries and commute matrix cached in DynamoDB         | OneMap routing is slow and quota-limited; ranking must answer in under 500 ms   | E1, E3     |
| T3  | Destination snapping to MRT stations as the cache key                    | Free-text destinations would make every search a cache miss                     | E3, E8     |
| T4  | SQS queue with a concurrency-limited commute worker                      | Uncached routes must not block requests or exceed OneMap's rate limit           | E4         |
| T5  | SQS retries, dead-letter queue, `unavailable` marking, CloudWatch alarms | Transient OneMap failures must recover without loops or invented commute times  | E5         |
| T6  | Validated, versioned rent snapshots behind a pointer; DynamoDB PITR      | A malformed monthly dataset must not corrupt recommendations                    | E6         |
| T7  | DynamoDB conditional writes and transactions; group revision             | Concurrent joins and edits must not overfill a group or show stale results      | E7         |
| T8  | CloudFront in front of S3 and the API on one origin                      | One URL for every flatmate's device, HTTPS, no CORS, cached static assets       | E1         |
| T9  | Pay-per-use services, budgets and tagging                                | A student project cannot pay for idle capacity sized for peak                   | E9         |

Users and data are evaluated by E10 and E8 so that the system's output, not only its infrastructure, is measured.

## Experiments

Each experiment names its owner (the issue's primary owner), the comparison, the workload (defined in the next section), the metric and the evidence to keep.

| ID  | Question                                                                      | Baseline or comparison                                                                                                           | Workload                                 | Metrics                                                                                                                                                                 | Evidence                                                                    | Owner and issue                                     |
| --- | ----------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- | --------------------------------------------------- |
| E1  | Is a cached search fast enough?                                               | Report target: under 500 ms. Cold start vs warm Lambda; warm cache vs results that need queued routes                            | W1 steady                                | p50, p95, p99 latency of `GET /api/groups/{groupId}/searches/{searchId}` at CloudFront; cold-start share and init duration; dataset size                                | k6 summary, CloudWatch Lambda duration and init metrics, dataset row counts | @wkkuu, #30                                         |
| E2  | How does the request path handle admitted bursts and throttle excess traffic? | Same handler on one fixed-size instance (`t4g.small`, uvicorn via `local.py` with 2 worker processes) as the on-premise analogue | W2 burst                                 | Successful requests/s, error and 429 rate, p95 latency under load, Lambda concurrent executions, cost per 1,000 searches                                                | k6 summaries for both targets, CloudWatch concurrency graph                 | @wkkuu, #30; summary in #36                         |
| E3  | How much external routing does caching and snapping save?                     | No cache: every search routes every member to every town (members × towns calls)                                                 | W1 and W3                                | Cache-hit ratio, OneMap calls per search, distinct cache keys vs distinct raw addresses, time to first complete result (cold vs warm)                                   | Powertools metrics, OneMap call counter, key counts                         | @lukerspace, #15; summary @shyamgj1900, #36         |
| E4  | Does the queue respect OneMap's limit while finishing quickly?                | Analytical baseline: synchronous fan-out in the request, which is bounded by the 30 s API Gateway timeout and the rate limit     | W3 cold start                            | Routing calls per minute (must stay under the limit agreed in #3), OneMap 429 count, SQS oldest-message age, time to drain N pairs                                      | Worker metrics, SQS CloudWatch graphs                                       | @lukerspace, #27; usage @saravanamani1999, #34      |
| E5  | Do transient failures recover without loops?                                  | Same failure with retries and the DLQ disabled                                                                                   | W4 fault                                 | Jobs recovered by retry, jobs in DLQ, maximum attempts per job, time from fix to recovery after redrive, alarm time to notify, UI shows `unavailable` and retry         | Fault-injection log, DLQ and alarm screenshots, UI capture                  | @lukerspace, #27, #19; checked by @wkkuu, #35       |
| E6  | Does a bad rent file leave searches untouched?                                | Before vs after the bad file: identical search results expected                                                                  | W5 bad data                              | Publication blocked (yes/no), searches answered during the incident, results unchanged, time until alarm, PITR restore drill duration                                   | Validation log, alarm, before/after result diff                             | @saravanamani1999, #28; checked by @wkkuu, #35      |
| E7  | Do concurrent writes keep groups consistent?                                  | Expected invariants from the contract (access patterns A3 and A4)                                                                | W6 concurrency                           | Successful joins when 20 clients race for the last place (expect exactly 1), stale searches detected after an edit (expect 100%)                                        | Automated test output in CI                                                 | @shyamgj1900, #29; checked by @wkkuu, #35           |
| E8  | Are the numbers we show trustworthy?                                          | Rent: HDB's published median rents by town and flat type. Commute: OneMap route to the exact address vs the snapped station      | Sample of 20 towns and 20 destinations   | Median rent difference, towns and flat types with too few records, snapped-vs-exact commute error in minutes (median and maximum), route coverage                       | Audit table with source dates                                               | @saravanamani1999, #20, #34; @lukerspace, #19       |
| E9  | What does it cost on AWS compared with on-premise?                            | On-premise model: hardware sized for the W2 peak, electricity, storage and backups, operator effort; free tier shown separately  | Quiet, typical and burst scenarios (#45) | Monthly cost per scenario, cost per 1,000 searches, main cost drivers, sensitivity to demand                                                                            | Cost Explorer filtered by the `project=flatsplit` tag, spreadsheet model    | @lukerspace, #45; usage from @saravanamani1999, #34 |
| E10 | Can users make a fair group decision?                                         | Within-participant comparison of a results view with averages only vs per-member commutes and the commute gap                    | 8–12 participants (at least 3 for #31)   | Task completion, time on task, correctly naming the most burdened member, explaining a rank change, 1–5 ratings of clarity, fairness understanding, ease and usefulness | Session notes, timings, ratings sheet, list of blockers fixed               | @horiiiiii032929, #31; reviewer @Raccoon33          |

## Workloads

Shared definitions keep the experiments comparable. A seeded generator script (to be added under `tools/load/`) produces them so that runs can be repeated.

| ID  | Name        | Definition                                                                                                                                                                           |
| --- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| W1  | Steady      | 3-member groups; destinations drawn from 30 common destinations (universities, CBD, business parks) weighted by expected popularity; 2 searches/s for 10 minutes with the cache warm |
| W2  | Burst       | Semester-start spike: ramp from 1 to 50 requests/s within 60 seconds, hold 5 minutes, back to 0. Mix of 30% create/join, 40% preference saves, 30% search reads                      |
| W3  | Long tail   | Destinations drawn uniformly from all MRT stations; empty commute cache at start                                                                                                     |
| W4  | Fault       | W3 with OneMap failing for 30% of calls, then 100% for 5 minutes (invalid credential), then restored                                                                                 |
| W5  | Bad data    | Monthly ingestion given a file with a renamed column, negative rents and a missing town                                                                                              |
| W6  | Concurrency | 20 parallel joins for the last place in a 5-member group; a preference edit while a search is pending                                                                                |

For E2, record API Gateway admission limits and separate expected 429 throttles from application errors. The skeleton allows 20 requests/s with burst 40, so W2’s sustained 50 requests/s is a throttle test at that configuration, not proof of compute saturation. A capacity run needs an explicitly agreed eval-stage limit that admits W2, and must use the same admitted workload on both targets. The fixed-instance baseline uses isolated worker processes because the local Powertools adapter serializes resolver execution per process; record worker count, vCPUs and CPU credit mode with the evidence.

All load runs use a separate `eval` stage (`-c stage=eval`) so they never disturb the shared `dev` stage, and the stage is destroyed after the evidence is collected.

## Checkpoints

| Date           | Checkpoint               | What must exist                                                                                            |
| -------------- | ------------------------ | ---------------------------------------------------------------------------------------------------------- |
| 12 Oct         | Plan agreed (M0)         | This matrix reviewed; owners accept their rows; decisions D-E1 to D-E7 recorded in #46                     |
| 18 Oct         | Shared group input       | Powertools metrics emitted by the API (latency, cache hits, OneMap calls); `project` tag on every resource |
| 25 Oct         | Usable end-to-end search | Workload generator and k6 scripts committed; E7 running in CI                                              |
| 29 Oct         | Integration              | Dry run of every experiment once on the `eval` stage; revise workloads and thresholds                      |
| 30 Oct – 8 Nov | Evidence collection      | Final runs; results in `docs/evaluation/` with raw data; each issue links its evidence                     |
| 13 Nov         | Report and slides        | #36 summarises system evidence; #45 the cost comparison; #31 the user study; #38 and #39 use them          |

## Decisions to confirm by 12 October

| ID   | Proposal                                                                                                                              |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------- |
| D-E1 | The workloads W1–W6 above, with the W2 peak of 50 requests/s as the "peak semester" assumption                                        |
| D-E2 | E2’s baseline is a `t4g.small` with 2 isolated uvicorn workers; agree runtime/cost and admission limits before running                |
| D-E3 | E10 compares an averages-only view with the per-member view, so the frontend keeps a toggle for the study only                        |
| D-E4 | Load and fault experiments run only on a separate `eval` stage                                                                        |
| D-E5 | Evidence goes in `docs/evaluation/<experiment>/` with the raw data, script version and date                                           |
| D-E6 | The 500 ms target applies to `GET /api/groups/{groupId}/searches/{searchId}` with a warm cache, measured at CloudFront from Singapore |
| D-E7 | OneMap's rate limit for E4 is whatever #3 measures, not the 250/min assumed in the preliminary report                                 |

## Limitations to state in the report

- Load tests run from one location and machine, which caps the request rate we can generate.
- The user study is small (8–12 participants) and indicates usability problems; it is not statistically significant.
- Commute estimates use one departure time and the snapped station, not live conditions or exact addresses (E8 measures the error).
- The on-premise cost model is an estimate built on stated assumptions, not a quote.
