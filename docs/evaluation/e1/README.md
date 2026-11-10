# E1 warm-read evidence — 9 November 2026

Run `WK20261109W1A` measured cached complete-result reads against `FlatSplit-eval` at an offered 2 requests/s for 600 seconds. It recorded 1,200/1,200 successful measured reads and 240 setup requests. Client HTTP p50/p95/p99 were **382/457/505 ms**; planned-arrival-to-completion p50/p95/p99 were **383/458/509 ms**. See the [finish receipt](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/30#issuecomment-6735588370), [operator reconciliation](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/30#issuecomment-6736291485) and [bounded acceptance](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/30#issuecomment-6738327225).

**Limits:** No operator monitored the run live, and the pre-window receipt was missing. The operator's CloudWatch reconciliation was retrospective and could not enforce stop conditions. The raw `config.json` preserves the operator-monitoring claim as it was supplied at run time; it is not proof of monitoring. Cold-request latency, cold-start share, W2 throughput, maximum capacity and a fixed-instance baseline were not measured. No rerun occurred.

## Files and provenance

- `raw/2026-11-09/WK20261109W1A/` contains the original config, plan, sample records, summary, k6 log and local supervisor result, copied without modification. `supervisor.json` is a local client observation, not live operator monitoring. Its `sample_rows_observed` was a polling snapshot, not the final file count.
- `scripts/` contains the four scripts used for this run. Their bytes match `tools/load/` at reviewed revision `236d850`. The deployed application source revision is recorded separately in the run config; it is not the script revision.
- `SHA256SUMS` hashes the archived files. Place IDs in the plan are expired target-local identifiers, not reusable credentials. Do not reuse this plan or config to generate traffic.
- The archived log and records are the original retained output. The runner does not retain HTTP response bodies or capabilities; samples were checked for the expected allowlisted fields before publication.

## Reproduce the summary offline

From this directory, using the project's Python 3.13 environment:

```sh
python scripts/summarize.py \
  --plan raw/2026-11-09/WK20261109W1A/plan.json \
  --samples raw/2026-11-09/WK20261109W1A/samples.jsonl \
  --output /tmp/WK20261109W1A-reproduced.json
cmp raw/2026-11-09/WK20261109W1A/summary.json /tmp/WK20261109W1A-reproduced.json
```

The original summarization attempt used macOS system Python 3.9 and failed because it lacks `datetime.UTC`. The archived summary was produced from the same raw records with project Python 3.13; k6 was not rerun. The offline reproduction above was checked byte-for-byte against the archived summary.
