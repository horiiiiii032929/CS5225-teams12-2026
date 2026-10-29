import { Duration } from 'aws-cdk-lib';
import {
  Alarm,
  ComparisonOperator,
  TreatMissingData,
} from 'aws-cdk-lib/aws-cloudwatch';
import { SnsAction } from 'aws-cdk-lib/aws-cloudwatch-actions';
import {
  FilterPattern,
  MetricFilter,
  type ILogGroup,
} from 'aws-cdk-lib/aws-logs';
import { Topic } from 'aws-cdk-lib/aws-sns';
import { EmailSubscription } from 'aws-cdk-lib/aws-sns-subscriptions';
import type { IQueue } from 'aws-cdk-lib/aws-sqs';
import { Construct } from 'constructs';

export interface CommuteAlarmsProps {
  readonly stage: string;
  /** Producer queue (#16); a rising oldest-message age means nothing drains it. */
  readonly jobsQueue: IQueue;
  /** Only holds what the worker could not account for, so one message matters. */
  readonly deadLetterQueue: IQueue;
  /** The API handler's log group, where the OneMap token warning is written. */
  readonly apiLogGroup: ILogGroup;
  /** Subscribed to the alert topic when set; alarms exist either way. */
  readonly alertEmail?: string;
}

/**
 * Operational alerts for the commute path (#27).
 *
 * The queue and its redrive policy already existed; what was missing was
 * anybody finding out. Three things can go wrong quietly:
 *
 * - a message reaches the dead-letter queue, which the handler only allows
 *   when it could not account for the message at all;
 * - the jobs queue stops draining, so pairs stay pending and a search never
 *   completes, with no error anywhere;
 * - the OneMap token approaches or passes expiry, which is routine for a
 *   three-day JWT and silent by design upstream - a lookup still answers 200
 *   during the grace period, so the log line is the only signal.
 *
 * `OneMapTokenWarning` is published from the handler's structured log rather
 * than counted in the application, because the token can expire with no
 * traffic at all and a metric nobody emits cannot alarm.
 */
export class CommuteAlarms extends Construct {
  /** Alert fan-out; #72's rotation failure and #15's worker errors attach here. */
  readonly topic: Topic;
  readonly dlqAlarm: Alarm;
  readonly stalledAlarm: Alarm;
  readonly tokenWarningAlarm: Alarm;

  constructor(scope: Construct, id: string, props: CommuteAlarmsProps) {
    super(scope, id);

    this.topic = new Topic(this, 'Alerts', {
      displayName: `FlatSplit ${props.stage} operational alerts`,
    });
    if (props.alertEmail) {
      this.topic.addSubscription(new EmailSubscription(props.alertEmail));
    }
    const notify = new SnsAction(this.topic);

    this.dlqAlarm = new Alarm(this, 'CommuteDlqNotEmpty', {
      alarmDescription:
        'A commute job reached the dead-letter queue: the worker could not ' +
        'account for it. Inspect, then redrive with ' +
        'aws sqs start-message-move-task.',
      metric: props.deadLetterQueue.metricApproximateNumberOfMessagesVisible({
        period: Duration.minutes(5),
        statistic: 'Maximum',
      }),
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      // An empty queue publishes nothing, so missing data is the healthy case.
      treatMissingData: TreatMissingData.NOT_BREACHING,
    });
    this.dlqAlarm.addAlarmAction(notify);

    this.stalledAlarm = new Alarm(this, 'CommuteJobsStalled', {
      alarmDescription:
        'Commute jobs are not draining: the oldest message has waited longer ' +
        'than three visibility timeouts, so pairs stay pending and no search ' +
        'completes. Check the worker, its concurrency and the OneMap budget.',
      metric: props.jobsQueue.metricApproximateAgeOfOldestMessage({
        period: Duration.minutes(5),
        statistic: 'Maximum',
      }),
      // 180 s visibility x 3 receives is the longest a healthy pair can take.
      threshold: Duration.minutes(9).toSeconds(),
      evaluationPeriods: 2,
      comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: TreatMissingData.NOT_BREACHING,
    });
    this.stalledAlarm.addAlarmAction(notify);

    const tokenWarning = new MetricFilter(this, 'OneMapTokenWarning', {
      logGroup: props.apiLogGroup,
      metricNamespace: `FlatSplit/${props.stage}`,
      metricName: 'OneMapTokenWarning',
      filterPattern: FilterPattern.booleanValue('$.onemapTokenWarning', true),
      metricValue: '1',
      defaultValue: 0,
    });
    this.tokenWarningAlarm = new Alarm(this, 'OneMapTokenExpiring', {
      alarmDescription:
        'The OneMap token is at or near expiry. It is a three-day JWT with no ' +
        'renewal endpoint, and a lookup still answers 200 during the grace ' +
        'period, so this log line is the only warning. Rotate the secret.',
      metric: tokenWarning.metric({
        period: Duration.minutes(5),
        statistic: 'Sum',
      }),
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: TreatMissingData.NOT_BREACHING,
    });
    this.tokenWarningAlarm.addAlarmAction(notify);
  }
}
