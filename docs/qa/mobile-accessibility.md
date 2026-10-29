# #25 mobile and accessibility review

Owner: Raccoon33. Reviewer: Hikaru. Scope: integrated local member input, status, ranked comparisons, map and recovery. This is implementation QA; deployed acceptance remains a separate gate.

## Repeatable checks

Run `pnpm test:browser` using [the local demo instructions](../demo/README.md). The versioned suite uses actual local HTTP/Moto persistence with deliberately synthetic places/rent and injected conditional route completions. It runs two- and five-member groups in separate Chromium browser contexts, at 390 × 844 and 1280 × 900. The earlier independent PR reviews also checked 320px; the integrated automated acceptance target here is 390px.

| Area               | Check and expected result                                                                                                                                                                             |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Group input        | Visible labels, explicit destination choice, inline bounds errors, focus moves to the first invalid field, errors linked by aria-describedby.                                                         |
| Sharing            | Each member uses its own browser context/capability; invitation fragment is removed; screenshot invitation field is masked.                                                                           |
| Status             | Disabled search while unready, actual asynchronous progress, retry without editing inputs, stale results withheld.                                                                                    |
| Results            | Three comparison columns accessible via a labelled focusable horizontal-scroll region; ArrowRight scrolls without moving the document horizontally. Fractional values are retained in the comparison. |
| Map                | Equivalent town list, numbered button labels/pressed state, Space/Enter selects details, reference-point limitations visible.                                                                         |
| Contrast/structure | Axe WCAG 2 A/AA + 2.1 A/AA tags, including text contrast and accessible names, return zero violations at each audited state.                                                                          |
| Focus/layout       | Keyboard submission and map selection work; no page-level horizontal overflow at 390px; user input survives reload and cross-member refresh.                                                          |

The pass found and corrected insufficient contrast in the selected map row's small rent-unit text. A separate integration correction replaces the shared timeout promise that inputs are “unchanged”: a preference PUT may have committed before its response times out. The form retains the draft and tells users to refresh to confirm the result. Component regressions cover this ambiguity.

## Evidence and limitations

A successful run stores sanitised rule IDs/impacts/selectors in `.qa-artifacts/evidence/audit.json`, plus masked screenshots. The committed local evidence handoff is linked from [remaining work](../remaining-work.md). Automated analysis is not a complete accessibility certification: screen-reader speech, physical touch/device behaviour, browser zoom/reflow and additional browser engines still need manual verification. No participant session or deployed run is claimed.

For formal acceptance, repeat against the reviewed deployed build and record the build/run identifiers, actual device/browser, manual focus sequence, contrast results, any findings/fixes, reviewer and evidence link. Retain failures and retests; do not turn a zero-test run into a pass.
