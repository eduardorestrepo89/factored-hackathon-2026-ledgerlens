import * as fs from "fs"
import * as os from "os"
import * as path from "path"
import { ConfigManager, resolveDeployScope } from "../lib/utils/config-manager"

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "config-manager-"))
afterAll(() => fs.rmSync(dir, { recursive: true, force: true }))

// Writes a config file with the given backend lines and loads its backend settings.
let files = 0
function loadBackend(backendLines: string) {
  const file = path.join(dir, `config-${files++}.yaml`)
  fs.writeFileSync(file, `stack_name_base: test\nbackend:\n${backendLines}`)
  return new ConfigManager(file).getProps().backend
}

test("the agent model defaults to DeepSeek V3.2 and is read trimmed", () => {
  expect(loadBackend("  pattern: ledgerlens\n").model_id).toBe("deepseek.v3.2")
  expect(loadBackend('  model_id: " us.anthropic.claude-haiku-4-5-20251001-v1:0 "\n').model_id).toBe(
    "us.anthropic.claude-haiku-4-5-20251001-v1:0"
  )
})

test.each([
  ["a blank model id", '  model_id: "  "\n'],
  ["a non-string model id", "  model_id: 42\n"],
])("rejects %s", (_name, backendLines) => {
  expect(() => loadBackend(backendLines)).toThrow(/backend.model_id/)
})

test("short-term memory defaults to a 30-message window without summarization", () => {
  expect(loadBackend("  pattern: ledgerlens\n")).toMatchObject({
    stm_window_size: 30,
    use_stm_summarization: false,
    stm_summary_ratio: 0.3,
    stm_preserve_recent_messages: 10,
    stm_summarization_model_id: "",
    stm_summarization_prompt: "",
  })
})

test("reads every short-term memory setting, trimming the summarizer strings", () => {
  const backend = loadBackend(
    [
      "  stm_window_size: 20",
      "  use_stm_summarization: true",
      "  stm_summary_ratio: 0.5",
      "  stm_preserve_recent_messages: 6",
      '  stm_summarization_model_id: " us.anthropic.claude-haiku-4-5-20251001-v1:0 "',
      "  stm_summarization_prompt: |",
      "    Keep every amount.",
      "    Keep every card's last 4 digits.",
      "",
    ].join("\n")
  )
  expect(backend).toMatchObject({
    stm_window_size: 20,
    use_stm_summarization: true,
    stm_summary_ratio: 0.5,
    stm_preserve_recent_messages: 6,
    stm_summarization_model_id: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    stm_summarization_prompt: "Keep every amount.\nKeep every card's last 4 digits.",
  })
})

test.each([
  ["a window below 2", "  stm_window_size: 1\n", /stm_window_size/],
  ["a window above 200", "  stm_window_size: 201\n", /stm_window_size/],
  ["a fractional window", "  stm_window_size: 2.5\n", /stm_window_size/],
  ["a ratio below 0.1", "  stm_summary_ratio: 0.05\n", /stm_summary_ratio/],
  ["a ratio above 0.8", "  stm_summary_ratio: 0.9\n", /stm_summary_ratio/],
  ["a negative preserve count", "  stm_preserve_recent_messages: -1\n", /stm_preserve_recent_messages/],
  [
    "a preserve count not below the window while summarizing",
    "  use_stm_summarization: true\n  stm_window_size: 10\n  stm_preserve_recent_messages: 10\n",
    /stm_preserve_recent_messages/,
  ],
  ["a non-string summarizer model id", "  stm_summarization_model_id: 42\n", /stm_summarization_model_id/],
  ["a non-string summarizer prompt", "  stm_summarization_prompt: [a, b]\n", /stm_summarization_prompt/],
])("rejects %s", (_name, backendLines, message) => {
  expect(() => loadBackend(backendLines)).toThrow(message)
})

test("a preserve count may reach the window while summarization is off", () => {
  // reduce_context never runs on a sliding window, so the count is unused
  const backend = loadBackend("  stm_window_size: 10\n  stm_preserve_recent_messages: 10\n")
  expect(backend.stm_preserve_recent_messages).toBe(10)
})

// Writes a config file from the given lines and loads it.
function loadConfig(lines: string) {
  const file = path.join(dir, `config-${files++}.yaml`)
  fs.writeFileSync(file, `stack_name_base: test\n${lines}`)
  return new ConfigManager(file).getProps()
}

test("deploys everything when deploy_scope is not set", () => {
  expect(loadConfig("").deploy_scope).toBe("full")
})

test.each(["full", "data"])("reads deploy_scope %s", (scope) => {
  expect(loadConfig(`deploy_scope: ${scope}\n`).deploy_scope).toBe(scope)
})

test("rejects an unknown deploy_scope", () => {
  expect(() => loadConfig("deploy_scope: backend\n")).toThrow(/deploy_scope/)
})

test("a -c deploy_scope override wins over config.yaml", () => {
  expect(resolveDeployScope("full", "data")).toBe("data")
  expect(resolveDeployScope("data", "full")).toBe("full")
  expect(resolveDeployScope("data", undefined)).toBe("data")
})

test("rejects an unknown -c deploy_scope override", () => {
  expect(() => resolveDeployScope("full", "all")).toThrow(/deploy_scope/)
})
