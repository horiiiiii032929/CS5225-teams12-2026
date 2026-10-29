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

| Evidence                                             | Directory                    | Status                                                                   |
| ---------------------------------------------------- | ---------------------------- | ------------------------------------------------------------------------ |
| OneMap feasibility and source-level commute coverage | [feasibility/](feasibility/) | Reviewed archive, with discrepancies and candidate-selection limitations |
| E6 bad-file/PITR recovery                            | [e6/](e6/)                   | Procedure; not run                                                       |
| E8 rental audit                                      | [e8/](e8/)                   | Source-level audit; integrated acceptance still pending                  |
| E9 hosting costs                                     | [e9/](e9/)                   | Reproducible assumption model; measured account/usage inputs pending     |
| Other experiments                                    | planned                      | Execution after implementation, 30 Oct–8 Nov baseline                    |

Use lowercase experiment IDs going forward; the named feasibility archive and historical raw files remain. A renamed directory does not change its measurements.

## 27 October — E10 preparation

The [E10 / #31 user-testing kit](e10/README.md) now contains a moderator protocol, unaided participant tasks, matched synthetic averages-only/per-member cards, a reproducible ranker-backed card generator, and blank session/defect/retest/summary templates. These are preparation materials, not participant evidence or deployed acceptance. Recruitment, reviewer approval, the integrated #25/#26 entry gates and actual sessions remain outstanding; the historical evidence statuses above are unchanged.
