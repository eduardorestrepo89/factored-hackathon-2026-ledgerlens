// Define message types
// "human" is the human agent (Laura) after a hand-off; those messages never reach AgentCore
export type MessageRole = "user" | "assistant" | "human"

export type ToolCallStatus = "streaming" | "executing" | "complete"

export interface ToolCall {
  toolUseId: string
  name: string
  input: string
  result?: string
  status: ToolCallStatus
}

/** A tool call the agent paused until the customer answers Yes or No (agent tools/confirmation_hook.py). */
export interface Confirmation {
  id: string
  tool: string
  toolUseId: string
  details: Record<string, unknown>
  /** How it was answered: a button, or "typed" when the customer wrote instead. */
  answer?: "yes" | "no" | "typed"
}

export type MessageSegment =
  | { type: "text"; content: string }
  | { type: "tool"; toolCall: ToolCall }
  | { type: "confirm"; confirm: Confirmation }

export interface Message {
  role: MessageRole
  content: string
  timestamp: string
  segments?: MessageSegment[]
}

// Define chat session types
export interface ChatSession {
  id: string
  name: string
  history: Message[]
  startDate: string
  endDate: string
}
