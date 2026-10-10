# Python API workspace

Follow the root repository guidance and these additions.

- Keep importable Python in `src/flatsplit_api`; use typed functions and Pydantic response models.
- Add Python dependencies with `uv add --package flatsplit-api <dependency>` from the root. Use the root uv lockfile and virtual environment.
- Use `uv run --package flatsplit-api`, never a separate pip-managed environment.
- HTTP routes live on the Powertools resolver in `handlers/http.py`; `local.py` serves the same resolver for `pnpm dev:api`, so never add routes elsewhere. Runtime dependencies ship in the Lambda bundle; local-only tools belong in the `local` extra.
- Follow `docs/backend-design.md` for the API contract, table layout and data assumptions.
- Keep secrets in server-side configuration. Avoid logging credentials or sensitive request data.
- Keep shared health fields aligned with `packages/contracts/src/health.ts`. For actual cross-language APIs, establish OpenAPI or JSON Schema as the source of truth and generate clients rather than manually duplicating full models.
- Run workspace lint, typecheck and `pnpm --filter @flatsplit/api test`. Add behavioral tests for every endpoint and data rule.
