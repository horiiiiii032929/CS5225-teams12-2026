# E5 failure, alarm and dead-letter drill procedure

**Experiment:** E5

**Status:** Procedure only; not yet run. Blocked on working `eval` access (#27).

**Environment:** Dedicated `eval` stage only. @wkkuu established on [#72](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/72#issuecomment-6625779422) that dead-letter injection is outside shared `dev` scope, and that is accepted.

**Owner:** Ming (@lukerspace), #27 and #19. Checked by @wkkuu under #35. The #33 runbook walkthrough runs in the same session and is @saravanamani1999's, not the author's.

## Question

When a commute job cannot succeed, does it stop, become visible, and leave its pair honestly unresolved — rather than loop, silently vanish, or acquire an invented travel time?

## What this procedure can and cannot establish

Pre-registered deliberately, because E5's metric list in the [evaluation plan](../../evaluation-plan.md) is wider than a queue-only drill can reach. The plan's workload **W4** is "W3 with 30% injected transient routing failures, then 100% for 5 minutes, then restored", plus permanent 400/403/404, routing 401 and 429 handling. Injecting a *transient routing* failure means making OneMap appear to fail to the deployed worker. Nothing in the deployed stack offers a fault switch, and the drill operator has queue access plus alarm and log reads — not the ability to intercept the worker's upstream calls. **W4 as specified cannot be run on `eval` by this route at all.**

| E5 metric | This drill | Where it actually comes from |
| --- | --- | --- |
| DLQ and attempt bounds | **Yes** — Phase A | new `eval` evidence |
| Alarm delay | **Yes** — Phase A, from alarm history | new `eval` evidence |
| Retries on permanent errors (expect 0) | **Yes** — Phase B | new `eval` evidence |
| Redrive recovery | **Mechanism only** — Phase C | partial; see Phase C |
| Jobs recovered by retry | **No** | not measured anywhere yet. The 26 October Moto drain had 0 redeliveries, and its `retry_exhaustion` scenario exhausts rather than recovers. State as unmeasured. |
| Token-warning alarm | **No** | invalidating the token breaks the stage for everyone and `eval` shares the team OneMap account with `dev`. Cite #72's observed post-expiry gap instead; do not provoke it. |
| Honest unavailable / retry UI | **No** | #26's UI work, with Lucy and Hikaru. Phase B supplies the *record* behind such a surface, not the surface. |

So the drill supplies three of E5's seven metrics as deployed evidence, one as a mechanism, and leaves three explicitly unmeasured. **E5 must not be reported as complete after this session.** The report should say which parts rest on AWS, which on the Moto harness in [`../worker-queue/`](../worker-queue/README.md), and which on nothing.

## Preconditions

Do not start until all of the following hold:

1. **Working access**, not a resource list: either an assumable role scoped to the two `eval` commute queues with alarm and log reads, or an operator-led witnessed session. A verbal authorization plus queue names did not give the drill operator account access on 5 November.
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
- the message fails identically on every receive, which is what makes it a *permanent* failure rather than a slow one.

Observe, with timestamps: the source queue depth, the three receives at the 180-second visibility timeout, the message's arrival in the DLQ, and the `CommuteDlqNotEmpty` transition in alarm history. Then read the DLQ message **under a 60-second inspection lease** — receive it, read it, do not delete it — and record its `ApproximateReceiveCount`, `SentTimestamp` and body, per §4 of the [runbook](../../data-refresh-runbook.md).

### Phase-A pass conditions

- The message is dead-lettered after exactly three deliveries **to the worker**, not sooner and
  not indefinitely redelivered. Count this from the three `Unusable commute job` log entries,
  **not** from the `ApproximateReceiveCount` read off the DLQ message: §4's inspection lease
  increments that count itself, and the rehearsal below read 4 for a message delivered three
  times. A pass condition read off the inspection would fail on its own artifact.
- `CommuteDlqNotEmpty` moves `OK → ALARM`, and the delay between the DLQ arrival and the transition is recorded as the **measured alarm delay**, with the 5-minute Maximum period stated as its floor.
- The worker log group carries one `Unusable commute job` entry per receive, matching the marker.
- No pair record is created or changed by this phase. Nothing in the payload addresses one.
- No OneMap call is attributable to the drill in the same window.

## Phase B — a permanently rejected job closes its pair without retrying

Covers E5's "retries on permanent errors (expect 0)", which Phase A cannot: an unkeyable message has no pair to close.

Inject one message that **is** keyable — valid `schemaVersion: 1`, `jobId`, `stationKey` and `town` — but whose coordinates are unusable. `route()` raises `RoutingRejected`, a subclass of `RoutingUnroutable`, from `_point()` **before any HTTP call**, so this also spends no quota. `_process()` then takes the `RoutingUnroutable` branch: it writes a terminal `unavailable` with `attempts: 1` and `retryAfter` 86,400 s ahead, and returns `False`, so the message is deleted rather than redelivered.

Use a **synthetic key that collides with nothing real** — `stationKey: DRILL27`, `town: DRILL`, giving `COMMUTE#DRILL27` / `TOWN#DRILL`. This is the one step that writes to the `eval` table, and the write is performed by the worker's own role, not the operator's. It must be agreed with the operator in advance and listed in the cleanup.

### Phase-B pass conditions

- Exactly **one** receive. `attempts: 1` on the record and one worker invocation: a permanent error consumed no retries.
- The pair record carries `status: unavailable` and an error code, and **no `minutes` field**. An unavailable route is never a zero-minute result.
- `retryAfter` is an epoch second roughly 86,400 s ahead, not a duration and not `0`.
- The DLQ depth is unchanged by this phase: a pair the worker could account for does not reach the DLQ.
- The **source** queue returns to zero only once the worker has consumed the Phase-B message.
  If the cleanup step reports a source depth of 1, check whether Phase B is still in flight
  before treating it as a leftover.

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
6. The Phase-B record as read back, showing `status`, `attempts`, `retryAfter` and the absence of `minutes`.
7. The post-cleanup depths and **the time they were checked**, which is what #30 needs.
8. The recorded stage revision, the operator, and the session's start and end.

Screenshots are listed in the plan's evidence column. CLI output with timestamps is preferred over screenshots wherever both are possible: it can be re-read and diffed. Where the plan asks for an alarm screenshot, attach the alarm-history records instead and say so.

## Cleanup, and who does it

1. The operator deletes **their own drill messages by receipt handle**, never with `purge-queue`. A purge would also destroy anything a teammate has in that queue. The grant requested for this drill deliberately omits `sqs:PurgeQueue`.
2. The DLQ is confirmed empty afterwards, and that confirmation is posted on #30 **with the time it was checked**, because #30's load run shares the stage.
3. Phase B's synthetic record `COMMUTE#DRILL27` / `TOWN#DRILL` is deleted, or explicitly left and recorded, by whoever holds table write access. The drill operator is not asking for it.
4. All five alarms are confirmed back to `OK`, or the reason one is not is recorded.

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
still require the eval session. The rehearsal proves the *procedure* is executable; it measures
nothing about the deployed system. This is the same boundary the
[worker-queue harness](../worker-queue/README.md) states for its own runs.

## Current blockers

- **Working `eval` access.** Resource details were published on 5 November; account access was not. See [#27](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/27#issuecomment-6660526283).
- **A witnessed slot before the 8 November implementation finish**, with the #33 walkthrough by a teammate who is not the runbook's author in the same session.
- **Operator agreement on Phase B's synthetic write**, which is the only part of this drill that changes table state.
