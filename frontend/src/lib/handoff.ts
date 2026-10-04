import type { Message, MessageSegment } from "@/components/chat/types"
import { bareToolName } from "@/hooks/useToolRenderer"

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

// The ticket shows these to the customer, so they never claim the bank confirmed fraud
const REASON_LABEL: Record<HandOffReason, string> = {
  FRAUD_CONFIRMED: "Cargo no reconocido",
  CUSTOMER_REQUEST: "Pidió hablar con una persona",
  UNRESOLVED: "El asistente no pudo resolverlo",
  OUT_OF_SCOPE: "Fuera del alcance del asistente",
}

export const reasonLabel = (reason: string): string => REASON_LABEL[reason as HandOffReason] ?? reason

export const queueFor = (reason: string): string => (reason === "FRAUD_CONFIRMED" ? "Fraudes" : "Servicio general")

const NEXT_STEP: Record<HandOffReason, string> = {
  FRAUD_CONFIRMED: "Voy a revisar si hubo otros intentos con tus tarjetas y te cuento por aquí mismo.",
  CUSTOMER_REQUEST: "Cuéntame en qué te puedo ayudar y lo revisamos juntos.",
  UNRESOLVED: "Voy a revisar tu caso con más detalle y te confirmo por aquí mismo.",
  OUT_OF_SCOPE: "Esa solicitud la reviso yo. Dame un momento para validar tus datos.",
}

/** Two replies Laura can send as they are: a greeting that shows she has the case, then a next step. */
export function suggestedReplies(handOff: HandOff, customerName: string): [string, string] {
  const firstName = customerName.trim().split(/\s+/)[0]
  const queue = queueFor(handOff.reason)
  const hello = firstName ? `Hola ${firstName}, soy Laura, de ${queue}.` : `Hola, soy Laura, de ${queue}.`
  return [
    `${hello} Ya tengo tu caso ${handOff.hand_off_id} y todo lo que hablaste con el asistente, así que no necesitas repetir nada.`,
    NEXT_STEP[handOff.reason] ?? NEXT_STEP.CUSTOMER_REQUEST,
  ]
}
