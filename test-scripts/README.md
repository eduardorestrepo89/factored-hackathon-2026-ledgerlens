# Test scripts

Scripts that check a deployed LedgerLens stack one piece at a time: the agent, the Gateway with its Cedar policy, the feedback API and AgentCore Memory. They find the stack through `stack_name_base` in `infra-cdk/config.yaml` and share the helpers in [`scripts/utils.py`](../scripts/README.md#utilspy-and-requirementstxt).

## Setup

Run them from the repo root with Python 3.11+ and the `ledgerlens` profile. With [uv](https://docs.astral.sh/uv/), no virtual environment is needed:

```bash
AWS_PROFILE=ledgerlens uv run --no-project --with-requirements test-scripts/requirements.txt \
  python test-scripts/<script>.py
```

Or install `test-scripts/requirements.txt` (`boto3`, `requests`, `PyYAML`, `colorama`) into any virtual environment and run the scripts with its Python.

| Script | Checks | Needs |
|---|---|---|
| `test-agent.py` | The deployed agent, in a chat | A login linked to a customer |
| `test-gateway.py` | The Gateway and Cedar, without the agent | A login's Cognito `sub` (optional) |
| `test-feedback-api.py` | The feedback API | Any login |
| `test-memory.py` | AgentCore Memory events | Only AWS credentials |

A login is linked to a customer when its `sub` is in `USER_CUSTOMER_IDS_MAP` (`infra-cdk/lib/cognito-construct.ts`). See [First deployment](../docs/DEPLOYMENT.md#first-deployment), step 5.

---

### test-agent.py

An interactive chat with the bank card agent. One session ID covers the whole run, so the agent keeps the conversation. It prints the streamed text, each tool name and the first 200 characters of each tool result. Type `exit` or `quit` to end.

```bash
python test-scripts/test-agent.py           # remote: the deployed agent
python test-scripts/test-agent.py --local   # local: an agent on localhost:8080
```

**Remote (default).**
1. Reads `CognitoUserPoolId`, `CognitoClientId` and `RuntimeArn` from the main stack's outputs.
2. Prompts for a username and password, and signs in with `USER_PASSWORD_AUTH`. It first checks that the user exists with `AdminGetUser`, so your AWS identity needs `cognito-idp:AdminGetUser`.
3. Invokes the runtime (`qualifier=DEFAULT`) with the access token, as the frontend does.

Sign in as the demo login (`demo@ledgerlens.example`) or another linked login. Any other login gets a blank `customer_id`, so no tool call goes through: Cedar permits the tools only for a token with a `customer_id`.

**Local (`--local`)** sends requests to `http://localhost:8080/invocations` with an unsigned mock token whose `sub` is `local-test-user`. If nothing listens on port 8080, it starts `agent/<pattern>/ledgerlens_agent.py` with `uv run`. It adds only `MEMORY_ID` (from the `MemoryArn` output), `AWS_DEFAULT_REGION` and `STACK_NAME` to your environment. `--pattern` overrides `backend.pattern` from `config.yaml`; `ledgerlens` is the only pattern.

Local mode does not give a working chat as it stands:
- **Missing settings.** The agent also requires `MODEL_ID`, `GUARDRAIL_ID` and `GUARDRAIL_VERSION`. Without them, every request returns an error event, starting with `MODEL_ID environment variable is required`. The auto-start passes your shell environment through, so export the deployed runtime's values first.
- **Dependencies.** Run from the repo root, the auto-start's `uv run` uses the root `pyproject.toml` project. That project doesn't install the agent's dependencies (`agent/ledgerlens/requirements.txt`), and `agent/utils/` isn't on the import path when the file runs on its own. The agent only starts if your environment provides both.
- **No customer.** `local-test-user` isn't in `USER_CUSTOMER_IDS_MAP`, so its Gateway token has a blank `customer_id`, and no tool call goes through.

To test the agent, use remote mode. If you run the agent yourself on port 8080 (for example the container in [docs/LOCAL_DEVELOPMENT.md](../docs/LOCAL_DEVELOPMENT.md), with the three settings above), `--local` uses it instead of starting one. Tool calls still need a linked `sub`.

---

### test-gateway.py

Calls the AgentCore Gateway directly, without the agent or the frontend. It doesn't prompt for credentials: it acts as the machine client, the way the agent does.

1. Reads `gateway_url`, `machine_client_id` and `cognito_provider` from SSM (`/<stack_name_base>/...`).
2. Reads the machine client secret from Secrets Manager (`/<stack_name_base>/machine_client_secret`).
3. Gets a client-credentials token from Cognito's `/oauth2/token`. With `--user-sub`, it sends `{"verified_user_id": "<sub>"}` as `aws_client_metadata`, as `agent/utils/auth.py` does. The pre-token Lambda then adds that login's `customer_id` claim.
4. Lists the tools (`tools/list`). With `--customer-id`, it also calls `list_credit_cards` for that customer.

```bash
python test-scripts/test-gateway.py                                  # a token with no user claims
python test-scripts/test-gateway.py --user-sub <sub>                 # list the tools as that login
python test-scripts/test-gateway.py --user-sub <sub> --customer-id <id>
```

- `--user-sub`: the Cognito `sub` to act as. A `sub` that isn't in `USER_CUSTOMER_IDS_MAP` tests an unlinked login, whose `customer_id` is blank.
- `--customer-id`: the customer to pass to `list_credit_cards`. Leave it out to only list the tools.

Cedar lets the call through only when the token has a `customer_id` and it matches the call's `customer_id`. A linked `sub` with its own customer succeeds; another customer's id or an unlinked `sub` is refused. The script exits with 1 when the call is refused or fails.

It needs `cloudformation:DescribeStacks`, `ssm:GetParameter` and `secretsmanager:GetSecretValue` on the machine client secret.

---

### test-feedback-api.py

Tests the deployed feedback API (`POST /feedback`).

```bash
python test-scripts/test-feedback-api.py
```

1. Reads `CognitoUserPoolId`, `CognitoClientId` and `FeedbackApiUrl` from the main stack's outputs.
2. Prompts for a username (default `testuser`) and password, and signs in the same way as `test-agent.py` (so it also needs `cognito-idp:AdminGetUser`). It sends the ID token, which the API's Cognito authorizer expects.
3. Runs three tests: positive feedback (expects 200), negative feedback (200) and a request with missing fields (400).
4. Prints the results and the DynamoDB table name (`<stack_name_base>-feedback`). The two accepted requests are stored in that table.

---

### test-memory.py

Tests AgentCore Memory operations directly, with no login.

```bash
python test-scripts/test-memory.py                          # the memory from the MemoryArn output
python test-scripts/test-memory.py --memory-arn <arn>       # another memory
```

The tests:
1. Create conversation events.
2. List events, with pagination.
3. Get one event by ID.
4. Check session ID validation.
5. Check the error for an invalid memory ID.

The events are written to the deployed memory under the actor `test-user-12345`, in a new session.

---

## Troubleshooting

- **AccessDenied, or "Stack ... not found":** the script ran without `AWS_PROFILE=ledgerlens`, or `stack_name_base` in `config.yaml` doesn't match the deployed stack.
- **"User ... does not exist":** the username is wrong, or the login was never created.
- **"Authentication failed: 'AuthenticationResult'":** the login still has its temporary password. Sign in once in the web app to set a permanent one.
- **The agent can't see the cards, or tool calls are refused:** the login's `sub` isn't in `USER_CUSTOMER_IDS_MAP`, or a redeploy reset the map to its committed value. Check with `test-gateway.py --user-sub <sub> --customer-id <id>`.
- **Local agent errors on every request:** see the local mode limits under [test-agent.py](#test-agentpy).
- **Port 8080 in use:** `--local` talks to whatever listens there. Stop it, or use remote mode.
