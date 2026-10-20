# FlatSplit hosting cost model: AWS versus on-premise

**Issue:** [#45 — Compare AWS and on-premise hosting costs](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/45) · **Experiment:** E9 in [evaluation-plan.md](https://github.com/horiiiiii032929/CS5225-teams12-2026/blob/main/docs/evaluation-plan.md)
**Draft:** 12 October 2026 · **Updated:** 20 October 2026 · **Owner:** Ming (@lukerspace) · **Reviewer:** Mani (@saravanamani1999) · **Status:** Partially measured — per-request operation counts measured; demand volumes and AWS-side metrics still assumed
**Intended repository path:** `docs/evaluation/E9-cost/cost-model.md` (D-E5: evidence lives in `docs/evaluation/<experiment>/` with raw data, script version and date)

The demand figures are assumptions. What each request _costs in AWS operations_ is no longer an assumption: on 20 October 2026 every DynamoDB, SQS and OneMap call was counted per request against the real Lambda resolver, and those counts replaced the design budgets the model used before (see [Measured per-request operations](#measured-per-request-operations-20-october-2026)). What remains assumed is how many people do these things, how long Lambda runs outside the lookup path, cold-start share, log volume, and the RRU/WRU conversion — all owned by #30 and #34. The on-premise figures are an estimate built on stated assumptions, **not a quote** (required wording, evaluation-plan limitations).

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

**Assumptions that must still be replaced by measurements**, each marked `_source: assumed` in `model/workloads.json`: Lambda duration outside the lookup path (120 ms) and the worker (900 ms), cold-start share (5%), log volume per invocation (2 KB), RRU per read request (2.0), WRU per write (1.5), both cache hit ratios, the demand volumes themselves, and `sustained_rps_per_node` for options B and C. See `evidence/measurement-requests.md` (next to this file) for who owns each one.

## Measured per-request operations (20 October 2026)

`model/measure_operations.py` drives API Gateway v2 events through the real resolver in `flatsplit_api.handlers.http`, with Moto standing in for DynamoDB and SQS and live OneMap upstream, and counts every botocore call, the items inside each transaction, and every OneMap round trip. Raw output: `evidence/measured-operations-20261020.json`. The `/places` rows need the persistent places work from [#14](https://github.com/horiiiiii032929/CS5225-teams12-2026/pull/65), so they were measured with that branch checked out; everything else is on `main`.

| Request                     | DynamoDB reads | Write items | OneMap calls | SQS sends |   Duration |
| --------------------------- | -------------: | ----------: | -----------: | --------: | ---------: |
| `GET /places` (cold)        |            3-5 |        9-11 |            6 |         0 | 557-697 ms |
| `GET /places` (cache hit)   |              5 |           0 |            0 |         0 |   15-18 ms |
| `POST /groups`              |              1 |           3 |            0 |         0 |      36 ms |
| `POST /groups/{id}/members` |              2 |           3 |            0 |         0 |      18 ms |
| `PUT .../members/{id}`      |              4 |           3 |            0 |         0 |      28 ms |
| `GET /groups/{id}`          |              2 |           0 |            0 |         0 |      10 ms |
| `POST .../searches` (first) |              7 |          58 |            0 |        52 |     283 ms |
| `POST .../searches` (again) |              8 |           0 |            0 |         0 |      94 ms |
| `GET .../searches/{id}`     |              7 |           0 |            0 |         0 |      93 ms |

Four corrections came out of this, and the first two are the reason the model's DynamoDB lines moved:

1. **A search start writes one record per pair, not two per job.** The old model charged `jobs × 2`; measurement shows one `PutItem` for every pair that has no usable cached result — 54 of them for a two-member search — plus a three-item transaction. A pair with a usable `COMMUTE#` record at the same routing profile returns from the read before writing or sending anything, so the cache hit ratio removes the write and the message together.
2. **A cold destination lookup writes 9-11 items** (one `PLACE#` per candidate, one `STATION#` per distinct station, one `PLACELOOKUP#`) and makes six OneMap calls. The old model charged it one read and nothing else.
3. **The enqueue is not batched**: exactly one `SendMessage` per enqueued pair.
4. **A cache hit is free of upstream cost**: five reads, no writes, no OneMap call, 15-18 ms against 557-697 ms. That is what makes the lookup cache hit ratio the lever on OneMap quota.

Durations here are laptop durations against Moto, so only the lookup paths feed the model: their cost is real upstream network time, which Lambda pays too. Everything else keeps the assumed 120 ms pending #30. Moto is not DynamoDB, so these are request and item counts, not consumed capacity; the RRU/WRU conversion stays with #34. #15's worker does not exist yet, so its routing call and result write are still assumed.

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

## Comparison (model output, updated 20 October 2026)

Generated by `model/cost_model.py`; raw output in `evidence/cost_model_20261020T103456Z.{md,json,csv}`.
Earlier runs are kept: `evidence/cost_model_20261014T072020Z.*` is the assumption-only version these figures
replace, and `evidence/cost_model_20261012T062840Z.*` is the one quoted in #45 (it assumed 26 towns).

| Option                                            | Quiet US$/mo | Typical US$/mo | Bursty US$/mo | US$ per 1,000 searches (typical) |
| ------------------------------------------------- | -----------: | -------------: | ------------: | -------------------------------: |
| A. AWS serverless — **payable**                   |         1.13 |           1.27 |          2.48 |                             1.27 |
| A. AWS serverless — list price, free tier removed |         8.20 |           8.83 |         13.90 |                             8.83 |
| B. AWS always-on VM                               |        38.67 |          38.84 |         57.70 |                            38.84 |
| C. On-premise                                     |       243.50 |         243.50 |        274.87 |                           243.50 |

Measuring the operation counts moved the serverless total by **+5% at typical demand and +13% in the burst**, all of it in DynamoDB: writes went from US$0.03 to US$0.07 typical and US$0.47 to US$0.70 bursty, reads from US$0.04 to US$0.06 and US$0.27 to US$0.33. Nothing in the comparison's conclusion changes — the gap to option C is still roughly two orders of magnitude — which is itself the useful result: **the on-premise comparison was never sensitive to the per-request accounting**, so the remaining uncertainty that matters is `sustained_rps_per_node` on the on-premise side, not AWS usage.

Free-tier allowances are listed per line item in the generated tables, never netted silently. At typical demand the free tier covers US$7.56 of US$8.83, so **the cloud-versus-on-premise conclusion does not depend on the free tier**: even at list price, option A is roughly 28× cheaper than option C.

### Main cost drivers

| Option                               | Dominant driver                                                                               | Share                     |
| ------------------------------------ | --------------------------------------------------------------------------------------------- | ------------------------- |
| A. AWS serverless, typical (payable) | CloudWatch custom metrics (12 metrics, 10 free) + Secrets Manager flat fee                    | 0.60 + 0.41 of 1.27 (79%) |
| A. AWS serverless, bursty (payable)  | **DynamoDB** reads + writes + PITR, now the largest payable group                             | 1.14 of 2.48 (46%)        |
| A. AWS serverless (list price)       | CloudWatch dashboard (US$3.00) + custom metrics (US$3.60)                                     | ~75% typical              |
| B. AWS always-on VM                  | EC2 instance-hours, billed whether or not anyone searches                                     | ~80%                      |
| C. On-premise                        | Operational effort and the business internet line — **people and connectivity, not hardware** | ~58%                      |

Compute is not the cost driver in any option at this scale. That is the finding worth putting in the report: for a bursty, low-average workload, hosting cost is dominated by _fixed_ commitments (a person, a line, a box, a dashboard), and the serverless model has the fewest of them. The one thing measurement changed here is that in the burst scenario DynamoDB overtakes the fixed CloudWatch and Secrets Manager lines, because per-pair writes scale with demand while a dashboard does not.

### Sensitivity to demand

| Demand (typical scaled)           | A. serverless payable | A. list price | C. on-premise | On-prem nodes |
| --------------------------------- | --------------------: | ------------: | ------------: | ------------: |
| idle — nobody uses it for a month |                  1.11 |          8.12 |        243.50 |             2 |
| ×0.1                              |                  1.13 |          8.19 |        243.50 |             2 |
| ×1 (1,000 searches)               |                  1.27 |          8.83 |        243.50 |             2 |
| ×10                               |                  2.66 |         15.26 |        243.50 |             2 |
| ×100 (100,000 searches)           |                 23.27 |         79.49 |        274.87 |             3 |

Option A tracks demand almost linearly and costs ~US$1.11/month when idle; option C is a step function that charges the same whether traffic is zero or 10× higher, then jumps when the peak needs another node. Measured per-request costs steepen option A's slope — ×100 demand is now US$23.27 payable rather than US$17.62 — but the break-even is still far beyond anything a student project reaches: serverless list price only approaches the on-premise total somewhere above ×250 of typical demand.

**The constraint that bites first is not cost.** The bursty scenario implies **295,200 OneMap calls per month**: 187,200 routing jobs (6,000 searches × 3 stations × 26 routable towns × 40% miss) plus 108,000 from destination lookups (18,000 cold lookups × 6 measured calls). Routing dominates the burst, but at typical demand the ratio inverts: 21,600 lookup calls against 7,800 routing calls, because the commute cache is assumed 90% warm while a 24-hour lookup cache is not. Published quota is 300 calls/min, and #3 did not establish a sustained safe rate; assess feasibility with the three-worker concurrency cap and measured drain/lookup latency, not a calls/min division. Two measured facts now bound this: a cold lookup costs exactly six calls and a cached one costs zero, so the lookup cache hit ratio — an assumption nobody has measured yet — is the single biggest lever on OneMap quota, and it belongs in #3/#27's follow-up rather than in the cost model.

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

# re-measure the per-request operation counts after a handler change
# (needs the dev dependency group for Moto, and a OneMap token for /places)
export ONEMAP_TOKEN=...
uv run --package flatsplit-api python docs/evaluation/e9/model/measure_operations.py
```

Prices come from the AWS Price List bulk API for `ap-southeast-1` (publication date 1 October 2026), captured in `model/prices_ap_southeast_1.json` with the source URL; CloudFront values use the `AP-` usage-type prefix (Asia Pacific price class, which serves Singapore). Refresh before the final report and commit the new file so the figures in the report are reproducible.
