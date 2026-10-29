import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { App, RemovalPolicy, Stack } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { Code } from 'aws-cdk-lib/aws-lambda';
import { RentIngestion } from '../src/rent-ingestion.js';

function synthesize(removalPolicy = RemovalPolicy.DESTROY): Template {
  const outdir = mkdtempSync(join(tmpdir(), 'flatsplit-rent-test-'));
  try {
    const stack = new Stack(new App({ outdir }), 'Test');
    new RentIngestion(stack, 'RentIngestion', {
      removalPolicy,
      code: Code.fromInline('def handler(event, context): return {}'),
    });
    return Template.fromStack(stack);
  } finally {
    rmSync(outdir, { recursive: true, force: true });
  }
}

test('raw rental evidence is private, encrypted and versioned', () => {
  const template = synthesize();
  template.hasResourceProperties('AWS::S3::Bucket', {
    BucketEncryption: {
      ServerSideEncryptionConfiguration: [
        {
          ServerSideEncryptionByDefault: { SSEAlgorithm: 'AES256' },
        },
      ],
    },
    PublicAccessBlockConfiguration: {
      BlockPublicAcls: true,
      BlockPublicPolicy: true,
      IgnorePublicAcls: true,
      RestrictPublicBuckets: true,
    },
    VersioningConfiguration: { Status: 'Enabled' },
  });
  template.hasResourceProperties('AWS::S3::BucketPolicy', {
    PolicyDocument: {
      Statement: Match.arrayWith([
        Match.objectLike({
          Effect: 'Deny',
          Principal: { AWS: '*' },
          Condition: { Bool: { 'aws:SecureTransport': 'false' } },
        }),
      ]),
    },
  });
});

test('ingestion Lambda has bounded resources and pointer read plus evidence write access', () => {
  const template = synthesize();
  template.hasResourceProperties('AWS::Lambda::Function', {
    Architectures: ['arm64'],
    Runtime: 'python3.13',
    Handler: 'flatsplit_api.handlers.ingest_rent.handler',
    MemorySize: 1024,
    Timeout: 600,
    Environment: {
      Variables: Match.objectLike({
        POWERTOOLS_SERVICE_NAME: 'flatsplit-rent-ingestion',
        RENT_RAW_BUCKET: Match.anyValue(),
      }),
    },
  });

  const policies = template.findResources('AWS::IAM::Policy');
  const statements = Object.values(policies).flatMap(
    (policy) =>
      policy.Properties.PolicyDocument.Statement as {
        Effect: string;
        Action: string | string[];
        Resource: unknown;
      }[],
  );
  const s3Actions = statements
    .filter((statement) =>
      [statement.Action].flat().some((action) => action.startsWith('s3:')),
    )
    .flatMap((statement) => [statement.Action].flat());
  assert(s3Actions.includes('s3:PutObject'));
  assert(s3Actions.includes('s3:GetObject'));
  assert(s3Actions.includes('s3:ListBucket'));
  assert.deepEqual([...new Set(s3Actions)].sort(), [
    's3:GetObject',
    's3:ListBucket',
    's3:PutObject',
  ]);
  assert(!s3Actions.includes('s3:DeleteObject'));
});

test('ingestion runs monthly on the third at 03:00 Singapore time', () => {
  const template = synthesize();
  template.hasResourceProperties('AWS::Events::Rule', {
    ScheduleExpression: 'cron(0 19 2 * ? *)',
    State: 'ENABLED',
    Targets: [{ Arn: Match.anyValue() }],
  });
});

test('production retains the raw evidence bucket', () => {
  const resources = synthesize(RemovalPolicy.RETAIN).findResources(
    'AWS::S3::Bucket',
  );
  const bucket = Object.values(resources)[0];
  assert.equal(bucket?.DeletionPolicy, 'Retain');
  assert.equal(bucket?.UpdateReplacePolicy, 'Retain');
});
