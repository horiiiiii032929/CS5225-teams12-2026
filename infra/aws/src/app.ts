import { App } from 'aws-cdk-lib';
import { FlatSplitStack } from './flatsplit-stack.js';

const app = new App();

const stage: unknown = app.node.tryGetContext('stage') ?? 'dev';
if (typeof stage !== 'string' || !/^[a-z][a-z0-9-]{1,15}$/.test(stage)) {
  throw new Error(
    'Context "stage" must be lowercase letters, digits or hyphens.',
  );
}
const budgetEmail: unknown = app.node.tryGetContext('budgetEmail');

new FlatSplitStack(app, `FlatSplit-${stage}`, {
  stage,
  budgetEmail: typeof budgetEmail === 'string' ? budgetEmail : undefined,
  env: { account: process.env.CDK_DEFAULT_ACCOUNT, region: 'ap-southeast-1' },
  tags: { project: 'flatsplit', stage },
});

app.synth();
