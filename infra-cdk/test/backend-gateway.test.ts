import * as cdk from "aws-cdk-lib"
import { Template } from "aws-cdk-lib/assertions"
import * as fs from "fs"
import * as path from "path"
import { FastMainStack } from "../lib/fast-main-stack"
import { ConfigManager } from "../lib/utils/config-manager"

// The three read tools live in the data stack; the main stack imports them by name.
const TOOLS = ["list_credit_cards", "list_card_transactions", "get_session_context"]
const slug = (tool: string) => tool.replace(/_/g, "-")
const REPO = path.join(__dirname, "..", "..")

function synth(): Template {
  // skip Docker bundling of the Python Lambdas: these tests read the template only.
  // Synthesizing the whole main stack takes about 2 minutes, mostly ts-jest compiling.
  const app = new cdk.App({ context: { "aws:cdk:bundling-stacks": [] } })
  const config = new ConfigManager("config.yaml").getProps()
  const stack = new FastMainStack(app, "ledgerlens-test", {
    config,
    env: { account: "111111111111", region: "us-east-1" },
  })
  return Template.fromStack(stack)
}

const t = synth()
const template = JSON.stringify(t.toJSON())
const targets = t.findResources("AWS::BedrockAgentCore::GatewayTarget")
const policy = Object.values(t.findResources("AWS::CloudFormation::CustomResource")).find(
  (r) => r.Properties.PolicyDocument
)

test("the Gateway has one target per read tool, pointing at the data stack's Lambda", () => {
  const byName = Object.fromEntries(Object.values(targets).map((r) => [r.Properties.Name, r]))
  expect(Object.keys(byName).sort()).toEqual(TOOLS.map((tool) => `${slug(tool)}-target`).sort())
  for (const tool of TOOLS) {
    expect(JSON.stringify(byName[`${slug(tool)}-target`].Properties.TargetConfiguration)).toContain(
      `arn:aws:lambda:us-east-1:111111111111:function:ledgerlens-${slug(tool)}`
    )
  }
})

test("the sample tool and Code Interpreter access are gone", () => {
  expect(template).not.toContain("text_analysis_tool")
  expect(template).not.toContain("SampleToolLambda")
  expect(template).not.toContain("CodeInterpreterAccess")
})

test("every Cedar action names a deployed target and the tool in its tool_spec.json", () => {
  // CDK strips // comment lines before CreatePolicy; read the statements the same way
  const statements = fs
    .readFileSync(path.join(REPO, "gateway", "policies", "policy.cedar"), "utf-8")
    .split("\n")
    .filter((line) => !line.trimStart().startsWith("//"))
    .join("\n")
  const actions = [...statements.matchAll(/AgentCore::Action::"([^"]+)"/g)].map((m) => m[1])
  const expected = TOOLS.map((tool) => {
    const spec = JSON.parse(
      fs.readFileSync(path.join(REPO, "gateway", "tools", tool, "tool_spec.json"), "utf-8")
    )
    return `${slug(tool)}-target___${spec[0].name}`
  })
  expect([...new Set(actions)].sort()).toEqual(expected.sort())
})

test("the Cedar policy waits for every target", () => {
  expect(policy?.DependsOn).toEqual(expect.arrayContaining(Object.keys(targets)))
})
