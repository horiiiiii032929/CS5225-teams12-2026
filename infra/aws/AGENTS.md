# AWS workspace

Follow the root repository guidance and these additions.

- `src/app.ts` creates one `FlatSplit-<stage>` stack (`-c stage=dev` by default) from small constructs. Add resources only for requested implementation work.
- Python Lambda code is bundled locally by uv (`src/python-code.ts`); synthesis needs uv but not Docker.
- Keep AWS definitions here, separate from application code. Prefer explicit configuration and reproducible infrastructure.
- Before adding services, document their purpose, permissions, cost assumptions and how the project will evaluate them.
- Use least-privilege policies and server-side secrets; avoid wildcard access without a concrete reason.
- Run `pnpm --filter @flatsplit/aws typecheck` and `pnpm synth`. Synthesis is local and uses no account lookups.
- Account bootstrap, deployment and cleanup are separate operations governed by the user's authorization. Do not infer deployment from a request to scaffold or review.
