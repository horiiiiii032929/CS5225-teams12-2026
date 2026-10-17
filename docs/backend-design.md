# FlatSplit backend and AWS design

**Updated:** 14 October 2026 · **Owner:** Shyam · **Status:** Implementation baseline under the PM blocker-resolution request. See [api-contract.md](api-contract.md) for the reconciled data/transport policy and explicit prototype defaults. Deployment and feature implementation remain separate issues.

This document turns the preliminary report (sections 3, 4.2, 5.2, 6) and the wireframe decisions in [user-journey.md](user-journey.md) into a buildable backend. It records each AWS service's purpose, permissions and cost assumptions, as `infra/aws/AGENTS.md` requires before resources are added.

## Changes from the preliminary report

| Report says                             | Proposal                                                                  | Why                                                                                                                                      |
| --------------------------------------- | ------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| API Gateway REST API                    | API Gateway **HTTP API**                                                  | ~70% cheaper per request, lower latency; stage throttling covers our needs                                                               |
| Optional Cognito / "Cognito JWT"        | **Capability tokens** (invite and per-member), stored only as hashes      | Report scope says no login; matches D11. Final report must be corrected                                                                  |
| Commutes via OneMap and LTA             | **OneMap PT routing**; LTA DataMall optional (station list only)          | LTA DataMall has no journey-planner endpoint                                                                                             |
| Web on S3 + CloudFront, separate API    | CloudFront serves the SPA **and** `/api/*` → HTTP API                     | Same origin: no CORS, one URL, matches the Vite `/api` proxy                                                                             |
| Destination per member                  | Free-text address, geocoded by OneMap, **snapped to nearest MRT station** | Bounded cache: ~200 stations × 27 current HDB towns ≈ 5,400 pairs, about 25 min at worker concurrency three (extrapolated, not measured) |
| PITR to recover bad data                | **Versioned rent snapshots + `CURRENT` pointer**, PITR kept as backup     | "Searches continue on the last validated snapshot" becomes an atomic pointer flip                                                        |
| Provisioned Concurrency for cold starts | Measure first; arm64, small package, Powertools                           | Provisioned Concurrency is billed while idle, which conflicts with the "zero idle cost" goal                                             |

## Architecture

```text
CloudFront ─┬─ /*      → S3 (web build, private, OAC)
            └─ /api/*  → HTTP API ─┬─ groups-api  ─┐
                                   ├─ search-api  ─┤→ DynamoDB (single table, on-demand)
                                   └─ places-api  ─┘   OneMap search proxy
search-api (cache miss) → SQS commute-jobs → commute-worker (max concurrency ≈3) → OneMap routing
                                     └→ DLQ after 3 attempts → pair marked UNAVAILABLE
EventBridge Scheduler (monthly) → ingest-rental → S3 raw/ + DynamoDB snapshot → seed commute jobs
Secrets Manager: OneMap account credentials; access token cached in Lambda memory
```

All functions are Python 3.13 on arm64 using AWS Lambda Powertools (routing, validation, logging, metrics, tracing). No VPC, so no NAT Gateway.

## API contract and data model

The endpoints, request and response shapes, errors, DynamoDB items and access patterns are specified in [api-contract.md](api-contract.md). In summary:

- `POST /groups`, `GET /groups/{id}`, `POST /groups/{id}/members`, `PUT /groups/{id}/members/{memberId}` for group input, authorised by invite and member tokens.
- `GET /places` for destination search with MRT-station snapping.
- `POST /groups/{id}/searches` and `GET /groups/{id}/searches/{searchId}?priority=` for queued commute lookups, status, and ranked and excluded towns with per-member explanations.
- One DynamoDB table with no scans or secondary indexes; search-ID and per-revision reservations plus consistent revision fences add point reads beyond the original 7/8-request sketch. A warm complete status read with five distinct stations uses 11 requests when partitions fit one page; cold claims/enqueues, pagination and retries are additional. #30 must measure latency and cost.

Search status is derived when it is read: if any required commute pair is `pending`, the search is pending. This avoids fan-in bookkeeping. Commute jobs use conditional pending leases and idempotent workers. Failed enqueue and expired leases are recoverable; the contract describes the claim and retry rules.

### Search producer and status implementation (#16/#18)

The API now implements member-authorised submission, idempotent revision reservations, pinned rent/cache reads, pending/complete/stale status, ranking integration and `latestSearch` composition. It packages the reviewed 27-town projection, including non-routable TENGAH. Missing snapshots return 503; unavailable/missing inputs never become invented recommendations.

The SQS source queue/DLQ exist in CDK to carry cache-miss work, not to perform routing in the HTTP request. Both use SQS-managed encryption and deny non-TLS access. Source visibility is 180 seconds, retention four days, and redrive follows three receives; DLQ retention is 14 days. `Api.commuteJobsQueue` is the consumer attachment point, `CommuteQueueUrl` is the output, and `COMMUTE_QUEUE_URL` configures the producer. #15 must consume that same queue; no worker is attached by this change.

The HTTP role can send to only that queue (no receive/delete), read rent/place partitions, read/write group partitions and read/claim/delete commute items. Partition-scoped DynamoDB grants require a non-null `dynamodb:LeadingKeys`. Conditional 900-second job leases recover failed sends/crashes; worker completion must be fenced by matching `jobId` and pending status. The [API contract](api-contract.md#16-producer-and-15-worker-handoff) records the payload and retry/profile semantics.

Cost remains a request-based design assumption, not a billing measurement: this adds two queues, DynamoDB claims/metadata reads and SQS sends, without a VPC or continuously running compute. API timeout is 30 seconds to admit cold submissions; cold work can include 135 claims and 130 sends for five distinct stations, so the latency target still needs #30 evidence. Local tests use seeded rent/place records and injected worker-contract completions. Live ingestion (#10), place persistence (#14), routing/consumer/DLQ work (#15/#27), deployment and deployed performance acceptance remain separate.

## Data assumptions

- **Rent:** data.gov.sg "Renting Out of Flats" (2021 onwards), dataset `d_c9f57187485a850908655db0e8cfe651`; see the [source profile and version 1 aggregation rules](hdb-rental-data-profile.md). Store trailing-12-month median, P25 and P75 whole-flat rent for every non-empty town/flat-type group. Only summaries whose block-cluster bootstrap 95% median interval is at most 10% of the median are eligible for recommendations. Rent per person is the eligible median divided by group size; utilities are excluded (D03).
- **Flat type by group size (D12, PM baseline):** 2 → 3-ROOM, 3 → 4-ROOM, 4–5 → 5-ROOM.
- **Town point:** each source-controlled HDB town is represented by its main MRT station or interchange (the [versioned principal-station table](evaluation/feasibility/data/towns.json), using exact HDB keys (`CENTRAL`, not archived `CENTRAL AREA`); TENGAH has a documented unavailable reference). The September 2026 rental source has 27 town values, including `TENGAH`.
- **Commute:** OneMap public-transport route from the town point to the destination's snapped station, on a weekday at 08:30 departure, requesting three itineraries and selecting their minimum duration. Destination selection is explicit, station snapping is bounded to 1,000 m with a warning above 800 m, and the result is labelled station-to-station, not door-to-door. All interchange aliases use an application-owned canonical `stationKey` and a pinned routing coordinate. A route that cannot be found is UNAVAILABLE; it is never treated as zero minutes (D06).
- **Ranking:** a port of `evaluateAreas` (same weights and scales), with parity tests on the wireframe fixtures. Scales stay _Open_ until the ranking task validates them (D07).

## Security

- Tokens are 256-bit random values. Only SHA-256 hashes are stored. An invite token can only join; it cannot read or edit the group (D11). Invite tokens travel in the URL fragment, so they never reach server logs.
- Each Lambda has its own role scoped to the table, queue, bucket or secret it actually uses. There are no wildcard resource grants.
- OneMap credentials are kept in Secrets Manager and never sent to the browser. `/places` proxies the search.
- Logs never contain tokens or member preference values.
- HTTP API stage throttling (20 requests/s, burst 40) limits abuse. Only the isolated `eval` stage uses 100 requests/s, burst 200 so E2 can admit its hypothesised 50 requests/s workload; account quotas and run authorization still require verification. Per-function reserved concurrency is added only once the account's Lambda concurrency quota is raised above the default for new accounts, because reserving below it fails.

## Cost assumptions (ap-southeast-1, prototype scale)

| Service                   | Assumption                                         | Expected monthly cost               |
| ------------------------- | -------------------------------------------------- | ----------------------------------- |
| Lambda (arm64)            | < 100k invocations, 256 MB                         | Free tier                           |
| HTTP API                  | < 100k requests                                    | < US$0.20                           |
| DynamoDB on-demand + PITR | < 1 GB, < 1M request units                         | < US$1                              |
| S3 + CloudFront           | Web build < 5 MB, low traffic                      | Free tier                           |
| SQS                       | < 10k messages                                     | Free tier                           |
| Secrets Manager           | 1 secret                                           | US$0.40                             |
| CloudWatch                | Logs (1-week retention), one dashboard, few alarms | ≈ US$3 (dashboard is the main cost) |

An AWS Budget with alerts at US$20, 50 and 100 (report section 6.2) is defined in CDK.

## Evaluation hooks

- Powertools metrics: search latency, commute cache-hit ratio, OneMap call latency and errors, jobs enqueued.
- SQS `ApproximateAgeOfOldestMessage` and DLQ depth alarms.
- k6 load test against warm-cache and cold-cache searches for p50, p95 and p99 latency (M5).
- Fault injection: transient 429/5xx/transport errors exercise bounded retry and DLQ recovery; permanent input/no-route errors do not retry. A routing 401 or a search HTTP-200 token warning exercises credential refresh/alerting. The plan separates rejected rent input from PITR restoration into a new isolated table.

## Ownership

Implementation follows the GitHub issues under the planning hubs #41 (frontend), #42 (data) and #43 (backend and AWS). The parts of this design map to them as follows.

| Part                                                    | Issues                  | Pair            |
| ------------------------------------------------------- | ----------------------- | --------------- |
| CDK stack, deployment and CI                            | #4                      | Backend and AWS |
| API contract and access patterns                        | #6                      | Backend and AWS |
| Group persistence, tokens and group APIs                | #11, #12                | Backend and AWS |
| Destination and job-status APIs, search read path       | #16, #18                | Backend and AWS |
| Constraint filtering, fairness ranking, explanations    | #21, #22                | Backend and AWS |
| Rent profile, ingestion, summaries, snapshot protection | #2, #9, #10, #28        | Data            |
| OneMap feasibility, geocoding, commute worker, DLQ      | #3, #14, #15, #27       | Data            |
| End-to-end tests, latency, reliability, evaluation      | #29, #30, #35, #36, #46 | Backend and AWS |

The data pair's Lambdas (ingestion and the commute worker) live in this repository's Python workspace and CDK stack. They read and write the items described in the contract.

## PM implementation defaults and remaining evaluation

On 14 October, the blocker-resolution request adopts the contract's equal split/group-size mapping, any-ready-member search, 30-day fixed expiry and bounded station-selection policy for this prototype. These are product defaults, not upstream-proven occupancy/price facts or a claim of six-person sign-off. Group removal/recovery/resizing remain outside this version. Ranking retains the wireframe scales until #22 validates parity; no performance/fairness result is claimed. Runtime/deployed acceptance follows the owning issues, and pair feedback can revise this baseline through a reviewed PR.
