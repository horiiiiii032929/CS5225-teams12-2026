import { Duration, RemovalPolicy, Stack } from 'aws-cdk-lib';
import { HttpApi, HttpStage } from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import type { ITable } from 'aws-cdk-lib/aws-dynamodb';
import { Rule, Schedule } from 'aws-cdk-lib/aws-events';
import { LambdaFunction } from 'aws-cdk-lib/aws-events-targets';
import { PolicyStatement } from 'aws-cdk-lib/aws-iam';
import { Architecture, Function, Runtime } from 'aws-cdk-lib/aws-lambda';
import { SqsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import { LogGroup, RetentionDays } from 'aws-cdk-lib/aws-logs';
import { Secret } from 'aws-cdk-lib/aws-secretsmanager';
import { Queue, QueueEncryption } from 'aws-cdk-lib/aws-sqs';
import { Construct } from 'constructs';
import { pythonApiCode } from './python-code.js';

/**
 * Deliveries before a job is dead-lettered. The worker recognises its own
 * final attempt from this number, so the queue and the handler must read the
 * same one: see COMMUTE_MAX_RECEIVES below.
 */
const COMMUTE_MAX_RECEIVES = 3;

/**
 * Concurrent commute workers. The routing rate is bounded by this alone: #3
 * measured OneMap routing p50 at 861 ms, so three in flight is ~209 calls/min
 * against OneMap's 300/min cap, leaving /places its share. Set on the event
 * source rather than as reserved concurrency, which a new account's Lambda
 * quota cannot satisfy (docs/backend-design.md); 2 is the lowest CDK accepts.
 */
const COMMUTE_WORKER_CONCURRENCY = 3;

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
  /** Kept valid every 15 minutes from `onemapCredentialsSecretName` (#72). */
  readonly onemapTokenSecretName: string;
  /** OneMap account email/password, put in once by hand; never in the repo. */
  readonly onemapCredentialsSecretName: string;
  /** Scheduled token refresh; #27's topic alarms on its errors. */
  readonly onemapTokenRefresh: Function;
  /** Producer queue, written by the API and drained by the commute worker. */
  readonly commuteJobsQueue: Queue;
  /** Holds only what the worker could not account for; #27 alarms on it. */
  readonly commuteDeadLetterQueue: Queue;
  /** Where the OneMap token warning is logged; #27 alarms on it. */
  readonly httpHandlerLogGroup: LogGroup;
  /** Routing token warnings share the operational alarm with the API. */
  readonly commuteWorkerLogGroup: LogGroup;

  constructor(scope: Construct, id: string, props: ApiProps) {
    super(scope, id);

    // The OneMap token is a three-day JWT that OneMap only issues from the
    // account's email and password (#3), with no refresh endpoint. Keeping it
    // in Secrets Manager lets /places proxy OneMap server-side without the
    // token ever reaching the browser (docs/backend-design.md). It was
    // replaced by hand until #72 and lapsed for days when nobody did, so a
    // scheduled Lambda now logs in with a separate credentials secret.
    const onemapToken = new Secret(this, 'OneMapToken', {
      description: `OneMap API token for FlatSplit ${props.stage}; kept valid every 15 minutes from the OneMap credentials secret`,
      removalPolicy: props.removalPolicy,
    });
    this.onemapTokenSecretName = onemapToken.secretName;

    // CDK seeds a random placeholder, which the refresh rejects as not
    // {"email", "password"} JSON until the account holder puts the real
    // credentials in once (runbook in docs/aws-dev-handoff.md).
    const onemapCredentials = new Secret(this, 'OneMapCredentials', {
      description: `OneMap account login for FlatSplit ${props.stage} token refresh: {"email": ..., "password": ...}`,
      removalPolicy: props.removalPolicy,
    });
    this.onemapCredentialsSecretName = onemapCredentials.secretName;

    // A schedule, not Secrets Manager rotation: rotation runs its testSecret
    // step during every deployment, so a deploy could fail on a placeholder
    // before the credentials exist. A deploy never invokes this function.
    this.onemapTokenRefresh = new Function(this, 'OneMapTokenRefresh', {
      runtime: Runtime.PYTHON_3_13,
      architecture: Architecture.ARM_64,
      code: pythonApiCode(),
      handler: 'flatsplit_api.handlers.onemap_token_refresh.handler',
      memorySize: 128,
      timeout: Duration.seconds(30),
      // The next run is minutes away, and retrying would triple the logins
      // OneMap sees from a wrong password.
      retryAttempts: 0,
      environment: {
        POWERTOOLS_SERVICE_NAME: 'flatsplit-onemap-token-refresh',
        POWERTOOLS_LOG_LEVEL: 'INFO',
        ONEMAP_SECRET_NAME: onemapToken.secretName,
        ONEMAP_CREDENTIALS_SECRET_NAME: onemapCredentials.secretName,
      },
      logGroup: new LogGroup(this, 'OneMapTokenRefreshLogs', {
        retention: RetentionDays.ONE_MONTH,
        removalPolicy: props.removalPolicy,
      }),
    });
    // Only this function can read the account login, and its only write is a
    // new value for the token secret (no UpdateSecret, no version staging).
    // It reads the token to tell whether a login is due or returned it again.
    onemapCredentials.grantRead(this.onemapTokenRefresh);
    onemapToken.grantRead(this.onemapTokenRefresh);
    this.onemapTokenRefresh.addToRolePolicy(
      new PolicyStatement({
        actions: ['secretsmanager:PutSecretValue'],
        resources: [onemapToken.secretArn],
      }),
    );
    // OneMap only issues a new token once the old one expires, so this
    // interval bounds the outage at each expiry. Most runs only read the secret.
    new Rule(this, 'OneMapTokenRefreshSchedule', {
      schedule: Schedule.rate(Duration.minutes(15)),
      targets: [new LambdaFunction(this.onemapTokenRefresh)],
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
      deadLetterQueue: {
        queue: commuteDlq,
        maxReceiveCount: COMMUTE_MAX_RECEIVES,
      },
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

    // The queue's consumer (#15): one station-town pair per message. Its
    // timeout stays well inside the queue's 3-minute visibility timeout, so a
    // message is never redelivered while an invocation is still working on it.
    this.commuteWorkerLogGroup = new LogGroup(this, 'CommuteWorkerLogs', {
      retention: RetentionDays.ONE_WEEK,
      removalPolicy: props.removalPolicy,
    });
    const commuteWorker = new Function(this, 'CommuteWorker', {
      runtime: Runtime.PYTHON_3_13,
      architecture: Architecture.ARM_64,
      code: pythonApiCode(),
      handler: 'flatsplit_api.handlers.commute_worker.handler',
      memorySize: 256,
      timeout: Duration.seconds(60),
      environment: {
        POWERTOOLS_SERVICE_NAME: 'flatsplit-commute-worker',
        POWERTOOLS_LOG_LEVEL: 'INFO',
        STAGE: props.stage,
        ONEMAP_SECRET_NAME: onemapToken.secretName,
        TABLE_NAME: props.table.tableName,
        COMMUTE_MAX_RECEIVES: String(COMMUTE_MAX_RECEIVES),
      },
      logGroup: this.commuteWorkerLogGroup,
    });

    onemapToken.grantRead(commuteWorker);
    commuteWorker.addEventSource(
      new SqsEventSource(this.commuteJobsQueue, {
        // One pair per invocation: a batch would share one timeout and one
        // failure, and the worker has nothing to gain from a second pair.
        batchSize: 1,
        maxConcurrency: COMMUTE_WORKER_CONCURRENCY,
        // Without this a single retry would redeliver the whole batch.
        reportBatchItemFailures: true,
      }),
    );

    // The worker completes claims and does nothing else: it cannot read a
    // group, a place or a rent snapshot, cannot delete a claim, and cannot
    // enqueue work. Contract A9's write is an UpdateItem on the pair.
    commuteWorker.addToRolePolicy(
      new PolicyStatement({
        actions: ['dynamodb:UpdateItem'],
        resources: [props.table.tableArn],
        conditions: {
          'ForAllValues:StringLike': {
            'dynamodb:LeadingKeys': ['COMMUTE#*'],
          },
          Null: { 'dynamodb:LeadingKeys': 'false' },
        },
      }),
    );

    // C7's shared OneMap call budget: one counter item per minute, written by
    // every caller that spends quota. ADD and the TTL are both UpdateItem, and
    // neither role can read or delete another role's counters.
    for (const role of [handler, commuteWorker]) {
      role.addToRolePolicy(
        new PolicyStatement({
          actions: ['dynamodb:UpdateItem'],
          resources: [props.table.tableArn],
          conditions: {
            'ForAllValues:StringLike': {
              'dynamodb:LeadingKeys': ['RATE#*'],
            },
            Null: { 'dynamodb:LeadingKeys': 'false' },
          },
        }),
      );
    }

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
