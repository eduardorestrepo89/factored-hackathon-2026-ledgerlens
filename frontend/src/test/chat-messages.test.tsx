import { afterEach, describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { ChatMessages } from "@/components/chat/ChatMessages"
import type { Message } from "@/components/chat/types"

const T = "2026-10-03T08:18:00.000Z"
const say = (content: string): Message => ({ role: "user", content, timestamp: T })

// jsdom has no layout: give every element a height and record writes to scrollTop
const scrollTop = vi.fn()
Object.defineProperty(HTMLElement.prototype, "scrollHeight", { configurable: true, get: () => 480 })
Object.defineProperty(HTMLElement.prototype, "scrollTop", { configurable: true, get: () => 0, set: scrollTop })
afterEach(() => scrollTop.mockClear())

describe("ChatMessages scrolling", () => {
  it("opens at the bottom, so a thread mounted at the split shows the ticket and the goodbye", () => {
    render(<ChatMessages messages={[say("hola"), say("chao")]} sessionId="s" onFeedbackSubmit={async () => {}} />)

    expect(scrollTop).toHaveBeenCalledWith(480)
  })

  it("follows every new message, in every copy of the thread", () => {
    const { rerender } = render(<ChatMessages messages={[say("hola")]} sessionId="s" onFeedbackSubmit={async () => {}} hideFeedback />)
    scrollTop.mockClear()

    rerender(<ChatMessages messages={[say("hola"), say("Hola, soy Laura.")]} sessionId="s" onFeedbackSubmit={async () => {}} hideFeedback />)

    expect(scrollTop).toHaveBeenCalledWith(480)
  })
})

describe("ChatMessages typing", () => {
  const reply = (content: string): Message => ({
    role: "assistant",
    content,
    timestamp: T,
    segments: content ? [{ type: "text", content }] : [],
  })
  const thread = (last: Message) => (
    <ChatMessages messages={[say("hola"), last]} sessionId="s" onFeedbackSubmit={async () => {}} isLoading />
  )

  it("shows the dots in the agent's line until its text streams in", () => {
    const { rerender } = render(thread(reply("")))
    expect(screen.getByRole("status", { name: "Escribiendo…" })).toBeInTheDocument()

    rerender(thread(reply("Hola")))
    expect(screen.queryByRole("status")).toBeNull()
  })
})

describe("ChatMessages tool calls", () => {
  it("shows no empty bubble for the whitespace a model writes before a tool call", () => {
    // DeepSeek on Bedrock writes "\n\n<｜DSML｜function_calls" before a tool; the agent strips the marker
    const reply: Message = {
      role: "assistant",
      content: "\n\nTienes dos tarjetas.",
      timestamp: T,
      segments: [
        { type: "text", content: "\n\n" },
        { type: "tool", toolCall: { toolUseId: "t1", name: "gw___list_credit_cards", input: "{}", status: "complete" } },
        { type: "text", content: "Tienes dos tarjetas." },
      ],
    }
    const { container } = render(<ChatMessages messages={[say("hola"), reply]} sessionId="s" onFeedbackSubmit={async () => {}} />)

    const bubbles = [...container.querySelectorAll(".bg-ai-bg")].filter(el => el.closest("[role=status]") === null)
    expect(bubbles.map(b => b.textContent)).toEqual(["Tienes dos tarjetas."])
  })
})
