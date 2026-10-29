# E10 moderator guide

**Preparation only.** Use with the [readiness checklist](README.md). The static cards support a controlled presentation comparison; they do not provide a production study toggle or test live interactions.

## Session script and timing

Allow 30–40 minutes: 3 minutes introduction, up to 12 minutes integrated journey, up to 10 minutes two card conditions, 5 minutes recovery, then debrief. If a task reaches its cap, record `timeout`, elapsed time and current state; stop or offer help only after saving the unaided outcome. Do not rush participants to fit a schedule.

Read:

> We’re testing this app, not you. Use only the supplied fictional names and preferences. Please say what you expect and what confuses you. I won’t guide you during a task, but you can stop or skip at any point. We’ll record anonymous notes and timing. Is that okay?

Record agreement before tasks. If declined, stop without collecting observations. Ask separately before any optional recording; written anonymous notes are sufficient. Do not collect real home addresses, passwords or access tokens.

Before each task, show only its participant prompt and start timing when the participant begins acting. Stop on observable completion, explicit abandonment, blocker or cap. Record pauses/interruption duration separately. Do not silently discard slow or failed trials.

During unaided tasks, stay silent except for neutral “What are you thinking?” prompts. Do not point to controls, explain a ranking, suggest a budget or give the right answer. Any hint changes the outcome to `completed_with_help` if completed; retain the unaided elapsed time/outcome. Stop for a privacy/access risk or a participant request.

For group tasks, the participant performs both member flows using separate browser contexts. The moderator may open the second blank context beforehand, but may not fill preferences, join or navigate for the participant during the timed task. This is a usability exercise, not proof of multi-user concurrency.

## Task sequence and observable outcomes

| ID  | Prompt source        | Unaided completion criterion                                                                                                                            | Cap   | Evidence mode                        |
| --- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- | ------------------------------------ |
| L1  | Create/join          | Participant creates a two-person test group, transfers invite privately to the second context and joins as the second supplied member                   | 4 min | integrated_app                       |
| L2  | Save/edit/reopen     | Both destinations and limits saved; one requested edit and reload preserve the new values                                                               | 4 min | integrated_app                       |
| L3  | Search/compare       | Participant starts search, interprets actual status, compares at least three feasible towns and identifies a member trade-off using displayed evidence  | 4 min | integrated_app                       |
| C1  | First assigned card  | Participant answers the four card questions before any teaching or answer-key disclosure                                                                | 4 min | synthetic_card                       |
| C2  | Second assigned card | Same questions on the other condition and other scenario; no correctness feedback between cards                                                         | 4 min | synthetic_card                       |
| R1  | Recovery             | Participant recognises a controlled no-match/data-unavailable/status-failure state and takes an offered next action while supplied inputs remain intact | 5 min | controlled_fixture or isolated_fault |
| D1  | Debrief              | Participant explains missing information and rates the integrated experience; no success threshold on opinions                                          | 3 min | interview                            |

The caps are protocol defaults for consistent observation, not product performance requirements. If the app blocks progress, record `blocked` and its evidence mode, not a user error. Complete C1/C2 separately if useful, without counting them as successful L1–L3. A route still pending at L3's cap is an observed task outcome; do not imply the user failed to understand or that all routes are unavailable.

For R1 use a reviewed isolated scenario with the same supplied inputs. Keep reason evidence and expected recovery in the session's moderator notes. Do not expose a real group to faults or edit its data to force a no-match. If no safe reviewed recovery scenario is available, record R1 as `not_run`.

## Condition allocation

A = averages-only; B = identical common fields plus per-member commute and gap. Cards share the same rent, average and ranking for a given scenario. X and Y use different names and slightly different numbers with the same rent/gap trade-off. Each participant sees **different scenarios** across conditions, reducing direct answer recall.

These are planned slots, not recruited participants or results:

| Slot | First card | Second card |
| ---- | ---------- | ----------- |
| P01  | X-A        | Y-B         |
| P02  | X-B        | Y-A         |
| P03  | Y-A        | X-B         |
| P04  | Y-B        | X-A         |
| P05  | X-A        | Y-B         |
| P06  | X-B        | Y-A         |
| P07  | Y-A        | X-B         |
| P08  | Y-B        | X-A         |
| P09  | X-A        | Y-B         |
| P10  | X-B        | Y-A         |
| P11  | Y-A        | X-B         |
| P12  | Y-B        | X-A         |

Use the next unused slot and record actual order. At only three participants the order/scenario distribution is inevitably uneven; disclose that. Eight or twelve complete sessions balance these four sequences. Do not show the other card, fixture, answer key or teaching examples before both conditions finish. Collect ratings immediately after each card. Record a participant's prior familiarity and any accidental exposure.

## Scoring without treating hidden information as error

Use the [answer key](moderator-answer-key.md), retaining the participant's exact anonymised answer before coding it.

- **Choice explanation:** 0 = unsupported/no explanation; 1 = uses an available rent or average-commute fact; 2 = explains a supported trade-off and what remains unknown. Choosing a particular town is not inherently correct.
- **Most-burdened member:** for A, accuracy is `not_observable`, because the individual times are hidden. Record separately whether missing information was recognised (`yes/no/unclear`); do not score A as an incorrect member identification. For B, score `correct/incorrect/no_answer` against the scenario key. A correct guess in A does not establish comprehension.
- **Rank change:** record the observed new first town (`correct/incorrect/no_answer`). Separately code the explanation `supported/unsupported/insufficient_information_recognised/no_answer`. A displays the changed ranks but lacks individual/gap evidence; do not force an unsupported fairness explanation. B can support the smaller-gap explanation. Both conditions retain three feasible towns; priority does not relax constraints.
- **Ratings:** ask clarity, fairness understanding, ease and usefulness, each from 1 (very low) to 5 (very high), or `not_answered`. Ask the participant's reason after rating; do not translate ratings into correctness.

Describe information availability separately from interface usability. B's extra information structurally enables answers unavailable in A. Do not report an A-versus-B accuracy gain as independent causal proof of better usability. Static-card timing also omits app navigation, loading and map interaction. The live journey occurs before cards and may prime participants; disclose that fixed order and prior exposure in the summary.

## After the session

1. Save untouched anonymous notes, observed timings and assistance. Do not overwrite the original with later interpretations.
2. Log reproducible defects with build/card version and severity. A hypothesis about cause must be labelled as such.
3. Fix critical blockers before continuing affected tasks. Rerun those tasks on the corrected build, recording original and retest separately; already-exposed participants are not fresh unaided trials.
4. Summarise all attempts, including blocked, withdrawn and skipped tasks. A participant who declines or withdraws is not a completed session.
5. Ask Raccoon33 to review the coded summary and closure evidence; feed anonymised supported findings to #32/#38/#39.
