import { Fragment, useLayoutEffect, useRef } from "react"
import { Message } from "./types"
import { ChatMessage } from "./ChatMessage"
import { useI18n } from "@/lib/i18n"

interface ChatMessagesProps {
  messages: Message[]
  sessionId: string
  onFeedbackSubmit: (
    messageContent: string,
    feedbackType: "positive" | "negative",
    comment: string
  ) => Promise<void>
  hideFeedback?: boolean
  isLoading?: boolean
}

const time = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })

export function ChatMessages({
  messages,
  sessionId,
  onFeedbackSubmit,
  hideFeedback = false,
  isLoading = false,
}: ChatMessagesProps) {
  const { t } = useI18n()
  // Laura's first message is the moment she joins the conversation
  const firstHuman = messages.findIndex(m => m.role === "human")

  // Each copy of the thread (chat, phone, desk mirror) keeps its own scroll at the bottom.
  // A layout effect also runs on mount, so a thread mounted by the split opens at the
  // ticket and the goodbye; scrolling the container never moves the page around it.
  const containerRef = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    const el = containerRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  return (
    <div
      ref={containerRef}
      className={`h-full w-full space-y-5 p-4 sm:p-6 ${
        messages.length > 0 ? "overflow-y-auto" : "overflow-hidden"
      }`}
    >
      {messages.length === 0 ? (
        <div className="flex items-center justify-center h-full text-muted-foreground">
          {t("emptyThread")}
        </div>
      ) : (
        messages.map((message, index) => (
          <Fragment key={index}>
            {index === firstHuman && (
              <p className="mx-auto flex w-fit items-center gap-2 rounded-full bg-human-bg px-3 py-1 text-xs font-medium text-human">
                <span className="h-1.5 w-1.5 rounded-full bg-mango" />
                {t("lauraJoined", { time: time(message.timestamp) })}
              </p>
            )}
            <ChatMessage
              message={message}
              sessionId={sessionId}
              hideFeedback={hideFeedback}
              typing={isLoading && index === messages.length - 1}
              onFeedbackSubmit={async (feedbackType, comment) => {
                await onFeedbackSubmit(message.content, feedbackType, comment)
              }}
            />
          </Fragment>
        ))
      )}
    </div>
  )
}
