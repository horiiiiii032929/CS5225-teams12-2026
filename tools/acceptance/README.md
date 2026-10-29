# Acceptance gate runner

One command that runs the #44 acceptance gate against a running FlatSplit API and writes a JSON evidence file. The same script runs locally and against the deployed API; the evidence records which one it was.

| File                                 | What it is                                                                                                                    |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| [`acceptance.py`](./acceptance.py)   | The gate. Standard library only, so it runs on any machine with Python 3, including one without the repository's dependencies |
| [`serve_local.py`](./serve_local.py) | Serves the **real** Lambda resolver over HTTP with Moto as AWS, so the gate can be exercised before deployment access exists  |

`serve_local.py` is not a second, fake API. It imports `flatsplit_api.local`, which turns each request into an API Gateway v2 event for the same resolver in `handlers/http.py` that runs in Lambda. Only DynamoDB and SQS are replaced.

## Run it

```bash
# terminal 1 - local environment (Moto AWS, real handler, live OneMap)
export ONEMAP_TOKEN=...   # from the stage secret, never committed
uv run --package flatsplit-api --extra local python tools/acceptance/serve_local.py

# terminal 2 - the gate
python3 tools/acceptance/acceptance.py
```

After deployment, the same script with different arguments:

```bash
python3 tools/acceptance/acceptance.py \
    --base-url https://<host>/api \
    --mode deployed \
    --revision "$(git rev-parse --short HEAD)"
```

The process exits non-zero if any check fails, so it can gate a pipeline.

## What it checks

| Stage | Check                                                                                                                                                                    | Issue     |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------- |
| 0     | `GET /health`                                                                                                                                                            | -         |
| 1     | Both destinations resolve and **every** candidate carries a station key and both finite coordinates                                                                      | #14       |
| 2     | A repeated lookup returns the same `placeId` and the same pin                                                                                                            | #14       |
| 3     | Group create, then a second member joins with the invite token                                                                                                           | #12 / #13 |
| 4     | Both members save preferences by `placeId`                                                                                                                               | #14       |
| 5     | Reopening with the **other** member's token gives **each member** back the destination, **the same pin** and the limits they saved, and leaks no credential at any depth | gate      |
| 6     | No token and an invalid token return 401; another member's token cannot edit this member (403)                                                                           | #12       |
| 7     | A search starts, starting again is idempotent, the status is read as `pending`, `complete` or `stale` on its own terms, and the view carries no credential               | #16 / #18 |
| 8     | Saving a preference marks the earlier search `stale`                                                                                                                     | D08       |

## It does not fail because #15 is open

Commute minutes come from #15's queue consumer. Until that worker runs on the stack under test a search stays `pending`, so stage 7 records `INFO` with the number of pairs still waiting instead of `FAIL`. That number is the integration gap, measured rather than described. When the worker runs, this script needs no change and the same stage reports the ranked result.

Stage 7 branches on the status rather than on "complete with results", because three outcomes are not one. A `complete` search with every town excluded is a real answer and is recorded as a pass with the exclusion reasons, not as a missing worker. A search that is already `stale` before stage 8 edits anything is a failure: the staleness came from somewhere this run cannot see, so neither stage can be judged. Pending pairs are `total - resolved`, because `resolved` already counts the pairs that came back unavailable.

An acceptance script that is red by construction until everyone else finishes is a script nobody runs, and a script nobody runs helps nobody on deployment day.

## Honest limits

1. **The gate's own checks are tested.** `tests/test_acceptance.py` runs in `pnpm test:evidence` and holds a regression for each case an earlier version of this script accepted: pending pairs double-counted, a candidate with no longitude, a nested issued token, a failing creation response printing the tokens it had already handed out, a reloaded pin moved to another finite coordinate, and a credential inside `progress` reaching a detail line. A gate that reports success wrongly is worse than the bug it misses.

   Two of those are worth stating as rules, because they are easy to reintroduce. A saved value is checked against **the value that was saved**, not merely against its type: finite coordinates are not preserved coordinates, so stage 5 compares the reloaded pin with the one `/places` handed out, to a tolerance of 1e-9 degrees, which is the float round trip through storage and nothing a person would call a different place. And every response-derived value is sanitized before it is interpolated — whole bodies through `detail_of`, single values through `shown` — because the `redact(summary)` at the end rewrites structure and cannot take a credential back out of a string. That includes the count slots: `progress.unavailable` arriving as an object, rather than a number, used to print its contents into the pending detail even though the run already failed. Responses that should carry no capability at all are rejected outright by `Report.no_credentials`, which reports the paths and never the values.

2. **`local-moto` is not deployed acceptance.** Moto has no real table contention, no IAM, no cold starts and no CloudFront. The evidence file records `mode`, and comments linking it must say so too.
3. **Local rent is synthetic.** `POST /searches` returns 503 without a `RENT/CURRENT` pointer, and publishing real summaries is #10. `serve_local.py` seeds five towns, tagging every item `syntheticLocalFixture`. A deployed run uses the real #10 records.
4. **`/places` calls live OneMap**, so it spends quota and needs a valid token; the token lasts three days and has no renewal endpoint (#27).
5. Stage 1's pinned-station assertions need the persistent places work from #14; stage 4 fails on a build without it, which is the bug that issue describes.

## Evidence file

`evidence/acceptance_<mode>_<timestamp>.json` holds every HTTP round trip with its status and milliseconds, every check with its result and detail, the representative records (such as each member's stored station snapshot), and the `mode` and `revision` of the build under test. Every credential field is replaced with `<redacted>` at any depth before anything is printed or written, so the file is safe to attach as it stands. The directory is ignored by git; attach the file to the issue instead.
