import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { Annotations, RemovalPolicy } from 'aws-cdk-lib';
import {
  AllowedMethods,
  CachePolicy,
  Distribution,
  Function,
  FunctionCode,
  FunctionEventType,
  FunctionRuntime,
  OriginRequestPolicy,
  ResponseHeadersPolicy,
  ViewerProtocolPolicy,
} from 'aws-cdk-lib/aws-cloudfront';
import { HttpOrigin, S3BucketOrigin } from 'aws-cdk-lib/aws-cloudfront-origins';
import {
  BlockPublicAccess,
  Bucket,
  BucketEncryption,
} from 'aws-cdk-lib/aws-s3';
import { BucketDeployment, Source } from 'aws-cdk-lib/aws-s3-deployment';
import { Construct } from 'constructs';
import { repoRoot } from './paths.js';

export interface WebProps {
  readonly apiOriginDomain: string;
  readonly removalPolicy: RemovalPolicy;
}

// SPA routes have no file extension; serve index.html so TanStack Router handles them.
const spaRewrite = `function handler(event) {
  var request = event.request;
  if (request.uri.indexOf('.') === -1) {
    request.uri = '/index.html';
  }
  return request;
}`;

/** One origin for the browser: the static web build and /api/* on the same domain. */
export class Web extends Construct {
  readonly distribution: Distribution;

  constructor(scope: Construct, id: string, props: WebProps) {
    super(scope, id);

    const destroy = props.removalPolicy === RemovalPolicy.DESTROY;
    const bucket = new Bucket(this, 'SiteBucket', {
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      encryption: BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      removalPolicy: props.removalPolicy,
      autoDeleteObjects: destroy,
    });

    this.distribution = new Distribution(this, 'Distribution', {
      comment: 'FlatSplit web and API',
      defaultRootObject: 'index.html',
      defaultBehavior: {
        origin: S3BucketOrigin.withOriginAccessControl(bucket),
        viewerProtocolPolicy: ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        responseHeadersPolicy: ResponseHeadersPolicy.SECURITY_HEADERS,
        functionAssociations: [
          {
            eventType: FunctionEventType.VIEWER_REQUEST,
            function: new Function(this, 'SpaRewrite', {
              runtime: FunctionRuntime.JS_2_0,
              code: FunctionCode.fromInline(spaRewrite),
            }),
          },
        ],
      },
      additionalBehaviors: {
        '/api/*': {
          origin: new HttpOrigin(props.apiOriginDomain),
          viewerProtocolPolicy: ViewerProtocolPolicy.HTTPS_ONLY,
          allowedMethods: AllowedMethods.ALLOW_ALL,
          cachePolicy: CachePolicy.CACHING_DISABLED,
          originRequestPolicy:
            OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
        },
      },
    });

    const webBuild = join(repoRoot, 'apps', 'web', 'dist');
    if (existsSync(join(webBuild, 'index.html'))) {
      new BucketDeployment(this, 'DeployWeb', {
        sources: [Source.asset(webBuild)],
        destinationBucket: bucket,
        distribution: this.distribution,
        distributionPaths: ['/*'],
      });
    } else {
      Annotations.of(this).addWarningV2(
        'flatsplit:web-build-missing',
        'apps/web/dist is missing; run `pnpm build` before synth to deploy the web app.',
      );
    }
  }
}
