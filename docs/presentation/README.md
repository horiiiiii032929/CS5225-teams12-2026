# FlatSplit initial presentation — #39

Owner/coordinator Raccoon33; reviewer Hikaru. Initial draft, 29 October 2026 SGT. [Open the HTML deck](index.html) or [review the initial PDF](flatsplit-initial-draft.pdf). No final speaking agreement, all-six review, timed rehearsal or submission is claimed. This is a reviewable initial artifact for the 2 November checkpoint; evidence-backed refresh remains due by 8 November and final submission by 13 November 2026 23:59 SGT.

Current online editing copy: [Google Slides — FlatSplit presentation](https://docs.google.com/presentation/d/1oOLGvCQOW5bwN6hG5KMhkMyFqmR50FqH/edit). Use this for team edits and review. The HTML/PDF files in this directory are the initial versioned snapshots; online edits are not automatically synced back to the repository.

## View / export

Open index.html locally, use Left/Right or PageUp/PageDown, or print. Assets and SVG are local; no remote script, font, credential or API is required. From the repository root, after installing locked development dependencies and Chromium:

```sh
node tools/qa/export-slides.mjs
# Existing supported Chromium can be selected with QA_CHROMIUM_PATH.
```

The output defaults to `.qa-artifacts/flatsplit-initial-deck.pdf`. The export refuses missing screenshot assets. The screenshot in this draft is explicitly **local synthetic**, with invitation values masked. Final deployed screenshots must replace it only after the [demo evidence checklist](../demo/README.md) is satisfied. Preserve the original local evidence; do not relabel it as deployment proof.

## Story and proposed speaker handoffs

Durations/order below are proposals, not team agreement. Rehearse against the course's confirmed presentation duration before fixing allocations.

| Slides | Story / speaker notes                                                                                                                                                                                             | Proposed contributor |
| ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- |
| 1–2    | Describe the group problem. A good average can conceal one person's unacceptable commute. Explain town-level scope and excluded listing/payment functionality.                                                    | Raccoon33            |
| 3–4    | Demonstrate member-owned inputs, explicit destination choice, comparison and small-screen interaction. State whether the shown run is synthetic/local or real/deployed before presenting it.                      | Hikaru / Raccoon33   |
| 5      | CloudFront serves private S3 and /api through one HTTP Lambda. SQS decouples route work. Distinguish code-defined main topology from unmerged/integration worker resources and the final deployed topology.       | WK → Shyam           |
| 6      | Explain capabilities, revision pinning, idempotent search and unknown ≠ zero. A timed-out write may have succeeded; require confirmation, not an “unchanged” guarantee. Include the corrected #67 privacy status. | WK                   |
| 7      | Historical rent uncertainty, immutable snapshots, physical-station snapping, per-member constraints and visible fairness. Do not imply exact-door commute or current listing availability.                        | Mani → Ming          |
| 8      | Separate local correctness proof, agreed latency targets, modeled cost, actual measurements and missing participant observations. Never plot test counts as performance or arithmetic as measured queue drain.    | Shyam → Ming         |
| 9      | Follow the versioned five-minute demonstration; keep sample inputs and deployed SHA consistent. Explain failures honestly without mutating shared production data.                                                | Raccoon33 / Hikaru   |
| 10–12  | Credit all six roles; agree actual speaking handoffs; state remaining limits and the final submission gate. Final conclusion must match the report's accepted evidence.                                           | All six / Raccoon33  |

## Citation ledger and corrections

| Claim                         | Source                                                                                                                                                  | Bound / status                                                                                                                                                                             |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Baseline AWS topology         | main b4a4434 `infra/aws/src/{web,api,data,flatsplit-stack}.ts`; [backend design](../backend-design.md)                                                  | Source-defined, not runtime/deployment inventory. Reconcile to final deployed SHA.                                                                                                         |
| UI behaviour and API contract | #84/#85, reviewed #76 e34ef9e / #77 2fa1f04; [API contract](../api-contract.md)                                                                         | This preparation branch composes them locally. It does not merge upstream or establish deployed acceptance.                                                                                |
| Privacy finding corrected     | #67 92a480c; [independent review](https://github.com/horiiiiii032929/CS5225-teams12-2026/pull/67#pullrequestreview-5682238401) and later #39 correction | 32 focused tests and 11 loopback/native-Moto scenarios/175 calls are **reported dated review evidence**, not fresh counts from this deck. Earlier “privacy still open” text is superseded. |
| Worker/ops readiness          | #74 / #79 later handbacks in #44                                                                                                                        | Clean reviewed heads supersede old conflict claims. Local code review is not deployment or real-provider acceptance.                                                                       |
| Rent timestamp correction     | #75 latest 3b95cae handoff in #44                                                                                                                       | Author correction delivered; formal review/real publication acceptance remains a gate. Do not repeat an older defect as if no fix was delivered.                                           |
| Latency                       | [evaluation plan](../evaluation-plan.md), #30 handoff                                                                                                   | Warm complete-result p95 ≤ 500 ms is a target; no accepted measured p95/capacity result is claimed.                                                                                        |
| Cost/reproducibility          | [E9 model](../evaluation/e9/cost-model.md), #68 and #80 review handoffs                                                                                 | Modeled scenarios are not bills/consumed-capacity measurements. Interpreter correction is not new AWS measurement.                                                                         |
| Queue drain                   | #39 later correction                                                                                                                                    | Any 78-pair/~28s or 187,200-job/~19h figure is extrapolation, never a measured drain. No queue-drain result is plotted.                                                                    |
| Local UI evidence             | [QA pass](../qa/mobile-accessibility.md), masked local screenshot and audit manifest                                                                    | Real local HTTP/Moto with synthetic place/rent and injected route completions. No live OneMap worker, deployed release or participants.                                                    |
| User evaluation               | #78 68007a4 study kit; #31 acceptance                                                                                                                   | Preparation only. At least three eligible integrated attempts, target 8–12, issues and critical retests still required.                                                                    |

## Finalisation / submission checklist

- [ ] Each of six members verifies their slide facts/citations and agrees speaking responsibilities; retain six explicit review records.
- [ ] Replace draft evidence with the accepted #32/#34–#36 material from the same report/deployed build, preserving limitations and raw-source links.
- [ ] Confirm actual presentation duration, run a timed rehearsal with all six speakers and record timings/changes through #37.
- [ ] Review the final deck during 9–11 November; rehearse during 11–12 November.
- [ ] Submit by 13 November 2026 23:59 SGT; link the real receipt in #39. No placeholder receipt counts as submission.
