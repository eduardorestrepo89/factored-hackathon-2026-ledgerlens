"use client"

import { useState } from "react"
import { Sparkles, ThumbsDown, ThumbsUp, User } from "lucide-react"
import { Message } from "./types"
import { FeedbackDialog } from "./FeedbackDialog"
import { getToolRenderer } from "@/hooks/useToolRenderer"
import { MarkdownRenderer } from "./MarkdownRenderer"

interface ChatMessageProps {
  message: Message
  sessionId: string
  onFeedbackSubmit: (feedbackType: "positive" | "negative", comment: string) => Promise<void>
  hideFeedback?: boolean
}

const TAG = "flex items-center gap-1 text-[11px] font-semibold uppercase tracking-[.06em]"
const BUBBLE = "rounded-2xl rounded-tl-sm px-3 py-2"

export function ChatMessage({
  message,
  sessionId: _sessionId,
  onFeedbackSubmit,
  hideFeedback = false,
}: ChatMessageProps) {
  const [isDialogOpen, setIsDialogOpen] = useState(false)
  const [selectedFeedbackType, setSelectedFeedbackType] = useState<"positive" | "negative">(
    "positive"
  )
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false)

  const formatTime = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    })
  }

  const handleFeedbackClick = (type: "positive" | "negative") => {
    setSelectedFeedbackType(type)
    setIsDialogOpen(true)
  }

  const handleFeedbackSubmit = async (comment: string) => {
    await onFeedbackSubmit(selectedFeedbackType, comment)
    setFeedbackSubmitted(true)
  }

  const renderAssistantContent = () => {
    // If segments exist, render them in order (interleaved text bubbles + tools)
    if (message.segments && message.segments.length > 0) {
      return message.segments.map((seg, i) => {
        if (seg.type === "text") {
          return (
            <div key={i} className={`${BUBBLE} bg-ai-bg`}>
              <MarkdownRenderer content={seg.content} />
            </div>
          )
        }
        const render = getToolRenderer(seg.toolCall.name)
        if (!render) return null
        return (
          <div key={seg.toolCall.toolUseId} className="my-1">
            {render({
              name: seg.toolCall.name,
              args: seg.toolCall.input,
              status: seg.toolCall.status,
              result: seg.toolCall.result,
            })}
          </div>
        )
      })
    }
    // Fallback: just render content as markdown
    return message.content ? (
      <div className={`${BUBBLE} bg-ai-bg`}>
        <MarkdownRenderer content={message.content} />
      </div>
    ) : null
  }

  const bubbleClass =
    message.role === "user"
      ? "rounded-2xl rounded-br-sm bg-brand-dark p-3 text-white whitespace-pre-wrap"
      : message.role === "human"
        ? `${BUBBLE} bg-human-bg whitespace-pre-wrap`
        : "flex flex-col gap-2 text-gray-800"

  return (
    <div className={`flex flex-col gap-1 ${message.role === "user" ? "items-end" : "items-start"}`}>
      {message.role === "assistant" && (
        <span className={`${TAG} text-ai`}>
          <Sparkles className="h-3 w-3" />
          Asistente IA
        </span>
      )}
      {message.role === "human" && (
        <span className={`${TAG} text-human`}>
          <User className="h-3 w-3" />
          Laura · Persona
        </span>
      )}
      <div className={`max-w-[85%] break-words ${bubbleClass}`}>
        {message.role === "assistant" ? renderAssistantContent() : message.content}
      </div>

      {/* Timestamp and Feedback buttons for assistant messages */}
      <div className="flex items-center gap-2 px-1">
        <div className="text-xs text-gray-500">{formatTime(message.timestamp)}</div>

        {/* Show feedback buttons only for assistant messages with content */}
        {!hideFeedback && message.role === "assistant" && message.content && (
          <div className="flex items-center gap-1 ml-2">
            <button
              onClick={() => handleFeedbackClick("positive")}
              disabled={feedbackSubmitted}
              className="p-1 text-gray-400 hover:text-green-600 hover:bg-green-50 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              aria-label="Positive feedback"
              title="Good response"
            >
              <ThumbsUp size={14} />
            </button>
            <button
              onClick={() => handleFeedbackClick("negative")}
              disabled={feedbackSubmitted}
              className="p-1 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              aria-label="Negative feedback"
              title="Bad response"
            >
              <ThumbsDown size={14} />
            </button>
            {feedbackSubmitted && (
              <span className="text-xs text-gray-500 ml-1">Thanks for your feedback!</span>
            )}
          </div>
        )}
      </div>

      {/* Feedback Dialog */}
      <FeedbackDialog
        isOpen={isDialogOpen}
        onClose={() => setIsDialogOpen(false)}
        onSubmit={handleFeedbackSubmit}
        feedbackType={selectedFeedbackType}
      />
    </div>
  )
}
