# Issue #34 deployed data-quality and usage evidence

**Captured:** 3 November 2026 · **Environment:** shared `dev`, Singapore · **Window:** 29 October 00:00 UTC to 3 November 04:00 UTC (124 hours) · **Classification:** observed team activity, not a controlled load test

This receipt addresses #34 with read-only evidence from the deployed stack. The raw CloudWatch series and DynamoDB metadata are in [`evidence/deployed-usage-20261103.json`](evidence/deployed-usage-20261103.json). They can be recaptured with [`tools/evaluation/issue34_usage_capture.py`](../../../tools/evaluation/issue34_usage_capture.py).

## Deployment identity and scope

The observed stack is `FlatSplit-dev` in AWS account `553455762180`, region `ap-southeast-1`. CloudFormation reports its latest update at 2 November 2026 10:55:49 UTC, but the stack has no source-revision output. The deployed Git commit is therefore **unknown**; the update timestamp must not be presented as a code revision.

This evidence covers the official HDB rental source and deployed AWS activity. The separate exact-address versus snapped-station commute-quality audit remains owned by E8/#19; the worker observations below demonstrate queue completion, not commute-time accuracy or full OneMap route coverage.

## Data coverage and freshness

The source is HDB's official [Renting Out of Flats from Jan 2021](https://data.gov.sg/datasets/d_c9f57187485a850908655db0e8cfe651/view), dataset `d_c9f57187485a850908655db0e8cfe651`. The deployed `RENT/CURRENT` pointer selected schema-v1 snapshot `rent-v1-r7-block-bootstrap-v1-2026-10-b6e2905f6698`, covering November 2025 through October 2026. The source was updated on 2 November 2026 at 10:06:56 SGT and the file was retrieved and validated on 3 November at 03:00:38 SGT, approximately 16 hours 54 minutes later.

| Measure               |                         Observed |
| --------------------- | -------------------------------: |
| Summary rows          |               129 of 162 (79.6%) |
| Towns                 |                               27 |
| Flat types            | 6 (`1-ROOM` through `EXECUTIVE`) |
| `USABLE` rows         |                               94 |
| `LOW_CONFIDENCE` rows |                               35 |

All 27 supported towns and all six flat types occur somewhere in the published snapshot, but 33 town/flat-type combinations have no records and therefore no summary:

| Missing flat type  | Missing towns |
| ------------------ | ------------: |
| `1-ROOM`           |            26 |
| `2-ROOM`           |             3 |
| `3-ROOM`           |             1 |
| `EXECUTIVE`        |             3 |
| `4-ROOM`, `5-ROOM` |             0 |

The raw receipt lists all 33 missing pairs. The published groups have the following record-count distribution:

| Group                         | Minimum |    P25 | Median |  P75 | Maximum |
| ----------------------------- | ------: | -----: | -----: | ---: | ------: |
| All 129 summaries             |       1 |     44 |    169 |  430 |   1,283 |
| 94 `USABLE` summaries         |       6 | 133.75 |  303.5 |  582 |   1,283 |
| 35 `LOW_CONFIDENCE` summaries |       1 |    9.5 |     17 | 34.5 |     186 |

The quality rule requires at least two independent blocks and a block-cluster-bootstrap 95% median interval no wider than 10% of the median. Of the 35 low-confidence summaries, 32 fail only the interval-width rule and three fail only the independent-block rule; none is unexplained. Low-confidence evidence remains visible to clients but does not enter feasibility or ranking. The 129 observed rows equal the pointer's declared `summaryCount`.

## Requests, failures and queue throughput

| Component            |                       Activity |                                  Failures / throttles |          Duration or throughput |
| -------------------- | -----------------------------: | ----------------------------------------------------: | ------------------------------: |
| HTTP API / Lambda    | 763 requests / 763 invocations | 51 HTTP 4xx; 0 HTTP 5xx; 0 Lambda errors; 0 throttles | 190.504 ms mean Lambda duration |
| Commute worker       |                130 invocations |                                 0 errors; 0 throttles |        990.307 ms mean duration |
| Rent ingestion       |                  4 invocations |                                 0 errors; 0 throttles |    169,913.342 ms mean duration |
| OneMap token refresh |                 80 invocations |                          6 Lambda errors; 0 throttles |      1,673.972 ms mean duration |
| Commute DLQ          |    0 sent / received / deleted |                                        no DLQ traffic |                               — |

The 51 API 4xx responses are client-error responses, not platform failures. The server-side API failure count for this window is zero by both API Gateway 5xx and HTTP Lambda `Errors`.

The six token-refresh errors occurred as two groups of three, in the CloudWatch hours beginning 30 October 22:00 UTC and 31 October 10:00 UTC. Both predate the stack's latest update on 2 November. Because the stack does not record its deployed revision and this capture did not inspect error payloads, the receipt does not assign those historical errors to a particular code version or cause, nor claim that the current deployment retains the fault.

The queue accepted, received and deleted 130 messages. Three observable worker bursts completed every invocation and completion log:

| Start (UTC)  | Jobs / distinct pairs | Distinct towns | Stations                | Wall time |  Observed rate |
| ------------ | --------------------: | -------------: | ----------------------- | --------: | -------------: |
| 30 Oct 10:16 |               26 / 26 |             26 | Kent Ridge              |  17.595 s |  88.7 jobs/min |
| 1 Nov 12:06  |               26 / 26 |             26 | Kent Ridge              |  15.873 s |  98.3 jobs/min |
| 1 Nov 12:19  |               78 / 78 |             26 | Bedok, Expo, Telok Ayer |  37.003 s | 126.5 jobs/min |

These are natural shared-dev bursts, not an admission-controlled capacity test. Each observed station run covers the 26 routable HDB towns, but the repeated Kent Ridge run means the window contains four distinct stations rather than five. The queue's maximum oldest-message age was 72,382 seconds because the observation window includes historical queued work before a later worker run; it is not the drain time of any of the three sessions above.

## Measured AWS usage

| Driver                 |           Observed in 124 hours | Existing E9 assumption | Evidence-led note                                                                                                                                                       |
| ---------------------- | ------------------------------: | ---------------------: | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Worker duration        |           990.307 ms/invocation |                 900 ms | An observed shared-dev mean; not a controlled replacement for the scenario input.                                                                                       |
| DynamoDB reads         |                     4,071.5 RCU |     2 RRU/read request | The window lacks a matching count of logical read requests, so it cannot produce RRU/request.                                                                           |
| DynamoDB writes        |                       2,680 WCU |          1.5 WRU/write | The window lacks a matching count of logical writes, so it cannot produce WRU/write.                                                                                    |
| DynamoDB table size    |     292,216 bytes (0.000292 GB) |                 0.5 GB | Direct deployed measurement; approximate item count 668.                                                                                                                |
| Lambda logs            | 581,461 bytes / 977 invocations | 2,048 bytes/invocation | 595 bytes/invocation across the four measured functions.                                                                                                                |
| Empty SQS receives     |                          48,443 |          650,000/month | Straight-line projection: about 285,189/month if this polling pattern persists.                                                                                         |
| All inferred SQS calls |                          48,833 |                      — | Sends + received messages + deletes + empty receives; projected about 287,485/month. A received-message metric is not an API-request meter when batch size exceeds one. |
| Custom metrics         |       1 distinct emitted metric |                     12 | `OneMapTokenWarning` was discoverable in the namespace; a metric with no datapoint in the window may not appear.                                                        |
| CloudWatch alarms      |                      4 deployed |                      6 | Stack inventory, before #28 is merged and deployed.                                                                                                                     |

Missing DynamoDB throttle/error datapoints are retained as `null` in the raw receipt. They are not rewritten as measured zeroes.

## Shared-dev observation cost estimate

Using the repository's [1 October 2026 Singapore list-price snapshot](model/prices_ap_southeast_1.json), the measured variable units above cost approximately **US$0.0338 at gross list price** for this 124-hour window:

| Variable line                            | Estimated list cost (US$) |
| ---------------------------------------- | ------------------------: |
| Lambda requests and compute              |                   0.01039 |
| HTTP API requests                        |                   0.00095 |
| DynamoDB reads, writes, storage and PITR |                   0.00251 |
| SQS requests (inferred as above)         |                   0.01953 |
| CloudWatch log ingestion                 |                   0.00038 |
| **Total**                                |               **0.03377** |

The calculation uses US$0.0000002 per Lambda request, US$0.0000133334 per Arm GB-second, US$0.00000125 per HTTP API request, US$0.0000001425 per DynamoDB read unit, US$0.00000071 per write unit, US$0.0000004 per SQS request, US$0.70 per GiB of logs, US$0.285 per DynamoDB GB-month and US$0.228 per PITR GB-month. It applies the deployed memory sizes (HTTP and worker 256 MiB, rent ingestion 1,024 MiB, token refresh 128 MiB), observed invocation counts and mean durations, decimal GB for DynamoDB billing, and 730 hours per month. It excludes fixed or unmeasured lines such as Secrets Manager, S3, dashboard charges, data transfer and AWS tax. Free-tier discounts are not applied because the account type remains unconfirmed.

This is a usage-based estimate, not the actual bill and not a controlled representative-run cost. It covers only the measured variable units in this 124-hour shared-dev window. It must not be compared directly with E9's complete monthly scenarios, which also include fixed services and assumed demand.

A read-only Cost Explorer check returned no usable value for the `project` tag, so FlatSplit spend cannot currently be separated from other workloads in account `553455762180`. A billing-authorised management/payer operator must activate `project` as a cost-allocation tag (and assess backfill eligibility) before #45 can validate the estimate against actual spend.

## Remaining limitations for #34 and the final report

- No controlled representative journey was run. The window measures genuine shared-dev usage, while monthly demand and the cost of one isolated journey remain modelled.
- The deployed Git revision is not recorded by the stack. A dated operator deployment receipt is required to attribute these measurements to a commit.
- DynamoDB consumed capacity is measured in aggregate, but the window has no matching logical read/write operation count, so RCU per read and WCU per write remain open.
- The `project` cost-allocation tag is not available in Cost Explorer and the account's applicable credit/free-tier terms are unconfirmed. No actual FlatSplit bill is claimed.
- CloudWatch returned no DynamoDB throttle/error datapoints. The raw receipt preserves those as `null`, not measured zeroes.
- `ListMetrics` found one recently emitted custom metric. This is a lower bound because configured metrics without recent datapoints may not be returned.
- Commute accuracy and route-coverage conclusions must come from E8/#19, not from the queue completion counts in this receipt.

## Reproduce

After authenticating the `flatsplit` AWS CLI profile, run:

```bash
uv run python tools/evaluation/issue34_usage_capture.py \
  --profile flatsplit \
  --region ap-southeast-1 \
  --stack FlatSplit-dev \
  --start 2026-10-29T00:00:00Z \
  --end 2026-11-03T04:00:00Z \
  --output docs/evaluation/e9/evidence/deployed-usage-20261103.json
```

The command reads CloudFormation, CloudWatch, Logs, DynamoDB and STS. It does not invoke a function, enqueue work, write data or change infrastructure. CloudWatch aggregates can settle after the window closes, and DynamoDB `TableSizeBytes` / `ItemCount` are approximate snapshots maintained by AWS.
