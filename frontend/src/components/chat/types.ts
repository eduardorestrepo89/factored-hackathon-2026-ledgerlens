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

export type MessageSegment =
  | { type: "text"; content: string }
  | { type: "tool"; toolCall: ToolCall }

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
