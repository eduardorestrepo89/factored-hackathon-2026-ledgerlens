# Streaming Guide for Agents

## Overview

Your agent sends streaming events in SSE format. This guide explains how to integrate streaming with frontend.

## Integration Steps

1. **Your agent sends streaming events** (SSE format)
2. **The `agentcore-client` library** reads the SSE stream and passes it to the Strands parser:
   - For **Strands agents**: `frontend/src/lib/agentcore-client/parsers/strands.ts` — parses Strands schema events
   - For **other agent frameworks**: Create a new parser and use it in `frontend/src/lib/agentcore-client/client.ts`
3. **Parsers emit typed `StreamEvent`s** (text, tool_use_start, tool_use_delta, tool_result, message, result, lifecycle)
4. **`ChatInterface.tsx`** handles events and builds message segments (interleaved text + tool calls)
5. **`ChatMessage.tsx`** renders segments inline with markdown formatting and tool call components

---

## Current Implementation

### Backend: Strands Agent

**File:** `agent/ledgerlens/ledgerlens_agent.py`

The backend yields all raw Strands streaming events, serialized to JSON-safe dicts:

```python
async for event in agent.stream_async(user_query):
    yield json.loads(json.dumps(dict(event), default=str))
```

**Note:** Strands events can contain non-JSON-serializable Python objects (agent instances, UUIDs, `ModelStopReason` tuples, etc.). The `json.dumps(default=str)` call converts these to strings, ensuring all events are safe to send over SSE.

### Frontend: Event Parser

**File:** `frontend/src/lib/agentcore-client/parsers/strands.ts`

The default parser for `ledgerlens` handles Strands schema events:

```typescript
export const parseStrandsChunk: ChunkParser = (line, callback) => {
  if (!line.startsWith("data: ")) return;
  const json = JSON.parse(line.substring(6).trim());

  // Text token: {"data": "Hello"}
  if (typeof json.data === "string") {
    callback({ type: "text", content: json.data });
  }

  // Tool use: {"current_tool_use": {...}, "delta": {"toolUse": {"input": "..."}}}
  if (json.current_tool_use) {
    // First delta (empty input) → tool_use_start
    // Subsequent deltas → tool_use_delta
  }

  // Tool result: {"message": {"role": "user", "content": [{"toolResult": {...}}]}}
  if (json.message?.role === "user") {
    // Extract toolResult blocks → callback({ type: "tool_result", ... })
  }

  // Completion: {"result": {"stop_reason": "end_turn"}}
  if (json.result) {
    callback({ type: "result", stopReason: "end_turn" });
  }

  // Lifecycle: {"init_event_loop": true}
  if (json.init_event_loop || json.start_event_loop) { ... }
};
```

See the full implementation in the source file for edge cases.

### Event Structure

Strands provides these event types:

- `data`: Text chunks (accumulate as they arrive)
- `current_tool_use`: Tool name, ID, and input parameters (with `delta` for streaming)
- `message`: Final structured message with full content (assistant with `toolUse`, user with `toolResult`)
- `result`: AgentResult with stop reason and metrics
- `init_event_loop`, `start_event_loop`, `complete`: Lifecycle markers
- `tool_stream_event`: Events streamed from tool execution
- `event`: Raw Bedrock Converse events

```javascript
// Text streaming
data: {"data": "Hello"}
data: {"data": " there"}

// Tool use start — first delta has empty input
data: {"current_tool_use": {"toolUseId": "tool_abc123", "name": "text_analysis"}, "delta": {"toolUse": {"input": ""}}}

// Tool input streaming
data: {"current_tool_use": {"toolUseId": "tool_abc123", "name": "text_analysis"}, "delta": {"toolUse": {"input": "{\"text\": \"hello\"}"}}}

// Complete assistant message
data: {"message": {"role": "assistant", "content": [{"toolUse": {"toolUseId": "tool_abc123", "name": "text_analysis", "input": {"text": "hello"}}}]}}

// Tool result (user message with toolResult blocks)
data: {"message": {"role": "user", "content": [{"toolResult": {"toolUseId": "tool_abc123", "content": [{"text": "Analysis complete: 1 word"}]}}]}}

// Final result
data: {"result": {"stop_reason": "end_turn"}}

// Lifecycle events
data: {"init_event_loop": true}
data: {"start_event_loop": true}
```

**Reference:** [Strands Streaming Documentation](https://strandsagents.com/latest/documentation/docs/user-guide/concepts/streaming/overview/)

---

## Adding a New Agent Pattern

1. Create `agent/my-pattern/` with your agent code
2. Create a parser: `frontend/src/lib/agentcore-client/parsers/my-pattern.ts`
   - Export a `ChunkParser` function that converts SSE lines into `StreamEvent`s via `callback()`
3. Use it in `frontend/src/lib/agentcore-client/client.ts` in place of `parseStrandsChunk`
4. Set `pattern: my-pattern` in `infra-cdk/config.yaml`

---

## Debugging

Enable console logging in the parser:

```javascript
console.log('[Streaming Event]', data);
```

Open browser console (F12) to see all events from your agent.
