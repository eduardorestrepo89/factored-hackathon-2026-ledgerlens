# API reference

LedgerLens exposes four interfaces:

| Interface | Who calls it | Auth |
|---|---|---|
| [AgentCore Runtime invocation](#agentcore-runtime-invocation) | The web app, `test-scripts/test-agent.py`, the eval harness | Cognito user access token (web client) |
| [Feedback API](#feedback-api) | The web app, `test-scripts/test-feedback-api.py` | Cognito user ID token |
| [Gateway MCP tools](#gateway-mcp-tools) | The agent, `test-scripts/test-gateway.py` | Cognito machine token (client credentials) carrying a `customer_id` claim |
| [Data pipeline CLI](#data-pipeline-cli) | CodeBuild (`ledgerlens-data-load`), and you for local rehearsals | AWS credentials |

The examples use the current deployment (`us-east-1`, profile `ledgerlens`). Read the IDs from the stack outputs if they changed: [DEPLOYMENT.md, Current deployment](DEPLOYMENT.md#current-deployment).

## AgentCore Runtime invocation

One request is one chat turn. The response is a stream of events that ends when the turn ends.

### Request

```
POST https://bedrock-agentcore.<region>.amazonaws.com/runtimes/<url-encoded runtime ARN>/invocations?qualifier=DEFAULT
```

The whole ARN is URL-encoded, `:` and `/` included (`encodeURIComponent` in `frontend/src/lib/agentcore-client/client.ts`, `quote(arn, safe='')` in `evals/runner.py`).

| Header | Value |
|---|---|
| `Authorization` | `Bearer <access token>`: a Cognito access token issued to the web client (`CognitoClientId`). The Runtime's JWT authorizer validates it before the agent runs. |
| `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` | The session id; the same value as `runtimeSessionId` in the body. |
| `Content-Type` | `application/json` |
| `X-Amzn-Trace-Id` | Optional. The web client sends one per request. |

The agent takes the user's identity (`sub`, `cognito:groups`) from the validated token, never from the body (`agent/utils/auth.py`). A body can't name a customer.

Body:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `prompt` | string | yes | The customer's message. Must be non-empty, even when the request only answers a confirmation. |
| `runtimeSessionId` | string | yes | The conversation id. The agent uses it as the AgentCore Memory session, so the same id continues a conversation and a new id starts one. Use 33 to 100 characters of letters, digits, `-` and `_` (a UUID works; that is what the web client sends). |
| `confirmations` | array of `{interruptId, approved}` | no | Answers to the Yes/No cards of the previous turn. See [Answering a confirmation](#answering-a-confirmation). |
| `eval` | object `{model_id, prompt_name, system_prompt}` | no | For evaluation logins only. See [Evaluation override](#evaluation-override). |

If `prompt` or `runtimeSessionId` is missing, the stream holds a single error event: `Missing required fields: prompt or runtimeSessionId`.

### Example

```bash
export AWS_PROFILE=ledgerlens
out() { aws cloudformation describe-stacks --stack-name ledgerlens-bank-assistant \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
CLIENT_ID=$(out CognitoClientId)
RUNTIME_ARN=$(out RuntimeArn)

read -rsp "Password: " PASSWORD; echo
TOKEN=$(aws cognito-idp initiate-auth --auth-flow USER_PASSWORD_AUTH --client-id "$CLIENT_ID" \
  --auth-parameters USERNAME=demo@ledgerlens.example,PASSWORD="$PASSWORD" \
  --query "AuthenticationResult.AccessToken" --output text)

SESSION=$(python -c "import uuid; print(uuid.uuid4())")
ARN=$(python -c "import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=''))" "$RUNTIME_ARN")

curl -N -X POST "https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/$ARN/invocations?qualifier=DEFAULT" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: $SESSION" \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"Why was my purchase declined?\", \"runtimeSessionId\": \"$SESSION\"}"
```

The web client allows the `USER_PASSWORD_AUTH` flow and has no secret (`infra-cdk/lib/cognito-construct.ts`), which is why `initiate-auth` works without a secret hash. The shorthand `--auth-parameters` syntax breaks on a password that contains a comma. `test-scripts/test-agent.py` does the same sign-in interactively.

### Response stream

The response is Server-Sent Events: one `data: <JSON>` line per event. The agent (`agent/ledgerlens/ledgerlens_agent.py`) passes Strands' `stream_async` events through, serialized with `json.dumps(..., default=str)`, and adds two LedgerLens events. The events a client needs:

| Event | Shape | Meaning |
|---|---|---|
| Text | `{"data": "<chunk>"}` | A piece of the reply. Concatenate the chunks. |
| Tool call | `{"current_tool_use": {"toolUseId", "name", "input"}, "delta": {"toolUse": {"input": "<chunk>"}}}` | The model is writing a tool call. `name` is `gateway_<target>___<tool>`; take the part after the last `___`. |
| Message | `{"message": {"role", "content": [...]}}` | A complete message. A `user` message carries the `toolResult` blocks with each tool's output. |
| Result | `{"result": "<final result as a string>"}` | The turn is over. |
| Confirmation | `{"confirmation": {"id", "tool", "toolUseId", "details"}}` | LedgerLens: a tool call is waiting for the customer's Yes or No. Sent just before the result event. |
| Error | `{"status": "error", "error": "<message>"}` | LedgerLens: the turn failed and the stream ends. |

Other Strands events (lifecycle flags such as `init_event_loop` and `start_event_loop`, raw model events) are safe to ignore. [STREAMING.md, Events on the wire](STREAMING.md#events-on-the-wire) has the full event grammar, an example turn, and how the frontend parser (`frontend/src/lib/agentcore-client/parsers/strands.ts`) turns each event into UI events.

Two details of the text events:
- **Leaked markup is filtered.** Some models write their raw tool-call marker into the reply text. The agent strips it before streaming (`tools/leaked_markup.py`), holding back a chunk that might be the start of a marker until the next one arrives.
- **A guardrail block replaces the reply.** When the Bedrock guardrail blocks the customer's message or the reply, the text is the guardrail's fixed message, in Spanish, Portuguese and English on three lines (`infra-cdk/lib/utils/agent-guardrail.ts`).

The error event's `error` is the exception text. Typical values: `Missing required fields: prompt or runtimeSessionId`, `eval override rejected: <why>`, `MODEL_ID environment variable is required`. The web client's parser has no case for the error event, so in the app a failed turn ends without text.

A request without a valid token is refused by the Runtime's JWT authorizer with a non-200 HTTP response before the agent runs; the web client shows it as `HTTP <status>: <body>`.

### Answering a confirmation

`block_credit_card`, `open_claim` and `human_agent_hand_off` never run when the model calls them. `ConfirmationHook` (`agent/ledgerlens/tools/confirmation_hook.py`) pauses the call with a Strands interrupt, the turn ends, and the stream carries:

```json
{"confirmation": {
  "id": "<interrupt id>",
  "tool": "block_credit_card",
  "toolUseId": "<the paused tool call>",
  "details": {"card_last4": "4497", "reason": "suspected_fraud"}
}}
```

`details` is the tool input without `customer_id` and `customer_confirmed`. The paused call is saved with the session, so the next request resumes that exact call:

```json
{
  "prompt": "Sí",
  "runtimeSessionId": "<same session>",
  "confirmations": [{"interruptId": "<confirmation.id>", "approved": true}]
}
```

- **`approved: true` runs the call.** For `block_credit_card` and `open_claim` the hook sets `customer_confirmed: true` on the input, which Cedar requires. The value comes from the click, never from the model.
- **Anything else is a No.** `approved: false`, or a pending confirmation missing from the list, cancels the call and tells the model not to retry unless the customer asks.
- **A typed reply is a No that carries the text.** A request without `confirmations` while a call waits cancels it, and the model reads the text as the customer's words. If they still want the action, the model calls the tool again and a new confirmation event follows.
- **`prompt` is ignored** when `confirmations` is a list, but it must still be non-empty. The web client sends the button's label; the eval harness sends `"[button]"`.
- **An approved call isn't announced again.** It runs in the answering request, so its result arrives in a `message` event (`toolResult`) without a `current_tool_use` event before it.

The full sequence, with the events on the wire: [STREAMING.md, Confirmation round trip](STREAMING.md#confirmation-round-trip).

### Evaluation override

The eval harness (`evals/`) compares models and prompts against the deployed agent through an optional `eval` object:

```json
"eval": {"model_id": "deepseek.v3.2", "prompt_name": "v12", "system_prompt": "<base prompt text>"}
```

The rules (`agent/ledgerlens/tools/eval_override.py`):
- **Evaluators only.** It applies only when the token's `cognito:groups` lists `evaluators`. Anyone else's `eval` field is ignored and the request runs on the defaults.
- **`model_id`** must be in `EVAL_MODEL_IDS`, the runtime variable built from `backend.eval_model_ids` in `infra-cdk/config.yaml`: `deepseek.v3.2`, `openai.gpt-oss-120b-1:0` and `global.anthropic.claude-haiku-4-5-20251001-v1:0`. It defaults to `MODEL_ID`.
- **`system_prompt`** is optional: 1 to 40,000 characters. It replaces only `BASE_SYSTEM_PROMPT`; the session blocks, both hooks, the guardrail and Cedar apply as for a customer.
- **`prompt_name`** is required with `system_prompt` and must match `[a-z0-9][a-z0-9._-]{0,31}`. The prompt version on the agent's spans becomes `<prompt_name>-<first 8 hex of the text's SHA-256>`.

An invalid override from an evaluator ends the turn with `eval override rejected: <why>` instead of silently running on the defaults.

## Feedback API

The thumbs up/down in the chat. Contract in `infra-cdk/lib/backend-construct.ts` (`createFeedbackApi`); handler in `infra-cdk/lambdas/feedback/index.py`.

```
POST <FeedbackApiUrl>feedback
```

`FeedbackApiUrl` is a stack output ending in `/prod/`. Current: `https://t886ssi6jk.execute-api.us-east-1.amazonaws.com/prod/feedback`.

| Header | Value |
|---|---|
| `Authorization` | `Bearer <ID token>`: a Cognito user pool **ID** token. API Gateway checks it with a Cognito user pools authorizer; the web client and `test-feedback-api.py` both send the ID token, not the access token. |
| `Content-Type` | `application/json` |

Body (camelCase; the snake_case names are accepted too):

| Field | Type | Required | Rule |
|---|---|---|---|
| `sessionId` | string | yes | 1 to 100 characters: letters, digits, `-`, `_` |
| `message` | string | yes | The agent reply being rated, 1 to 5,000 characters |
| `feedbackType` | `"positive"` or `"negative"` | yes | |
| `comment` | string | no | Up to 5,000 characters |

Responses:

| Status | Body | When |
|---|---|---|
| 200 | `{"success": true, "feedbackId": "<uuid>"}` | Saved |
| 400 | `{"error": "<validation message>"}` | A field is missing or breaks a rule |
| 401 | `{"message": "Unauthorized"}` from API Gateway, or `{"error": "Unauthorized"}` from the Lambda | Missing or invalid token |
| 500 | `{"error": "Internal server error"}` | DynamoDB or another failure |

Each item in DynamoDB table `ledgerlens-bank-assistant-feedback` holds `feedbackId`, `sessionId`, `message`, `userId` (the token's `sub`), `feedbackType`, `timestamp` (epoch milliseconds) and `comment` when given.

- **CORS** allows the Amplify URL and `http://localhost:3000`, methods `POST` and `OPTIONS`, headers `Content-Type` and `Authorization`.
- **Throttling** on the `prod` stage: 100 requests per second, bursts of 200.

```bash
ID_TOKEN=$(aws cognito-idp initiate-auth --auth-flow USER_PASSWORD_AUTH --client-id "$CLIENT_ID" \
  --auth-parameters USERNAME=demo@ledgerlens.example,PASSWORD="$PASSWORD" \
  --query "AuthenticationResult.IdToken" --output text)

curl -X POST "https://t886ssi6jk.execute-api.us-east-1.amazonaws.com/prod/feedback" \
  -H "Authorization: Bearer $ID_TOKEN" -H "Content-Type: application/json" \
  -d '{"sessionId": "manual-test-1", "message": "The agent reply being rated", "feedbackType": "positive"}'
```

## Gateway MCP tools

The AgentCore Gateway serves the 9 tools over MCP (protocol `2025-03-26`, JSON-RPC 2.0 over HTTP).

### Calling the Gateway

- **URL:** SSM parameter `/ledgerlens-bank-assistant/gateway_url`.
- **Token:** the Gateway's JWT authorizer accepts only the machine client.
  - The token comes from Cognito's `/oauth2/token` with `grant_type=client_credentials`, and `aws_client_metadata={"verified_user_id": "<cognito sub>"}` to act for a user.
  - The V3 pre-token Lambda turns that sub into a `customer_id` claim through `USER_CUSTOMER_IDS_MAP`, blank for an unmapped sub.
  - `agent/utils/auth.py` and `test-scripts/test-gateway.py` both build it this way.
- **Methods:** `tools/list`, and `tools/call` with `{"name": "<target>___<tool>", "arguments": {...}}`. For example `list-credit-cards-target___list_credit_cards`. The agent sees the same tools with a `gateway_` prefix.

The easiest way to call it by hand is the smoke script: [usage.md, Smoke scripts](usage.md#smoke-scripts).

### Rules every call goes through

1. **Cedar** (`gateway/policies/policy.cedar`):
   - It permits the 9 tools only when the token's `customer_id` claim is non-empty.
   - It forbids any call whose `customer_id` argument differs from that claim.
   - It forbids `block_credit_card` and `open_claim` unless `customer_confirmed` is present and `true`.
2. **In the agent**, before Cedar:
   - `CustomerIdHook` overwrites `customer_id` on every call with the token's claim, whatever the model wrote, and cancels the call when the login isn't linked.
   - `ConfirmationHook` holds the three action tools until the customer taps Yes ([Answering a confirmation](#answering-a-confirmation)).
3. **In the Lambda:**
   - Each tool validates its own arguments. The write tools refuse `customer_confirmed` other than `true` before touching the database.
   - Each Lambda checks that the tool name in `context.client_context.custom["bedrockAgentCoreToolName"]` is its own.

### Tool results

The Lambda returns `{"content": [{"type": "text", "text": "<JSON body>"}]}` on success. Through the Gateway, that body is the MCP tool result's text. The Gateway may also pass the Lambda's whole `{"content": [...]}` envelope through as text, so parse one level deeper when you find it; the agent (`tools/session_context.py`) and the frontend (`lib/handoff.ts`) both do.

On failure the Lambda returns `{"error": "<message>"}`. The message is written for the model: what went wrong and what to do next, for example *"No credit card ending in 1234 was found for this customer. Check the card with list_credit_cards and confirm it with the customer."* Raw exception text, SQL and hostnames never reach it. A call Cedar denies never reaches the Lambda; `test-gateway.py` treats a JSON-RPC `error` and a result with `isError: true` alike, as a refusal.

Common to the bodies:
- **Amounts** are strings with 2 decimals, rounded half up, in the stated currency.
- **Dates** are ISO 8601.
- **"Today"** is `AS_OF` (`data.as_of` in `config.yaml`, `2026-06-17T23:59:59`), not the real clock.
- **`unavailable`** lists sections that couldn't be loaded; those sections are `null`. `truncated` names lists that had more items.
- **No fraud score** is ever returned.

### The 9 tools

Every tool requires `customer_id` (string). The other arguments:

| Tool | Other arguments | Returns |
|---|---|---|
| `list_credit_cards` | none | `cards` (`card_last4`, `product_status`, `currency`, `current_balance`, `credit_limit`, `available_credit`, `expiration_date`, `days_past_due`), `count`, `truncated`. At most 25 cards, active first, every status. `cards` is `null` when the customer has none. |
| `list_card_transactions` | Optional: `card_last4`; `date_from`, `date_to` (`YYYY-MM-DD`; default the 30 days up to today; range at most 180 days); `merchant` (partial match ignoring case and accents, up to 100 characters); `min_amount`, `max_amount` (≥ 0); `status` (`Approved`, `Declined`, `Pending`, `Reversed`) | `transactions` (`transaction_id`, `transaction_date`, `card_last4`, `merchant_name`, `merchant_category`, `amount`, `currency`, `channel`, `transaction_city`, `transaction_country`, `transaction_status`), `count`, `truncated`. At most 25 rows, newest first. |
| `get_session_context` | none | `as_of`, `customer` (`customer_id`, `first_name`, `country`, `city`, `customer_status`), `cards`, `recent_transactions` (last 72 hours, with `flags`: `declined`, `foreign`, `above_usual_amount`, `new_merchant`), `digital_signals` (app and web, last 24 hours), `open_cases` (at most 5), `truncated`, `unavailable`. Lists hold at most 25 items. |
| `classify_call_type` | none | `reasons`: up to 3 likely reasons for the contact, best first, each with `reason`, `confidence` (0 to 1), `ref_id` (a transaction, complaint, event id or card last 4) and `evidence`; plus `unavailable`. Reasons: `FRAUD_SUSPECTED`, `UNRECOGNIZED_CHARGE_REVIEW`, `DECLINED_TRANSACTION`, `PENDING_TRANSACTION`, `REVERSED_TRANSACTION`, `OPEN_CASE_FOLLOWUP`, `CARD_NOT_ACTIVE`, `FAILED_APP_ACTION`, `FOREIGN_TRANSACTION`, `PAYMENT_OVERDUE`, `CARD_EXPIRING`. |
| `explain_transaction` | Required: `transaction_id` | `transaction` (the charge); `fx` (`card_currency`, `rate_date`, `rate`, `amount_in_card_currency`) when it was in another currency; `decline` (`response_code`, `meaning`, `contradicts_card_state`) for a declined charge; `habit` over the card's 90 days before the charge; `app_activity` (the closest app or web session within 2 hours, with `conflict`); `unavailable`. |
| `transaction_fraud_detection` | Exactly one of `transaction_id` or `card_last4` | `{"mode": "transaction", "assessment": {...}}` for one charge, or `{"mode": "card", "card_last4", "date_from", "date_to", "checked", "flagged": [...], "truncated"}` for a 30-day sweep. Each assessment has the charge's fields, `verdict` (`fraud`, `review`, `no_fraud`), `basis` (`not_scored` means the engine produced no score) and `next_step`. |
| `block_credit_card` | Required: `card_last4`; `reason` (`suspected_fraud`, `lost`, `stolen`, `customer_request`); `customer_confirmed` (must be `true`) | `card_last4`, `status`, `already_blocked` (`true` when it was blocked before: not an error). A closed card or two cards with the same last 4 digits return an error. |
| `open_claim` | Required: `transaction_ids` (1 to 10); `claim_type` (`fraud` or `dispute`); `customer_statement` (1 to 500 characters); `customer_confirmed` (must be `true`) | `claims`, one per card and currency: `claim_id`, `card_last4`, `transaction_ids`, `claimed_amount`, `currency`, `priority`, `status`, `already_existed`. Plus `resolution_estimate` (`median_days`, `p90_days` from similar claims over the last year, or `null`). |
| `human_agent_hand_off` | Required: `priority` (`high` or `normal`); `reason` (`FRAUD_CONFIRMED`, `CUSTOMER_REQUEST`, `UNRESOLVED`, `OUT_OF_SCOPE`); `summary` (1 to 2,000 characters). Optional: `related_ids` (up to 20 ids of letters, digits and dashes) | `hand_off_id` (`HO-` plus 8 characters), `status` (`queued`), `priority`, `reason`, `customer_id`, `summary`, `related_ids`. |

What each write does:
- **`block_credit_card`** sets the card's `product_status` to `Blocked` in DSQL. It never touches a card that is already blocked or closed, so a repeated call is safe.
- **`open_claim`** inserts into `complaints`. The claim id is a hash of its content, so repeating the same claim returns the existing one with `already_existed: true`.
- **`human_agent_hand_off`** writes nothing and calls no service. The id comes from a hash of the content, so a retried call gives the same id. The frontend reads the result from the stream and opens the agent desk ([usage.md, Hand-off](usage.md#hand-off-to-a-person)).

The full model-facing descriptions are each tool's `gateway/tools/<tool>/tool_spec.json`; the bodies are built in `<tool>_lambda/delivery/presenters/`.

## Data pipeline CLI

`python -m data_load <stage>` runs one stage of the pipeline that loads Aurora DSQL (`data_load/__main__.py`). In AWS, the CodeBuild project `ledgerlens-data-load` runs `python -m data_load $STAGE`, and the Step Functions state machine `ledgerlens-data-pipeline` sets `STAGE` and `RUN_ID`. To start or rerun stages there, see [DEPLOYMENT.md, Operating the data pipeline](DEPLOYMENT.md#operating-the-data-pipeline).

| Stage | Environment | Arguments | What it does |
|---|---|---|---|
| `ingest` | `RUN_ID`, `TEAM_BUCKET`, `HACKATHON_SECRET_ID` | none | Copies the organizer's CSVs byte for byte to `raw/<run-id>/` in the team bucket, using the keys in the secret. |
| `transform` | `RUN_ID`, `TEAM_BUCKET` (not with `--source`) | `--source <dir>` (local organizer-layout folder; nothing in AWS is read or written), `--out <dir>` (default `<temp>/ledgerlens-pipeline`), `--tables a,b` (only with `--source`) | Checks types and constraints against `schema.sql`, applies repairs R1–R6, writes Parquet to `clean/<run-id>/`. |
| `curate` | `RUN_ID`, `TEAM_BUCKET` (not with `--source`) | `--source <dir>` (local clean Parquet), `--out <dir>`, `--customers N` (default 1500), `--defect-per-class N` (default 20) | Applies rules C1–C12, selects the customers and the defect cohort, writes `curated/<run-id>/`. |
| `load` | `RUN_ID`, `TEAM_BUCKET`, `DSQL_ENDPOINT`, `TOOLS_ROLE_ARN`, `WRITE_TOOLS_ROLE_ARN` | none | Drops and recreates the 13 tables, bulk-loads `curated/<run-id>/`, builds the indexes. Needs that run's `curate.json`. |
| `access` | `DSQL_ENDPOINT`, `TOOLS_ROLE_ARN`, `WRITE_TOOLS_ROLE_ARN` | none | Creates the `ll_read` and `ll_write` roles, maps them to their IAM roles and re-runs the grants. Touches no data. |
| `check` | AWS profiles (below) | `--run <run-id>` and `--team-bucket <bucket>` (both required), `--team-profile` (default `ledgerlens`), `--bucket-profile` (default `hackathon`) | Compares the organizer's bucket with a run's ingest record. Exits 1 and names the tables that changed since the ingest. |

- **Missing environment:** a stage stops with `missing environment variables: <names>`.
- **Run records:** `ingest`, `transform`, `curate` and `load` each clear and rewrite theirs, `runs/<run-id>/<stage>.json` in the team bucket.
- **`load` and `access` run only from CodeBuild:** the DSQL cluster policy refuses every identity from outside the VPC except the loader role.
- **From a laptop**, the useful runs are `transform` and `curate` with `--source` (local rehearsals) and `check`:

  ```bash
  uv run --no-project --with-requirements data_load/requirements.txt python -m data_load check --run <run-id> --team-bucket <team-bucket>
  ```
