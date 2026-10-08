# Repository decisions

Researched on 8 October 2026. These are scaffold choices, not a detailed application specification.

## Structure and dependency ownership

Use pnpm workspaces with a small Turborepo task graph. Deployable units live in `apps`, `services` and `infra`; reusable TypeScript packages live in `packages`. Every workspace owns a manifest. Imports cross package boundaries through explicit exports, and local JavaScript dependencies use `workspace:*`.

This follows the [Turborepo repository guide](https://turborepo.dev/docs/crafting-your-repository/structuring-a-repository) and [pnpm workspace documentation](https://pnpm.io/workspaces). The three-folder variation reflects this project's optional Python service and separate AWS ownership.

Turborepo orchestrates commands; pnpm owns JavaScript dependencies and uv owns Python dependencies. There is one lockfile per ecosystem. Build artifacts and local environments are ignored.

## React and TanStack

Use a Vite React SPA with TanStack Router for file-based routing and Query for asynchronous server state. This keeps the initial web artifact static and leaves AWS API execution to its own implementation task. TanStack Start remains an option if a real SSR or server-function requirement appears.

The [TanStack Router Vite setup](https://tanstack.com/router/latest/docs/installation/with-vite) places its plugin before the React plugin. Generated route files stay out of lint/format input; scripts generate them before type checks on a fresh checkout. The [Router and Query example](https://tanstack.com/router/latest/docs/framework/react/examples/basic-react-query) shows integration around a stable QueryClient and router context.

React components remain small and typed. The initial health request uses cancellation, a shared response schema and explicit loading/error states. A development proxy avoids adding CORS policy before there is a deployment design.

## Optional Python

Use uv with a root Python workspace and one `src`-layout package. A Python developer gets a real environment and importable service without changing the frontend stack. A small `package.json` in that service exposes Python commands to Turborepo; JavaScript dependencies do not manage Python code.

The [uv workspace documentation](https://docs.astral.sh/uv/concepts/workspaces/) describes a shared lockfile with separate member manifests. The [uv project guide](https://docs.astral.sh/uv/guides/projects/) documents syncing and running environments. Future Python workers should be separate members with their own `pyproject.toml`.

The TypeScript health contract is intentionally small. Expanded APIs should have a language-neutral schema source and generated clients.

## Agent instructions

Use concise, versioned instructions close to the code. The root `AGENTS.md` carries shared commands and boundaries; workspace files add only local rules. A nearby `CLAUDE.md` imports the matching `AGENTS.md` using `@AGENTS.md`, avoiding two independently maintained instruction sets.

The [Codex AGENTS.md guide](https://learn.chatgpt.com/docs/agent-configuration/agents-md) explains root-to-directory instruction discovery and narrower overrides. [Claude Code memory documentation](https://code.claude.com/docs/en/memory) documents imports and ancestor/descendant loading. Its [best practices guide](https://code.claude.com/docs/en/best-practices) emphasizes concrete verification and focused project guidance.

No personal/global agent configuration, tool permission settings or custom hooks are needed for this scaffold.

## Reproducibility and CI

Pin direct JavaScript dependencies, the pnpm version and runtime major versions. Use committed locks and frozen/locked installs in CI. Python uses Python 3.13; the recommended Node runtime is 24 LTS. TypeScript remains on a release compatible with the chosen lint tooling.

CI checks formatting, linting, types, builds and local CDK synthesis. Its GitHub Actions references are pinned to verified commit SHAs. There are no cloud credentials or deployment jobs. When real behavior is added, add tests tied to that behavior and the project evaluation plan.
