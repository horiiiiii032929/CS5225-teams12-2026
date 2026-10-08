# Python API workspace

Follow the root repository guidance and these additions.

- Keep importable Python in `src/flatsplit_api`; use typed functions and Pydantic response models.
- Add Python dependencies with `uv add --package flatsplit-api <dependency>` from the root. Use the root uv lockfile and virtual environment.
- Use `uv run --package flatsplit-api`, never a separate pip-managed environment.
- The health endpoint is the only initial behavior. Choose AWS runtime adapters, queues and persistence when their implementation is requested.
- Keep secrets in server-side configuration. Avoid logging credentials or sensitive request data.
- Keep shared health fields aligned with `packages/contracts/src/health.ts`. For actual cross-language APIs, establish OpenAPI or JSON Schema as the source of truth and generate clients rather than manually duplicating full models.
- Run workspace lint/typecheck and root build. Add meaningful behavioral tests when endpoints or data logic are implemented.
