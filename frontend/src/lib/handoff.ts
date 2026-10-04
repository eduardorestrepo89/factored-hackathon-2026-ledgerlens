import type { Message, MessageSegment } from "@/components/chat/types"
import { bareToolName } from "@/hooks/useToolRenderer"
import { hasKey, translate, type Lang } from "./i18n"

export const HAND_OFF_TOOL = "human_agent_hand_off"
/** Pause between the end of the goodbye and the split, so the goodbye can be read. */
export const HAND_OFF_DELAY_MS = 600

export type HandOffReason = "FRAUD_CONFIRMED" | "CUSTOMER_REQUEST" | "UNRESOLVED" | "OUT_OF_SCOPE"

/** What human_agent_hand_off returns (spec §2.2). */
export interface HandOffResult {
  hand_off_id: string
  status: string
  priority: "high" | "normal"
  reason: HandOffReason
  customer_id: string
  summary: string
  related_ids: string[]
}

/** The tool result plus what the desk shows from the stream. */
export interface HandOff extends HandOffResult {
  /** The agent's words to the customer around the hand-off, verbatim. */
  goodbye: string
  /** ISO time of the assistant message that made the hand-off. */
  at: string
}

/** ai: the bot owns the chat; connecting: handed off, Laura hasn't written; joined: she has. */
export type Phase = "ai" | "connecting" | "joined"

/** The hand-off result, or null for an error, text that isn't JSON or a missing id. */
export function parseHandOffResult(result: string | undefined): HandOffResult | null {
  if (!result) return null
  try {
    let value: unknown = JSON.parse(result)
    // The Gateway may pass the Lambda's whole {"content":[{"text": <JSON>}]} response through
    const inner = (value as { content?: { text?: unknown }[] } | null)?.content?.[0]?.text
    if (typeof inner === "string") value = JSON.parse(inner)
    if (typeof value === "object" && value !== null && typeof (value as HandOffResult).hand_off_id === "string") {
      const found = value as HandOffResult
      return { ...found, related_ids: Array.isArray(found.related_ids) ? found.related_ids : [] }
    }
  } catch {
    // not JSON: an error text from the Gateway or the Lambda
  }
  return null
}

const textOf = (segments: MessageSegment[]) =>
  segments
    .flatMap(s => (s.type === "text" ? [s.content] : []))
    .join("")
    .trim()

/** The first completed, valid hand-off in the last message, if that message is the agent's. */
export function findHandOff(messages: Message[]): HandOff | null {
  const last = messages[messages.length - 1]
  if (last?.role !== "assistant" || !last.segments) return null
  const segments = last.segments
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i]
    if (seg.type !== "tool" || seg.toolCall.status !== "complete") continue
    if (bareToolName(seg.toolCall.name) !== HAND_OFF_TOOL) continue
    const result = parseHandOffResult(seg.toolCall.result)
    if (!result) continue
    // the goodbye normally follows the tool; if the model said it first, use what came before
    const goodbye = textOf(segments.slice(i + 1)) || textOf(segments.slice(0, i))
    return { ...result, goodbye, at: last.timestamp }
  }
  return null
}

export const phaseOf = (handOff: HandOff | null, messages: Message[]): Phase =>
  !handOff ? "ai" : messages.some(m => m.role === "human") ? "joined" : "connecting"

export const reasonLabel = (reason: string, lang: Lang = "es"): string => {
  const key = `reason.${reason}`
  return hasKey(key) ? translate(lang, key) : reason
}

export const queueFor = (reason: string, lang: Lang = "es"): string =>
  translate(lang, reason === "FRAUD_CONFIRMED" ? "queueFraud" : "queueGeneral")

/** Two replies Laura can send as they are: a greeting that shows she has the case, then a next step. */
export function suggestedReplies(handOff: HandOff, customerName: string, lang: Lang = "es"): [string, string] {
  const name = customerName.trim().split(/\s+/)[0]
  const queue = queueFor(handOff.reason, lang)
  const hello = translate(lang, name ? "helloNamed" : "hello", { name, queue })
  const next = `next.${handOff.reason}`
  return [
    `${hello} ${translate(lang, "haveCase", { id: handOff.hand_off_id })}`,
    translate(lang, hasKey(next) ? next : "next.CUSTOMER_REQUEST"),
  ]
}
