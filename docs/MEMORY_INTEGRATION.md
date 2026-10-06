# AgentCore Memory

LedgerLens uses AgentCore Memory in two ways:

- **Short-term memory** stores each conversation, so a chat continues across requests. It is always on.
- **Long-term memory** extracts facts about a user across sessions. It is off by default.

The agent uses both through `AgentCoreMemorySessionManager` from `bedrock-agentcore==1.4.7`. That is the plain package; the `[strands-agents]` extra isn't needed because `strands-agents==1.32.0` is pinned separately in `agent/ledgerlens/requirements.txt`. For how much of the stored conversation reaches the model, see [CONTEXT_MANAGEMENT.md](CONTEXT_MANAGEMENT.md).

## The memory resource

The main stack creates the memory with the L2 `Memory` construct from `aws-cdk-lib/aws-bedrockagentcore` (`infra-cdk/lib/backend-construct.ts`):

```typescript
const memory = new agentcore.Memory(this, "AgentMemory", {
  memoryName: cdk.Names.uniqueResourceName(this, { maxLength: 48 }),
  expirationDuration: cdk.Duration.days(30),
  description: `Short-term memory for ${config.stack_name_base} agent`,
  memoryStrategies: [
    agentcore.MemoryStrategy.usingSemantic({
      strategyName: "FactExtractor",
      namespaces: ["/facts/{actorId}"],
    }),
  ],
  executionRole: agentRole,
  ...
})
```

- Conversation events expire after 30 days.
- One semantic strategy, `FactExtractor`, is always attached. It stores facts under `/facts/{actorId}`.
- The runtime gets the memory id as `MEMORY_ID`.
- The agent role gets one statement, `MemoryResourceAccess`, on the memory ARN: `bedrock-agentcore:CreateEvent`, `GetEvent` and `ListEvents` for short-term memory, plus `RetrieveMemoryRecords` for long-term retrieval.

## Short-term memory

`_create_session_manager(user_id, session_id)` in `agent/ledgerlens/ledgerlens_agent.py` creates a new session manager on every request:

```python
config = AgentCoreMemoryConfig(
    memory_id=memory_id,            # MEMORY_ID, required
    session_id=session_id,          # runtimeSessionId from the request body
    actor_id=user_id,               # the JWT sub claim
    retrieval_config=retrieval_config,  # None unless long-term memory is on
)
return AgentCoreMemorySessionManager(
    agentcore_memory_config=config,
    region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
)
```

- **`actor_id` is the Cognito user's `sub`** from the validated JWT, never a body field. Events and facts are stored per user, so changing the request body can't reach another user's memory.
- **`session_id` is the `runtimeSessionId`.** The frontend makes one per conversation with `crypto.randomUUID()`.

### What is saved with the session

Strands' session manager, as implemented by bedrock-agentcore, saves:

- **Every message, as a memory event.** The default `batch_size` is 1, so each message is sent as soon as it is added.
- **`agent.state`.** In LedgerLens this holds `session_context`, the customer's context loaded at session start (`tools/session_context.py`).
- **The conversation manager's state.** That is `removed_message_count`, plus the summary when summarization is on.
- **Strands' interrupt state.** This keeps a Yes/No confirmation pending across requests. When the customer taps a button, the next request restores the interrupt and resumes the exact tool call that was waiting (`tools/confirmation_hook.py`).

### What happens on the next request

Building the `Agent` with the session manager restores, in order:

1. `agent.state`.
2. The interrupt state.
3. The conversation manager's state.
4. The messages, from offset `removed_message_count` onward, with the saved summary in front when there is one.

AgentCore Memory events can't be changed after they are written. This matters for the guardrail. When it blocks a customer message, `guardrail_redact_input` makes Strands replace that message in `agent.messages` and call the session manager's `redact_latest_message()`. In bedrock-agentcore 1.4.7, `AgentCoreMemorySessionManager.update_message()` only logs, because events can't be updated. The stored event keeps the original text, and the next request restores it into the history.

## Enabling long-term memory

Long-term memory is off by default. Turn it on in `infra-cdk/config.yaml`:

```yaml
backend:
  use_long_term_memory: true   # default false
  ltm_top_k: 10                # facts retrieved per user message (default 10)
  ltm_relevance_score: 0.3     # minimum relevance score (default 0.3)
```

Then redeploy the main stack:

```bash
AWS_PROFILE=ledgerlens python scripts/deploy-with-codebuild.py ledgerlens-bank-assistant
```

A plain `cdk deploy` fails because the app has two stacks. A local deploy uses `cd infra-cdk && npx cdk deploy --all`. See [DEPLOYMENT.md](DEPLOYMENT.md#configuration).

The CDK passes these as `USE_LONG_TERM_MEMORY` (`"true"` or `"false"`), `LTM_TOP_K` and `LTM_RELEVANCE_SCORE`. When `USE_LONG_TERM_MEMORY` is `"true"`, the agent adds a retrieval config:

```python
top_k = int(os.environ.get("LTM_TOP_K", "10"))
relevance_score = float(os.environ.get("LTM_RELEVANCE_SCORE", "0.3"))

retrieval_config = (
    {"/facts/{actorId}": RetrievalConfig(top_k=top_k, relevance_score=relevance_score)}
    if use_ltm
    else None
)
```

### How retrieval works

bedrock-agentcore 1.4.7 does the following on each new user text message (not on tool results):

1. It runs a semantic search in `/facts/<sub>`, using the message text as the query.
2. It keeps the records that score at least `relevance_score`.
3. It inserts them at the start of that message as one `<user_context>…</user_context>` text block.

If retrieval fails, the error is logged and the turn goes on without facts.

### Extraction runs either way

The semantic strategy is always attached to the memory. AgentCore extracts long-term records in the background from the events of any memory that has a strategy ([AWS: Memory types](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-types.html)). So:

- `use_long_term_memory` only decides whether the agent **reads** the facts. Turning it off doesn't stop facts from being extracted from conversations.
- To stop extraction, remove the strategy from `memoryStrategies` in `backend-construct.ts`.

Costs, as listed in `config.yaml`: $0.75 per 1,000 long-term records stored and $0.50 per 1,000 retrieval calls. The retrieval cost applies only when the switch is on.

## Changing the memory setup

To add another long-term strategy:

1. Add it to `memoryStrategies` in `backend-construct.ts`. The construct has `MemoryStrategy.usingSummarization`, `usingUserPreference`, `usingEpisodic` and the built-in variants.
2. Add its namespace to `retrieval_config` in `_create_session_manager()`.
3. Redeploy.

`retrieval_config` takes one `RetrievalConfig` per namespace.

## References

- [AgentCore Memory developer guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html)
- [Strands SDK memory integration (AWS)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/strands-sdk-memory.html)
- [AgentCore Memory session manager for Strands](https://strandsagents.com/latest/documentation/docs/community/session-managers/agentcore-memory/)
