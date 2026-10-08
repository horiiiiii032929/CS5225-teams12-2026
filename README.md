# FlatSplit

A React and TanStack monorepo with an optional Python API and an AWS infrastructure workspace. This commit-sized scaffold contains local wiring only: two frontend routes, a health endpoint, and an empty CDK stack.

## Get started

Use Node.js 24 LTS, pnpm 11.0.9, and uv 0.9.26 or newer. Python 3.13 is pinned in `.python-version`; uv can provision it automatically. Node 26 is also accepted by the workspace engines.

```sh
pnpm install --frozen-lockfile
uv sync --locked --all-packages --group dev
pnpm dev
```

Open <http://127.0.0.1:5173>. Both the frontend and Python API start with `pnpm dev`. The API exposes <http://127.0.0.1:8000/health> and local interactive documentation at <http://127.0.0.1:8000/docs>.

To work on one side, use `pnpm dev:web` or `pnpm dev:api`. The frontend works without the API and shows an unavailable state on the status page.

Frontend-only contributors can skip the uv setup and run `pnpm dev:web` after the pnpm install. Shared TypeScript packages build automatically before the web server starts.

## Workspaces

| Location             | Responsibility                                          |
| -------------------- | ------------------------------------------------------- |
| `apps/web`           | React, Vite, TanStack file routes and server state      |
| `services/api`       | Optional Python/FastAPI service, managed by uv          |
| `packages/contracts` | Explicitly exported TypeScript response schemas         |
| `packages/tsconfig`  | Shared strict TypeScript settings                       |
| `infra/aws`          | TypeScript CDK app; currently contains no AWS resources |

The root orchestrates commands. Each workspace owns its dependencies and scripts. Use `workspace:*` for local TypeScript packages and import through their declared exports.

## Commands

| Command             | Purpose                                                               |
| ------------------- | --------------------------------------------------------------------- |
| `pnpm dev`          | Run the frontend and API together                                     |
| `pnpm check`        | Check formatting, linting and types in both languages                 |
| `pnpm format`       | Format TypeScript, configuration, Markdown and Python                 |
| `pnpm build`        | Build the frontend, shared package, Python distributions and CDK code |
| `pnpm synth`        | Produce a local template from the empty AWS stack; no deployment      |
| `pnpm setup:python` | Recreate the Python environment from its lockfile                     |

There is no test suite yet because the scaffold contains no application behavior. Add meaningful tests with the first feature; do not add commands that silently pass with zero tests.

CDK synthesis warns that the empty stack has no resources; it is intentionally not deployable yet. The current TanStack route CLI may also emit a dependency circular-import warning while completing generation.

## Local configuration

Vite proxies `/api` to the local Python service. No environment file or cloud credentials are required for this scaffold. If needed, copy `apps/web/.env.example` to `apps/web/.env.local`.

Every `VITE_` variable is public in the browser bundle. Keep credentials on the server. A future static host must serve `index.html` for frontend routes, and needs its own API routing or an explicit public API URL; Vite's proxy only runs in development.

## Codex and Claude Code

[AGENTS.md](AGENTS.md) contains shared repository instructions. [CLAUDE.md](CLAUDE.md) imports it. Each source workspace also has scoped instructions and a Claude import so guidance stays consistent across both tools.

Read the relevant workspace instructions before changing code. Run the documented checks, report actual results, and record substantial AI-assisted work in [docs/ai-usage.md](docs/ai-usage.md). CI runs the same checks and local CDK synthesis.

The researched choices and official references are in [docs/repository-decisions.md](docs/repository-decisions.md). The two supplied project documents remain in the repository root.
