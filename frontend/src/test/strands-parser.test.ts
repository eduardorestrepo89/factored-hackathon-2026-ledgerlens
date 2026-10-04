import { describe, it, expect } from "vitest"
import { createStrandsParser } from "@/lib/agentcore-client/parsers/strands"
import type { StreamEvent } from "@/lib/agentcore-client"

const TOOL = { toolUseId: "tooluse_1", name: "gw___list_credit_cards" }

/** Strands' stream event for one tool-input delta, as the agent forwards it. */
const delta = (input: string) =>
  `data: ${JSON.stringify({ delta: { toolUse: { input } }, current_tool_use: { ...TOOL, input } })}`

const parseAll = (lines: string[]) => {
  const parse = createStrandsParser()
  const events: StreamEvent[] = []
  lines.forEach(line => parse(line, e => events.push(e)))
  return events
}

describe("strands parser: tool calls", () => {
  it("starts a tool whose whole input arrives in its first delta (DeepSeek on Bedrock)", () => {
    expect(parseAll([delta('{"customer_id": "CLI-1"}')])).toEqual([
      { type: "tool_use_start", ...TOOL },
      { type: "tool_use_delta", toolUseId: TOOL.toolUseId, input: '{"customer_id": "CLI-1"}' },
    ])
  })

  it("starts a tool once when its first delta is empty (Claude on Bedrock)", () => {
    expect(parseAll([delta(""), delta('{"customer_id"'), delta(': "CLI-1"}')])).toEqual([
      { type: "tool_use_start", ...TOOL },
      { type: "tool_use_delta", toolUseId: TOOL.toolUseId, input: '{"customer_id"' },
      { type: "tool_use_delta", toolUseId: TOOL.toolUseId, input: ': "CLI-1"}' },
    ])
  })
})

describe("strands parser: confirmations", () => {
  it("passes on a claim or hand-off paused for the customer's Yes/No", () => {
    const confirmation = { id: "int-1", tool: "open_claim", toolUseId: "tooluse_2", details: { transaction_ids: ["TRX-1"] } }

    expect(parseAll([`data: ${JSON.stringify({ confirmation })}`])).toEqual([{ type: "confirmation", ...confirmation }])
  })
})
