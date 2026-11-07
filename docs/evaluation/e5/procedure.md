# E5 failure, alarm and dead-letter drill procedure

**Experiment:** E5

**Status:** Procedure only; not yet run. Blocked on working `eval` access (#27).

**Environment:** Dedicated `eval` stage only. @wkkuu established on [#72](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/72#issuecomment-6625779422) that dead-letter injection is outside shared `dev` scope, and that is accepted.

**Owner:** Ming (@lukerspace), #27 and #19. Checked by @wkkuu under #35. The #33 runbook walkthrough runs in the same session and is @saravanamani1999's, not the author's.

## Question

When a commute job cannot succeed, does it stop, become visible, and leave its pair honestly unresolved — rather than loop, silently vanish, or acquire an invented travel time?

## What this procedure can and cannot establish

Pre-registered deliberately, because E5's metric list in the [evaluation plan](../../evaluation-plan.md) is wider than a queue-only drill can reach. The plan's workload **W4** is "W3 with 30% injected transient routing failures, then 100% for 5 minutes, then restored", plus permanent 400/403/404, routing 401 and 429 handling. Injecting a _transient routing_ failure means making OneMap appear to fail to the deployed worker. Nothing in the deployed stack offers a fault switch, and the drill operator has queue access plus alarm and log reads — not the ability to intercept the worker's upstream calls. **W4 as specified cannot be run on `eval` by this route at all.**

| E5 metric                              | This drill                            | Where it actually comes from                                                                                                                                                                                                                                                                                            |
| -------------------------------------- | ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| DLQ and attempt bounds                 | **Yes** — Phase A                     | new `eval` evidence                                                                                                                                                                                                                                                                                                     |
| Alarm delay                            | **Yes** — Phase A, from alarm history | new `eval` evidence                                                                                                                                                                                                                                                                                                     |
| Retries on permanent errors (expect 0) | **Yes** — Phase B                     | new `eval` evidence                                                                                                                                                                                                                                                                                                     |
| Redrive recovery                       | **Mechanism only** — Phase C          | partial; see Phase C                                                                                                                                                                                                                                                                                                    |
| Jobs recovered by retry                | **No**                                | not measured anywhere. The 26 October Moto drain had 0 redeliveries, and its `retry_exhaustion` scenario exhausts rather than recovers. The 6 November W1/W2 run cannot supply it either: the warm-up cached all 729 catalog pairs, so no commute job is enqueued and the worker is never invoked. State as unmeasured. |
| Token-warning alarm                    | **No**                                | invalidating the token breaks the stage for everyone and `eval` shares the team OneMap account with `dev`. Cite #72's observed post-expiry gap instead; do not provoke it.                                                                                                                                              |
| Honest unavailable / retry UI          | **No**                                | #26's UI work, with Lucy and Hikaru. Phase B supplies the _record_ behind such a surface, not the surface.                                                                                                                                                                                                              |

So the drill supplies three of E5's seven metrics as deployed evidence, one as a mechanism, and leaves three explicitly unmeasured. **E5 must not be reported as complete after this session.** The report should say which parts rest on AWS, which on the Moto harness in [`../worker-queue/`](../worker-queue/README.md), and which on nothing.

## Preconditions

Do not start until all of the following hold:

1. **Working access.** Granted 6 November: role `FlatSplit-eval-Drill27` in `553455762180`, trusting only `arn:aws:iam::897729133025:user/ming`, sessions capped at one hour, assumed through the `flatsplit-drill` CLI profile. IAM's policy simulator confirms `SendMessage`, `DeleteMessage` and `FilterLogEvents` allowed and `PurgeQueue`, every dev queue, `dynamodb:PutItem` and `lambda:InvokeFunction` denied. A resource list alone did not give access on 5 November; this does.
2. The `eval` DLQ is **empty**, confirmed by a reading taken at the start of the session. An earlier reading is not a current check (@wkkuu, [#30](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/30#issuecomment-6661549506)). If it is not empty, stop: something else is in there and must not be purged.
3. All five `eval` alarms are `OK` at the start, recorded with their `StateUpdatedTimestamp`.
4. The stage's deployed revision is recorded as a full SHA. The stack publishes no source-revision output (#34), so this comes from the operator's deploy record, not from CloudFormation's update timestamp.
5. No overlapping provider-heavy run on `eval` or `dev`; both share the team OneMap account. Coordination with #30 is on #27 and #30.
6. The alarms publish to an SNS topic with no subscribers, so **each transition is read from alarm history**, not from a notification.
7. Clocks in UTC, with the SGT equivalent recorded alongside for the team's own timeline.

## Phase A — a permanently unkeyable job reaches the DLQ and raises the alarm

Covers #27's second acceptance criterion: a permanently failing job is visible and does not loop indefinitely.

Inject one message whose body is valid JSON with `schemaVersion: 0`, carrying a `drill-27-<timestamp>` marker, the issue number and a `Never re-drive` note. In `commute_worker.py`, `_parse()` raises `Unkeyable` and `_process()` returns `True` **before `_route()` is reached**, so:

- no OneMap call is made and **no provider quota is spent** — this matters because the 250/min budget is shared with #30's load work and with `/places`;
- no cache item is addressed, so no real pair can be overwritten;
- the message fails identically on every receive, which is what makes it a _permanent_ failure rather than a slow one.

Observe, with timestamps: the source queue depth, the three receives at the 180-second visibility timeout, the message's arrival in the DLQ, and the `CommuteDlqNotEmpty` transition in alarm history. Then read the DLQ message **under a 60-second inspection lease** — receive it, read it, do not delete it — and record its `ApproximateReceiveCount`, `SentTimestamp` and body, per §4 of the [runbook](../../data-refresh-runbook.md).

### Phase-A pass conditions

- The message is dead-lettered after exactly three deliveries **to the worker**, not sooner and
  not indefinitely redelivered. Count this from the three `Unusable commute job` log entries,
  **not** from the `ApproximateReceiveCount` read off the DLQ message: §4's inspection lease
  increments that count itself, and the rehearsal below read 4 for a message delivered three
  times. A pass condition read off the inspection would fail on its own artifact.
- `CommuteDlqNotEmpty` moves `OK → ALARM`, and the delay between the DLQ arrival and the
  transition is recorded as the **measured alarm delay**. An earlier version of this line called
  the alarm's 300-second `Maximum` period a **floor** on that delay. It is not, and the
  7 November run measured 99–110 seconds, which refutes it. Do not replace it with a different
  rule: that run's two transitions do not follow the same one — the raise came 92 seconds after
  its evaluation window closed, while the clear came **before** its window closed. Record the
  measured delay, the alarm's period and statistic, and where in the window the arrival fell,
  and state plainly that one drill does not establish how the alarm evaluates. The alarm's
  windows are anchored on its own schedule, not clock-aligned; read the breaching datapoint's
  timestamp out of `StateReason` rather than assuming.
- The worker log group carries one `Unusable commute job` entry per receive, matching the marker.
- No pair record is created or changed by this phase. Nothing in the payload addresses one.
- No OneMap call is attributable to the drill in the same window.

## Phase B — a permanently rejected job stops without retrying, and writes nothing

Covers E5's "retries on permanent errors (expect 0)", which Phase A cannot: an unkeyable message has no pair to close.

Inject one message that **is** keyable — valid `schemaVersion: 1`, `jobId`, `stationKey` and `town` — but whose coordinates are unusable. `route()` raises `RoutingRejected`, a subclass of `RoutingUnroutable`, from `_point()` **before any HTTP call**, so this also spends no quota. `_process()` then takes the `RoutingUnroutable` branch and returns `False`, so the message is deleted rather than redelivered.

**The terminal write is refused, and that is the correct behaviour rather than a flaw in the drill.** @shyamgj1900 established this while building the role, and the implementation confirms it: `CommuteResults._write` guards every completion with `ConditionExpression="#jobId = :jobId AND #status = :pending"`, and its own docstring says why — "`update_item` creates a missing item, so the condition also stops a claim that was rolled back after a failed send from being resurrected by its own in-flight message." Only the API's enqueue creates that pending claim. A message sent straight to the queue for `COMMUTE#DRILL27` / `TOWN#DRILL` therefore fails the condition, `store_unavailable()` returns `False`, and `_terminal()` logs **`A newer claim or result owns this pair; terminal write skipped`** with `attempts: 1` and `routingError` set.

So the zero-retry evidence is **that log line plus the queue state**, not a table record. Two consequences, both improvements:

- **Nothing is written to the eval table at all**, so there is nothing to clean up and no table-write authorisation is needed. The earlier version of this procedure claimed a `status: unavailable` record with `retryAfter`; that was wrong.
- The drill demonstrates the fence as well as the retry policy: a job with no claim cannot manufacture a result for a pair nobody asked about.

The synthetic `stationKey: DRILL27` / `town: DRILL` is kept anyway, so that nothing in the log or the payload can be mistaken for a real pair.

### Phase-B pass conditions

- Exactly **one** delivery to the worker: one invocation and `attempts: 1` in the log entry. A permanent error consumed no retries.
- The worker logs `A newer claim or result owns this pair; terminal write skipped`, carrying `attempts: 1`, the `routingError` code from `RoutingRejected`, and the drill marker.
- The message is **deleted, not redelivered**: the source queue does not return it after the visibility timeout.
- The DLQ depth is unchanged by this phase. A message the worker could account for does not reach the DLQ.
- **No item exists** at `COMMUTE#DRILL27` / `TOWN#DRILL` afterwards. The drill operator cannot check this — the role denies `dynamodb` entirely — so it is either confirmed by whoever holds table read access or recorded as unchecked.
- The **source** queue returns to zero only once the worker has consumed the Phase-B message. If the cleanup step reports a source depth of 1, check whether Phase B is still in flight before treating it as a leftover.

## Phase C — redrive moves a dead-lettered message, and why that is not recovery

E5 asks for "redrive recovery". Phase A's message can be redriven, and `start-message-move-task` can be shown to move it back to the source queue — but it will fail there again, because nothing about it was transient. **That demonstrates the redrive mechanism, not recovery.**

Record it as such, and state the limit plainly: recovery by redrive needs a job whose underlying cause has been fixed between the failure and the redrive. The 26 October Moto harness exercised the mechanism (`unaccountable_payload`: three receives, then redrive, source queue empty, DLQ depth 1). Neither run shows a pair that failed, was redriven, and then succeeded. That remains unmeasured, and §4 of the runbook already says the decision table exists precisely so that a re-drive which cannot win is not spent.

Phase C is **optional** and runs only if the session has time after A and B. It must not be the last action: the cleanup below has to follow it.

## Evidence to retain

Under `docs/evaluation/e5/raw/<YYYY-MM-DD>/`, per convention D-E5 (lowercase experiment directory, raw data, script version, date and source mapping):

1. The injected bodies, verbatim, with their markers.
2. Both queue depths sampled over the whole session, with timestamps.
3. `describe-alarms` before and after, and `describe-alarm-history` covering the window, for all five alarms.
4. The DLQ message as read under the inspection lease, with its receive count.
5. The worker log events matching each marker.
6. The Phase-B terminal log line — `A newer claim or result owns this pair; terminal write skipped`, with `attempts: 1`, the `routingError` code and the pair keys — together with the source-queue depth showing no redelivery. **There is no record to read back**: the fenced write is refused, and the drill role denies `dynamodb` entirely. If someone with table read access confirms that nothing exists at `COMMUTE#DRILL27` / `TOWN#DRILL`, retain that confirmation; otherwise retain the note that it is unchecked.
7. The post-cleanup depths and **the time they were checked**, which is what #30 needs.
8. The recorded stage revision, the operator, and the session's start and end.

Screenshots are listed in the plan's evidence column. CLI output with timestamps is preferred over screenshots wherever both are possible: it can be re-read and diffed. Where the plan asks for an alarm screenshot, attach the alarm-history records instead and say so.

## Cleanup, and who does it

1. The operator deletes **their own drill messages by receipt handle**, never with `purge-queue`. A purge would also destroy anything a teammate has in that queue. The grant requested for this drill deliberately omits `sqs:PurgeQueue`.
2. The DLQ is confirmed empty afterwards, and that confirmation is posted on #30 **with the time it was checked**, because #30's load run shares the stage.
3. **Nothing to delete from the table.** Phase B's fenced write is refused, so no item is created — see Phase B. If someone with table read access confirms the absence of `COMMUTE#DRILL27` / `TOWN#DRILL`, record that; otherwise record it as unchecked.
4. All five alarms are confirmed back to `OK`, or the reason one is not is recorded.

## Post-run observation — recovery by retry, which the 6 November run cannot supply

Not a phase of the drill, and nothing here is injected.

**Closed for the 6 November W1/W2 run, by construction.** The 19:47–19:53 SGT warm-up resolved all
**729** pairs of the pinned catalog — 27 stations x 27 towns — leaving 702 `ok` and 27 `unavailable`
(`TOWN#TENGAH`, `NON_ROUTABLE_TOWN`, `attempts: 0`). `CommuteJobs.ensure` returns a cached `ok` without
enqueueing; a `NON_ROUTABLE_TOWN` record is returned untouched by a read, and even by
`SearchService.repeat`, which is the only caller passing `retry_unavailable=True`, because the enqueue
also requires `point.routable is not False` and `retryAfter <= now` and that record has `routable`
`False` with `retryAfter` `253402300799`. The monthly profile `pt-v1:2026-11` does not roll over until
1 December. So W1/W2 enqueues **zero** commute jobs, the worker is **never invoked**,
`call_budget.reserve` is **never called**, and leg 1 below cannot exist. The observation to record for
that run is the **absence**: zero worker invocations in the window. The metric is reported as
unmeasured, and this is known before the run rather than concluded from an empty log.

The method below is retained because it is tested and because any later run with cache misses could
reach it. For the 6 November run it is not expected to yield anything.

**What the warm-up did establish, kept separate from recovery.** 702 routing calls over 19:47:39–19:53:16
is about **125 calls/min sustained** against a `WORKER_CALLS` ceiling of 200 per 60-second window, with
702 `Routing call succeeded`, all `attempts: 1`, and no budget refusals. The guard was therefore **not
reached** at that rate — a measurement of headroom, not of recovery. Separately, the 27 `unavailable`
records are deployed evidence that a permanently non-routable destination yields an honest record with a
reason code and no travel time at **zero OneMap calls and zero queue traffic**; their `attempts: 0` means
the worker never saw them, so they are **not** evidence about the worker's handling of a permanent error,
which rests on Phase B alone. E5's "jobs recovered by retry" is unmeasured
everywhere, and the worker has a transient failure path that is not OneMap: `call_budget.py` counts
worker routing calls in a 60-second window at `pk: RATE#ONEMAP`, `sk: WINDOW#<floor(epoch/60)>`, under
`attribute_not_exists(#calls) OR #calls < :ceiling`, with `WORKER_CALLS` of 200. A full window logs
`OneMap call budget reached for this window` and raises `BudgetExhausted`, which `routing.py` turns into
`RoutingRetryable`, and `_process()` returns the message to the queue.

**Whether it fires at all depends on upstream latency and on saturation.** An earlier draft of this
paragraph claimed that three concurrent workers "cannot exhaust their own 200 share". **That claim is
withdrawn; the 6 November warm-up measures it false.** Read from
`FlatSplit-eval-ApiCommuteWorkerLogsA37837F9-YOtZw0L8oT3N` over 19:40–20:00 SGT, 3,513 events: 702
invocations carrying one message each, across **3 log streams with 3 `INIT_START`**, 702
`Routing call succeeded` spanning 19:47:39–19:53:16. Mean **125.0 calls/min**, per-minute buckets
42/129/122/125/116/133/35, **peak rolling 60-second window 136 calls/min**. Invocation duration p50
**834 ms**, p90 1275 ms, p99 1790 ms, max 3479 ms.

Three containers at one routing call per invocation and a p50 of 834 ms compute to roughly **216
calls/min, which is above the 200 ceiling**; hitting 200/min with three containers needs only 900 ms per
call, and the p50 is faster than that. The warm-up peaked at 136/min **because the workers were not
saturated**, not because the guard is unreachable. The accurate statement is that the limiter sits about
1.5x above observed peak throughput and **below** saturated three-way throughput, so a sustained backlog
could reach it, and no run so far has produced one. Note also that the three containers are **observed,
not read from configuration** — the drill role is denied `lambda:ListEventSourceMappings`, so the
concurrency cap itself is not verified here.

**It does not promise recovery, and an earlier draft of this section wrongly implied that it does.**
A 180-second visibility timeout guarantees the redelivery lands in a _different_ window, not an
_available_ one — another in-flight worker can have filled it — and an available budget says nothing
about whether the route then returns an itinerary. `_process()` retries only while
`attempts < max_receives`, and `max_receives` is 3, so a job that meets a full window has two further
chances and then exhausts into a terminal `unavailable` with `TRANSIENT_RETRY_SECONDS`. The design
bounds the retry; it does not guarantee the pair recovers. Correction due to @wkkuu on #35.

### The four legs, and the rule for a missing one

@wkkuu set this bar and it is stricter than the original proposal. All four correlate on one `jobId`:

1. `OneMap call budget reached for this window`, with `onemapWindow` and `onemapCeiling`;
2. `Routing failed; returning the job to the queue` for that `jobId`, with `routingError` and `attempts`, timestamped;
3. a later `Commute pair resolved` for that `jobId`, with `attempts` incremented, timestamped;
4. the persisted record for that pair.

Leg 4 needs `dynamodb` read, which the drill role denies, so it belongs to whoever holds table access.

**An `attempts >= 2` result on its own does not establish why a job retried.** `RoutingRetryable` also
covers an unreadable counter, an unreachable OneMap and a malformed routing plan, so the attempt count
without leg 1 for the same `jobId` shows that a retry happened, not which path caused it.

### The correlation keys, measured rather than assumed

`scripts/test_retry_legs.py` runs the real `commute_worker.handler` against Moto with `urlopen`
stubbed, pre-fills the window counter to `WORKER_CALLS`, and delivers the same message twice. All four
legs reproduce — and two of them do not correlate the way the bar above assumes:

|                                             | Finding                                                                                                                                                                                                                                                                                                                                         |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Leg 1 carries no `jobId`**                | It is emitted from `call_budget.reserve`, which never sees the job. Legs 1 and 2 can only be tied together by **`function_request_id`**, the Lambda invocation. Legs 2 and 3 then tie by `jobId`.                                                                                                                                               |
| **`routingError` cannot identify the path** | A budget exhaustion logs `ROUTING_UNAVAILABLE`, which is `RoutingRetryable.code` — shared with throttling, 5xx, transport failures and unreadable bodies. So neither the attempt count nor the error code distinguishes budget exhaustion from any other transient cause. **Only leg 1's message does**, reached through `function_request_id`. |

So the chain is: leg 1 → `function_request_id` → leg 2 → `jobId` → leg 3 → the pair key → leg 4. Reading it
by `jobId` alone, as originally proposed, would have silently dropped leg 1 and left a retry whose cause
was unidentified — which is exactly what @wkkuu said an attempt count cannot establish.

The harness also confirmed the retry stores `attempts: 2` and that 1,802 s is retained as
30.033… minutes rather than rounded, which is the #74 fractional-duration correction behaving as
intended on the recovery path.

It is a Moto run with no real worker, no real queue and no real OneMap call, so it establishes the log
shapes and the correlation keys, nothing about the deployed system. Its value is that the reading method
is fixed and tested before any logs exist to read.

**If any leg is missing, the metric is reported as unmeasured.** That includes the likely outcome — a
clean one-invocation-per-message drain — which would mean the guard went untested on AWS again. A
partial chain is not presented as recovery. A budget-exhausted job that exhausts its three receives and
ends `unavailable` is also a result and is recorded as one.

**Deliberately inducing this is not authorized and is not planned.** Pre-filling the window counter was
proposed on #35 and refused by @wkkuu; it would need its own reviewed plan, authorization, budget,
isolation, monitoring and cleanup, and none is sought before 8 November.

## Rehearsal, 6 November

The whole procedure was rehearsed end to end against a Moto server before any eval access existed,
with `DRILL_ACCOUNT`, `DRILL_SRC_NAME` and `DRILL_DLQ_NAME` pointed at throwaway queues carrying the
same 3-receive redrive policy, and a CloudWatch alarm created under the real alarm name. A stand-in
consumer received the message without deleting it, which is what `_process()` does when `_parse()`
raises `Unkeyable`.

What the rehearsal established: steps 0 and 1 run, the message dead-letters after three deliveries,
step 2 detects it, step 4 reads it under the lease without consuming it, step 6 deletes **only** the
message carrying the session's marker and leaves anything else alone, and step 8 produces the receipt
offline. It also corrected the two pass conditions above, which had been written from the
implementation rather than from a run.

What it cannot establish: Moto is not AWS, there is no real worker, no real OneMap call and no real
alarm evaluation, so the measured alarm delay, the Phase-B terminal record and the log entries all
still require the eval session. The rehearsal proves the _procedure_ is executable; it measures
nothing about the deployed system. **It also missed Phase B's refused write entirely**,
because no worker ran in it — @shyamgj1900 found that by reading the implementation while building
the role, which is the kind of thing a harness without the real consumer cannot surface. This is the same boundary the
[worker-queue harness](../worker-queue/README.md) states for its own runs.

## Current blockers

- **Resolved 6 November:** eval access, as the role above. Phase B's table write turned out not to exist, so the authorisation it would have needed is moot.
- **Sequencing.** The drill runs only after @wkkuu posts that the #30 load run has finished, so a DLQ alarm cannot land inside his window. The operator deletes the role once the receipt is posted, and no later than 8 November.
- **Still open: the #33 walkthrough** by a teammate who is not the runbook's author, in or near the same session. @saravanamani1999's eval access is unconfirmed.
