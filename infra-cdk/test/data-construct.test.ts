import * as cdk from "aws-cdk-lib"
import { Match, Template } from "aws-cdk-lib/assertions"
import { DataConstruct } from "../lib/data-construct"
import { AppConfig } from "../lib/utils/config-manager"

const config = {
  stack_name_base: "ledgerlens-test",
  data: { as_of: "2026-06-17T23:59:59" },
} as unknown as AppConfig

function synth(): Template {
  // skip Docker bundling of the read-check Lambda: these tests read the template only
  const app = new cdk.App({ context: { "aws:cdk:bundling-stacks": [] } })
  const stack = new cdk.Stack(app, "T", { env: { account: "111111111111", region: "us-east-1" } })
  new DataConstruct(stack, "Data", { config })
  return Template.fromStack(stack)
}

const t = synth()
const logicalId = (type: string, props: object) => Object.keys(t.findResources(type, { Properties: props }))[0]
const actionsOf = (roleId: string) =>
  Object.values(t.findResources("AWS::IAM::Policy"))
    .filter((p) => JSON.stringify(p.Properties.Roles).includes(roleId))
    .flatMap((p) => p.Properties.PolicyDocument.Statement.flatMap((s: { Action: string | string[] }) => s.Action))

test("cluster policy denies DSQL connections from outside the VPC, except the loader", () => {
  const cluster = Object.values(t.findResources("AWS::DSQL::Cluster"))[0]
  expect(cluster.Properties.DeletionProtectionEnabled).toBe(true)
  const policy = JSON.stringify(cluster.Properties.PolicyDocument)
  expect(policy).toContain("DenyOutsideAnyVpcExceptLoader")
  expect(policy).toContain('\\"Null\\":{\\"aws:SourceVpc\\":\\"true\\"}')
  expect(policy).toContain("DenyOtherVpcsExceptLoader")
  // the account's default VPC, looked up at synth (vpc-12345 is CDK's lookup placeholder in tests)
  expect(policy).toContain('\\"aws:SourceVpc\\":\\"vpc-12345\\"')
  const loaderId = logicalId("AWS::IAM::Role", {
    AssumeRolePolicyDocument: Match.objectLike({
      Statement: [Match.objectLike({ Principal: { Service: "codebuild.amazonaws.com" } })],
    }),
  })
  expect(policy).toContain(`{"Fn::GetAtt":["${loaderId}","Arn"]}`)
})

test("tools role can connect to DSQL, never as admin", () => {
  const toolsId = logicalId("AWS::IAM::Role", { RoleName: "ledgerlens-tools" })
  const actions = actionsOf(toolsId)
  expect(actions).toContain("dsql:DbConnect")
  expect(actions).not.toContain("dsql:DbConnectAdmin")
})

test("uses the default VPC, creating no network of its own; the endpoint admits only the tools", () => {
  for (const type of ["AWS::EC2::VPC", "AWS::EC2::Subnet", "AWS::EC2::NatGateway", "AWS::EC2::InternetGateway"]) {
    t.resourceCountIs(type, 0)
  }
  t.hasResourceProperties("AWS::EC2::VPCEndpoint", {
    VpcId: "vpc-12345",
    VpcEndpointType: "Interface",
    PrivateDnsEnabled: true,
    SubnetIds: ["s-12345"], // one AZ: each extra AZ costs another endpoint ENI
  })
  t.hasResourceProperties("AWS::EC2::SecurityGroupIngress", { IpProtocol: "tcp", FromPort: 5432, ToPort: 5432 })
})

test("every Lambda in the VPC runs in the endpoint's subnet", () => {
  const vpcFns = Object.values(t.findResources("AWS::Lambda::Function")).filter((f) => f.Properties.VpcConfig)
  expect(vpcFns).toHaveLength(6) // the read check and the five tools
  for (const fn of vpcFns) expect(fn.Properties.VpcConfig.SubnetIds).toEqual(["s-12345"])
})

test("read check runs in the VPC with the tools role and the private host", () => {
  const toolsId = logicalId("AWS::IAM::Role", { RoleName: "ledgerlens-tools" })
  t.hasResourceProperties("AWS::Lambda::Function", {
    FunctionName: "ledgerlens-dsql-read-check",
    Role: { "Fn::GetAtt": [toolsId, "Arn"] },
    VpcConfig: Match.objectLike({ SubnetIds: Match.anyValue() }),
    Environment: { Variables: { DSQL_HOST: Match.anyValue() } },
  })
  // <cluster-id>.<service-id>.<region>.on.aws, service-id = 4th part of com.amazonaws.<region>.dsql-xxxx
  const fn = Object.values(t.findResources("AWS::Lambda::Function", { Properties: { FunctionName: "ledgerlens-dsql-read-check" } }))[0]
  const clusterId = logicalId("AWS::DSQL::Cluster", {})
  const host = JSON.stringify(fn.Properties.Environment.Variables.DSQL_HOST)
  expect(host).toContain(`{"Fn::GetAtt":["${clusterId}","Identifier"]}`)
  expect(host).toContain(`{"Fn::Select":[3,{"Fn::Split":[".",{"Fn::GetAtt":["${clusterId}","VpcEndpointServiceName"]}]}]}`)
  expect(host).toContain('"us-east-1.on.aws"')
})

test.each([
  ["list_credit_cards", "ledgerlens-list-credit-cards"],
  ["list_card_transactions", "ledgerlens-list-card-transactions"],
  ["get_session_context", "ledgerlens-get-session-context"],
  ["transaction_fraud_detection", "ledgerlens-transaction-fraud-detection"],
  ["explain_transaction", "ledgerlens-explain-transaction"],
])("%s runs in the VPC as the tools role, against the private host as ll_read", (tool, functionName) => {
  const toolsId = logicalId("AWS::IAM::Role", { RoleName: "ledgerlens-tools" })
  t.hasResourceProperties("AWS::Lambda::Function", {
    FunctionName: functionName,
    Handler: `${tool}_lambda.delivery.handler.handler`,
    Role: { "Fn::GetAtt": [toolsId, "Arn"] },
    VpcConfig: Match.objectLike({ SubnetIds: Match.anyValue() }),
    Environment: { Variables: { DSQL_CLUSTER_ENDPOINT: Match.anyValue(), AS_OF: "2026-06-17T23:59:59" } },
  })
  const fn = Object.values(t.findResources("AWS::Lambda::Function", { Properties: { FunctionName: functionName } }))[0]
  const readCheck = Object.values(t.findResources("AWS::Lambda::Function", { Properties: { FunctionName: "ledgerlens-dsql-read-check" } }))[0]
  expect(fn.Properties.Environment.Variables.DSQL_CLUSTER_ENDPOINT).toEqual(readCheck.Properties.Environment.Variables.DSQL_HOST)
})

test("state machine runs ingest, transform, curate, load, then the read check", () => {
  const machine = Object.values(t.findResources("AWS::StepFunctions::StateMachine"))[0]
  expect(machine.Properties.StateMachineName).toBe("ledgerlens-data-pipeline")
  const definition = JSON.stringify(machine.Properties.DefinitionString)
  for (const fragment of [
    '\\"TimeoutSeconds\\":36000', // 10 h: above the CodeBuild timeout, so CodeBuild fails first
    '\\"StartAt\\":\\"Ingest\\"',
    '\\"Next\\":\\"Transform\\"',
    '\\"Next\\":\\"Curate\\"',
    '\\"Next\\":\\"Load\\"',
    '\\"Next\\":\\"ReadCheck\\"',
    '\\"Name\\":\\"STAGE\\",\\"Type\\":\\"PLAINTEXT\\",\\"Value\\":\\"transform\\"',
    '\\"Name\\":\\"STAGE\\",\\"Type\\":\\"PLAINTEXT\\",\\"Value\\":\\"curate\\"',
    '\\"Name\\":\\"RUN_ID\\",\\"Type\\":\\"PLAINTEXT\\",\\"Value.$\\":\\"$$.Execution.Name\\"',
  ]) {
    expect(definition).toContain(fragment)
  }
})

test("CodeBuild gets the secret's name, never its value; one build at a time", () => {
  t.hasResourceProperties("AWS::CodeBuild::Project", {
    Name: "ledgerlens-data-load",
    TimeoutInMinutes: 480, // headroom over the unmeasured ~90-min load (spec 13, check 5)
    ConcurrentBuildLimit: 1,
    Environment: Match.objectLike({
      Type: "ARM_CONTAINER",
      ComputeType: "BUILD_GENERAL1_LARGE",
      EnvironmentVariables: Match.arrayWith([
        Match.objectLike({ Name: "TEAM_BUCKET" }),
        Match.objectLike({ Name: "DSQL_ENDPOINT" }),
        Match.objectLike({ Name: "TOOLS_ROLE_ARN" }),
        { Name: "HACKATHON_SECRET_ID", Type: "PLAINTEXT", Value: "ledgerlens/hackathon-s3" },
      ]),
    }),
  })
  const project = Object.values(t.findResources("AWS::CodeBuild::Project"))[0]
  const types = project.Properties.Environment.EnvironmentVariables.map((v: { Type: string }) => v.Type)
  expect(types).not.toContain("SECRETS_MANAGER")
  const buildSpec = project.Properties.Source.BuildSpec
  expect(buildSpec).toContain('python -m data_load \\"$STAGE\\"')
  expect(buildSpec).toContain("import duckdb, psycopg, aurora_dsql_psycopg, boto3")
})
