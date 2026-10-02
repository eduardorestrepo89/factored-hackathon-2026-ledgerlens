import * as path from "path"
import * as cdk from "aws-cdk-lib"
import * as codebuild from "aws-cdk-lib/aws-codebuild"
import * as dsql from "aws-cdk-lib/aws-dsql"
import * as ec2 from "aws-cdk-lib/aws-ec2"
import * as iam from "aws-cdk-lib/aws-iam"
import * as lambda from "aws-cdk-lib/aws-lambda"
import * as logs from "aws-cdk-lib/aws-logs"
import * as s3 from "aws-cdk-lib/aws-s3"
import * as s3assets from "aws-cdk-lib/aws-s3-assets"
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager"
import * as sfn from "aws-cdk-lib/aws-stepfunctions"
import * as tasks from "aws-cdk-lib/aws-stepfunctions-tasks"
import { PythonFunction } from "@aws-cdk/aws-lambda-python-alpha"
import { Construct } from "constructs"
import { AppConfig } from "./utils/config-manager"

// Pinned aurora-dsql-loader release; the hash is GitHub's published asset digest
const LOADER_URL =
  "https://github.com/aws-samples/aurora-dsql-loader/releases/download/v3.3.0/aurora-dsql-loader-aarch64-unknown-linux-musl.tar.gz"
const LOADER_SHA256 = "eb7a559f13aa3603704aae0e3e27b4f5e2bd3904ae9e656161df60170ce3dff5"
const SECRET_NAME = "ledgerlens/hackathon-s3"

export interface DataConstructProps {
  config: AppConfig
}

/**
 * Aurora DSQL, readable only by the tools role from inside the VPC, plus the staged
 * pipeline that loads it (docs/superpowers/specs/2026-10-02-data-pipeline-design.md).
 */
export class DataConstruct extends Construct {
  public readonly clusterEndpoint: string
  public readonly clusterArn: string
  public readonly privateHost: string
  public readonly loadProjectName: string
  public readonly stateMachineArn: string
  public readonly vpc: ec2.Vpc
  public readonly toolsRole: iam.Role
  public readonly toolsSecurityGroup: ec2.SecurityGroup

  constructor(scope: Construct, id: string, props: DataConstructProps) {
    super(scope, id)
    const stack = cdk.Stack.of(this)

    // Network (spec 7.2): one AZ, isolated subnet, no NAT or internet gateway
    this.vpc = new ec2.Vpc(this, "Vpc", {
      maxAzs: 1,
      natGateways: 0,
      subnetConfiguration: [{ name: "tools", subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 }],
    })
    this.toolsSecurityGroup = new ec2.SecurityGroup(this, "ToolsSg", {
      vpc: this.vpc,
      description: "LedgerLens tool Lambdas",
    })
    const endpointSg = new ec2.SecurityGroup(this, "DsqlEndpointSg", {
      vpc: this.vpc,
      description: "Aurora DSQL PrivateLink endpoint",
      allowAllOutbound: false,
    })
    endpointSg.addIngressRule(this.toolsSecurityGroup, ec2.Port.tcp(5432), "PostgreSQL from the tools")

    // Identities (spec 7.3). The loader role exists before the cluster: the cluster policy names it.
    const loaderRole = new iam.Role(this, "LoaderRole", {
      assumedBy: new iam.ServicePrincipal("codebuild.amazonaws.com"),
      description: "Data pipeline CodeBuild stages; the only identity allowed into DSQL from outside the VPC",
    })
    this.toolsRole = new iam.Role(this, "ToolsRole", {
      roleName: "ledgerlens-tools",
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      description: "Tool Lambdas: read-only DSQL access as ll_read, from the VPC only",
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSLambdaVPCAccessExecutionRole"),
      ],
    })

    // Layer 3 (spec 7.1): deny DSQL connections from outside our VPC, except the loader
    const denyOutside = (sid: string, condition: Record<string, unknown>) => ({
      Sid: sid,
      Effect: "Deny",
      Principal: { AWS: "*" },
      Resource: "*",
      Action: ["dsql:DbConnect", "dsql:DbConnectAdmin"],
      Condition: condition,
    })
    const cluster = new dsql.CfnCluster(this, "Cluster", {
      deletionProtectionEnabled: true,
      tags: [{ key: "Name", value: `${props.config.stack_name_base}-dsql` }],
      policyDocument: stack.toJsonString({
        Version: "2012-10-17",
        Statement: [
          denyOutside("DenyOutsideAnyVpcExceptLoader", {
            Null: { "aws:SourceVpc": "true" },
            StringNotEquals: { "aws:PrincipalArn": loaderRole.roleArn },
          }),
          denyOutside("DenyOtherVpcsExceptLoader", {
            StringNotEquals: { "aws:SourceVpc": this.vpc.vpcId, "aws:PrincipalArn": loaderRole.roleArn },
          }),
        ],
      }),
    })
    cluster.applyRemovalPolicy(cdk.RemovalPolicy.RETAIN)
    this.clusterEndpoint = cluster.attrEndpoint
    this.clusterArn = cluster.attrResourceArn

    new ec2.InterfaceVpcEndpoint(this, "DsqlEndpoint", {
      vpc: this.vpc,
      service: new ec2.InterfaceVpcEndpointService(cluster.attrVpcEndpointServiceName, 5432),
      privateDnsEnabled: true,
      securityGroups: [endpointSg],
      open: false,
    })
    // com.amazonaws.<region>.dsql-xxxx -> <cluster-id>.dsql-xxxx.<region>.on.aws
    const serviceId = cdk.Fn.select(3, cdk.Fn.split(".", cluster.attrVpcEndpointServiceName))
    this.privateHost = cdk.Fn.join(".", [cluster.attrIdentifier, serviceId, stack.region, "on.aws"])

    // Layer 1 (spec 7.1): the tools may connect, never as admin
    this.toolsRole.addToPolicy(
      new iam.PolicyStatement({ actions: ["dsql:DbConnect"], resources: [cluster.attrResourceArn] })
    )

    const teamBucket = new s3.Bucket(this, "StagingBucket", {
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    })

    // Created with a generated placeholder; a teammate sets the real JSON once (spec section 12)
    const hackathonSecret = new secretsmanager.Secret(this, "HackathonS3", {
      secretName: SECRET_NAME,
      description: "Organizer S3 read keys for the datathon bucket (JSON). Set manually; never commit.",
    })

    const source = new s3assets.Asset(this, "DataLoadSource", {
      path: path.join(__dirname, "..", "..", "data_load"),
      exclude: ["__pycache__", "*.pyc"],
    })

    const project = new codebuild.Project(this, "DataLoad", {
      projectName: "ledgerlens-data-load",
      description: "Data pipeline stages 1-3: python -m data_load $STAGE (ingest, transform, load)",
      role: loaderRole,
      source: codebuild.Source.s3({ bucket: source.bucket, path: source.s3ObjectKey }),
      environment: {
        buildImage: codebuild.LinuxArmBuildImage.AMAZON_LINUX_2_STANDARD_3_0,
        computeType: codebuild.ComputeType.LARGE,
      },
      timeout: cdk.Duration.minutes(180),
      concurrentBuildLimit: 1, // two loads would race on drop/create/load
      environmentVariables: {
        TEAM_BUCKET: { value: teamBucket.bucketName },
        DSQL_ENDPOINT: { value: cluster.attrEndpoint },
        TOOLS_ROLE_ARN: { value: this.toolsRole.roleArn },
        HACKATHON_SECRET_ID: { value: SECRET_NAME }, // the name, never the value
      },
      buildSpec: codebuild.BuildSpec.fromObject({
        version: "0.2",
        phases: {
          install: {
            "runtime-versions": { python: "3.12" },
            commands: [
              "pip install --quiet -r requirements.txt",
              // fail in seconds, not after an hour, if a dependency is missing
              'python -c "import duckdb, psycopg, aurora_dsql_psycopg, boto3"',
              `curl --proto '=https' --tlsv1.2 -sSfL -o /tmp/loader.tar.gz ${LOADER_URL}`,
              `echo "${LOADER_SHA256}  /tmp/loader.tar.gz" | sha256sum -c -`,
              "tar -xzf /tmp/loader.tar.gz -C /usr/local/bin aurora-dsql-loader",
              "aurora-dsql-loader load --help",
            ],
          },
          build: {
            commands: [
              // The asset unpacks data_load's contents at the source root; python -m needs the package dir
              'mkdir -p /tmp/src/data_load && cp -r . /tmp/src/data_load/ && cd /tmp/src && python -m data_load "$STAGE"',
            ],
          },
        },
      }),
    })
    teamBucket.grantReadWrite(project)
    hackathonSecret.grantRead(project)
    project.addToRolePolicy(
      new iam.PolicyStatement({ actions: ["dsql:DbConnectAdmin"], resources: [cluster.attrResourceArn] })
    )
    this.loadProjectName = project.projectName

    // Stage 4: the read check runs where the tools will run (spec 4.1)
    const readCheck = new PythonFunction(this, "ReadCheckFn", {
      functionName: "ledgerlens-dsql-read-check",
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64, // matches the Cedar Lambda's bundling
      entry: path.join(__dirname, "..", "lambdas", "dsql-read-check"),
      handler: "handler",
      role: this.toolsRole,
      vpc: this.vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [this.toolsSecurityGroup],
      timeout: cdk.Duration.minutes(2),
      environment: { DSQL_HOST: this.privateHost },
      logGroup: new logs.LogGroup(this, "ReadCheckLogs", {
        logGroupName: `/aws/lambda/${props.config.stack_name_base}-dsql-read-check`,
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    })

    // Stages 1-4 in order (spec 4.2); RUN_ID is the execution name
    const stage = (name: string) =>
      new tasks.CodeBuildStartBuild(this, name, {
        project,
        integrationPattern: sfn.IntegrationPattern.RUN_JOB,
        environmentVariablesOverride: {
          STAGE: { type: codebuild.BuildEnvironmentVariableType.PLAINTEXT, value: name.toLowerCase() },
          RUN_ID: {
            type: codebuild.BuildEnvironmentVariableType.PLAINTEXT,
            value: sfn.JsonPath.stringAt("$$.Execution.Name"),
          },
        },
        resultPath: sfn.JsonPath.DISCARD,
      })
    const pipeline = new sfn.StateMachine(this, "Pipeline", {
      stateMachineName: "ledgerlens-data-pipeline",
      definitionBody: sfn.DefinitionBody.fromChainable(
        stage("Ingest")
          .next(stage("Transform"))
          .next(stage("Load"))
          .next(new tasks.LambdaInvoke(this, "ReadCheck", { lambdaFunction: readCheck, payloadResponseOnly: true }))
      ),
      timeout: cdk.Duration.hours(5),
    })
    this.stateMachineArn = pipeline.stateMachineArn
  }
}
