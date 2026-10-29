import { CfnOutput, RemovalPolicy, Stack, type StackProps } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { CommuteAlarms } from './alarms.js';
import { Api } from './api.js';
import { Data } from './data.js';
import { Ops } from './ops.js';
import { RentIngestion } from './rent-ingestion.js';
import { Web } from './web.js';

export interface FlatSplitStackProps extends StackProps {
  readonly stage: string;
  /** Creates the account-wide cost budget when set; deploy it from one stage only. */
  readonly budgetEmail?: string;
}

export class FlatSplitStack extends Stack {
  constructor(scope: Construct, id: string, props: FlatSplitStackProps) {
    super(scope, id, props);

    const removalPolicy =
      props.stage === 'prod' ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY;

    const data = new Data(this, 'Data', { removalPolicy });
    const rentIngestion = new RentIngestion(this, 'RentIngestion', {
      removalPolicy,
    });
    const api = new Api(this, 'Api', {
      stage: props.stage,
      removalPolicy,
      table: data.table,
    });
    const web = new Web(this, 'Web', {
      apiOriginDomain: api.originDomain,
      removalPolicy,
    });
    // Alarms exist in every stage; only the account-wide budget is deployed
    // from one. The email is optional: an alarm with no subscriber still
    // shows in the console and still carries its state history.
    new CommuteAlarms(this, 'CommuteAlarms', {
      stage: props.stage,
      jobsQueue: api.commuteJobsQueue,
      deadLetterQueue: api.commuteDeadLetterQueue,
      apiLogGroup: api.httpHandlerLogGroup,
      alertEmail: props.budgetEmail,
    });
    if (props.budgetEmail) {
      new Ops(this, 'Ops', { budgetEmail: props.budgetEmail });
    }

    new CfnOutput(this, 'SiteUrl', {
      value: `https://${web.distribution.distributionDomainName}`,
    });
    new CfnOutput(this, 'ApiUrl', { value: api.httpApi.apiEndpoint });
    new CfnOutput(this, 'TableName', { value: data.table.tableName });
    new CfnOutput(this, 'RentRawBucketName', {
      value: rentIngestion.bucket.bucketName,
    });
    new CfnOutput(this, 'RentIngestionFunctionName', {
      value: rentIngestion.handler.functionName,
    });
    new CfnOutput(this, 'CommuteQueueUrl', {
      value: api.commuteJobsQueue.queueUrl,
    });
    new CfnOutput(this, 'OneMapTokenSecret', {
      value: api.onemapTokenSecretName,
    });
  }
}
