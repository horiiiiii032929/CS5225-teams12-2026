# Final report review draft

The canonical review source is [final-report-draft.md](final-report-draft.md).
The corresponding PDF is [flatsplit-final-report-draft.pdf](../../output/pdf/flatsplit-final-report-draft.pdf).

From the repository root, regenerate it with:

```sh
uv run --no-project --with reportlab tools/report/render_report.py
```

The renderer handles this report’s Markdown subset and draws a report-specific
vector layout of its Mermaid component paths. Update both the source figure and
renderer if those paths change. Review the rendered pages after regeneration;
the renderer refuses a report exceeding the course’s ten-page limit.

This is a review draft. Its checklist retains missing measurements, member
fact-checks, final deployed-revision reconciliation and the submission receipt.
Merging it does not complete issue #38 or establish deployed acceptance.
