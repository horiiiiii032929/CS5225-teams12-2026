import { Duration, RemovalPolicy, Stack } from 'aws-cdk-lib';
import { HttpApi, HttpStage } from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import type { ITable } from 'aws-cdk-lib/aws-dynamodb';
import { PolicyStatement } from 'aws-cdk-lib/aws-iam';
import { Architecture, Function, Runtime } from 'aws-cdk-lib/aws-lambda';
import { LogGroup, RetentionDays } from 'aws-cdk-lib/aws-logs';
import { Secret } from 'aws-cdk-lib/aws-secretsmanager';
import { Queue, QueueEncryption } from 'aws-cdk-lib/aws-sqs';
import { Construct } from 'constructs';
import { pythonApiCode } from './python-code.js';

export interface ApiProps {
  readonly stage: string;
  readonly removalPolicy: RemovalPolicy;
  /** Single table from docs/api-contract.md. */
  readonly table: ITable;
}

/** HTTP API whose $default route invokes the Powertools resolver Lambda. */
export class Api extends Construct {
  readonly httpApi: HttpApi;
  /** Hostname CloudFront uses as the /api/* origin. */
  readonly originDomain: string;
  /** Rotated automatically from `onemapCredentialsSecretName` (#72). */
  readonly onemapTokenSecretName: string;
  /** OneMap account email/password, put in once by hand; never in the repo. */
  readonly onemapCredentialsSecretName: string;
  /** Shared producer queue; #15 attaches its worker to this queue. */
  readonly commuteJobsQueue: Queue;
  /** Holds only what the worker could not account for; #27 alarms on it. */
  readonly commuteDeadLetterQueue: Queue;
  /** Where the OneMap token warning is logged; #27 alarms on it. */
  readonly httpHandlerLogGroup: LogGroup;

  constructor(scope: Construct, id: string, props: ApiProps) {
    super(scope, id);

    // The OneMap token is a three-day JWT that OneMap only issues from the
    // account's email and password (#3), with no refresh endpoint. Keeping it
    // in Secrets Manager lets /places proxy OneMap server-side without the
    // token ever reaching the browser (docs/backend-design.md). It was
    // replaced by hand until #72 and lapsed for a week when nobody did, so a
    // rotation Lambda now logs in with a separate credentials secret.
    const onemapToken = new Secret(this, 'OneMapToken', {
      description: `OneMap API token for FlatSplit ${props.stage}; rotated every 12 hours from the OneMap credentials secret`,
      removalPolicy: props.removalPolicy,
    });
    this.onemapTokenSecretName = onemapToken.secretName;

    // CDK seeds a random placeholder, which the rotation rejects as not
    // {"email", "password"} JSON until the account holder puts the real
    // credentials in once (runbook in docs/aws-dev-handoff.md).
    const onemapCredentials = new Secret(this, 'OneMapCredentials', {
      description: `OneMap account login for FlatSplit ${props.stage} token rotation: {"email": ..., "password": ...}`,
      removalPolicy: props.removalPolicy,
    });
    this.onemapCredentialsSecretName = onemapCredentials.secretName;

    const onemapRotation = new Function(this, 'OneMapTokenRotation', {
      runtime: Runtime.PYTHON_3_13,
      architecture: Architecture.ARM_64,
      code: pythonApiCode(),
      handler: 'flatsplit_api.handlers.onemap_rotation.handler',
      memorySize: 128,
      timeout: Duration.seconds(30),
      environment: {
        POWERTOOLS_SERVICE_NAME: 'flatsplit-onemap-rotation',
        POWERTOOLS_LOG_LEVEL: 'INFO',
        ONEMAP_CREDENTIALS_SECRET_NAME: onemapCredentials.secretName,
      },
      logGroup: new LogGroup(this, 'OneMapTokenRotationLogs', {
        retention: RetentionDays.ONE_MONTH,
        removalPolicy: props.removalPolicy,
      }),
    });
    // Only the rotation Lambda can read the account login. The schedule grants
    // it the four rotation actions on the token secret alone.
    onemapCredentials.grantRead(onemapRotation);
    onemapToken.addRotationSchedule('Rotation', {
      rotationLambda: onemapRotation,
      // Tokens last three days; rotating every 12 hours leaves several retries
      // before the current one expires if a login fails.
      automaticallyAfter: Duration.hours(12),
      // A deploy must not rotate before the credentials have been put in.
      rotateImmediatelyOnUpdate: false,
    });

    const commuteDlq = new Queue(this, 'CommuteDlq', {
      encryption: QueueEncryption.SQS_MANAGED,
      enforceSSL: true,
      retentionPeriod: Duration.days(14),
      removalPolicy: props.removalPolicy,
    });
    this.commuteDeadLetterQueue = commuteDlq;
    this.commuteJobsQueue = new Queue(this, 'CommuteJobs', {
      encryption: QueueEncryption.SQS_MANAGED,
      enforceSSL: true,
      visibilityTimeout: Duration.minutes(3),
      retentionPeriod: Duration.days(4),
      deadLetterQueue: { queue: commuteDlq, maxReceiveCount: 3 },
      removalPolicy: props.removalPolicy,
    });

    const handlerLogs = new LogGroup(this, 'HttpHandlerLogs', {
      retention: RetentionDays.ONE_WEEK,
      removalPolicy: props.removalPolicy,
    });
    this.httpHandlerLogGroup = handlerLogs;

    const handler = new Function(this, 'HttpHandler', {
      runtime: Runtime.PYTHON_3_13,
      architecture: Architecture.ARM_64,
      code: pythonApiCode(),
      handler: 'flatsplit_api.handlers.http.handler',
      memorySize: 256,
      timeout: Duration.seconds(30),
      environment: {
        POWERTOOLS_SERVICE_NAME: 'flatsplit-api',
        POWERTOOLS_LOG_LEVEL: 'INFO',
        STAGE: props.stage,
        ONEMAP_SECRET_NAME: onemapToken.secretName,
        TABLE_NAME: props.table.tableName,
        COMMUTE_QUEUE_URL: this.commuteJobsQueue.queueUrl,
      },
      logGroup: handlerLogs,
    });

    onemapToken.grantRead(handler);
    this.commuteJobsQueue.grantSendMessages(handler);

    // Transactions are authorised per item action. The API writes groups,
    // commute claims and the place and station records a lookup creates (#14),
    // and can only read validated rent snapshots. A pinned station may gain
    // line-code aliases but is never deleted through the API.
    handler.addToRolePolicy(
      new PolicyStatement({
        actions: [
          'dynamodb:Query',
          'dynamodb:GetItem',
          'dynamodb:PutItem',
          'dynamodb:UpdateItem',
          'dynamodb:DeleteItem',
          'dynamodb:ConditionCheckItem',
        ],
        resources: [props.table.tableArn],
        conditions: {
          'ForAllValues:StringLike': { 'dynamodb:LeadingKeys': ['GROUP#*'] },
          Null: { 'dynamodb:LeadingKeys': 'false' },
        },
      }),
    );
    handler.addToRolePolicy(
      new PolicyStatement({
        actions: [
          'dynamodb:GetItem',
          'dynamodb:PutItem',
          'dynamodb:ConditionCheckItem',
        ],
        resources: [props.table.tableArn],
        conditions: {
          'ForAllValues:StringLike': { 'dynamodb:LeadingKeys': ['PLACE#*'] },
          Null: { 'dynamodb:LeadingKeys': 'false' },
        },
      }),
    );
    // The query cache needs its own statement: the prefix above is the literal
    // `PLACE#`, so it does not match `PLACELOOKUP#`. Without this, `/places`
    // would be denied on the GetItem it makes before reaching OneMap and every
    // lookup would return 503. Read and write only — a cache entry is replaced
    // by a whole new item and expires by ttl, never updated or deleted.
    handler.addToRolePolicy(
      new PolicyStatement({
        actions: ['dynamodb:GetItem', 'dynamodb:PutItem'],
        resources: [props.table.tableArn],
        conditions: {
          'ForAllValues:StringLike': {
            'dynamodb:LeadingKeys': ['PLACELOOKUP#*'],
          },
          Null: { 'dynamodb:LeadingKeys': 'false' },
        },
      }),
    );
    handler.addToRolePolicy(
      new PolicyStatement({
        actions: [
          'dynamodb:GetItem',
          'dynamodb:PutItem',
          'dynamodb:UpdateItem',
        ],
        resources: [props.table.tableArn],
        conditions: {
          'ForAllValues:StringLike': { 'dynamodb:LeadingKeys': ['STATION#*'] },
          Null: { 'dynamodb:LeadingKeys': 'false' },
        },
      }),
    );
    handler.addToRolePolicy(
      new PolicyStatement({
        actions: ['dynamodb:GetItem', 'dynamodb:Query'],
        resources: [props.table.tableArn],
        conditions: {
          'ForAllValues:StringLike': {
            'dynamodb:LeadingKeys': ['RENT', 'RENT#*'],
          },
          Null: { 'dynamodb:LeadingKeys': 'false' },
        },
      }),
    );
    handler.addToRolePolicy(
      new PolicyStatement({
        actions: [
          'dynamodb:GetItem',
          'dynamodb:Query',
          'dynamodb:PutItem',
          'dynamodb:DeleteItem',
        ],
        resources: [props.table.tableArn],
        conditions: {
          'ForAllValues:StringLike': {
            'dynamodb:LeadingKeys': ['COMMUTE#*'],
          },
          Null: { 'dynamodb:LeadingKeys': 'false' },
        },
      }),
    );

    this.httpApi = new HttpApi(this, 'HttpApi', {
      description: `FlatSplit ${props.stage} API`,
      createDefaultStage: false,
      defaultIntegration: new HttpLambdaIntegration('Handler', handler),
    });

    // The isolated capacity experiment must admit its 50 req/s workload.
    // Shared application stages retain the prototype abuse/cost limit.
    new HttpStage(this, 'DefaultStage', {
      httpApi: this.httpApi,
      stageName: '$default',
      autoDeploy: true,
      throttle:
        props.stage === 'eval'
          ? { rateLimit: 100, burstLimit: 200 }
          : { rateLimit: 20, burstLimit: 40 },
    });

    const stack = Stack.of(this);
    this.originDomain = `${this.httpApi.apiId}.execute-api.${stack.region}.${stack.urlSuffix}`;
  }
}
