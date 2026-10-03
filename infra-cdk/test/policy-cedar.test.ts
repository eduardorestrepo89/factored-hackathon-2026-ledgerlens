import * as fs from "fs"
import * as path from "path"

// CDK strips // comment lines before CreatePolicy; read the statements the same way
const statements = fs
  .readFileSync(path.join(__dirname, "..", "..", "gateway", "policies", "policy.cedar"), "utf-8")
  .split("\n")
  .filter((line) => !line.trimStart().startsWith("//"))
  .join("\n")
  .split(";")
  .filter((statement) => statement.trim())

test("every forbid names its actions", () => {
  // AgentCore's policy analysis rejects a forbid over all actions as "Overly
  // Restrictive": it would also cover tools that don't exist yet (deploy, 2026-10-03).
  const unscoped = statements.filter((s) => /forbid\s*\([^)]*\baction\s*,/.test(s))
  expect(unscoped).toEqual([])
})
