import * as path from "path"
import * as cdk from "aws-cdk-lib"
import * as codebuild from "aws-cdk-lib/aws-codebuild"
import * as dsql from "aws-cdk-lib/aws-dsql"
import * as ec2 from "aws-cdk-lib/aws-ec2"
import * as iam from "aws-cdk-lib/aws-iam"
import * as kms from "aws-cdk-lib/aws-kms"
import * as lambda from "aws-cdk-lib/aws-lambda"
import * as logs from "aws-cdk-lib/aws-logs"
import * as s3 from "aws-cdk-lib/aws-s3"
import * as s3assets from "aws-cdk-lib/aws-s3-assets"
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager"
import * as sns from "aws-cdk-lib/aws-sns"
import * as subscriptions from "aws-cdk-lib/aws-sns-subscriptions"
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
 * Aurora DSQL, open only to the tool roles from inside the VPC, the staged pipeline that
 * loads it (docs/superpowers/specs/2026-10-02-data-pipeline-design.md), the Gateway tool
 * Lambdas and the hand-off topic (docs/superpowers/specs/2026-10-03-write-tools-design.md).
 */
export class DataConstruct extends Construct {
  public readonly clusterEndpoint: string
  public readonly clusterArn: string
  public readonly privateHost: string
  public readonly loadProjectName: string
  public readonly stateMachineArn: string
  public readonly vpc: ec2.IVpc
  public readonly toolsRole: iam.Role
  public readonly writeToolsRole: iam.Role
  public readonly toolsSecurityGroup: ec2.SecurityGroup

  constructor(scope: Construct, id: string, props: DataConstructProps) {
    super(scope, id)
    const stack = cdk.Stack.of(this)

    // Network (spec 7.2): the account's default VPC, one AZ. Its subnets are public, but
    // Lambdas get no public IP, so the tools still reach only the DSQL endpoint.
    this.vpc = ec2.Vpc.fromLookup(this, "Vpc", { isDefault: true })
    const subnets: ec2.SubnetSelection = {
      subnetType: ec2.SubnetType.PUBLIC,
      availabilityZones: [stack.availabilityZones[0]], // each extra AZ costs another endpoint ENI
    }
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
    // block_credit_card and open_claim connect as ll_write (write tools spec section 8)
    this.writeToolsRole = new iam.Role(this, "WriteToolsRole", {
      roleName: "ledgerlens-write-tools",
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      description: "Write tool Lambdas: DSQL access as ll_write, from the VPC only",
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
      subnets,
      service: new ec2.InterfaceVpcEndpointService(cluster.attrVpcEndpointServiceName, 5432),
      privateDnsEnabled: true,
      securityGroups: [endpointSg],
      open: false,
    })
    // com.amazonaws.<region>.dsql-xxxx -> <cluster-id>.dsql-xxxx.<region>.on.aws
    const serviceId = cdk.Fn.select(3, cdk.Fn.split(".", cluster.attrVpcEndpointServiceName))
    this.privateHost = cdk.Fn.join(".", [cluster.attrIdentifier, serviceId, stack.region, "on.aws"])

    // Layer 1 (spec 7.1): the tools may connect, never as admin
    for (const role of [this.toolsRole, this.writeToolsRole]) {
      role.addToPolicy(new iam.PolicyStatement({ actions: ["dsql:DbConnect"], resources: [cluster.attrResourceArn] }))
    }

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
      description: "Data pipeline: python -m data_load $STAGE (ingest, transform, curate, load; access on demand)",
      role: loaderRole,
      source: codebuild.Source.s3({ bucket: source.bucket, path: source.s3ObjectKey }),
      environment: {
        buildImage: codebuild.LinuxArmBuildImage.AMAZON_LINUX_2_STANDARD_3_0,
        computeType: codebuild.ComputeType.LARGE,
      },
      // the ~90-min load is unmeasured (spec 13, check 5); a killed load costs a full rerun
      timeout: cdk.Duration.minutes(480),
      concurrentBuildLimit: 1, // two loads would race on drop/create/load
      environmentVariables: {
        TEAM_BUCKET: { value: teamBucket.bucketName },
        DSQL_ENDPOINT: { value: cluster.attrEndpoint },
        TOOLS_ROLE_ARN: { value: this.toolsRole.roleArn },
        WRITE_TOOLS_ROLE_ARN: { value: this.writeToolsRole.roleArn },
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
      vpcSubnets: subnets,
      allowPublicSubnet: true, // no public IP and no route out; see the network note above
      securityGroups: [this.toolsSecurityGroup],
      timeout: cdk.Duration.minutes(2),
      environment: { DSQL_HOST: this.privateHost },
      logGroup: new logs.LogGroup(this, "ReadCheckLogs", {
        logGroupName: `/aws/lambda/${props.config.stack_name_base}-dsql-read-check`,
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    })

    // Gateway tool Lambdas, imported by name by the agent stack. The read tools read as
    // ll_read, the role the read check proves. The write tools connect as ll_write (their
    // DSQL_DB_USER default) with their own IAM role, which the load and access stages map.
    // The ids keep ListCreditCardsFn/ListCreditCardsLogs so the deployed function is not replaced.
    const tools: { tool: string; id: string; role?: iam.IRole }[] = [
      { tool: "list_credit_cards", id: "ListCreditCards" },
      { tool: "list_card_transactions", id: "ListCardTransactions" },
      { tool: "get_session_context", id: "GetSessionContext" },
      { tool: "block_credit_card", id: "BlockCreditCard", role: this.writeToolsRole },
      { tool: "open_claim", id: "OpenClaim", role: this.writeToolsRole },
    ]
    for (const { tool, id, role = this.toolsRole } of tools) {
      const slug = tool.replace(/_/g, "-")
      new PythonFunction(this, `${id}Fn`, {
        functionName: `ledgerlens-${slug}`,
        runtime: lambda.Runtime.PYTHON_3_13,
        architecture: lambda.Architecture.ARM_64,
        entry: path.join(__dirname, "..", "..", "gateway", "tools", tool), // nosemgrep: javascript.lang.security.audit.path-traversal.path-join-resolve-traversal.path-join-resolve-traversal
        index: `${tool}_lambda/delivery/handler.py`,
        handler: "handler",
        // local test runs leave bytecode caches in the tool folder; don't ship them
        bundling: { assetExcludes: ["**/__pycache__", "**/*.pyc"] },
        role,
        vpc: this.vpc,
        vpcSubnets: subnets,
        allowPublicSubnet: true,
        securityGroups: [this.toolsSecurityGroup],
        timeout: cdk.Duration.seconds(30),
        environment: { DSQL_CLUSTER_ENDPOINT: this.privateHost, AS_OF: props.config.data.as_of },
        logGroup: new logs.LogGroup(this, `${id}Logs`, {
          logGroupName: `/aws/lambda/${props.config.stack_name_base}-${slug}`,
          retention: logs.RetentionDays.ONE_WEEK,
          removalPolicy: cdk.RemovalPolicy.DESTROY,
        }),
      })
    }

    // The hand-off tool only publishes to SNS: it runs outside the VPC (which has no route
    // out) and never touches DSQL. The topic uses the AWS-managed key, whose key policy lets
    // SNS use it for publishers in the account, so the function needs only sns:Publish.
    const handOffTopic = new sns.Topic(this, "HumanHandOffTopic", {
      topicName: "ledgerlens-human-handoff",
      masterKey: kms.Alias.fromAliasName(this, "SnsManagedKey", "alias/aws/sns"),
    })
    if (props.config.admin_user_email) {
      // the recipient confirms the subscription once, from the email SNS sends
      handOffTopic.addSubscription(new subscriptions.EmailSubscription(props.config.admin_user_email))
    }
    const handOff = new PythonFunction(this, "HumanAgentHandOffFn", {
      functionName: "ledgerlens-human-agent-hand-off",
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      entry: path.join(__dirname, "..", "..", "gateway", "tools", "human_agent_hand_off"), // nosemgrep: javascript.lang.security.audit.path-traversal.path-join-resolve-traversal.path-join-resolve-traversal
      index: "human_agent_hand_off_lambda/delivery/handler.py",
      handler: "handler",
      bundling: { assetExcludes: ["**/__pycache__", "**/*.pyc"] },
      timeout: cdk.Duration.seconds(10),
      environment: { HANDOFF_TOPIC_ARN: handOffTopic.topicArn },
      logGroup: new logs.LogGroup(this, "HumanAgentHandOffLogs", {
        logGroupName: `/aws/lambda/${props.config.stack_name_base}-human-agent-hand-off`,
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    })
    handOffTopic.grantPublish(handOff)

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
          .next(stage("Curate"))
          .next(stage("Load"))
          .next(new tasks.LambdaInvoke(this, "ReadCheck", { lambdaFunction: readCheck, payloadResponseOnly: true }))
      ),
      timeout: cdk.Duration.hours(10), // above the CodeBuild timeout, so CodeBuild fails first
    })
    this.stateMachineArn = pipeline.stateMachineArn
  }
}
