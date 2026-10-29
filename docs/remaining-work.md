# Raccoon33 issue handoff — 29 October 2026 (SGT)

This is a reviewable progress record, not an issue-closing instruction. Existing issue acceptance criteria remain in force. Source: assigned open issues #8, #13, #23, #25, #32, #39 and planning hubs #41/#44.

| Issue    | Preparation delivered                                                                                                                                         | Exact remaining acceptance / owner action                                                                                                                                                                  |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| #8, #13  | #84 original form; #85 validated editing, per-member reload and form tests; this branch adds two/five-member repeatable browser checks and input-error focus. | Hikaru reviews implementation; merge the chosen PR sequence without duplicating #84's commit; verify integrated deployment with representative saved destinations. Keep issues open until evidence exists. |
| #23      | #85 rank/per-member/three-town comparison; this preparation branch composes reviewed #76 map and #77 recovery without discarding either.                      | Reviewed merge/deployment and real rent/worker results; confirm freshness metadata limitations. This branch does not deploy or merge upstream PRs.                                                         |
| #25      | [Versioned keyboard/mobile/contrast pass](qa/mobile-accessibility.md), automated two/five-member local suite and redacted screenshots.                        | Repeat on the deployed build; manual screen-reader/physical-device review and Hikaru sign-off.                                                                                                             |
| #32      | [Reproducible demo](demo/README.md), known synthetic scenario, reset/run/capture steps, local screenshot evidence.                                            | #31 user-session handoff and screenshots/recording from the same final deployed build, with verified SHA/source/privacy metadata.                                                                          |
| #39      | [Initial slide deck](presentation/index.html), [source/citation ledger and speaker notes](presentation/README.md), PDF export helper.                         | All six owners verify their material, agree speaking order, incorporate real #34–#36/#32 evidence, complete timed rehearsal, submit and link receipt by 13 November 2026 23:59 SGT.                        |
| #41, #44 | This matrix and fork branch are the owner handoff artifact.                                                                                                   | Post the reviewed artifact links and precise blockers using the existing Raccoon33 identity; no invented delivery date or teammate commitment.                                                             |

## Deployment/research boundaries

Worker implementation #74 and operational #79 were reported clean at reviewed heads; do not describe their code as absent. They are not part of main b4a4434's worker runtime and are not deployed merely by this local frontend branch. #75's latest timestamp correction needs formal acceptance. Shared OneMap custody/rotation and deployment receipts remain their owners' work. #67's evidence-privacy findings were independently verified resolved at 92a480c; the earlier slide packet's open-privacy statement is superseded. No real latency, capacity, AWS bill, participant study, final sign-off or submission is supplied by our local tests.

GitHub API identity access previously returned Forbidden. This branch does not switch tokens/accounts, close issues, approve on anyone's behalf, merge upstream PRs or publish status comments automatically. The user reports completing reviews of #76–#78. #85 includes the original #84 commit; #84 can be closed as superseded without closing issue #8 or deleting the feature branch. #85 may enter formal review once its title/body reflect readiness and the known acceptance limits. Local composition preserves their authorship/history and all AI-usage records.

## Reviewed merge sequence — 29 October 2026

Use merge commits in this order: **#78 → #76 → #85 → #77 → #86**. The refreshed heads preserve predecessor ancestry, so each PR's diff shrinks after its predecessor merges. Avoid squash/rebase merges for this stack; they discard the ancestry used to prevent repeated conflicts.

1. #78: independent E10 study materials, placed first to avoid another AI-log collision. This is preparation, not completed sessions.
2. #76: town reference map and accessible details.
3. #85: member input/editing and ranked comparisons, composed with #76; includes neutral service-error guidance for writes whose result is uncertain.
4. #77: empty/error recovery, retaining both the ranked comparisons and map; includes the preference-safe timeout wording and regression.
5. #86: validation focus/contrast, combined browser QA, reproducible demo and initial presentation.

All contributions and both acceptance/browser evidence ignore paths are preserved. Local checks and synthetic browser proof do not close the issues' real-data/deployed acceptance gates. This sequence is prepared and pushed for review; no upstream PR was merged during the integration work. Recheck current main and CI before an eventual merge if unrelated work lands meanwhile.
