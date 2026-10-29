# FlatSplit backend and AWS design

**Updated:** 20 October 2026 (status reconciliation; original PM baseline: 14 October) · **Owner:** Shyam · **Status:** Design baseline with partial implementation on main. See [api-contract.md](api-contract.md) for the reconciled data/transport policy and explicit prototype defaults. Deployment and feature implementation remain separate issues.

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

The diagram preserves the target architecture. On main, group, search and place routes share **one HTTP Lambda**; the three API labels below are logical responsibilities, not separate deployed functions. CDK defines the table, hosting, source/DLQ queues and the private raw-rental evidence bucket/Lambda from #9. The commute worker, terminal-failure/DLQ handling, monthly scheduler, rent publication and automatic post-ingestion commute seeding are not implemented on main; the feasibility archive contains a standalone seed script. The last recorded shared deployment is 14 October from `4394195`; see the [deployment handoff](aws-dev-handoff.md). Raw rent ingestion is implemented locally in #9, while summary publication remains #10 work.

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

The current HTTP Lambda uses Python 3.13 on arm64 with Powertools routing, validation and logging, 256 MB memory and a 30-second timeout. Metrics/tracing and the worker instrumentation below are evaluation requirements, not completed instrumentation. No VPC, so no NAT Gateway. CDK creates a Secrets Manager placeholder for a manually rotated OneMap access token; its current deployed value was not verified by this reconciliation. Account-credential storage and automatic token renewal in the target design are not implemented.

## API contract and data model

The endpoints, request and response shapes, errors, DynamoDB items and access patterns are specified in [api-contract.md](api-contract.md). In summary:

- `POST /groups`, `GET /groups/{id}`, `POST /groups/{id}/members`, `PUT /groups/{id}/members/{memberId}` for group input, authorised by invite and member tokens.
- `GET /places` for destination search with MRT-station snapping.
- `POST /groups/{id}/searches` and `GET /groups/{id}/searches/{searchId}?priority=` for queued commute lookups, status, and ranked and excluded towns with per-member explanations.
- One DynamoDB table with no scans or secondary indexes; search-ID and per-revision reservations plus consistent revision fences add point reads beyond the original 7/8-request sketch. A warm complete status read with five distinct stations uses 11 requests when partitions fit one page; cold claims/enqueues, pagination and retries are additional. #30 must measure latency and cost.

Search status is derived when it is read: if any required commute pair is `pending`, the search is pending. This avoids fan-in bookkeeping. The producer implements conditional pending leases and enqueue recovery; #15 must implement idempotent worker completion. Failed enqueue and expired leases are recoverable; the contract describes the claim and retry rules.

### Search producer and status implementation (#16/#18)

The API now implements member-authorised submission, idempotent revision reservations, pinned rent/cache reads, pending/complete/stale status, ranking integration and `latestSearch` composition. It packages the reviewed 27-town projection, including non-routable TENGAH. Missing snapshots return 503; unavailable/missing inputs never become invented recommendations.

The SQS source queue/DLQ exist in CDK to carry cache-miss work, not to perform routing in the HTTP request. Both use SQS-managed encryption and deny non-TLS access. Source visibility is 180 seconds, retention four days, and redrive follows three receives; DLQ retention is 14 days. `Api.commuteJobsQueue` is the consumer attachment point, `CommuteQueueUrl` is the output, and `COMMUTE_QUEUE_URL` configures the producer. #15 must consume that same queue; no worker is attached by this change.

The HTTP role can send to only that queue (no receive/delete), read rent/place partitions, read/write group partitions and read/claim/delete commute items. Partition-scoped DynamoDB grants require a non-null `dynamodb:LeadingKeys`. Conditional 900-second job leases recover failed sends/crashes; worker completion must be fenced by matching `jobId` and pending status. The [API contract](api-contract.md#16-producer-and-15-worker-handoff) records the payload and retry/profile semantics.

Cost remains a request-based design assumption, not a billing measurement: this adds two queues, DynamoDB claims/metadata reads and SQS sends, without a VPC or continuously running compute. API timeout is 30 seconds to admit cold submissions; cold work can include 135 claims and 130 sends for five distinct stations, so the latency target still needs #30 evidence. Local tests use seeded rent/place records and injected worker-contract completions. Live summary publication (#10), place persistence (#14), routing/consumer/DLQ work (#15/#27), deployment and deployed performance acceptance remain separate.

### Local frontend integration (#7/#17)

The frontend now calls the group and search APIs for creation, invite join, saved-membership reload, readiness polling and search submission/status/retry. It validates responses through generated public contracts derived from the resolver's OpenAPI; generation drift is checked in CI. This is client implementation only: local browser QA uses Moto and seeded preferences/rent/place records plus conditional injected worker results. Live member preference forms, complete comparisons, actual data/worker operation and integrated deployment remain outstanding. See the [README flow and acceptance boundary](../README.md#frontend-implementation--7-and-17).

## Data assumptions

- **Rent:** data.gov.sg "Renting Out of Flats" (2021 onwards), dataset `d_c9f57187485a850908655db0e8cfe651`; see the [source profile and version 1 aggregation rules](hdb-rental-data-profile.md). Store trailing-12-month median, P25 and P75 whole-flat rent for every non-empty town/flat-type group. Only summaries whose block-cluster bootstrap 95% median interval is at most 10% of the median are eligible for recommendations. Rent per person is the eligible median divided by group size; utilities are excluded (D03).
- **Flat type by group size (D12, PM baseline):** 2 → 3-ROOM, 3 → 4-ROOM, 4–5 → 5-ROOM.
- **Town point:** each source-controlled HDB town is represented by its main MRT station or interchange (the [versioned principal-station table](evaluation/feasibility/data/towns.json), using exact HDB keys (`CENTRAL`, not archived `CENTRAL AREA`); TENGAH has a documented unavailable reference). The September 2026 rental source has 27 town values, including `TENGAH`.
- **Commute:** OneMap public-transport route from the town point to the destination's snapped station, on a weekday at 08:30 departure, requesting three itineraries and selecting their minimum duration. Destination selection is explicit, station snapping is bounded to 1,000 m with a warning above 800 m, and the result is labelled station-to-station, not door-to-door. All interchange aliases use an application-owned canonical `stationKey` and a pinned routing coordinate. A route that cannot be found is UNAVAILABLE; it is never treated as zero minutes (D06).
- **Ranking:** the merged engine ports `evaluateAreas` with the same weights and scales; tests establish fixture parity for all three priorities, including fractional commute handling. D07 remains a fairness hypothesis requiring empirical user evaluation; parity does not establish deployed recommendation quality.

### Raw rental ingestion (#9)

The ingestion Lambda calls the official data.gov.sg metadata and whole-dataset export APIs, validates the exact six-column schema, the reviewed 27-town inventory, all six flat types, a complete trailing 12-month window, and agreement between the CSV's latest month and the source metadata coverage end. Valid evidence is written first under `raw/source_month=<YYYY-MM>/retrieved_at=<UTC>/<sha256>`, followed by a manifest and the `raw/current.json` pointer. The pointer is read before publication so an older source month or retrieval cannot replace the current snapshot; an ETag condition also prevents an overlapping run from overwriting a pointer that changed during the write. Invalid input is retained under `rejected/` and never updates the pointer.

The Lambda is configured with 1024 MiB memory and a 10-minute timeout. The source body remains bounded at 64 MiB, while API polling and response limits are bounded in the client. After valid evidence is archived, #10 derives the trailing-12-month summaries in the same invocation and writes immutable `RENT#<snapshotId>` items before conditionally advancing `RENT/CURRENT`. The summary publisher writes only `RENT` and `RENT#*` keys; an incomplete publication is never made current and can be retried idempotently. Raw and rejected evidence writes remain append-only. Monthly scheduling remains a separate operational concern.

## Security

- Tokens are 256-bit random values. Only SHA-256 hashes are stored. An invite token can only join; it cannot read or edit the group (D11). Invite tokens travel in the URL fragment, so they never reach server logs.
- Each Lambda has its own role scoped to the table, queue, bucket or secret it actually uses. There are no wildcard resource grants.
- OneMap credentials are kept in Secrets Manager and never sent to the browser. `/places` proxies the search.
- Logs never contain tokens or member preference values.
- HTTP API stage throttling (20 requests/s, burst 40) limits abuse. Only the isolated `eval` stage uses 100 requests/s, burst 200 so E2 can admit its hypothesised 50 requests/s workload; account quotas and run authorization still require verification. Per-function reserved concurrency is added only once the account's Lambda concurrency quota is raised above the default for new accounts, because reserving below it fails.

## Cost assumptions (ap-southeast-1, prototype scale)

The table below preserves the 14 October design estimates, not a measured bill or an inventory of provisioned resources. Account-specific free-tier eligibility is unverified. The planned dashboard, custom metrics and queue alarms are absent on main; worker/queue-consumption costs cannot describe a live worker yet. See the [E9 reconciliation](evaluation/e9/cost-model.md#status-reconciliation--20-october-2026) for superseded request assumptions and pending model inputs.

| Service                   | Assumption                                         | Expected monthly cost               |
| ------------------------- | -------------------------------------------------- | ----------------------------------- |
| Lambda (arm64)            | < 100k invocations, 256 MB                         | Free tier                           |
| HTTP API                  | < 100k requests                                    | < US$0.20                           |
| DynamoDB on-demand + PITR | < 1 GB, < 1M request units                         | < US$1                              |
| S3 + CloudFront           | Web build < 5 MB, low traffic                      | Free tier                           |
| SQS                       | < 10k messages                                     | Free tier                           |
| Secrets Manager           | 1 secret                                           | US$0.40                             |
| CloudWatch                | Logs (1-week retention), one dashboard, few alarms | ≈ US$3 (dashboard is the main cost) |

An AWS Budget with alerts at US$20, 50 and 100 (report section 6.2) is defined in CDK and instantiated only when `budgetEmail` is supplied. Its definition is not evidence that billing alerts are active in the shared account.

## Operational alerts (#27)

The commute queue, its three receives and its dead-letter queue were already in place; what was missing was anybody finding out. `infra/aws/src/alarms.ts` adds three alarms, all notifying one SNS topic so later alerts attach to the same place:

| Alarm                 | Fires when                                                | Why that threshold                                                                                                                                 |
| --------------------- | --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `CommuteDlqNotEmpty`  | the dead-letter queue holds a message for five minutes    | the DLQ is meant to hold only what the consumer could not account for at all, so one message is already an event                                   |
| `CommuteJobsStalled`  | the oldest job has waited more than 9 minutes, twice over | 180-second visibility across three receives is the longest a healthy pair can take; past that nothing is draining and no search can complete       |
| `OneMapTokenExpiring` | the API handler logs `onemapTokenWarning`                 | the token is a three-day JWT with no renewal endpoint, and a lookup still answers 200 during the grace period, so that log line is the only signal |

The token warning is published from the structured log through a metric filter rather than counted in the application, because the token can expire with no traffic at all and a metric nobody emits cannot alarm. Missing data is the healthy case for all three, so an idle stage does not alarm. The email subscriber is optional; the alarms and their state history exist either way.

Inspecting and redriving the dead-letter queue, once something is in it:

```bash
aws sqs receive-message --queue-url "$DLQ_URL" --max-number-of-messages 10 \
  --message-attribute-names All --visibility-timeout 0
aws sqs start-message-move-task \
  --source-arn "$DLQ_ARN" --destination-arn "$JOBS_ARN"
```

A redrive is only correct once the cause is fixed, and it is not a way to recover a pair: a claim another search has since reclaimed makes the fenced completion refuse the result, which is the intended outcome, not a lost job. The drill itself needs the deployed stack and is still outstanding.

## Evaluation hooks

These are planned measurement and failure-recovery hooks. Main has structured HTTP logging and queue definitions, but no custom metric emission, CloudWatch dashboard or queue/DLQ alarms. Load/fault scripts and executed evidence remain with their owning issues; see the [evaluation index](evaluation/README.md).

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

The planned ingestion and commute-worker Lambdas belong in this repository's Python workspace and CDK stack. Their implementations must read and write the items described in the contract; this ownership rule does not imply that both handlers exist on main.

## PM implementation defaults and remaining evaluation

On 14 October, the blocker-resolution request adopted the contract's equal split/group-size mapping, any-ready-member search once the whole group is ready, 30-day fixed expiry and bounded station-selection policy for this prototype. These are product defaults, not upstream-proven occupancy/price facts or a claim of six-person sign-off. Group removal/recovery/resizing remain outside this version. As of 20 October, ranking parity tests are merged; performance, empirical fairness and deployed acceptance remain outstanding. Runtime/deployed acceptance follows the owning issues, and pair feedback can revise this baseline through a reviewed PR.
