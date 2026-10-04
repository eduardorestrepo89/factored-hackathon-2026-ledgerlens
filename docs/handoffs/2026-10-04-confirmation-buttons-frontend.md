# Handoff: Yes/No confirmation buttons in the chat frontend

**For:** the agent that owns the frontend (`frontend/`).
**From:** the backend session, 2026-10-04.
**Status (updated 2026-10-04):**
- **Backend:** prompt **v8**: `block_credit_card` now uses the same buttons as `open_claim` and
  `human_agent_hand_off`. Deployed 2026-10-04 11:14 UTC, runtime version 4 (see "Deploy record" at the end).
- **Frontend:** written and tested, then reverted so the frontend owner can apply it on top of their own work. A
  complete reference diff is at the end.
- **Frontend, applied (2026-10-04):** on branch `feat/frontend-3d-home` (worktree `.claude/worktrees/frontend-3d-home`),
  restyled to the redesign: `components/chat/ConfirmCard.tsx`, copy in `lib/i18n.tsx`, and the composer stays locked
  while a card is open. Tests: `confirmation-flow.test.tsx` (claim Yes/No, hand-off Yes → desk split),
  `confirm-card.test.tsx`, `strands-parser.test.ts`.
- **End-to-end proof:** a separate research run exercised the real entrypoint with a real Strands `Agent`, a scripted
  model and the real AgentCore Memory session manager; all 9 scenarios in "Verified behaviour" below passed on
  strands-agents 1.32.0 (deployed) and on 1.57.2 (planned upgrade, contract unchanged).

## Why

`block_credit_card`, `open_claim` and `human_agent_hand_off` must not run on the model's word alone. The backend
pauses all three until the customer taps **Yes** or **No**. Until the frontend shows those buttons, a card block,
claim or hand-off stays paused: the customer sees a tool spinner and no question, because prompt v8 tells the
model not to ask in text first (the buttons do the asking). **This is the only thing left for these three
actions to work.**

The text consent check (`consent_hook.py`) is gone: the click is the only consent. After a Yes, the backend sets
`customer_confirmed: true` on the block or claim itself, so the value Cedar checks comes from the click.

## Backend contract (already deployed)

Code: `agent/ledgerlens/tools/confirmation_hook.py`, wired in `agent/ledgerlens/ledgerlens_agent.py`.

### 1. The runtime streams a `confirmation` event when a tool is paused

On the same SSE stream as everything else, as its own `data:` line, just before the final `result` event:

```json
{"confirmation": {
  "id": "<interrupt id>",
  "tool": "open_claim",
  "toolUseId": "tooluse_abc123",
  "details": {"transaction_ids": ["TRX-23BIJAU4GL46ATPW9STY"], "claim_type": "fraud", "customer_statement": "..."}
}}
```

- `tool` is the bare name: `block_credit_card`, `open_claim` or `human_agent_hand_off`.
- `toolUseId` is the id of the tool call that was already announced earlier in the same stream (`current_tool_use`
  deltas). That tool segment never gets a result in this turn.
- `details` is the tool input without `customer_id` and `customer_confirmed`:
  - card block: `{"card_last4": "4497", "reason": "suspected_fraud" | "lost" | "stolen" | "customer_request"}`;
  - claim: `transaction_ids`, `claim_type`, `customer_statement`;
  - hand-off: `reason`, `priority`, `summary`, `related_ids`.
  Don't show internal ids or the hand-off summary to the customer.
- For a card block, the model's text just before the card already says the block can't be undone here.
  Suggested card copy (es): "¿Bloqueamos tu tarjeta •••• 4497?".
- The turn then ends (`result` with `stop_reason` `"interrupt"`). There can be more than one confirmation in a
  turn, though prompt v8 makes that rare.

### 2. The click is the next request, with a `confirmations` field

POST body to the runtime (same endpoint, same `runtimeSessionId`):

```json
{"prompt": "Sí", "runtimeSessionId": "...", "confirmations": [{"interruptId": "<id>", "approved": true}]}
```

- `prompt` must be non-empty (the entrypoint requires it); send the button label, it is what shows as the
  customer's bubble.
- `approved: true` runs the paused tool. `false` cancels it, and the model is told not to call it again unless
  the customer asks.
- Every pending confirmation not listed counts as **No**.
- **Typing instead of clicking never approves**, even "sí": the backend cancels the paused call and hands the text
  to the model as the customer's words. If they still want it, the model calls the tool again and a new
  confirmation (new `id`) arrives. So just send typed text as usual, without `confirmations`.

### 3. What streams after a click

The model is not called again before the tool: Strands resumes the saved tool call directly.
- **Yes:** a `message` event (role `user`) with the `toolResult` for the original `toolUseId`, then the model's
  next text (for a hand-off, the goodbye). There is **no new `tool_use_start`** for that tool.
- **No:** a `toolResult` whose text starts with `Not done:`, then the model's text.

### 4. Edge cases (verified)

- **Stale click** (a `confirmations` field when nothing is pending, e.g. a double click): the backend ignores the
  field and treats `prompt` as a normal message, so the model just sees "Sí". Disable the buttons once a card is
  answered so this doesn't happen.
- **Page reload or lost card while a confirmation is pending, same `runtimeSessionId`:** the pause survives on the
  server. The customer's next typed message cancels it (typed text never approves) and reaches the model. A new
  chat (new `runtimeSessionId`) starts clean.
- **Interrupt ids are opaque strings.** Don't parse them; send them back as received.
- **Extra keys on stream events:** today every `data` (text) event also carries Strands' internal invocation state
  (system prompt, messages, tool config). Read only the documented keys (`data`, `current_tool_use`, `delta`,
  `message`, `result`, `confirmation`, lifecycle keys). The backend will strip the rest later; that change won't
  touch these keys.

### 5. Verified behaviour (end-to-end test, 9 scenarios)

1. A paused call streams one `confirmation` event, `details` has no `customer_id`, and the tool doesn't run.
2. Yes, sent to a brand-new agent instance (as on AgentCore Runtime): the tool runs with the token's `customer_id`,
   the model isn't called before it, and there's no new `tool_use_start`.
3. No: the tool result starts with `Not done:` and the model answers.
4. Typed "sí, ábrelo" while paused: the tool never runs, the text reaches the model.
5. A typed question while paused: same, the model answers the question.
6. A stale click after the answer, then normal prompts: all work.
7. Strands itself rejects a plain prompt while paused (`TypeError`); the entrypoint converts it, so the frontend
   never sees that error.
8. Other tools (e.g. `list_credit_cards`) run without any confirmation.
9. A call another hook already cancelled (e.g. no linked customer) is never put to the customer.

## What the frontend has to do

1. **Parser** (`lib/agentcore-client/parsers/strands.ts`): turn `json.confirmation` into a stream event
   `{type: "confirmation", id, tool, toolUseId, details}` (add it to `StreamEvent` in `lib/agentcore-client/types.ts`).
   Check it before the `json.data` branch.
2. **Client** (`lib/agentcore-client/client.ts`): let `invoke` send extra body fields (`confirmations`).
3. **Segment** (`components/chat/types.ts`): a new `MessageSegment` kind
   `{type: "confirm", confirm: {id, tool, toolUseId, details, answer?: "yes" | "no" | "typed"}}`.
4. **On the `confirmation` event** (`ChatInterface.sendMessage`): remove the paused tool's segment (same
   `toolUseId`) and push a `confirm` segment in its place.
5. **Card** (new `components/chat/ConfirmCard.tsx`): title + one line + **Yes / No** buttons, in es/pt/en.
   Suggested copy (es): "¿Abrimos el reclamo?" / "Reclamo por {n} cargo(s) que no reconoces." and
   "¿Te paso con una persona?" / "Una persona de LATAM Bank sigue esta conversación." `{n}` is
   `details.transaction_ids.length`. Once answered, show the answer instead of buttons.
6. **On click:** mark that card answered, then send the label as the customer's message with
   `confirmations: [{interruptId: id, approved}]`.
   - **On Yes, pre-create the tool segment in the new assistant message** (`toolUseId`, `name` = the tool,
     `input` = JSON of `details`, status `executing`) and register it in the turn's `toolCallMap`. The resumed
     tool result only carries the `toolUseId`; without this, the result is dropped and `findHandOff` never sees
     the hand-off, so the split to the agent desk doesn't happen.
   - On No, don't pre-create anything.
7. **When the customer types instead:** close every open card as `answer: "typed"` (no buttons left), send the
   text as normal.
8. **Only the customer's live chat may answer.** The desk mirror (`AgentDesk` renders `ChatMessages` too) and the
   phone view after the split must show the card without buttons. The reference diff does this with a
   `ConfirmContext` provided only around the in-progress chat's `ChatMessages`, and `null` while `isLoading`.

## Verify

- First, confirm the new backend is live: the runtime logs show `[PROMPT] version=v8` on the first message.
- Unit: the parser test and `ConfirmCard` test in the reference diff (13 related tests passed with it).
- Live, persona P07 (`CLI-EX6BOAOEFZHQ`): say you don't recognise the charge and lost the card; after the
  which-card question, the block card for •••• 4497 appears. **No** → nothing is blocked; **Yes** → the read-back
  ("tarjeta 4497 bloqueada") and the recent charges come in the next reply.
- Then ask to dispute the Estación de Servicio charge:
  - the claim card appears, **No** → the agent acknowledges and no claim is opened;
  - ask again, **Yes** → the claim id and resolution time come back in the same reply;
  - ask for a person → hand-off card, **Yes** → ticket, goodbye, split to the agent desk.
- Runtime logs: `[CONFIRM] Customer approved open_claim` / `declined`.
- Note: P07 blocks/claims write to the DSQL database, so the persona keeps that state.

## Backend notes for later

- The backend is on strands-agents **1.32.0**. The entrypoint reads the private `agent._interrupt_state` to know a
  confirmation is pending; Strands has no public API for that yet (issue harness-sdk#4202). Upgrading to 1.57.2 is
  planned after the deadline and keeps this contract byte-for-byte (verified); its built-in `HumanInTheLoop` was
  evaluated and rejected (string-only reason that includes `customer_id`, fixed `CONFIRMATION_FAILED:` message,
  accepts a typed "yes").
- `block_credit_card` moved behind the same buttons in prompt v8 (`CONFIRM_TOOLS` in `confirmation_hook.py`);
  `consent_hook.py` was deleted.

## Deploy record

- 2026-10-04 10:50 UTC: backend deployed (prompt v7 + `ConfirmationHook`). Stack `ledgerlens-bank-assistant`
  `UPDATE_COMPLETE`; AgentCore runtime `ledgerlens_bank_assistant_ledgerlens_agent-Log4xE4K9D` **version 3**,
  `READY`, `MODEL_ID=deepseek.v3.2`. Claims and hand-offs now wait for the buttons.
- 2026-10-04 11:14 UTC: prompt **v8** deployed: card blocks behind the buttons, `customer_confirmed` set by the
  click, text consent check removed. Stack `UPDATE_COMPLETE`; runtime **version 4**, `READY`,
  `MODEL_ID=deepseek.v3.2`. Card blocks, claims and hand-offs now all wait for the buttons.

## Reference implementation (reverted)

Applies on commit `8fb7b5f` (branch `feat/frontend-i18n-dark-mode`), 9 files, +206/-11. The 8 frontend test
failures present on that commit (routing, components and config tests) are unrelated to this change.

```diff
diff --git a/frontend/src/components/chat/ChatInterface.tsx b/frontend/src/components/chat/ChatInterface.tsx
index 98ee7ac..4b2b4f0 100644
--- a/frontend/src/components/chat/ChatInterface.tsx
+++ b/frontend/src/components/chat/ChatInterface.tsx
@@ -6,7 +6,8 @@ import { AgentDesk } from "./AgentDesk"
 import { ChatHeader } from "./ChatHeader"
 import { ChatInput } from "./ChatInput"
 import { ChatMessages } from "./ChatMessages"
-import { Message, MessageSegment, ToolCall } from "./types"
+import { Confirmation, Message, MessageSegment, ToolCall } from "./types"
+import { ConfirmContext } from "./ConfirmCard"
 
 import { useGlobal } from "@/app/context/GlobalContext"
 import { AgentCoreClient } from "@/lib/agentcore-client"
@@ -75,7 +76,8 @@ export default function ChatInterface() {
     loadConfig()
   }, [])
 
-  const sendMessage = async (userMessage: string) => {
+  // `answer` resumes a claim or hand-off the agent paused for the customer's Yes/No
+  const sendMessage = async (userMessage: string, answer?: { confirm: Confirmation; approved: boolean }) => {
     if (!userMessage.trim() || !client) return
 
     // Clear any previous errors
@@ -88,7 +90,21 @@ export default function ChatInterface() {
       timestamp: new Date().toISOString(),
     }
 
-    setMessages(prev => [...prev, newUserMessage])
+    // Close the open Yes/No cards: the clicked one with its answer, any other as answered in writing
+    const closed = (s: MessageSegment): MessageSegment =>
+      s.type !== "confirm" || s.confirm.answer
+        ? s
+        : {
+            type: "confirm",
+            confirm: {
+              ...s.confirm,
+              answer: s.confirm.id === answer?.confirm.id ? (answer.approved ? "yes" : "no") : "typed",
+            },
+          }
+    setMessages(prev => [
+      ...prev.map(m => (m.segments ? { ...m, segments: m.segments.map(closed) } : m)),
+      newUserMessage,
+    ])
     setInput("")
     // ponytail: after the hand-off a person owns the chat, so the bot is never called again
     if (handOff) return
@@ -107,6 +123,18 @@ export default function ChatInterface() {
     const turnConversation = conversation.current
     const segments: MessageSegment[] = []
     const toolCallMap = new Map<string, ToolCall>()
+    // A confirmed tool runs in this turn without being announced again: show it here, so its
+    // result (and a hand-off's ticket) lands in this message
+    if (answer?.approved) {
+      const tc: ToolCall = {
+        toolUseId: answer.confirm.toolUseId,
+        name: answer.confirm.tool,
+        input: JSON.stringify(answer.confirm.details),
+        status: "executing",
+      }
+      toolCallMap.set(tc.toolUseId, tc)
+      segments.push({ type: "tool", toolCall: tc })
+    }
 
     try {
       // Get auth token from react-oidc-context
@@ -136,8 +164,19 @@ export default function ChatInterface() {
 
       // User identity is extracted server-side from the validated JWT token,
       // not passed as a parameter — prevents impersonation via prompt injection.
+      const extra = answer ? { confirmations: [{ interruptId: answer.confirm.id, approved: answer.approved }] } : {}
       await client.invoke(userMessage, sessionId, accessToken, event => {
         switch (event.type) {
+          case "confirmation": {
+            // The paused tool becomes a Yes/No card
+            const i = segments.findIndex(s => s.type === "tool" && s.toolCall.toolUseId === event.toolUseId)
+            if (i >= 0) segments.splice(i, 1)
+            toolCallMap.delete(event.toolUseId)
+            const { type: _type, ...confirm } = event
+            segments.push({ type: "confirm", confirm })
+            updateMessage()
+            break
+          }
           case "text": {
             // If text arrives after a tool segment, mark all pending tools as complete
             const prev = segments[segments.length - 1]
@@ -197,7 +236,7 @@ export default function ChatInterface() {
             break
           }
         }
-      })
+      }, extra)
     } catch (err) {
       const errorMessage = err instanceof Error ? err.message : "Unknown error"
       setError(t("responseFailed", { error: errorMessage }))
@@ -378,12 +417,17 @@ export default function ChatInterface() {
         <>
           <div className="grow overflow-hidden">
             <div className="max-w-3xl mx-auto w-full h-full">
-              <ChatMessages
-                messages={messages}
-                sessionId={sessionId}
-                onFeedbackSubmit={handleFeedbackSubmit}
-                isLoading={isLoading}
-              />
+              {/* Only the customer's live chat answers Yes/No cards */}
+              <ConfirmContext.Provider
+                value={isLoading ? null : (confirm, approved, label) => sendMessage(label, { confirm, approved })}
+              >
+                <ChatMessages
+                  messages={messages}
+                  sessionId={sessionId}
+                  onFeedbackSubmit={handleFeedbackSubmit}
+                  isLoading={isLoading}
+                />
+              </ConfirmContext.Provider>
             </div>
           </div>
 
diff --git a/frontend/src/components/chat/ChatMessage.tsx b/frontend/src/components/chat/ChatMessage.tsx
index c9c5b99..607045e 100644
--- a/frontend/src/components/chat/ChatMessage.tsx
+++ b/frontend/src/components/chat/ChatMessage.tsx
@@ -7,6 +7,7 @@ import { FeedbackDialog } from "./FeedbackDialog"
 import { getToolRenderer } from "@/hooks/useToolRenderer"
 import { MarkdownRenderer } from "./MarkdownRenderer"
 import { LensMark } from "./ChatHeader"
+import { ConfirmCard } from "./ConfirmCard"
 import { useI18n } from "@/lib/i18n"
 
 interface ChatMessageProps {
@@ -67,6 +68,13 @@ export function ChatMessage({
             </div>
           )
         }
+        if (seg.type === "confirm") {
+          return (
+            <div key={seg.confirm.id} className="my-1">
+              <ConfirmCard confirm={seg.confirm} />
+            </div>
+          )
+        }
         const render = getToolRenderer(seg.toolCall.name)
         if (!render) return null
         return (
diff --git a/frontend/src/components/chat/ConfirmCard.tsx b/frontend/src/components/chat/ConfirmCard.tsx
new file mode 100644
index 0000000..1a48b7d
--- /dev/null
+++ b/frontend/src/components/chat/ConfirmCard.tsx
@@ -0,0 +1,76 @@
+import { createContext, useContext } from "react"
+import { Check, X } from "lucide-react"
+import { Button } from "@/components/ui/button"
+import { bareToolName } from "@/hooks/useToolRenderer"
+import { useI18n, type Lang } from "@/lib/i18n"
+import type { Confirmation } from "./types"
+
+/** Answers a confirmation; only the customer's live chat provides it, so mirrors show no buttons. */
+export const ConfirmContext = createContext<((c: Confirmation, approved: boolean, label: string) => void) | null>(
+  null
+)
+
+// ponytail: the card's strings live here, not in i18n.tsx, until the copy settles
+const COPY: Record<Lang, Record<string, string>> = {
+  es: {
+    open_claim: "¿Abrimos el reclamo?",
+    open_claim_body: "Reclamo por {n} cargo(s) que no reconoces.",
+    human_agent_hand_off: "¿Te paso con una persona?",
+    human_agent_hand_off_body: "Una persona de LATAM Bank sigue esta conversación.",
+    yes: "Sí",
+    no: "No",
+    typed: "Respondiste por escrito",
+  },
+  pt: {
+    open_claim: "Abrimos a reclamação?",
+    open_claim_body: "Reclamação de {n} cobrança(s) que você não reconhece.",
+    human_agent_hand_off: "Quer falar com uma pessoa?",
+    human_agent_hand_off_body: "Uma pessoa do LATAM Bank continua esta conversa.",
+    yes: "Sim",
+    no: "Não",
+    typed: "Você respondeu por escrito",
+  },
+  en: {
+    open_claim: "Open the claim?",
+    open_claim_body: "A claim for {n} charge(s) you don't recognise.",
+    human_agent_hand_off: "Talk to a person?",
+    human_agent_hand_off_body: "A LATAM Bank person takes over this chat.",
+    yes: "Yes",
+    no: "No",
+    typed: "You answered in writing",
+  },
+}
+
+/** The Yes/No card for a claim or hand-off the agent paused (agent tools/confirmation_hook.py). */
+export function ConfirmCard({ confirm }: { confirm: Confirmation }) {
+  const { lang } = useI18n()
+  const answer = useContext(ConfirmContext)
+  const copy = COPY[lang]
+  const tool = bareToolName(confirm.tool)
+  const ids = confirm.details.transaction_ids
+  const body = (copy[`${tool}_body`] ?? "").replace("{n}", String(Array.isArray(ids) ? ids.length : 1))
+
+  return (
+    <div role="group" aria-label={copy[tool] ?? tool} className="rounded-2xl border bg-card p-3 text-sm">
+      <p className="font-semibold">{copy[tool] ?? tool}</p>
+      {body && <p className="mt-0.5 text-muted-foreground">{body}</p>}
+      {confirm.answer ? (
+        <p className="mt-2 inline-flex items-center gap-1.5 text-muted-foreground">
+          {confirm.answer === "yes" ? <Check size={14} /> : confirm.answer === "no" ? <X size={14} /> : null}
+          {copy[confirm.answer]}
+        </p>
+      ) : (
+        answer && (
+          <div className="mt-3 flex gap-2">
+            <Button type="button" size="sm" onClick={() => answer(confirm, true, copy.yes)}>
+              {copy.yes}
+            </Button>
+            <Button type="button" size="sm" variant="outline" onClick={() => answer(confirm, false, copy.no)}>
+              {copy.no}
+            </Button>
+          </div>
+        )
+      )}
+    </div>
+  )
+}
diff --git a/frontend/src/components/chat/types.ts b/frontend/src/components/chat/types.ts
index 61e41fa..e6cd73b 100644
--- a/frontend/src/components/chat/types.ts
+++ b/frontend/src/components/chat/types.ts
@@ -12,9 +12,20 @@ export interface ToolCall {
   status: ToolCallStatus
 }
 
+/** A claim or hand-off the agent paused until the customer answers Yes or No. */
+export interface Confirmation {
+  id: string
+  tool: string
+  toolUseId: string
+  details: Record<string, unknown>
+  /** How it was answered: a button, or "typed" when the customer wrote instead. */
+  answer?: "yes" | "no" | "typed"
+}
+
 export type MessageSegment =
   | { type: "text"; content: string }
   | { type: "tool"; toolCall: ToolCall }
+  | { type: "confirm"; confirm: Confirmation }
 
 export interface Message {
   role: MessageRole
diff --git a/frontend/src/lib/agentcore-client/client.ts b/frontend/src/lib/agentcore-client/client.ts
index 50d245a..7d1c14a 100644
--- a/frontend/src/lib/agentcore-client/client.ts
+++ b/frontend/src/lib/agentcore-client/client.ts
@@ -22,7 +22,9 @@ export class AgentCoreClient {
     query: string,
     sessionId: string,
     accessToken: string,
-    onEvent: StreamCallback
+    onEvent: StreamCallback,
+    // Extra body fields, e.g. the customer's Yes/No: { confirmations: [{ interruptId, approved }] }
+    extra: Record<string, unknown> = {}
   ): Promise<void> {
     if (!accessToken) throw new Error("No valid access token found.")
     if (!this.runtimeArn) throw new Error("Agent Runtime ARN not configured.")
@@ -34,6 +36,7 @@ export class AgentCoreClient {
     const traceId = `1-${Math.floor(Date.now() / 1000).toString(16)}-${crypto.randomUUID()}`
 
     const body = {
+      ...extra,
       prompt: query,
       runtimeSessionId: sessionId,
     }
diff --git a/frontend/src/lib/agentcore-client/parsers/strands.ts b/frontend/src/lib/agentcore-client/parsers/strands.ts
index 0f1022c..b497363 100644
--- a/frontend/src/lib/agentcore-client/parsers/strands.ts
+++ b/frontend/src/lib/agentcore-client/parsers/strands.ts
@@ -19,6 +19,13 @@ export function createStrandsParser(): ChunkParser {
     try {
       const json = JSON.parse(data)
 
+      // A claim or hand-off waits for the customer's Yes/No
+      if (json.confirmation) {
+        const c = json.confirmation
+        callback({ type: "confirmation", id: c.id, tool: c.tool, toolUseId: c.toolUseId, details: c.details ?? {} })
+        return
+      }
+
       // Text streaming
       if (typeof json.data === "string") {
         callback({ type: "text", content: json.data })
diff --git a/frontend/src/lib/agentcore-client/types.ts b/frontend/src/lib/agentcore-client/types.ts
index 62acdac..eddb8c3 100644
--- a/frontend/src/lib/agentcore-client/types.ts
+++ b/frontend/src/lib/agentcore-client/types.ts
@@ -16,6 +16,8 @@ export type StreamEvent =
   | { type: "message"; role: string; content: unknown[] }
   | { type: "result"; stopReason: string }
   | { type: "lifecycle"; event: string }
+  // A claim or hand-off paused for the customer's Yes/No (agent tools/confirmation_hook.py)
+  | { type: "confirmation"; id: string; tool: string; toolUseId: string; details: Record<string, unknown> }
 
 /** Callback invoked with each stream event */
 export type StreamCallback = (event: StreamEvent) => void
diff --git a/frontend/src/test/confirm-card.test.tsx b/frontend/src/test/confirm-card.test.tsx
new file mode 100644
index 0000000..63ab7fa
--- /dev/null
+++ b/frontend/src/test/confirm-card.test.tsx
@@ -0,0 +1,36 @@
+import { describe, it, expect, vi } from "vitest"
+import { fireEvent, render, screen } from "@testing-library/react"
+import { ConfirmCard, ConfirmContext } from "@/components/chat/ConfirmCard"
+import type { Confirmation } from "@/components/chat/types"
+
+const CLAIM: Confirmation = {
+  id: "int-1",
+  tool: "gateway_open-claim-target___open_claim",
+  toolUseId: "tooluse_2",
+  details: { transaction_ids: ["TRX-1", "TRX-2"], claim_type: "fraud" },
+}
+
+describe("ConfirmCard", () => {
+  it("asks about the claim and sends the customer's answer", () => {
+    const answer = vi.fn()
+    render(
+      <ConfirmContext.Provider value={answer}>
+        <ConfirmCard confirm={CLAIM} />
+      </ConfirmContext.Provider>
+    )
+
+    expect(screen.getByText("¿Abrimos el reclamo?")).toBeInTheDocument()
+    expect(screen.getByText("Reclamo por 2 cargo(s) que no reconoces.")).toBeInTheDocument()
+    fireEvent.click(screen.getByRole("button", { name: "No" }))
+
+    expect(answer).toHaveBeenCalledWith(CLAIM, false, "No")
+  })
+
+  it("shows no buttons once answered, or where no chat can answer it", () => {
+    render(<ConfirmCard confirm={{ ...CLAIM, answer: "yes" }} />)
+    render(<ConfirmCard confirm={{ ...CLAIM, id: "int-2" }} />)
+
+    expect(screen.queryByRole("button")).toBeNull()
+    expect(screen.getByText("Sí")).toBeInTheDocument()
+  })
+})
diff --git a/frontend/src/test/strands-parser.test.ts b/frontend/src/test/strands-parser.test.ts
index 01e78e5..c24bf56 100644
--- a/frontend/src/test/strands-parser.test.ts
+++ b/frontend/src/test/strands-parser.test.ts
@@ -31,3 +31,11 @@ describe("strands parser: tool calls", () => {
     ])
   })
 })
+
+describe("strands parser: confirmations", () => {
+  it("passes on a claim or hand-off paused for the customer's Yes/No", () => {
+    const confirmation = { id: "int-1", tool: "open_claim", toolUseId: "tooluse_2", details: { transaction_ids: ["TRX-1"] } }
+
+    expect(parseAll([`data: ${JSON.stringify({ confirmation })}`])).toEqual([{ type: "confirmation", ...confirmation }])
+  })
+})
```
