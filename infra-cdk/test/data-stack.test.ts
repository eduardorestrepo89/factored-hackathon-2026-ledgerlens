import * as cdk from "aws-cdk-lib"
import { Template } from "aws-cdk-lib/assertions"
import { DataStack } from "../lib/data-stack"
import { AppConfig } from "../lib/utils/config-manager"

const config = {
  stack_name_base: "ledgerlens-test",
  data: { as_of: "2026-06-17T23:59:59" },
} as unknown as AppConfig

test("the data stack deploys on its own and exports the pipeline's outputs", () => {
  // skip Docker bundling of the read-check Lambda: this test reads the template only
  const app = new cdk.App({ context: { "aws:cdk:bundling-stacks": [] } })
  const stack = new DataStack(app, "ledgerlens-test-data", {
    config,
    env: { account: "111111111111", region: "us-east-1" },
  })
  const t = Template.fromStack(stack)
  t.resourceCountIs("AWS::DSQL::Cluster", 1)
  t.resourceCountIs("AWS::StepFunctions::StateMachine", 1)
  for (const name of ["DsqlEndpoint", "DsqlPrivateHost", "DataPipelineStateMachine", "DataLoadProject"]) {
    t.hasOutput(name, {})
  }
  t.hasOutput("DsqlEndpoint", { Export: { Name: "ledgerlens-test-DsqlEndpoint" } })
})
