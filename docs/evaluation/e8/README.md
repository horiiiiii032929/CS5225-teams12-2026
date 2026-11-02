# E8 rental-number audit

**Experiment:** E8, rental component only

**Run date:** 13 October 2026 (Singapore time)

**Status:** Completed for the source-level rent audit. A [31 October deployed spot-check](deployed-audit-2026-10-31.md) covers 129 rent summaries and all 27 town keys for one pinned destination; #19's multi-destination and exact-address commute acceptance remains pending.

## Question and scope

This audit checks whether FlatSplit calculates HDB town/flat-type medians consistently with HDB's separately published quarterly median table. Both inputs are official HDB datasets, so this is an aggregation-consistency check rather than independent verification of the owner-declared rents.

The comparison uses the same period on both sides:

- Detailed input: April through June 2026 records from [Renting Out of Flats from Jan 2021](https://data.gov.sg/datasets/d_c9f57187485a850908655db0e8cfe651/view).
- Benchmark: `2026-Q2` from [Median Rent By Town And Flat Type](https://data.gov.sg/datasets/d_23000a00c52996c55106084ed0339566/view).
- Recommendation scope: `3-ROOM`, `4-ROOM`, and `5-ROOM`.
- Town coverage: all 27 towns in the detailed source, exceeding the plan's 20-town sample.

The script calculates the ordinary median of each detailed-record group and subtracts the published numeric median. It maps HDB's benchmark labels `3-RM`, `4-RM`, and `5-RM` to the detailed dataset's labels. Comparison keys are whitespace-trimmed because the downloaded benchmark contains `QUEENSTOWN ` with a trailing space; the source irregularity is not silently changed in either source file.

## Result

| Metric                                                        | Result       |
| ------------------------------------------------------------- | ------------ |
| Town/flat-type combinations in the 3/4/5-room scope           | 81           |
| Groups with a numeric published Q2 median                     | 72           |
| Exact matches among numeric comparisons                       | 65 of 72     |
| Non-exact numeric comparisons                                 | 7 of 72      |
| Median absolute difference                                    | S$0          |
| Mean absolute difference                                      | S$3.40       |
| Maximum absolute difference                                   | S$100        |
| Maximum absolute percentage difference                        | 2.70%        |
| Groups with a non-numeric published value                     | 6            |
| Groups whose town was absent from the published Q2 benchmark  | 3 (`TENGAH`) |
| Trailing-12-month groups currently usable for recommendations | 75 of 81     |
| Trailing-12-month groups currently marked `LOW_CONFIDENCE`    | 5 of 81      |
| Trailing-12-month groups currently missing                    | 1 of 81      |

The seven non-exact numeric comparisons are:

| Town          | Flat type | Detailed rows | Calculated | Published | Difference |
| ------------- | --------- | ------------: | ---------: | --------: | ---------: |
| ANG MO KIO    | 5-ROOM    |            36 |      3,875 |     3,880 |         -5 |
| CLEMENTI      | 4-ROOM    |           132 |      3,925 |     3,900 |         25 |
| JURONG WEST   | 5-ROOM    |           239 |      3,800 |     3,700 |        100 |
| MARINE PARADE | 4-ROOM    |            23 |      3,400 |     3,350 |         50 |
| QUEENSTOWN    | 4-ROOM    |           129 |      4,100 |     4,130 |        -30 |
| SEMBAWANG     | 4-ROOM    |            68 |      3,175 |     3,180 |         -5 |
| TOA PAYOH     | 5-ROOM    |            47 |      4,000 |     4,030 |        -30 |

The audit does not establish why those seven values differ. The detailed export was updated on 2 October 2026, after the quarterly benchmark's 24 July 2026 update, so later source revisions are one possible explanation; HDB's aggregation cutoff, methodology, or rounding may also differ. These are hypotheses, not findings from the available metadata.

## Missing and low-volume evidence

The downloaded published benchmark contains a non-numeric `-` for six scoped groups. Every one has fewer than 20 records in the detailed Q2 extract:

| Town          | Flat type | Detailed Q2 rows | Calculated median |
| ------------- | --------- | ---------------: | ----------------: |
| BUKIT TIMAH   | 3-ROOM    |                7 |             3,200 |
| BUKIT TIMAH   | 4-ROOM    |               10 |             3,500 |
| BUKIT TIMAH   | 5-ROOM    |                6 |             4,300 |
| MARINE PARADE | 5-ROOM    |                5 |             4,050 |
| PASIR RIS     | 3-ROOM    |                7 |             2,000 |
| SEMBAWANG     | 3-ROOM    |               10 |             2,900 |

HDB's [rental-statistics guidance](https://www.hdb.gov.sg/renting-a-flat/renting-from-open-market/rental-statistics) says a median is not shown when there are fewer than 20 transactions in a town/flat-type quarter. The CSV marker itself is retained as non-numeric evidence rather than interpreted as zero rent.

`TENGAH` is not present in the Q2 benchmark's town keys. The detailed Q2 source has no `TENGAH × 3-ROOM` rows, one `4-ROOM` row, and two `5-ROOM` rows. Those groups therefore have no comparable published median.

For the production trailing-12-month window (`2025-10` through `2026-09`), FlatSplit does not use a fixed minimum-row rule. The approved block-cluster bootstrap rule marks five non-empty groups as `LOW_CONFIDENCE`: `BUKIT TIMAH × 5-ROOM`, `CENTRAL × 4-ROOM`, `PASIR RIS × 3-ROOM`, `TENGAH × 4-ROOM`, and `TENGAH × 5-ROOM`. `TENGAH × 3-ROOM` is missing. The observed statistics remain available even when a group cannot drive a recommendation.

## Evidence and reproduction

- [Deployed rent and commute spot-check](deployed-audit-2026-10-31.md)
- [Deployed machine-readable receipt](raw/2026-10-31/deployed-audit.json)
- [Deployed read-only capture script](../../../tools/evaluation/e8_deployed_audit.py)
- [Full 162-row audit table](rent-audit-2026-q2.csv)
- [Machine-readable result summary](rent-audit-summary.json)
- [Audit script](../../../tools/evaluation/e8_rent_audit.py)

Input digests:

- Detailed export SHA-256: `767a94819f4bb96bc4cff411064bedf6bef63ed053c05de1e2b560b65d85b1c9`
- Published median export SHA-256: `ae13566804f2c3ac088827f62c386c610055de6ef09f593a096031799a14275a`

The source exports are not committed because they are reproducible public datasets and the detailed file is approximately 10 MB. With the three source/evidence files available locally, reproduce the committed outputs from the repository root:

```sh
python3 tools/evaluation/e8_rent_audit.py \
  --transactions /path/to/RentingOutofFlats.csv \
  --published-medians /path/to/MedianRentByTownAndFlatType.csv \
  --bootstrap-evidence /path/to/hdb-bootstrap-ci.csv \
  --output docs/evaluation/e8/rent-audit-2026-q2.csv \
  --summary-output docs/evaluation/e8/rent-audit-summary.json
```

## Remaining E8 work

The deployed run confirms cached records for all 27 towns for one pinned destination, with 26 successful routes and one explicit unavailable result. It does not answer the multi-destination exact-address-versus-snapped-station question. That remains #19's responsibility and requires its reviewed route-coverage evidence to be linked before formal E8 closure.
