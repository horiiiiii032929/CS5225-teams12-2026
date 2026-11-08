#!/usr/bin/env bash
# Read-only snapshot of a deployed FlatSplit stack's components, for the #36
# architecture figure. Prints no secrets: only resource types, names and
# configuration that the CDK template already declares.
# Usage: STACK=FlatSplit-eval docs/evaluation/architecture/scripts/readback.sh > raw/<date>/readback.txt
set -euo pipefail
STACK=${STACK:-FlatSplit-eval}
aws() { command aws --output json "$@"; }
RESOURCES=$(aws cloudformation describe-stack-resources --stack-name "$STACK")
# A CDK logical ID is the construct path plus an 8-character hash.
phys() { python3 -c 'import json,re,sys
m=[r["PhysicalResourceId"] for r in json.loads(sys.argv[2])["StackResources"] if re.fullmatch(sys.argv[1]+"[0-9A-F]{8}",r["LogicalResourceId"])]
assert len(m)==1,(sys.argv[1],m);print(m[0])' "$1" "$RESOURCES"; }

echo "# captured_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "# account: $(command aws sts get-caller-identity --query Account --output text)"
echo "# stack: $STACK"
aws cloudformation describe-stacks --stack-name "$STACK" \
  --query 'Stacks[0].{status:StackStatus,created:CreationTime,updated:LastUpdatedTime}'
echo "## resource types"
printf '%s' "$RESOURCES" | python3 -c 'import json,sys,collections;[print(f"{v:3} {k}") for k,v in sorted(collections.Counter(r["ResourceType"] for r in json.load(sys.stdin)["StackResources"]).items())]'
echo "## lambda functions"
for id in ApiHttpHandler ApiCommuteWorker ApiOneMapTokenRefresh RentIngestionHandler; do
  aws lambda get-function-configuration --function-name "$(phys "$id")" \
    --query "{fn:'$id',runtime:Runtime,arch:Architectures[0],memory:MemorySize,timeout:Timeout,state:State,lastModified:LastModified}"
done
echo "## worker event source mapping"
aws lambda list-event-source-mappings --function-name "$(phys ApiCommuteWorker)" \
  --query 'EventSourceMappings[].{state:State,batch:BatchSize,maxConcurrency:ScalingConfig.MaximumConcurrency,reportFailures:FunctionResponseTypes}'
echo "## queues"
for id in ApiCommuteJobs ApiCommuteDlq; do
  aws sqs get-queue-attributes --queue-url "$(phys "$id")" --attribute-names VisibilityTimeout RedrivePolicy MessageRetentionPeriod ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
    --query "{queue:'$id',attrs:Attributes}"
done
echo "## api stage throttling"
aws apigatewayv2 get-stages --api-id "$(phys ApiHttpApi)" \
  --query 'Items[].{stage:StageName,burst:DefaultRouteSettings.ThrottlingBurstLimit,rate:DefaultRouteSettings.ThrottlingRateLimit}'
echo "## table"
TABLE=$(phys DataTable)
aws dynamodb describe-table --table-name "$TABLE" --query 'Table.{billing:BillingModeSummary.BillingMode,status:TableStatus,items:ItemCount}'
aws dynamodb describe-continuous-backups --table-name "$TABLE" \
  --query 'ContinuousBackupsDescription.PointInTimeRecoveryDescription.PointInTimeRecoveryStatus'
echo "## schedules"
for id in ApiOneMapTokenRefreshSchedule RentIngestionMonthlySchedule; do
  aws events describe-rule --name "$(phys "$id")" --query "{rule:'$id',schedule:ScheduleExpression,state:State}"
done
echo "## alarms and notification"
aws cloudwatch describe-alarms --alarm-name-prefix "$STACK-" \
  --query 'MetricAlarms[].{alarm:AlarmName,state:StateValue,actions:length(AlarmActions)}'
TOPIC=$(phys CommuteAlarmsAlerts)
aws sns get-topic-attributes --topic-arn "$TOPIC" \
  --query '{confirmed:Attributes.SubscriptionsConfirmed,pending:Attributes.SubscriptionsPending}'
