#!/bin/bash
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
export AWS_ACCESS_KEY_ID=rehearsal AWS_SECRET_ACCESS_KEY=rehearsal
export AWS_ENDPOINT_URL=http://127.0.0.1:5001
export AWS_REGION=ap-southeast-1 AWS_DEFAULT_REGION=ap-southeast-1
export DRILL_ACCOUNT=123456789012
export DRILL_SRC_NAME=FlatSplit-eval-ApiCommuteJobs-rehearsal
export DRILL_DLQ_NAME=FlatSplit-eval-ApiCommuteDlq-rehearsal
export DRILL_WATCH_TICKS=24 DRILL_WATCH_SLEEP=2
export EV="$HERE/rehearsal-evidence"
rm -rf "$EV"; mkdir -p "$EV"

echo "### creating the two queues with a 3-receive redrive policy"
DLQ_URL=$(aws sqs create-queue --queue-name "$DRILL_DLQ_NAME" --query QueueUrl --output text)
DLQ_ARN=$(aws sqs get-queue-attributes --queue-url "$DLQ_URL" --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
SRC_URL=$(aws sqs create-queue --queue-name "$DRILL_SRC_NAME" \
  --attributes "{\"VisibilityTimeout\":\"2\",\"RedrivePolicy\":\"{\\\"deadLetterTargetArn\\\":\\\"$DLQ_ARN\\\",\\\"maxReceiveCount\\\":\\\"3\\\"}\"}" \
  --query QueueUrl --output text)
echo "    src=$SRC_URL"; echo "    dlq=$DLQ_ARN"

echo "### creating the DLQ-depth alarm under its real name"
aws cloudwatch put-metric-alarm \
  --alarm-name FlatSplit-eval-CommuteAlarmsCommuteDlqNotEmptyF7769442-pqGC0L7DfpRz \
  --namespace AWS/SQS --metric-name ApproximateNumberOfMessagesVisible \
  --dimensions "Name=QueueName,Value=$DRILL_DLQ_NAME" \
  --statistic Maximum --period 300 --evaluation-periods 1 \
  --threshold 1 --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching

echo; echo "### step 0 - identity and pre-state"
bash "$HERE/dlq_drill.sh" 0 || exit 1
echo; echo "### step 1 - Phase A injection"
bash "$HERE/dlq_drill.sh" 1 >/dev/null || exit 1
MARK=$(cat "$EV/marker.txt"); echo "    marker $MARK"

echo; echo "### stand-in worker: receive without deleting, as _process() returns True for Unkeyable"
for i in 1 2 3 4; do
  N=$(aws sqs receive-message --queue-url "$SRC_URL" --max-number-of-messages 1 \
       --visibility-timeout 1 --attribute-names ApproximateReceiveCount \
       --query 'length(Messages || `[]`)' --output text)
  RC=$(aws sqs receive-message --queue-url "$SRC_URL" --max-number-of-messages 0 2>/dev/null; echo)
  echo "    receive attempt $i: messages returned = $N"
  sleep 3
done

echo; echo "### step 2 - watch for the DLQ"
bash "$HERE/dlq_drill.sh" 2 | tail -4
echo; echo "### step 3 - alarm history"
bash "$HERE/dlq_drill.sh" 3 >/dev/null 2>&1 && echo "    step 3 ran" || echo "    step 3 errored (expected: Moto has no alarm history)"
echo; echo "### step 4 - inspect under a 60s lease"
bash "$HERE/dlq_drill.sh" 4 | tail -14
echo; echo "### step 1b - Phase B injection"
bash "$HERE/dlq_drill.sh" 1b >/dev/null && echo "    Phase B payload sent"
echo; echo "### step 6 - cleanup, delete only ours"
sleep 62
bash "$HERE/dlq_drill.sh" 6 | tail -5
echo; echo "### step 8 - receipt"
bash "$HERE/dlq_drill.sh" 8
