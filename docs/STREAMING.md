# Streaming

The agent streams its reply to the browser as Server-Sent Events (SSE). This page is the reference for that stream: the request body, the events on the wire, how the frontend parses them, and the Yes/No confirmation round trip.

## Path of a reply

1. `ChatInterface.tsx` calls `AgentCoreClient.invoke()` (`frontend/src/lib/agentcore-client/client.ts`). That sends `POST https://bedrock-agentcore.<region>.amazonaws.com/runtimes/<url-encoded runtime ARN>/invocations?qualifier=DEFAULT` with the user's Cognito access token.
2. AgentCore Runtime runs `invocations()` in `agent/ledgerlens/ledgerlens_agent.py`. `BedrockAgentCoreApp` (bedrock-agentcore 1.4.7) writes each dict the generator yields as one `data: <json>\n\n` line, with media type `text/event-stream`.
3. `readSSEStream()` (`utils/sse.ts`) splits the response into lines and hands each line to the parser.
4. The parser comes from `createStrandsParser()` (`parsers/strands.ts`). `client.ts` creates a new one for each stream, because the parser remembers which tool calls it has already announced. It turns lines into typed `StreamEvent`s (`types.ts`).
5. `ChatInterface.tsx` builds message segments (text, tool calls, Yes/No cards) from those events, and `ChatMessage.tsx` renders them.

## Request

Headers:

| Header | Value |
|--------|-------|
| `Authorization` | `Bearer <Cognito access token>` |
| `Content-Type` | `application/json` |
| `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` | The conversation's session id (`crypto.randomUUID()`) |
| `X-Amzn-Trace-Id` | `1-<hex epoch seconds>-<uuid>` |

Body:

```json
{
  "prompt": "I don't recognise a charge",
  "runtimeSessionId": "5f0c…",
  "confirmations": [{ "interruptId": "…", "approved": true }]
}
```

- `prompt` and `runtimeSessionId` are required. Without either, the agent sends an error event and stops.
- `confirmations` is optional. The frontend adds it when the customer taps Yes or No on a confirmation card. See [Confirmation round trip](#confirmation-round-trip).
- `eval` is optional and only for evaluation logins. See the [agent README](../agent/ledgerlens/README.md#evaluation-override).

The body never carries the user's identity. The agent reads it from the validated JWT.

## Backend loop

The streaming part of `invocations()`:

```python
prompt = user_query
if agent._interrupt_state.activated:
    prompt = resume_prompt(list(agent._interrupt_state.interrupts), payload)

markup = LeakedMarkupFilter()
async for event in agent.stream_async(prompt):
    for confirmation in confirmation_events(event):
        yield confirmation
    for clean in markup.clean(json.loads(json.dumps(dict(event), default=str))):
        yield clean
```

- **The prompt isn't always the user's text.** When the agent is waiting on a Yes/No answer, `prompt` becomes the list of interrupt responses from `resume_prompt()`.
- **Confirmations go first.** `confirmation_events()` looks at the raw event before serialization. When the agent stopped on a confirmation, the `{"confirmation": ...}` events go out before the `result` event that carries them.
- **Non-JSON values become strings.** Strands merges its invocation state into text and tool-use events: `agent`, `event_loop_cycle_id`, `request_state`, `event_loop_cycle_trace` and `event_loop_cycle_span`. `json.dumps(default=str)` turns each of these into a string, as it does for the `AgentResult` in the final event. Treat those keys as noise.
- **The markup filter can change events.** Every event passes through `LeakedMarkupFilter.clean()`, which can drop an event, hold back part of its text, or split it in two. See [Leaked markup filter](#leaked-markup-filter).

## Events on the wire

Each line is `data: ` followed by one JSON object. The parser checks the keys in the order of this table and acts on the first match:

| Wire shape | When | Parser output |
|------------|------|---------------|
| `{"confirmation": {"id", "tool", "toolUseId", "details"}}` | The agent paused a tool for the customer's Yes/No | `confirmation` |
| `{"data": "<text>", "delta": {...}, ...}` | A chunk of reply text | `text` |
| `{"current_tool_use": {"toolUseId", "name", "input"}, "delta": {"toolUse": {"input": "<chunk>"}}, ...}` | The model is writing a tool call. `current_tool_use.input` holds the input so far. | `tool_use_start` the first time a `toolUseId` appears, then `tool_use_delta` for every event whose `delta.toolUse.input` is non-empty |
| `{"message": {"role": "assistant" or "user", "content": [...]}}` | A complete message: the assistant's text and `toolUse` blocks, or the user message with `toolResult` blocks | `message` for every role, plus one `tool_result` per `toolResult` block in a user message |
| `{"result": "<final text>"}` | The turn ended | `result` |
| `{"init_event_loop": true, ...}`, `{"start": true}`, `{"start_event_loop": true}` | Strands lifecycle | `lifecycle` with `init`, `start` or `start_loop` |
| `{"status": "error", "error": "<message>"}` | The agent failed (see [Errors](#errors)) | Nothing |
| Anything else: `event` (raw Bedrock stream chunks), `reasoningText`, `tool_interrupt_event`, `tool_cancel_event`, `tool_stream_event` | Other Strands events | Nothing |

Details the parser handles:

- **Tool start.** The parser starts a tool the first time it sees its `toolUseId`, whatever that delta holds. Claude on Bedrock sends an empty first delta. DeepSeek on Bedrock sends the whole input in one delta, so the parser can emit `tool_use_start` and `tool_use_delta` from the same line.
- **Tool result text.** `tool_result` joins the `text` items of the `toolResult` content. If there are none, it sends the content as JSON.
- **The `result` value is a string.** `AgentResult.__str__` returns the final message's text blocks, each followed by a newline. For an interrupted turn, it returns the Python repr of the interrupt list instead. A string `result` gives `stopReason: "end_turn"`, and an object `result` gives `result.stop_reason`, so an interrupted turn also reports `end_turn`. An empty final text (`{"result": ""}`) is falsy, and the parser emits nothing for it.
- **Tool names.** The model sees Gateway tools as `gateway_<target>___<tool>`, so `name` in `current_tool_use` looks like `gateway_list-credit-cards-target___list_credit_cards`.
- **Parse errors.** A line that isn't valid JSON is logged with `console.debug("Failed to parse strands event:", data)`.

`ChatInterface.tsx` acts on `confirmation`, `text`, `tool_use_start`, `tool_use_delta`, `tool_result` and `message` (assistant only). It ignores `result` and `lifecycle`.

### Example

A turn with one tool call. The raw `event` lines are left out, and each line is trimmed to the keys the parser reads:

```text
data: {"init_event_loop": true}
data: {"start": true}
data: {"start_event_loop": true}
data: {"current_tool_use": {"toolUseId": "tooluse_1", "name": "gateway_list-credit-cards-target___list_credit_cards", "input": ""}, "delta": {"toolUse": {"input": ""}}}
data: {"current_tool_use": {"toolUseId": "tooluse_1", "name": "gateway_list-credit-cards-target___list_credit_cards", "input": "{\"customer_id\": \"CLI-1\"}"}, "delta": {"toolUse": {"input": "{\"customer_id\": \"CLI-1\"}"}}}
data: {"message": {"role": "assistant", "content": [{"toolUse": {"toolUseId": "tooluse_1", "name": "gateway_list-credit-cards-target___list_credit_cards", "input": {"customer_id": "CLI-1"}}}]}}
data: {"message": {"role": "user", "content": [{"toolResult": {"toolUseId": "tooluse_1", "status": "success", "content": [{"text": "{\"cards\": [...]}"}]}}]}}
data: {"start": true}
data: {"start": true}
data: {"start_event_loop": true}
data: {"data": "You have two cards: "}
data: {"data": "…1234 and …5678."}
data: {"message": {"role": "assistant", "content": [{"text": "You have two cards: …1234 and …5678."}]}}
data: {"result": "You have two cards: …1234 and …5678.\n"}
```

## Confirmation round trip

`block_credit_card`, `open_claim` and `human_agent_hand_off` run only after the customer taps Yes (`agent/ledgerlens/tools/confirmation_hook.py`).

1. The model calls one of these tools. The stream shows the tool call and the assistant `message` as usual.
2. Before the tool runs, `ConfirmationHook` raises a Strands interrupt named `confirm_<tool>`. The agent stops with stop reason `interrupt`. The session manager saves the interrupt and the waiting tool call with the session.
3. The runtime sends one event per pending confirmation, then the result:

   ```text
   data: {"confirmation": {"id": "<interrupt id>", "tool": "block_credit_card", "toolUseId": "tooluse_2", "details": {"card_last4": "1234", "reason": "suspected_fraud"}}}
   data: {"result": "[{'id': '<interrupt id>', 'name': 'confirm_block_credit_card', 'reason': {...}, 'response': None}]"}
   ```

   `details` is the tool input without `customer_id` and `customer_confirmed`.
4. The frontend replaces that tool's segment with a Yes/No card.
5. A tap sends a new request. Its `prompt` is the button label, and it carries `"confirmations": [{"interruptId": "<id>", "approved": true}]` (`ChatInterface.tsx`).
6. The agent sees that it is waiting (`agent._interrupt_state.activated`) and builds the responses with `resume_prompt()`:
   - With `confirmations`, an interrupt is approved only if the click for its id says `approved: true`. A pending interrupt with no matching click counts as No.
   - Without `confirmations` (the customer typed instead of tapping), every pending interrupt is a No that carries the typed text.
7. Strands resumes the saved tool call without calling the model first:
   - **Yes:** the tool runs. On `block_credit_card` and `open_claim`, `customer_confirmed` is set to `true` first.
   - **No:** the call is cancelled with "Not done: the customer chose No. Don't call this tool again unless they ask for it."
   - **Typed reply:** the call is cancelled with a message that quotes the text (up to 300 characters, with `"` replaced by `'`) and tells the model to answer it.

The resumed call is not announced again, so the stream has no `current_tool_use` events for it. The first event about it is the user `message` with its `toolResult`. That is why `ChatInterface.tsx` creates the tool segment itself when the customer taps Yes: the result needs a segment to land in.

## Errors

`invocations()` yields `{"status": "error", "error": "<message>"}` in three cases:

- `prompt` or `runtimeSessionId` is missing.
- An evaluator's override is invalid: `"eval override rejected: ..."`.
- Any exception while the agent is built or run: `str(e)`. This includes a failed Cognito token call, a missing environment variable, a registry MCP server that can't be reached, and a failed summary on context overflow.

The frontend parser has no branch for these events (`parsers/strands.ts`), so nothing in the chat reacts to them. A non-2xx HTTP response is different: `client.ts` throws on it, and `ChatInterface.tsx` shows the error.

## Guardrail and streaming

The model runs with `guardrail_stream_processing_mode: "sync"` (`agent/ledgerlens/tools/guardrail.py`). Bedrock holds each reply chunk until the guardrail has checked it, so a blocked reply never shows halfway. When the guardrail blocks the customer's message, Bedrock replies with the guardrail's blocked message, and it streams as ordinary `data` events.

## Leaked markup filter

On Bedrock, DeepSeek V3.2 sometimes starts its text after a tool call with its raw tool-call marker, `<｜DSML｜function_calls`. The bars are the full-width `｜` (U+FF5C). `LeakedMarkupFilter` (`agent/ledgerlens/tools/leaked_markup.py`) keeps the marker out of the chat:

- In a `data` event, it removes the marker (and a space right after it) from the text. If the text then ends with the start of the marker, that tail is held back, because the rest of the marker may come in the next chunk.
- A `data` event left with no text is dropped.
- On a `message` or `result` event, any held text is sent first as a bare `{"data": "<held text>"}` event. Then the event itself goes out, with the marker removed from the text blocks of `message` events.
- All other events pass through unchanged.

So one Strands event can become zero, one or two events on the wire.

## Debugging

- To see every raw event, add `console.log("[Streaming Event]", data)` at the top of the parser in `parsers/strands.ts`, after `data` is read. Then open the browser console.
- The evaluation harness in `evals/` grades sessions from this same stream ([evals/README.md](../evals/README.md)).
- Strands streaming reference: [strandsagents.com, streaming overview](https://strandsagents.com/latest/documentation/docs/user-guide/concepts/streaming/overview/).
