# FlatSplit hosting cost model: AWS versus on-premise

**Issue:** [#45 — Compare AWS and on-premise hosting costs](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/45) · **Experiment:** E9 in [evaluation-plan.md](https://github.com/horiiiiii032929/CS5225-teams12-2026/blob/main/docs/evaluation-plan.md)
**Draft:** 12 October 2026 · **Owner:** Ming (@lukerspace) · **Reviewer:** Mani (@saravanamani1999) · **Status:** Provisional runnable model; historical inputs/outputs require reconciliation before current-cost claims
**Repository path:** `docs/evaluation/e9/cost-model.md` (the original draft proposed `docs/evaluation/E9-cost/cost-model.md`; D-E5 now uses lowercase experiment IDs)

Nothing in this document is a result. Every workload figure is an assumption until #30 and #34 supply measured usage. The on-premise figures are an estimate built on stated assumptions, **not a quote** (required wording, evaluation-plan limitations).

## Status reconciliation — 20 October 2026

The runnable model and dated 12/14 October outputs are preserved, including the original tables below. They are assumption-based scenarios, not the current deployed bill. This documentation update does not change model inputs, rerun the model or recalculate historical totals. The original architecture/driver discussion below describes the model baseline, including components that are still planned.

Before publishing a refreshed result, the model owner must reconcile these inputs:

- **DynamoDB:** the old 7/8-request budget is superseded. The implemented complete status path uses eight calls for two distinct stations and 11 for five when partitions fit one page; claims, submission, pagination and retries add work. Measure the actual workload in #30 instead of treating the old fixed budget as a current fact.
- **Routing:** main resolves non-routable TENGAH directly to `unavailable`; it does not enqueue that pair. There are 27 town records but 26 routable town pairs per distinct destination station. The JSON's statement that TENGAH is enqueued is historical and must be corrected with the next model revision. The historical 187,200-job table and 194,400-job prose use different town counts; neither is a measured monthly total.
- **Destination lookup:** [Ming's 20 October evidence](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/45#issuecomment-6286439604) reports cold lookup cost of `1 + N` upstream calls and repeat-query cache hits of zero for open PR #65. Its Kent Ridge sample used six calls cold and zero warm, through a local handler with live OneMap and Moto. Candidate count and distinct-query/cache-hit rate must drive the lookup estimate; a fixed two-call assumption is superseded. Sample timings are not deployed p95/capacity evidence, and the query cache is not merged on main.
- **Runtime/admission:** main's HTTP Lambda timeout is 30 seconds, not the draft's 10. CDK now defines 100 requests/s, burst 200 for `eval` only; other stages retain 20/40. Verify actual deployed configuration and authorisation before W2; configuration does not establish capacity or a 500 ms result.
- **Resource scope:** the worker/event-source mapping, scheduled ingestion, custom metrics, dashboard and queue/DLQ alarms are not implemented on main. Their model costs remain planned assumptions; SQS idle-poll volume is not an observed charge. Budget alerts are conditional on `budgetEmail` configuration.

Payer-side cost-tag status/history, account allowances, actual worker/usage measurements (#34), node throughput (#30) and final price refresh remain outstanding. The 14 October linked-account billing access denial remains the recorded limitation. See the [measurement requests](evidence/measurement-requests.md) and [deployment handoff](../../aws-dev-handoff.md); no billing or deployment change is claimed.

## Historical model baseline — 12–14 October 2026

## What this answers

E9 asks: _what does FlatSplit cost on AWS compared with on-premise, for the same workload and the same service goals?_ The model therefore has to produce four things, which are the acceptance criteria of #45:

1. Comparable quiet, typical and bursty workload scenarios, with documented assumptions.
2. Normal AWS hosting cost against an on-premise model covering hardware, electricity, storage/backups and operational effort, with free-tier credits shown **separately**.
3. The main cost drivers and the sensitivity to demand, refined with measured usage.
4. A comparison and its evidence, linkable from the final report (#36, #38).

## Three options, not two

The report's claim is about hosting _models_, so a bare "AWS versus a box" comparison would be unfair in both directions: it would credit serverless with the free tier while charging on-premise for a machine sized for the peak. The model therefore prices three options on the same workload:

| Option                  | What it is                                                                                                                               | Why it is in the comparison                                                                                        |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| **A. AWS serverless**   | The deployed architecture: CloudFront + S3, HTTP API, Lambda (arm64, 256 MB), DynamoDB on-demand, SQS + DLQ, Secrets Manager, CloudWatch | What we actually built (T1, T8, T9 in the technique matrix)                                                        |
| **B. AWS always-on VM** | The same Powertools handler under uvicorn on `t4g.small` instances, 24×7, still using DynamoDB and S3                                    | Isolates "serverless versus always-on" from "cloud versus on-premise". This is the cloud twin of the D-E2 baseline |
| **C. On-premise**       | Owned hardware sized for the W2 peak, in a room we power and cool, patched by a person                                                   | The report's on-premise alternative                                                                                |

B is the honest middle column: it shows how much of the saving comes from AWS and how much comes from _not paying for idle capacity_.

## Workload scenarios (provisional)

Scenarios are defined in `model/workloads.json` and derive billable units from user-level assumptions, so one edit changes every table. Monthly figures, not peak figures, except where stated.

|                                             |             Quiet |   Typical |                            Bursty |
| ------------------------------------------- | ----------------: | --------: | --------------------------------: |
| Maps to                                     | between semesters | W1 Steady |           W2 Burst + W3 Long tail |
| Groups created / month                      |                50 |       500 |                             3,000 |
| Members per group                           |                 3 |         3 |                                 3 |
| Searches / month                            |               100 |     1,000 |                             6,000 |
| Result polls per search                     |                20 |        20 |                                20 |
| API requests / month                        |             3,500 |    35,000 |                           276,000 |
| Commute cache hit ratio (assumed)           |               80% |       90% |                               60% |
| Commute jobs = OneMap routing calls / month |             1,560 |     7,800 |                           187,200 |
| Burst events / month                        |                 0 |         0 | 4 × (1→50 req/s ramp, 5 min hold) |
| Peak admitted rate used for sizing          |                 — |         — |                   50 req/s (D-E1) |

Fixed facts behind the derivation, taken from the team's merged documents rather than invented: 27 HDB towns each represented by one MRT station (26 of them routable) ([backend-design.md](https://github.com/horiiiiii032929/CS5225-teams12-2026/blob/main/docs/backend-design.md)); 3 distinct member stations × 27 towns = 81 commute pairs per search; a first search costs 8 single-partition DynamoDB requests and each later result read costs 7 ([api-contract.md](https://github.com/horiiiiii032929/CS5225-teams12-2026/blob/main/docs/api-contract.md), access patterns A1/A6/A7); Lambda is arm64 at 256 MB with a 10 s timeout ([infra/aws/src/api.ts](https://github.com/horiiiiii032929/CS5225-teams12-2026/blob/main/infra/aws/src/api.ts)); the HTTP API stage throttles at 20 req/s burst 40, so admitting W2's 50 req/s needs an explicit eval-stage limit (D-E1, D-E2).

**Assumptions that must be replaced by measurements**, each marked `_source: assumed` in `model/workloads.json`: Lambda duration (120 ms API, 900 ms worker), cold-start share (5%), log volume per invocation (2 KB), RRU per read request (2.0), WRU per write (1.5), commute cache hit ratios, and `sustained_rps_per_node` for options B and C. See `evidence/measurement-requests.md` (next to this file in the #45 deliverable) for exactly who owns each one.

## AWS cost drivers and their on-premise counterparts

| AWS line item                               | What drives it                                                                           | On-premise counterpart                                                                                    |
| ------------------------------------------- | ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| Lambda requests + GB-seconds                | invocations × duration × memory                                                          | A share of the server's purchase price and its idle power                                                 |
| API Gateway HTTP API requests               | every `/api/*` call                                                                      | The same server's web listener (no separate charge, no separate scaling either)                           |
| DynamoDB RRU/WRU                            | the 7–8 requests per search read, job claims and result writes                           | PostgreSQL on the same box: no per-request charge, but disk, tuning, backups and a restore drill          |
| DynamoDB storage + PITR                     | table size; PITR is charged per GB-month                                                 | RAID/mirrored disks plus a backup schedule somebody has to verify                                         |
| S3 + CloudFront                             | web build size, page loads, data transfer out                                            | Bandwidth on the business line, plus no global edge at all                                                |
| SQS requests                                | 3 requests per commute job **plus idle long polls from the Lambda event-source mapping** | A local queue (Redis/RabbitMQ) to install, monitor and restart                                            |
| Secrets Manager                             | 1 secret per month, flat                                                                 | A file with 600 permissions and a rotation habit                                                          |
| CloudWatch logs, metrics, alarms, dashboard | log GB ingested, custom metric count, alarm count                                        | Prometheus/Grafana or nothing; if nothing, the comparison is not like-for-like and the report must say so |
| AWS Budgets                                 | free                                                                                     | No equivalent; cost is sunk at purchase                                                                   |

Two drivers are easy to miss and both are in the model: **CloudWatch is the largest payable serverless line at prototype scale** (custom metrics beyond the 10 free, and the dashboard beyond the 3 free), and **SQS long-poll receives are billed even when nobody uses the app** — an idle serverless deployment is cheap, but not exactly zero.

## On-premise model

Full assumptions in `model/onprem.json`. Sizing follows D-E2: one node is a `t4g.small`-class machine (2 vCPU / 2 GiB) running the same handler under two isolated uvicorn workers, and the cluster is sized for the **W2 peak**, with one spare node because a single box has no availability story.

| Category                               | Assumption                                                                                              | Monthly (US$) |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------- | ------------: |
| Hardware depreciation                  | 2 × S$1,200 node + UPS S$350 + switch S$250 + backup disks S$200 + spares S$150, 36-month straight line |         72.70 |
| Electricity                            | 15 W idle / 45 W load, 15% duty cycle, PUE 1.5, S$0.3191/kWh (SP Group household tariff, Q3 2026)       |         10.65 |
| Room cooling share                     | assumption beyond PUE                                                                                   |         11.72 |
| Business internet + static IP          | needed for a public endpoint                                                                            |         62.50 |
| Offsite backup                         | nightly dumps to object storage                                                                         |          6.25 |
| Domain + TLS                           | Let's Encrypt = 0                                                                                       |          1.56 |
| Operational effort                     | 4 h/month × S$25/h (patching, TLS, restore drills, incidents)                                           |         78.12 |
| **Total (quiet and typical, 2 nodes)** |                                                                                                         |    **243.50** |
| **Total (bursty, 3 nodes)**            |                                                                                                         |    **274.87** |

Named but excluded, so the reader can judge the bias: room rent and physical security (assumed free on campus), hardware failure beyond the spares buffer, DDoS protection (CloudFront includes Shield Standard), the one-off time to build a deployment pipeline, and the cost of downtime — the single-box model has no SLA.

## Comparison (provisional model output, updated 14 October 2026)

Generated by `model/cost_model.py`; raw output in `evidence/cost_model_20261014T072020Z.{md,json,csv}`.
The superseded 12 October run (`evidence/cost_model_20261012T062840Z.*`) is kept because its figures are the ones
quoted in #45; it assumed 26 towns. The 27-town correction from the #2 data profile (PR #52) moves only the bursty
column, by 2 cents on the payable serverless option.

| Option                                            | Quiet US$/mo | Typical US$/mo | Bursty US$/mo | US$ per 1,000 searches (typical) |
| ------------------------------------------------- | -----------: | -------------: | ------------: | -------------------------------: |
| A. AWS serverless — **payable**                   |         1.13 |           1.21 |          2.19 |                             1.21 |
| A. AWS serverless — list price, free tier removed |         8.19 |           8.77 |         13.63 |                             8.77 |
| B. AWS always-on VM                               |        38.67 |          38.78 |         57.41 |                            38.78 |
| C. On-premise                                     |       243.50 |         243.50 |        274.87 |                           243.50 |

Free-tier allowances are listed per line item in the generated tables, never netted silently. At typical demand the free tier covers US$7.56 of US$8.77, so **the cloud-versus-on-premise conclusion does not depend on the free tier**: even at list price, option A is roughly 28× cheaper than option C.

### Main cost drivers

| Option                         | Dominant driver                                                                               | Share               |
| ------------------------------ | --------------------------------------------------------------------------------------------- | ------------------- |
| A. AWS serverless (payable)    | CloudWatch custom metrics (12 metrics, 10 free) + Secrets Manager flat fee                    | 0.60 + 0.41 of 1.21 |
| A. AWS serverless (list price) | CloudWatch dashboard (US$3.00) + custom metrics (US$3.60)                                     | ~75%                |
| B. AWS always-on VM            | EC2 instance-hours, billed whether or not anyone searches                                     | ~80%                |
| C. On-premise                  | Operational effort and the business internet line — **people and connectivity, not hardware** | ~58%                |

Compute is not the cost driver in any option at this scale. That is the finding worth putting in the report: for a bursty, low-average workload, hosting cost is dominated by _fixed_ commitments (a person, a line, a box, a dashboard), and the serverless model has the fewest of them.

### Sensitivity to demand

| Demand (typical scaled)           | A. serverless payable | A. list price | C. on-premise | On-prem nodes |
| --------------------------------- | --------------------: | ------------: | ------------: | ------------: |
| idle — nobody uses it for a month |                  1.11 |          8.12 |        243.50 |             2 |
| ×0.1                              |                  1.12 |          8.18 |        243.50 |             2 |
| ×1 (1,000 searches)               |                  1.21 |          8.77 |        243.50 |             2 |
| ×10                               |                  2.09 |         14.65 |        243.50 |             2 |
| ×100 (100,000 searches)           |                 17.62 |         73.44 |        274.87 |             3 |

Option A tracks demand almost linearly and costs ~US$1.11/month when idle; option C is a step function that charges the same whether traffic is zero or 10× higher, then jumps when the peak needs another node. On this model the break-even is far beyond anything a student project reaches: serverless list price only approaches the on-premise total somewhere above ×300 of typical demand.

**The constraint that bites first is not cost.** In the bursty scenario the model implies 194,400 OneMap routing jobs per month (6,000 searches × 3 stations × 27 towns × 40% miss rate). This is a conservative per-search demand estimate: in-flight deduplication and cache reuse may lower actual jobs, while retries and destination lookups add calls.

The call count per job is now fixed by the implemented worker (#15), not assumed: **one routing call per delivery**, and asking for three itineraries is still one call. A job is delivered again only on a transient failure, so the worst case is three calls for a job that keeps being throttled (`COMMUTE_MAX_RECEIVES`), while a terminal failure such as a 404 spends exactly one. Published quota is 300 calls/min, and #3 did not establish a sustained safe rate, so the bound in force is the event source's concurrency cap of three. [Draining a real queue at that concurrency](../worker-queue/) measured **165 calls/min**, below the 180 the 992 ms routing p50 alone implies because each invocation also writes its result; the cap would be reached at about concurrency five. Drain time, not a calls/min division, is what decides feasibility — at the measured rate 5,400 cold pairs take about 33 minutes. That harness emulates AWS and replays OneMap's latency, so E4 (#27) still has to confirm it on real infrastructure. The cache hit ratio and the queue — not the AWS bill — decide whether the burst scenario is feasible.

## Open questions for the team

1. **Account type (blocks the free-tier column).** Is the deployment account a new-account credit-plan AWS account or an AWS Academy/classroom account? The always-free allowances used here (Lambda 1M requests, CloudFront 1 TB, SQS 1M requests, DynamoDB 25 GB) differ from the 12-month ones (API Gateway, S3). #34 should confirm against the real bill.
2. **Cost allocation tag.** `infra/aws/src/app.ts` already tags every resource `project=flatsplit`, `stage=<stage>`. The tag must be activated as a cost allocation tag before Cost Explorer can filter by it. Late activation does not necessarily lose earlier tagged spend: [AWS supports management-account tag backfill for up to twelve months](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/cost-allocation-backfill.html), provided the tag was already assigned to the resource during that period. Backfill cannot invent historical resource tags, applies the current activation status of all tag keys, and billing views refresh after processing. Record activation/backfill eligibility and the actual available measurement window. Owner: the billing-authorised management/payer-account operator, to be identified in #4; do not assume the application deployer has billing access.
3. **`sustained_rps_per_node`** (currently a placeholder of 25 req/s) is the single number that decides how many nodes options B and C need. #30/E2 must measure it under W2 with the 500 ms target in force.
4. Is the 4 h/month operational-effort assumption acceptable to the team, and do we price it at S$25/h? It is 32% of the on-premise total, so the report should defend it or vary it.
5. Does the team want the comparison stated per month, per 1,000 searches, or both? The slides (#39) probably want one number.

## Limitations to state in the report

- The on-premise model is an estimate from stated assumptions, not a quote; hardware prices, the electricity tariff (household, not non-residential) and the SGD/USD rate of 1.28 are all assumptions.
- The free tier is shown separately, but which allowances apply depends on the account type (open question 1).
- Serverless usage figures are derived from assumed per-request durations and log volumes; until #30 and #34 report, the AWS totals could move by a factor of a few — though not by the ~28× that separates the options.
- The comparison prices the same _workload_, not the same _availability_. Option A is multi-AZ by default; option C is one room with one spare machine. The model charges on-premise nothing for that gap.
- CloudWatch dashboard pricing (US$3.00/dashboard/month) is AWS's published list price and is the only figure not taken from the Price List API export.

## Reproducing this

```bash
cd docs/evaluation/e9/model
python3 cost_model.py            # writes ../evidence/cost_model_<utc>.{md,json,csv}
python3 cost_model.py --scale 10 # demand sensitivity
```

Prices come from the AWS Price List bulk API for `ap-southeast-1` (publication date 1 October 2026), captured in `model/prices_ap_southeast_1.json` with the source URL; CloudFront values use the `AP-` usage-type prefix (Asia Pacific price class, which serves Singapore). Refresh before the final report and commit the new file so the figures in the report are reproducible.
