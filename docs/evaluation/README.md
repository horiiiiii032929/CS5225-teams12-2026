# Evaluation evidence

Evidence for the experiments in [evaluation-plan.md](../evaluation-plan.md), stored under one directory per experiment as agreed in decision **D-E5**: raw data, the script that produced it, and the date.

**Status — 20 October 2026:** merged group/search/ranking code and passing local/CI tests do not complete the deployed experiments. The latest local baseline passed 258 API, 29 web, five CDK and three offline evidence tests; API/web/CDK tests were rerun without Turbo cache. Search coverage uses seeded rent/place records and injected worker completions. #29's group journeys are partial coverage, not complete search/results or deployed-build acceptance. No E1/E2 latency/capacity, E4/E5 worker/recovery, E6 PITR or E10 user-study result is established by these tests.

The 20 October live-OneMap/local-handler/Moto evidence is linked from [#14](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/14) and the [#45 model update](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/45#issuecomment-6286439604); it concerns open PR #65, not main or a real-table deployment. The [E9 reconciliation](e9/cost-model.md#status-reconciliation--20-october-2026) lists inputs that must change before the next model run. Existing raw files and dated model outputs remain historical evidence.

```
docs/evaluation/
  <experiment>/
    README.md            what was measured, when, and which claim each file supports
    scripts/             the code that produced the raw output
    raw/<YYYY-MM-DD>/    unedited output, one directory per run
    data/                derived tables other issues consume
```

Conventions:

- **Raw output is never edited.** If a run is wrong or superseded, it stays and the README says so.
- **No credentials in this tree.** Scripts read tokens from the environment.
- **A run without its script is incomplete evidence** and must be labelled as such, because D-E5 requires the script version.

| Evidence                                             | Directory                          | Status                                                                   |
| ---------------------------------------------------- | ---------------------------------- | ------------------------------------------------------------------------ |
| OneMap feasibility and source-level commute coverage | [feasibility/](feasibility/)       | Reviewed archive, with discrepancies and candidate-selection limitations |
| #15 commute-worker routing, verified live            | [worker-routing/](worker-routing/) | Module verified against live OneMap on 20 Oct                            |
| #15 queue drain, concurrency and deduplication       | [worker-queue/](worker-queue/)     | Measured off a real queue on 26 Oct; emulated AWS, replayed OneMap       |
| E6 bad-file/PITR recovery                            | [e6/](e6/)                         | Procedure; not run                                                       |
| E8 rental audit                                      | [e8/](e8/)                         | Source-level audit; integrated acceptance still pending                  |
| E9 hosting costs                                     | [e9/](e9/)                         | Reproducible assumption model; measured account/usage inputs pending     |
| Other experiments                                    | planned                            | Execution after implementation, 30 Oct–8 Nov baseline                    |

Use lowercase experiment IDs going forward; the named feasibility archive and historical raw files remain. A renamed directory does not change its measurements.

## 27 October — E10 preparation

The [E10 / #31 user-testing kit](e10/README.md) now contains a moderator protocol, unaided participant tasks, matched synthetic averages-only/per-member cards, a reproducible ranker-backed card generator, and blank session/defect/retest/summary templates. These are preparation materials, not participant evidence or deployed acceptance. Recruitment, reviewer approval, the integrated #25/#26 entry gates and actual sessions remain outstanding; the historical evidence statuses above are unchanged.

## #30 W1/W2 load tooling — preparation, not measured evaluation

The local workload generator, k6 runner and privacy-safe summarizer are in [`tools/load/`](../../tools/load/). They implement E1/E2's seeded open-arrival workloads; they do not authorize requests against dev/eval or prove deployed acceptance, latency or capacity. Actual measurement remains gated by complete #29 acceptance, reviewed destination/seed/mix inputs and explicit isolated-eval operator, quota, budget, request ceiling and stop approval.

### Inputs and safeguards

- W1:2 complete-result GETs/s for600 seconds, **1,200 planned reads**. W2:1→50 requests/s over60 seconds, then50/s for300 seconds, **16,530 planned requests**. Seeded ten-operation blocks preserve the proposed1-create/2-join/4-save/3-read split (1,653/3,306/6,612/4,959 standard operations); Shyam must review that refinement.
- `generate.py` works offline. No catalog permits arithmetic-only plans, not HTTP execution. A catalog must contain exactly `version:1`, `kind`, `review` and `destinations`. `kind` is `synthetic-local` or `reviewed-public`; public execution needs exactly30 distinct aliases with distinct selection receipts. `review` contains nonempty `reviewer`, `revision` and `weight_basis`; these strings assert provenance, not independently verified approval.
- Each destination contains only `alias`, positive finite `weight`, `selection_receipt`, `station:{stationKey,lat,lng}` and `place_ids:{targetLabel:persistedPlaceId}`. Use persisted IDs/pins from the target; multiple destinations may share a canonical station. Public receipts must be credential/query/fragment-free public HTTPS references; local synthetic receipts use `synthetic://<alias>`. No intended public catalog is fabricated or bundled.
- Plans pin the trace and catalog SHA256 with cross-runtime numeric normalization, preserving coordinate precision. Run configuration contains exactly `mode`, `run_id`, `target`, `base_url`, `source_revision`, `max_lateness_ms`, `timeout_ms` and `setup_timeout_seconds`, plus `approval` only for eval. Every destination needs a `place_ids` entry matching `target`.
- `local` accepts only literal localhost/127.0.0.1/[::1] HTTP, optionally ending in `/api`; no approval block. `eval` requires nonlocal HTTPS, an unscaled standard plan and `reviewed-public` catalog, plus `approval:{operator,stage:"eval",reference,stop_reference,client_location:"Singapore",max_requests}`. URL credentials/query/fragment/arbitrary paths, extra secret fields, redirects, segmented/cloud/debug execution and unsafe input are rejected. An approval-shaped object is **not actual authority or proof of stage isolation**.
- The request ceiling includes setup and measured requests, computed by `requestBudget(plan)` in `protocol.mjs`. Setup creates separate join/save/read pools, saves inputs and starts/verifies complete read cohorts without polling. Setup can enqueue real route work: **do not start it against any shared/eval target without authorization**, even before the measured interval.
- Read cohorts use independently seeded weighted companion destinations rather than forcing every member onto one station. Save success verifies the persisted pin, identity, limits and revision. Writes do not stale measured read groups.
- k6 uses one single-instance `per-vu-iterations` execution, sharded by ordinal. Requests wait for absolute planned arrivals; arrivals beyond `max_lateness_ms` are explicitly dropped rather than hidden in a response-dependent queue. Finite-VU drops are client limitations to disclose, not measured backend capacity.

### Run only against a verified, authorized target

Requires Python3.13/Node24 from the repository setup and a separately installed k6 binary. No application dependency or lockfile change is needed. Supply operator-created absolute catalog/run paths, existing target records and a fresh evidence path for each run:

```sh
python tools/load/generate.py --workload W1 --catalog /absolute/catalog.json --output /tmp/W1.plan.json
python tools/load/generate.py --workload W2 --catalog /absolute/catalog.json --output /tmp/W2.plan.json
K6_NO_USAGE_REPORT=true k6 run --log-format raw --console-output /tmp/W1.samples.jsonl \
  -e PLAN=/tmp/W1.plan.json -e RUN_CONFIG=/absolute/run.json tools/load/runner.js
python tools/load/summarize.py --plan /tmp/W1.plan.json \
  --samples /tmp/W1.samples.jsonl --output /tmp/W1.summary.json
```

Repeat the k6/summarizer commands for W2. `--scale 0.005 --vus 2` produces a short local W1 smoke at unchanged arrival rates, explicitly **not the standard workload**; eval rejects scaled plans. Preserve raw evidence rather than overwriting a prior run. Plans/configs must never contain provider credentials or group/member capabilities.

The runner keeps capabilities and actual IDs in memory and projects allowlisted evidence only: safe run/cohort/operation labels, planned ordinal/time, measured timestamps/duration, status and fixed outcome enums. It does not retain headers, response bodies, capabilities or arbitrary provider messages; k6's default summary is suppressed. Disable usage reporting before process startup as shown. No HTTP debug output, cloud execution, credential-bearing tags or request retries.

`summarize.py` separates setup/measured traffic, operations, ramp/hold, HTTP errors, invalid responses, pending/stale data and dropped arrivals. Successful-only nearest-rank p50/p95/p99 exclude failures; hold throughput uses the full planned hold interval, not the observed sample span. Durations use elapsed `Date.now()` around the request, not a guaranteed monotonic clock or evidence of Lambda initialization. Cold classification/billed duration remain unknown.

Exit0 means complete captured evidence, **not all-successful requests or a passed500ms target**. Exit1 means valid but incomplete/interrupted evidence with missing ordinals; exit2 means malformed/unsafe input without echoing it or overwriting protected inputs/output. Inspect all outcomes and eligible sample counts. Store real approved E1/E2 raw/script/date artifacts using the existing lowercase evidence convention only when those runs exist; local synthetic smoke is not a permanent benchmark dataset.

### Regression checks

`pnpm test:evidence` discovers the Python workload/evidence regressions **and the existing acceptance suite**. `pnpm test:load` runs the Node protocol regressions. Root `pnpm test` retains API/web/CDK, evaluation/acceptance and E2E summarizer coverage and adds the load protocol suite. These offline checks do not authorize or execute a shared workload.
