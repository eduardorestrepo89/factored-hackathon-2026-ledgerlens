# LedgerLens agent

The LedgerLens agent is the bank's chat assistant for credit card holders. It is a [Strands Agents](https://github.com/strands-agents/sdk-python) agent that runs in AgentCore Runtime. It reads the customer's cards and transactions, blocks a card, opens a fraud claim and hands off to a person. It does all of this through 9 tools on the AgentCore Gateway. AgentCore Memory keeps the conversation, and a Bedrock guardrail checks what goes in and out of the model.

The repo has only this agent. `backend.pattern: ledgerlens` in `infra-cdk/config.yaml` points the CDK at this folder.

## Files

| File | What it does |
|------|--------------|
| `ledgerlens_agent.py` | Runtime entrypoint (`invocations`). Builds a new agent for every request and streams its events. |
| `tools/system_prompt.py` | `BASE_SYSTEM_PROMPT`, `PROMPT_VERSION` and `build_system_prompt()`. |
| `tools/session_context.py` | Loads the customer's context once per session and puts it in the system prompt. |
| `tools/customer_id_hook.py` | `CustomerIdHook`: writes the token's `customer_id` into every tool call that takes one. |
| `tools/confirmation_hook.py` | `ConfirmationHook`: pauses a card block, a claim or a hand-off until the customer taps Yes or No. |
| `tools/conversation_memory.py` | Short-term memory window and optional summarization, from the `STM_*` variables. |
| `tools/guardrail.py` | Guardrail settings for the Bedrock model. |
| `tools/eval_override.py` | Per-session model and prompt override for evaluation logins. |
| `tools/gateway.py` | MCP client for the AgentCore Gateway. |
| `tools/mcp_registry.py` | Optional MCP servers discovered from an AWS Agent Registry (off by default). |
| `tools/leaked_markup.py` | Removes raw tool-call markup that some models leak into reply text. |
| `../utils/auth.py`, `../utils/ssm.py` | JWT claims, the Gateway token, SSM and Secrets Manager reads. Copied into the image as `utils/`. |
| `requirements.txt` | Pinned Python dependencies. |
| `Dockerfile` | The runtime image. |

Unit tests for these modules are in `tests/unit/` (`test_<module>.py`).

## What happens on each request

`invocations()` in `ledgerlens_agent.py` runs once per chat message:

1. It reads `prompt` and `runtimeSessionId` from the body. If either is missing, it sends an error event and stops.
2. It decodes the caller's JWT from the `Authorization` header (`extract_claims_from_context`). AgentCore Runtime has already validated the token, so the signature isn't checked again. The user id is the token's `sub` claim, never a body field.
3. It picks the model and base prompt with `resolve_eval_settings()`: `MODEL_ID` and `BASE_SYSTEM_PROMPT`, unless an evaluation login sends an override (see [Evaluation override](#evaluation-override)).
4. It gets one Gateway access token for the request (`get_gateway_access_token`). This is a Cognito client-credentials call that passes the user id as `aws_client_metadata`. The Cognito Pre-Token Lambda then adds the user's `customer_id` claim to the token.
5. It reads `customer_id` from that same token (`extract_customer_id_from_token`). The value is `""` when the user has no linked customer. The agent and the Gateway's Cedar policy check the same token, so they always agree on the customer.
6. It builds the agent (`create_strands_agent`): model, memory session manager, Gateway client, optional registry clients, system prompt, conversation manager, hooks and trace attributes.
7. It loads the session context into the system prompt (`apply_session_context`).
8. If the agent is waiting on a Yes/No answer from the last turn, the prompt becomes the answer to that confirmation (`resume_prompt`) instead of the user's text.
9. It streams `agent.stream_async(prompt)`. A confirmation event goes out before the event that carries it. Every event then passes through `LeakedMarkupFilter`.

Any exception in steps 2 to 9 ends the stream with `{"status": "error", "error": "<message>"}`. [docs/STREAMING.md](../../docs/STREAMING.md) covers the request body, every event on the wire and the confirmation round trip.

## Model

- `MODEL_ID` comes from `backend.model_id` in `infra-cdk/config.yaml`. It is set to `global.anthropic.claude-haiku-4-5-20251001-v1:0`. The CDK config manager uses `deepseek.v3.2` only when the key is missing (`infra-cdk/lib/utils/config-manager.ts`).
- The agent builds `BedrockModel(model_id, temperature=0.1, **MODEL_SETTINGS.get(model_id, {}), **guardrail_settings())`.
- `MODEL_SETTINGS` adds per-model options. Right now there is only one: `openai.gpt-oss-120b-1:0` gets `max_tokens=8192`, because it reasons before it answers.
- An evaluation login can switch to any model in `EVAL_MODEL_IDS` (see below). Customers always get `MODEL_ID`.

To change the model, edit `backend.model_id` and redeploy. A third-party model needs its Marketplace agreement accepted first (see [DEPLOYMENT.md](../../docs/DEPLOYMENT.md#prerequisites)).

## System prompt

`build_system_prompt(customer_id, session_context, base)` in `tools/system_prompt.py` builds the system prompt in three parts:

1. `base`. This is `BASE_SYSTEM_PROMPT`, or an evaluator's text.
2. One session block. A linked user gets "The signed-in customer's id is ...". A user with no linked customer gets the "not linked" block, which tells the model not to look anything up.
3. The session context, as compact JSON inside `<session_context>` tags, marked as data. `<` and `>` in that JSON are escaped, so database text can't close the tag.

`PROMPT_VERSION` (now `"v12"`) names the template. `tests/unit/test_system_prompt.py` pins the template's SHA-256 for each version in `PINNED_PROMPT_HASHES`, so editing the prompt without a version bump fails the tests. To change the prompt:

1. Edit `BASE_SYSTEM_PROMPT` or one of the session blocks.
2. Bump `PROMPT_VERSION`.
3. Add the new hash to `PINNED_PROMPT_HASHES`.

The version goes on every agent span as `prompt.version` and in one `[PROMPT]` log line per request.

## Tools

### Gateway tools

The agent has one MCP client for the AgentCore Gateway (`tools/gateway.py`). The client reads the Gateway URL from SSM (`/<STACK_NAME>/gateway_url`) and sends the request's access token as a bearer token. Its prefix is `gateway`. The Gateway names each tool `<target>___<tool>`, so the model sees `gateway_<target>___<tool>`, for example `gateway_list-credit-cards-target___list_credit_cards`.

The tools are defined in `infra-cdk/lib/backend-construct.ts`. Each one is a Lambda in `gateway/tools/<tool>/`:

| Tool | Gateway target | Yes/No confirmation |
|------|----------------|---------------------|
| `list_credit_cards` | `list-credit-cards-target` | No |
| `list_card_transactions` | `list-card-transactions-target` | No |
| `get_session_context` | `get-session-context-target` | No |
| `transaction_fraud_detection` | `fraud-detection-target` | No |
| `explain_transaction` | `explain-transaction-target` | No |
| `classify_call_type` | `classify-call-type-target` | No |
| `block_credit_card` | `block-credit-card-target` | Yes |
| `open_claim` | `open-claim-target` | Yes |
| `human_agent_hand_off` | `human-agent-hand-off-target` | Yes |

`transaction_fraud_detection` has a shorter target name for a reason. If any tool name is over 64 characters, Bedrock rejects every request, and `gateway_transaction-fraud-detection-target___transaction_fraud_detection` would be 73. Every tool takes `customer_id`. The Cedar policy (`gateway/policies/policy.cedar`) allows a call only when that input matches the token's `customer_id` claim. See [DEPLOYMENT.md](../../docs/DEPLOYMENT.md#gateway-tools) and [GATEWAY.md](../../docs/GATEWAY.md) for the tools themselves.

There is no Code Interpreter. The card questions don't need it, and it would add risk in a banking app.

### Registry tools (optional)

With `backend.mcp_registry.enabled: true`, the agent also connects to the MCP servers it finds in an AWS Agent Registry. These connections go straight to each server, not through the Gateway, so Cedar doesn't check them. See [docs/MCP_REGISTRY_DISCOVERY.md](../../docs/MCP_REGISTRY_DISCOVERY.md), including its security section.

## Hooks

The agent registers `hooks=[CustomerIdHook(customer_id), ConfirmationHook()]`. Both run on Strands' `BeforeToolCallEvent`, in that order.

**`CustomerIdHook`** (`tools/customer_id_hook.py`). The model is never the source of `customer_id`:

- For any tool whose input schema has a `customer_id` property, the hook overwrites the value with the token's `customer_id`, whatever the model wrote.
- If the user has no linked customer, the hook cancels the call with "This user's account is not linked to a customer...".
- It logs that it replaced a value, but never the value itself.

**`ConfirmationHook`** (`tools/confirmation_hook.py`) covers `block_credit_card`, `open_claim` and `human_agent_hand_off`. It matches on the part of the tool name after the last `___`.

- It skips a call that `CustomerIdHook` already cancelled.
- Otherwise it raises a Strands interrupt named `confirm_<tool>`. The agent stops with stop reason `interrupt`, the frontend shows Yes/No buttons, and the click comes back as the next request.
- **Yes:** the saved call runs. On `block_credit_card` and `open_claim`, the hook first sets `customer_confirmed: true`. Cedar requires that value, so it comes from the click, never from the model.
- **No:** the call is cancelled with a message telling the model not to retry.
- **Typed reply** instead of a click: also a No. The message carries the customer's text (up to 300 characters) so the model can answer it.

The order matters. `customer_id` is fixed before the confirmation, and the card shown to the customer leaves out `customer_id` and `customer_confirmed`.

## Session context

`tools/session_context.py` gives the model the customer's context without spending conversation messages on it.

- On the first request of a session, the agent calls `get_session_context` and `classify_call_type` in parallel. It calls them straight from the tool registry, not through the agent loop. Each call goes out with the token's `customer_id`.
- The results go into `agent.state["session_context"]` as `{"customer": ..., "likely_reasons": ...}`. The memory session manager saves `agent.state` with the session, so later requests read the context from state and don't call the tools again.
- The context is rendered into the system prompt on every request. The system prompt is outside `agent.messages`, so the conversation window never trims it or summarizes it.
- If either call fails, nothing is saved, the prompt goes out without `<session_context>`, and the next request tries again. A Lambda's `{"error": ...}` body counts as a failure, so an error never stays in the prompt for the whole session.
- Users with no linked customer skip this step.

## Memory

- **Short-term memory.** `AgentCoreMemorySessionManager` stores the conversation in AgentCore Memory. `actor_id` is the JWT `sub` and `session_id` is the request's `runtimeSessionId`. It also saves `agent.state` and the pending Yes/No interrupt.
- **Conversation window.** `create_conversation_manager()` sends the model at most `STM_WINDOW_SIZE` messages (30 by default). Older messages are dropped, or summarized when `use_stm_summarization` is on. See [docs/CONTEXT_MANAGEMENT.md](../../docs/CONTEXT_MANAGEMENT.md).
- **Long-term memory.** Off by default. With `use_long_term_memory: true`, the agent retrieves facts from `/facts/{actorId}`, using `LTM_TOP_K` and `LTM_RELEVANCE_SCORE`. See [docs/MEMORY_INTEGRATION.md](../../docs/MEMORY_INTEGRATION.md).

## Guardrail

`guardrail_settings()` reads `GUARDRAIL_ID` and `GUARDRAIL_VERSION`. If either is missing or blank, it raises, so the agent never runs without its guardrail. The guardrail is defined in `infra-cdk/lib/utils/agent-guardrail.ts`:

- It blocks prompt attacks, harmful content and four topic groups unrelated to banking: software and coding, general knowledge and schoolwork, entertainment and lifestyle, and politics, religion, legal and medical questions.
- It masks nothing. Card digits, amounts and merchants reach the customer unchanged.
- Banking requests the agent can't serve, such as loans or new products, aren't blocked here. The system prompt declines those and offers a person.

The settings passed to `BedrockModel`:

| Setting | Value | Why |
|---------|-------|-----|
| `guardrail_trace` | `"enabled"` | Guardrail decisions show up in traces. |
| `guardrail_stream_processing_mode` | `"sync"` | Each reply chunk is held until it has been checked, so a blocked reply is never half shown. |
| `guardrail_latest_message` | `True` | Only the customer's newest message is checked, not the history or tool results. |
| `guardrail_redact_input` | `True` | Strands replaces a blocked customer message in `agent.messages` for the rest of the request. AgentCore Memory can't update a stored event, so the next request restores the original text ([MEMORY_INTEGRATION.md](../../docs/MEMORY_INTEGRATION.md#what-happens-on-the-next-request)). |
| `guardrail_redact_output` | `False` | Bedrock already replies with the guardrail's blocked message. Redaction would overwrite it with "[Assistant output redacted.]". |

## Leaked tool-call markup

On Bedrock, DeepSeek V3.2 sometimes starts its text after a tool call with its raw marker, `<｜DSML｜function_calls`. `LeakedMarkupFilter` (`tools/leaked_markup.py`) strips that marker from streamed text before it reaches the browser. [docs/STREAMING.md](../../docs/STREAMING.md#leaked-markup-filter) explains how this changes the events.

## Evaluation override

The harness in `evals/` compares models and prompt versions against the deployed agent ([evals/README.md](../../evals/README.md)). A request may carry:

```json
{"eval": {"model_id": "deepseek.v3.2", "prompt_name": "v12-short", "system_prompt": "..."}}
```

`resolve_eval_settings()` in `tools/eval_override.py` applies these rules:

- Only a caller whose JWT lists the Cognito group `evaluators` (`cognito:groups`) gets the override. For anyone else, `eval` is ignored with a warning, and the request runs on the defaults.
- `eval` must be an object. `model_id` defaults to `MODEL_ID` and must be in `EVAL_MODEL_IDS` (`backend.eval_model_ids`, joined with commas).
- `system_prompt` is optional. When it is present, it must be 1 to 40,000 characters of non-blank text, and `prompt_name` must match `[a-z0-9][a-z0-9._-]{0,31}`. The span's prompt version becomes `<prompt_name>-<first 8 hex of its SHA-256>`.
- An invalid override from an evaluator doesn't fall back to the defaults. It ends the request with `{"status": "error", "error": "eval override rejected: ..."}`.
- The text replaces only `BASE_SYSTEM_PROMPT`. The session blocks, both hooks, the guardrail and Cedar apply exactly as they do for a customer.

## Observability

Every agent gets `trace_attributes` with `user.id` (JWT `sub`), `session.id`, `model.id` and `prompt.version`. With these, traces and evaluations can tell users, models and prompt versions apart. The container starts under `opentelemetry-instrument` (see [Container image](#container-image)). Log lines are tagged by area: `[PROMPT]`, `[CUSTOMER-ID]`, `[CONFIRM]`, `[SESSION-START]`, `[STM]`, `[EVAL]`, `[GATEWAY]`, `[MCP-REGISTRY]`.

## Environment variables

The CDK sets these on the runtime in `infra-cdk/lib/backend-construct.ts`. All values come from `infra-cdk/config.yaml` unless noted.

| Variable | Source | Used by |
|----------|--------|---------|
| `AWS_REGION`, `AWS_DEFAULT_REGION` | Stack region | SSM, Secrets Manager, Cognito, memory, registry clients |
| `MEMORY_ID` | The memory resource | Session manager (required) |
| `STACK_NAME` | `stack_name_base` | SSM and Secrets Manager paths in `utils/auth.py` and `tools/gateway.py` |
| `GATEWAY_CREDENTIAL_PROVIDER_NAME` | `<stack>-runtime-gateway-auth` | Nothing in the active code. Only the commented-out decorator option in `tools/gateway.py` uses it. |
| `MODEL_ID` | `backend.model_id` | The agent's model (required) |
| `EVAL_MODEL_IDS` | `backend.eval_model_ids`, comma-joined | Evaluation override allowlist |
| `USE_LONG_TERM_MEMORY` | `backend.use_long_term_memory` (`"true"`/`"false"`) | Long-term memory retrieval |
| `LTM_TOP_K`, `LTM_RELEVANCE_SCORE` | `backend.ltm_top_k`, `backend.ltm_relevance_score` | Long-term memory retrieval (defaults 10 and 0.3) |
| `STM_WINDOW_SIZE`, `USE_STM_SUMMARIZATION`, `STM_SUMMARY_RATIO`, `STM_PRESERVE_RECENT_MESSAGES`, `STM_SUMMARIZATION_MODEL_ID`, `STM_SUMMARIZATION_PROMPT` | `backend.stm_*` | Conversation window and summarization |
| `MCP_REGISTRY_DISCOVERY_ENABLED`, `MCP_REGISTRY_ID` | `backend.mcp_registry` (always set: `"false"` and `""` when off) | Registry discovery |
| `GUARDRAIL_ID`, `GUARDRAIL_VERSION` | The guardrail construct | Guardrail (required) |

The agent also reads these at runtime:

- From SSM: `/<STACK_NAME>/gateway_url`, `/<STACK_NAME>/cognito_provider` and `/<STACK_NAME>/machine_client_id`.
- From Secrets Manager: `/<STACK_NAME>/machine_client_secret`.

## Security

- **User identity.** The user id comes from the validated JWT's `sub` claim, never from the request body, so a prompt or a body field can't impersonate another user.
- **Customer id.** It comes from the Gateway token, not from the model or the user. `CustomerIdHook` overwrites it on every tool call. Cedar then checks it against the same token at the Gateway.
- **Confirmed actions.** `customer_confirmed` comes only from a Yes click (`ConfirmationHook`). Cedar requires it on `block_credit_card` and `open_claim`.
- **Gateway auth.** The Gateway accepts only the Cognito machine client's tokens (OAuth2 client credentials). The user's identity reaches Cedar through claims that the Pre-Token Lambda adds.
- **`STACK_NAME`.** It comes from the CDK. `tools/gateway.py` checks that it contains only letters, digits, `-` and `_`. `utils/auth.py` builds the Cognito SSM and Secrets Manager paths from it before that check runs, because the token is fetched before the Gateway client is built.
- **Payload.** `prompt` and `runtimeSessionId` are required. An `eval` field takes effect only for the `evaluators` group.

## Container image

`Dockerfile`:

- Base image: `ghcr.io/astral-sh/uv:python3.13-bookworm-slim`.
- Installs `requirements.txt` plus `aws-opentelemetry-distro==0.16.0`.
- Copies `agent/ledgerlens/ledgerlens_agent.py`, `agent/ledgerlens/tools/` and `agent/utils/` (as `utils/`).
- Runs as the non-root user `bedrock_agentcore` (uid 1000) on port 8080, with a health check on `/ping`.
- Starts with `opentelemetry-instrument python -m ledgerlens_agent`.

The `COPY` paths are relative to the repository root. The CDK builds the image with the repo root as context and `agent/ledgerlens/Dockerfile` as the file, for `linux/arm64` (`backend-construct.ts`). A local build has to do the same:

```bash
docker build --platform linux/arm64 -f agent/ledgerlens/Dockerfile .
```

`backend.deployment_type: zip` packages the same files and requirements with a Lambda instead, for the runtime's Python 3.12. See [DEPLOYMENT.md](../../docs/DEPLOYMENT.md#configuration).

## Deploying changes

Any change under `agent/` needs a deploy of the main stack:

```bash
AWS_PROFILE=ledgerlens python scripts/deploy-with-codebuild.py ledgerlens-bank-assistant
```

A plain `cdk deploy` fails because the app has two stacks. To deploy locally, use `cd infra-cdk && npx cdk deploy --all`. That builds the ARM64 image on your machine. See [DEPLOYMENT.md](../../docs/DEPLOYMENT.md) for the full steps.

## Dependencies

From `requirements.txt`:

```
strands-agents==1.32.0
bedrock-agentcore==1.4.7
mcp==1.28.1
PyJWT[crypto]==2.13.0
requests>=2.31.0
boto3>=1.43.66
botocore>=1.43.66
```

`requests` makes the Cognito token call. boto3/botocore 1.43.66 or later ship the `agent-registry` client used by `tools/mcp_registry.py`. Several modules rely on Strands internals (`_interrupt_state`, hook event fields, conversation manager state) and say so in their docstrings ("Checked against strands-agents 1.32.0"). Re-check them when you upgrade Strands.
