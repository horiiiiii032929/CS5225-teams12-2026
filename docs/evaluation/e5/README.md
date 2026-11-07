# E5 — failure, alarm and dead-letter recovery

**Question.** When a commute job cannot succeed, does it stop, become visible, and leave its pair honestly unresolved — rather than loop, silently vanish, or acquire an invented travel time?

**Status:** the queue-reachable part is **measured** on the `eval` stage, 7 November 2026. Three of E5's seven metrics are deployed evidence, one is mechanism only, and three are unmeasured. **E5 is not complete.** See [What this does not establish](#what-this-does-not-establish).

|                                           |                                                                                                                                                                               |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Procedure (pre-registered before the run) | [`procedure.md`](procedure.md)                                                                                                                                                |
| Scripts                                   | [`scripts/`](scripts/), `dlq_drill.sh` v1.0.0                                                                                                                                 |
| Raw output                                | [`raw/2026-11-07/`](raw/2026-11-07/)                                                                                                                                          |
| Stage                                     | `FlatSplit-eval`, revision `e2d3780e28028574f8ee3dd990c10257be9f8029`                                                                                                         |
| Operator                                  | @lukerspace, via the scoped `FlatSplit-eval-Drill27` role granted by @shyamgj1900 on #27                                                                                      |
| Session                                   | 11:47:42 → 12:01:46 SGT, marker `drill-27-20261107T034815Z`                                                                                                                   |
| Issue threads                             | [#27](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/27) (drill), [#30](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/30) (stage coordination) |

Pre-state: both queues `0/0`, all five alarms `OK`, DLQ confirmed empty before anything was sent. The deployed queue configuration matched what the procedure assumed — `VisibilityTimeout` 180 s, `maxReceiveCount` 3 to the DLQ, source retention 345,600 s, DLQ retention 1,209,600 s.

## Phase A — a permanently unkeyable job reaches the DLQ and raises the alarm

Covers #27's second acceptance criterion: a permanently failing job is visible and does not loop indefinitely.

One message with `schemaVersion: 0`. `_parse()` raises `Unkeyable` and `_process()` returns before `_route()`, so **no OneMap call and no cache item is addressed**.

|                              | Measured                                                                 |
| ---------------------------- | ------------------------------------------------------------------------ |
| Deliveries to the worker     | **exactly 3** — 11:48:18.982, 11:51:17.120, 11:54:17.112 SGT             |
| Interval between deliveries  | **180 s**, matching the deployed `VisibilityTimeout`                     |
| Failure reason, every time   | `Unsupported payload version 0.`                                         |
| Dead-lettered                | between 11:57:42 and 11:57:53 SGT — **9 min 37 s** after injection       |
| `CommuteDlqNotEmpty`         | `OK → ALARM` at **11:59:32.200 SGT**                                     |
| Alarm delay from DLQ arrival | **99–110 s** (the arrival is bracketed by an 11-second polling interval) |

**The attempt count must be read from the log, not from the message.** The DLQ message's `ApproximateReceiveCount` read **4**, not 3, because §4's 60-second inspection lease increments it. The procedure predicted this and the run confirmed it: a pass condition read off the inspection would be falsified by the act of inspecting.

**The alarm delay is one sample, and this run does not establish a rule for it.** The alarm is `ApproximateNumberOfMessagesVisible`, `Maximum`, 300-second period, threshold ≥ 1, `notBreaching` on missing data. Its `StateReason` names the breaching datapoint as `1.0 (07/11/26 03:53:00)` — a window of 11:53:00–11:58:00 SGT, so the alarm's windows are anchored on its own schedule rather than clock-aligned, and the message landed a few seconds before that one closed.

Two measured transitions, and they do not follow the same rule:

|              | Measured                                                        |
| ------------ | --------------------------------------------------------------- |
| `OK → ALARM` | 11:59:32.200 SGT — **92 s after** the 11:53–11:58 window closed |
| `ALARM → OK` | 12:07:32.199 SGT — **before** the 12:03–12:08 window closed     |

So the clearing transition used a window that had not finished and the raising one did not. **One drill cannot resolve that**, and nothing here should be read as how CloudWatch evaluates alarms in general. What the run establishes is the pair of timestamps above, and that in this instance the delay was small relative to the 300-second period.

An earlier draft of the procedure called the 300-second period a **floor** on the delay; the measured 99–110 s refutes that. It is tempting to replace it with "the period bounds the jitter, not the size", which was my first reading, but the clearing transition does not support that either. The procedure now records the delay, the period and where the arrival fell, and declines to generalise.

## Phase B — a permanently rejected job stops without retrying, and writes nothing

Covers E5's "retries on permanent errors (expect 0)", which Phase A cannot: an unkeyable message has no pair to close.

One keyable message for the synthetic pair `COMMUTE#DRILL27 / TOWN#DRILL` with non-numeric coordinates. `route()` raises `RoutingRejected` from `_point()` **before any HTTP call**, so this spends no quota either.

|                     | Measured                                                                                  |
| ------------------- | ----------------------------------------------------------------------------------------- |
| Deliveries          | **exactly 1**, `attempts: 1` — a permanent error consumed no retries                      |
| Log line            | `A newer claim or result owns this pair; terminal write skipped` at 12:00:16.263 SGT      |
| `routingError`      | `INVALID_ROUTE_REQUEST`, `reason: "The job's lat is not a number."`                       |
| Correlation         | `jobId` `128035d3-…` matches the injected body; `function_request_id` `fc9ec3e9-…`        |
| Message disposition | **deleted, not redelivered** — the source queue returned to `0/0`                         |
| DLQ depth           | **unchanged** by this phase                                                               |
| Table               | **no item created.** Unchecked by the operator: the drill role denies `dynamodb` entirely |

**The terminal write is refused, and that is the implementation working.** @shyamgj1900 established this from the code while building the role: `CommuteResults._write` fences every completion with `ConditionExpression="#jobId = :jobId AND #status = :pending"`, and only the API's enqueue creates that pending claim. A message sent straight to the queue therefore cannot manufacture a result for a pair nobody asked about. So the zero-retry evidence is **that log line plus the queue state**, not a record — and the drill demonstrates the fence as a side effect.

**This is also why the log filter mattered.** Phase A's entry is `Unusable commute job`; Phase B's is `A newer claim or result owns this pair; terminal write skipped`, which does not contain the substring `commute job`. The procedure's step 5 originally filtered on that substring alone, so Phase B — whose only evidence is a log line, since the write is refused — would have been captured with **nothing at all**. Both terms are now required, and the run captured 4 events: 3 for Phase A, 1 for Phase B.

## Phase C — not run

Redrive was skipped. It demonstrates the mechanism, not recovery: Phase A's message fails identically on every delivery because nothing about it was transient. The 26 October Moto harness already exercised the mechanism (`unaccountable_payload`: three receives, then redrive, source empty, DLQ depth 1). Neither run shows a pair that failed, was redriven, and then succeeded.

## Cleanup

Both drill messages were deleted **by receipt handle**. The role deliberately has no `sqs:PurgeQueue`, which would have destroyed anything a teammate had in the queue. Phase B's message needed no cleanup: the worker had already deleted it.

|                                    |                                                                                        |
| ---------------------------------- | -------------------------------------------------------------------------------------- |
| Drill message deleted from the DLQ | 12:01:09 SGT                                                                           |
| **Both queues confirmed `0/0`**    | **12:01:46 SGT** — the timestamp quoted on #30                                         |
| `CommuteDlqNotEmpty` back to `OK`  | **12:07:32.199 SGT**, 8 min 0 s after it raised and 6 min 23 s after the queue emptied |
| Other four alarms                  | never left `OK`                                                                        |

No OneMap quota was spent in either phase, so the 729 warm catalog pairs and the 7 November load window were untouched.

## What this establishes

- **DLQ and attempt bounds** — deployed evidence. Three deliveries, then dead-lettered; bounded, visible, and not looping.
- **Measured alarm delay** — deployed evidence, with the phase caveat above.
- **Retries on a permanent error: zero** — deployed evidence, plus the write fence.

## What this does not establish

- **Jobs recovered by retry — unmeasured, and it stays that way.** The 26 October Moto drain had 0 redeliveries and its `retry_exhaustion` scenario exhausts rather than recovers. The 6 November `eval` warm-up cached all 729 catalog pairs, so the W1/W2 load run enqueues no commute job, the worker is never invoked, and `call_budget.reserve` is never called — the first link of the agreed four-leg chain cannot exist. Known before the run, not concluded from an empty log.
- **The token-warning alarm — not provoked.** Invalidating the token breaks the stage for everyone and `eval` shares the team OneMap account with `dev`. #72's observed post-expiry gap is the honest citation.
- **Honest unavailable / retry UI — not here.** #26, with @Raccoon33 and @horiiiiii032929. Phase B supplies the record behind such a surface, not the surface.
- **W4 as the evaluation plan specifies it cannot be run by this route at all.** Injecting a transient _routing_ failure means making OneMap appear to fail to the deployed worker; the stack has no fault switch and the drill role has queue access plus alarm and log reads.
- **The worker's concurrency cap is not verified.** The 6 November warm-up _observed_ three containers; the drill role denies `lambda:ListEventSourceMappings`, so the configured cap is unread.

The report should say which parts rest on AWS, which on the Moto harness in [`../worker-queue/`](../worker-queue/README.md), and which on nothing.
