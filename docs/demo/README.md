# FlatSplit reproducible demo — #32

Status: local integrated preparation, not a deployed release or completed #31 user study. Owner Raccoon33; reviewer Hikaru. Final screenshots must be recaptured against the same reviewed deployed revision used in the report/deck.

## Reproduce locally

From the repository root, with Node 24, pnpm 11.0.9, Python 3.13 and uv:

```sh
pnpm install --frozen-lockfile
uv sync --locked --all-packages --group dev --extra local
pnpm --filter @flatsplit/contracts build
pnpm exec playwright install chromium
pnpm test:browser
```

If a supported Chromium already exists, set `QA_CHROMIUM_PATH` to its absolute executable path instead of installing a second browser. In the managed environment first source `/workspace/.cloud-tools/env.sh`; preserve the existing proxy and CA settings. The test starts its own isolated API on port 8010 and Vite on 5180, then stops them. It refuses to silently reuse another server. On Linux a missing browser library must be installed through the supported package manager; never disable TLS or artifact checks.

The QA adapter uses the actual HTTP resolver, persistence, search submission/status and ranking with Moto DynamoDB. It supplies a synthetic Kent Ridge destination and synthetic rent records from the existing API journey fixtures. A background helper conditionally finishes captured pending jobs with 20.5-minute estimates. This helper is not the OneMap worker or a production API mode. No real AWS identity, credential, resource or provider call is needed. State resets on restart.

`tools/qa/journey.spec.ts` exercises two and five independent browser contexts, creation/invite/join, explicit place selection, per-member input, editing/reload across members, async results, three-town comparison, map keyboard interaction, stale removal and accessibility. The API query/response is real local HTTP; the underlying records and route completions are synthetic.

## Manual rehearsal: approximately 5 minutes, not a recorded rehearsal

Run `uv run --package flatsplit-api --extra local python tools/qa/local_stack.py` and, in another terminal, `pnpm --filter @flatsplit/web exec vite --config ../../tools/qa/vite.config.mts`. Use the local Vite address printed by the command. Open an independent browser profile/private context for each member, not two tabs sharing storage.

| Time      | Demonstrator action                                                                                                 | Expected evidence / narration                                                                                                                                                                                                                  |
| --------- | ------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0:00–0:30 | Create “Synthetic demo 2” as Alex, group size two                                                                   | A real local group is created. Explain that all demo records are synthetic, not rental listings.                                                                                                                                               |
| 0:30–1:00 | Privately transfer the invitation to the independent Jamie context and join                                         | Both see the same group; the invitation is removed from the address bar. Never display or record the capability link.                                                                                                                          |
| 1:00–2:00 | Each member searches “Kent Ridge”, explicitly selects the supported candidate, enters S$1,800 and 60 minutes, saves | No automatic place selection. Each browser edits only its own member. Explain that the test adapter returns one synthetic destination.                                                                                                         |
| 2:00–2:30 | Reload Alex; start the search                                                                                       | Show actual pending/complete responses. The QA helper finishes only matching pending jobs; do not describe it as a live OneMap worker.                                                                                                         |
| 2:30–3:30 | Compare three ranked towns, expand member outcomes, select a map pin by keyboard                                    | Show rent/person, each commute, longest journey and gap. Read rent coverage/source and freshness limitations; no claim of live rental availability.                                                                                            |
| 3:30–4:15 | Alex changes budget to S$1,900; Jamie reloads                                                                       | Jamie sees the change; old comparisons/map disappear because the revision changed. Reopen Alex's form and confirm saved values.                                                                                                                |
| 4:15–5:00 | Explain missing-data/recovery examples and final limits                                                             | Unknown routes never become zero. For a failure demo, use controlled isolated fixtures, never disturb the shared deployment. The current QA suite verifies search/stale behavior; the component tests cover injected errors/exclusion reasons. |

If fewer than three real towns qualify on the deployed build, show that state honestly. Do not relax constraints silently or replace the run with synthetic recommendations under a “live” label. Stop and record the actual blocker.

## Capture and publication rules

The browser run writes `.qa-artifacts/evidence/`: redacted PNGs and a sanitised accessibility record. Invite input values are masked; traces/videos are off. Do not publish Playwright error contexts, storage dumps, raw request/response logs, capabilities, contact data or unreviewed screenshots. A copied local screenshot must remain labelled **local synthetic** in captions and slides.

Before using deployed evidence, record all of:

- Actual deployed commit and non-capability site URL, UTC/SGT run time, browser/viewport, capture operator.
- Confirmed sample/scenario, group size, non-secret rent snapshot/period/source, commute basis and actual worker/provider mode.
- Same build in #25 checks, #31 sessions, demo, screenshots and slides/report; record deviations rather than editing old evidence.
- Screenshot hashes, masking/privacy check, reviewer sign-off and links. A reachable site is not proof of its deployed SHA.

No deployment, participant session, release sign-off or submission receipt is established by this script. #31's participant attempts and the final deployed-capture acceptance of #32 remain open gates.
