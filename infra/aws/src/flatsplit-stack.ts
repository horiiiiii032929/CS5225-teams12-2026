import { CfnOutput, RemovalPolicy, Stack, type StackProps } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { Api } from './api.js';
import { Data } from './data.js';
import { Ops } from './ops.js';
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
    const api = new Api(this, 'Api', { stage: props.stage, removalPolicy });
    const web = new Web(this, 'Web', {
      apiOriginDomain: api.originDomain,
      removalPolicy,
    });
    if (props.budgetEmail) {
      new Ops(this, 'Ops', { budgetEmail: props.budgetEmail });
    }

    new CfnOutput(this, 'SiteUrl', {
      value: `https://${web.distribution.distributionDomainName}`,
    });
    new CfnOutput(this, 'ApiUrl', { value: api.httpApi.apiEndpoint });
    new CfnOutput(this, 'TableName', { value: data.table.tableName });
  }
}
