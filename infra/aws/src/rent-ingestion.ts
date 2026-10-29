import { Duration, RemovalPolicy } from 'aws-cdk-lib';
import { Rule, Schedule } from 'aws-cdk-lib/aws-events';
import { LambdaFunction } from 'aws-cdk-lib/aws-events-targets';
import { Architecture, Code, Function, Runtime } from 'aws-cdk-lib/aws-lambda';
import { PolicyStatement } from 'aws-cdk-lib/aws-iam';
import type { ITable } from 'aws-cdk-lib/aws-dynamodb';
import { LogGroup, RetentionDays } from 'aws-cdk-lib/aws-logs';
import {
  BlockPublicAccess,
  Bucket,
  BucketEncryption,
  type IBucket,
} from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';
import { pythonApiCode } from './python-code.js';

export interface RentIngestionProps {
  readonly removalPolicy: RemovalPolicy;
  /** Test seam that avoids bundling the Python workspace during assertions. */
  readonly code?: Code;
  /** Shared table used for versioned rent summaries and the current pointer. */
  readonly table?: ITable;
}

/** Raw HDB rental evidence and the Lambda that validates each source export. */
export class RentIngestion extends Construct {
  readonly bucket: IBucket;
  readonly handler: Function;
  readonly schedule: Rule;

  constructor(scope: Construct, id: string, props: RentIngestionProps) {
    super(scope, id);

    this.bucket = new Bucket(this, 'RawSnapshots', {
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      encryption: BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      versioned: true,
      removalPolicy: props.removalPolicy,
      autoDeleteObjects: props.removalPolicy === RemovalPolicy.DESTROY,
    });

    this.handler = new Function(this, 'Handler', {
      runtime: Runtime.PYTHON_3_13,
      architecture: Architecture.ARM_64,
      code: props.code ?? pythonApiCode(),
      handler: 'flatsplit_api.handlers.ingest_rent.handler',
      memorySize: 1024,
      timeout: Duration.minutes(10),
      environment: {
        POWERTOOLS_SERVICE_NAME: 'flatsplit-rent-ingestion',
        POWERTOOLS_LOG_LEVEL: 'INFO',
        RENT_RAW_BUCKET: this.bucket.bucketName,
        ...(props.table ? { RENT_TABLE_NAME: props.table.tableName } : {}),
      },
      logGroup: new LogGroup(this, 'HandlerLogs', {
        retention: RetentionDays.ONE_WEEK,
        removalPolicy: props.removalPolicy,
      }),
    });

    // The handler reads only the current pointer to prevent an older valid
    // export from replacing a newer snapshot. All evidence writes are append-only.
    this.handler.addToRolePolicy(
      new PolicyStatement({
        actions: ['s3:ListBucket'],
        resources: [this.bucket.bucketArn],
        conditions: {
          StringLike: { 's3:prefix': ['raw/current.json'] },
        },
      }),
    );
    if (props.table) {
      this.handler.addToRolePolicy(
        new PolicyStatement({
          actions: ['dynamodb:PutItem'],
          resources: [props.table.tableArn],
          conditions: {
            'ForAllValues:StringLike': {
              'dynamodb:LeadingKeys': ['RENT', 'RENT#*'],
            },
          },
        }),
      );
    }
    this.handler.addToRolePolicy(
      new PolicyStatement({
        actions: ['s3:GetObject'],
        resources: [this.bucket.arnForObjects('raw/current.json')],
      }),
    );
    this.handler.addToRolePolicy(
      new PolicyStatement({
        actions: ['s3:PutObject'],
        resources: [
          this.bucket.arnForObjects('raw/*'),
          this.bucket.arnForObjects('rejected/*'),
        ],
      }),
    );
    this.schedule = new Rule(this, 'MonthlySchedule', {
      description:
        'Run HDB rental snapshot ingestion on the third of each month.',
      schedule: Schedule.expression('cron(0 19 2 * ? *)'),
      targets: [new LambdaFunction(this.handler)],
    });
  }
}
