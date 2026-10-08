import { App, Stack } from 'aws-cdk-lib';

const app = new App();

// Intentionally empty. Add reviewed AWS resources in implementation issues.
new Stack(app, 'FlatSplitScaffold');
app.synth();
