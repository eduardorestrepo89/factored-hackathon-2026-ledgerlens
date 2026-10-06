# Human hand-off: SNS-free Lambda and the hand-off frontend: Design

**Date:** 2026-10-03
**Status:** Draft, awaiting the user's review.
**Parent design:** [LEDGERLENS_PRODUCT_DESIGN.md](../../LEDGERLENS_PRODUCT_DESIGN.md), §7.9
**Replaces:** the SNS part of [2026-10-03-write-tools-design.md](2026-10-03-write-tools-design.md) §5 (`human_agent_hand_off`).
**Visual reference:** Superdesign project "LedgerLens · Human hand-off" ([canvas](https://superdesign.dev/teams/d7127829-7b70-42db-821b-1e00f8cad320/projects/7b3e9514-e39a-4418-ae55-7dea1f0803d0)) and [`.superdesign/design-system.md`](../../../.superdesign/design-system.md).
**Prototype it grew from:** the "LedgerLens Handoff Lab" scratch artifact (three lenses; only the hand-off and the desk carry over).

---

## 1. Goal

Make the hand-off to a human the moment judges remember: the agent calls `human_agent_hand_off`, says goodbye, and the app visibly passes the conversation to a person who already has the whole case.

1. **Lambda cleanup.** `human_agent_hand_off` stops publishing to SNS. It validates the input, derives an id from the content and returns the full validated hand-off to the agent. No database write, no AWS call.
2. **Live wiring.** The agent can call the tool: Gateway target, Cedar statements, and a v2 system prompt with the hand-off rules and the goodbye.
3. **Hand-off frontend.** The React app detects the completed tool result, waits for the goodbye to finish streaming, and animates into a split screen: the customer's chat in a phone frame on the left, a human agent desk ("Laura") on the right. The presenter types as Laura; the customer sees it live.

### Success criteria
- Saying *"quiero hablar con una persona"* in the deployed app produces beats 1 → 2 → 3 of §6 with no manual step but Laura's first message.
- No SNS topic, subscription, `sns:Publish` grant or `HANDOFF_TOPIC_ARN` remains in code or CDK output.
- A failed hand-off (`{"error": …}`) never switches the UI.
- `pytest tests/unit -q`, `ruff format --check`, `ruff check`, the CDK tests, `npm run lint` and `npm test` in `frontend/` are clean.

### Decisions made with the user
| Topic | Decision |
|---|---|
| Database | **No write.** The frontend gets everything from the stream. |
| Human side | **Split screen** in one browser: phone left, desk right, presenter types as the agent. No backend. |
| Scope | **Hand-off + desk only.** No action timeline, no decision trace, no router-model picker. |
| Choreography | **Baton pass** (§6): ticket in chat → split with the ticket morphing into the case card → "connecting" → "Laura se unió". |
| Visuals | The three Superdesign beats (§6), approved. |

### Out of scope
- Real contact-center delivery or multi-browser sync (a later queue replaces nothing here; it would be a new adapter).
- Gateway targets, Cedar statements and prompt rules for `block_credit_card` and `open_claim`.
- An action timeline built from earlier tool calls, the decision trace, scripted scenarios.
- Dark mode switching (tokens stay defined; the app stays light).

---

## 2. Lambda: `gateway/tools/human_agent_hand_off/`

### 2.1 What goes
| Path | Why |
|---|---|
| `application/ports/` (`hand_off_publisher.py`, `errors.py`) | No publisher. |
| `infrastructure/` (`publishers/sns_publisher.py`) | No SNS. |
| `delivery/settings.py` | No configuration left. |
| `delivery/dependencies/` | Nothing to build: the use case has no dependencies. |
| `HandOffUnavailableError` in `domain/errors.py` | Its only causes (bad config, publish failure) are gone. |

### 2.2 What stays and changes
- **Entities.** `HandOff(customer_id, priority, reason, summary, related_ids)` unchanged. `HandOffResult` becomes `HandOffResult(hand_off_id, hand_off: HandOff)`.
- **Use case.** `HandOffUseCase()` takes no arguments. Validation (`_clean_*`) is unchanged. Then:
  ```
  hand_off_id = "HO-" + base32(sha256("|".join([customer_id, priority, reason, summary, ",".join(sorted(related_ids))])))[:8]
  ```
  Same content → same id, so a retried or repeated call never makes a second case; a test pins the format `^HO-[A-Z2-7]{8}$`.
- **Presenter.** Returns
  ```json
  {"hand_off_id": "HO-7Q3KX2MA", "status": "queued", "priority": "high", "reason": "FRAUD_CONFIRMED",
   "customer_id": "CLI-…", "summary": "…", "related_ids": ["TX-88", "TX-89", "C-20931"]}
  ```
- **Handler.** `USE_CASE = HandOffUseCase()` at module load. Keeps the `<target>___` tool-name guard, `DomainError → {"error": message}`, any other exception → `UNEXPECTED_ERROR_MESSAGE`, success → `{"content": [{"type": "text", "text": <JSON>}]}`. The summary is still never logged. Drop the R1 TODO (§3 wires the target) and the R5 TODO (§3 adds the Cedar statements).
- **`tool_spec.json`.** Input schema unchanged. Description becomes:
  > Sends the conversation to a human agent, who continues in this same chat. Use when the customer asks for a person, after a confirmed fraud case, for anything out of scope, or when you can't resolve the request. The summary must let the agent continue without asking the customer anything again: the card's last 4 digits, the transactions, what was blocked or opened (with ids) and what the customer said. Returns JSON with 'hand_off_id', 'status', 'priority', 'reason', 'customer_id', 'summary' and 'related_ids'. After it succeeds, say goodbye in one or two sentences: a person will continue in this same chat and the customer won't need to repeat anything. Don't promise a time.

---

## 3. Wiring

| File | Change |
|---|---|
| `infra-cdk/lib/data-construct.ts` | Remove `HumanHandOffTopic`, the email subscription, the `sns`, `subscriptions` and `kms` imports (`kms` is used only by the topic), `HANDOFF_TOPIC_ARN` and `grantPublish`. The function keeps its name, stays outside the VPC, gets no environment variables and no extra policy. Update the comment above it. |
| `infra-cdk/lib/backend-construct.ts` | Add `{ tool: "human_agent_hand_off", id: "HumanAgentHandOff" }` to `toolTargets`. The imported name `ledgerlens-human-agent-hand-off` already matches `ledgerlens-${slug}`. |
| `gateway/policies/policy.cedar` | Add `AgentCore::Action::"human-agent-hand-off-target___human_agent_hand_off"` to statement 1 (permit) and statement 2 (forbid on a different `customer_id`; the tool requires `customer_id`, so no `has` guard). Update the header's RULES text. |
| `patterns/strands-single-agent/tools/system_prompt.py` | `PROMPT_VERSION = "v2"`. In FRAUD AND ACTIONS, keep "you can't block cards or open claims" but replace the "never say you transferred them" rule with a HAND OFF block: call `human_agent_hand_off` when the customer asks for a person, the request is out of scope, you can't resolve it within 3 tool calls, or the customer reports unrecognised charges above USD 500 (priority high for fraud, else normal); after it succeeds, say goodbye in one or two sentences, in the customer's language, saying a person continues in this chat and they won't repeat anything; promise no time. BOUNDARIES' "a human agent can help" becomes "offer a hand-off". The unlinked block is unchanged (no customer_id, so no tool). |

Docs: §7.9 of the product design and the hand-off rows of §5/§12 of the write-tools spec point here.

---

## 4. Frontend: detection and state

### 4.1 Detection: `frontend/src/lib/handoff.ts`
```ts
export interface HandOff { hand_off_id: string; status: string; priority: "high" | "normal";
  reason: "FRAUD_CONFIRMED" | "CUSTOMER_REQUEST" | "UNRESOLVED" | "OUT_OF_SCOPE";
  customer_id: string; summary: string; related_ids: string[]; goodbye: string; at: string }

export function findHandOff(messages: Message[]): HandOff | null
```
- Looks only at the **last assistant message**.
- Finds a tool segment whose `name` ends with `human_agent_hand_off` (the stream name is `human-agent-hand-off-target___human_agent_hand_off`), with `status === "complete"` and a `result` that `JSON.parse`s to an object with a string `hand_off_id`.
- `goodbye` = the text segments after that tool segment, joined. `at` = the message timestamp.
- Anything else (`{"error": …}`, invalid JSON, no id, still running) → `null`.

### 4.2 Trigger and state: `ChatInterface.tsx`
- New state: `handOff: HandOff | null`. New `MessageRole`: `"human"` (the human agent).
- In `sendMessage`'s `finally` (the turn finished streaming, so the goodbye is on screen): if `!handOff` and `findHandOff(latest messages)` returns a value, wait 600 ms, then `document.startViewTransition?.(() => flushSync(() => setHandOff(h)))`, or `setHandOff(h)` when the API is missing.
- **Phase** is derived, never stored: `ai` (no hand-off) → `connecting` (hand-off, no `human` message) → `joined`.
- After the hand-off, `sendMessage` appends the customer's text and **does not call AgentCore**: the bot is muted while a person owns the chat.
- The desk composer appends `{ role: "human", content, timestamp }`.
- "Nueva conversación" resets `handOff` with the rest.

### 4.3 Renderer lookup: `frontend/src/hooks/useToolRenderer.ts`
`getToolRenderer(name)` looks up `name.split("___").pop()` before `"*"`, so `useToolRenderer("human_agent_hand_off", …)` matches the prefixed stream name.

---

## 5. Frontend: components

| File | New/changed | Content |
|---|---|---|
| `components/chat/HandOffTicket.tsx` | New | Renderer for `human_agent_hand_off`. Running → "Enviando a una persona…" with a spinner. Complete with a valid result → orange ticket: ticket icon, `HO-…`, ALTA (danger outline) or Normal pill, reason label, mono id chips, "Enviado a una persona". `view-transition-name: handoff-ticket` only while phase is `ai`. Error or bad result → `ToolCallDisplay`. |
| `components/chat/AgentDesk.tsx` | New | Right pane. **Header:** "Laura Restrepo · Fraudes y servicio" + pill *Conectando…* / *En conversación*. **Case card** (`view-transition-name: handoff-ticket` after the split): id, *Nuevo* badge until `joined`, priority pill, queue (`FRAUD_CONFIRMED` → Fraudes, else Servicio general), customer name from `auth.user.profile` (`name` → `given_name` → `customer_id`), reason label, summary, related-id chips, "En cola desde hh:mm" (`at`), **"Lo que ya se le dijo"** = `goodbye`. **Mirrored thread:** the same `messages`, without feedback buttons. **Suggested replies:** two per reason from a static Spanish map filled with name and id; "Usar" puts the text in the composer. **Composer:** "Escribe como Laura…", hint "Tu primer mensaje le avisa al cliente que te uniste." |
| `components/chat/ChatInterface.tsx` | Changed | No hand-off → today's centered layout. Hand-off → grid `400px | 1fr`: phone frame (28 px radius, the same `ChatMessages` + `ChatInput`) and `AgentDesk`. Below 1100 px the desk stacks under the phone. Registers the `HandOffTicket` renderer. |
| `components/chat/ChatHeader.tsx` | Changed | LedgerLens brand; status track *Asistente IA → Persona · Laura* (teal check / orange dot, pulsing while `connecting`) driven by `phase`. |
| `components/chat/ChatMessage.tsx`, `ChatMessages.tsx` | Changed | Tier bubbles: customer brand-dark, assistant `ai-bg` with an "Asistente IA" tag, human `human-bg` with a "Laura · Persona" tag. "Laura se unió a la conversación · hh:mm" divider before the first `human` message. A `hideFeedback` prop for the desk copy. |
| `styles/globals.css` | Changed | Tokens `--color-ai`, `--color-ai-bg`, `--color-human`, `--color-human-bg`, page background (values in `design-system.md`). `::view-transition-*` at 320 ms ease-out; cross-fade only under `prefers-reduced-motion`. |
| `index.html` | Changed | Google Fonts family `Geist` (the request for `Geist+Sans` fails today), title "LedgerLens". |
| Welcome copy | Changed | "Welcome to FAST Chat" → Spanish LedgerLens welcome. |

No new dependencies. Icons from `lucide-react` (Ticket, ShieldCheck, User, Sparkles, Send, Check, Loader2).

---

## 6. Choreography (the approved storyboard)

| Beat | Superdesign draft | What the viewer sees |
|---|---|---|
| 1 · Before the split | [Beat 1](https://p.superdesign.dev/draft/baa69b92-1a61-4157-91ff-b51321bb73f6) | Full-width chat. The hand-off ticket rises in (220 ms), the goodbye streams under it, the composer shows "Conectando con una persona…". Status track: *Asistente IA* active, *Persona* grey. |
| 2 · Connecting | [Beat 2](https://p.superdesign.dev/draft/1a136718-0306-4dd9-ab11-6a9aa3dea16f) | 600 ms after the goodbye ends, a view transition: the chat shrinks into the phone, the desk slides in, the ticket morphs into the case card (*Nuevo*). *Persona · Laura* pulses "conectando"; Laura's composer has focus. |
| 3 · Laura joined | [Beat 3](https://p.superdesign.dev/draft/33d6a32d-d553-4fd0-9f49-aac432227a9b) | Laura sends a message (typed or "Usar"): the phone shows "Laura se unió · hh:mm" and an orange bubble; the desk pill reads *En conversación*. |

The mockups' sample text is placeholder; in the app every value comes from the stream and the auth profile. The mockups' "Verificado por OTP" line is dropped: no tool returns it.

---

## 7. Error handling

| Case | Behavior |
|---|---|
| Invalid tool input | Existing `InvalidInputError` message to the agent; no switch. |
| Unexpected Lambda error | Existing fixed `UNEXPECTED_ERROR_MESSAGE`; no switch. |
| Result not JSON or without `hand_off_id` | `findHandOff` → `null`; the generic tool row shows. |
| Stream fails after the tool completed | The split still happens (detection runs in `finally`); the case is queued. |
| Tool called twice | `handOff` is set once; same content gives the same id anyway. |
| No View Transitions API | Instant switch. |
| Customer types while connecting | The text joins the thread and the desk; AgentCore is not called. |

---

## 8. Testing

- **Lambda** (`tests/unit/human_agent_hand_off/`): delete `test_sns_publisher.py`, `test_settings.py` and the publisher fakes; rewrite `test_delivery_wiring.py` for the dependency-free handler. Use case: same content → same id, any field change → different id, id matches `^HO-[A-Z2-7]{8}$`, validation cases unchanged. Presenter: every field present. Handler: success shape, invalid input, wrong tool name, no environment variable needed. `test_tool_spec.py`: the new description mentions the goodbye.
- **CDK:** `data-construct.test.ts`: no `AWS::SNS::Topic` or `AWS::SNS::Subscription`; the hand-off function has no `Environment`, no VPC config and no `sns:Publish`. `backend-gateway.test.ts`: a `human-agent-hand-off-target` exists. `policy-cedar.test.ts`: the action is in both statements.
- **Prompt:** `tests/unit/test_system_prompt.py` pins the v2 hash.
- **Frontend (vitest):** `findHandOff`: prefixed name, error result, invalid JSON, still running, hand-off in an older message only. `getToolRenderer`: prefixed name resolves to the named renderer.
- **Demo check after deploy:** *"quiero hablar con una persona"* runs beats 1 → 3; record a GIF for the deck. Deploy only after the branch's code review finishes.

---

## 9. Risks

| # | Risk | Mitigation |
|---|---|---|
| H1 | The model says goodbye but skips the tool, or calls it without saying goodbye. | Rules in both the tool description and the v2 prompt; the UI keys off the tool result, never the words. |
| H2 | View transitions with a shared name break if both elements exist in one snapshot. | The ticket drops its `view-transition-name` once phase leaves `ai`. |
| H3 | Mock data in the mockups (names, tool names) leaks into code. | §6 note; all values come from the stream. |
| H4 | The v2 prompt conflicts with a parallel v2 prompt effort (product design PART 3). | This change adds only the hand-off block; a later full v2 bumps to v3. |
