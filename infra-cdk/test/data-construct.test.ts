import * as cdk from "aws-cdk-lib"
import { Match, Template } from "aws-cdk-lib/assertions"
import { DataConstruct } from "../lib/data-construct"
import { AppConfig } from "../lib/utils/config-manager"

const config = {
  stack_name_base: "ledgerlens-test",
  data: { as_of: "2026-06-17T23:59:59", window_years: 2 },
} as unknown as AppConfig

test("DSQL cluster, secret and data-load job", () => {
  const app = new cdk.App()
  const stack = new cdk.Stack(app, "T", { env: { account: "111111111111", region: "us-east-1" } })
  new DataConstruct(stack, "Data", { config })
  const t = Template.fromStack(stack)

  t.hasResourceProperties("AWS::DSQL::Cluster", { DeletionProtectionEnabled: true })
  t.hasResourceProperties("AWS::SecretsManager::Secret", { Name: "ledgerlens/hackathon-s3" })
  t.hasResourceProperties("AWS::CodeBuild::Project", {
    Name: "ledgerlens-data-load",
    TimeoutInMinutes: 180,
    Environment: Match.objectLike({
      Type: "ARM_CONTAINER",
      ComputeType: "BUILD_GENERAL1_LARGE",
      // arrayWith is order-sensitive: same order as environmentVariables in data-construct.ts
      EnvironmentVariables: Match.arrayWith([
        { Name: "AS_OF", Type: "PLAINTEXT", Value: "2026-06-17T23:59:59" },
        { Name: "WINDOW_YEARS", Type: "PLAINTEXT", Value: "2" },
        Match.objectLike({ Name: "DSQL_ENDPOINT" }),
        Match.objectLike({ Name: "TEAM_BUCKET" }),
        Match.objectLike({ Name: "HACKATHON_S3", Type: "SECRETS_MANAGER" }),
      ]),
    }),
  })
  t.hasResourceProperties("AWS::IAM::Policy", {
    PolicyDocument: {
      Statement: Match.arrayWith([Match.objectLike({ Action: "dsql:DbConnectAdmin" })]),
    },
  })
})
