# Data refresh and failure recovery runbook (#33)

Who to call, what a failure looks like from outside, and the exact commands to
inspect and recover one. Written for a teammate who did not build the pipeline.

**Scope and honesty.** Every record shape, threshold and key below is read from
the reviewed integration source, including #74/#75/#82, rather than an assumed
live inventory. Merged code and deployed resources are separate: discover the
actual stack outputs and record its deployed revision before using a procedure. Nothing here is a deployment receipt: running these commands is
how you find out what the deployed stack is actually doing.

Shared deployment, from `docs/aws-dev-handoff.md`: account `553455762180`,
region `ap-southeast-1`, stack `FlatSplit-dev`. Confirm the account before
every command in this file.

```bash
aws sts get-caller-identity --query Account --output text   # expect 553455762180
```

Resolve names from the stack rather than pasting them, because they change on
redeploy:

```bash
aws cloudformation describe-stacks --stack-name FlatSplit-dev \
  --query 'Stacks[0].Outputs[].{K:OutputKey,V:OutputValue}' --output table
```

| Output                      | What it is                                           |
| --------------------------- | ---------------------------------------------------- |
| `TableName`                 | the single DynamoDB table holding every record below |
| `RentRawBucketName`         | raw HDB rental snapshots and the current pointer     |
| `RentIngestionFunctionName` | the monthly ingestion Lambda                         |
| `CommuteQueueUrl`           | the commute jobs queue                               |
| `OneMapTokenSecret`         | the Secrets Manager secret holding the OneMap token  |
| `ApiUrl`, `SiteUrl`         | API and front end                                    |

Shorthand used below:

```bash
TABLE=$(aws cloudformation describe-stacks --stack-name FlatSplit-dev \
  --query "Stacks[0].Outputs[?OutputKey=='TableName'].OutputValue" --output text)
QUEUE=$(aws cloudformation describe-stacks --stack-name FlatSplit-dev \
  --query "Stacks[0].Outputs[?OutputKey=='CommuteQueueUrl'].OutputValue" --output text)
BUCKET=$(aws cloudformation describe-stacks --stack-name FlatSplit-dev \
  --query "Stacks[0].Outputs[?OutputKey=='RentRawBucketName'].OutputValue" --output text)
SINCE=$(python3 -c 'from datetime import datetime,timedelta,timezone; print((datetime.now(timezone.utc)-timedelta(hours=1)).isoformat())')
UNTIL=$(python3 -c 'from datetime import datetime,timezone; print(datetime.now(timezone.utc).isoformat())')
```

---

## 1. The two data sources, and what each one can go wrong at

|                        | OneMap                                                                   | HDB rental dataset                                          |
| ---------------------- | ------------------------------------------------------------------------ | ----------------------------------------------------------- |
| Used for               | destination search, nearest-station snapping, station-to-station routing | town rent medians shown in results                          |
| Owner                  | project OneMap account, registered by Shyam on 28 October (#72)          | data.gov.sg, public; no credential                          |
| Refresh trigger        | on demand, per request, through the caches in section 3                  | the monthly EventBridge rule on `RentIngestionFunctionName` |
| Credential             | three-day JWT in `OneMapTokenSecret`                                     | none                                                        |
| Typical failure        | expired token, 429, a route that does not exist                          | the publisher changed its columns, or a month arrives short |
| **What the user sees** | nothing obvious — see the warning below                                  | rent fields withheld, towns explained rather than ranked    |

**The failure mode worth knowing before anything else:** OneMap answers an
expired, invalid or missing token with **HTTP 200 and full results**, setting
only an `error` field in the body (`services/api/src/flatsplit_api/onemap.py`).
A healthy-looking response is therefore not evidence of a healthy token. The
previous token expired on 14 October and nothing broke visibly for six days.
The only signal is the log line the client emits on that field:

```python
logger.warning("OneMap token warning", extra={"onemapTokenWarning": True})
```

So **never conclude the token is fine because `/api/places` returned 200.**
Check the warning (section 2).

---

## 2. The OneMap token

A three-day JWT. The reviewed #82 implementation refreshes it every 12 hours
using an EventBridge-triggered Lambda; confirm that function and credentials
setup are actually deployed. Resolution order, from
`onemap.py::resolve_token`:

1. `ONEMAP_TOKEN` in the environment — local development only.
2. otherwise `ONEMAP_SECRET_NAME` → Secrets Manager, **cached for 900 seconds**
   (`max_age=900`). After installing a new token, allow 15 minutes before
   concluding it did not work.

Every credential failure — missing SDK, access denied, empty secret — surfaces
as the same public `OneMapUnavailable` message, deliberately, so nothing leaks.
That means an access-denied secret and an expired token look identical from the
outside; the log tells them apart.

### Is the token healthy?

```bash
# Traffic-driven warning metric. Missing data is not proof of token health.
aws cloudwatch get-metric-statistics \
  --namespace FlatSplit/dev --metric-name OneMapTokenWarning \
  --start-time "$SINCE" \
  --end-time "$UNTIL" \
  --period 300 --statistics Sum
```

API and worker log-group filters match `$.onemapTokenWarning = true` and
publish `FlatSplit/dev` / `OneMapTokenWarning`. They require log traffic: no
datapoint during an idle period is not evidence of a valid credential. The
scheduled refresh and its `OneMapTokenRefreshFailing` alarm cover refresh
failures during idle periods. Confirm both filters exist in the deployed stack.

The alarm (construct `OneMapTokenExpiring`) sums that metric over 5 minutes
and fires at 1, on one evaluation period, with missing data not breaching.

```bash
aws cloudwatch describe-alarms --alarm-name-prefix FlatSplit \
  --query 'MetricAlarms[].{Name:AlarmName,State:StateValue,Reason:StateReason}' \
  --output table
```

### Installing a new token

Only someone holding the OneMap account can mint one; that is Shyam as of
28 October. **Never paste a token into an issue, a PR or this file.**

```bash
SECRET=$(aws cloudformation describe-stacks --stack-name FlatSplit-dev \
  --query "Stacks[0].Outputs[?OutputKey=='OneMapTokenSecret'].OutputValue" --output text)
aws secretsmanager put-secret-value --secret-id "$SECRET" \
  --secret-string "file://$HOME/onemap-token.txt"   # do not expand the token into argv
```

Then wait out the 900-second cache and verify with a real lookup — not
`/api/health`, which never touches OneMap:

```bash
API=$(aws cloudformation describe-stacks --stack-name FlatSplit-dev \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)
set -o pipefail
curl --fail-with-body --silent --show-error "$API/places?q=kent%20ridge" \
  | python3 -c 'import json,sys; body=json.load(sys.stdin); assert isinstance(body, dict) and "error" not in body and isinstance(body.get("places"), list), "Lookup error or malformed response"; print("Selectable candidates:", len(body["places"]))'
```

Record only status, counts and observation time. Neither health nor public
lookup HTTP 200 proves credential health: the public API can omit OneMap's
original `error` field while the backend logs `onemapTokenWarning`. Inspect
warning events/metrics covering the lookup. Use the [first-refresh receipt
procedure](aws-dev-handoff.md#onemap-token-refresh-runbook-72), which rejects
Lambda `FunctionError` and requires a checked future expiry before claiming
refresh success. Never record the token or credentials.

#82's reviewed scheduled refresh replaces Secrets Manager rotation; it avoids
the old deployment-time `testSecret` and AWSPENDING problems. Verify deployment,
credential setup and a first success receipt. If those resources are absent,
manual replacement remains the operator's stopgap, not automatic renewal.

---

## 3. Cache state and expiry

One table, these records. The lifetimes differ and the differences matter.

| Record                                         | Lifetime                    | Written by                           |
| ---------------------------------------------- | --------------------------- | ------------------------------------ |
| `PLACE#<placeId>` / `META`                     | 24 h (`PLACE_TTL_SECONDS`)  | `/places` lookup                     |
| `PLACELOOKUP#<query>` / `META`                 | 24 h (`LOOKUP_TTL_SECONDS`) | `/places` lookup                     |
| `STATION#<stationKey>` / `META`                | **no ttl, ever**            | first `/places` lookup to snap there |
| `COMMUTE#<stationKey>` / `TOWN#<town>`         | **no ttl**                  | search claim, then the worker        |
| `GROUP#<groupId>` / `META`, `MEMBER#…`         | 30 days (`GROUP_LIFETIME`)  | groups API                           |
| `RENT#<snapshotId>` / `TOWN#<town>#<flatType>` | **no ttl**                  | rent publication                     |

`docs/api-contract.md` states it plainly: _"Commute and rent items carry no
TTL. Commutes are refreshed by profile-aware claims; monthly batch refresh
remains external work."_ An earlier planning note on #33 said commute records
expire after 30 days — **that was wrong**, and anything repeating it should be
corrected. Commute freshness comes from `routingProfileVersion`
(`pt-v1:YYYY-MM`, a Singapore calendar month), not from expiry: a claim for a
newer profile supersedes an older record, and an older request can never
reclaim a newer profile's lease.

### The one record a refresh must not silently rewrite

`STATION#<stationKey>/META` holds the **pinned routing coordinate**. It is
created conditionally, the first writer wins, and every later lookup that snaps
to that station reuses the winning coordinate. #3 measured why:
`getNearestMrtStops` returns one entry per line code for an interchange, in a
varying order, with coordinates up to ~100 m apart — Dhoby Ghaut returns CC1,
NS24 and NE6. If a lookup could overwrite the coordinate, one member would get
different commute minutes on different days, and minutes computed from
different origins would silently accumulate under a single
`COMMUTE#<stationKey>` key, which is E4's primary metric.

**Aliases may be merged into an existing station record. The coordinate may not
change without an explicit cache refresh.** Re-pinning is a deliberate
migration: change the coordinate _and_ delete every `COMMUTE#<stationKey>`
record under that key in the same operation, or the cache now holds minutes
measured from a place the pin no longer names. Do not treat re-pinning as a
cache-warming step.

### Inspecting a cache record

```bash
aws dynamodb get-item --table-name "$TABLE" \
  --key '{"pk":{"S":"STATION#KENT_RIDGE"},"sk":{"S":"META"}}'

aws dynamodb query --table-name "$TABLE" \
  --key-condition-expression 'pk = :p AND begins_with(sk, :s)' \
  --expression-attribute-values '{":p":{"S":"COMMUTE#KENT_RIDGE"},":s":{"S":"TOWN#"}}' \
  --query 'Items[].{town:sk.S,status:status.S,minutes:minutes.N,profile:routingProfileVersion.S}' \
  --output table
```

---

## 4. DLQ replay

The queue is `CommuteJobs`: SQS-managed encryption, TLS only, **180-second
visibility timeout**, **four-day retention**, and **three receives** before a
message is dead-lettered to `CommuteDlq`, which retains for **14 days**
(`infra/aws/src/api.ts`).

> **Deployment gate:** #74 defines the consumer. Confirm its deployed revision
> and event-source mapping before expecting the queue to drain. If it is absent,
> messages accumulate without receives; an empty DLQ then does not prove success.

Two alarms, both from #79, both treating missing data as not breaching so an
idle stage is quiet, and both notifying the `Alerts` SNS topic — which has an
email subscriber only if the stack was deployed with `budgetEmail` set, so
check that a human actually receives them:

| Construct            | Metric                                                     | Fires when                                                      |
| -------------------- | ---------------------------------------------------------- | --------------------------------------------------------------- |
| `CommuteDlqNotEmpty` | DLQ `ApproximateNumberOfMessagesVisible`, 5-minute Maximum | the maximum reaches 1 in any one 5-minute window                |
| `CommuteJobsStalled` | queue `ApproximateAgeOfOldestMessage`, 5-minute Maximum    | the oldest message exceeds 540 s in **two consecutive** windows |

Nine minutes is deliberate: 180-second visibility across three receives is the
longest a healthy pair can legitimately take.

Those are CDK construct ids, not alarm names: `alarmName` is not set, so the
deployed names are stack-prefixed and generated. Discover them with
`--alarm-name-prefix FlatSplit` rather than guessing a full name.

### Look before you re-drive

```bash
DLQ=$(aws sqs get-queue-attributes --queue-url "$QUEUE" \
  --attribute-names RedrivePolicy \
  --query 'Attributes.RedrivePolicy' --output text \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["deadLetterTargetArn"])')
DLQ_NAME=${DLQ##*:}
DLQ_ACCOUNT=$(python3 -c 'import sys; print(sys.argv[1].split(":")[4])' "$DLQ")
DLQ_URL=$(aws sqs get-queue-url --queue-name "$DLQ_NAME" \
  --queue-owner-aws-account-id "$DLQ_ACCOUNT" --query QueueUrl --output text)

aws sqs get-queue-attributes --queue-url "$DLQ_URL" \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible

# Age is a CloudWatch metric, not an SQS GetQueueAttributes attribute.
aws cloudwatch get-metric-statistics --namespace AWS/SQS \
  --metric-name ApproximateAgeOfOldestMessage \
  --dimensions Name=QueueName,Value="$DLQ_NAME" \
  --start-time "$SINCE" --end-time "$UNTIL" --period 300 --statistics Maximum
```

Read one message **without consuming it permanently** — receive it, read it,
and let a 60-second inspection lease return it. This increments its receive
count; do not run a competing consumer/redrive during inspection. Do not delete
it, and wait for visibility to return before a redrive:

```bash
aws sqs receive-message --queue-url "$DLQ_URL" --max-number-of-messages 1 \
  --visibility-timeout 60 --query 'Messages[0].Body' --output text | python3 -m json.tool
```

A job message looks like this (`commute_jobs.py`):

```json
{
  "schemaVersion": 1,
  "jobId": "f1f0c4e2-…",
  "stationKey": "KENT_RIDGE",
  "town": "BEDOK",
  "origin": { "lat": 1.3236, "lng": 103.9273 },
  "destination": { "lat": 1.2935, "lng": 103.7846 },
  "routingProfileVersion": "pt-v1:2026-10",
  "routingDate": "2026-10-30",
  "routingTime": "08:30:00",
  "leaseExpiresAt": 1761800000
}
```

**Check this before re-driving.** Completion is conditioned on a matching
`jobId` _and_ `status = pending`, so a stale attempt cannot overwrite a newer
claim — but a re-drive that can never win is just quota spent for nothing.
Compare the message against the record:

```bash
aws dynamodb get-item --table-name "$TABLE" --consistent-read \
  --key '{"pk":{"S":"COMMUTE#KENT_RIDGE"},"sk":{"S":"TOWN#BEDOK"}}' \
  --query 'Item.{status:status.S,jobId:jobId.S,profile:routingProfileVersion.S,lease:leaseExpiresAt.N,attempts:attempts.N,error:error.S}'
```

| What you find                                       | Do this                                                                                                                                          |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `jobId` differs from the message                    | **do not re-drive** — another claim owns this pair                                                                                               |
| `routingProfileVersion` is newer than the message   | **do not re-drive** — superseded by a newer profile                                                                                              |
| `status = ok`                                       | **do not re-drive** — already answered                                                                                                           |
| `status = unavailable`, `error = NON_ROUTABLE_TOWN` | **never re-drive** — `retryAfter` is 253402300799, the town's reference point is permanently non-routable and was resolved locally, never queued |
| `status = pending`, `jobId` matches, lease expired  | re-drive, or let a reader reclaim it                                                                                                             |

Re-drive only after that check:

```bash
aws sqs start-message-move-task --source-arn "$DLQ"
aws sqs list-message-move-tasks --source-arn "$DLQ"   # watch it
```

If the cause is upstream and not transient, **leaving the pair `unavailable` is
the correct outcome.** A town with no route must be explained, not given an
invented number — an unavailable route is never a zero-minute result.

---

## 5. Worked example: inspecting one failed sample job

The acceptance criterion for #33. A member is waiting on a pair that never
completes.

**1. Which pair.** Get the search's status and find the pending or unavailable
town.

```bash
curl -s "$API/groups/<groupId>/searches/<searchId>" \
  -H "Authorization: Bearer <memberToken>" | python3 -m json.tool
```

Pending pairs are `total - resolved`. A town that is ranked needs no
investigation; a town carrying a reason code does.

**2. Which record.** Map the member's station and that town to the key:

```bash
aws dynamodb get-item --table-name "$TABLE" --consistent-read \
  --key '{"pk":{"S":"COMMUTE#<stationKey>"},"sk":{"S":"TOWN#<TOWN>"}}'
```

Read `status`, `jobId`, `attempts`, `routingProfileVersion`, and
`leaseExpiresAt` or `error`/`retryAfter`.

**3. Which log line.** The worker's log group is `CommuteWorkerLogs`, retained
one week. Discover its exact physical name from this stack:

```bash
LOGS=$(aws cloudformation describe-stack-resources --stack-name FlatSplit-dev \
  --query "StackResources[?ResourceType=='AWS::Logs::LogGroup' && contains(LogicalResourceId, 'CommuteWorkerLogs')].PhysicalResourceId | [0]" --output text)
aws logs filter-log-events --log-group-name "$LOGS" \
  --start-time "$(( ($(date +%s) - 3600) * 1000 ))" \
  --filter-pattern '{ $.jobId = "<jobId>" }'
```

One week of retention is the real constraint here: a job that failed eight days
ago cannot be diagnosed from logs, only from the record.

**4. Which DLQ message, if any.** Section 4, then the decision table there.

**5. Decide, and say which.** Either re-drive, or leave the pair `unavailable`
and let the search explain it. Both are legitimate. Writing a number you did
not measure is not.

> If the deployed revision lacks #74, an empty DLQ with expiring pending
> leases reflects the missing consumer. Check deployment before treating this
> as a worker-runtime failure.

---

## 6. Last-good fallback

For losing upstream access near the deadline.

`docs/evaluation/feasibility/scripts/seed_commute_cache.py` pre-computes a
`(town × destination station)` commute matrix in the contract's Commute item
shape — `pk = COMMUTE#<stationKey>`, `sk = TOWN#<town>`, with `status`,
`minutes`, `transfers`, `walkMinutes`, `attempts`, `computedAt`, `error`.

```bash
python3 docs/evaluation/feasibility/scripts/seed_commute_cache.py --dests "NUS" --dry-run
python3 docs/evaluation/feasibility/scripts/seed_commute_cache.py \
  --dests-file dests.txt --full --out evidence
```

An existing matrix from 11 October is committed at
`docs/evaluation/feasibility/evidence/commute_seed_20261011T093301Z.json`.

**Two honest limits, and they are not optional.**

1. **The script emits JSON only.** It contains no DynamoDB client and writes
   nothing to any table — loading the matrix is a manual `batch-write-item`
   step that nobody has scripted or rehearsed. Do not plan on this as a
   one-command recovery; if we want it to be one, it needs writing before we
   need it.
2. **If the matrix is loaded, the report must say so.** `/searches` keeps its
   shape, which is exactly why this is dangerous: results look computed. Any
   figure derived from a loaded matrix is a static lookup from a dated
   measurement, not a live routing result, and the limitations section has to
   state the matrix's date. Loading it without recording that is passing off
   old data as current.

---

## 7. Rent refresh and the last valid snapshot

The monthly ingestion Lambda (`RentIngestionFunctionName`) downloads the HDB
export, validates it, and writes to the raw bucket. Invoke it by hand:

```bash
FN=$(aws cloudformation describe-stacks --stack-name FlatSplit-dev \
  --query "Stacks[0].Outputs[?OutputKey=='RentIngestionFunctionName'].OutputValue" --output text)
aws lambda invoke --function-name "$FN" --payload '{}' /dev/stdout
```

It requires `RENT_RAW_BUCKET` and `RENT_TABLE_NAME`, and raises rather than
returning quietly, so a failed invocation is a failed invocation.

Object layout:

| Path                                                                      | What                                                                     |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `raw/source_month=<YYYY-MM>/retrieved_at=<YYYYMMDDTHHMMSSZ>/<sha256>.csv` | the immutable snapshot                                                   |
| …`.manifest.json`                                                         | `status: VALIDATED`, row/town/flat-type counts, `sha256`, source headers |
| `raw/current.json`                                                        | the pointer naming the current snapshot                                  |
| `rejected/retrieved_at=<…>/<sha256>.csv` + manifest                       | `status: REJECTED` with a `reason`                                       |

```bash
aws s3 cp "s3://$BUCKET/raw/current.json" - | python3 -m json.tool
aws s3 ls "s3://$BUCKET/rejected/" --recursive | tail
```

**A rejected download does not disturb the current pointer.** That is the
last-good guarantee: validation failures are written under `rejected/` with
their reason, and `raw/current.json` keeps naming the last snapshot that
passed. If results still show rent, that is the previous month's validated
snapshot doing its job, not a silent failure.

Two protections worth knowing when a refresh behaves oddly:

- The pointer is replaced with a conditional `IfMatch` on its ETag. A
  concurrent ingestion loses with _"The current rent pointer changed during
  ingestion; retry."_ Retry it; do not force the write.
- A candidate older than the current one is refused outright: _"The candidate
  rent snapshot is older than the current snapshot."_ Ordering compares the
  month first, then parses `retrievedAt` into datetimes — not string
  comparison, so variable-precision timestamps order correctly here.

**#75 is merged.** The ingestion pipeline publishes validated, versioned
`RENT#<snapshotId>` town summaries before advancing `RENT/CURRENT`. Its monthly
rule is 19:00 UTC on day 2, which is 03:00 SGT on day 3. Publication is fenced
by source month and fixed-width UTC retrieval time; failed/rejected or older
publications do not replace the last valid rent pointer. Historical snapshot
records remain readable by searches that pinned them.

Confirm the deployed code and actual producer records; a merge or another
reviewer's deployment statement does not establish the inventory inspected here:

```bash
aws dynamodb get-item --table-name "$TABLE" --consistent-read \
  --key '{"pk":{"S":"RENT"},"sk":{"S":"CURRENT"}}' \
  --query 'Item.{snapshot:snapshotId.S,period:period.S,validatedAt:validatedAt.S,rawRetrievedAt:rawRetrievedAt.S}'
```

Retain this pointer and representative summary/rejection receipts for #10/#28
acceptance. Missing or low-confidence summaries stay excluded from rankings;
they are not a reason to invent a rent value.

---

## 8. When something is wrong, in order

1. `aws sts get-caller-identity` — right account?
2. `aws cloudwatch describe-alarms --alarm-name-prefix FlatSplit` — what is
   already telling you?
3. `OneMapTokenWarning` over the last hour — is the token healthy? Remember a
   200 proves nothing.
4. DLQ depth and oldest-message age (section 4).
5. `raw/current.json` and `rejected/` (section 7).
6. The one record for the pair the user is actually waiting on (section 5).

Escalation: OneMap account and rotation → Shyam (#72, #82). Rent ingestion and
publication → Mani (#10, #28, #75). Commute worker, queue and alarms → Ming
(#15, #27, #74, #79). Deployed verification → WK (#29, #30, #35).
