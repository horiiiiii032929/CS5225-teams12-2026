import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { App, RemovalPolicy, Stack } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { AttributeType, Table } from 'aws-cdk-lib/aws-dynamodb';
import { Api } from '../src/api.js';

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

test('table access is scoped per item type, with rent read-only', () => {
  const policies = synthesize('dev').findResources('AWS::IAM::Policy');
  const dynamo = Object.values(policies)
    .flatMap(
      (policy) =>
        policy.Properties.PolicyDocument.Statement as {
          Action: string | string[];
          Condition?: Record<string, Record<string, Record<string, string[]>>>;
        }[],
    )
    .filter((statement) =>
      [statement.Action].flat().some((a) => a.startsWith('dynamodb:')),
    );

  const byPrefix = Object.fromEntries(
    dynamo.map((statement) => [
      statement.Condition?.['ForAllValues:StringLike']?.[
        'dynamodb:LeadingKeys'
      ]?.join(','),
      [statement.Action].flat().sort(),
    ]),
  );
  // Keying by prefix silently drops a duplicate, which would hide a statement
  // from the comparison below. Fail instead if two statements share a prefix.
  assert.equal(
    Object.keys(byPrefix).length,
    dynamo.length,
    'two DynamoDB statements share a LeadingKeys prefix',
  );
  assert.deepEqual(byPrefix, {
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
  });
});

test('the search producer cannot receive or delete commute jobs', () => {
  const template = synthesize('dev');
  const policies = template.findResources('AWS::IAM::Policy');
  const statements = Object.values(policies).flatMap(
    (policy) =>
      policy.Properties.PolicyDocument.Statement as {
        Effect: string;
        Action: string | string[];
        Resource: unknown;
      }[],
  );
  const allowed = statements.filter((s) => s.Effect === 'Allow');
  const sqs = allowed.filter((s) =>
    [s.Action].flat().some((action) => action.startsWith('sqs:')),
  );
  assert.equal(sqs.length, 1);
  assert.deepEqual([sqs[0]!.Action].flat().sort(), [
    'sqs:GetQueueAttributes',
    'sqs:GetQueueUrl',
    'sqs:SendMessage',
  ]);
  assert.notEqual(sqs[0]!.Resource, '*');
  template.hasResourceProperties('AWS::SQS::Queue', {
    SqsManagedSseEnabled: true,
    RedrivePolicy: Match.objectLike({ maxReceiveCount: 3 }),
  });
});

test('the OneMap token rotates every 12 hours, not on deploy', () => {
  const template = synthesize('dev');
  template.resourceCountIs('AWS::SecretsManager::RotationSchedule', 1);
  template.hasResourceProperties('AWS::SecretsManager::RotationSchedule', {
    RotationRules: { ScheduleExpression: 'rate(12 hours)' },
    RotateImmediatelyOnUpdate: false,
  });
  template.hasResourceProperties('AWS::Lambda::Function', {
    Handler: 'flatsplit_api.handlers.onemap_rotation.handler',
    Runtime: 'python3.13',
    Architectures: ['arm64'],
  });
});

interface Statement {
  Action: string | string[];
  Resource: unknown;
}

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

test('only the rotation Lambda can read the OneMap account login', () => {
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
  assert.match(readers[0].role, /OneMapTokenRotation/);
  assert.deepEqual([readers[0].s.Action].flat().sort(), [
    'secretsmanager:DescribeSecret',
    'secretsmanager:GetSecretValue',
  ]);

  // Its only write access is the rotation actions on the token secret.
  const writes = all.filter(
    ({ role, s }) =>
      role.includes('OneMapTokenRotation') &&
      [s.Action].flat().some((action) => /Put|Update/.test(action)),
  );
  assert.equal(writes.length, 1);
  assert.ok(JSON.stringify(writes[0].s.Resource).includes(token));
});
