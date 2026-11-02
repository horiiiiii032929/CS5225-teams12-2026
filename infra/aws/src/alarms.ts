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
import type { IFunction } from 'aws-cdk-lib/aws-lambda';
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
  /** The worker can be the only caller while a queue is draining. */
  readonly workerLogGroup: ILogGroup;
  /** The scheduled OneMap token refresh (#72); any error is an alert. */
  readonly tokenRefresh: IFunction;
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
 * `OneMapTokenWarning` comes from the handler's structured log, so it only
 * reports while there is traffic: with no requests there are no log events
 * and no datapoints. Expiry during idle periods is prevented instead by #72's
 * scheduled refresh, whose failures raise `OneMapTokenRefreshFailing`.
 */
export class CommuteAlarms extends Construct {
  /** Alert fan-out; #15's worker errors attach here too. */
  readonly topic: Topic;
  readonly dlqAlarm: Alarm;
  readonly stalledAlarm: Alarm;
  readonly tokenWarningAlarm: Alarm;
  readonly tokenRefreshAlarm: Alarm;

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
    new MetricFilter(this, 'CommuteWorkerTokenWarning', {
      logGroup: props.workerLogGroup,
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
        'period, so this log line is the only warning. Check the ' +
        'OneMapTokenRefresh Lambda logs; to refresh now, invoke it ' +
        '(docs/aws-dev-handoff.md).',
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

    this.tokenRefreshAlarm = new Alarm(this, 'OneMapTokenRefreshFailing', {
      alarmDescription:
        'The scheduled OneMap token refresh failed. The current token stays ' +
        'in place until it expires (up to three days), so fix the cause ' +
        'before then: the reason is in the OneMapTokenRefresh Lambda logs ' +
        '(credentials secret, refused login, or a rejected new token).',
      metric: props.tokenRefresh.metricErrors({
        period: Duration.hours(1),
        statistic: 'Sum',
      }),
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      // Most runs only read the secret, so errors are rare and data is sparse.
      treatMissingData: TreatMissingData.NOT_BREACHING,
    });
    this.tokenRefreshAlarm.addAlarmAction(notify);
  }
}
