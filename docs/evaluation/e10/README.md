# E10 / #31 user-testing kit

**Prepared 27 October 2026. Status: preparation only; no participants recruited, sessions completed or results claimed.**

Owner: Hikaru (@horiiiiii032929). Reviewer: @Raccoon33. The [evaluation plan](../../evaluation-plan.md) and [#31](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/31) retain the 2–5 November session window, minimum three people outside the implementation pair, and aim of 8–12 participants. This kit does not change those dates or establish reviewer approval.

## Start here

1. Have Raccoon33 review this protocol, wording, A/B cards and scoring before recruitment/testing.
2. Recruit at least three willing participants outside the implementation pair; aim for 8–12. Use P01 etc. Store any contact/scheduling information separately from research notes. Do not contact people automatically from this kit.
3. Complete the readiness checklist below. Book 30–40 minutes per participant, with breaks or withdrawal allowed. Have one moderator and, if available, one silent note-taker.
4. Copy [session.md](templates/session.md) per session and use the allocation table in the [moderator guide](moderator-guide.md). Show only [participant tasks](participant-tasks.md) and the assigned card, never the answer key or complete repository folder.
5. Log blockers in [defect-and-retest.md](templates/defect-and-retest.md). Fix critical blockers and rerun affected tasks before filling [summary.md](templates/summary.md).

Suggested invitation, for you to send when ready:

> Could you spare 30–40 minutes to try our flatmate neighbourhood app? We’re testing the app, not you. You’ll use supplied fictional names and preferences, and can stop at any time. No real home address is needed.

## Readiness checklist

- [ ] Reviewer accepts the protocol and study presentations; record review link/date.
- [ ] Integrated build includes working group creation/join, destination lookup, saved member input/edit/reload, progress/retry and ranked results/comparisons/map; record actual deployed commit and URL.
- [ ] #25 mobile/keyboard checks and #26 recovery checks are verified for that build. PRs #76/#77 alone do not establish integration.
- [ ] An authorised owner confirms working shared OneMap access, usable rent publication and worker integration. Record only non-secret verification link/time.
- [ ] Moderator preflights two distinct browser contexts with supplied test names and public destinations. Prepare a reproducible scenario with at least three feasible ranked towns; record rent snapshot/period and commute basis. S$1,800/60 minutes is a starting scenario, not a guarantee of matches.
- [ ] Confirm a supported way to edit preferences and return to results; do not promise an edit control before #8/#13/#23 integration supplies it.
- [ ] Prepare known no-match, unavailable-route and status-outage cases in a reviewed local/isolated environment. Never disrupt the shared deployment for the study. Mark controlled fixtures/faults separately.
- [ ] Run card generation verification, then a **moderator dry run**, covering timing, disclosure of synthetic data, scenario order, note-taking and answer-key separation. A dry run is not a participant session.
- [ ] Confirm device/browser, independent group contexts, timer, note template and a private evidence folder that will not be committed. Capture no invite/member capability URLs, tokens, real addresses or identifying screenshots.
- [ ] Populate any missing build/scenario values in session copies. Blank fields mean not ready, not success.

If an integrated gate fails, record it as blocked. The offline comparison cards may be reviewed/piloted separately, labelled `synthetic_card`; they do not satisfy #31's integrated group-input/result-comparison acceptance. Do not replace a missing live journey with a demonstration and mark it passed.

## Files and reproducibility

- [Moderator guide](moderator-guide.md): script, assistance rules, order allocation and scoring.
- [Participant tasks](participant-tasks.md): neutral task prompts without navigation hints.
- [Cards X-A](cards/x-a.md), [X-B](cards/x-b.md), [Y-A](cards/y-a.md), [Y-B](cards/y-b.md): matched offline stimuli. A shows averages only; B adds member commutes and gap. Use only the assigned card.
- [Moderator answer key](moderator-answer-key.md): correct rankings and interpretation rubric; withhold from participants.
- [Synthetic fixture inputs](data/study-fixtures.json) and [generator](../../../tools/evaluation/prepare_e10.py): same underlying numbers and ranking algorithm for both presentations, no network or credentials.
- [Session](templates/session.md), [defect/retest](templates/defect-and-retest.md) and [summary](templates/summary.md): blank recording templates, not evidence.

From the repository root:

```sh
uv run --package flatsplit-api python tools/evaluation/prepare_e10.py --check
# Only to intentionally rebuild the cards after reviewing fixture/ranker changes:
uv run --package flatsplit-api python tools/evaluation/prepare_e10.py
```

The key records fixture/ranker SHA-256 values. Record the kit commit and hashes used in each session; freeze those materials across a cohort. Any changed build or card version gets its own cohort/retest annotation. Keep original observations unchanged.

## Evidence and completion

Keep consent/contacts outside the repository. Use anonymous session IDs in notes and redact exports before proposing a separate evidence commit. No actual participant records belong in these templates. Follow the evidence index's dated-run convention for approved anonymised exports, retaining original observations and recording the protocol/material versions and procedure.

Close #31 only after at least three eligible participants each attempt the integrated group-input and results-comparison tasks unaided, issues are recorded, critical fixes are rerun, and the reviewed build/evidence is linked. Eight to twelve is the study target; a three-person minimum is not equivalent to meeting that target. Summaries for #32/#38/#39 must distinguish synthetic-card findings, integrated observations and blocked tasks. Small convenience samples and static cards cannot establish population-level or live-system performance claims.
