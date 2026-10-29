import assert from 'node:assert/strict';
import { test } from 'node:test';
import { App, Duration, RemovalPolicy, Stack } from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { LogGroup } from 'aws-cdk-lib/aws-logs';
import { Queue } from 'aws-cdk-lib/aws-sqs';
import { CommuteAlarms } from '../src/alarms.js';

/** The construct takes primitives, so these assertions need no Python bundle. */
function synthesize(alertEmail?: string): Template {
  const stack = new Stack(new App(), 'Test');
  const dlq = new Queue(stack, 'Dlq');
  new CommuteAlarms(stack, 'CommuteAlarms', {
    stage: 'dev',
    jobsQueue: new Queue(stack, 'Jobs', {
      deadLetterQueue: { queue: dlq, maxReceiveCount: 3 },
      visibilityTimeout: Duration.seconds(180),
    }),
    deadLetterQueue: dlq,
    apiLogGroup: new LogGroup(stack, 'Logs', {
      removalPolicy: RemovalPolicy.DESTROY,
    }),
    alertEmail,
  });
  return Template.fromStack(stack);
}

test('one message in the dead-letter queue raises an alarm', () => {
  const found = Object.values(
    synthesize().findResources('AWS::CloudWatch::Alarm'),
  ).filter(
    (alarm) =>
      alarm.Properties.MetricName === 'ApproximateNumberOfMessagesVisible',
  );

  assert.equal(found.length, 1);
  const [{ Properties: properties }] = found;
  assert.equal(properties.Threshold, 1);
  assert.equal(properties.EvaluationPeriods, 1);
  assert.equal(properties.ComparisonOperator, 'GreaterThanOrEqualToThreshold');
  // An empty queue publishes nothing, so missing data must not alarm.
  assert.equal(properties.TreatMissingData, 'notBreaching');
  assert.equal(properties.Statistic, 'Maximum');
});

test('a queue that stops draining raises an alarm after three visibility timeouts', () => {
  const found = Object.values(
    synthesize().findResources('AWS::CloudWatch::Alarm'),
  ).filter(
    (alarm) => alarm.Properties.MetricName === 'ApproximateAgeOfOldestMessage',
  );

  assert.equal(found.length, 1);
  const [{ Properties: properties }] = found;
  // 180 s visibility x 3 receives is the longest a healthy pair can take.
  assert.equal(properties.Threshold, 540);
  assert.equal(properties.EvaluationPeriods, 2);
  assert.equal(properties.ComparisonOperator, 'GreaterThanThreshold');
});

test('the token warning is published from the log and alarmed on', () => {
  const template = synthesize();
  template.hasResourceProperties('AWS::Logs::MetricFilter', {
    FilterPattern: '{ $.onemapTokenWarning IS TRUE }',
    MetricTransformations: [
      {
        MetricName: 'OneMapTokenWarning',
        MetricNamespace: 'FlatSplit/dev',
        MetricValue: '1',
        DefaultValue: 0,
      },
    ],
  });
  const found = Object.values(
    template.findResources('AWS::CloudWatch::Alarm'),
  ).filter((alarm) => alarm.Properties.MetricName === 'OneMapTokenWarning');
  assert.equal(found.length, 1);
  assert.equal(found[0].Properties.Threshold, 1);
});

test('every alarm notifies the one topic', () => {
  const template = synthesize();
  const topics = template.findResources('AWS::SNS::Topic');
  assert.equal(Object.keys(topics).length, 1);
  const [topicId] = Object.keys(topics);

  const all = Object.values(template.findResources('AWS::CloudWatch::Alarm'));
  assert.equal(all.length, 3);
  for (const alarm of all) {
    assert.deepEqual(alarm.Properties.AlarmActions, [{ Ref: topicId }]);
    assert.ok(
      typeof alarm.Properties.AlarmDescription === 'string' &&
        alarm.Properties.AlarmDescription.length > 0,
      'an alarm with no description tells the on-call person nothing',
    );
  }
});

test('the email is subscribed when given and the alarms exist without it', () => {
  const withEmail = synthesize('ops@example.com');
  withEmail.hasResourceProperties('AWS::SNS::Subscription', {
    Protocol: 'email',
    Endpoint: 'ops@example.com',
  });

  const without = synthesize();
  assert.equal(
    Object.keys(without.findResources('AWS::SNS::Subscription')).length,
    0,
  );
  assert.equal(
    Object.keys(without.findResources('AWS::CloudWatch::Alarm')).length,
    3,
  );
});
