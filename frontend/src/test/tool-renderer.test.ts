import { describe, it, expect } from "vitest"
import {
  bareToolName,
  getToolRenderer,
  useDefaultTool,
  useToolRenderer,
} from "@/hooks/useToolRenderer"

describe("tool renderer lookup", () => {
  it("finds a named renderer by the Gateway-prefixed name and falls back to the default", () => {
    const named = () => "named"
    const fallback = () => "default"
    useDefaultTool(fallback)
    useToolRenderer("human_agent_hand_off", named)

    expect(getToolRenderer("human-agent-hand-off-target___human_agent_hand_off")).toBe(named)
    expect(getToolRenderer("human_agent_hand_off")).toBe(named)
    expect(getToolRenderer("list-credit-cards-target___list_credit_cards")).toBe(fallback)
  })

  it("strips only the target prefix", () => {
    expect(bareToolName("human-agent-hand-off-target___human_agent_hand_off")).toBe(
      "human_agent_hand_off"
    )
    expect(bareToolName("human_agent_hand_off")).toBe("human_agent_hand_off")
  })
})
