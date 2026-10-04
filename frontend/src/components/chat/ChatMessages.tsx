import { Fragment, RefObject } from "react"
import { Message } from "./types"
import { ChatMessage } from "./ChatMessage"

interface ChatMessagesProps {
  messages: Message[]
  messagesEndRef?: RefObject<HTMLDivElement | null>
  sessionId: string
  onFeedbackSubmit: (
    messageContent: string,
    feedbackType: "positive" | "negative",
    comment: string
  ) => Promise<void>
  hideFeedback?: boolean
}

const time = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })

export function ChatMessages({
  messages,
  messagesEndRef,
  sessionId,
  onFeedbackSubmit,
  hideFeedback = false,
}: ChatMessagesProps) {
  // Laura's first message is the moment she joins the conversation
  const firstHuman = messages.findIndex(m => m.role === "human")

  return (
    <div
      className={`h-full p-4 space-y-4 w-full ${
        messages.length > 0 ? "overflow-y-auto" : "overflow-hidden"
      }`}
    >
      {messages.length === 0 ? (
        <div className="flex items-center justify-center h-full text-gray-400">
          Empieza una conversación
        </div>
      ) : (
        messages.map((message, index) => (
          <Fragment key={index}>
            {index === firstHuman && (
              <p className="text-center text-[11px] font-semibold uppercase tracking-[.06em] text-muted-foreground">
                Laura se unió a la conversación · {time(message.timestamp)}
              </p>
            )}
            <ChatMessage
              message={message}
              sessionId={sessionId}
              hideFeedback={hideFeedback}
              onFeedbackSubmit={async (feedbackType, comment) => {
                await onFeedbackSubmit(message.content, feedbackType, comment)
              }}
            />
          </Fragment>
        ))
      )}
      <div ref={messagesEndRef} />
    </div>
  )
}
