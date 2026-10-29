# FlatSplit

A React and TanStack monorepo with Python Lambda handlers and an AWS CDK app. The frontend supports API-backed group creation, invite joining, reopening and search progress, alongside an interactive wireframe with fictional data. The backend implements health, destination lookup, token-authorised group APIs, search submission/status with filtering and fairness ranking, and validated raw HDB rental snapshot ingestion. Live rental publication, persistent destinations and the commute worker remain integration work. Its CDK stack defines DynamoDB, an HTTP API Lambda, a private versioned rental-evidence bucket, encrypted commute queues, and CloudFront serving the web app with `/api`. See the [backend and AWS design](docs/backend-design.md).

Presentation: [Google Slides (working draft)](https://docs.google.com/presentation/d/1oOLGvCQOW5bwN6hG5KMhkMyFqmR50FqH/edit) · [speaker notes, sources and export instructions](docs/presentation/README.md).

For issue #1, start with the [user journey and responsive wireframes](docs/user-journey.md). Run `pnpm dev:web` and open `/?review=create` for the Design review selector: member input, processing, ranked comparisons and recovery fixtures. Only these explicit previews run without the API, use fictional data and reset on refresh.

## Frontend implementation — #7 and #17

The default `/` route creates a real group through the configured API. The organiser receives a copyable `/join/<groupId>#<inviteToken>` link; a new browser joins with its own name and member token. `/groups/<groupId>` reopens that browser's saved membership and polls group readiness every five seconds. Invite fragments are removed from the address bar before joining and retained in session storage until submission, so a pre-join reload still works. Only the organiser's browser retains the original invitation; an invite cannot read group data. Returning invitations verify any saved membership before reopening it. A confirmed permission failure allows rejoining with the original invite while space remains; a service outage preserves the existing membership and offers verification retry.

Membership is stored in `localStorage`, with fixed server expiry. If browser storage fails, the current tab retains access and displays a warning that refresh/close may lose it. The home page lists saved groups. Losing membership cannot be repaired through the server; use the original invite while space remains, or create a new group if full.

Once every member is ready, the lobby submits a search and polls pending status every two seconds. It shows actual resolved/unavailable counts, supports explicit retry after request failures, resumes the latest search after reload, and withholds results when the group revision changes. Completed searches show server-ranked towns, per-person rent, every member’s commute and headroom, fairness trade-offs, and up to three towns side by side. Rent coverage, source and freshness limitations are visible; the map remains separate #24 work. The API has no per-worker running state: queued/checking labels derive from available pair outcomes, not a fabricated timer or a claim that a worker has started.

**Acceptance boundary:** this is local #7/#17 implementation, not deployment evidence or closure of either issue. Live member preference entry/editing (#8/#13) is implemented and locally tested, including independent member reloads; integrated deployment acceptance remains outstanding. Real readiness/completion still needs those inputs, validated rent publication (#10), persisted places (#14), the commute worker (#15/#27) and an authorised integrated deployment. Browser QA used the actual local resolver with Moto, synthetic rent/place records, API-seeded preferences and conditional injected commute completions; no live OneMap worker was exercised.

`pnpm generate:api` exports the backend's OpenAPI and regenerates public schemas/types in `@flatsplit/contracts/api` and the web SDK. `pnpm generate:api:check` checks drift without modifying repository artifacts and runs in CI. Generated files must not be edited by hand.

### Town reference map — local #24 implementation

Completed current-revision searches now include a town reference map, numbered recommendation pins, an equivalent keyboard-accessible town list and selected-town rent/commute details. The map uses a public projection of the existing principal-MRT reference coordinates; the offline evidence suite checks that projection against the API reference. It is a reference-point map, with latitude/longitude guides, rather than a street map or property/town-boundary display. Small screens can scroll the map independently while the list and member details fit the viewport. Pending, stale, empty and no-longer-ready results do not expose recommendations.

`TownMapResults` accepts the public `SearchView` and `GroupView` props so #23 can compose it into the full results/comparison surface without adding a second fetch or server-data cache. Route calculation timestamps are absent from the current response and are explicitly unavailable; the rent source/period and commute basis remain visible. Local component/browser checks use synthetic completed results and do not establish real-data quality, deployment, #23 completion or #24 deployed acceptance.

## Repository status — 20 October 2026

This historical snapshot, before the frontend work above, describes `main` at `760dd1f` after PRs #60–#63 merged on 19 October. It separates code in the repository from live acceptance; see [issue #44](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/44) for dated coordination updates.

| Area                     | Implemented on main                                                                                                         | Remaining acceptance / integration                                                                                                                          |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Group APIs               | Token-authorised create, join, read and preference updates; persistence, expiry and revision checks                         | Real destination records, frontend integration, shared-device and deployed verification (#7/#8/#12/#13/#14)                                                 |
| Search and ranking       | Submission/status, idempotent revisions, pinned rent reads, recoverable queue claims, filtering and per-member explanations | Validated rent publication (#10), persisted destinations (#14), actual worker results (#15/#27), deployed search and latency evidence (#16/#18/#21/#22/#30) |
| Frontend                 | Responsive journey, comparisons and recovery fixtures; API health page                                                      | Group journey uses fictional in-memory data and resets on refresh; real progress/results integration remains (#17/#23)                                      |
| Tests and infrastructure | API, web, CDK and offline evidence suites; one HTTP Lambda, table, source/DLQ queues and web hosting defined in CDK         | E2E group tests use Moto by default; search/results journey coverage and deployed-build CI remain (#29). No commute consumer is attached on main            |

Open work as of this snapshot: [PR #64](https://github.com/horiiiiii032929/CS5225-teams12-2026/pull/64) adds raw HDB ingestion (approved, CI passing); [PR #65](https://github.com/horiiiiii032929/CS5225-teams12-2026/pull/65) adds place persistence, pinned stations and query caching (CI passing, review ongoing). Neither is merged or accepted in the shared deployment. Raw ingestion alone does not publish validated `RENT/CURRENT` summaries.

The latest recorded deployment is still **14 October**, from `4394195`. Read-only checks on 20 October returned HTTP 200 for the frontend and API health; they do not identify the deployed revision or prove group/search acceptance. M1's 18 October shared-input checkpoint is overdue; the 29 October integration and 13 November 23:59 SGT submission baselines remain. [Ming's 20 October update](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/44#issuecomment-6286402588) targets a worker PR by 24 October, with deployed acceptance still outstanding.

## Get started

Use Node.js 24 LTS, pnpm 11.0.9, and uv 0.9.26 or newer. Python 3.13 is pinned in `.python-version`; uv can provision it automatically. Node 26 is also accepted by the workspace engines.

```sh
pnpm install --frozen-lockfile
uv sync --locked --all-packages --group dev
pnpm dev
```

Open <http://127.0.0.1:5173>. Both the frontend and Python API start with `pnpm dev`. The API exposes <http://127.0.0.1:8000/health> and local interactive documentation at <http://127.0.0.1:8000/docs>. The local server runs the same Powertools resolver that is deployed to Lambda.

To work on one side, use `pnpm dev:web` or `pnpm dev:api`. The explicit wireframe previews work without the API. The default creation flow requires it and shows a recoverable error when unavailable.

Frontend-only contributors can skip the uv setup and run `pnpm dev:web` after the pnpm install. Shared TypeScript packages build automatically before the web server starts.

## Workspaces

| Location             | Responsibility                                     |
| -------------------- | -------------------------------------------------- |
| `apps/web`           | React, Vite, TanStack file routes and server state |
| `services/api`       | Python Lambda handlers (Powertools), managed by uv |
| `packages/contracts` | Explicitly exported TypeScript response schemas    |
| `packages/tsconfig`  | Shared strict TypeScript settings                  |
| `infra/aws`          | TypeScript CDK app, one `FlatSplit-<stage>` stack  |

The root orchestrates commands. Each workspace owns its dependencies and scripts. Use `workspace:*` for local TypeScript packages and import through their declared exports.

## Commands

| Command             | Purpose                                                               |
| ------------------- | --------------------------------------------------------------------- |
| `pnpm dev`          | Run the frontend and API together                                     |
| `pnpm check`        | Check formatting, linting and types in both languages                 |
| `pnpm format`       | Format TypeScript, configuration, Markdown and Python                 |
| `pnpm build`        | Build the frontend, shared package, Python distributions and CDK code |
| `pnpm test`         | Run the frontend and Python behaviour tests                           |
| `pnpm synth`        | Synthesize the AWS stack locally (bundles Lambda code with uv)        |
| `pnpm deploy:aws`   | Build, then deploy the dev stack with your AWS credentials            |
| `pnpm setup:python` | Recreate the Python environment from its lockfile                     |

Run `pnpm test` for wireframe behavior, API error/destination handling, CDK admission-limit assertions, and offline rental-to-station reference regressions. CI runs these alongside formatting, linting, types, builds and local CDK synthesis. Browser verification remains necessary for visible changes.

CDK synthesis warns when `apps/web/dist` is missing; run `pnpm build` first to include the web app. The current TanStack route CLI may also emit a dependency circular-import warning while completing generation.

## Deploying to AWS

The shared dev environment is deployed in account `553455762180`: [FlatSplit dev](https://d2g88qlwvm8dec.cloudfront.net) and [API health](https://d2g88qlwvm8dec.cloudfront.net/api/health). See the [deployment evidence and remaining handoffs](docs/aws-dev-handoff.md). The last recorded deployed frontend remains the prototype. The 14 October deployment evidence predates the merged group/search APIs and local #7/#17 frontend work; their shared-environment acceptance remains outstanding.

For the new shared account, copy the root credential template and edit the local copy:

```sh
cp -n .env.example .env
chmod 600 .env
```

Fill in `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and the shared account's 12-digit `FLATSPLIT_AWS_ACCOUNT_ID`. Temporary credentials also need `AWS_SESSION_TOKEN`; leave it empty for an IAM user's access key. Keep these values in the ignored root `.env`, separate from the public frontend configuration. The template contains no credentials. [AWS documents these credential environment variables](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-envvars.html).

AWS CLI and CDK do not automatically read `.env`. From the repository root, use this subshell to load it and verify the target before deployment:

```sh
(
  unset AWS_PROFILE AWS_DEFAULT_PROFILE AWS_ROLE_ARN AWS_WEB_IDENTITY_TOKEN_FILE
  unset CDK_DEFAULT_ACCOUNT CDK_DEFAULT_REGION
  set -a
  . ./.env
  set +a
  : "${AWS_ACCESS_KEY_ID:?Fill in .env first}"
  : "${AWS_SECRET_ACCESS_KEY:?Fill in .env first}"
  : "${FLATSPLIT_AWS_ACCOUNT_ID:?Set the shared account ID in .env}"
  flatsplit_actual_account=$(aws sts get-caller-identity --query Account --output text) || exit 1
  if [ "$flatsplit_actual_account" != "$FLATSPLIT_AWS_ACCOUNT_ID" ]; then
    echo "AWS account mismatch; stop and check .env." >&2
    exit 1
  fi
  aws sts get-caller-identity
  # Run the authorised bootstrap/deployment commands below here,
  # inside this subshell, after confirming the identity.
)
```

The subshell keeps these credentials out of subsequent commands in your normal shell. Only source your own local `.env`. Once its identity is verified, record the canonical account and shared URL in issue #4; the credentials stay local.

Deployment is manual and needs credentials for the team account in `ap-southeast-1`. Once per account, run `pnpm --filter @flatsplit/aws exec cdk bootstrap`. Then `pnpm deploy:aws` builds everything and deploys `FlatSplit-dev`; the `SiteUrl` output serves the web app and `/api/health`. Use `pnpm --filter @flatsplit/aws exec cdk deploy -c stage=<name>` for another stage, and add `-c budgetEmail=<address>` on one stage to create the US$20/50/100 cost alerts. Non-`prod` stages delete their data when destroyed.

## Local configuration

Vite proxies `/api` to the local Python service. The prototype shell and health endpoint need no environment file or cloud credentials. If needed, copy `apps/web/.env.example` to `apps/web/.env.local`.

Every `VITE_` variable is public in the browser bundle. Keep credentials on the server. A future static host must serve `index.html` for frontend routes, and needs its own API routing or an explicit public API URL; Vite's proxy only runs in development.

Group/search APIs require server-side `TABLE_NAME` and SDK region/credentials; use `DYNAMODB_ENDPOINT_URL` for a local compatible service. Cache-miss searches also require `COMMUTE_QUEUE_URL` (optional local `SQS_ENDPOINT_URL`). Local emulators may use dummy SDK credentials, never real secrets in browser configuration. Preference saves need persisted `PLACE#` records; searches need a validated `RENT/CURRENT` pointer and snapshot summaries. The API does not seed those records or fabricate results. Local browser QA for #13/#23 used Moto and deliberately synthetic place/rent data with injected conditional commute completions; it is not real producer or deployment evidence. CDK provides the queue/table configuration, but the #15 worker must still consume jobs; without it, queued pairs stay pending until their results are written. See the [producer/worker contract](docs/api-contract.md#16-producer-and-15-worker-handoff).

Export these before `pnpm dev` or `pnpm dev:api`. Turborepo runs tasks in strict environment mode, so only the variables allowed in `services/api/turbo.json` (the ones above, `ONEMAP_TOKEN`/`ONEMAP_SECRET_NAME` and `AWS_*`) reach the API, and none of them reach the web dev server.

## Codex and Claude Code

[AGENTS.md](AGENTS.md) contains shared repository instructions. [CLAUDE.md](CLAUDE.md) imports it. Each source workspace also has scoped instructions and a Claude import so guidance stays consistent across both tools.

Read the relevant workspace instructions before changing code. Run the documented checks, report actual results, and record substantial AI-assisted work in [docs/ai-usage.md](docs/ai-usage.md). CI runs the same checks and local CDK synthesis.

The researched choices and official references are in [docs/repository-decisions.md](docs/repository-decisions.md). The two supplied project documents remain in the repository root.
