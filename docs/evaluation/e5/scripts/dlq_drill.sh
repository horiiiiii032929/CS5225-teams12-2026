#!/bin/bash
# CS5225 #27 / E5 eval drill. Run INSIDE the README credential subshell.
# Procedure: docs/evaluation/e5/procedure.md
#
# Usage: bash dlq_drill.sh <step>
#   0    verify identity + record pre-state       (read-only)
#   1    Phase A: inject the unkeyable job        (writes 1 msg to source queue)
#   2    Phase A: watch it reach the DLQ          (read-only, polls)
#   3    Phase A: capture alarm transitions       (read-only)
#   4    Phase A: inspect the DLQ msg, 60s lease  (read-only, no delete)
#   5    worker log lines for the drill           (read-only)
#   1b   Phase B: inject the rejected job         (writes 1 msg; worker writes 1 item)
#   6    cleanup: delete OUR messages, confirm empty
#   7    Phase C OPTIONAL: redrive (mechanism only; re-run 6 after)
#   8    build the receipt from the evidence      (offline, no AWS)
set -uo pipefail

SCRIPT_VERSION=1.0.0   # convention D-E5: record this in every receipt

# Overridable so the whole script can be rehearsed against a Moto server
# before it is pointed at eval. Defaults are the real eval resources.
ACCOUNT=${DRILL_ACCOUNT:-553455762180}
export AWS_REGION=${DRILL_REGION:-ap-southeast-1}
export AWS_DEFAULT_REGION=$AWS_REGION
SRC_NAME=${DRILL_SRC_NAME:-FlatSplit-eval-ApiCommuteJobs7487AB1D-GfmtprOp2wv4}
DLQ_NAME=${DRILL_DLQ_NAME:-FlatSplit-eval-ApiCommuteDlq5A1C45AD-n4LpNoZb1ix1}
WORKER=${DRILL_WORKER:-FlatSplit-eval-ApiCommuteWorkerDCCDFB3E-q5NINW3MSCpw}
# The worker does NOT log to /aws/lambda/<function>. Operator-confirmed name:
WORKER_LOGS=${DRILL_WORKER_LOGS:-FlatSplit-eval-ApiCommuteWorkerLogsA37837F9-YOtZw0L8oT3N}
REVISION=e2d3780e28028574f8ee3dd990c10257be9f8029
ALARMS=(
  FlatSplit-eval-CommuteAlarmsCommuteDlqNotEmptyF7769442-pqGC0L7DfpRz
  FlatSplit-eval-CommuteAlarmsCommuteJobsStalledBD017C6C-spDtpagUajN9
  FlatSplit-eval-CommuteAlarmsOneMapTokenRefreshFailing2F3BF79B-EZFmy862pO18
  FlatSplit-eval-CommuteAlarmsOneMapTokenExpiringE2BD398F-XbS8tBohAc1q
  FlatSplit-eval-CommuteAlarmsRentIngestionFailed77352AD1-IaiMNEomPgSd
)
HERE=$(cd "$(dirname "$0")" && pwd)
EV=${EV:-$HOME/cs5225-drill-evidence}
mkdir -p "$EV"
MARK_F="$EV/marker.txt"

ts()  { date -u +%Y-%m-%dT%H:%M:%SZ; }
sgt() { TZ=Asia/Singapore date +"%H:%M:%S SGT"; }
say() { echo "[$(ts) / $(sgt)] $*" | tee -a "$EV/drill.log"; }
qurl() { aws sqs get-queue-url --queue-name "$1" --queue-owner-aws-account-id "$ACCOUNT" --query QueueUrl --output text; }
depths() {
  aws sqs get-queue-attributes --queue-url "$1" \
    --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
    --query 'Attributes.[ApproximateNumberOfMessages,ApproximateNumberOfMessagesNotVisible]' --output text
}

case "${1:-}" in
0)
  ACTUAL=$(aws sts get-caller-identity --query Account --output text) || exit 1
  if [ "$ACTUAL" != "$ACCOUNT" ]; then
    echo "WRONG ACCOUNT: $ACTUAL != $ACCOUNT - stop." >&2; exit 1
  fi
  aws sts get-caller-identity | tee "$EV/identity.json"
  SRC=$(qurl "$SRC_NAME"); DLQ=$(qurl "$DLQ_NAME")
  echo "$SRC" > "$EV/src_url.txt"; echo "$DLQ" > "$EV/dlq_url.txt"
  say "source  $(depths "$SRC")   (visible / in-flight)"
  say "dlq     $(depths "$DLQ")   (visible / in-flight)"
  D=$(depths "$DLQ" | awk '{print $1+$2}')
  if [ "$D" != "0" ]; then
    say "STOP: the DLQ is not empty ($D). Something else is in there."
    say "Do NOT purge. Ask the operator what it is before going further."
    exit 1
  fi
  say "DLQ confirmed empty at the start of the session, so step 6 can only touch our own messages."
  aws cloudwatch describe-alarms --alarm-names "${ALARMS[@]}" \
    --query 'MetricAlarms[].{name:AlarmName,state:StateValue,since:StateUpdatedTimestamp}' \
    | tee "$EV/alarms_before.json"
  aws sqs get-queue-attributes --queue-url "$SRC" --attribute-names All > "$EV/src_attrs.json"
  aws sqs get-queue-attributes --queue-url "$DLQ" --attribute-names All > "$EV/dlq_attrs.json"
  say "pre-state recorded in $EV"
  ;;
1)
  SRC=$(cat "$EV/src_url.txt")
  MARK="drill-27-$(date -u +%Y%m%dT%H%M%SZ)"
  echo "$MARK" > "$MARK_F"
  # Unkeyable on purpose: _parse() raises Unkeyable and _process() returns True
  # BEFORE _route() is reached, so no OneMap call and no cache item is addressed.
  BODY=$("$HERE"/mkbody.py unkeyable "$MARK" "$REVISION")
  echo "$BODY" > "$EV/injected_body.json"
  say "Phase A: injecting marker $MARK"
  aws sqs send-message --queue-url "$SRC" --message-body "$BODY" | tee "$EV/injected_receipt.json"
  say "injected. 3 receives x 180s visibility => expect the DLQ in ~6-9 min."
  ;;
1b)
  SRC=$(cat "$EV/src_url.txt"); MARK=$(cat "$MARK_F")
  # Keyable, so it addresses a pair, but RoutingRejected fires inside _point()
  # before any OneMap HTTP call. The worker takes the RoutingUnroutable branch:
  # terminal unavailable, attempts 1, retryAfter +86400s, no retry, msg deleted.
  BODY=$("$HERE"/mkbody.py rejected "$MARK" "$REVISION")
  echo "$BODY" > "$EV/injected_body_phaseB.json"
  say "Phase B: injecting permanently-rejected job (expect attempts=1, no retry, DLQ unchanged)"
  aws sqs send-message --queue-url "$SRC" --message-body "$BODY" | tee "$EV/injected_receipt_phaseB.json"
  say "Phase B sent. Terminal record lands on COMMUTE#DRILL27 / TOWN#DRILL."
  say "Reading it needs dynamodb:GetItem, not in this grant - that is Mani's step under #33."
  ;;
2)
  SRC=$(cat "$EV/src_url.txt"); DLQ=$(cat "$EV/dlq_url.txt")
  say "watching for up to 15 minutes"
  for i in $(seq 1 ${DRILL_WATCH_TICKS:-90}); do
    S=$(depths "$SRC"); D=$(depths "$DLQ")
    echo "[$(ts) / $(sgt)] src=$S dlq=$D" | tee -a "$EV/watch.log"
    if [ "$(echo "$D" | awk '{print $1+$2}')" != "0" ]; then
      say "LANDED IN DLQ at $(ts)"; break
    fi
    sleep ${DRILL_WATCH_SLEEP:-10}
  done
  ;;
3)
  SINCE=$(python3 -c "import datetime;print((datetime.datetime.now(datetime.UTC)-datetime.timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M:%SZ'))")
  for A in "${ALARMS[@]}"; do
    echo "--- $A"
    aws cloudwatch describe-alarm-history --alarm-name "$A" \
      --history-item-type StateUpdate --start-date "$SINCE" --end-date "$(ts)" \
      --query 'AlarmHistoryItems[].{at:Timestamp,summary:HistorySummary}' --output table
  done | tee "$EV/alarm_history.txt"
  aws cloudwatch describe-alarms --alarm-names "${ALARMS[@]}" \
    --query 'MetricAlarms[].{name:AlarmName,state:StateValue,since:StateUpdatedTimestamp,reason:StateReason}' \
    | tee "$EV/alarms_after.json"
  ;;
4)
  DLQ=$(cat "$EV/dlq_url.txt")
  # 60-second inspection lease, per runbook section 4. Do NOT delete here.
  aws sqs receive-message --queue-url "$DLQ" --max-number-of-messages 1 \
    --visibility-timeout 60 --attribute-names All --message-attribute-names All \
    | tee "$EV/dlq_message.json"
  "$HERE"/show_msg.py "$EV/dlq_message.json"
  say "inspected without consuming; the lease returns it in 60s"
  ;;
5)
  LG=$(aws logs describe-log-groups --log-group-name-prefix "$WORKER_LOGS" \
    --query 'logGroups[0].logGroupName' --output text)
  say "worker log group: $LG"
  aws logs filter-log-events --log-group-name "$LG" \
    --start-time "$(( ($(date +%s) - 7200) * 1000 ))" \
    --filter-pattern '"commute job"' \
    --query 'events[].{at:timestamp,msg:message}' | tee "$EV/worker_logs.json"
  ;;
6)
  DLQ=$(cat "$EV/dlq_url.txt"); MARK=$(cat "$MARK_F")
  say "cleanup: deleting ONLY messages carrying marker $MARK"
  for i in $(seq 1 12); do
    aws sqs receive-message --queue-url "$DLQ" --max-number-of-messages 10 \
      --visibility-timeout 30 --wait-time-seconds 5 > "$EV/_batch.json" 2>/dev/null
    "$HERE"/show_msg.py "$EV/_batch.json" --handles "$MARK" > "$EV/_handles.txt" 2>/dev/null
    while read -r RH MINE; do
      [ -z "${RH:-}" ] && continue
      if [ "$MINE" = "ours" ]; then
        aws sqs delete-message --queue-url "$DLQ" --receipt-handle "$RH" && say "deleted our drill message"
      else
        say "WARNING: a message that is NOT ours is in the DLQ - left untouched, report it"
      fi
    done < "$EV/_handles.txt"
    D=$(depths "$DLQ")
    [ "$(echo "$D" | awk '{print $1+$2}')" = "0" ] && break
    sleep 5
  done
  sleep 10
  say "final DLQ depth (visible / in-flight): $(depths "$DLQ")"
  say "final source depth: $(depths "$(cat "$EV/src_url.txt")")"
  say "DLQ-empty check time above is the timestamp to quote on #30."
  ;;
7)
  DLQ=$(cat "$EV/dlq_url.txt")
  DLQ_ARN=$(aws sqs get-queue-attributes --queue-url "$DLQ" --attribute-names QueueArn \
    --query 'Attributes.QueueArn' --output text)
  say "Phase C (mechanism only): redriving $DLQ_ARN - it WILL fail again, nothing was transient"
  aws sqs start-message-move-task --source-arn "$DLQ_ARN" | tee "$EV/redrive_task.json"
  sleep 20
  aws sqs list-message-move-tasks --source-arn "$DLQ_ARN" | tee "$EV/redrive_tasks_list.json"
  say "redrive recorded. This is NOT recovery. Run step 6 again afterwards."
  ;;
8)
  "$HERE"/make_receipt.py "$EV"
  ;;
*)
  sed -n '2,16p' "$0"; exit 2 ;;
esac
