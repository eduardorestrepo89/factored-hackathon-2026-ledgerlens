"use client"

import { useEffect, useRef, useState } from "react"
import { flushSync } from "react-dom"
import { AgentDesk } from "./AgentDesk"
import { ChatHeader } from "./ChatHeader"
import { ChatInput } from "./ChatInput"
import { ChatMessages } from "./ChatMessages"
import { Message, MessageSegment, ToolCall } from "./types"

import { useGlobal } from "@/app/context/GlobalContext"
import { AgentCoreClient } from "@/lib/agentcore-client"
import type { AgentPattern } from "@/lib/agentcore-client"
import { submitFeedback } from "@/services/feedbackService"
import { useAuth } from "react-oidc-context"
import { useDefaultTool, useToolRenderer } from "@/hooks/useToolRenderer"
import { findHandOff, HAND_OFF_DELAY_MS, HAND_OFF_TOOL, phaseOf, queueFor, type HandOff } from "@/lib/handoff"
import { HandOffTicket } from "./HandOffTicket"
import { ToolCallDisplay } from "./ToolCallDisplay"

export default function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [client, setClient] = useState<AgentCoreClient | null>(null)
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID())
  const [handOff, setHandOff] = useState<HandOff | null>(null)
  // the pending split, cancelled by "Nueva conversación"
  const handOffTimer = useRef<number | undefined>(undefined)
  const phase = phaseOf(handOff, messages)

  const { isLoading, setIsLoading } = useGlobal()
  const auth = useAuth()

  // Ref for message container to enable auto-scrolling
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Register default tool renderer (wildcard "*")
  useDefaultTool(({ name, args, status, result }) => (
    <ToolCallDisplay name={name} args={args} status={status} result={result} />
  ))

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
          pattern: (config.agentPattern || "strands-single-agent") as AgentPattern,
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

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  const sendMessage = async (userMessage: string) => {
    if (!userMessage.trim() || !client) return

    // Clear any previous errors
    setError(null)

    // Add user message to chat
    const newUserMessage: Message = {
      role: "user",
      content: userMessage,
      timestamp: new Date().toISOString(),
    }

    setMessages(prev => [...prev, newUserMessage])
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
    const segments: MessageSegment[] = []
    const toolCallMap = new Map<string, ToolCall>()

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
      await client.invoke(userMessage, sessionId, accessToken, event => {
        switch (event.type) {
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
      })
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Unknown error"
      setError(`Failed to get response: ${errorMessage}`)
      console.error("Error invoking AgentCore:", err)

      // Update the assistant message with error
      setMessages(prev => {
        const updated = [...prev]
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content:
            "I apologize, but I encountered an error processing your request. Please try again.",
        }
        return updated
      })
    } finally {
      // The turn has finished streaming, so the goodbye is on screen: split after a pause
      const found = findHandOff([{ ...assistantResponse, segments }])
      if (found) {
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
      setError(`Failed to submit feedback: ${errorMessage}`)
    }
  }

  // Start a new chat by clearing messages and generating a fresh session ID.
  // A new UUID is required so the backend treats this as a distinct conversation context.
  const startNewChat = () => {
    clearTimeout(handOffTimer.current)
    setHandOff(null)
    setMessages([])
    setInput("")
    setError(null)
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

  return (
    <div className="flex h-screen w-full flex-col bg-page">
      {/* Fixed header */}
      <div className="flex-none">
        <ChatHeader onNewChat={startNewChat} canStartNewChat={hasAssistantMessages} phase={phase} />
        {error && (
          <div className="bg-red-50 border-l-4 border-red-500 p-4 mx-4 mt-2">
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}
      </div>

      {handOff ? (
        // Hand-off split: the customer's phone and the human agent's desk
        <div className="grid min-h-0 flex-1 gap-4 overflow-y-auto p-4 min-[1100px]:grid-cols-[400px_minmax(0,1fr)] min-[1100px]:overflow-hidden">
          <section aria-label="Cliente" className="flex min-h-0 flex-col gap-2">
            <h2 className="text-[11px] font-semibold uppercase tracking-[.08em] text-muted-foreground">
              Cliente · App
            </h2>
            <div className="flex min-h-[560px] flex-1 flex-col overflow-hidden rounded-[28px] border bg-white shadow-[0_18px_40px_-28px_hsl(200_40%_10%/.45)]">
              <div className="flex items-center justify-between gap-2 border-b px-4 py-3">
                <b>LATAM Bank</b>
                <span className="rounded-full bg-human-bg px-2.5 py-0.5 text-xs font-medium text-human">
                  {phase === "joined" ? "Laura · Persona" : `En cola · ${queueFor(handOff.reason)}`}
                </span>
              </div>
              <div className="min-h-0 flex-1">
                <ChatMessages
                  messages={messages}
                  messagesEndRef={messagesEndRef}
                  sessionId={sessionId}
                  onFeedbackSubmit={handleFeedbackSubmit}
                />
              </div>
              <ChatInput input={input} setInput={setInput} handleSubmit={handleSubmit} isLoading={isLoading} />
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
        // Initial state - input in the middle
        <>
          <div className="grow" />

          <div className="text-center mb-6">
            <h2 className="text-2xl font-bold text-gray-800">Hola, soy LedgerLens</h2>
            <p className="text-gray-600 mt-2">
              Pregúntame por tus tarjetas, tus compras o un cargo que no reconozcas.
            </p>
          </div>

          <div className="px-4 mb-16 max-w-4xl mx-auto w-full">
            <ChatInput
              input={input}
              setInput={setInput}
              handleSubmit={handleSubmit}
              isLoading={isLoading}
            />
          </div>

          <div className="grow" />
        </>
      ) : (
        // Chat in progress - normal layout
        <>
          <div className="grow overflow-hidden">
            <div className="max-w-4xl mx-auto w-full h-full">
              <ChatMessages
                messages={messages}
                messagesEndRef={messagesEndRef}
                sessionId={sessionId}
                onFeedbackSubmit={handleFeedbackSubmit}
              />
            </div>
          </div>

          <div className="flex-none">
            <div className="max-w-4xl mx-auto w-full">
              <ChatInput
                input={input}
                setInput={setInput}
                handleSubmit={handleSubmit}
                isLoading={isLoading}
                placeholder={handOffPending ? "Conectando con una persona…" : undefined}
              />
            </div>
          </div>
        </>
      )}
    </div>
  )
}
