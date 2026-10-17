# AI-assisted work

Keep concise records of substantial AI contributions so the team can explain and review its own implementation.

## 8 October 2026 — repository scaffold

- Tool: Codex.
- Request: scaffold and install a React/TanStack monorepo with optional Python support, and research repository/agent best practices.
- Contribution: workspace manifests, development wiring, shared configuration and schema, optional FastAPI health endpoint, empty AWS CDK app, CI and repository instructions.
- Scope: no rental, commute, recommendation or application features; no deployment.
- Verification: frozen pnpm install and locked uv sync passed; formatting, ESLint/Ruff, TypeScript/mypy and all workspace builds passed. Python wheel and source distribution were produced. Local CDK synthesis succeeded with the expected empty-stack warning; TanStack's route CLI emitted a dependency circular-import warning without failing generation. HTTP checks confirmed direct and proxied API health responses. Playwright verified home-to-status navigation, API response rendering and refresh at desktop (1440 × 900) and mobile (390 × 844); with the API running, the browser console contained no errors or warnings, and mobile content had no horizontal overflow.
- Environment: local Node 26, pnpm 11.0.9, Python 3.13.11 and uv 0.9.26. CI targets Node 24 and Python 3.13; its remote run has not been executed.
- Fresh-start check: removed generated routes and shared build output, then `pnpm dev:web` restored the shared package and regenerated routes without starting Python. Browser navigation still worked, and the unavailable API state rendered correctly. The deliberately stopped API produced the expected failed health request in this check.
- Human follow-up: review dependency and runtime choices before implementing assigned issues.

For future entries, record the requested issue, tool, contribution, checks actually run and remaining human review.

## 9 October 2026 — issue 1 journey and responsive wireframes

- Tool: Codex, using Product Design guidance and the frontend, React and shadcn skills; no delegated agents.
- Request: browser wireframes and Markdown for the 2–5 member journey, implemented directly in React with Tailwind and the latest shadcn, with deeper demonstrations of fairness and recovery.
- Contribution: creation, group readiness, member preferences and validation, invite preview, simulated processing, ranked results, priority changes, per-member commute bars, up-to-three-area comparisons, missing-data, no-match and failed-search states. Added a documented fictional ranking model and an accessible controlled-dialog focus helper. Preserved the optional service-status route.
- Dependencies: Tailwind CSS 4.3.3, shadcn CLI/source 4.21.4 with Radix Nova, locally bundled Geist, and Vitest 5.0.3; package-manager-generated pnpm lockfile. Node 24.15.0 and pnpm 11.0.9 used locally.
- Documentation: `docs/user-journey.md` contains a Mermaid journey, screen/viewport matrix, proposed decisions, prototype limitations, team/usability review script, evaluation opportunities and acceptance evidence. `docs/wireframes/` contains ten full-page desktop/mobile captures and a desktop results preview. README links the draft; CI now runs the behaviour tests.
- Verification: `pnpm format`, `pnpm check`, `pnpm test` (29 passing tests), `pnpm build`, `pnpm install --frozen-lockfile`, and `git diff --check` passed. The existing TanStack route CLI circular-dependency warning remains non-fatal. No deployment or AWS changes were made; synth was not rerun for this frontend-only work.
- Browser verification: Codex in-app browser at 1440 × 1000 and 390 × 844 for all five primary screens; additional overflow checks at 320 × 900 and 768 × 900. Verified two-member creation through results, invalid budget errors, readiness gating, saved-edit invalidation, priority reranking, comparison, missing-route and service-failure retries, invite-preview copy, and member-entry state. Mobile comparison scrolls within its table, not the page. Fixed narrow-phone creation overflow, cramped mobile member rows, a missing mobile help-button label, progress accessibility values, and dialog focus restoration; rechecked the affected behaviours. The wireframe browser console had no errors or warnings in the checked flow. Screenshots were visually inspected.
- Limitations: fictional datasets, in-memory drafts, local preview links and simulated jobs; no live multi-device sharing, permissions, geocoding, rental/route ingestion, real job queue or cloud performance evidence. The six-person review, final ranking policy, API integration, deployment, external issue evidence and reviewed/merged PR remain pending. No human approvals or usability-study results were invented.

## 10 October 2026 — backend design and M0 AWS skeleton

- Tool: Claude Code (Claude Opus 5.5)
- Request: plan the backend and AWS work from the preliminary report, then draft the design and build a deployable skeleton.
- Contribution: `docs/backend-design.md` (proposed API contract, DynamoDB layout, data assumptions, security, cost and evaluation hooks, plus proposed changes from the preliminary report). Replaced the FastAPI health app with an AWS Lambda Powertools resolver (`handlers/http.py`) and an ASGI adapter (`local.py`) so local development runs the deployed routes. FastAPI was removed; uvicorn is a local-only extra. CDK `FlatSplit-<stage>` stack: DynamoDB table (on-demand, PITR, TTL), arm64 Python 3.13 Lambda behind an HTTP API with stage throttling, private S3 site behind CloudFront (OAC, SPA rewrite function, security headers) with `/api/*` routed to the HTTP API, optional cost budget. Lambda dependencies are bundled locally with uv for arm64 Linux, so Docker is not needed. Updated scripts (`pnpm test` now runs Python tests; `pnpm deploy:aws`), README and agent guidance.
- Dependencies: aws-lambda-powertools 3.35.0, pydantic 2.14.0, pytest 8.4.2. Re-resolving the lock also moved fastapi 0.142.4 → 0.143.0 (now local-only) and pydantic 2.13.5 → 2.14.0.
- Verification: `pnpm format`, `pnpm check`, `pnpm test` (5 Python and 29 web tests), `pnpm build` and `pnpm synth` passed locally. The synthesized Lambda bundle (11 MB unzipped) contains the aarch64 pydantic-core binary and no FastAPI, uvicorn or boto3. The API Lambda role has only basic execution permissions. A local uvicorn run served `/health`, `/docs` and the generated OpenAPI document, and returned 404 for unknown routes.
- Not verified: no AWS deployment or bootstrap was performed. The bundle was not invoked in a Lambda container because Docker was not running. CI was not run remotely. The API contract and open questions in the design doc still need team review.

## 10 October 2026 — issue 6 API contract and access patterns

- Tool: Claude Code (Claude Opus 5.5)
- Contribution: `docs/api-contract.md` with conventions, token model, errors, validation, endpoint shapes and JSON fixtures, DynamoDB items and access patterns A1–A10, assumptions awaiting #2 and #3, and open questions. `docs/backend-design.md` now links to the contract and maps design parts to issue owners.
- Verification: example ranking values were computed by running the wireframe's `evaluateAreas` on its sample group (Node type stripping), not by hand. `pnpm format:check` passed. No code or infrastructure changed.
- Pending: WK review, frontend and data pair sign-off, and confirmation of C1–C7 against #2 and #3.

## 10 October 2026 — issue 46 evaluation plan

- Tool: Claude Code (Claude Opus 5.5)
- Contribution: `docs/evaluation-plan.md` mapping nine AWS techniques to application problems and ten experiments, each with a baseline, workload, metrics, evidence and owning issue (#15, #19, #20, #27, #28, #29, #30, #31, #34, #35, #36, #45); shared workloads W1–W6, checkpoints and decisions to confirm by 12 October.
- Verification: experiment owners and acceptance criteria were checked against the current GitHub issues. `pnpm format:check` passed. No code or infrastructure changed; no experiment has been run.
- Pending: WK review and each owner accepting their row.

## 10 October 2026 — review of PR 48 and API request isolation

- Tool: Codex, directed by Hikaru to review and merge the open PR stack while keeping main working.
- Finding and fix: overlapping ASGI requests used Powertools' process-wide router event state without isolation. A regression test reproduced the first request returning the second request's query value. Added a thread lock around resolver execution, including requests that outlive ASGI cancellation, so each local process matches Lambda's single-invocation execution environment.
- Verification: frozen pnpm install and locked uv sync passed; `pnpm format`, `pnpm check`, `pnpm test` (6 Python and 29 web tests), `pnpm build`, `pnpm synth`, and `git diff --check` passed. Reviewed synthesized arm64 Python 3.13 Lambda, DynamoDB on-demand/PITR/TTL, separate CloudFront API behavior, SPA rewrite and web deployment. Direct and Vite-proxied health requests returned the shared health schema.
- Browser verification: Playwright CLI used because the Browser plugin is not available. Checked the results page at desktop and 390 × 844, priority reranking and the service-status page against the local adapter. Captures are temporary review evidence outside the repository.
- Limits: local and synthesis checks only; AWS bootstrap/deployment and Lambda-container invocation remain unverified. Contract/data decisions and evaluation owner agreement remain proposed.

## 10 October 2026 — review of PR 49 contract

- Tool: Codex, directed by Hikaru to review and merge the open stack.
- Corrections: made invite tokens creation-only with browser retention (hashes cannot recover a token), corrected the initial DynamoDB read budget to eight requests, specified missing-rent nulls, explicit expiry checks and transactional name reservations, and documented leased/idempotent commute enqueue recovery and retry semantics. These are provisional implementation requirements, not completed endpoints.
- Verification: JSON fixtures parse; documentation formatting and diff checks pass. Carried the verified PR 48 request-isolation fix into this branch without rewriting the author’s commits. Rent/transport assumptions still await #2 and #3; issue #6 should stay open until those confirmations are recorded.

## 10 October 2026 — review of PR 50 evaluation plan

- Tool: Codex, directed by Hikaru to review and merge the open stack.
- Corrections: aligned the measured search URL with the API contract, assigned E4 usage evidence to the owner of #34, and distinguished the 20 requests/s admission limit from the proposed 50 requests/s capacity workload. Specified isolated local worker processes for the fixed-instance comparison to avoid benchmarking the resolver’s safety lock as compute capacity.
- Verification: documentation formatting and diff checks pass; the combined stack passes checks, 35 tests, build and synth. Evaluation owner agreement and decisions D-E1–D-E7 remain pending; no experiment results or AWS deployment are claimed.

## 14 October 2026 — project management and blocker reconciliation

- Tool: Codex, directed by Hikaru to act as PM and audit existing discussions before seeking missing information.
- Evidence: inspected all 46 task bodies, seven PRs, 15 issue/PR comments, the recorded pair review, project fields/statuses, repository collaborators and pending invitations. GitHub discussions and reviews remain the source of owner statements; proposed recovery targets are not owner commitments.
- Contribution: reconciled stale repository-access blockers and restored assignees from the existing allocation; updated issue #44 with an evidence-linked recovery plan for the at-risk 18 October milestone. Clarified deployment/billing setup, group-contract handoff, canonical station keys and snapping policy, the 27-town mismatch, pending reviews, evaluation amendments and work that can proceed against fixtures. Corrected project statuses only where discussions or reviews document progress.
- Limits: no implementation, merge, deployment, billing activation, experiment completion or teammate approval is claimed. AWS payer/deployer responsibility remains unconfirmed in the audited discussions. PR #52 has Ming's approval; #51/#53 still await pair review. Existing baseline milestones remain visible alongside PM recovery checkpoints.
- Verification: GitHub issue bodies and assignees were read back after updates; project status updates were read back. Local Markdown formatting and `git diff --check` passed. Application tests, build and synth were not rerun for tracking/documentation changes.

## 13 October 2026 — issue 3 feasibility evidence and issue 46 owner confirmation

- Tool: Claude Code (Claude Opus 5).
- Request: confirm the E3, E4, E5 and E9 rows of `docs/evaluation-plan.md` in #46, then commit the feasibility evidence promised under decision D-E5.
- Contribution: `docs/evaluation/` evidence layout and `docs/evaluation/feasibility/` — the four re-runnable probe scripts, the unedited console output of the 11 October run, the 26-town → principal MRT station table (`data/towns.json`), and a README mapping each claim in #3 to the file and section that supports it. Posted the owner confirmation in #46: four rows accepted, E4's primary metric replaced because OneMap throttles on concurrency rather than requests per minute, W4's invalid-credential injection corrected because untokenised search still returns HTTP 200, and proposed wording for D-E7.
- Verification: every claim in the README was re-checked against the raw files rather than against the issue text, which corrected three rows — the kept feasibility run was untokenised and throttled after 4 of 10 queries, so its latency sample is n=4 and not the n=12 quoted in #3. Prettier formatting passed for the added Markdown and JSON. No code, infrastructure or lockfile changed; no experiment was run.
- Correction during the same session: the instrumented toolkit behind #3 was first reported as unrecoverable and the evidence was committed from console output alone. The working copy was then located and the real artifacts were added — the `onemap` client package, five versioned measurement scripts, and seven summary JSONs with their raw HTTP archives (45 feasibility and 1,037 rate-limit exchanges, authorization headers replaced by a token fingerprint). The README now attributes every claim in #3 to a specific run.
- Discrepancies recorded rather than smoothed over: #3's search latency table quotes n=12, while the instrumented run has n=8 and the untokenised console probe n=4; the 300 calls/min routing boundary comes from run 1.0.0, not the final 1.2.0 run, which re-tested routing only at 250/min; endpoint sharing was observed in 1 of 3 runs; and the instrumented routing latency (p50 140 ms) measured OneMap's upstream cache rather than the 861 ms uncached path.
- Human follow-up: @shyamgj1900 to resolve C6 in #6, which blocks E3; payer-account holder to activate the `project=flatsplit` cost allocation tag, which blocks E9. The two superseded rate-limit archives (645 and 1,573 exchanges) are summarised but their raw bodies are not committed, to keep the repository small.

## 12–14 October 2026 — HDB rental profile and evaluation evidence

- Tool: Codex, directed by Mani.
- Human contribution: Mani drafted the rent schema from the system design and decided the aggregation statistics, confidence method and threshold, duplicate-row handling, supported flat types, and low-confidence API behavior.
- AI assistance: profiled the official HDB datasets, validated the draft against the source data, generated the reproducible E8 audit, helped document the E6 procedure, and performed formatting and consistency checks.
- Verification: 65 of 72 comparable published medians matched exactly; documentation, JSON, sample-data and audit assertions passed. E6 was documented but not run; no AWS deployment was performed.

## 14 October 2026 — issue 14 destination search endpoint

- Tool: Claude Code (Claude Opus 5).
- Request: implement the parts of #14 that do not depend on contract assumption C6, since M1 is due on 18 October and C6 is still unresolved in #6.
- Contribution: `GET /places` on the existing Powertools resolver — query normalisation and the contract's 3-100 character rule, OneMap text search proxied server-side, nearest-station snapping with a straight-line walk distance, at most five candidates returned and never collapsed to one, and the contract's single error body applied to this route and to unknown routes. New `flatsplit_api/onemap.py` and `flatsplit_api/errors.py`. Infrastructure: a Secrets Manager secret for the OneMap token with read access granted to the handler and its name passed as an environment variable, so the token never reaches the browser.
- Behaviour taken from the #3 measurements rather than OneMap's documentation: a lookup costs two calls; `/common/elastic/search` returns HTTP 200 with full results even when the token is missing, invalid or expired, so the `error` field is logged as a token warning instead of being ignored; 429 and 403 bodies are sometimes HTML, so no body is parsed blindly; and candidates are not auto-selected, because taking the top hit silently chose PASIR RIS EAST, PUNGGOL COAST and TAMPINES EAST in #3.
- Verification: 31 tests pass, including the two-calls-per-lookup count, the five-candidate cap, nearest-station selection against a reordered list, the combined `"EW24 / NS1"` id, an unhealthy token still serving results, and the 422, 429, 503 and 404 bodies. `ruff format --check`, `ruff check` and `mypy --strict` pass on the service, `prettier --check` passes repository-wide, `eslint` passes, and the CDK package typechecks. `pnpm synth` and the web build could not be run in this environment because they need `uv` and Node 24; CI covers both.
- Deliberately not included: the DynamoDB place cache, which needs `boto3` added to the lockfile and the table granted to the handler, and the two pieces that depend on C6 — the commute cache key and a maximum snapping distance. `stationId` in the response is marked provisional in the model for that reason. No AWS resource was deployed.

## 14 October 2026 — issue 45 cost model into the repository

- Tool: Claude Code (Claude Opus 5).
- Request: open the pull request promised in #45 so the cost model and its assumptions live in the repository under `docs/evaluation/E9-cost/`, and request review on the open #3 evidence pull request.
- Contribution: moved the existing 12 October draft into `docs/evaluation/E9-cost/` without changing its substance — `cost-model.md`, the runnable model (`model/cost_model.py` and its three JSON inputs) and the 12 October run under `evidence/`. Two formatting corrections were needed to satisfy CI: `cost_model.py` now writes a trailing newline after the JSON summary, and the committed 12 October JSON received the same newline, so a regenerated file is byte-identical to the committed one apart from its `generated_utc` stamp. Prettier padded the Markdown tables and rewrote `0.40` as `0.4` in the two hand-maintained price and workload inputs; no value changed.
- Verification: re-ran `cost_model.py` and reproduced every published figure (payable serverless US$1.13 quiet, US$1.21 typical, US$2.17 bursty; always-on VM US$38.67, US$38.78, US$57.38; on-premise US$243.50, US$243.50, US$274.87). The regenerated CSV is identical to the committed one and the JSON differs only in its timestamp. `prettier --check` passes for every added file, so no `.prettierignore` entry was required. No application code, infrastructure or lockfile changed, no AWS resource was created, and no measured usage is claimed.
- Not addressed here: every workload figure remains an assumption until #30 and #34 supply measured usage, and the `project=flatsplit` cost allocation tag is still not activated, which leaves E9 without a measured Cost Explorer breakdown to compare against this model.

## 14 October 2026 — foundation blocker completion and PR cleanup

- Tool: Codex, directed by Hikaru to finish blocker issues and clean up the PR queue today.
- Integration: reviewed and merged rental profile #52, feasibility/evidence #51, provisional cost model #53 and the newly opened partial destination lookup #54. Preserved all author commits and AI entries while resolving branch conflicts; CI passed on the merged heads. Offline checks reproduced the current 27-town cost model and checked rental-audit counts, station doctests, JSON/JSONL parsing and JWT-pattern absence in the feasibility tree.
- Contract/planning: incorporated WK/Ming's canonical-station, itinerary, quota and candidate-selection corrections and Mani's rent-quality policy. Reconciled `CENTRAL` across the rental and station tables, retained TENGAH as unavailable, and made regeneration refuse fuzzy station matches. Adopted explicit PM prototype defaults for group/expiry/rent mapping, 1,000 m snapping with an 800 m warning, and the evaluation/study baseline; no absent human approval or measured performance is claimed. Standardised the E9 directory and corrected its reproduction path and routing-demand explanation without altering historical raw evidence.
- Runtime corrections: destination lookup now returns canonical station keys and aliases, station coordinates and straight-line snap distance, ambiguity and explicit unsupported reasons. Added finite-coordinate checks, exact-before-rounding snap limits, deduplication, bounded lookup/credential timeouts and public secret/upstream failures without logging provider details. Query/place caching and persistent station-coordinate pinning still belong to #14; groups/searches remain their own implementation issues.
- Infrastructure: isolated `eval` admission is 100 requests/s with burst 200 for the planned 50 requests/s workload. Other stages retain 20/40. Added synthesized-template regression assertions and offline evidence-handoff tests to the normal test command. This is local configuration, not an eval deployment or capacity result.
- Verification: frozen pnpm install and locked uv sync passed; formatting, check, 78 tests (43 API, 29 web, three CDK and three evidence), build, local synth and diff checks passed. Direct ASGI HTTP checks verified health 200, query validation 422, missing-credential 503 and unknown-route 404. No live OneMap experiment was run; browser verification was not required for these backend/documentation changes. The existing TanStack circular-import warning remains non-fatal.
- Remaining external dependency: the audited discussions still do not identify the team AWS profile/account or verify deployment/billing-tag status. No AWS bootstrap, deployment, billing activation, recovery drill or user study was performed. The profile clarification is pending with Hikaru; remaining runtime/evaluation tasks stay open.

## 14 October 2026 — billing blocker correction

- Tool: Codex, continuing Hikaru's PM blocker cleanup.
- Finding: the discussions and cost model overstated delayed tag activation as permanent evidence loss. AWS's official Billing guide supports management-account backfill for up to twelve months when the resource tag existed historically; it cannot recover tags that were absent. Backfill affects all tag keys' current activation statuses, so account eligibility and impact must be checked before an operation.
- Contribution: corrected the E9 model's billing dependency and operator responsibility; linked the official source and retained historical evidence/AI entries. No billing operation or cloud deployment was performed.
- Verification: Markdown formatting and diff checks passed; the immediately preceding implementation baseline passed 78 tests, check, build and synth. This correction changes documentation only.

## 14 October 2026 — shared AWS credential setup

- Tool: Codex, directed by Hikaru to prepare environment files for new AWS credentials.
- Contribution: added a blank root `.env.example` for access keys, optional session token, Singapore region and the expected shared account ID. Created an ignored local `.env` with owner-only permissions. Documented explicit loading in a subshell, required-value checks and STS account matching before cloud writes; existing personal profile settings are not modified.
- Verification: template shell syntax, Git ignore coverage, local file permissions, Markdown formatting and diff checks passed. No application behavior changed; application tests were not rerun. No real credentials were supplied or loaded, and no AWS deployment or bootstrap was performed.

## 14 October 2026 — shared dev deployment and foundation acceptance

- Tool: Codex, continuing Hikaru's authorised PM blocker cleanup after Hikaru supplied new credentials locally.
- Contribution: verified the supplied NUS SSO session belongs to account `553455762180`, recorded that expected target only in the ignored local credential file, built the existing main application, reviewed CDK diff, bootstrapped Singapore and deployed `FlatSplit-dev`. Added a deployment handoff with shared URLs, responsibility, stack outputs and remaining runtime/billing work. No credential values or personal identity were committed.
- Verification: AWS workspace typecheck and build passed; CDK bootstrap and dev deployment completed. Direct/proxied health returned 200, frontend and SPA route returned 200, invalid lookup returned 422 and unknown API route returned 404. Deployed browser checks at 1280 × 900 and 390 × 844 showed the creation shell without horizontal overflow; the service-status page displayed API connected. System Python's certificate store prevented its initial HTTP check; curl repeated the checks successfully with certificate verification enabled. Application tests were not rerun because application code was unchanged from the preceding 78-test baseline.
- Remaining limits: the frontend is still a fictional-data prototype; group/data/cache integration and a live OneMap token/renewal remain open. A read-only billing-tag request returned linked-account access denied, so the organisation's payer-account operator must handle tag activation/window evidence. No billing change, load experiment or live destination experiment was performed. Shyam remains deployment coordinator and WK reviewer.

## 14 October 2026 — PR completion comments and team handoff

- Tool: Codex, directed by Hikaru to comment on the PRs, clean up current progress and prepare a team message using exact names.
- Contribution: rechecked that #51–#57 are merged and no open PR remains; posted and read back a completion comment on each of those seven PRs with verification and specific remaining issues. Reconciled #44 and the project README to show M0 complete and M1 still at risk, moved superseded audit/recovery notes into a history disclosure, and retained the original schedule. Matched the existing six ownership handles to the names in the supplied preliminary-report roster; no student identifiers were copied into the handoff. Recovery checkpoints remain PM targets, not invented teammate commitments.
- Verification: PR state/comments, issue-body edits and project README were read back. The board has eight Done, three Ready, seven In progress and 28 Backlog items. Latest application main CI passed; no application code or cloud resources changed during this tracking cleanup. Markdown formatting and diff checks passed; application tests were not rerun.

## 15 October 2026 — issues 21 and 22 constraint filtering and fairness ranking

- Tool: Claude Code (Claude Opus 5.5), directed by Shyam.
- Contribution: `services/api/src/flatsplit_api/ranking.py`, a pure ranking engine for the search read path (#18). It applies per-member budget and commute limits (inclusive, unrounded), excludes towns with missing rent (`RENT_UNAVAILABLE`), low-confidence rent (`RENT_LOW_CONFIDENCE`, evidence still exposed, no budget headroom) or unavailable routes (`ROUTE_UNAVAILABLE`, never zero minutes), and scores feasible towns with the contract formula and the three wireframe weight presets. It returns rank, score, rent distribution fields, commute statistics, most-burdened member, per-member outcomes and reasons, and orders exclusions as the contract specifies. Pending or missing routes raise `PendingRoutesError`. The contract records the half-up rounding, weights, display rounding and pending rule.
- Verification: 15 new tests, including parity with the wireframe's `evaluateAreas` for all three priorities (expected scores produced by running the wireframe code on its sample group), inclusive and S$0.01 boundary cases, missing route and rent, low-confidence rent, exclusion order, tie-breaks, half-up rounding, zero clamp, pending routes and determinism. `pnpm check`, `pnpm test` (58 API, 3 CDK, 29 web) and `pnpm synth` passed.
- Not covered: no DynamoDB integration; #18 must load members, the pinned rent snapshot and commutes and call `rank_towns`. Scales and weights remain the wireframe baseline until validated (D07).
- Review follow-up (17 October): fixed WK's P1 on #61: fractional commute minutes (e.g. 30.5) no longer fail validation; minutes, headroom and longest/shortest/gap are kept unrounded, and `OVER_COMMUTE` keeps the exact amount while its message rounds up to whole minutes. Added a regression test for a feasible 30.5-minute commute and a 0.5-minute exclusion. API tests (59) and `pnpm check` passed.
