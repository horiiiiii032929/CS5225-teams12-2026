# FlatSplit backend and AWS design

**Draft:** 10 October 2026 · **Owner:** Shyam · **Status:** Proposed — needs frontend-pair sign-off on the API contract and team decisions marked _Open_.

This document turns the preliminary report (sections 3, 4.2, 5.2, 6) and the wireframe decisions in [user-journey.md](user-journey.md) into a buildable backend. It records each AWS service's purpose, permissions and cost assumptions, as `infra/aws/AGENTS.md` requires before resources are added.

## Changes from the preliminary report

| Report says                             | Proposal                                                                     | Why                                                                                                          |
| --------------------------------------- | ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| API Gateway REST API                    | API Gateway **HTTP API**                                                     | ~70% cheaper per request, lower latency; stage throttling covers our needs                                   |
| Optional Cognito / "Cognito JWT"        | **Capability tokens** (organiser, invite, per-member), stored only as hashes | Report scope says no login; matches D11. Final report must be corrected                                      |
| Commutes via OneMap and LTA             | **OneMap PT routing**; LTA DataMall optional (station list only)             | LTA DataMall has no journey-planner endpoint                                                                 |
| Web on S3 + CloudFront, separate API    | CloudFront serves the SPA **and** `/api/*` → HTTP API                        | Same origin: no CORS, one URL, matches the Vite `/api` proxy                                                 |
| Destination per member                  | Free-text address, geocoded by OneMap, **snapped to nearest MRT station**    | Bounded cache: ~200 stations × 26 towns ≈ 5,200 pairs, ≈21 min of OneMap calls at 250/min to fill completely |
| PITR to recover bad data                | **Versioned rent snapshots + `CURRENT` pointer**, PITR kept as backup        | "Searches continue on the last validated snapshot" becomes an atomic pointer flip                            |
| Provisioned Concurrency for cold starts | Measure first; arm64, small package, Powertools                              | Provisioned Concurrency is billed while idle, which conflicts with the "zero idle cost" goal                 |

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

## API contract (proposed)

All paths sit under `/api` in the browser. Tokens go in `Authorization: Bearer <token>`. Request and response bodies are Pydantic models; OpenAPI is generated from them and converted into zod schemas in `@flatsplit/contracts`.

| Method | Path                                     | Auth                | Behaviour                                                                                                                      |
| ------ | ---------------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| GET    | `/health`                                | —                   | Liveness                                                                                                                       |
| POST   | `/groups`                                | —                   | Create group (name, size 2–5, organiser name) → `groupId`, organiser member token, invite token                                |
| GET    | `/groups/{gid}`                          | any group token     | Group, members, readiness, `revision`, latest search id and status                                                             |
| POST   | `/groups/{gid}/members`                  | invite token        | Join; 409 when the group is full → `memberId`, member token                                                                    |
| PUT    | `/groups/{gid}/members/{mid}`            | that member's token | Save destination (`placeId` from `/places`), budget, max commute; marks ready; increments `revision`                           |
| GET    | `/places?q=`                             | — (throttled)       | OneMap search → up to 5 candidates, each with its snapped MRT station                                                          |
| POST   | `/groups/{gid}/searches`                 | any group token     | 409 unless all members ready. All pairs cached → 200 with results; otherwise enqueue missing pairs → 202 `{searchId, pending}` |
| GET    | `/groups/{gid}/searches/{sid}?priority=` | any group token     | `pending` (with progress), `complete` (ranked and excluded areas), or `stale` when `revision` changed since the search started |
| GET    | `/meta`                                  | —                   | Rent snapshot period and sample sizes, commute data freshness                                                                  |

Validation mirrors `apps/web/src/features/wireframes/model.ts`: name 1–30 characters, budget S$300–5,000, max commute an integer from 10 to 120 minutes, group size 2–5. The server is authoritative; the client keeps its checks for fast feedback.

## Data model (DynamoDB single table)

Keys are `pk` / `sk`. Group items carry a `ttl` attribute (proposed 30 days after the last change).

| Item            | pk                    | sk                       | Attributes                                                               |
| --------------- | --------------------- | ------------------------ | ------------------------------------------------------------------------ |
| Group           | `GROUP#<gid>`         | `META`                   | name, size, revision, organiser and invite token hashes, ttl             |
| Member          | `GROUP#<gid>`         | `MEMBER#<mid>`           | name, destination label, stationId, budget, maxCommute, ready, tokenHash |
| Search          | `GROUP#<gid>`         | `SEARCH#<sid>`           | revision at start, createdAt                                             |
| Rent statistic  | `RENT#<snapshotId>`   | `TOWN#<town>#<flatType>` | median, p25, p75, count, period                                          |
| Active snapshot | `META`                | `RENT_CURRENT`           | snapshotId, validatedAt                                                  |
| Commute         | `COMMUTE#<stationId>` | `TOWN#<town>`            | status (PENDING, OK, UNAVAILABLE), minutes, transfers, computedAt        |

A search reads one `GROUP#` partition, at most five `COMMUTE#` partitions (one per member, about 26 items each) and one `RENT#` query. That is 7 queries or fewer, well within the 500 ms target.

Search status is derived when it is read: if any required commute pair is `PENDING`, the search is pending. This avoids fan-in bookkeeping. Commute jobs are de-duplicated with a conditional write of the `PENDING` item, so two groups asking for the same pair produce one OneMap call.

## Data assumptions

- **Rent:** data.gov.sg "Renting Out of Flats" (2021 onwards). Statistic: trailing 12-month median whole-flat rent per town and flat type. Rent per person is that median divided by group size; utilities are excluded (D03). _Verify the dataset id and API limits in the data spike._
- **Flat type by group size (D12, Open):** proposed 2 → 3-ROOM, 3 → 4-ROOM, 4–5 → 5-ROOM.
- **Town point:** each of the 26 HDB towns is represented by its main MRT station or interchange (a static file in the repository).
- **Commute:** OneMap public-transport route from the town point to the destination's snapped station, on a weekday at 08:30 departure, taking the shortest itinerary. A route that cannot be found is UNAVAILABLE; it is never treated as zero minutes (D06).
- **Ranking:** a port of `evaluateAreas` (same weights and scales), with parity tests on the wireframe fixtures. Scales stay _Open_ until the ranking task validates them (D07).

## Security

- Tokens are 256-bit random values. Only SHA-256 hashes are stored. The organiser token is never derivable from an invite or member link (D11).
- Each Lambda has its own role scoped to the table, queue, bucket or secret it actually uses. There are no wildcard resource grants.
- OneMap credentials are kept in Secrets Manager and never sent to the browser. `/places` proxies the search.
- Logs never contain tokens or member preference values.
- HTTP API stage throttling limits abuse; reserved concurrency caps each function's spend.

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

## Delivery milestones

| Milestone | Target | Scope                                                                                                 |
| --------- | ------ | ----------------------------------------------------------------------------------------------------- |
| M0        | 13 Oct | CDK skeleton: table, HTTP API with Powertools `/health`, S3 + CloudFront with `/api`, budget          |
| M1        | 16 Oct | Groups API, tokens, validation, revision, TTL; handler tests; OpenAPI → contracts                     |
| M2        | 19 Oct | Rental ingestion with validated snapshots, monthly schedule, `/meta`, `/places` with station snapping |
| M3        | 23 Oct | Commute queue, worker, DLQ, search endpoints, ranking port with parity tests                          |
| M4        | 25 Oct | Frontend switched from fixtures to the API; end-to-end on the dev stage                               |
| M5        | 8 Nov  | Dashboard and alarms, load test, fault injection, cost report                                         |

## Open questions for the team

1. Flat type by group size (D12) and the equal rent split (D03).
2. Can any member start a search, or only the organiser (D02)?
3. Group data retention: is 30 days after the last change acceptable?
4. Who owns the ranking formula: the data pair or the backend? (Formula and scales, D07.)
