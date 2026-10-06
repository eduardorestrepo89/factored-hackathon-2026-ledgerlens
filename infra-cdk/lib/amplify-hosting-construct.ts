import * as cdk from "aws-cdk-lib"
import * as amplify from "@aws-cdk/aws-amplify-alpha"
import * as s3 from "aws-cdk-lib/aws-s3"
import * as iam from "aws-cdk-lib/aws-iam"
import { Construct } from "constructs"
import { AppConfig } from "./utils/config-manager"

export interface AmplifyConstructProps {
  config: AppConfig
}

export class AmplifyHostingConstruct extends Construct {
  public readonly amplifyApp: amplify.App
  public readonly amplifyUrl: string
  public readonly stagingBucket: s3.Bucket

  constructor(scope: Construct, id: string, props: AmplifyConstructProps) {
    super(scope, id)

    // Create access logs bucket for staging bucket
    const accessLogsBucket = new s3.Bucket(this, "StagingBucketAccessLogs", {
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      publicReadAccess: false,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      lifecycleRules: [
        {
          id: "DeleteOldAccessLogs",
          enabled: true,
          expiration: cdk.Duration.days(90), // Keep access logs for 90 days
        },
      ],
    })

    // Create staging bucket for Amplify deployments with dynamic name
    this.stagingBucket = new s3.Bucket(this, "StagingBucket", {
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      versioned: true, // Enable versioning as required by Amplify
      publicReadAccess: false,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      serverAccessLogsBucket: accessLogsBucket,
      serverAccessLogsPrefix: "staging-bucket-access-logs/",
      lifecycleRules: [
        {
          id: "DeleteOldDeployments",
          enabled: true,
          expiration: cdk.Duration.days(30), // Clean up old deployment artifacts after 30 days
        },
      ],
    })

    // Add bucket policy to allow Amplify service access
    this.stagingBucket.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: "AmplifyAccess",
        effect: iam.Effect.ALLOW,
        principals: [new iam.ServicePrincipal("amplify.amazonaws.com")],
        actions: ["s3:GetObject", "s3:GetObjectVersion"],
        resources: [this.stagingBucket.arnForObjects("*")],
      })
    )

    // Enforce SSL/TLS for all requests to the bucket
    this.stagingBucket.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: "DenyInsecureConnections",
        effect: iam.Effect.DENY,
        principals: [new iam.AnyPrincipal()],
        actions: ["s3:*"],
        resources: [
          this.stagingBucket.bucketArn,
          this.stagingBucket.arnForObjects("*"),
        ],
        conditions: {
          Bool: {
            "aws:SecureTransport": "false",
          },
        },
      })
    )

    // The login tokens live in localStorage, so the CSP is what keeps an injected script from
    // reading them. connect-src lists every origin the SPA calls: aws-exports.json, Cognito
    // (OIDC discovery + the hosted-UI token endpoint), the AgentCore runtime and the feedback API.
    const region = cdk.Aws.REGION
    const cognitoHostedUi = `https://*.auth.${region}.amazoncognito.com`
    const csp = [
      "default-src 'self'",
      "script-src 'self'",
      "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
      "font-src 'self' https://fonts.gstatic.com",
      "img-src 'self' data: blob:",
      `connect-src 'self' https://cognito-idp.${region}.amazonaws.com ${cognitoHostedUi} https://bedrock-agentcore.${region}.amazonaws.com https://*.execute-api.${region}.amazonaws.com`,
      `frame-src ${cognitoHostedUi}`, // oidc-client-ts falls back to an iframe for silent renew
      "object-src 'none'",
      "base-uri 'self'",
      "form-action 'self'",
      "frame-ancestors 'none'",
    ].join("; ")

    // Create the Amplify app
    this.amplifyApp = new amplify.App(this, "AmplifyApp", {
      appName: `${props.config.stack_name_base}-frontend`,
      description: `${props.config.stack_name_base} - React Frontend`,
      platform: amplify.Platform.WEB,
      customResponseHeaders: [
        {
          pattern: "**",
          headers: {
            "Content-Security-Policy": csp,
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "strict-origin-when-cross-origin",
          },
        },
      ],
    })

    // Create main branch for the Amplify app
    this.amplifyApp.addBranch("main", {
      stage: "PRODUCTION",
      branchName: "main",
    })

    // The predictable domain format: https://main.{appId}.amplifyapp.com
    this.amplifyUrl = `https://main.${this.amplifyApp.appId}.amplifyapp.com`
  }
}
