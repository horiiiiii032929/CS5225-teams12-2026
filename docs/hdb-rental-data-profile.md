# HDB rental data profile and town-summary schema

**Issue:** [#2 - Profile HDB rental data and define rent summary schema](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/2)

**Contract dependency:** [#6 - Agree API contracts and DynamoDB access patterns](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/6)

**Profiled:** 12 October 2026 (Singapore time) · **Reviewer requested:** Ming · **Status:** Initial schema notes

## Review links

- [Representative source-row sample](data/hdb-rental-sample-2026-09.csv)
- [Provisional API and DynamoDB contract](api-contract.md#dynamodb-design)
- [Official HDB dataset page](https://data.gov.sg/datasets/d_c9f57187485a850908655db0e8cfe651/view)
- [Official download API instructions](https://guide.data.gov.sg/developer-guide/dataset-apis/download-dataset)

## Source and freshness

| Property             | Observation                                                                                |
| -------------------- | ------------------------------------------------------------------------------------------ |
| Publisher            | Housing & Development Board (HDB), through data.gov.sg                                     |
| Dataset              | `Renting Out of Flats from Jan 2021`                                                       |
| Dataset ID           | `d_c9f57187485a850908655db0e8cfe651`                                                       |
| Source coverage      | January 2021 through September 2026                                                        |
| Update cadence       | Monthly. The parent collection's official metadata declares `frequency: monthly`.          |
| Profiled release     | Source month September 2026; data.gov.sg `lastUpdatedAt` was `2026-10-02T10:06:14+08:00`.  |
| Source qualification | Values are owner-declared and indicative. HDB says that it does not verify their accuracy. |
| Licence              | Singapore Open Data Licence, as linked by the dataset page                                 |
| Retrieved export     | 212,597 rows; SHA-256 `767a94819f4bb96bc4cff411064bedf6bef63ed053c05de1e2b560b65d85b1c9`   |

The update cadence and timestamps were checked against the official [collection metadata](https://api-production.data.gov.sg/v2/public/api/collections/166/metadata) and [dataset metadata](https://api-production.data.gov.sg/v2/public/api/datasets/d_c9f57187485a850908655db0e8cfe651/metadata). The source publishes one cumulative CSV rather than a separate file for each month. A monthly ingestion must therefore archive the retrieved raw file and derive the newest complete source month from the data, not from the retrieval date.

## Source fields and units

The downloadable CSV has exactly six columns. The datastore search API also supplies a synthetic `_id`; it is not part of the CSV and must not be treated as a stable rental identifier.

| Source column        | Source type       | Meaning and FlatSplit treatment                                                                                                                                                                |
| -------------------- | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `rent_approval_date` | Month (`YYYY-MM`) | Rental approval month; aggregation time key                                                                                                                                                    |
| `town`               | Text              | HDB town spelling, upper case; town-summary key                                                                                                                                                |
| `block`              | Text              | Preserve as text because values may contain letters                                                                                                                                            |
| `street_name`        | Text              | Preserve source spelling; not needed by the town summary                                                                                                                                       |
| `flat_type`          | Text              | One of `1-ROOM`, `2-ROOM`, `3-ROOM`, `4-ROOM`, `5-ROOM`, `EXECUTIVE` in this snapshot                                                                                                          |
| `monthly_rent`       | Numeric           | Whole-flat monthly rent. The source metadata does not declare a currency unit; FlatSplit's Singapore-only contract interprets it as SGD per month and must label that as a project assumption. |

The source contains 27 town values. In particular, the exact keys are `CENTRAL` (not `CENTRAL AREA`), `KALLANG/WHAMPOA`, and the newly represented `TENGAH`. Code must treat the observed town set as source-controlled rather than hard-code the earlier 26-town assumption.

## Profile results

The full export has 69 continuous source months from `2021-01` through `2026-09`.

| Check                                            | Result                                                                         |
| ------------------------------------------------ | ------------------------------------------------------------------------------ |
| Null, empty, or whitespace-only values           | 0 in every source column                                                       |
| Leading or trailing whitespace                   | 0 values in every source column                                                |
| Invalid/non-positive/non-integral `monthly_rent` | 0                                                                              |
| Observed monthly-rent range                      | 300 to 9,200                                                                   |
| Town values                                      | 27                                                                             |
| Flat-type values                                 | 6                                                                              |
| Exact repeated six-column rows                   | 1,630 additional rows across 1,570 repeated row shapes; maximum multiplicity 5 |

Exact repeated rows are not automatically duplicates: the source has no contract or transaction identifier, so two approvals can legitimately share month, block, street, flat type, and rent. Version 1 retains every valid row and records the resulting sample size. It does not trim or winsorise the owner-declared rent range; the median limits the effect of extreme values.

The [12-row sample](data/hdb-rental-sample-2026-09.csv) comes from the latest source month and includes every available flat type, several towns, alphanumeric blocks, the slash in `KALLANG/WHAMPOA`, and two same-block 1-room observations with different rents. It is evidence of source shape, not a statistically random sample.

## Town-level benchmark evidence

The provisional FlatSplit benchmark uses the 12 complete source months ending at the latest source month: `2025-10` through `2026-09`. That window contains 37,012 records and 129 observed town/flat-type groups.

For the three flat types currently proposed for group-size mapping, 80 of 81 town/flat-type combinations have data:

- `3-ROOM`: 26 of 27 towns; `TENGAH` has no observations.
- `4-ROOM`: 27 of 27 towns.
- `5-ROOM`: 27 of 27 towns.

The smallest non-empty groups are `TENGAH × 4-ROOM` and `TENGAH × 5-ROOM`, each with 5 records. Version 1 stores every non-empty summary for all six source flat types but does not use a statistically weak summary in recommendations. A missing combination produces no summary item and becomes `RENT_UNAVAILABLE`, never zero rent.

Representative derived summaries, using the rules below:

| Town        | Flat type | Rows | Blocks |   P25 | Median |   P75 | Median 95% CI  | Relative width | Quality          |
| ----------- | --------: | ---: | -----: | ----: | -----: | ----: | -------------- | -------------: | ---------------- |
| QUEENSTOWN  |    4-ROOM |  433 |     90 | 3,800 |  4,150 | 4,400 | 4,000–4,200.63 |          4.83% | `USABLE`         |
| JURONG EAST |    4-ROOM |  317 |    107 | 3,100 |  3,500 | 3,700 | 3,400–3,500    |          2.86% | `USABLE`         |
| TAMPINES    |    4-ROOM |  924 |    438 | 3,200 |  3,400 | 3,600 | 3,400–3,500    |          2.94% | `USABLE`         |
| CENTRAL     |    4-ROOM |  204 |     31 | 3,800 |  4,450 | 5,000 | 4,000–4,800    |         17.98% | `LOW_CONFIDENCE` |
| TENGAH      |    4-ROOM |    5 |      5 | 3,200 |  3,400 | 3,500 | 3,200–4,000    |         23.53% | `LOW_CONFIDENCE` |
| TAMPINES    |    5-ROOM |  612 |    283 | 3,430 |  3,700 | 3,900 | 3,600–3,700    |          2.70% | `USABLE`         |

For the proposed 3/4/5-room recommendation set, 75 of 81 possible combinations are usable under the approved confidence rule. Five non-empty combinations are `LOW_CONFIDENCE`: `TENGAH × 4-ROOM`, `TENGAH × 5-ROOM`, `BUKIT TIMAH × 5-ROOM`, `PASIR RIS × 3-ROOM`, and `CENTRAL × 4-ROOM`. `TENGAH × 3-ROOM` is missing. This result also shows why row count alone is insufficient: `CENTRAL × 4-ROOM` has 204 rows but its block-cluster interval is too wide.

## Version 1 aggregation rules

1. Validate the exact six-column source schema. Reject publication if a required column is missing or renamed.
2. Parse `rent_approval_date` strictly as `YYYY-MM`; preserve `town`, `block`, `street_name`, and `flat_type` exactly after rejecting blank or whitespace-padded values.
3. Parse `monthly_rent` as a positive integer. Reject the snapshot on invalid values rather than silently dropping rows.
4. Let `sourceMonthTo` be the maximum source month and require the preceding 11 calendar months to be present. Set `sourceMonthFrom` to the first of those 12 months.
5. Keep every valid row in that inclusive window. Do not deduplicate or remove outliers in version 1.
6. Group by the exact pair `(town, flat_type)` for all six source flat types and sort rents ascending. Compute P25, median, and P75 with the R-7 linear quantile rule: `h = (n - 1) × p`, then linearly interpolate between values at `floor(h)` and `ceil(h)`. Preserve a fractional result if interpolation produces one.
7. Estimate median stability with 10,000 deterministic block-cluster bootstrap resamples. A cluster is the exact `(street_name, block)` pair within the town. Each resample draws the same number of clusters with replacement and carries every source row from each selected cluster. Use the 2.5th and 97.5th R-7 quantiles of the bootstrap medians as the 95% percentile interval. Derive each group's random seed from the snapshot algorithm version, town, and flat type so reruns are reproducible.
8. Set `medianCi95RelativeWidth = (medianCi95High - medianCi95Low) / median`. A summary is `USABLE` only when it has at least two independent blocks and this value is at most `0.10`; otherwise it is `LOW_CONFIDENCE` and must not be used for recommendations.
9. Publish one item for every non-empty group, including `LOW_CONFIDENCE` groups. Record source-row and distinct-block counts. Do not fabricate an item for a missing group.
10. Write the entire immutable snapshot first, validate row/group counts and expected keys, then atomically change `RENT/CURRENT`. Searches already in progress remain pinned to their recorded snapshot.

## Versioned summary shape

The DynamoDB key is `pk = RENT#<snapshotId>`, `sk = TOWN#<town>#<flatType>`. The snapshot ID includes the schema and aggregation algorithm versions plus a content digest, so a revised algorithm publishes a new immutable snapshot even when the source export is unchanged.

```json
{
  "schemaVersion": 1,
  "snapshotId": "rent-v1-r7-block-bootstrap-v1-2026-09-767a94819f4b",
  "sourceDatasetId": "d_c9f57187485a850908655db0e8cfe651",
  "sourceUpdatedAt": "2026-10-02T02:06:14Z",
  "sourceMonthFrom": "2025-10",
  "sourceMonthTo": "2026-09",
  "period": "2025-10/2026-09",
  "town": "QUEENSTOWN",
  "flatType": "4-ROOM",
  "currency": "SGD",
  "unit": "whole-flat/month",
  "statistic": "trailing-12-month-r7-quantiles",
  "median": 4150,
  "p25": 3800,
  "p75": 4400,
  "count": 433,
  "blockCount": 90,
  "bootstrapMethod": "block-cluster-percentile",
  "bootstrapReplicates": 10000,
  "medianCi95Low": 4000,
  "medianCi95High": 4200.625,
  "medianCi95RelativeWidth": 0.0483433735,
  "qualityStatus": "USABLE"
}
```

The `RENT/CURRENT` pointer carries `schemaVersion`, `snapshotId`, `period`, `sourceMonthTo`, `rawRetrievedAt`, and `validatedAt`. It advances only for a newer source month or a strictly newer raw retrieval within the same month. Search responses expose the stored median, per-person estimate, P25, P75, 95% median interval, source-row count, and quality status. A `LOW_CONFIDENCE` summary is returned with the dedicated `RENT_LOW_CONFIDENCE` reason so users can inspect the observed data, but its budget-headroom fields are null and it cannot affect affordability or ranking.

## Decisions and remaining review

- Approved by Mani on 13–14 October 2026: store median, P25, and P75; use R-7 linear interpolation; retain identical-looking source rows because the source cannot prove they are duplicate transactions; store all six flat types; store all non-empty summaries; mark groups with fewer than two independent blocks or a block-cluster bootstrap median interval wider than 10% of the median as `LOW_CONFIDENCE`; represent those exclusions with the dedicated `RENT_LOW_CONFIDENCE` API reason; and still expose their observed distribution, confidence interval, quality status, and sample size without using them in affordability or ranking.
- Still to confirm: the project-level interpretation of `monthly_rent` as SGD per whole flat per month because data.gov.sg leaves the column unit blank.
- Still to confirm: the separate group-size-to-flat-type policy (`2 → 3-ROOM`, `3 → 4-ROOM`, `4-5 → 5-ROOM`). The source profile proves those fields exist but does not establish that occupancy mapping.
