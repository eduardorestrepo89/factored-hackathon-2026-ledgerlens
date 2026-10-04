import { afterEach, describe, it, expect, vi } from "vitest"
import { render } from "@testing-library/react"
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
