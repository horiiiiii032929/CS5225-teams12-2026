# Final report

The canonical source is [final-report-draft.md](final-report-draft.md). The
submission-ready PDF is [Final.pdf](../../output/pdf/Final.pdf).

From the repository root, regenerate it with:

```sh
uv run --no-project --with reportlab tools/report/render_report.py
```

The renderer handles this report’s Markdown subset and draws a report-specific
vector layout of its Mermaid component paths. Update both the source figure and
renderer if those paths change. Review the rendered pages after regeneration;
the renderer refuses a report exceeding the course’s ten-page limit.

The report records missing measurements as limitations instead of leaving
internal completion gates in the submitted document. Submission coordination
still requires the team's final factual check and the Canvas receipt in #38;
merging the report does not itself provide that receipt.
