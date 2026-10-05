import * as cdk from "aws-cdk-lib"
import { Template } from "aws-cdk-lib/assertions"
import * as fs from "fs"
import * as os from "os"
import * as path from "path"
import { buildStacks } from "../lib/ledgerlens-app"
import { ConfigManager } from "../lib/utils/config-manager"

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ledgerlens-cdk-"))
afterAll(() => fs.rmSync(dir, { recursive: true, force: true }))

const env = { account: "111111111111", region: "us-east-1" }

// Builds the app from a config file with the given extra lines and -c context.
let files = 0
function build(configLines = "", context: Record<string, string> = {}) {
  const file = path.join(dir, `config-${files++}.yaml`)
  fs.writeFileSync(file, `stack_name_base: ledgerlens-test\n${configLines}`)
  // skip Docker bundling of the Lambdas: these tests only build the stacks
  const app = new cdk.App({ context: { "aws:cdk:bundling-stacks": [], ...context } })
  const stacks = buildStacks(app, new ConfigManager(file).getProps(), env)
  const ids = app.node.children.filter((c) => c instanceof cdk.Stack).map((s) => s.node.id)
  return { stacks, ids }
}

test("a full deploy builds the main stack on top of the data stack", () => {
  const { stacks, ids } = build()
  expect(ids.sort()).toEqual(["ledgerlens-test", "ledgerlens-test-data"])
  // the tool Lambdas use the data stack's VPC, roles and host, so data deploys first
  expect(stacks.main?.dependencies).toContain(stacks.data)
})

test("deploy_scope: data in config.yaml builds only the data stack", () => {
  const { stacks, ids } = build("deploy_scope: data\n")
  expect(ids).toEqual(["ledgerlens-test-data"])
  expect(stacks.main).toBeUndefined()
})

test("-c deploy_scope=data builds only the data stack", () => {
  expect(build("", { deploy_scope: "data" }).ids).toEqual(["ledgerlens-test-data"])
})

test("-c deploy_scope=full overrides deploy_scope: data in config.yaml", () => {
  expect(build("deploy_scope: data\n", { deploy_scope: "full" }).ids.sort()).toEqual([
    "ledgerlens-test",
    "ledgerlens-test-data",
  ])
})

test("an unknown -c deploy_scope stops the synth", () => {
  expect(() => build("", { deploy_scope: "backend" })).toThrow(/deploy_scope/)
})

test("the Amplify app sends a CSP and the other security headers", () => {
  const app = Template.fromStack(build().stacks.main!).findResources("AWS::Amplify::App")
  const headers = JSON.stringify(Object.values(app)[0].Properties.CustomHeaders)
  for (const expected of [
    "Content-Security-Policy",
    "script-src 'self'",
    "https://bedrock-agentcore.",
    "frame-ancestors 'none'",
    "Strict-Transport-Security",
    "X-Content-Type-Options",
  ])
    expect(headers).toContain(expected)
})
