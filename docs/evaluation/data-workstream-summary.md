# Data workstream — final evidence summary and contribution handoff

**Issue [#42](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/42) · 8 November 2026 (SGT) · owners Ming (@lukerspace) and Mani (@saravanamani1999)**

One page for the report writers and reviewers: what the rental-and-commute pipeline
established, what it did **not**, and where each number lives. Every figure here is
read out of a committed artifact named beside it. Nothing in this file is a new
measurement.

## 1. Disposition at a glance

| Issue   | Scope                                                   | State                                                   |
| ------- | ------------------------------------------------------- | ------------------------------------------------------- |
| #2      | HDB export profile and rent summary schema              | Closed                                                  |
| #3      | OneMap geocoding and transit feasibility                | Closed                                                  |
| #9      | Raw HDB ingestion to versioned S3                       | Closed                                                  |
| #10     | Validated town rent summaries published                 | Closed                                                  |
| #14     | Singapore destination geocoding and place cache         | Closed                                                  |
| #19     | Route coverage and unavailable-route behaviour          | Closed, accepted 7 Nov                                  |
| #20     | Audit of rental and commute values shown in results     | Closed                                                  |
| #27     | Commute retries, DLQ and operational alerts             | Closed on its scoped criteria                           |
| #28     | Last-valid rent snapshot protected on ingestion failure | Closed                                                  |
| #33     | Data refresh and failure-recovery runbook               | Closed, independent walkthrough accepted 7 Nov          |
| #34     | Deployed data-quality and cost evidence                 | Closed                                                  |
| #72     | Shared OneMap credential rotation                       | Closed                                                  |
| **#15** | Queued commute worker and result cache                  | **Open — deployed rate-limit enforcement only**         |
| **#18** | Rent/commute integration into the search read path      | **Open — rent-row-to-response numeric mapping**         |
| **#45** | AWS versus on-premise hosting cost                      | **Open — capacity-dependent sizing of options B and C** |

## 2. What the pipeline established

**Rental numbers are correct against their source.** The Q2 2026 audit compared
medians computed from detailed HDB records against HDB's separately published
quarterly town/flat-type medians. Of 81 possible 3/4/5-room groups, 72 had numeric
published medians: **65 matched exactly**, the remaining seven differed by at most
**S$100 (2.70%)**, median absolute difference **S$0**, mean **S$3.40**. Six published
values were `-` and every corresponding detailed group held fewer than 20 records, so
the marker was preserved as missing evidence rather than read as zero.
→ `docs/evaluation/e8/README.md`, `rent-audit-summary.json`, `rent-audit-2026-q2.csv`

**Weak rental evidence is labelled, not silently used.** For the production
trailing-12-month window, **75 of 81** scoped groups were usable, five were
low-confidence and `TENGAH x 3-ROOM` was absent. `CENTRAL x 4-ROOM` had 204 rows and
still failed the block-cluster stability rule, which is the case that justifies the
quality flag existing at all. The 31 October deployed capture read **129 summaries,
97 `USABLE` / 32 `LOW_CONFIDENCE`** under snapshot
`rent-v1-r7-block-bootstrap-v1-2026-09-767a94819f4b`, period `2025-10/2026-09`.
→ `docs/evaluation/e8/deployed-audit-2026-10-31.md`, `raw/2026-10-31/deployed-audit.json`

**Route coverage is complete and its one gap is explicit.** The reviewed catalogue of
30 destinations across 27 towns produced **810 pairs: 780 routable, all succeeded;
30 TENGAH pairs explicitly unavailable; zero errors**; 1,050 client calls, no retries,
no rate limiting. Across the 780 routed pairs median commute was **33.0 min**, p95
**62.3**, max **82.4**. The 7 November deployed reconciliation found a record for
**810/810** requested pairs across **729** canonical station-town records (30
destinations mapping to 27 distinct stations) with **810/810 status agreement**;
deployed-minus-audit travel time had median **0.00 min** and p95 absolute difference
**0.05 min**. Twenty OUTRAM_PARK pairs differed by about ±5.7 min, consistent with
different points inside a multi-line interchange.
→ `docs/evaluation/feasibility/README.md`, `evidence/coverage_20261105T093324Z.json`

**Failure is bounded and visible.** The 7 November `eval` drill: an unkeyable message
received exactly three times at the 180-second visibility interval, dead-lettered
**9 min 37 s** after injection, `CommuteDlqNotEmpty` entering `ALARM`. A keyable
message with invalid coordinates was consumed once, logged terminal and not
redelivered. Cleanup deleted only drill messages by receipt handle; both queues
returned to zero and all alarms to `OK`.
→ `docs/evaluation/e5/README.md`, `procedure.md`, `scripts/dlq_drill.sh`

**Nothing downstream can read a fabricated number.** In the deployed capture
`TOWN#TENGAH` carries `status: "unavailable"`, `error: "NON_ROUTABLE_TOWN"`,
`attempts: 0`, a never-retry `retryAfter` sentinel, and **no `minutes` attribute at
all** — absent, not present-and-zero. Fractional minutes survive storage at full
precision (`12.483333333333333`, `61.56666666666667`). A missing rent row has no
summary and a low-confidence row cannot drive ranking.

**Operations are documented and were executed by someone else.** An independent
teammate followed the runbook against `FlatSplit-eval`, found 26 successful town
routes and TENGAH explicitly unavailable, confirmed null rather than zero commute
values in a complete three-member search, located a successful worker event, found an
empty DLQ and correctly decided not to redrive a permanently non-routable town.
→ `docs/data-refresh-runbook.md`, #33

## 3. What it did not establish — carry these as limitations, not as pending work

1. **Commutes are station-to-station and systematically understate the journey.**
   Across 90 exact-address-versus-snapped comparisons, median absolute error
   **4.1 min**, max **16.8**, and **82 of 90 understated** the journey. Median signed
   error grows from **−2.4 min** below 200 m of walk distance to **−11.9 min** at
   500 m or more. The station estimate omits the final walk. Three probe towns were
   selected alphabetically, not at random.
2. **Deployed transient provider recovery was never induced.** The drill establishes
   bounded failure and visibility, not recovery from a OneMap outage. W4 required a
   fault switch the deployed stack does not have, and the team chose not to add
   failure-only code to the shared evaluation stage during release week. Redrive was
   demonstrated only as a mechanism. The measured alarm-transition delay is not a
   general detection-time bound.
3. **Rate-limit enforcement at the ceiling is unmeasured (#15).** The fixed-window
   guard reserves 200 of the shared 250 calls/min and is implemented and locally
   tested. The deployed warm-up resolved 702 pairs at **125 calls/min sustained**,
   peak **136/min**, p50 invocation **834 ms**, with no budget refusal. That is
   headroom at the measured load, not enforcement.
4. **The read-path numeric mapping is incomplete (#18).** Aggregates reconcile
   exactly — 27 towns × 2 members = 54 pairs, TENGAH × 2 = 2 unavailable, 6 ranked +
   21 excluded = 27 towns — but the rent rows the 4 November search actually read were
   never captured: that response reported period `2025-11/2026-10` while the retained
   capture holds `2025-10/2026-09`. Because `routingProfileVersion` is an attribute
   and not part of the commute key, a profile rollover replaces the record, so the
   31 October minutes are a different generation from what the 4 November search
   returned. Closing this needs about ten read-only `GetItem`s, no provider traffic.
5. **AWS costs are modelled, never billed (#45).** `ce:ListCostAllocationTags` is
   denied to a linked account and the `project` tag was never activated by the payer
   account, so no tagged bill will exist before submission. This is final for this
   project. `sustained_rps_per_node` remains an assumed 25 req/s and sets the node
   counts of options B and C only — **option D, the university-hosted VM and the
   realistic on-premise alternative in an NUS context, is not sized by us and does not
   depend on it.**
6. **E6 bad-file / PITR restoration was not run.** Point-in-time recovery is enabled;
   the drill is a procedure only.
7. **The rent unit is a project assumption.** Monthly rent is interpreted as SGD per
   whole flat per month; the source metadata does not state the unit. Both audit
   datasets are HDB sources, not independent market truth.

## 4. For the report and the deck

Quote these with their boundary attached, never bare:

| Claim                | Figure                                                    | Boundary that must travel with it                    |
| -------------------- | --------------------------------------------------------- | ---------------------------------------------------- |
| Rental accuracy      | 65/72 exact, max error S$100 / 2.70%                      | HDB against HDB, not market truth                    |
| Route coverage       | 780/780 routable, 30/30 unavailable, 0 errors             | One weekday 08:30 departure, station-to-station      |
| Deployed agreement   | 810/810 status, median 0.00 min                           | Reconciliation, not an independent re-measurement    |
| Approximation bias   | median 4.1 min, 82/90 understated                         | Three alphabetically chosen probe towns              |
| Failure containment  | 3 deliveries, DLQ at 9 min 37 s, alarm                    | Provider recovery not induced; not a detection bound |
| Typical hosting cost | US$0.96 serverless against US$85.94 university VM (~90×)  | Modelled under assumed allowances, not an invoice    |
| Idle hosting cost    | US$0.80 against US$243.50 (~304×)                         | The seasonal-workload argument, not "AWS is cheap"   |
| Scalability headroom | no crossover in any plausible range (~×650 at list price) | Derived from the model, not from a load test         |

## 5. Contribution handoff

**Ming (@lukerspace)** — OneMap feasibility (#3); destination geocoding, station
pinning and the place cache (#14); the queued commute worker, result cache and
routing module (#15); route coverage and the snapping-error study (#19); the shared
credential rotation that keeps `/places` alive (#72); the data refresh and
failure-recovery runbook (#33); the E5 drill procedure; and the hosting cost model
and its evidence (#45).

**Mani (@saravanamani1999)** — HDB export profiling and the summary schema (#2); raw
ingestion to versioned S3 (#9); validated town rent summaries (#10); last-valid
snapshot protection on ingestion failure (#28); the deployed rental/commute value
audit (#20); deployed data-quality and cost evidence (#34); and reviewer of record
for the worker and cost work.

**Open at handoff:** #15 awaits an authorisation decision from @shyamgj1900; #18
awaits a short read-only capture; #45 awaits #30's outcome or an explicit
assumed-sizing acceptance. Each has a stated default so none of them needs to remain
open through submission.

## 6. Reproducing any of it

Scripts sit beside their raw output under `docs/evaluation/<experiment>/scripts/`,
read credentials from the environment only, and never edit a previous run. Model and
cost evidence regenerate from `docs/evaluation/e9/model/`. Deployed captures are
read-only, strongly consistent DynamoDB reads and record their account, region,
stack, table and access mode in the artifact itself.
