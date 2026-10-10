import { CfnBudget } from 'aws-cdk-lib/aws-budgets';
import { Construct } from 'constructs';

export interface OpsProps {
  readonly budgetEmail: string;
}

/** Monthly cost alerts at the thresholds in the preliminary report (US$20/50/100). */
export class Ops extends Construct {
  constructor(scope: Construct, id: string, props: OpsProps) {
    super(scope, id);

    new CfnBudget(this, 'MonthlyBudget', {
      budget: {
        budgetName: 'flatsplit-monthly',
        budgetType: 'COST',
        timeUnit: 'MONTHLY',
        budgetLimit: { amount: 100, unit: 'USD' },
      },
      notificationsWithSubscribers: [20, 50, 100].map((threshold) => ({
        notification: {
          notificationType: 'ACTUAL',
          comparisonOperator: 'GREATER_THAN',
          threshold,
          thresholdType: 'ABSOLUTE_VALUE',
        },
        subscribers: [
          { subscriptionType: 'EMAIL', address: props.budgetEmail },
        ],
      })),
    });
  }
}
