# Deployed rent and commute audit — 31 October 2026

This is a read-only spot-check of the shared `FlatSplit-dev` DynamoDB table in AWS account `553455762180`, region `ap-southeast-1`. The capture used strongly consistent reads and made no DynamoDB, OneMap or deployment changes.

## Rent summaries

`RENT/CURRENT` pointed to snapshot `rent-v1-r7-block-bootstrap-v1-2026-09-767a94819f4b`, covering October 2025 through September 2026. The pointer declared 129 town/flat-type summaries and the query returned all 129. HDB reports the source dataset update as 2 October 2026; FlatSplit retrieved and validated the raw data on 29 October 2026, and the latest source month was September 2026.

The stored values are SGD per whole flat per month. Of the 129 summaries across all stored flat types, 97 were `USABLE` and 32 were `LOW_CONFIDENCE`. Low-confidence evidence remains available to users but must not drive ranking. A missing town/flat-type combination has no summary row and likewise cannot drive ranking.

Representative rows:

| Town       | Flat type |     P25 |  Median |     P75 | Records | Blocks |   95% median CI | Quality          |
| ---------- | --------- | ------: | ------: | ------: | ------: | -----: | --------------: | ---------------- |
| ANG MO KIO | 3-ROOM    | S$2,600 | S$2,800 | S$3,000 |   1,278 |    195 | S$2,800–S$2,800 | `USABLE`         |
| QUEENSTOWN | 4-ROOM    | S$3,800 | S$4,150 | S$4,400 |     433 |     90 | S$4,000–S$4,225 | `USABLE`         |
| TENGAH     | 3-ROOM    |       — |       — |       — |       — |      — |               — | Missing          |
| TENGAH     | 4-ROOM    | S$3,200 | S$3,400 | S$3,500 |       5 |      5 | S$3,200–S$4,000 | `LOW_CONFIDENCE` |
| TENGAH     | 5-ROOM    | S$3,300 | S$3,400 | S$3,600 |       5 |      3 | S$2,450–S$3,725 | `LOW_CONFIDENCE` |

These deployed values are consistent with the intended behavior: retain observed distributions, label weak evidence explicitly and exclude weak or missing values from recommendations.

## Commute cache

The table scan found 27 commute records for the pinned `KENT_RIDGE` station under routing profile `pt-v1:2026-10`: 26 successful town routes and one unavailable route. Successful records identify OneMap public-transport routing as their source and were computed on 30 October 2026 for the weekday 08:30 profile.

- Fastest observed route: `QUEENSTOWN`, 12.48 minutes.
- Slowest observed route: `SEMBAWANG`, 61.57 minutes.
- Unavailable route: `TENGAH`, reason `NON_ROUTABLE_TOWN`; no minutes were fabricated.

These are town principal-station to pinned destination-station estimates. They are not live travel times, door-to-door routes or exact-address routes. This receipt proves that the deployed table contains results for all 27 town keys for one destination, including explicit unavailability. Issue #19 remains responsible for the separate 20-destination route-coverage and exact-address-versus-snapped-station acceptance evidence.

## Evidence and reproduction

- [Unedited machine-readable receipt](raw/2026-10-31/deployed-audit.json)
- [Read-only capture script](../../../tools/evaluation/e8_deployed_audit.py)

Reproduce from the repository root after authenticating the `flatsplit` AWS profile:

```sh
uv run python tools/evaluation/e8_deployed_audit.py \
  --profile flatsplit \
  --region ap-southeast-1 \
  --stack FlatSplit-dev \
  --output docs/evaluation/e8/raw/2026-10-31/deployed-audit.json
```

The account, region, physical table name, capture timestamp, pointer metadata and every returned commute record are retained in the receipt. The script resolves the physical table from CloudFormation rather than relying on a pasted table name.

## Remaining acceptance

This receipt completes #20's deployed representative-value spot-check, subject to Ming's review and merge of the evidence PR. Formal closure still depends on linking #19's reviewed route-coverage evidence; it does not depend on #28/E6 or another deployment.
