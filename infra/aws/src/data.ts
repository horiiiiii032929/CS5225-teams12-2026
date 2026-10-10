import { RemovalPolicy } from 'aws-cdk-lib';
import {
  AttributeType,
  BillingMode,
  Table,
  type ITable,
} from 'aws-cdk-lib/aws-dynamodb';
import { Construct } from 'constructs';

export interface DataProps {
  readonly removalPolicy: RemovalPolicy;
}

/** Single DynamoDB table; item layout is documented in docs/backend-design.md. */
export class Data extends Construct {
  readonly table: ITable;

  constructor(scope: Construct, id: string, props: DataProps) {
    super(scope, id);

    this.table = new Table(this, 'Table', {
      partitionKey: { name: 'pk', type: AttributeType.STRING },
      sortKey: { name: 'sk', type: AttributeType.STRING },
      billingMode: BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: 'ttl',
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      removalPolicy: props.removalPolicy,
    });
  }
}
