"use client"

import { useEffect, useRef, useState } from "react"
import { flushSync } from "react-dom"
import { ReceiptText, RotateCcw, ScanSearch } from "lucide-react"
import { Button } from "@/components/ui/button"
import { AgentDesk } from "./AgentDesk"
import { ChatHeader } from "./ChatHeader"
import { ChatInput } from "./ChatInput"
import { ChatMessages } from "./ChatMessages"
import { ConfirmContext } from "./ConfirmCard"
import { BiometricCheck, Confirmation, Message, MessageSegment, ToolCall } from "./types"

import { useGlobal } from "@/app/context/GlobalContext"
import { AgentCoreClient } from "@/lib/agentcore-client"
import { submitFeedback } from "@/services/feedbackService"
import { useAuth } from "react-oidc-context"
import { useDefaultTool, useToolRenderer } from "@/hooks/useToolRenderer"
import { findHandOff, HAND_OFF_DELAY_MS, HAND_OFF_TOOL, phaseOf, queueFor, type HandOff } from "@/lib/handoff"
import { useI18n } from "@/lib/i18n"
import { HandOffTicket } from "./HandOffTicket"
import { LensMark } from "./ChatHeader"
import { ToolCallDisplay } from "./ToolCallDisplay"

// The empty chat's ways in
const STARTERS = [
  { key: "starter.1", hint: "starterHint.1", Icon: ScanSearch },
  { key: "starter.2", hint: "starterHint.2", Icon: ReceiptText },
] as const

export default function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [error, setError] = useState<string | null>(null)
  // The message whose turn failed, so the error can offer to send it again
  const [failed, setFailed] = useState<string | null>(null)
  const [client, setClient] = useState<AgentCoreClient | null>(null)
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID())
  const [handOff, setHandOff] = useState<HandOff | null>(null)
  // the pending split, cancelled by "Nueva conversación"
  const handOffTimer = useRef<number | undefined>(undefined)
  // bumped by "Nueva conversación", so a turn still streaming from the old chat can't split the new one
  const conversation = useRef(0)
  const phase = phaseOf(handOff, messages)

  const { isLoading, setIsLoading } = useGlobal()
  const auth = useAuth()
  const { lang, t } = useI18n()

  // Register default tool renderer (wildcard "*")
  useDefaultTool(props => <ToolCallDisplay {...props} />)

  // The hand-off renders as a ticket. It carries the shared view-transition name until the
  // split; then the desk's case card takes the name over and the ticket morphs into it.
  useToolRenderer(HAND_OFF_TOOL, props => <HandOffTicket {...props} tagged={phase === "ai"} />)

  // Load agent configuration and create client on mount
  useEffect(() => {
    async function loadConfig() {
      try {
        const response = await fetch("/aws-exports.json")
        if (!response.ok) {
          throw new Error("Failed to load configuration")
        }
        const config = await response.json()

        if (!config.agentRuntimeArn) {
          throw new Error("Agent Runtime ARN not found in configuration")
        }

        const agentClient = new AgentCoreClient({
          runtimeArn: config.agentRuntimeArn,
          region: config.awsRegion || "us-east-1",
        })

        setClient(agentClient)
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : "Unknown error"
        setError(`Configuration error: ${errorMessage}`)
        console.error("Failed to load agent configuration:", err)
      }
    }

    loadConfig()
  }, [])

  // `answer` resumes a tool call the agent paused for the customer's Yes/No. After a biometric
  // check the card shows the outcome, so the answer goes to the agent without a bubble
  const sendMessage = async (
    userMessage: string,
    answer?: { confirm: Confirmation; approved: boolean; check?: BiometricCheck }
  ) => {
    if (!userMessage.trim() || !client) return

    // Clear any previous errors
    setError(null)
    setFailed(null)

    // Add user message to chat
    const newUserMessage: Message = {
      role: "user",
      content: userMessage,
      timestamp: new Date().toISOString(),
    }

    // Close the open Yes/No cards: the clicked one with its answer, any other as answered in writing
    const closed = (s: MessageSegment): MessageSegment =>
      s.type !== "confirm" || s.confirm.answer
        ? s
        : {
            type: "confirm",
            confirm: {
              ...s.confirm,
              answer:
                s.confirm.id === answer?.confirm.id ? (answer.check ?? (answer.approved ? "yes" : "no")) : "typed",
            },
          }
    setMessages(prev => [
      ...prev.map(m => (m.segments ? { ...m, segments: m.segments.map(closed) } : m)),
      ...(answer?.check ? [] : [newUserMessage]),
    ])
    setInput("")
    // ponytail: after the hand-off a person owns the chat, so the bot is never called again
    if (handOff) return
    setIsLoading(true)

    // Create placeholder for assistant response
    const assistantResponse: Message = {
      role: "assistant",
      content: "",
      timestamp: new Date().toISOString(),
    }

    setMessages(prev => [...prev, assistantResponse])

    // Outside the try so the finally block can look for a hand-off in what streamed
    const turnConversation = conversation.current
    const segments: MessageSegment[] = []
    const toolCallMap = new Map<string, ToolCall>()
    // A confirmed call runs in this turn without being announced again: show it here, so its
    // result (and a hand-off's ticket) lands in this message
    if (answer?.approved) {
      const tc: ToolCall = {
        toolUseId: answer.confirm.toolUseId,
        name: answer.confirm.tool,
        input: JSON.stringify(answer.confirm.details),
        status: "executing",
      }
      toolCallMap.set(tc.toolUseId, tc)
      segments.push({ type: "tool", toolCall: tc })
    }

    try {
      // Get auth token from react-oidc-context
      const accessToken = auth.user?.access_token

      if (!accessToken) {
        throw new Error("Authentication required. Please log in again.")
      }

      const updateMessage = () => {
        // Build content from text segments for backward compat
        const content = segments
          .filter((s): s is Extract<MessageSegment, { type: "text" }> => s.type === "text")
          .map(s => s.content)
          .join("")

        setMessages(prev => {
          const updated = [...prev]
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            content,
            segments: [...segments],
          }
          return updated
        })
      }

      // User identity is extracted server-side from the validated JWT token,
      // not passed as a parameter — prevents impersonation via prompt injection.
      const extra = answer ? { confirmations: [{ interruptId: answer.confirm.id, approved: answer.approved }] } : {}
      await client.invoke(userMessage, sessionId, accessToken, event => {
        switch (event.type) {
          case "confirmation": {
            // The paused tool call becomes a Yes/No card
            const i = segments.findIndex(s => s.type === "tool" && s.toolCall.toolUseId === event.toolUseId)
            if (i >= 0) segments.splice(i, 1)
            toolCallMap.delete(event.toolUseId)
            const { id, tool, toolUseId, details } = event
            segments.push({ type: "confirm", confirm: { id, tool, toolUseId, details } })
            updateMessage()
            break
          }
          case "text": {
            // If text arrives after a tool segment, mark all pending tools as complete
            const prev = segments[segments.length - 1]
            if (prev && prev.type === "tool") {
              for (const tc of toolCallMap.values()) {
                if (tc.status === "streaming" || tc.status === "executing") {
                  tc.status = "complete"
                }
              }
            }
            // Append to last text segment, or create new one
            const last = segments[segments.length - 1]
            if (last && last.type === "text") {
              last.content += event.content
            } else {
              segments.push({ type: "text", content: event.content })
            }
            updateMessage()
            break
          }
          case "tool_use_start": {
            const tc: ToolCall = {
              toolUseId: event.toolUseId,
              name: event.name,
              input: "",
              status: "streaming",
            }
            toolCallMap.set(event.toolUseId, tc)
            segments.push({ type: "tool", toolCall: tc })
            updateMessage()
            break
          }
          case "tool_use_delta": {
            const tc = toolCallMap.get(event.toolUseId)
            if (tc) {
              tc.input += event.input
            }
            updateMessage()
            break
          }
          case "tool_result": {
            const tc = toolCallMap.get(event.toolUseId)
            if (tc) {
              tc.result = event.result
              tc.status = "complete"
            }
            updateMessage()
            break
          }
          case "message": {
            if (event.role === "assistant") {
              for (const tc of toolCallMap.values()) {
                if (tc.status === "streaming") tc.status = "executing"
              }
              updateMessage()
            }
            break
          }
        }
      }, extra)
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Unknown error"
      setError(t("responseFailed", { error: errorMessage }))
      setFailed(userMessage)
      console.error("Error invoking AgentCore:", err)

      // Update the assistant message with error
      setMessages(prev => {
        const updated = [...prev]
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: t("agentError"),
        }
        return updated
      })
    } finally {
      // The turn has finished streaming, so the goodbye is on screen: split after a pause
      const found = findHandOff([{ ...assistantResponse, segments }])
      if (found && conversation.current === turnConversation) {
        handOffTimer.current = window.setTimeout(() => openHandOff(found), HAND_OFF_DELAY_MS)
      }
      setIsLoading(false)
    }
  }

  // Animate into the split with the View Transitions API where the browser has it
  const openHandOff = (found: HandOff) => {
    const apply = () => flushSync(() => setHandOff(current => current ?? found))
    if ("startViewTransition" in document) document.startViewTransition(apply)
    else apply()
  }

  // Send the failed message again, dropping it and its error reply from the thread first
  const retry = () => {
    if (!failed) return
    setMessages(prev =>
      prev[prev.length - 2]?.role === "user" && prev[prev.length - 1]?.role === "assistant"
        ? prev.slice(0, -2)
        : prev
    )
    sendMessage(failed)
  }

  // Handle form submission
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()

    sendMessage(input)
  }

  // Handle feedback submission
  const handleFeedbackSubmit = async (
    messageContent: string,
    feedbackType: "positive" | "negative",
    comment: string
  ) => {
    try {
      // Use ID token for API Gateway Cognito authorizer (not access token)
      const idToken = auth.user?.id_token

      if (!idToken) {
        throw new Error("Authentication required. Please log in again.")
      }

      await submitFeedback(
        {
          sessionId,
          message: messageContent,
          feedbackType,
          comment: comment || undefined,
        },
        idToken
      )

      console.log("Feedback submitted successfully")
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Unknown error"
      console.error("Error submitting feedback:", err)
      setError(t("feedbackFailed", { error: errorMessage }))
    }
  }

  // Start a new chat by clearing messages and generating a fresh session ID.
  // A new UUID is required so the backend treats this as a distinct conversation context.
  const startNewChat = () => {
    conversation.current++
    clearTimeout(handOffTimer.current)
    setHandOff(null)
    setMessages([])
    setInput("")
    setError(null)
    setFailed(null)
    setSessionId(crypto.randomUUID())
  }

  // Laura's messages stay in the browser: they never reach AgentCore
  const sendAsAgent = (content: string) =>
    setMessages(prev => [...prev, { role: "human", content, timestamp: new Date().toISOString() }])

  // Check if this is the initial state (no messages)
  const isInitialState = messages.length === 0

  // Check if there are any assistant messages
  const hasAssistantMessages = messages.some(message => message.role === "assistant")

  // Beat 1: the hand-off is done and the split is about to happen
  const handOffPending = !handOff && findHandOff(messages) !== null

  const profile = auth.user?.profile
  const customerName = String(profile?.name ?? profile?.given_name ?? "")
  const firstName = customerName.trim().split(/\s+/)[0]

  // A Yes/No card is open (the agent paused a call): the customer answers with its buttons,
  // so the composer waits
  const confirming =
    !isLoading && !handOff && messages.some(m => m.segments?.some(s => s.type === "confirm" && !s.confirm.answer))

  return (
    <div className="flex h-screen w-full flex-col bg-page">
      {/* Fixed header */}
      <div className="flex-none">
        <ChatHeader onNewChat={startNewChat} canStartNewChat={hasAssistantMessages} phase={phase} />
        {error && (
          <div
            role="alert"
            className="mx-4 mt-3 flex items-center justify-between gap-3 rounded-2xl bg-destructive/10 px-4 py-3 text-sm text-destructive"
          >
            <span>{error}</span>
            {failed && !isLoading && (
              <Button
                size="sm"
                variant="outline"
                onClick={retry}
                className="shrink-0 rounded-full border-destructive/40 text-destructive hover:text-destructive"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                {t("retry")}
              </Button>
            )}
          </div>
        )}
      </div>

      {handOff ? (
        // Hand-off split: the customer's phone and the human agent's desk
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-5 overflow-y-auto p-4 sm:p-5 min-[1100px]:grid-cols-[400px_minmax(0,1fr)] min-[1100px]:overflow-hidden">
          <section aria-label="Cliente" className="flex flex-col gap-2 min-[1100px]:min-h-0">
            <h2 className="px-2 text-sm font-medium text-muted-foreground">{t("customerApp")}</h2>
            {/* The phone: an ink bezel around the customer's own app */}
            <div className="flex min-h-[560px] flex-1 flex-col rounded-[40px] bg-ink p-2 shadow-[0_30px_60px_-30px_rgb(22_26_51/.6)]">
              <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[32px] bg-page">
                <div className="flex items-center justify-between gap-2 bg-card px-4 py-3">
                  <span className="flex items-center gap-2 font-semibold">
                    <LensMark className="h-6 w-6" phase={phase} />
                    LATAM Bank
                  </span>
                  <span className="rounded-full bg-human-bg px-2.5 py-0.5 text-xs font-medium text-human">
                    {phase === "joined" ? t("lauraTag") : t("inQueue", { queue: queueFor(handOff.reason, lang) })}
                  </span>
                </div>
                <div className="min-h-0 flex-1">
                  <ChatMessages
                    messages={messages}
                    sessionId={sessionId}
                    onFeedbackSubmit={handleFeedbackSubmit}
                  />
                </div>
                <ChatInput input={input} setInput={setInput} handleSubmit={handleSubmit} isLoading={isLoading} className="p-2 sm:p-2" />
              </div>
            </div>
          </section>
          <AgentDesk
            handOff={handOff}
            phase={phase}
            messages={messages}
            customerName={customerName}
            sessionId={sessionId}
            onSend={sendAsAgent}
          />
        </div>
      ) : isInitialState ? (
        // Initial state: the greeting and the composer, with three ways to start
        <div className="flex min-h-0 flex-1 flex-col justify-center overflow-y-auto px-4 sm:px-6">
          <div className="mx-auto w-full max-w-2xl py-10">
            <LensMark className="h-12 w-12" />
            <h2 className="display mt-6 text-5xl font-light sm:text-7xl">
              {firstName ? t("greetingNamed", { name: firstName }) : t("greeting")}
            </h2>
            <p className="mt-4 max-w-[52ch] text-lg leading-relaxed text-muted-foreground">
              {firstName ? t("greetingNamedBody") : t("greetingBody")}
            </p>
            <ChatInput
              input={input}
              setInput={setInput}
              handleSubmit={handleSubmit}
              isLoading={isLoading}
              className="mt-8 p-0 sm:p-0"
            />
            <div role="group" aria-label={t("starters")} className="mt-5 divide-y overflow-hidden rounded-3xl border bg-card">
              {STARTERS.map(({ key, hint, Icon }) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => sendMessage(t(key))}
                  disabled={!client || isLoading}
                  className="flex w-full items-center gap-4 px-5 py-4 text-left transition-colors hover:bg-page focus-visible:bg-page disabled:opacity-50"
                >
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-ai-bg text-ai">
                    <Icon className="h-5 w-5" />
                  </span>
                  <span className="min-w-0">
                    <span className="block font-medium">{t(key)}</span>
                    <span className="block text-sm text-muted-foreground">{t(hint)}</span>
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : (
        // Chat in progress - normal layout
        <>
          <div className="grow overflow-hidden">
            <div className="max-w-3xl mx-auto w-full h-full">
              {/* Only the customer's live chat answers Yes/No cards */}
              <ConfirmContext.Provider
                value={isLoading ? null : (confirm, approved, label, check) => sendMessage(label, { confirm, approved, check })}
              >
                <ChatMessages
                  messages={messages}
                  sessionId={sessionId}
                  onFeedbackSubmit={handleFeedbackSubmit}
                  isLoading={isLoading}
                />
              </ConfirmContext.Provider>
            </div>
          </div>

          <div className="flex-none">
            <div className="max-w-3xl mx-auto w-full">
              <ChatInput
                input={input}
                setInput={setInput}
                handleSubmit={handleSubmit}
                isLoading={isLoading}
                disabled={confirming}
                placeholder={
                  confirming ? t("confirmPlaceholder") : handOffPending ? t("connectingToPerson") : undefined
                }
              />
            </div>
          </div>
        </>
      )}
    </div>
  )
}
