import { Duration, RemovalPolicy, Stack } from 'aws-cdk-lib';
import { HttpApi, HttpStage } from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import type { ITable } from 'aws-cdk-lib/aws-dynamodb';
import { PolicyStatement } from 'aws-cdk-lib/aws-iam';
import { Architecture, Function, Runtime } from 'aws-cdk-lib/aws-lambda';
import { LogGroup, RetentionDays } from 'aws-cdk-lib/aws-logs';
import { Secret } from 'aws-cdk-lib/aws-secretsmanager';
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
  /** Rotate this by hand; see onemapToken below. */
  readonly onemapTokenSecretName: string;

  constructor(scope: Construct, id: string, props: ApiProps) {
    super(scope, id);

    // The OneMap token is a three-day JWT with no automatic renewal (#3), so
    // it cannot be generated here. CDK seeds a random placeholder and the real
    // token is put in by hand until a refresh path exists (#27). Keeping it in
    // Secrets Manager is what lets /places proxy OneMap server-side without
    // the token ever reaching the browser (docs/backend-design.md).
    const onemapToken = new Secret(this, 'OneMapToken', {
      description: `OneMap API token for FlatSplit ${props.stage} — rotate manually every 3 days`,
      removalPolicy: props.removalPolicy,
    });
    this.onemapTokenSecretName = onemapToken.secretName;

    const handler = new Function(this, 'HttpHandler', {
      runtime: Runtime.PYTHON_3_13,
      architecture: Architecture.ARM_64,
      code: pythonApiCode(),
      handler: 'flatsplit_api.handlers.http.handler',
      memorySize: 256,
      timeout: Duration.seconds(10),
      environment: {
        POWERTOOLS_SERVICE_NAME: 'flatsplit-api',
        POWERTOOLS_LOG_LEVEL: 'INFO',
        STAGE: props.stage,
        ONEMAP_SECRET_NAME: onemapToken.secretName,
        TABLE_NAME: props.table.tableName,
      },
      logGroup: new LogGroup(this, 'HttpHandlerLogs', {
        retention: RetentionDays.ONE_WEEK,
        removalPolicy: props.removalPolicy,
      }),
    });

    onemapToken.grantRead(handler);

    // Group APIs (#12) read and write only group partitions and read places.
    // Rent and commute partitions belong to the data pipeline. Transactions are
    // authorised per item action, so TransactWriteItems needs no action of its own.
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
        },
      }),
    );
    handler.addToRolePolicy(
      new PolicyStatement({
        actions: ['dynamodb:GetItem', 'dynamodb:ConditionCheckItem'],
        resources: [props.table.tableArn],
        conditions: {
          'ForAllValues:StringLike': { 'dynamodb:LeadingKeys': ['PLACE#*'] },
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
