# FlatSplit

A React and TanStack monorepo with Python Lambda handlers and an AWS CDK app. The frontend includes an interactive group flat-hunting wireframe with fictional data. The backend currently exposes a health endpoint; its CDK stack defines DynamoDB, an HTTP API Lambda, and CloudFront serving the web app with `/api`. See the [backend and AWS design](docs/backend-design.md).

For issue #1, start with the [user journey and responsive wireframes](docs/user-journey.md). Run `pnpm dev:web`, then use the Design review selector to explore group creation, member input, processing, ranked comparisons, and recovery states. This prototype runs locally without the API, does not share groups across devices, and resets on refresh.

## Get started

Use Node.js 24 LTS, pnpm 11.0.9, and uv 0.9.26 or newer. Python 3.13 is pinned in `.python-version`; uv can provision it automatically. Node 26 is also accepted by the workspace engines.

```sh
pnpm install --frozen-lockfile
uv sync --locked --all-packages --group dev
pnpm dev
```

Open <http://127.0.0.1:5173>. Both the frontend and Python API start with `pnpm dev`. The API exposes <http://127.0.0.1:8000/health> and local interactive documentation at <http://127.0.0.1:8000/docs>. The local server runs the same Powertools resolver that is deployed to Lambda.

To work on one side, use `pnpm dev:web` or `pnpm dev:api`. The frontend works without the API and shows an unavailable state on the status page.

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

Run `pnpm test` for the wireframe’s readiness, validation, feasibility and ranking tests and the API handler tests. CI runs these alongside formatting, linting, types, builds and local CDK synthesis. Browser verification remains necessary for visible changes.

CDK synthesis warns when `apps/web/dist` is missing; run `pnpm build` first to include the web app. The current TanStack route CLI may also emit a dependency circular-import warning while completing generation.

## Deploying to AWS

Deployment is manual and needs credentials for the team account in `ap-southeast-1`. Once per account, run `pnpm --filter @flatsplit/aws exec cdk bootstrap`. Then `pnpm deploy:aws` builds everything and deploys `FlatSplit-dev`; the `SiteUrl` output serves the web app and `/api/health`. Use `pnpm --filter @flatsplit/aws exec cdk deploy -c stage=<name>` for another stage, and add `-c budgetEmail=<address>` on one stage to create the US$20/50/100 cost alerts. Non-`prod` stages delete their data when destroyed.

## Local configuration

Vite proxies `/api` to the local Python service. No environment file or cloud credentials are required for this scaffold. If needed, copy `apps/web/.env.example` to `apps/web/.env.local`.

Every `VITE_` variable is public in the browser bundle. Keep credentials on the server. A future static host must serve `index.html` for frontend routes, and needs its own API routing or an explicit public API URL; Vite's proxy only runs in development.

## Codex and Claude Code

[AGENTS.md](AGENTS.md) contains shared repository instructions. [CLAUDE.md](CLAUDE.md) imports it. Each source workspace also has scoped instructions and a Claude import so guidance stays consistent across both tools.

Read the relevant workspace instructions before changing code. Run the documented checks, report actual results, and record substantial AI-assisted work in [docs/ai-usage.md](docs/ai-usage.md). CI runs the same checks and local CDK synthesis.

The researched choices and official references are in [docs/repository-decisions.md](docs/repository-decisions.md). The two supplied project documents remain in the repository root.
