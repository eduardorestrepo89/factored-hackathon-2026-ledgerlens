import { describe, it, expect } from "vitest"
import type { Message, MessageSegment, ToolCallStatus } from "@/components/chat/types"
import {
  findHandOff,
  parseHandOffResult,
  phaseOf,
  queueFor,
  reasonLabel,
  suggestedReplies,
  type HandOff,
} from "@/lib/handoff"

const RESULT = {
  hand_off_id: "HO-7Q3KX2MA",
  status: "queued",
  priority: "high" as const,
  reason: "FRAUD_CONFIRMED" as const,
  customer_id: "CLI-F2DZJYU0POJ9",
  summary: "No reconoce 2 cargos en Miami.",
  related_ids: ["TX-88", "TX-89"],
}
const PREFIXED = "human-agent-hand-off-target___human_agent_hand_off"
const AT = "2026-10-03T08:18:00.000Z"

const tool = (result: string | undefined, status: ToolCallStatus = "complete", name = PREFIXED): MessageSegment => ({
  type: "tool",
  toolCall: { toolUseId: "t1", name, input: "{}", result, status },
})
const text = (content: string): MessageSegment => ({ type: "text", content })
const assistant = (...segments: MessageSegment[]): Message => ({ role: "assistant", content: "", timestamp: AT, segments })
const user = (content: string): Message => ({ role: "user", content, timestamp: AT })
const human = (content: string): Message => ({ role: "human", content, timestamp: AT })
const handOff = (over: Partial<HandOff> = {}): HandOff => ({ ...RESULT, goodbye: "", at: AT, ...over })

describe("findHandOff", () => {
  it("returns the result, the goodbye after the tool and the message time", () => {
    const found = findHandOff([
      user("quiero hablar con una persona"),
      assistant(text("Te paso con una persona."), tool(JSON.stringify(RESULT)), text(" Una persona sigue contigo aquí.")),
    ])
    expect(found).toEqual({ ...RESULT, goodbye: "Una persona sigue contigo aquí.", at: AT })
  })

  it("matches the bare tool name too", () => {
    expect(findHandOff([assistant(tool(JSON.stringify(RESULT), "complete", "human_agent_hand_off"))])?.hand_off_id).toBe(
      "HO-7Q3KX2MA"
    )
  })

  it("falls back to the text before the tool when the goodbye came first", () => {
    const found = findHandOff([assistant(text("Una persona sigue contigo aquí."), tool(JSON.stringify(RESULT)))])
    expect(found?.goodbye).toBe("Una persona sigue contigo aquí.")
  })

  it.each([
    ["an error result", JSON.stringify({ error: "The hand-off couldn't be sent." })],
    ["text that isn't JSON", "Unexpected internal error sending the hand-off."],
    ["JSON without an id", JSON.stringify({ status: "queued" })],
    ["no result", undefined],
  ])("ignores %s", (_label, result) => {
    expect(findHandOff([assistant(tool(result), text("Hasta pronto."))])).toBeNull()
  })

  it("ignores a call that hasn't finished", () => {
    expect(findHandOff([assistant(tool(JSON.stringify(RESULT), "executing"))])).toBeNull()
  })

  it("ignores other tools", () => {
    expect(findHandOff([assistant(tool(JSON.stringify(RESULT), "complete", "list-credit-cards-target___list_credit_cards"))])).toBeNull()
  })

  it("looks only at the last message", () => {
    expect(findHandOff([assistant(tool(JSON.stringify(RESULT))), user("hola")])).toBeNull()
  })

  it("takes the first valid call when the tool ran twice", () => {
    const second = { ...RESULT, hand_off_id: "HO-SECOND22" }
    const found = findHandOff([assistant(tool(JSON.stringify(RESULT)), tool(JSON.stringify(second)), text("Chao."))])
    expect(found?.hand_off_id).toBe("HO-7Q3KX2MA")
  })
})

describe("parseHandOffResult", () => {
  it("unwraps the Lambda envelope when the Gateway passes it through as the text", () => {
    const envelope = JSON.stringify({ content: [{ type: "text", text: JSON.stringify(RESULT) }] })
    expect(parseHandOffResult(envelope)?.hand_off_id).toBe("HO-7Q3KX2MA")
  })

  it("ignores an envelope around an error", () => {
    const envelope = JSON.stringify({ content: [{ type: "text", text: JSON.stringify({ error: "down" }) }] })
    expect(parseHandOffResult(envelope)).toBeNull()
  })

  it("gives related_ids a default when the result has none", () => {
    const withoutIds: Partial<typeof RESULT> = { ...RESULT }
    delete withoutIds.related_ids
    expect(parseHandOffResult(JSON.stringify(withoutIds))?.related_ids).toEqual([])
  })
})

describe("phaseOf", () => {
  it("moves from ai to connecting to joined", () => {
    expect(phaseOf(null, [user("hola")])).toBe("ai")
    expect(phaseOf(handOff(), [user("hola")])).toBe("connecting")
    expect(phaseOf(handOff(), [user("hola"), human("Hola, soy Laura.")])).toBe("joined")
  })
})

describe("labels", () => {
  it("names the queue and the reason in Spanish, passing unknown reasons through", () => {
    expect(queueFor("FRAUD_CONFIRMED")).toBe("Fraudes")
    expect(queueFor("OUT_OF_SCOPE")).toBe("Servicio general")
    // the customer sees this label: never claim the bank confirmed fraud
    expect(reasonLabel("FRAUD_CONFIRMED")).toBe("Cargo no reconocido")
    expect(reasonLabel("SOMETHING_NEW")).toBe("SOMETHING_NEW")
  })
})

describe("suggestedReplies", () => {
  it("greets by first name and names the queue and the case", () => {
    const [hello, next] = suggestedReplies(handOff(), "Carlos Rendón")
    expect(hello).toBe(
      "Hola Carlos, soy Laura, de Fraudes. Ya tengo tu caso HO-7Q3KX2MA y todo lo que hablaste con el asistente, así que no necesitas repetir nada."
    )
    expect(next).toContain("otros intentos")
  })

  it("leaves the name out when the profile has none", () => {
    const [hello] = suggestedReplies(handOff({ reason: "CUSTOMER_REQUEST" }), "  ")
    expect(hello.startsWith("Hola, soy Laura, de Servicio general.")).toBe(true)
  })
})
