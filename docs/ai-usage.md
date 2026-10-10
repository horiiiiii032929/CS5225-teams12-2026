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

- Tool: Claude Code (Claude Opus 5.5), directed by Shyam.
- Request: plan the backend and AWS work from the preliminary report, then draft the design and build a deployable skeleton.
- Contribution: `docs/backend-design.md` (proposed API contract, DynamoDB layout, data assumptions, security, cost and evaluation hooks, plus proposed changes from the preliminary report). Replaced the FastAPI health app with an AWS Lambda Powertools resolver (`handlers/http.py`) and an ASGI adapter (`local.py`) so local development runs the deployed routes. FastAPI was removed; uvicorn is a local-only extra. CDK `FlatSplit-<stage>` stack: DynamoDB table (on-demand, PITR, TTL), arm64 Python 3.13 Lambda behind an HTTP API with stage throttling, private S3 site behind CloudFront (OAC, SPA rewrite function, security headers) with `/api/*` routed to the HTTP API, optional cost budget. Lambda dependencies are bundled locally with uv for arm64 Linux, so Docker is not needed. Updated scripts (`pnpm test` now runs Python tests; `pnpm deploy:aws`), README and agent guidance.
- Dependencies: aws-lambda-powertools 3.35.0, pydantic 2.14.0, pytest 8.4.2. Re-resolving the lock also moved fastapi 0.142.4 → 0.143.0 (now local-only) and pydantic 2.13.5 → 2.14.0.
- Verification: `pnpm format`, `pnpm check`, `pnpm test` (5 Python and 29 web tests), `pnpm build` and `pnpm synth` passed locally. The synthesized Lambda bundle (11 MB unzipped) contains the aarch64 pydantic-core binary and no FastAPI, uvicorn or boto3. The API Lambda role has only basic execution permissions. A local uvicorn run served `/health`, `/docs` and the generated OpenAPI document, and returned 404 for unknown routes.
- Not verified: no AWS deployment or bootstrap was performed. The bundle was not invoked in a Lambda container because Docker was not running. CI was not run remotely. The API contract and open questions in the design doc still need team review.

## 10 October 2026 — review of PR 48 and API request isolation

- Tool: Codex, directed by Hikaru to review and merge the open PR stack while keeping main working.
- Finding and fix: overlapping ASGI requests used Powertools' process-wide router event state without isolation. A regression test reproduced the first request returning the second request's query value. Added a thread lock around resolver execution, including requests that outlive ASGI cancellation, so each local process matches Lambda's single-invocation execution environment.
- Verification: frozen pnpm install and locked uv sync passed; `pnpm format`, `pnpm check`, `pnpm test` (6 Python and 29 web tests), `pnpm build`, `pnpm synth`, and `git diff --check` passed. Reviewed synthesized arm64 Python 3.13 Lambda, DynamoDB on-demand/PITR/TTL, separate CloudFront API behavior, SPA rewrite and web deployment. Direct and Vite-proxied health requests returned the shared health schema.
- Browser verification: Playwright CLI used because the Browser plugin is not available. Checked the results page at desktop and 390 × 844, priority reranking and the service-status page against the local adapter. Captures are temporary review evidence outside the repository.
- Limits: local and synthesis checks only; AWS bootstrap/deployment and Lambda-container invocation remain unverified. Contract/data decisions and evaluation owner agreement remain proposed.
