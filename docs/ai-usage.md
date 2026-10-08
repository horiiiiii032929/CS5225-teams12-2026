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
