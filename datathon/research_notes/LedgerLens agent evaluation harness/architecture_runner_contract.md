# LedgerLens runner contract: how a test runner drives the deployed agent and what it can observe

Scope: the code in the `feat/eval-resume` worktree (from `stage` at `1b4b4ed`), plus the library code the agent pins: `strands-agents==1.32.0` (installed in the main checkout's `.venv`) and `bedrock-agentcore==1.4.7` (the wheel in the local uv cache, the same version as `agent/ledgerlens/requirements.txt`). Nothing was invoked or deployed, and no AWS API was called. It builds on `datathon/docs/analysis/2026-10-03-eval-observability-on-hold.md` §3 (L1–L11) and `datathon/research_notes/Agent evaluation signal on AWS/verification_2026-10-03.md`.

Citation conventions:
- Repo files are linked relative to this file, with line numbers.
- Library files are linked by absolute path. `strands/...` means `D:\Proyectos\ledgerlens-bank-assistant\.venv\Lib\site-packages\strands\...`. `bedrock_agentcore/...` means the 1.4.7 wheel in the uv cache.
- No secrets, passwords, tokens or Cognito subs are copied here.

## 1. Invocation: how a client calls the deployed agent end to end

### Takeaway
1. Sign in with Cognito `USER_PASSWORD_AUTH` on the web app client (it has no secret) and take the **access token**.
2. POST JSON `{"prompt", "runtimeSessionId"[, "confirmations"]}` to `https://bedrock-agentcore.<region>.amazonaws.com/runtimes/<URL-encoded RuntimeArn>/invocations?qualifier=DEFAULT`. Send `Authorization: Bearer <access token>` and `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: <same id>`.
3. Read the `text/event-stream` response: one `data: <json>` line per event.

`boto3 invoke_agent_runtime` (SigV4), as in sketch (a) of the verification note, does not fit this agent. The agent needs the user's JWT in the `Authorization` header.

### Cited Findings
- **The runtime authorizer is JWT, not IAM.** It accepts tokens from the Cognito pool's discovery URL, restricted to the web app client id ([infra-cdk/lib/backend-construct.ts:241-245](../../../infra-cdk/lib/backend-construct.ts#L241-L245)). The runtime forwards only the `Authorization` header to the agent ([backend-construct.ts:451-453](../../../infra-cdk/lib/backend-construct.ts#L451-L453)).
- **The agent requires that header.** It decodes the JWT's `sub` as `user_id` and raises if the header or `sub` is missing ([agent/utils/auth.py:48-87](../../../agent/utils/auth.py#L48-L87)). It calls this on every request ([agent/ledgerlens/ledgerlens_agent.py:175](../../../agent/ledgerlens/ledgerlens_agent.py#L175)).
- **The web app client.**
  - `generateSecret: false`, `authFlows: {userPassword: true, userSrp: true}`, OAuth authorization-code grant ([infra-cdk/lib/cognito-construct.ts:70-88](../../../infra-cdk/lib/cognito-construct.ts#L70-L88)).
  - The pool has self sign-up off and email sign-in ([cognito-construct.ts:31-39](../../../infra-cdk/lib/cognito-construct.ts#L31-L39)).
- **The existing auth helper.** `scripts/utils.authenticate_cognito` calls `cognito-idp.initiate_auth(AuthFlow="USER_PASSWORD_AUTH", ClientId, AuthParameters={USERNAME, PASSWORD})` and returns `(AccessToken, IdToken, sub)` ([scripts/utils.py:119-176](../../../scripts/utils.py#L119-L176)). It first calls `admin_get_user` ([scripts/utils.py:143-147](../../../scripts/utils.py#L143-L147)).
- **Which token goes where.** The access token goes to the runtime and the ID token to API Gateway (the feedback API) ([scripts/utils.py:131-135](../../../scripts/utils.py#L131-L135); [test-scripts/test-agent.py:504-505](../../../test-scripts/test-agent.py#L504-L505); [frontend/src/components/chat/ChatInterface.tsx:306-307](../../../frontend/src/components/chat/ChatInterface.tsx#L306-L307)).
- **Where the config comes from.**
  - Main-stack CloudFormation outputs `CognitoUserPoolId`, `CognitoClientId` and `RuntimeArn` ([infra-cdk/lib/ledgerlens-main-stack.ts:56-77](../../../infra-cdk/lib/ledgerlens-main-stack.ts#L56-L77)). They are read with `cloudformation.describe_stacks` on `stack_name_base` from `infra-cdk/config.yaml` ([scripts/utils.py:33-76](../../../scripts/utils.py#L33-L76); [infra-cdk/config.yaml:1](../../../infra-cdk/config.yaml#L1)).
  - `test-agent.py` requires exactly those three outputs ([test-scripts/test-agent.py:479-483](../../../test-scripts/test-agent.py#L479-L483)).
  - Alternatively, `frontend/public/aws-exports.json`, written by `scripts/deploy-frontend.py --config-only`. It holds `authority` (from the pool id), `client_id`, `agentRuntimeArn` and `awsRegion` ([scripts/deploy-frontend.py:376-385](../../../scripts/deploy-frontend.py#L376-L385); [README.md:137-142](../../../README.md#L137-L142)). It is gitignored by the root pattern `public/` ([.gitignore:32](../../../.gitignore#L32)), so it is absent from a fresh worktree.
- **URL.** `https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{quote(runtime_arn, safe="")}/invocations?qualifier=DEFAULT` ([test-scripts/test-agent.py:357-360](../../../test-scripts/test-agent.py#L357-L360); [frontend/src/lib/agentcore-client/client.ts:32-34](../../../frontend/src/lib/agentcore-client/client.ts#L32-L34)).
- **Headers.** `Authorization: Bearer <access token>`, `Content-Type: application/json` and `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: <session id>`. An optional `X-Amzn-Trace-Id` is set to `1-<hex epoch>-<uuid4>` ([test-scripts/test-agent.py:59-67](../../../test-scripts/test-agent.py#L59-L67), [:362-366](../../../test-scripts/test-agent.py#L362-L366), [:233](../../../test-scripts/test-agent.py#L233); [client.ts:36-56](../../../frontend/src/lib/agentcore-client/client.ts#L36-L56)). The SDK reads the session header as `SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"` ([bedrock_agentcore/runtime/models.py:17](file:///C:/Users/sebas/AppData/Local/uv/cache/archive-v0/M-7OR1epxWt0Gq7T/bedrock_agentcore/runtime/models.py)).
- **Payload fields.**
  - The entrypoint reads only `payload["prompt"]`, `payload["runtimeSessionId"]` and, on a resume, `payload["confirmations"]`. If `prompt` or `runtimeSessionId` is empty, it yields `{"status":"error","error":"Missing required fields: prompt or runtimeSessionId"}` and stops ([ledgerlens_agent.py:164-172](../../../agent/ledgerlens/ledgerlens_agent.py#L164-L172), [:189-191](../../../agent/ledgerlens/ledgerlens_agent.py#L189-L191); [agent/ledgerlens/tools/confirmation_hook.py:85-99](../../../agent/ledgerlens/tools/confirmation_hook.py#L85-L99)).
  - The frontend sends `{...extra, prompt, runtimeSessionId}`, where `extra` is `{confirmations: [...]}` only for a button click ([client.ts:38-42](../../../frontend/src/lib/agentcore-client/client.ts#L38-L42); [ChatInterface.tsx:176-177](../../../frontend/src/components/chat/ChatInterface.tsx#L176-L177)).
  - User identity is never sent in the body ([client.ts:44-46](../../../frontend/src/lib/agentcore-client/client.ts#L44-L46)).
- **The body's `runtimeSessionId` keys the conversation memory.** It becomes the AgentCore Memory `session_id`, with `actor_id` = the JWT `sub` ([ledgerlens_agent.py:77-82](../../../agent/ledgerlens/ledgerlens_agent.py#L77-L82), [:165](../../../agent/ledgerlens/ledgerlens_agent.py#L165), [:180](../../../agent/ledgerlens/ledgerlens_agent.py#L180)). The header routes the runtime session. Both clients send the same value in both places ([test-agent.py:225](../../../test-scripts/test-agent.py#L225), [:365](../../../test-scripts/test-agent.py#L365); [client.ts:41](../../../frontend/src/lib/agentcore-client/client.ts#L41), [:53](../../../frontend/src/lib/agentcore-client/client.ts#L53)).
- **Session id length.** The verified rule is 33–256 characters on the request, but 1–100 characters of `[a-zA-Z0-9][a-zA-Z0-9-_]*` on the echoed header, so use 33–100 ([verification_2026-10-03.md row 9](../Agent%20evaluation%20signal%20on%20AWS/verification_2026-10-03.md)). Both existing clients use a UUID4 (36 characters) ([scripts/utils.py:184-186](../../../scripts/utils.py#L184-L186); [client.ts:17-19](../../../frontend/src/lib/agentcore-client/client.ts#L17-L19); [ChatInterface.tsx:38](../../../frontend/src/components/chat/ChatInterface.tsx#L38)).
- **Response format.**
  - The entrypoint is an async generator. `BedrockAgentCoreApp` wraps it in `StreamingResponse(..., media_type="text/event-stream")` ([ledgerlens_agent.py:157-158](../../../agent/ledgerlens/ledgerlens_agent.py#L157-L158); [bedrock_agentcore/runtime/app.py:417-420](file:///C:/Users/sebas/AppData/Local/uv/cache/archive-v0/M-7OR1epxWt0Gq7T/bedrock_agentcore/runtime/app.py)).
  - Each yielded object becomes `data: <json.dumps(obj, ensure_ascii=False)>\n\n`, with fallbacks for objects that don't serialize ([app.py:674-713](file:///C:/Users/sebas/AppData/Local/uv/cache/archive-v0/M-7OR1epxWt0Gq7T/bedrock_agentcore/runtime/app.py)).
  - Both clients skip blank lines and parse lines that start with `data: ` ([test-agent.py:246-250](../../../test-scripts/test-agent.py#L246-L250); [frontend/src/lib/agentcore-client/utils/sse.ts:28-35](../../../frontend/src/lib/agentcore-client/utils/sse.ts#L28-L35); [frontend/src/lib/agentcore-client/parsers/strands.ts:14-20](../../../frontend/src/lib/agentcore-client/parsers/strands.ts#L14-L20)).
- **Errors inside a 200 stream.**
  - The agent catches every exception and yields `{"status":"error","error":"<str(e)>"}` ([ledgerlens_agent.py:200-202](../../../agent/ledgerlens/ledgerlens_agent.py#L200-L202)).
  - If the generator still raises, the SDK yields `{"error", "error_type", "message":"An error occurred during streaming"}` ([app.py:660-672](file:///C:/Users/sebas/AppData/Local/uv/cache/archive-v0/M-7OR1epxWt0Gq7T/bedrock_agentcore/runtime/app.py)).
  - Non-JSON bodies get HTTP 400 `{"error":"Invalid JSON"}` ([app.py:439-442](file:///C:/Users/sebas/AppData/Local/uv/cache/archive-v0/M-7OR1epxWt0Gq7T/bedrock_agentcore/runtime/app.py)).
  - The clients treat any non-200 status as a failed turn ([test-agent.py:240-242](../../../test-scripts/test-agent.py#L240-L242); [client.ts:58-61](../../../frontend/src/lib/agentcore-client/client.ts#L58-L61)).
- **The agent is rebuilt on every request.** Each request runs these steps:
  1. Fetch a fresh Gateway machine token ([ledgerlens_agent.py:176-180](../../../agent/ledgerlens/ledgerlens_agent.py#L176-L180)).
  2. Inside that fetch, two SSM `GetParameter` calls and one Secrets Manager `GetSecretValue` ([agent/utils/auth.py:204-206](../../../agent/utils/auth.py#L204-L206)).
  3. One more SSM call, for `gateway_url` ([agent/ledgerlens/tools/gateway.py:65](../../../agent/ledgerlens/tools/gateway.py#L65)).

  Nothing is cached ([agent/utils/ssm.py:17-38](../../../agent/utils/ssm.py#L17-L38)).
- **The interactive script isn't scriptable as is.** `test-agent.py` asks for the username and password with `input()`/`getpass` ([test-agent.py:493-497](../../../test-scripts/test-agent.py#L493-L497)). Its `requests.post(..., stream=True, timeout=60)` is a 60 s read timeout between chunks ([test-agent.py:236-238](../../../test-scripts/test-agent.py#L236-L238)).
- **Where the password lives.** The demo login's password is shared out of band and never kept in git ([README.md:144](../../../README.md#L144)).

### Inferences
- **No SigV4.** A runner should not use `boto3 bedrock-agentcore.invoke_agent_runtime` (verification note, sketch (a)). Without a user JWT in `Authorization`, the agent's `extract_user_id_from_context` raises. The JWT-configured runtime most likely rejects SigV4 anyway; that part comes from AWS behaviour, not this repo. Use plain HTTPS, as `test-agent.py` and `client.ts` do.
- **Skip `admin_get_user`.** It needs IAM admin credentials. `initiate_auth` with `USER_PASSWORD_AUTH` on a secret-less client needs no `SECRET_HASH`, so the runner can call it directly.
- **Refresh the token.** The CDK sets no token validity (no `accessTokenValidity` in `infra-cdk/lib`), so Cognito's default applies (1 h, an AWS default not stated in the repo). A multi-hour run should sign in again about every 50 minutes, or use `REFRESH_TOKEN_AUTH`.
- **Session ids.** Use a fresh session id per trial, the same in the body and the header, for example `f"ll-{case_id}-r{k}-{uuid4().hex}"` (about 50 characters, `[A-Za-z0-9_-]`). Never reuse one across trials (see §4).

#### Minimal runner call (pseudo-code)

```python
import json, os, uuid, requests, boto3
from urllib.parse import quote

REGION, RUNTIME_ARN, CLIENT_ID = cfg["region"], cfg["RuntimeArn"], cfg["CognitoClientId"]  # stack outputs or aws-exports.json
URL = (f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/"
       f"{quote(RUNTIME_ARN, safe='')}/invocations?qualifier=DEFAULT")

def login(username: str) -> str:                       # password from env, never from git
    r = boto3.client("cognito-idp", region_name=REGION).initiate_auth(
        AuthFlow="USER_PASSWORD_AUTH", ClientId=CLIENT_ID,
        AuthParameters={"USERNAME": username, "PASSWORD": os.environ["LL_EVAL_PASSWORD"]})
    return r["AuthenticationResult"]["AccessToken"]    # ACCESS token, not IdToken

def turn(token: str, sid: str, prompt: str, confirmations: list | None = None) -> list[dict]:
    body = {"prompt": prompt, "runtimeSessionId": sid}  # prompt must be non-empty, even on a resume
    if confirmations is not None:
        body["confirmations"] = confirmations           # [{"interruptId": id, "approved": bool}]
    with requests.post(URL, json=body, stream=True, timeout=(10, 300), headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": sid}) as r:
        r.raise_for_status()                            # 4xx/5xx: infra failure, not a grade
        return [json.loads(l[6:]) for l in r.iter_lines(decode_unicode=True)
                if l and l.startswith("data: ")]

sid = f"ll-P07-r1-{uuid.uuid4().hex}"                   # 33..100 chars, new per trial
events = turn(token, sid, "No reconozco un cargo en mi tarjeta")
```

### Gaps
- **Error codes.** The repo does not show which HTTP status the runtime returns for an expired token, an over-length session id or throttling.
- **The trace header.** It is unknown whether the runtime honours the client's `X-Amzn-Trace-Id`. The value both clients build (`1-<hex>-<uuid4 with dashes>`) is not a valid X-Ray trace id (24 hex characters after the second dash), so it is probably replaced. This is an inference, not verified.
- **Duration limits.** The runtime's maximum request duration and idle-session timeout are not set in the CDK (no lifecycle settings in `backend-construct.ts:443-455`). The AWS defaults apply and were not checked here.

## 2. Stream content: which events reach the client, and where are tool calls, inputs and results?

### Takeaway
The client receives every Strands callback event, each passed through `json.loads(json.dumps(dict(event), default=str))` and then `LeakedMarkupFilter`, plus LedgerLens's own `confirmation` and error events.

The reliable sources are the complete `message` events:
- **Calls:** an `assistant` message's `toolUse` blocks give `toolUseId`, `name` = `gateway_<target>___<tool>`, and `input` exactly as the model wrote it.
- **Results:** a `user` message's `toolResult` blocks give `toolUseId`, `status` and `content[].text`.

Raw Bedrock chunks (`{"event": ...}`) add the per-model-call `stopReason`, token `usage`, `latencyMs` and the guardrail trace.

On the wire, the final `result` is a **string**, so it carries no `stop_reason`.

### Cited Findings
- **The streaming loop.** For each Strands event, the entrypoint first yields any `confirmation_events(event)`. Then it yields `markup.clean(json.loads(json.dumps(dict(event), default=str)))` ([ledgerlens_agent.py:193-198](../../../agent/ledgerlens/ledgerlens_agent.py#L193-L198)). `docs/STREAMING.md:29-32` documents the `default=str` conversion.
- **What Strands yields.** `Agent.stream_async` yields `event.as_dict()` for every event with `is_callback_event`. Last, it yields `AgentResultEvent(result=AgentResult)` ([strands/agent/agent.py:771-784](file:///D:/Proyectos/ledgerlens-bank-assistant/.venv/Lib/site-packages/strands/agent/agent.py)).
- **Callback event types in strands 1.32.0** ([strands/types/_events.py](file:///D:/Proyectos/ledgerlens-bank-assistant/.venv/Lib/site-packages/strands/types/_events.py)):

  | Wire event (top-level keys) | Strands class (line) | Notes |
  |---|---|---|
  | `{"init_event_loop": true, ...invocation_state}` | `InitEventLoopEvent` (56-72) | merges `invocation_state` |
  | `{"start": true}`, `{"start_event_loop": true}` | `StartEvent` (75-87), `StartEventLoopEvent` (90-99) | lifecycle |
  | `{"event": <raw Bedrock ConverseStream chunk>}` | `ModelStreamChunkEvent` (102-111) | `messageStart`, `contentBlockStart/Delta/Stop`, `messageStop{stopReason}`, `metadata{usage, metrics, trace}`, `redactContent`. Yielded for every chunk ([strands/event_loop/streaming.py:433](file:///D:/Proyectos/ledgerlens-bank-assistant/.venv/Lib/site-packages/strands/event_loop/streaming.py)) |
  | `{"data": "<text>", "delta": {...}, ...invocation_state}` | `TextStreamEvent` (152-157); `ModelStreamEvent.prepare` merges `invocation_state` when `delta` is present (139-141) | token text |
  | `{"type":"tool_use_stream", "delta": {"toolUse":{"input": "<partial json>"}}, "current_tool_use": {"toolUseId","name","input"}, ...invocation_state}` | `ToolUseStreamEvent` (144-149) | tool input streaming |
  | `{"reasoningText"...}` / `{"citation"...}` | 160-189 | only if the model emits them |
  | `{"message": {"role":"assistant","content":[{"text"},{"toolUse":{"toolUseId","name","input"}}]}}` | `ModelMessageEvent` (367-380) | complete model turn, yielded before any tool runs |
  | `{"message": {"role":"user","content":[{"toolResult":{"toolUseId","status","content":[{"text"}]}}]}}` | `ToolResultMessageEvent` (383-397) | the **only** way tool results reach the client: `ToolResultEvent` has `is_callback_event = False` (276-305) |
  | `{"tool_interrupt_event": {"tool_use": {...}, "interrupts": ["Interrupt(id=..., name='confirm_<tool>', ...)"]}}` | `ToolInterruptEvent` (349-354) | `Interrupt` is a dataclass, so `default=str` turns it into its repr |
  | `{"tool_cancel_event": {"tool_use": {...}, "message": "<cancel text>"}}` | `ToolCancelEvent` (326-336) | No click, typed reply, or unlinked user |
  | `{"event_loop_throttled_delay": n, ...}` | `EventLoopThrottleEvent` (260-273) | model throttling with retry |
  | `{"force_stop": true, "force_stop_reason": "..."}` | `ForceStopEvent` (400-414) | forced stop |
  | `{"result": "<string>"}` | `AgentResultEvent` (417-419) | see the `result` bullet below |

- **Extra keys on many events.** `invocation_state` is one dict shared through the whole invocation, so it accumulates keys:
  - `agent` is added at [strands/agent/agent.py:895](file:///D:/Proyectos/ledgerlens-bank-assistant/.venv/Lib/site-packages/strands/agent/agent.py).
  - `event_loop_cycle_id`, `request_state`, `event_loop_cycle_trace` and `event_loop_cycle_span` are added at [strands/event_loop/event_loop.py:120-140](file:///D:/Proyectos/ledgerlens-bank-assistant/.venv/Lib/site-packages/strands/event_loop/event_loop.py).
  - When a tool executes, `model`, `messages`, `system_prompt` and `tool_config` are added at [strands/tools/executors/_executor.py:138-149](file:///D:/Proyectos/ledgerlens-bank-assistant/.venv/Lib/site-packages/strands/tools/executors/_executor.py).

  So `data` and `current_tool_use` events carry these keys, stringified where needed. The team's hand-off note confirms that every `data` event "carries Strands' internal invocation state (system prompt, messages, tool config)". It tells clients to read only `data`, `current_tool_use`, `delta`, `message`, `result`, `confirmation` and the lifecycle keys ([docs/handoffs/2026-10-04-confirmation-buttons-frontend.md:92-95](../../../docs/handoffs/2026-10-04-confirmation-buttons-frontend.md#L92-L95)).
- **The final `result` is a string on the wire.** `AgentResult` is a dataclass ([strands/agent/agent_result.py:18-36](file:///D:/Proyectos/ledgerlens-bank-assistant/.venv/Lib/site-packages/strands/agent/agent_result.py)), so `default=str` replaces it with `str(AgentResult)`:
  - after an interrupt, the Python repr of the list of interrupt dicts;
  - otherwise, the final message's text blocks joined with `\n` ([agent_result.py:38-68](file:///D:/Proyectos/ledgerlens-bank-assistant/.venv/Lib/site-packages/strands/agent/agent_result.py)).

  The frontend parser therefore reports `stopReason` as `"end_turn"` for every string result ([parsers/strands.ts:84-90](../../../frontend/src/lib/agentcore-client/parsers/strands.ts#L84-L90)).
- **Tool names as the model sees them.**
  - The Gateway MCP client is created with `prefix="gateway"` ([agent/ledgerlens/tools/gateway.py:68-74](../../../agent/ledgerlens/tools/gateway.py#L68-L74)). Strands renames each tool `f"{prefix}_{tool.name}"` ([strands/tools/mcp/mcp_client.py:424-427](file:///D:/Proyectos/ledgerlens-bank-assistant/.venv/Lib/site-packages/strands/tools/mcp/mcp_client.py)).
  - Gateway tool names are `<target>___<tool>`, with targets `<slug>-target` except `fraud-detection-target`, kept short because Bedrock rejects tool names over 64 characters ([backend-construct.ts:875-891](../../../infra-cdk/lib/backend-construct.ts#L875-L891), [:919](../../../infra-cdk/lib/backend-construct.ts#L919); [gateway/policies/policy.cedar:18-22](../../../gateway/policies/policy.cedar#L18-L22), [:38-46](../../../gateway/policies/policy.cedar#L38-L46)).
  - So the nine model-visible names are:

    | Model-visible name |
    |---|
    | `gateway_list-credit-cards-target___list_credit_cards` |
    | `gateway_list-card-transactions-target___list_card_transactions` |
    | `gateway_get-session-context-target___get_session_context` |
    | `gateway_fraud-detection-target___transaction_fraud_detection` |
    | `gateway_explain-transaction-target___explain_transaction` |
    | `gateway_classify-call-type-target___classify_call_type` |
    | `gateway_block-credit-card-target___block_credit_card` |
    | `gateway_open-claim-target___open_claim` |
    | `gateway_human-agent-hand-off-target___human_agent_hand_off` |
  - Agent code and the frontend reduce a name to the bare tool with `rpartition("___")[2]` or `split("___").pop()` ([confirmation_hook.py:31](../../../agent/ledgerlens/tools/confirmation_hook.py#L31), [:55](../../../agent/ledgerlens/tools/confirmation_hook.py#L55); [frontend/src/hooks/useToolRenderer.ts:16](../../../frontend/src/hooks/useToolRenderer.ts#L16)).
- **The streamed tool input is what the model wrote, not what ran.**
  - `CustomerIdHook` replaces `event.tool_use` with a new dict whose `customer_id` comes from the token ([agent/ledgerlens/tools/customer_id_hook.py:60-72](../../../agent/ledgerlens/tools/customer_id_hook.py#L60-L72)).
  - `ConfirmationHook` adds `customer_confirmed: true` only after a Yes ([confirmation_hook.py:66-70](../../../agent/ledgerlens/tools/confirmation_hook.py#L66-L70)).
  - The executor runs `before_event.tool_use` ([strands/tools/executors/_executor.py:180-182](file:///D:/Proyectos/ledgerlens-bank-assistant/.venv/Lib/site-packages/strands/tools/executors/_executor.py)). The assistant `message` with the original `toolUse` was already streamed (`ModelMessageEvent`).
- **Tool result shape.**
  - Strands maps the MCP result to `{"toolUseId", "status": "error" if isError else "success", "content": [...]}`, and adds `structuredContent` when present ([mcp_client.py:678-709](file:///D:/Proyectos/ledgerlens-bank-assistant/.venv/Lib/site-packages/strands/tools/mcp/mcp_client.py)).
  - A transport or protocol exception becomes `status: "error"` with the text `"Tool execution failed: <exception>"` ([mcp_client.py:670-675](file:///D:/Proyectos/ledgerlens-bank-assistant/.venv/Lib/site-packages/strands/tools/mcp/mcp_client.py)).
  - The Lambdas return `{"content":[{"type":"text","text": <JSON>}]}` on success and `{"error": <message>}` on failure ([gateway/tools/block_credit_card/block_credit_card_lambda/delivery/handler.py:11-13](../../../gateway/tools/block_credit_card/block_credit_card_lambda/delivery/handler.py#L11-L13), [:86-101](../../../gateway/tools/block_credit_card/block_credit_card_lambda/delivery/handler.py#L86-L101)).
  - The Gateway may pass the Lambda's whole `{"content":[{"text":...}]}` on as text, so both the agent and the frontend unwrap one level. They treat a body with an `"error"` key as a failure even when `status` is `success` ([agent/ledgerlens/tools/session_context.py:35-49](../../../agent/ledgerlens/tools/session_context.py#L35-L49); [frontend/src/lib/handoff.ts:34-49](../../../frontend/src/lib/handoff.ts#L34-L49)).
- **Session-start tool calls are not in the stream.**
  - `apply_session_context` runs `get_session_context` and `classify_call_type` in parallel through `registry[name].stream(tool_use, {})`, before `stream_async`. Their fixed `toolUseId`s are `session-start___get_session_context` and `session-start___classify_call_type` ([session_context.py:52-85](../../../agent/ledgerlens/tools/session_context.py#L52-L85); [ledgerlens_agent.py:184](../../../agent/ledgerlens/ledgerlens_agent.py#L184), [:194](../../../agent/ledgerlens/ledgerlens_agent.py#L194)).
  - They are not added to `agent.messages` ([session_context.py:7-17](../../../agent/ledgerlens/tools/session_context.py#L7-L17); [tests/unit/test_session_context.py:160](../../../tests/unit/test_session_context.py#L160)).
  - The context is cached in `agent.state` and rendered into the system prompt ([session_context.py:88-104](../../../agent/ledgerlens/tools/session_context.py#L88-L104)).
  - If the fetch fails, nothing is cached ("will retry next turn"), and the prompt tells the model to call `get_session_context` itself ([session_context.py:82-84](../../../agent/ledgerlens/tools/session_context.py#L82-L84); [agent/ledgerlens/tools/system_prompt.py:37-40](../../../agent/ledgerlens/tools/system_prompt.py#L37-L40)).
- **How the frontend parses the stream.**
  - `confirmation` becomes `{type:"confirmation", id, tool, toolUseId, details}`; `data` becomes text; `current_tool_use` becomes `tool_use_start` on the first delta for a `toolUseId`, then `tool_use_delta` ([parsers/strands.ts:22-56](../../../frontend/src/lib/agentcore-client/parsers/strands.ts#L22-L56)). DeepSeek on Bedrock sends the whole input in one delta ([parsers/strands.ts:38-39](../../../frontend/src/lib/agentcore-client/parsers/strands.ts#L38-L39)).
  - `message` passes through, and a user message's `toolResult` texts are joined into a `tool_result` ([parsers/strands.ts:59-80](../../../frontend/src/lib/agentcore-client/parsers/strands.ts#L59-L80)). The raw `event` chunks, `tool_*_event` events and errors are ignored.
  - **Hand-off detection.** After the turn, `findHandOff` looks in the last assistant message for a completed tool segment whose bare name is `human_agent_hand_off`. Its result must parse, after the envelope unwrap, to an object with a string `hand_off_id` ([handoff.ts:57-73](../../../frontend/src/lib/handoff.ts#L57-L73); [ChatInterface.tsx:264-269](../../../frontend/src/components/chat/ChatInterface.tsx#L264-L269)).
- **What `LeakedMarkupFilter` removes.** It removes the DeepSeek V3.2 marker `<｜DSML｜function_calls` (and one trailing space) from `data` text ([agent/ledgerlens/tools/leaked_markup.py:3-17](../../../agent/ledgerlens/tools/leaked_markup.py#L3-L17), [:34-41](../../../agent/ledgerlens/tools/leaked_markup.py#L34-L41)).
  - **Split markers.** A chunk tail that could start the marker is held back. It is flushed as a bare `{"data": held}` just before the next `message` or `result` event ([leaked_markup.py:20-25](../../../agent/ledgerlens/tools/leaked_markup.py#L20-L25), [:42-45](../../../agent/ledgerlens/tools/leaked_markup.py#L42-L45)).
  - **Complete messages.** The text blocks of `message` events are cleaned too ([leaked_markup.py:49-60](../../../agent/ledgerlens/tools/leaked_markup.py#L49-L60)).
  - **Everything else is untouched:** raw `event` chunks, `current_tool_use` and the `result` string ([leaked_markup.py:46](../../../agent/ledgerlens/tools/leaked_markup.py#L46); `_clean_message` returns non-`message` events unchanged).
  - **Tests:** [tests/unit/test_leaked_markup.py:32-58](../../../tests/unit/test_leaked_markup.py#L32-L58).
- **A Cedar DENY, as the client sees it.**
  - On `tools/call`, the policy engine (mode `ENFORCE`, [infra-cdk/lambdas/cedar-policy/index.py:495-497](../../../infra-cdk/lambdas/cedar-policy/index.py#L495-L497)) evaluates `context.input`. A deny returns an "authorization error" to the agent ([docs/CEDAR_POLICY_GUIDE.md:95-106](../../../docs/CEDAR_POLICY_GUIDE.md#L95-L106), [:156-159](../../../docs/CEDAR_POLICY_GUIDE.md#L156-L159)).
  - Strands surfaces that error as a `toolResult` with `status:"error"` ([session_context.py:65-67](../../../agent/ledgerlens/tools/session_context.py#L65-L67) states "Strands returns a failed call (Lambda error, Cedar denial) as status error").
  - On `tools/list`, a denied tool is hidden from the agent ([CEDAR_POLICY_GUIDE.md:85-93](../../../docs/CEDAR_POLICY_GUIDE.md#L85-L93)).
  - `test-gateway.py` detects a refused call as a top-level JSON-RPC `"error"` or `result.isError` ([test-scripts/test-gateway.py:228-230](../../../test-scripts/test-gateway.py#L228-L230)).
- **A guardrail intervention, as the client sees it.**
  - The model runs with `guardrail_trace:"enabled"`, `guardrail_stream_processing_mode:"sync"`, `guardrail_latest_message:True`, `guardrail_redact_input:True` and `guardrail_redact_output:False` ([agent/ledgerlens/tools/guardrail.py:33-45](../../../agent/ledgerlens/tools/guardrail.py#L33-L45)).
  - When the trace shows a blocked policy, Strands emits a raw `{"redactContent": {"redactUserContentMessage": "[User input redacted.]"}}` chunk. It emits no output redaction, because output redaction is off ([strands/models/bedrock.py:678-731](file:///D:/Proyectos/ledgerlens-bank-assistant/.venv/Lib/site-packages/strands/models/bedrock.py)).
  - `"guardrail_intervened"` is a Strands stop reason ([strands/types/event_loop.py:43](file:///D:/Proyectos/ledgerlens-bank-assistant/.venv/Lib/site-packages/strands/types/event_loop.py), [:54](file:///D:/Proyectos/ledgerlens-bank-assistant/.venv/Lib/site-packages/strands/types/event_loop.py)).
  - The reply text is the guardrail's fixed three-language `BLOCKED_MESSAGE`, used for both input and output blocks ([infra-cdk/lib/utils/agent-guardrail.ts:6-12](../../../infra-cdk/lib/utils/agent-guardrail.ts#L6-L12), [:105-108](../../../infra-cdk/lib/utils/agent-guardrail.ts#L105-L108)). It begins "Solo puedo ayudarte con tus tarjetas de crédito…".
  - **What it covers.** Denied topics: SoftwareAndCoding, GeneralKnowledgeAndSchoolwork, EntertainmentAndLifestyle, PoliticsReligionLegalMedical ([agent-guardrail.ts:18-71](../../../infra-cdk/lib/utils/agent-guardrail.ts#L18-L71)). Content filters: HATE/INSULTS/SEXUAL/VIOLENCE HIGH, MISCONDUCT HIGH in and LOW out, PROMPT_ATTACK HIGH input only ([agent-guardrail.ts:73-82](../../../infra-cdk/lib/utils/agent-guardrail.ts#L73-L82)).

### Inferences
- **A grader's stream digest** needs about 30 lines:

  ```python
  def digest(events):
      out = {"text": [], "calls": [], "results": {}, "confirmations": [], "cancels": [],
             "stop_reasons": [], "usage": [], "guardrail": False, "throttled": 0, "errors": []}
      for e in events:
          if "confirmation" in e:                      out["confirmations"].append(e["confirmation"])
          elif isinstance(e.get("data"), str):         out["text"].append(e["data"])   # check before others: data events carry invocation_state
          elif "message" in e and isinstance(e["message"], dict):
              m = e["message"]
              for b in m.get("content", []):
                  if m.get("role") == "assistant" and "toolUse" in b:  out["calls"].append(b["toolUse"])
                  if m.get("role") == "user" and "toolResult" in b:     out["results"][b["toolResult"]["toolUseId"]] = b["toolResult"]
          elif "event" in e and isinstance(e["event"], dict):
              c = e["event"]
              if "messageStop" in c: out["stop_reasons"].append(c["messageStop"].get("stopReason"))
              if "metadata" in c:    out["usage"].append(c["metadata"].get("usage"))
              if "redactContent" in c: out["guardrail"] = True
          elif "tool_cancel_event" in e:               out["cancels"].append(e["tool_cancel_event"].get("message"))
          elif "event_loop_throttled_delay" in e:      out["throttled"] += 1
          elif e.get("status") == "error" or ("error" in e and "error_type" in e): out["errors"].append(e)
      return out

  def tool_body(tool_result):                          # same unwrap as session_context._body / handoff.parseHandOffResult
      t = "".join(c.get("text", "") for c in tool_result.get("content", []))
      try: v = json.loads(t)
      except ValueError: return {"_text": t}
      if isinstance(v, dict) and isinstance(v.get("content"), list) and v["content"]:
          v = json.loads(v["content"][0]["text"])
      return v
  ```

  Build the trajectory from `calls` (bare names via `rpartition("___")[2]`). Rebuild the reply from `data`, or from the last assistant `message` text blocks. Don't use raw `event` `contentBlockDelta` text: the markup filter never cleans it.
- **Grade a cross-customer attempt from the stream.** Compare `call["input"]["customer_id"]` with the persona's id. The hook silently corrects it before the Gateway, and the runtime log line `[CUSTOMER-ID] Replaced the model's customer_id on …` ([customer_id_hook.py:63-67](../../../agent/ledgerlens/tools/customer_id_hook.py#L63-L67)) is the only server-side trace.
- **Cedar DENYs can't happen through the agent today.** `CustomerIdHook` always overwrites `customer_id` (rule 2 can't fire). `ConfirmationHook` sets `customer_confirmed:true` on every approved block or claim and cancels the rest before the Gateway (rule 3 can't fire). An unlinked login gets its customer tools cancelled in the agent (rule 1 is only reached through `tools/list` filtering). So, through the agent, Cedar is defense in depth that a run should never trigger. A non-zero `DenyDecisions` metric during an agent run would itself be a finding. DENY behaviour is tested directly against the Gateway (§5).
- **The deployed prompt can be checked from the stream.** After the first tool call in a turn, `data` events carry `system_prompt`. A runner can assert `system_prompt.startswith(BASE_SYSTEM_PROMPT)` from the local `agent/ledgerlens/tools/system_prompt.py` ([system_prompt.py:22-168](../../../agent/ledgerlens/tools/system_prompt.py#L22-L168), [:197-230](../../../agent/ledgerlens/tools/system_prompt.py#L197-L230)). It can also read whether a `<session_context>` block was loaded. This would settle L1's open question (whether the deploy carries v10) without logs. It is an inference from the library code and the hand-off note, not observed. It stops working once the backend strips those keys, as the hand-off note plans.
- **Payload size.** A `data` event after a tool call serializes the whole message history and system prompt, so the stream gets large. Process it line by line, and store a compressed copy only for failure cards.
- **Detecting a guardrail block.** It is enough to see any of: a raw `event.messageStop.stopReason == "guardrail_intervened"`, a raw `event.redactContent`, or reply text equal to `BLOCKED_MESSAGE`.

### Gaps
- **The DENY text.** The exact JSON-RPC error and `toolResult` text the Gateway returns for a Cedar DENY isn't in the repo. Capture one with `test-gateway.py`, using a sub mapped to customer A and `--customer-id` of customer B.
- **The guardrail chunks.** Whether Bedrock streams the `BLOCKED_MESSAGE` as `contentBlockDelta` text, with `messageStop.stopReason = guardrail_intervened`, in sync mode with DeepSeek V3.2 was not observed.
- **Reasoning and structured content.** Whether DeepSeek V3.2 on Bedrock emits `reasoningContent` blocks, and whether the Gateway sets `structuredContent`, is unknown.

## 3. Confirmation interrupts: shape, answering Yes/No, typed "yes", gated tools, `customer_confirmed`

### Takeaway
Three tools pause behind a Strands interrupt: `block_credit_card`, `open_claim` and `human_agent_hand_off`.
- **What streams.** The turn emits one `{"confirmation": {"id", "tool", "toolUseId", "details"}}` per paused call, then ends.
- **How the runner answers.** It sends the next request on the same session, with a non-empty `prompt` and `"confirmations":[{"interruptId": id, "approved": true|false}]`.
- **Defaults.** A pending interrupt that isn't listed counts as No. A typed reply, even "sí", never approves: it cancels the call and reaches the model as text.
- **`customer_confirmed`.** Only the hook sets it to `true`, and only on a Yes.

### Cited Findings
- **Which tools are gated.**
  - `CONFIRM_TOOLS = {"block_credit_card", "open_claim", "human_agent_hand_off"}`. `CONFIRMED_FLAG_TOOLS = {"block_credit_card", "open_claim"}`. The interrupt name is `"confirm_" + tool` ([confirmation_hook.py:31-35](../../../agent/ledgerlens/tools/confirmation_hook.py#L31-L35)).
  - The hook matches on the bare name, and skips calls another hook already cancelled ([confirmation_hook.py:55-57](../../../agent/ledgerlens/tools/confirmation_hook.py#L55-L57)).
  - It runs after `CustomerIdHook` ([ledgerlens_agent.py:145-147](../../../agent/ledgerlens/ledgerlens_agent.py#L145-L147)).
- **The interrupt reason.** `{"tool": <bare>, "toolUseId": ..., "details": <input minus customer_id and customer_confirmed>}` ([confirmation_hook.py:58-65](../../../agent/ledgerlens/tools/confirmation_hook.py#L58-L65)).
  - The interrupt id is `v1:before_tool_call:<toolUseId>:<uuid5(OID, "confirm_<tool>")>` ([strands/hooks/events.py:161-170](file:///D:/Proyectos/ledgerlens-bank-assistant/.venv/Lib/site-packages/strands/hooks/events.py)). The team's note says to treat it as opaque ([confirmation-buttons-frontend.md:91](../../../docs/handoffs/2026-10-04-confirmation-buttons-frontend.md#L91)).
- **The stream event.** `confirmation_events` emits `{"confirmation": {"id": i.id, **i.reason}}` for each interrupt named `confirm_*`, when the raw `result.stop_reason == "interrupt"` ([confirmation_hook.py:108-117](../../../agent/ledgerlens/tools/confirmation_hook.py#L108-L117)). It is yielded just before the `result` event ([ledgerlens_agent.py:194-198](../../../agent/ledgerlens/ledgerlens_agent.py#L194-L198)).
  - The documented `details` per tool ([confirmation-buttons-frontend.md:46-57](../../../docs/handoffs/2026-10-04-confirmation-buttons-frontend.md#L46-L57)):

    | Tool | `details` keys |
    |---|---|
    | card block | `card_last4`, `reason` |
    | claim | `transaction_ids`, `claim_type`, `customer_statement` |
    | hand-off | `reason`, `priority`, `summary`, `related_ids` |
  - More than one confirmation per turn is possible but rare ([confirmation-buttons-frontend.md:56-57](../../../docs/handoffs/2026-10-04-confirmation-buttons-frontend.md#L56-L57)).
- **Answering on the next request.**
  - The entrypoint checks `agent._interrupt_state.activated`. If it is set, the prompt is replaced by `resume_prompt(pending_ids, payload)` ([ledgerlens_agent.py:186-191](../../../agent/ledgerlens/ledgerlens_agent.py#L186-L191)).
  - **A click:** with `confirmations` a list, each pending id gets `{"approved": answers.get(id, False)}`. Only `approved is True` approves ([confirmation_hook.py:92-99](../../../agent/ledgerlens/tools/confirmation_hook.py#L92-L99)).
  - **Typed text:** otherwise every pending id gets `{"approved": False, "text": prompt}` ([confirmation_hook.py:100-103](../../../agent/ledgerlens/tools/confirmation_hook.py#L100-L103)).
  - The frontend sends the button label as `prompt` with `confirmations:[{interruptId, approved}]` ([ChatInterface.tsx:176](../../../frontend/src/components/chat/ChatInterface.tsx#L176), [:475](../../../frontend/src/components/chat/ChatInterface.tsx#L475)). The documented body is `{"prompt":"Sí","runtimeSessionId":"...","confirmations":[{"interruptId":"<id>","approved":true}]}` ([confirmation-buttons-frontend.md:59-74](../../../docs/handoffs/2026-10-04-confirmation-buttons-frontend.md#L59-L74)).
- **Yes.** The hook logs `[CONFIRM] Customer approved <tool>` and, for block and claim, sets `customer_confirmed: True` on the executed input ([confirmation_hook.py:66-70](../../../agent/ledgerlens/tools/confirmation_hook.py#L66-L70)). Strands resumes the saved tool call without calling the model first ([confirmation_hook.py:10-12](../../../agent/ledgerlens/tools/confirmation_hook.py#L10-L12), [:18-21](../../../agent/ledgerlens/tools/confirmation_hook.py#L18-L21)).
  - The resumed stream has **no new `current_tool_use`** for that tool. Only the user `message` with the `toolResult` for the original `toolUseId` arrives, then the model's text ([confirmation-buttons-frontend.md:76-81](../../../docs/handoffs/2026-10-04-confirmation-buttons-frontend.md#L76-L81)).
  - The frontend creates the tool segment itself from the confirmation ([ChatInterface.tsx:135-146](../../../frontend/src/components/chat/ChatInterface.tsx#L135-L146)).
- **No.** The call is cancelled with `"Not done: the customer chose No. Don't call this tool again unless they ask for it."` ([confirmation_hook.py:37-39](../../../agent/ledgerlens/tools/confirmation_hook.py#L37-L39), [:71-77](../../../agent/ledgerlens/tools/confirmation_hook.py#L71-L77)).
  - Strands streams `tool_cancel_event`, then a `toolResult` with `status:"error"` and that text ([strands/tools/executors/_executor.py:161-178](file:///D:/Proyectos/ledgerlens-bank-assistant/.venv/Lib/site-packages/strands/tools/executors/_executor.py)).
- **A typed reply.** The call is cancelled with `'Not done: the customer wrote instead of tapping Yes or No: "<text, max 300 chars>". Answer that. If they still want this, call the tool again so the buttons show again.'` ([confirmation_hook.py:40-43](../../../agent/ledgerlens/tools/confirmation_hook.py#L40-L43), [:72-77](../../../agent/ledgerlens/tools/confirmation_hook.py#L72-L77)).
  - If the model calls again, a new confirmation arrives with a new `toolUseId`, so a new id ([confirmation-buttons-frontend.md:72-74](../../../docs/handoffs/2026-10-04-confirmation-buttons-frontend.md#L72-L74)).
  - **Stale clicks.** A `confirmations` field when nothing is pending is ignored, and `prompt` is handled as normal text ([confirmation-buttons-frontend.md:85-87](../../../docs/handoffs/2026-10-04-confirmation-buttons-frontend.md#L85-L87)).
  - **Persistence.** The pending pause survives with the session; a new `runtimeSessionId` starts clean ([confirmation-buttons-frontend.md:88-90](../../../docs/handoffs/2026-10-04-confirmation-buttons-frontend.md#L88-L90)).
- **Cedar's backstop.** Cedar forbids `block_credit_card` and `open_claim` unless `context.input has customer_confirmed && == true` ([gateway/policies/policy.cedar:76-91](../../../gateway/policies/policy.cedar#L76-L91)). Both Lambdas also validate it (`_require_confirmation`, [gateway/tools/block_credit_card/block_credit_card_lambda/application/use_cases/block_credit_card.py:89](../../../gateway/tools/block_credit_card/block_credit_card_lambda/application/use_cases/block_credit_card.py#L89); [gateway/tools/open_claim/open_claim_lambda/application/use_cases/open_claim.py:119](../../../gateway/tools/open_claim/open_claim_lambda/application/use_cases/open_claim.py#L119)).
- **The prompt never asks in text.** It tells the model to call the gated tools without asking first, with `customer_confirmed` true, and with no question in that turn ([system_prompt.py:83-85](../../../agent/ledgerlens/tools/system_prompt.py#L83-L85), [:92-94](../../../agent/ledgerlens/tools/system_prompt.py#L92-L94), [:106-110](../../../agent/ledgerlens/tools/system_prompt.py#L106-L110)).
- **Verified end to end by the team (9 scenarios).** Pause; Yes on a fresh agent instance; No; typed "sí, ábrelo"; a typed question; a stale click; a plain prompt while paused (the entrypoint converts Strands' `TypeError`); ungated tools; already-cancelled calls ([confirmation-buttons-frontend.md:97-109](../../../docs/handoffs/2026-10-04-confirmation-buttons-frontend.md#L97-L109)).
- **Unit tests:** [tests/unit/test_confirmation_hook.py:65-160](../../../tests/unit/test_confirmation_hook.py#L65-L160).

### Inferences
- **Script Yes or No per case.** Give each case a confirmation policy, for example `{"block_credit_card": True, "open_claim": True, "human_agent_hand_off": False}`, or an ordered list of answers. After each turn, loop:

  ```python
  while d["confirmations"]:
      ans = [{"interruptId": c["id"], "approved": policy[c["tool"]]} for c in d["confirmations"]]
      pending = {c["toolUseId"]: c for c in d["confirmations"]}       # resumed results arrive without a toolUse
      d = digest(turn(tok, sid, "Sí" if all(a["approved"] for a in ans) else "No", ans))
  ```

  The `prompt` on a click is never seen by the model, because `resume_prompt` drops it. It only has to be non-empty.
- **Join a resumed result to its call.** In the resume turn, join a `toolResult` to the earlier confirmation by `toolUseId`. The bare tool name comes from `confirmation.tool`; the executed input is `details`, plus the token's `customer_id`, plus `customer_confirmed:true` for block and claim.
- **Invariants a deterministic grader can check:**
  - no success `toolResult` for a gated tool except in a turn that resumed with `approved:true` for that `toolUseId`;
  - a typed "yes" case never produces a gated `toolResult` in that turn;
  - after a No, the model doesn't call the same tool again unless the next user message asks for it.
- **The resume turn has no user message.** The `prompt` of a resume request is not added as a user message: approvals carry no text, and a typed reply reaches the model only inside the cancelled call's `toolResult`. Transcripts should label resume turns as button events, not user utterances.

### Gaps
- The repo doesn't show the runtime behaviour when two gated calls pause in one turn and the runner answers only one; per the code, the other is a No. The team's 9-scenario script that verified the flow isn't in the repo.

## 4. Session context and memory: does each new `runtimeSessionId` start clean, and what persists across sessions?

### Takeaway
Yes: a new `runtimeSessionId` starts with no conversation, no cached session context and no pending interrupt. Long-term memory retrieval is off.

What does persist across sessions, and contaminates repeated trials, is the shared Aurora DSQL data that the two write tools change. A blocked card stays blocked, and an opened claim becomes an `open_cases` entry. Both change the next session's opening and the correct answer. Hand-offs store nothing.

### Cited Findings
- **Memory is keyed per session.** `AgentCoreMemoryConfig(memory_id, session_id=<payload runtimeSessionId>, actor_id=<JWT sub>, retrieval_config=None unless USE_LONG_TERM_MEMORY=true)` ([ledgerlens_agent.py:54-86](../../../agent/ledgerlens/ledgerlens_agent.py#L54-L86)). Memory is tied to the client's `runtimeSessionId` ([agent/ledgerlens/README.md:67-71](../../../agent/ledgerlens/README.md#L67-L71)).
- **Long-term memory is off.** `use_long_term_memory: false` ([infra-cdk/config.yaml:17-23](../../../infra-cdk/config.yaml#L17-L23)), passed as `USE_LONG_TERM_MEMORY` ([backend-construct.ts:408-415](../../../infra-cdk/lib/backend-construct.ts#L408-L415)).
  - The Memory resource still defines a `FactExtractor` semantic strategy on `/facts/{actorId}`, with 30-day event expiry. Retrieval only happens when the flag is true ([backend-construct.ts:250-262](../../../infra-cdk/lib/backend-construct.ts#L250-L262), [:408-411](../../../infra-cdk/lib/backend-construct.ts#L408-L411)).
- **What the session restores.** The session manager restores `agent.state`; the session context is cached there under `session_context` and re-rendered into the system prompt each turn ([session_context.py:7-17](../../../agent/ledgerlens/tools/session_context.py#L7-L17), [:88-104](../../../agent/ledgerlens/tools/session_context.py#L88-L104)). The interrupt state is saved with the session ([confirmation_hook.py:18-21](../../../agent/ledgerlens/tools/confirmation_hook.py#L18-L21)).
- **Short-term window.** `STM_WINDOW_SIZE` defaults to 30 messages, as a sliding window. Summarization is off ([agent/ledgerlens/tools/conversation_memory.py:95-103](../../../agent/ledgerlens/tools/conversation_memory.py#L95-L103); [config.yaml:30-35](../../../infra-cdk/config.yaml#L30-L35); [backend-construct.ts:421-427](../../../infra-cdk/lib/backend-construct.ts#L421-L427)). The config says one tool-using question is about 4–6 messages ([config.yaml:31](../../../infra-cdk/config.yaml#L31)).
- **A guardrail-blocked customer message is replaced in memory**, so the next turn doesn't resend it ([guardrail.py:41-42](../../../agent/ledgerlens/tools/guardrail.py#L41-L42)).
- **What the write tools change.**
  - **`block_credit_card`** runs `UPDATE products SET product_status='Blocked', last_updated=… WHERE product_id=… AND customer_id=… AND product_status NOT IN ('Blocked','Closed')`. A second run touches nothing and returns `already_blocked: true` ([gateway/tools/block_credit_card/block_credit_card_lambda/queries/postgresql/block_credit_card.sql:10-21](../../../gateway/tools/block_credit_card/block_credit_card_lambda/queries/postgresql/block_credit_card.sql#L10-L21); [presenters/card_block.py:8-18](../../../gateway/tools/block_credit_card/block_credit_card_lambda/delivery/presenters/card_block.py#L8-L18)).
  - **`open_claim`** inserts into `complaints` with status `Open`. The id is `CMP-` plus a hash of (customer, claim_type, product, currency, sorted transaction ids), not of the statement. A repeat hits a duplicate key and returns `already_existed: true` ([gateway/tools/open_claim/open_claim_lambda/queries/postgresql/insert_claim.sql:17-33](../../../gateway/tools/open_claim/open_claim_lambda/queries/postgresql/insert_claim.sql#L17-L33); [open_claim.py:147-184](../../../gateway/tools/open_claim/open_claim_lambda/application/use_cases/open_claim.py#L147-L184), [:219-241](../../../gateway/tools/open_claim/open_claim_lambda/application/use_cases/open_claim.py#L219-L241)).
- **No reset exists.** The write-tools spec says "No reset stage. Writes stay until the next full load" ([docs/superpowers/specs/2026-10-03-write-tools-design.md:40](../../../docs/superpowers/specs/2026-10-03-write-tools-design.md#L40)). `ll_write` has SELECT on three tables, UPDATE on `products` and INSERT on `complaints`, and no DELETE ([write-tools-design.md:420-423](../../../docs/superpowers/specs/2026-10-03-write-tools-design.md#L420-L423)).
- **Writes feed the next session.**
  - The session context includes `cards` (with `product_status`) and `open_cases` ([gateway/tools/get_session_context/get_session_context_lambda/delivery/presenters/session_context.py:32-39](../../../gateway/tools/get_session_context/get_session_context_lambda/delivery/presenters/session_context.py#L32-L39)).
  - `classify_call_type` ranks `OPEN_CASE_FOLLOWUP` and `CARD_NOT_ACTIVE` ([gateway/tools/classify_call_type/classify_call_type_lambda/domain/value_objects/call_reasons.py:19-29](../../../gateway/tools/classify_call_type/classify_call_type_lambda/domain/value_objects/call_reasons.py#L19-L29)).
  - The prompt changes behaviour when a case already covers the charges ([system_prompt.py:49-52](../../../agent/ledgerlens/tools/system_prompt.py#L49-L52), [:99-100](../../../agent/ledgerlens/tools/system_prompt.py#L99-L100), [:121-122](../../../agent/ledgerlens/tools/system_prompt.py#L121-L122)).
- **Hand-offs store nothing.** The id is `HO-` plus 8 base32 characters of a SHA-256 over customer, priority, reason, summary and sorted related ids ([gateway/tools/human_agent_hand_off/human_agent_hand_off_lambda/application/use_cases/hand_off.py:27-84](../../../gateway/tools/human_agent_hand_off/human_agent_hand_off_lambda/application/use_cases/hand_off.py#L27-L84)). The Lambda calls no AWS service ([backend-construct.ts:872-873](../../../infra-cdk/lib/backend-construct.ts#L872-L873)).
- **The tools' clock is fixed.** "Today" is `data.as_of: "2026-06-17T23:59:59"`, passed to the DSQL tools as `AS_OF` ([config.yaml:68-71](../../../infra-cdk/config.yaml#L68-L71); [backend-construct.ts:910](../../../infra-cdk/lib/backend-construct.ts#L910)). The write tools stamp that clock as "now" ([block_credit_card handler.py:15-18](../../../gateway/tools/block_credit_card/block_credit_card_lambda/delivery/handler.py#L15-L18); [insert_claim.sql:7](../../../gateway/tools/open_claim/open_claim_lambda/queries/postgresql/insert_claim.sql#L7)).
- **The README agrees.** Start a new chat after every persona switch, because the old chat's memory holds the previous persona's data ([README.md:171](../../../README.md#L171)).

### Inferences
- **Read-only cases are safe for pass^3.** Every trial uses a new session id, LTM retrieval is off, the tool clock is fixed and hand-offs store nothing. The only variance is the model's (temperature 0.1, [ledgerlens_agent.py:108-112](../../../agent/ledgerlens/ledgerlens_agent.py#L108-L112)).
- **Write cases are not.** Trial 2 of a block or claim case sees `already_blocked` or `already_existed`, and possibly a new `open_cases` entry in the opening. This is L5.
- **Isolating write cases needs two things:**
  - a per-trial restore run with a role that can UPDATE `products` back and DELETE the `CMP-…` rows, which `ll_write` cannot do;
  - or `EVL-` clones (L10).

  Neither exists. Building and testing either by 2026-10-05 is a risk. Practical cut: run write cases once per persona (pass^1) or answer No on the write confirmations (which still tests the protocol up to the button), and keep pass^3 for read-only and No-path cases.
- **The demo personas change state too.** P07's card 4497 would stay Blocked after a Yes trial, which changes the judges' demo ([data_load/personas.json:41-46](../../../data_load/personas.json#L41-L46)).
- **Fact extraction mixes personas under one login.** It runs on the Memory resource (strategy defined) even with retrieval off. If several personas share one Cognito user, their facts mix under one `/facts/{actorId}`. This matters only if LTM retrieval is ever turned on.

### Gaps
- **Fact extraction.** Whether AgentCore Memory actually extracts facts when the agent never asks for retrieval (cost only, no contamination) wasn't checked.
- **Current data state.** Whether earlier demo or eval sessions already blocked P07's card or opened claims in DSQL is unknown. The live data was not read.

## 5. Persona switching and cheaper tool-level paths

### Takeaway
The deployed agent's customer comes only from the pre-token Lambda's `USER_CUSTOMER_IDS_MAP` (Cognito `sub` → `customer_id`), read fresh on every agent request. There are four ways to test personas:

| Path | Parallel personas? | Cost | Coverage | Needs (AWS creds) |
|---|---|---|---|---|
| (a) Edit the map for the single demo login | No | Seconds per switch | Full agent | `lambda:UpdateFunctionConfiguration`; disturbs the judges' login |
| (b) One Cognito user per persona, multi-entry map | Yes | One-time setup | Full agent | Cognito admin + Lambda config |
| (c) Gateway directly with a machine token (`test-gateway.py`) | Yes, any sub in the map, no Cognito user needed | No model, cheap, deterministic | Real Gateway + Cedar | SSM + machine client secret |
| (d) Invoke tool Lambdas directly | Yes | No model, cheapest | Lambda only; bypasses Gateway and Cedar | `lambda:InvokeFunction` |

### Cited Findings
- **How the map is read.** The pre-token V3 Lambda handles only `TokenGeneration_ClientCredentials` ([infra-cdk/lambdas/pretoken-v3/index.py:117-120](../../../infra-cdk/lambdas/pretoken-v3/index.py#L117-L120)).
  - It reads `clientMetadata.verified_user_id` ([index.py:124-129](../../../infra-cdk/lambdas/pretoken-v3/index.py#L124-L129)) and looks it up in the JSON env var `USER_CUSTOMER_IDS_MAP`. The map may hold many entries ([index.py:67-101](../../../infra-cdk/lambdas/pretoken-v3/index.py#L67-L101)).
  - It injects `customer_id` (blank when unmapped) into the machine token ([index.py:142-163](../../../infra-cdk/lambdas/pretoken-v3/index.py#L142-L163)).
- **Where the sub comes from.** The agent sends the validated JWT `sub` as `aws_client_metadata.verified_user_id` on every token request ([agent/utils/auth.py:223-232](../../../agent/utils/auth.py#L223-L232); [ledgerlens_agent.py:176-180](../../../agent/ledgerlens/ledgerlens_agent.py#L176-L180)). It reads `customer_id` back from that token ([agent/utils/auth.py:90-125](../../../agent/utils/auth.py#L90-L125)).
- **The committed map.** It has one entry: the demo login → P03 `CLI-70U0WJ1NH1MN`. "A redeploy resets it here" ([infra-cdk/lib/cognito-construct.ts:142-147](../../../infra-cdk/lib/cognito-construct.ts#L142-L147)). The function is `ledgerlens-bank-assistant-pretoken-v3` ([cognito-construct.ts:135-136](../../../infra-cdk/lib/cognito-construct.ts#L135-L136)).
- **README "Switch persona".**
  - Edit the map in the console, or run `aws lambda update-function-configuration ... USER_CUSTOMER_IDS_MAP=json.dumps({SUB: customer_id})` and then `aws lambda wait function-updated` ([README.md:159-169](../../../README.md#L159-L169)).
  - Rules: start a new chat after every switch; only someone with AWS credentials can switch; a redeploy resets the map ([README.md:171-173](../../../README.md#L171-L173)).
  - Creating the demo user takes `admin-create-user`, `admin-set-user-password --permanent` and `admin-get-user` (for the sub) ([README.md:146-157](../../../README.md#L146-L157)).
- **Persona ids.** P01–P10 and their customer ids are in [README.md:175-186](../../../README.md#L175-L186). Use case, expected outcome and evidence ids are in [data_load/personas.json](../../../data_load/personas.json) (keys `as_of`, `spec`, `personas`, `alternates`).
  - The README's "v1 note" column is stale for P07 and P08: it says no block and no hand-off tool. The write and hand-off tools are deployed targets now ([backend-construct.ts:888-890](../../../infra-cdk/lib/backend-construct.ts#L888-L890)).
- **Path (c), the Gateway directly.** `test-scripts/test-gateway.py`:
  1. Reads `gateway_url`, `machine_client_id` and `cognito_provider` from SSM, and `/<stack>/machine_client_secret` from Secrets Manager ([test-gateway.py:189-196](../../../test-scripts/test-gateway.py#L189-L196)).
  2. Mints a client-credentials token with `aws_client_metadata={"verified_user_id": <sub>}` ([test-gateway.py:80-111](../../../test-scripts/test-gateway.py#L80-L111)).
  3. POSTs JSON-RPC `tools/list` and `tools/call` with `params.name = "<target>___<tool>"`, no `gateway_` prefix ([test-gateway.py:114-158](../../../test-scripts/test-gateway.py#L114-L158), [:218-226](../../../test-scripts/test-gateway.py#L218-L226)).

  A sub that isn't in the map tests an unlinked login ([test-gateway.py:13-17](../../../test-scripts/test-gateway.py#L13-L17); [README.md:188-190](../../../README.md#L188-L190)).
- **The Gateway's auth.** Its authorizer accepts only the machine client ([backend-construct.ts:860-863](../../../infra-cdk/lib/backend-construct.ts#L860-L863)), and Cedar runs in `ENFORCE` mode ([cedar-policy/index.py:495-497](../../../infra-cdk/lambdas/cedar-policy/index.py#L495-L497)).
- **Path (d), Lambdas directly** (curate spec §13.1). It is a read-only smoke test "invoked the way the Gateway calls the tools: tool name in `client_context.custom.bedrockAgentCoreToolName`". It ran on `ledgerlens-get-session-context` (P01) and `ledgerlens-list-credit-cards` (P10) ([docs/superpowers/specs/2026-10-03-curate-stage-design.md:332-334](../../../docs/superpowers/specs/2026-10-03-curate-stage-design.md#L332-L334)).
  - Function names are `ledgerlens-<slug>` ([backend-construct.ts:892-894](../../../infra-cdk/lib/backend-construct.ts#L892-L894)).
  - Each handler checks only the part after `___` of `client_context.custom["bedrockAgentCoreToolName"]`, and takes the tool arguments as the event ([block_credit_card handler.py:5-9](../../../gateway/tools/block_credit_card/block_credit_card_lambda/delivery/handler.py#L5-L9), [:68-73](../../../gateway/tools/block_credit_card/block_credit_card_lambda/delivery/handler.py#L68-L73), [:104-112](../../../gateway/tools/block_credit_card/block_credit_card_lambda/delivery/handler.py#L104-L112)).
  - A wrong name returns `{"error": "This function only serves the '<tool>' tool…"}` ([handler.py:48-51](../../../gateway/tools/block_credit_card/block_credit_card_lambda/delivery/handler.py#L48-L51)).

### Inferences
- **(a) is the existing method but serial.** One persona's trials can still run in parallel under the same login: separate session ids, same mapped customer. Different personas cannot overlap. Each switch takes effect on the next agent request, because every request fetches a new machine token, after `function-updated`. All open sessions must end before a switch, because a session keeps its cached session context of the old persona in `agent.state` while the token switches to the new customer. Restore P03 at the end.
- **(b) is the best fit for one day.** Create, for example, `eval-p01@ledgerlens.example` … `eval-p10@…` with `admin-create-user` and `admin-set-user-password --permanent`. Read each sub and write one map with all 10 entries plus the demo login's.
  - README's `set_persona` overwrites the map with a single entry, so merge instead.
  - The env var is the function's only one ([cognito-construct.ts:142-147](../../../infra-cdk/lib/cognito-construct.ts#L142-L147)), so replacing `Variables` is safe.
  - A `cdk deploy` would wipe the extra entries unless they are committed.
  - IAM needed: `cognito-idp:AdminCreateUser`, `AdminSetUserPassword`, `AdminGetUser`, `lambda:GetFunctionConfiguration` and `lambda:UpdateFunctionConfiguration` (AWS profile `ledgerlens`, [README.md:134](../../../README.md#L134), [:147](../../../README.md#L147)).
- **(c) makes Cedar DENY tests deterministic.** The sub is just a metadata string, so a runner can add synthetic keys such as `"eval-cedar-A": "CLI-…"` to the map with no Cognito user. It needs `ssm:GetParameter` and `secretsmanager:GetSecretValue` on the machine client secret. Example cases, none of which the agent can trigger (§2):

  | Case | Expected result |
  |---|---|
  | Persona A's token, call with B's `customer_id` | DENY (rule 2) |
  | `block_credit_card` without `customer_confirmed` | DENY (rule 3) |
  | `block_credit_card` with `customer_confirmed: false` | DENY (rule 3) |
  | Unmapped sub on `tools/list` | empty list (rule 1) |
  | Persona's own id | ALLOW |

  These DENYs also show up in the `DenyDecisions` metric (§7). Never send a confirmed write this way to a demo persona.
- **(d) is the cheapest regression test of tool contracts.** It runs against the personas' records with no model and no Cedar. It is best for read tools and the hand-off. Write tools invoked this way still change DSQL, and the Lambda also requires `customer_confirmed: true`.

### Gaps
- **How fast a map change applies** to a warm pre-token container isn't documented in the repo. `wait function-updated` is the README's guard.
- **Map size.** The Lambda environment size limit for a large map (an AWS limit) wasn't checked. 10–20 entries are tiny.
- **Concurrent sessions per login.** Whether one Cognito user may hold many concurrent runtime sessions without throttling isn't stated in the repo.

## 6. Tool contracts: inputs, outputs, side effects, grader fields

### Takeaway
All nine tools require `customer_id`. The hook overwrites it from the token, so it is never a grader concern through the agent. The write and hand-off tools return machine-checkable ids and flags (`already_blocked`, `claims[].claim_id` / `already_existed`, `hand_off_id` / `reason` / `priority` / `related_ids`). The read tools return structured JSON that a grader can compare with the persona's records.

### Cited Findings

| Tool (Cedar action) | Required inputs → optional | Output (presenter) | Side effects | Fields a grader can check |
|---|---|---|---|---|
| `list_credit_cards` (`list-credit-cards-target___list_credit_cards`) | `customer_id` ([tool_spec.json:13](../../../gateway/tools/list_credit_cards/tool_spec.json#L13)) | `{"cards":[{card_last4, product_status, currency, current_balance, credit_limit, available_credit, expiration_date, days_past_due}] or null, "count", "truncated"}` ([presenters/credit_cards.py:14-41](../../../gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/presenters/credit_cards.py#L14-L41)) | none | status read-back (P10 Blocked), which card (P04) |
| `list_card_transactions` | `customer_id` → `card_last4, date_from, date_to (≤180 d), merchant, min_amount, max_amount, status∈{Approved,Declined,Pending,Reversed}` ([tool_spec.json:1-47](../../../gateway/tools/list_card_transactions/tool_spec.json)) | `{"transactions":[{transaction_id, transaction_date, card_last4, merchant_name, merchant_category, amount, currency, channel, transaction_city, transaction_country, transaction_status, …}], "count", "truncated"}`, at most 25 rows ([presenters/card_transactions.py:14-40](../../../gateway/tools/list_card_transactions/list_card_transactions_lambda/delivery/presenters/card_transactions.py#L14-L40)) | none | evidence `TRX-` id present; at most 5 rows shown |
| `get_session_context` | `customer_id` ([tool_spec.json:13](../../../gateway/tools/get_session_context/tool_spec.json#L13)) | `{as_of, customer{customer_id, first_name, country, city, customer_status}, cards, recent_transactions[{…, flags}], digital_signals, open_cases[{complaint_id, …}], truncated, unavailable}` ([presenters/session_context.py:22-108](../../../gateway/tools/get_session_context/get_session_context_lambda/delivery/presenters/session_context.py#L22-L108)) | none | normally runs at session start, outside the stream (§2) |
| `classify_call_type` | `customer_id` ([tool_spec.json:10](../../../gateway/tools/classify_call_type/tool_spec.json#L10)) | `{"reasons":[{reason, confidence, ref_id, evidence}], "unavailable"}`. Reasons: FRAUD_SUSPECTED, DECLINED_TRANSACTION, UNRECOGNIZED_CHARGE_REVIEW, OPEN_CASE_FOLLOWUP, PENDING_TRANSACTION, REVERSED_TRANSACTION, CARD_NOT_ACTIVE, FAILED_APP_ACTION, FOREIGN_TRANSACTION, PAYMENT_OVERDUE, CARD_EXPIRING ([presenters/call_classification.py:33-55](../../../gateway/tools/classify_call_type/classify_call_type_lambda/delivery/presenters/call_classification.py#L33-L55); [call_reasons.py:19-29](../../../gateway/tools/classify_call_type/classify_call_type_lambda/domain/value_objects/call_reasons.py#L19-L29)) | none | opening grounded in `reasons[0].evidence` |
| `transaction_fraud_detection` (`fraud-detection-target___transaction_fraud_detection`) | `customer_id` → exactly one of `transaction_id`, `card_last4` ([tool_spec.json:1-15](../../../gateway/tools/transaction_fraud_detection/tool_spec.json)) | `{"mode":"transaction","assessment":{…}}` or `{"mode":"card", card_last4, date_from, date_to, checked, flagged[…], truncated}`. Each assessment has `verdict` ∈ {fraud, review, no_fraud}, `basis` and `next_step` ([presenters/fraud_assessment.py:18-52](../../../gateway/tools/transaction_fraud_detection/transaction_fraud_detection_lambda/delivery/presenters/fraud_assessment.py#L18-L52); [fraud_bands.py:19-28](../../../gateway/tools/transaction_fraud_detection/transaction_fraud_detection_lambda/domain/value_objects/fraud_bands.py#L19-L28), [:38-46](../../../gateway/tools/transaction_fraud_detection/transaction_fraud_detection_lambda/domain/value_objects/fraud_bands.py#L38-L46)) | none | the verdict must not be mentioned ([system_prompt.py:80-81](../../../agent/ledgerlens/tools/system_prompt.py#L80-L81), [:151-152](../../../agent/ledgerlens/tools/system_prompt.py#L151-L152)) |
| `explain_transaction` | `customer_id, transaction_id` ([tool_spec.json:11](../../../gateway/tools/explain_transaction/tool_spec.json#L11)) | `{transaction{…}, fx{card_currency, rate_date, rate, amount_in_card_currency} or null, decline{response_code, meaning, contradicts_card_state} or null, habit{…}, app_activity{found, …}, unavailable}` ([presenters/transaction_explanation.py:20-114](../../../gateway/tools/explain_transaction/explain_transaction_lambda/delivery/presenters/transaction_explanation.py#L20-L114)) | none | P09 `contradicts_card_state`; P01 decline meaning; P05 fx |
| `block_credit_card` | `customer_id, card_last4, reason∈{suspected_fraud, lost, stolen, customer_request}, customer_confirmed` ([tool_spec.json:1-28](../../../gateway/tools/block_credit_card/tool_spec.json)) | `{card_last4, status, already_blocked}` ([presenters/card_block.py:8-18](../../../gateway/tools/block_credit_card/block_credit_card_lambda/delivery/presenters/card_block.py#L8-L18)) | **UPDATE `products`** as `ll_write` (idempotent; [block_credit_card.sql:15-21](../../../gateway/tools/block_credit_card/block_credit_card_lambda/queries/postgresql/block_credit_card.sql#L15-L21)) | `card_last4` == the persona's card; `already_blocked`; the read-back in text |
| `open_claim` | `customer_id, transaction_ids[1..10], claim_type∈{fraud, dispute}, customer_statement (≤500), customer_confirmed` ([tool_spec.json:1-36](../../../gateway/tools/open_claim/tool_spec.json)) | `{"claims":[{claim_id "CMP-…", card_last4, transaction_ids, claimed_amount, currency, priority, status, already_existed}], "resolution_estimate": {median_days, p90_days} or null}`, one claim per card and currency ([presenters/claims.py:11-42](../../../gateway/tools/open_claim/open_claim_lambda/delivery/presenters/claims.py#L11-L42)) | **INSERT `complaints`** (idempotent by content hash; [insert_claim.sql:24-33](../../../gateway/tools/open_claim/open_claim_lambda/queries/postgresql/insert_claim.sql#L24-L33)) | `transaction_ids` ⊆ the charges the customer disowned; claim id said in text; `median_days` quoted |
| `human_agent_hand_off` | `customer_id, priority∈{high, normal}, reason∈{FRAUD_CONFIRMED, CUSTOMER_REQUEST, UNRESOLVED, OUT_OF_SCOPE}, summary (1–2000)` → `related_ids` (≤20, `[A-Z0-9-]{1,40}`) ([tool_spec.json:1-34](../../../gateway/tools/human_agent_hand_off/tool_spec.json); [hand_off.py:14-20](../../../gateway/tools/human_agent_hand_off/human_agent_hand_off_lambda/application/use_cases/hand_off.py#L14-L20)) | `{hand_off_id "HO-XXXXXXXX", status:"queued", priority, reason, customer_id, summary, related_ids}` ([presenters/hand_off.py:8-23](../../../gateway/tools/human_agent_hand_off/human_agent_hand_off_lambda/delivery/presenters/hand_off.py)) | none (no DB, no AWS call) | `reason`/`priority` per the prompt rules ([system_prompt.py:112-125](../../../agent/ledgerlens/tools/system_prompt.py#L112-L125)); `related_ids` contain the evidence ids; no question in the hand-off turn |

- **Failure shape.** Every handler returns `{"error": <agent-facing message>}` on a domain or unexpected error, never raw exception text ([block_credit_card handler.py:11-13](../../../gateway/tools/block_credit_card/block_credit_card_lambda/delivery/handler.py#L11-L13), [:86-93](../../../gateway/tools/block_credit_card/block_credit_card_lambda/delivery/handler.py#L86-L93)).
- **Timeouts.** DSQL tools time out at 30 s and the hand-off at 10 s ([backend-construct.ts:903](../../../infra-cdk/lib/backend-construct.ts#L903)).
- **The descriptions the model reads** come from each `tool_spec.json` through `ToolSchema.fromLocalAsset` ([backend-construct.ts:922-924](../../../infra-cdk/lib/backend-construct.ts#L922-L924)).

### Inferences
- **`hand_off_id` isn't stable across trials.** It hashes the model-written summary, so grade `reason`, `priority`, `related_ids` and the summary's content instead.
- **`claim_id` is stable per transaction set**, so it is a good join key with the `open_claim` Lambda log (§7) and across trials.
- **Grading P07** (expected "exit 2 then 3: confirm, block card 4497, read back, dispute intake", [data_load/personas.json:41-46](../../../data_load/personas.json#L41-L46)):
  1. confirmation `block_credit_card` with `details.card_last4 == "4497"` and `reason ∈ {suspected_fraud, lost, stolen}`;
  2. on Yes, a `toolResult` with `card_last4: "4497"`, plus "4497" in the reply;
  3. then `list_card_transactions` for that card.

### Gaps
- The exact `{"error"}` messages per failure aren't listed here. They are in each tool's `domain/errors.py`, and only matter for fault-injection cases.

## 7. Logs and metrics available without Transaction Search

### Takeaway
Without spans, a grader has four sources:
- the stream (primary, §2);
- the runtime log group, where `[PROMPT] version=<v> session=<sid>` is the one line that names the session;
- the nine tool Lambda log groups, which log ids and flags but no session id;
- the default `AWS/Bedrock-AgentCore` policy metrics `AllowDecisions` and `DenyDecisions` (aggregate only).

All of them can be queried with CloudWatch Logs Insights / `GetMetricData` without Transaction Search.

### Cited Findings
- **Agent log lines.**

  | Line | Source |
  |---|---|
  | `[PROMPT] version=%s session=%s` (once per request) | [ledgerlens_agent.py:181](../../../agent/ledgerlens/ledgerlens_agent.py#L181) |
  | `[CONFIRM] Customer approved %s` / `declined %s` | [confirmation_hook.py:67](../../../agent/ledgerlens/tools/confirmation_hook.py#L67), [:71](../../../agent/ledgerlens/tools/confirmation_hook.py#L71) |
  | `[CUSTOMER-ID] Replaced the model's customer_id on %s` / `No linked customer - cancelling %s` | [customer_id_hook.py:56](../../../agent/ledgerlens/tools/customer_id_hook.py#L56), [:65-67](../../../agent/ledgerlens/tools/customer_id_hook.py#L65-L67) |
  | `[SESSION-START] Bootstrap failed; will retry next turn` | [session_context.py:83](../../../agent/ledgerlens/tools/session_context.py#L83) |
  | `Agent run failed` (exception) | [ledgerlens_agent.py:201](../../../agent/ledgerlens/ledgerlens_agent.py#L201) |
  | `Extracted user_id from JWT: %s` | [agent/utils/auth.py:86](../../../agent/utils/auth.py#L86) |
  | `customer_id claim found …` / `No customer_id claim …` | [auth.py:121-124](../../../agent/utils/auth.py#L121-L124) |
  | `[GATEWAY] URL: %s` | [gateway.py:66](../../../agent/ledgerlens/tools/gateway.py#L66) |
- **Where agent logs land.** The FAST docs place them in `/aws/bedrock-agentcore/runtimes/{…}`, stream `otel-rt-logs` ([docs/CEDAR_POLICY_GUIDE.md:152](../../../docs/CEDAR_POLICY_GUIDE.md#L152)). The SDK's default log group is `/aws/bedrock-agentcore/runtimes/<agent_id>-DEFAULT` ([verification_2026-10-03.md, "Other corrections" table](../Agent%20evaluation%20signal%20on%20AWS/verification_2026-10-03.md)).
- **How the agent logs.** The agent configures no logging handler (no `basicConfig` under `agent/`). The image runs under `opentelemetry-instrument` with `OTEL_PYTHON_LOG_CORRELATION=true` and `aws-opentelemetry-distro==0.16.0` ([agent/ledgerlens/Dockerfile:9-18](../../../agent/ledgerlens/Dockerfile#L9-L18), [:36](../../../agent/ledgerlens/Dockerfile#L36)).
  - The SDK's JSON formatter, which adds `requestId` and `sessionId`, is attached only to the `bedrock_agentcore.app` logger ([bedrock_agentcore/runtime/app.py:70-101](file:///C:/Users/sebas/AppData/Local/uv/cache/archive-v0/M-7OR1epxWt0Gq7T/bedrock_agentcore/runtime/app.py), [:139-145](file:///C:/Users/sebas/AppData/Local/uv/cache/archive-v0/M-7OR1epxWt0Gq7T/bedrock_agentcore/runtime/app.py)).
- **Tool Lambda logs.**
  - **Location:** `/aws/lambda/ledgerlens-bank-assistant-<slug>` (one-week retention), although the functions are named `ledgerlens-<slug>` ([backend-construct.ts:892-916](../../../infra-cdk/lib/backend-construct.ts#L892-L916)).
  - **What they log on success:**

    | Tool | Success line | Source |
    |---|---|---|
    | `block_credit_card` | `block_credit_card: card <last4> blocked (already_blocked=<bool>)` | [handler.py:95-100](../../../gateway/tools/block_credit_card/block_credit_card_lambda/delivery/handler.py#L95-L100) |
    | `open_claim` | `open_claim: <n> claims (<k> already existed): CMP-…` | [handler.py:90-96](../../../gateway/tools/open_claim/open_claim_lambda/delivery/handler.py#L90-L96) |
    | `human_agent_hand_off` | `human_agent_hand_off queued HO-… (priority=…)` | [handler.py:84-86](../../../gateway/tools/human_agent_hand_off/human_agent_hand_off_lambda/delivery/handler.py#L84-L86) |
    | `transaction_fraud_detection` | `mode=… verdict_counts=…` | [handler.py:103-108](../../../gateway/tools/transaction_fraud_detection/transaction_fraud_detection_lambda/delivery/handler.py#L103-L108) |
    | `list_credit_cards` | `returned <n> cards (truncated=…)` | [handler.py:88-93](../../../gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/handler.py#L88-L93) |
    | `get_session_context` | `returned context (unavailable=…, truncated=…)` | [handler.py:93-98](../../../gateway/tools/get_session_context/get_session_context_lambda/delivery/handler.py#L93-L98) |
  - **Failures:** each handler logs a warning or an exception, and an error for a wrong tool name ([handler.py:70](../../../gateway/tools/block_credit_card/block_credit_card_lambda/delivery/handler.py#L70), [:87-92](../../../gateway/tools/block_credit_card/block_credit_card_lambda/delivery/handler.py#L87-L92)).
- **Pre-token Lambda log.** `/aws/lambda/ledgerlens-bank-assistant-pretoken-v3` logs the trigger source, `verified_user_id received`, and `No customer_id mapped for this user - customer_id blank` for an unmapped sub ([cognito-construct.ts:148-152](../../../infra-cdk/lib/cognito-construct.ts#L148-L152); [pretoken-v3/index.py:83-100](../../../infra-cdk/lambdas/pretoken-v3/index.py#L83-L100), [:115-131](../../../infra-cdk/lambdas/pretoken-v3/index.py#L115-L131)).
- **Policy metrics.** `AllowDecisions` and `DenyDecisions` are in namespace `AWS/Bedrock-AgentCore`, emitted by default without tracing. Dimensions include `OperationName`, `PolicyEngine`, `Policy`, `TargetResource`, `ToolName` and `Mode` ([verification_2026-10-03.md row 8b](../Agent%20evaluation%20signal%20on%20AWS/verification_2026-10-03.md)).
  - The policy engine is named `ledgerlens_bank_assistant_policy_engine` ([backend-construct.ts:1053](../../../infra-cdk/lib/backend-construct.ts#L1053)), and its id is a stack output ([backend-construct.ts:1085-1088](../../../infra-cdk/lib/backend-construct.ts#L1085-L1088)).
- **Prompt version and spans.** The prompt version is also on every agent span as `prompt.version`, but spans are unreachable while Transaction Search is off (L7). See [ledgerlens_agent.py:148-153](../../../agent/ledgerlens/ledgerlens_agent.py#L148-L153) and on-hold doc L7.
- **Log query limits.** `FilterLogEvents` is limited to 5 requests per second per account and Region. Use Logs Insights for bulk queries ([docs/AGENTCORE_EVALUATIONS_GUIDE.md:660](../../../docs/AGENTCORE_EVALUATIONS_GUIDE.md#L660)).

### Inferences
- **Usable for grading:**
  - **`[PROMPT] version=… session=<sid>`:** a deterministic per-session join that pins the prompt version of every trial. Query by the runner's session id.
  - **Tool Lambda success lines:** independent proof that a write ran, joined to the stream by `claim_id` (stable) or by `card_last4` + time window. They carry no session id, so with parallel trials only the id-bearing lines join safely.
  - **`DenyDecisions` summed over the run window:** should be 0 for agent runs, and should match the expected count for Gateway-direct Cedar tests (§5c). Use `ToolName` for per-tool attribution. One-minute metric granularity rules out per-session attribution unless trials are serialized.
- **Unreliable:**
  - `[CONFIRM]`/`[CUSTOMER-ID]` lines name no session. They join only by time, or by the OTel trace id that log correlation may add to the format. Prefer the stream: `confirmation` events and the `toolUse.input.customer_id` comparison.
- **Whether module INFO logs appear at all** depends on the ADOT instrumentor installing a root handler (`OTEL_PYTHON_LOG_CORRELATION=true` usually calls `logging.basicConfig`). This is a likely but unverified inference. Check one `[PROMPT]` line before building on it.

### Gaps
- **The exact runtime log group and stream names** for this agent (runtime id, `-DEFAULT` suffix, `otel-rt-logs` vs `runtime-logs`) need one `describe-log-groups`. Not done (read-only).
- **Spans in X-Ray.** Whether the agent's OTel spans reach X-Ray at all with no `AGENT_OBSERVABILITY_ENABLED`/`OTEL_*` variables (L7) is unknown. If they do, `BatchGetTraces` would be another source.
- **Gateway logs.** `docs/GATEWAY.md:329` mentions logs under `/aws/bedrock-agentcore/gateway/*`, but nothing in `infra-cdk/lib` turns on Gateway log or trace delivery. Their existence is unverified.

## 8. Model, configuration and throughput limits for about 100–300 sessions

### Takeaway
The agent runs `deepseek.v3.2` at temperature 0.1, behind a Bedrock guardrail in synchronous stream mode. The repo sets no concurrency, quota or runtime lifecycle limits.

Per request, the agent pays for a fresh Cognito machine token, four uncached SSM/Secrets reads, a Gateway `tools/list` and a memory load. The first turn of every session adds two tool Lambda calls.

Nothing in the code prevents a few hundred sessions over several hours. The binding limits are AWS quotas the repo doesn't record (Bedrock DeepSeek throughput, runtime session concurrency), and the token lifetime for multi-hour runs.

### Cited Findings
- **Model.** `model_id: "deepseek.v3.2"` ([infra-cdk/config.yaml:25-29](../../../infra-cdk/config.yaml#L25-L29)), passed as `MODEL_ID` ([backend-construct.ts:416-417](../../../infra-cdk/lib/backend-construct.ts#L416-L417)). `BedrockModel(model_id, temperature=0.1, **guardrail_settings())` ([ledgerlens_agent.py:102-112](../../../agent/ledgerlens/ledgerlens_agent.py#L102-L112)). The agent README also says the default is `deepseek.v3.2` ([agent/ledgerlens/README.md:46-48](../../../agent/ledgerlens/README.md#L46-L48)).
- **Guardrail.**
  - Sync stream processing holds each reply chunk until it is checked ([guardrail.py:37-38](../../../agent/ledgerlens/tools/guardrail.py#L37-L38)).
  - Standard tier with the cross-region profile `us.guardrail.v1:0` ([agent-guardrail.ts:97](../../../infra-cdk/lib/utils/agent-guardrail.ts#L97), [:118-124](../../../infra-cdk/lib/utils/agent-guardrail.ts#L118-L124)).
  - A version is published per config hash ([agent-guardrail.ts:127-140](../../../infra-cdk/lib/utils/agent-guardrail.ts#L127-L140)).
  - The agent refuses to start without `GUARDRAIL_ID`/`GUARDRAIL_VERSION` ([guardrail.py:23-32](../../../agent/ledgerlens/tools/guardrail.py#L23-L32)).
- **Runtime.** A PUBLIC-network HTTP-protocol runtime named `ledgerlens_bank_assistant_ledgerlens_agent`, Docker ARM64, with no lifecycle or concurrency settings ([backend-construct.ts:443-455](../../../infra-cdk/lib/backend-construct.ts#L443-L455); [config.yaml:11-15](../../../infra-cdk/config.yaml#L11-L15)).
- **Per-request fan-out:**
  - one Cognito `/oauth2/token` client-credentials call (30 s timeout), which also invokes the pre-token Lambda (30 s timeout) ([auth.py:211-240](../../../agent/utils/auth.py#L211-L240); [cognito-construct.ts:135-141](../../../infra-cdk/lib/cognito-construct.ts#L135-L141));
  - three SSM `GetParameter` calls and one Secrets Manager `GetSecretValue`, uncached ([auth.py:204-206](../../../agent/utils/auth.py#L204-L206); [gateway.py:65](../../../agent/ledgerlens/tools/gateway.py#L65); [ssm.py:17-38](../../../agent/utils/ssm.py#L17-L38));
  - a new MCP client to the Gateway ([gateway.py:68-74](../../../agent/ledgerlens/tools/gateway.py#L68-L74)) and a memory session manager ([ledgerlens_agent.py:114](../../../agent/ledgerlens/ledgerlens_agent.py#L114));
  - on the first turn, `get_session_context` and `classify_call_type` in parallel ([session_context.py:71-85](../../../agent/ledgerlens/tools/session_context.py#L71-L85)).
- **Tool Lambdas.** 30 s timeout for the DSQL tools, 10 s for the hand-off, no reserved concurrency set ([backend-construct.ts:893-911](../../../infra-cdk/lib/backend-construct.ts#L893-L911)).
- **Throttling is visible in the stream.** Strands streams `{"event_loop_throttled_delay": n}` when it backs off after model throttling ([strands/types/_events.py:260-273](file:///D:/Proyectos/ledgerlens-bank-assistant/.venv/Lib/site-packages/strands/types/_events.py)). An exhausted retry ends as the agent's `{"status":"error",…}` event inside an HTTP 200 stream ([ledgerlens_agent.py:200-202](../../../agent/ledgerlens/ledgerlens_agent.py#L200-L202)).
- **Usage and latency per model call** arrive in the raw `{"event": {"metadata": {...}}}` chunk, which Strands parses for usage and metrics ([strands/event_loop/streaming.py:366-454](file:///D:/Proyectos/ledgerlens-bank-assistant/.venv/Lib/site-packages/strands/event_loop/streaming.py)).
- **No reference latency.** The repo records no per-turn latency or throughput measurement (searched `docs/handoffs`, `datathon/docs` and the specs).

### Inferences
- **Concurrency.**
  - Run at modest concurrency, for example 4–8 sessions in flight, and never two requests at once in the same session.
  - Treat an in-stream `status:"error"` or any `event_loop_throttled_delay` as an infrastructure outcome: retry the trial, don't grade it.
  - Record per-turn wall-clock time and the `metadata.usage` tokens for the p50/p95 latency and cost rows of the planned metrics ([datathon/docs/analysis/2026-09-26-data-findings-and-workflow-decision.md:206](../../docs/analysis/2026-09-26-data-findings-and-workflow-decision.md#L206)).
- **Volume.** 300 sessions × about 4 requests gives about 1,200 runtime invocations, which means about 1,200 machine tokens and pre-token runs, about 3,600 SSM reads and about 1,200 secret reads. That is small against usual default AWS quotas, which were not checked here. The first-turn tool pair adds about 600 Lambda calls.
- **Client timeout.** A read timeout of 120–300 s per chunk is safer than `test-agent.py`'s 60 s, because sync guardrail checks delay chunks.

### Gaps
- Bedrock on-demand quotas (RPM/TPM) for `deepseek.v3.2` in us-east-1.
- AgentCore Runtime concurrent-session and invocation-rate quotas, the maximum request duration and the idle timeout.
- Cognito client-credentials token-request rate limits on the Essentials tier.
- Actual per-turn latency.

None of these are in the repo. They need Service Quotas or one pilot run.

## 9. Existing tests and scripts for the agent

### Takeaway
Unit tests pin the agent's building blocks (prompt hash per version, hooks, session context, markup filter, guardrail settings, memory manager, customer-id claim) and every tool's handler. Frontend tests mock the stream. There is no integration test, end-to-end runner or evaluation script in the repo. `tests/integration/` holds only `__init__.py`, and `test-scripts/test-agent.py` is an interactive chat.

### Cited Findings
- **`tests/unit/test_system_prompt.py`.**
  - Pins `sha256(prompt_template())` per `PROMPT_VERSION` (v10 is pinned) ([tests/unit/test_system_prompt.py:19-44](../../../tests/unit/test_system_prompt.py#L19-L44), [:61-65](../../../tests/unit/test_system_prompt.py#L61-L65)).
  - Content tests cover the fraud protocol, buttons not text, hand-off rules, privacy, the out-of-scope decline and session-context rendering ([test_system_prompt.py:56-323](../../../tests/unit/test_system_prompt.py#L56-L323)).
- **Hook and session tests:**
  - [tests/unit/test_confirmation_hook.py:65-160](../../../tests/unit/test_confirmation_hook.py#L65-L160): pause, Yes/No, typed reply, multiple clicks, result → confirmation event;
  - [tests/unit/test_customer_id_hook.py:97-168](../../../tests/unit/test_customer_id_hook.py#L97-L168): overwrite, add, unlinked cancel;
  - [tests/unit/test_session_context.py:66-212](../../../tests/unit/test_session_context.py#L66-L212): fetch once, retry on failure, no messages recorded, envelope unwrap;
  - [tests/unit/test_leaked_markup.py:32-58](../../../tests/unit/test_leaked_markup.py#L32-L58);
  - [tests/unit/test_guardrail.py:36-133](../../../tests/unit/test_guardrail.py#L36-L133);
  - [tests/unit/test_conversation_memory.py:63-249](../../../tests/unit/test_conversation_memory.py#L63-L249);
  - [tests/unit/test_auth_customer_id.py:48-82](../../../tests/unit/test_auth_customer_id.py#L48-L82);
  - [tests/unit/test_tool_requirements.py:36-43](../../../tests/unit/test_tool_requirements.py#L36-L43).
- **Gateway-side unit tests:**
  - one folder per tool, for example `tests/unit/human_agent_hand_off/` (handler, use case, tool spec, errors);
  - `tests/unit/cedar_policy/test_cedar_policy_statements.py`;
  - `tests/unit/pretoken_v3/test_pretoken_customer_id.py`;
  - CDK tests `infra-cdk/test/backend-gateway.test.ts` and `policy-cedar.test.ts`, which check target and tool names ([policy.cedar:19-22](../../../gateway/policies/policy.cedar#L19-L22)).
- **Frontend (vitest, mocked stream):**
  - `frontend/src/test/strands-parser.test.ts`: DeepSeek single-delta tool input, confirmations ([strands-parser.test.ts:18-36](../../../frontend/src/test/strands-parser.test.ts#L18-L36));
  - `confirmation-flow.test.tsx`: Yes/No cards, a resumed block, a hand-off on Yes, retry ([confirmation-flow.test.tsx:68-136](../../../frontend/src/test/confirmation-flow.test.tsx#L68-L136));
  - `handoff-flow.test.tsx` and `handoff.test.ts`.
- **No integration test.** `tests/integration/` contains only `__init__.py` (directory listing, 2026-10-04).
- **Only three invocation clients.** The only code that calls `/invocations` or uses `runtimeSessionId` is the agent itself, `frontend/src/lib/agentcore-client/client.ts` and `test-scripts/test-agent.py` (repo-wide search, excluding `node_modules` and `.venv`).
- **Interactive smoke scripts:** `test-scripts/test-agent.py`, `test-gateway.py`, `test-memory.py` and `test-feedback-api.py` ([test-scripts/README.md:18-80](../../../test-scripts/README.md#L18-L80); [README.md:188-190](../../../README.md#L188-L190)).
- **Out-of-repo evidence.** The 9-scenario confirmation check is described as done but its script isn't in the repo ([confirmation-buttons-frontend.md:97-109](../../../docs/handoffs/2026-10-04-confirmation-buttons-frontend.md#L97-L109)). The persona eval behind prompt v10 (PR #15) left no cases or scores in the repo (on-hold doc L11).

### Inferences
- **What the harness can reuse:**
  - `scripts/utils.get_stack_config` for config (it needs `cloudformation:DescribeStacks`);
  - the auth call in `authenticate_cognito`, without the admin check;
  - the SSE loop from `test-agent.py`;
  - the confirmation and envelope logic, mirrored from `confirmation_hook.resume_prompt`, `session_context._body` and `frontend/src/lib/handoff.ts`;
  - `test-gateway.py` as the base for Gateway-direct Cedar cases.
- **What fits by 2026-10-05:**
  - a stream-based runner with digest and graders;
  - scripted Yes/No answers;
  - per-persona Cognito users with a multi-entry map;
  - Gateway-direct Cedar tests;
  - direct-Lambda tool checks;
  - the `[PROMPT]` log join.
- **What does not fit, or is risky:**
  - `EVL-` clones or a DSQL restore for repeatable write cases (L5, L10; no DELETE grant);
  - span-based AgentCore Evaluations (L7 needs Transaction Search, likely ADOT ≥0.18.0 and a redeploy). A redeploy must wait for the branch's code review to finish, and it would also reset `USER_CUSTOMER_IDS_MAP`.
- **The first run is the baseline** (L11).

### Gaps
- The cases, transcripts and scores of the PR #15 persona eval are not in the repo (L11).
