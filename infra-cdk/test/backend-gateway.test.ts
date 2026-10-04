import * as cdk from "aws-cdk-lib"
import { Match, Template } from "aws-cdk-lib/assertions"
import * as fs from "fs"
import * as path from "path"
import { DataStack } from "../lib/data-stack"
import { LedgerLensMainStack } from "../lib/ledgerlens-main-stack"
import { ConfigManager } from "../lib/utils/config-manager"

// The backend creates the tool Lambdas and wires each one as a Gateway target. They run in
// the data stack's VPC with its roles and DSQL host. Tool -> Gateway target name.
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

// skip Docker bundling of the Python Lambdas: these tests read the template only.
// Synthesizing the whole main stack takes about 2 minutes, mostly ts-jest compiling.
// Both stacks share one app, so a reference cycle between them fails the synth here.
const app = new cdk.App({ context: { "aws:cdk:bundling-stacks": [] } })
const config = new ConfigManager("config.yaml").getProps()
const env = { account: "111111111111", region: "us-east-1" }
const dataStack = new DataStack(app, "ledgerlens-test-data", { config, env })
const stack = new LedgerLensMainStack(app, "ledgerlens-test", { config, data: dataStack.data, env })
const t = Template.fromStack(stack)
const dataT = Template.fromStack(dataStack)
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

const fnId = (functionName: string) =>
  Object.keys(t.findResources("AWS::Lambda::Function", { Properties: { FunctionName: functionName } }))
const fnOf = (functionName: string) => t.findResources("AWS::Lambda::Function")[fnId(functionName)[0]]
const dataRoleId = (roleName: string) =>
  Object.keys(dataT.findResources("AWS::IAM::Role", { Properties: { RoleName: roleName } }))[0]

test("the Gateway has one target per tool, pointing at the Lambda this stack creates", () => {
  const byName = Object.fromEntries(Object.values(targets).map((r) => [r.Properties.Name, r]))
  expect(Object.keys(byName).sort()).toEqual(Object.values(TARGETS).sort())
  for (const tool of TOOLS) {
    const ids = fnId(`ledgerlens-${slug(tool)}`)
    expect(ids).toHaveLength(1)
    expect(JSON.stringify(byName[TARGETS[tool]].Properties.TargetConfiguration)).toContain(
      `{"Fn::GetAtt":["${ids[0]}","Arn"]}`
    )
  }
})

test.each([
  ["list_credit_cards", "ledgerlens-tools"],
  ["list_card_transactions", "ledgerlens-tools"],
  ["get_session_context", "ledgerlens-tools"],
  ["transaction_fraud_detection", "ledgerlens-tools"],
  ["explain_transaction", "ledgerlens-tools"],
  ["classify_call_type", "ledgerlens-tools"],
  ["block_credit_card", "ledgerlens-write-tools"],
  ["open_claim", "ledgerlens-write-tools"],
])("%s runs in the data stack's VPC subnet as %s, against the private host", (tool, roleName) => {
  t.hasResourceProperties("AWS::Lambda::Function", {
    FunctionName: `ledgerlens-${slug(tool)}`,
    Handler: `${tool}_lambda.delivery.handler.handler`,
    Runtime: "python3.13",
    Architectures: ["arm64"],
    Timeout: 30,
    // the endpoint's subnet (s-12345 is CDK's lookup placeholder in tests)
    VpcConfig: Match.objectLike({ SubnetIds: ["s-12345"] }),
    Environment: { Variables: { DSQL_CLUSTER_ENDPOINT: Match.anyValue(), AS_OF: config.data.as_of } },
  })
  const fn = fnOf(`ledgerlens-${slug(tool)}`)
  expect(JSON.stringify(fn.Properties.Role)).toContain(dataRoleId(roleName))
  expect(JSON.stringify(fn.Properties.VpcConfig.SecurityGroupIds)).toContain("ToolsSg")
  expect(JSON.stringify(fn.Properties.Environment.Variables.DSQL_CLUSTER_ENDPOINT)).toContain("Fn::ImportValue")
  t.hasResourceProperties("AWS::Logs::LogGroup", {
    LogGroupName: `/aws/lambda/${config.stack_name_base}-${slug(tool)}`,
    RetentionInDays: 7,
  })
})

test("the hand-off Lambda runs outside the VPC with no environment, no SNS and no DSQL", () => {
  const fn = fnOf("ledgerlens-human-agent-hand-off")
  expect(fn.Properties.VpcConfig).toBeUndefined()
  expect(fn.Properties.Handler).toBe("human_agent_hand_off_lambda.delivery.handler.handler")
  expect(fn.Properties.Timeout).toBe(10)
  expect(fn.Properties.Environment).toBeUndefined()
  const roleId = fn.Properties.Role["Fn::GetAtt"][0]
  const actions = Object.values(t.findResources("AWS::IAM::Policy"))
    .filter((p) => JSON.stringify(p.Properties.Roles).includes(roleId))
    .flatMap((p) => p.Properties.PolicyDocument.Statement.flatMap((s: { Action: string | string[] }) => s.Action))
  expect(actions.filter((a: string) => a.startsWith("sns:") || a.startsWith("dsql:"))).toEqual([])
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

const guardrails = t.findResources("AWS::Bedrock::Guardrail")
const [guardrail] = Object.values(guardrails)
const [guardrailId] = Object.keys(guardrails)

test("one guardrail blocks prompt attacks and harmful content", () => {
  expect(Object.keys(guardrails)).toHaveLength(1)
  const filters = guardrail.Properties.ContentPolicyConfig.FiltersConfig
  expect(filters).toContainEqual({ Type: "PROMPT_ATTACK", InputStrength: "HIGH", OutputStrength: "NONE" })
  expect(filters.map((f: { Type: string }) => f.Type).sort()).toEqual(
    ["HATE", "INSULTS", "MISCONDUCT", "PROMPT_ATTACK", "SEXUAL", "VIOLENCE"]
  )
})

test("the guardrail denies the topics unrelated to banking", () => {
  const topics = guardrail.Properties.TopicPolicyConfig.TopicsConfig
  expect(topics.map((topic: { Name: string }) => topic.Name).sort()).toEqual([
    "EntertainmentAndLifestyle",
    "GeneralKnowledgeAndSchoolwork",
    "PoliticsReligionLegalMedical",
    "SoftwareAndCoding",
  ])
  for (const topic of topics) {
    expect(topic.Type).toBe("DENY")
    expect(topic.Definition.length).toBeLessThanOrEqual(200)
    expect(topic.Examples.length).toBeLessThanOrEqual(5)
  }
})

test("the guardrail leaves banking requests to the prompt", () => {
  // Loans, investments and new products are declined by the prompt, which offers a
  // person; a guardrail block would skip that offer.
  const names = guardrail.Properties.TopicPolicyConfig.TopicsConfig.map((topic: { Name: string }) => topic.Name)
  expect(names.join(" ")).not.toMatch(/Invest|Financ|Loan|Bank/)
})

test("the guardrail masks nothing", () => {
  // Card digits, amounts and merchants must reach the customer unchanged.
  expect(guardrail.Properties.SensitiveInformationPolicyConfig).toBeUndefined()
  expect(guardrail.Properties.WordPolicyConfig).toBeUndefined()
  expect(guardrail.Properties.ContextualGroundingPolicyConfig).toBeUndefined()
})

test("the guardrail uses the Standard tier, which covers Spanish and Portuguese", () => {
  expect(guardrail.Properties.ContentPolicyConfig.ContentFiltersTierConfig).toEqual({ TierName: "STANDARD" })
  expect(guardrail.Properties.TopicPolicyConfig.TopicsTierConfig).toEqual({ TierName: "STANDARD" })
  expect(guardrail.Properties.CrossRegionConfig.GuardrailProfileArn).toBe(
    "arn:aws:bedrock:us-east-1:111111111111:guardrail-profile/us.guardrail.v1:0"
  )
})

test("the runtime gets the guardrail's id and published version", () => {
  const [runtime] = Object.values(t.findResources("AWS::BedrockAgentCore::Runtime"))
  const [versionId] = Object.keys(t.findResources("AWS::Bedrock::GuardrailVersion"))
  expect(runtime.Properties.EnvironmentVariables.GUARDRAIL_ID).toEqual({ "Fn::GetAtt": [guardrailId, "GuardrailId"] })
  expect(runtime.Properties.EnvironmentVariables.GUARDRAIL_VERSION).toEqual({ "Fn::GetAtt": [versionId, "Version"] })
})

test("the agent role may apply the guardrail", () => {
  const statements = Object.values(t.findResources("AWS::IAM::Policy")).flatMap(
    (p) => p.Properties.PolicyDocument.Statement
  )
  const apply = statements.find((s: { Sid?: string }) => s.Sid === "GuardrailAccess")
  expect(apply.Action).toBe("bedrock:ApplyGuardrail")
  expect(apply.Resource).toContainEqual({ "Fn::GetAtt": [guardrailId, "GuardrailArn"] })
})
