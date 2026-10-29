import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { App, RemovalPolicy, Stack } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { AttributeType, Table } from 'aws-cdk-lib/aws-dynamodb';
import { Api } from '../src/api.js';

interface Statement {
  readonly Effect: string;
  readonly Action: string | string[];
  readonly Resource?: unknown;
  readonly Condition?: Record<string, Record<string, string[] | string>>;
}

function synthesize(stage: string): Template {
  const outdir = mkdtempSync(join(tmpdir(), 'flatsplit-api-test-'));
  try {
    const stack = new Stack(new App({ outdir }), `Test-${stage}`);
    const table = new Table(stack, 'Table', {
      partitionKey: { name: 'pk', type: AttributeType.STRING },
      sortKey: { name: 'sk', type: AttributeType.STRING },
    });
    new Api(stack, 'Api', {
      stage,
      removalPolicy: RemovalPolicy.DESTROY,
      table,
    });
    return Template.fromStack(stack);
  } finally {
    rmSync(outdir, { recursive: true, force: true });
  }
}

function actions(statement: Statement): string[] {
  return [statement.Action].flat().sort();
}

/**
 * Allow statements grouped by the Lambda whose role carries them. The API and
 * the commute worker are separate principals, so an unprefixed list of
 * statements can no longer say who was granted what.
 */
function allowedByRole(template: Template): Record<string, Statement[]> {
  const byRole: Record<string, Statement[]> = {};
  for (const policy of Object.values(
    template.findResources('AWS::IAM::Policy'),
  )) {
    const roles = policy.Properties.Roles as { Ref: string }[];
    assert.equal(
      roles.length,
      1,
      'a policy shared by roles cannot be attributed',
    );
    const named = /^Api(\w+?)ServiceRole/.exec(roles[0]!.Ref);
    assert.ok(named, `unexpected role reference ${roles[0]!.Ref}`);
    const statements = policy.Properties.PolicyDocument
      .Statement as Statement[];
    byRole[named[1]!] = [
      ...(byRole[named[1]!] ?? []),
      ...statements.filter((statement) => statement.Effect === 'Allow'),
    ];
  }
  return byRole;
}

/** Each role's `prefix -> actions`, for the statements on one service. */
function accessByRole(
  template: Template,
  service: string,
  prefixKey: string,
): Record<string, Record<string, string[]>> {
  return Object.fromEntries(
    Object.entries(allowedByRole(template))
      .filter(([, statements]) =>
        statements.some((statement) =>
          actions(statement).some((action) => action.startsWith(`${service}:`)),
        ),
      )
      .map(([role, statements]) => [
        role,
        Object.fromEntries(
          statements
            .filter((statement) =>
              actions(statement).some((action) =>
                action.startsWith(`${service}:`),
              ),
            )
            .map((statement) => {
              assert.notEqual(
                statement.Resource,
                '*',
                `${role} may not use ${service}:*`,
              );
              const prefixes =
                statement.Condition?.['ForAllValues:StringLike']?.[prefixKey];
              return [[prefixes].flat().join(','), actions(statement)];
            }),
        ),
      ]),
  );
}

for (const [stage, rate, burst] of [
  ['dev', 20, 40],
  ['prod', 20, 40],
  ['eval', 100, 200],
] as const) {
  test(`${stage} has the intended admission limit`, () => {
    const template = synthesize(stage);
    template.resourceCountIs('AWS::ApiGatewayV2::Stage', 1);
    template.hasResourceProperties('AWS::ApiGatewayV2::Stage', {
      StageName: '$default',
      DefaultRouteSettings: {
        ThrottlingRateLimit: rate,
        ThrottlingBurstLimit: burst,
      },
    });
  });
}

test('table access separates group/commute writes from place/rent reads', () => {
  assert.deepEqual(
    accessByRole(synthesize('dev'), 'dynamodb', 'dynamodb:LeadingKeys'),
    {
      HttpHandler: {
        'GROUP#*': [
          'dynamodb:ConditionCheckItem',
          'dynamodb:DeleteItem',
          'dynamodb:GetItem',
          'dynamodb:PutItem',
          'dynamodb:Query',
          'dynamodb:UpdateItem',
        ],
        'PLACE#*': [
          'dynamodb:ConditionCheckItem',
          'dynamodb:GetItem',
          'dynamodb:PutItem',
        ],
        'PLACELOOKUP#*': ['dynamodb:GetItem', 'dynamodb:PutItem'],
        'STATION#*': [
          'dynamodb:GetItem',
          'dynamodb:PutItem',
          'dynamodb:UpdateItem',
        ],
        'RENT,RENT#*': ['dynamodb:GetItem', 'dynamodb:Query'],
        'COMMUTE#*': [
          'dynamodb:DeleteItem',
          'dynamodb:GetItem',
          'dynamodb:PutItem',
          'dynamodb:Query',
        ],
        // C7's shared OneMap call budget: both callers count their calls.
        'RATE#*': ['dynamodb:UpdateItem'],
      },
      // The worker only ends claims: it cannot read a group, a place or a rent
      // snapshot, and cannot delete the pair it failed to route.
      CommuteWorker: {
        'COMMUTE#*': ['dynamodb:UpdateItem'],
        'RATE#*': ['dynamodb:UpdateItem'],
      },
    },
  );
});

test('the producer can only send commute jobs and the worker only consume them', () => {
  const template = synthesize('dev');
  const sqs = Object.fromEntries(
    Object.entries(allowedByRole(template)).map(([role, statements]) => [
      role,
      statements
        .filter((statement) =>
          actions(statement).some((action) => action.startsWith('sqs:')),
        )
        .flatMap((statement) => {
          assert.notEqual(statement.Resource, '*');
          return actions(statement);
        }),
    ]),
  );
  assert.deepEqual(sqs, {
    OneMapTokenRefresh: [],
    HttpHandler: [
      'sqs:GetQueueAttributes',
      'sqs:GetQueueUrl',
      'sqs:SendMessage',
    ],
    CommuteWorker: [
      'sqs:ChangeMessageVisibility',
      'sqs:DeleteMessage',
      'sqs:GetQueueAttributes',
      'sqs:GetQueueUrl',
      'sqs:ReceiveMessage',
    ],
  });
  template.hasResourceProperties('AWS::SQS::Queue', {
    SqsManagedSseEnabled: true,
    RedrivePolicy: Match.objectLike({ maxReceiveCount: 3 }),
  });
});

test('the commute worker drains the queue one pair at a time', () => {
  const template = synthesize('dev');
  template.resourceCountIs('AWS::Lambda::EventSourceMapping', 1);
  template.hasResourceProperties('AWS::Lambda::EventSourceMapping', {
    BatchSize: 1,
    // Resource concurrency complements the shared DynamoDB call budget.
    ScalingConfig: { MaximumConcurrency: 3 },
    // Without this, one retried pair would redeliver its whole batch.
    FunctionResponseTypes: ['ReportBatchItemFailures'],
  });
  // Reserved concurrency would be the alternative, and a new account's Lambda
  // quota cannot satisfy it (docs/backend-design.md): deployment would fail.
  for (const fn of Object.values(
    template.findResources('AWS::Lambda::Function'),
  )) {
    assert.equal(fn.Properties.ReservedConcurrentExecutions, undefined);
  }
});

test('a worker invocation cannot outlive the visibility timeout of its message', () => {
  const template = synthesize('dev');
  const worker = Object.values(
    template.findResources('AWS::Lambda::Function'),
  ).find(
    (fn) =>
      fn.Properties.Handler === 'flatsplit_api.handlers.commute_worker.handler',
  );
  assert.ok(worker, 'the commute worker was not synthesized');
  const jobQueue = Object.values(
    template.findResources('AWS::SQS::Queue'),
  ).find((queue) => queue.Properties.RedrivePolicy !== undefined);
  assert.ok(jobQueue);
  assert.ok(
    worker.Properties.Timeout < jobQueue.Properties.VisibilityTimeout,
    'a redelivery could race an invocation that is still routing',
  );
  // The worker recognises its own last attempt, so both must read one number.
  assert.equal(
    worker.Properties.Environment.Variables.COMMUTE_MAX_RECEIVES,
    String(jobQueue.Properties.RedrivePolicy.maxReceiveCount),
  );
});

test('the OneMap token is refreshed every 12 hours by a schedule, not rotation', () => {
  const template = synthesize('dev');
  // Secrets Manager rotation would run testSecret during every deploy.
  template.resourceCountIs('AWS::SecretsManager::RotationSchedule', 0);
  const functions = template.findResources('AWS::Lambda::Function', {
    Properties: {
      Handler: 'flatsplit_api.handlers.onemap_token_refresh.handler',
    },
  });
  const [refreshId] = Object.keys(functions);
  assert.ok(refreshId);
  template.hasResourceProperties('AWS::Lambda::Function', {
    Handler: 'flatsplit_api.handlers.onemap_token_refresh.handler',
    Runtime: 'python3.13',
    Architectures: ['arm64'],
  });
  template.hasResourceProperties('AWS::Events::Rule', {
    ScheduleExpression: 'rate(12 hours)',
    Targets: [Match.objectLike({ Arn: { 'Fn::GetAtt': [refreshId, 'Arn'] } })],
  });
});

/** Each IAM statement with the role it is attached to. */
function statements(template: Template): { role: string; s: Statement }[] {
  return Object.values(template.findResources('AWS::IAM::Policy')).flatMap(
    (policy) =>
      (policy.Properties.PolicyDocument.Statement as Statement[]).map((s) => ({
        role: JSON.stringify(policy.Properties.Roles),
        s,
      })),
  );
}

test('only the refresh Lambda can read the OneMap account login', () => {
  const template = synthesize('dev');
  const ids = Object.keys(
    template.findResources('AWS::SecretsManager::Secret'),
  );
  const credentials = ids.find((id) => id.includes('OneMapCredentials'));
  const token = ids.find((id) => id.includes('OneMapToken'));
  assert.ok(credentials && token);
  const all = statements(template);

  const readers = all.filter(({ s }) =>
    JSON.stringify(s.Resource).includes(credentials),
  );
  assert.equal(readers.length, 1);
  assert.match(readers[0].role, /OneMapTokenRefresh/);
  assert.deepEqual([readers[0].s.Action].flat().sort(), [
    'secretsmanager:DescribeSecret',
    'secretsmanager:GetSecretValue',
  ]);

  // Its only write is a new token value: no UpdateSecret, no stage moves and
  // none of rotation's account-wide GetRandomPassword.
  const refresh = all.filter(({ role }) => role.includes('OneMapTokenRefresh'));
  const writes = refresh.filter(({ s }) =>
    [s.Action].flat().some((action) => !/Get|Describe|logs:/.test(action)),
  );
  assert.equal(writes.length, 1);
  assert.deepEqual([writes[0].s.Action].flat(), [
    'secretsmanager:PutSecretValue',
  ]);
  assert.ok(JSON.stringify(writes[0].s.Resource).includes(token));
  assert.ok(!refresh.some(({ s }) => JSON.stringify(s.Resource) === '"*"'));
});
