# Context management

LedgerLens keeps the model's input small with a Strands conversation manager. `create_conversation_manager()` in `agent/ledgerlens/tools/conversation_memory.py` builds it from the `STM_*` environment variables, and the agent passes it as `conversation_manager=` (`ledgerlens_agent.py`). By default it is a sliding window of 30 messages. Summarization of older messages is optional.

This page describes that setup as built on strands-agents 1.32.0.

## What the model sees each turn

- **The system prompt.** This is `BASE_SYSTEM_PROMPT`, the customer block and the `<session_context>` block. It is rebuilt on every request (`build_system_prompt`) and is never part of `agent.messages`, so the conversation manager never trims it or summarizes it. The session context itself is kept in `agent.state["session_context"]`, which is saved with the session (`tools/session_context.py`).
- **The history.** `agent.messages` as the memory session manager restores it. It starts at the conversation manager's saved offset, with the saved summary in front when there is one.
- **The new turn.** The customer's message, or the answer to a pending confirmation, and the tool calls and results of this turn.
- **Long-term facts** (only when `use_long_term_memory` is on). bedrock-agentcore inserts the retrieved facts as a `<user_context>…</user_context>` text block at the start of the newest user message. See [MEMORY_INTEGRATION.md](MEMORY_INTEGRATION.md).

## Configuration

Set these in `infra-cdk/config.yaml` under `backend`. The CDK passes them to the runtime as environment variables (`infra-cdk/lib/backend-construct.ts`). `infra-cdk/lib/utils/config-manager.ts` validates them at synth time.

| `config.yaml` key | Env var | Default | Rule |
|-------------------|---------|---------|------|
| `stm_window_size` | `STM_WINDOW_SIZE` | `30` | Integer from 2 to 200 |
| `use_stm_summarization` | `USE_STM_SUMMARIZATION` | `false` | Only YAML `true` turns it on |
| `stm_summary_ratio` | `STM_SUMMARY_RATIO` | `0.3` | Number from 0.1 to 0.8 |
| `stm_preserve_recent_messages` | `STM_PRESERVE_RECENT_MESSAGES` | `10` | Integer, 0 or more. With summarization on, it must be less than `stm_window_size`, or every summary attempt would fail for lack of messages. `create_conversation_manager()` checks this again at runtime. |
| `stm_summarization_model_id` | `STM_SUMMARIZATION_MODEL_ID` | `""` | String. Empty means the agent's own model. |
| `stm_summarization_prompt` | `STM_SUMMARIZATION_PROMPT` | `""` | String. Empty means the built-in `STM_SUMMARY_PROMPT`. Use a YAML block (`|`) for several lines. |

The window counts messages, not turns. One question that uses a tool is about 4 to 6 messages (user, assistant `toolUse`, user `toolResult`, assistant reply, more for more tools). A change to any key needs a redeploy of the main stack (see [DEPLOYMENT.md](DEPLOYMENT.md#configuration)).

## Sliding window (default)

With `use_stm_summarization: false`, the manager is `StmSlidingWindowConversationManager(window_size=STM_WINDOW_SIZE)`. That is Strands' `SlidingWindowConversationManager` with its defaults (`should_truncate_results=True`, `per_turn=False`), plus the session restore described [below](#switching-between-the-two-managers).

How it behaves in strands-agents 1.32.0:

- **When it runs.** Strands calls `apply_management()` once, after the request has finished streaming. It doesn't run before each model call, because `per_turn` is off. Within a turn, the model sees the history as trimmed at the end of the previous turn, plus everything from the current turn.
- **What happens when the history is longer than the window.** `reduce_context()` first looks at the oldest message that has tool results. If any of its result texts is longer than 400 characters and not yet truncated, it cuts each such text down to its first and last 200 characters and stops there. Otherwise it drops the oldest messages down to the window size. The cut moves forward so that a `toolResult` never loses the `toolUse` before it.
- **On context overflow.** When Bedrock reports a context overflow, Strands calls `reduce_context()` and retries the model call.
- **Dropped messages aren't deleted.** They stay in AgentCore Memory. The manager's `removed_message_count` is saved with the session, so the next request restores only the messages after it.

## Summarization (optional)

With `use_stm_summarization: true`, the manager is `WindowedSummarizingConversationManager`, a subclass of Strands' `SummarizingConversationManager(summary_ratio, preserve_recent_messages, summarization_agent, summarization_system_prompt)`.

### When it summarizes

In strands-agents 1.32.0, `SummarizingConversationManager.apply_management()` does nothing. On its own, Strands summarizes only after a context overflow. LedgerLens overrides `apply_management()` to summarize as soon as the history passes `window_size`, at the end of a request, the same moment the sliding window would trim.

### What it summarizes

Each time it summarizes, `reduce_context()` (Strands' code):

1. Takes the oldest `max(1, int(len(messages) * summary_ratio))` messages, capped so that the newest `preserve_recent_messages` stay.
2. Moves the cut forward so it doesn't separate a `toolUse` from its `toolResult`.
3. Replaces those messages with one summary message (role `user`). The summary is kept in the manager's state and saved with the session.

The previous summary is always the oldest message, so it is folded into the next one.

Example with the defaults (window 30, ratio 0.3, keep 10): at 31 messages, the oldest 9 become one summary, and the history drops to 23 messages (more are summarized if the cut has to move past a tool pair).

### The summary prompt

`STM_SUMMARY_PROMPT` is written for banking. It keeps identifiers word for word, and it skips what the system prompt already has:

```text
Summarize the conversation as concise third-person bullets.
You MUST preserve verbatim: card last-4 digits, transaction IDs, amounts with currency,
dates, fraud classifications, claim and complaint IDs, and any action taken or promised
(card blocked, dispute opened, hand-off requested). Then list open questions.
The customer profile and session context are in the system prompt; do not repeat them.
```

`STM_SUMMARIZATION_PROMPT` replaces it.

### Which model writes the summary

- **`stm_summarization_model_id` empty.** Strands calls the agent's own model directly with `model.stream()`, using the summary prompt as the system prompt and no tools. It doesn't go through the agent loop. It is the same `BedrockModel`, so the guardrail settings apply to this call too.
- **`stm_summarization_model_id` set.** The summary comes from a separate agent, `stm_summarizer`: `BedrockModel(model_id, temperature=0)` with the summary prompt.
  - It has no tools. Strands registers a no-op tool for the call to meet its tool-spec requirement.
  - It has no session manager, so it can't write into the customer's session.
  - Its callback handler is `None`, because Strands' default handler prints the summary, customer data included, to the runtime logs.
  - It has no guardrail.

`conversation_memory.py` passes either `summarization_agent` or `summarization_system_prompt`, never both, because Strands rejects both together.

### When a summary fails

- **At the window limit.** `apply_management()` logs `[STM] Summarization failed; keeping the full history until next turn` and leaves the messages as they were. The request still succeeds. `reduce_context()` also puts back `removed_message_count`, which Strands raises before the summary call. Without that, the session would restore from the wrong offset.
- **On a context overflow.** The error propagates, and the request ends with an error event.

Each summary is one extra model call. A cheaper `stm_summarization_model_id` lowers that cost.

## Switching between the two managers

Strands refuses to restore a saved conversation-manager state whose class name doesn't match the current manager. Without a fix, flipping `use_stm_summarization` would break every session in flight. `_restorable()` relabels a state saved by any of these three classes as the current one:

- `SlidingWindowConversationManager` (Strands' default, used before the `STM_*` settings existed)
- `StmSlidingWindowConversationManager`
- `WindowedSummarizingConversationManager`

`StmSlidingWindowConversationManager.restore_from_session()` also returns the saved `summary_message`. That way, a session that was summarized earlier keeps its summary after summarization is turned off. The summary stands for the messages before the restore offset.

## What the window never touches

The system prompt and the session context. The prompt is rebuilt on every request and the context is restored from `agent.state`, both outside `agent.messages`. This is why `tools/session_context.py` keeps the context there instead of in the conversation, where the window would drop it and a summary would reword it.

## Custom context management

Strands also supports fully custom context handling, for example a `HookProvider` on `BeforeModelCallEvent` combined with a no-op conversation manager. LedgerLens doesn't use it.

## Further reading

- [Strands ConversationManager API](https://strandsagents.com/docs/api/python/strands.agent.conversation_manager.conversation_manager/)
- [Strands SlidingWindowConversationManager](https://strandsagents.com/docs/api/python/strands.agent.conversation_manager.sliding_window_conversation_manager/)
- [Strands SummarizingConversationManager](https://strandsagents.com/docs/api/python/strands.agent.conversation_manager.summarizing_conversation_manager/)
- [AgentCore Memory in LedgerLens](MEMORY_INTEGRATION.md)
