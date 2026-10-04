import * as cdk from "aws-cdk-lib"
import { Template } from "aws-cdk-lib/assertions"
import * as fs from "fs"
import * as path from "path"
import { FastMainStack } from "../lib/fast-main-stack"
import { ConfigManager } from "../lib/utils/config-manager"

// The tool Lambdas live in the data stack; the main stack imports them by name.
// Tool -> Gateway target name.
const TARGETS: Record<string, string> = {
  list_credit_cards: "list-credit-cards-target",
  list_card_transactions: "list-card-transactions-target",
  get_session_context: "get-session-context-target",
  transaction_fraud_detection: "fraud-detection-target",
  explain_transaction: "explain-transaction-target",
  classify_call_type: "classify-call-type-target",
  block_credit_card: "block-credit-card-target",
  open_claim: "open-claim-target",
  human_agent_hand_off: "human-agent-hand-off-target",
}
const TOOLS = Object.keys(TARGETS)
const slug = (tool: string) => tool.replace(/_/g, "-")
const REPO = path.join(__dirname, "..", "..")
const specName = (tool: string): string =>
  JSON.parse(fs.readFileSync(path.join(REPO, "gateway", "tools", tool, "tool_spec.json"), "utf-8"))[0].name

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

test("the runtime gets the short-term memory settings from config.yaml", () => {
  const [runtime] = Object.values(t.findResources("AWS::BedrockAgentCore::Runtime"))
  expect(runtime.Properties.EnvironmentVariables).toMatchObject({
    STM_WINDOW_SIZE: "30",
    USE_STM_SUMMARIZATION: "false",
    STM_SUMMARY_RATIO: "0.3",
    STM_PRESERVE_RECENT_MESSAGES: "10",
    STM_SUMMARIZATION_MODEL_ID: "",
    STM_SUMMARIZATION_PROMPT: "",
  })
})

test("the Gateway has one target per tool, pointing at the data stack's Lambda", () => {
  const byName = Object.fromEntries(Object.values(targets).map((r) => [r.Properties.Name, r]))
  expect(Object.keys(byName).sort()).toEqual(Object.values(TARGETS).sort())
  for (const tool of TOOLS) {
    expect(JSON.stringify(byName[TARGETS[tool]].Properties.TargetConfiguration)).toContain(
      `arn:aws:lambda:us-east-1:111111111111:function:ledgerlens-${slug(tool)}`
    )
  }
})

test("every tool name the model sees fits Bedrock's 64-character limit", () => {
  // The agent's MCP client adds prefix="gateway" (patterns/strands-single-agent/tools/gateway.py).
  // One name over the limit makes Bedrock reject every request, not just that tool's.
  const tooLong = TOOLS.map((tool) => `gateway_${TARGETS[tool]}___${specName(tool)}`).filter((n) => n.length > 64)
  expect(tooLong).toEqual([])
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
  const expected = TOOLS.map((tool) => `${TARGETS[tool]}___${specName(tool)}`)
  expect([...new Set(actions)].sort()).toEqual(expected.sort())
})

test("the Cedar policy waits for every target", () => {
  expect(policy?.DependsOn).toEqual(expect.arrayContaining(Object.keys(targets)))
})
