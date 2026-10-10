# FlatSplit backend and AWS design

**Draft:** 10 October 2026 · **Owner:** Shyam · **Status:** Proposed. The API contract and table design are in [api-contract.md](api-contract.md) (#6); team decisions are marked _Open_.

This document turns the preliminary report (sections 3, 4.2, 5.2, 6) and the wireframe decisions in [user-journey.md](user-journey.md) into a buildable backend. It records each AWS service's purpose, permissions and cost assumptions, as `infra/aws/AGENTS.md` requires before resources are added.

## Changes from the preliminary report

| Report says                             | Proposal                                                                  | Why                                                                                                          |
| --------------------------------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| API Gateway REST API                    | API Gateway **HTTP API**                                                  | ~70% cheaper per request, lower latency; stage throttling covers our needs                                   |
| Optional Cognito / "Cognito JWT"        | **Capability tokens** (invite and per-member), stored only as hashes      | Report scope says no login; matches D11. Final report must be corrected                                      |
| Commutes via OneMap and LTA             | **OneMap PT routing**; LTA DataMall optional (station list only)          | LTA DataMall has no journey-planner endpoint                                                                 |
| Web on S3 + CloudFront, separate API    | CloudFront serves the SPA **and** `/api/*` → HTTP API                     | Same origin: no CORS, one URL, matches the Vite `/api` proxy                                                 |
| Destination per member                  | Free-text address, geocoded by OneMap, **snapped to nearest MRT station** | Bounded cache: ~200 stations × 26 towns ≈ 5,200 pairs, ≈21 min of OneMap calls at 250/min to fill completely |
| PITR to recover bad data                | **Versioned rent snapshots + `CURRENT` pointer**, PITR kept as backup     | "Searches continue on the last validated snapshot" becomes an atomic pointer flip                            |
| Provisioned Concurrency for cold starts | Measure first; arm64, small package, Powertools                           | Provisioned Concurrency is billed while idle, which conflicts with the "zero idle cost" goal                 |

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
- One DynamoDB table with no scans or secondary indexes; the one-page read budget is 7 requests after the rent snapshot is pinned, or 8 for a first search that also reads the pointer. Long group histories require pagination and measurement.

Search status is derived when it is read: if any required commute pair is `pending`, the search is pending. This avoids fan-in bookkeeping. Commute jobs use conditional pending leases and idempotent workers. Failed enqueue and expired leases are recoverable; the contract describes the claim and retry rules.

## Data assumptions

- **Rent:** data.gov.sg "Renting Out of Flats" (2021 onwards). Statistic: trailing 12-month median whole-flat rent per town and flat type. Rent per person is that median divided by group size; utilities are excluded (D03). _Verify the dataset id and API limits in the data spike._
- **Flat type by group size (D12, Open):** proposed 2 → 3-ROOM, 3 → 4-ROOM, 4–5 → 5-ROOM.
- **Town point:** each of the 26 HDB towns is represented by its main MRT station or interchange (a static file in the repository).
- **Commute:** OneMap public-transport route from the town point to the destination's snapped station, on a weekday at 08:30 departure, taking the shortest itinerary. A route that cannot be found is UNAVAILABLE; it is never treated as zero minutes (D06).
- **Ranking:** a port of `evaluateAreas` (same weights and scales), with parity tests on the wireframe fixtures. Scales stay _Open_ until the ranking task validates them (D07).

## Security

- Tokens are 256-bit random values. Only SHA-256 hashes are stored. An invite token can only join; it cannot read or edit the group (D11). Invite tokens travel in the URL fragment, so they never reach server logs.
- Each Lambda has its own role scoped to the table, queue, bucket or secret it actually uses. There are no wildcard resource grants.
- OneMap credentials are kept in Secrets Manager and never sent to the browser. `/places` proxies the search.
- Logs never contain tokens or member preference values.
- HTTP API stage throttling (20 requests/s, burst 40) limits abuse. Per-function reserved concurrency is added only once the account's Lambda concurrency quota is raised above the default for new accounts, because reserving below it fails.

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
- Fault injection: an invalid OneMap credential should drive jobs through retries into the DLQ, mark them UNAVAILABLE, and show the UI retry.

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

## Open questions for the team

1. Flat type by group size (D12) and the equal rent split (D03).
2. Any ready member may start a search (D02). Does the team agree?
3. Group data retention: is 30 days from creation acceptable?
4. Ranking scales and weights (D07): the contract keeps the wireframe values until #22 validates them.
