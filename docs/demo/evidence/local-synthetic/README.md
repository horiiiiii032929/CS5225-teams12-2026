# Local synthetic UI evidence — 29 October 2026 SGT

These are redacted captures from the two- and five-member `pnpm test:browser` suites. They are **not deployed screenshots, real HDB/OneMap results or participant study evidence**. The real local HTTP resolver and Moto store were used with a synthetic destination/rent fixture and conditional injected route completions. Only fictional member names are present; invitation inputs are masked.

- `create-mobile.png`: 390px creation form, two-member scenario.
- `results-mobile.png` / `results-desktop.png`: same local two-member scenario at 390 × 844 / 1280 × 900, including ranking, three-town comparison and map.
- `five-member-mobile.png`: five independent member contexts and 390px results/map.
- `audit.json`: sanitised WCAG A/AA automated findings per state and scenario, zero violations in the recorded final run. Two browser journey tests passed. This is not a full assistive-technology audit.
- `manifest.json`: source/artifact hashes and exact limitations. The base commit is the working-tree run's history anchor, not a deployed revision or a claim that uncommitted files were absent. Match source file hashes for the tested implementation; later deck/narrative edits do not retrospectively change this run.

No raw capability links, request bodies, browser storage, traces, videos, Playwright error contexts or identifying participant records are included. Final #32 acceptance requires captures matched to an independently verified final deployed SHA; retain this directory as historical local evidence when adding those later captures.
