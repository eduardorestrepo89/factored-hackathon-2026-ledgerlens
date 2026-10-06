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

test("the write tools are forbidden unless customer_confirmed is present and true", () => {
  const confirm = statements.filter((s) => s.includes("customer_confirmed"))
  expect(confirm).toHaveLength(1)
  expect(confirm[0]).toMatch(/^\s*forbid/)
  expect(confirm[0]).toContain('"block-credit-card-target___block_credit_card"')
  expect(confirm[0]).toContain('"open-claim-target___open_claim"')
  // without the has guard, a missing argument makes the forbid fail to evaluate and be skipped
  expect(confirm[0]).toContain("!(context.input has customer_confirmed)")
  expect(confirm[0]).toContain("context.input.customer_confirmed != true")
})
