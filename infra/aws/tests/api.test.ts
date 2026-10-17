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

test('the API Lambda knows its table', () => {
  synthesize('dev').hasResourceProperties('AWS::Lambda::Function', {
    Handler: 'flatsplit_api.handlers.http.handler',
    Environment: {
      Variables: Match.objectLike({ TABLE_NAME: { Ref: Match.anyValue() } }),
    },
  });
});

test('table access is limited to group writes and place reads', () => {
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
  assert.deepEqual(byPrefix, {
    'GROUP#*': [
      'dynamodb:ConditionCheckItem',
      'dynamodb:DeleteItem',
      'dynamodb:GetItem',
      'dynamodb:PutItem',
      'dynamodb:Query',
      'dynamodb:UpdateItem',
    ],
    'PLACE#*': ['dynamodb:ConditionCheckItem', 'dynamodb:GetItem'],
  });
});
