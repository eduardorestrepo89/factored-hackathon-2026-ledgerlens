# AgentCore Gateway

The Gateway is how the LedgerLens agent reaches its 9 tools. It is an MCP server in front of one Lambda per tool. Before a tool runs, the Gateway checks two things: that the machine token is valid, and that the Cedar policy allows the call.

This page covers how the Gateway is built, the contract each tool Lambda follows, and how to test and debug it. The tool list (Lambda, target, database access) is in [DEPLOYMENT.md, Gateway tools](DEPLOYMENT.md#gateway-tools), and the steps to add a tool are in [DEPLOYMENT.md, Updating](DEPLOYMENT.md#updating).

## Request path

```
Agent (AgentCore Runtime)
  │  POST <gateway_url>   Authorization: Bearer <machine token with customer_id>
  ▼
Gateway  ledgerlens-bank-assistant-gateway (MCP 2025-03-26)
  │  1. JWT authorizer: signed by the user pool, issued to the machine client?   no → 401
  │  2. Cedar policy engine (ENFORCE): tools/list hides denied tools,
  │     tools/call rejects denied calls
  ▼
Tool Lambda  ledgerlens-<slug>   (invoked with the Gateway's IAM role)
  │
  ▼
Aurora DSQL (8 tools; the hand-off tool uses no database)
```

## Why Lambda targets, one tool per Lambda

The Gateway only routes and authorizes. Each tool's code lives in its own Lambda, so:
- each tool gets the IAM role it needs: the read tools connect to DSQL as `ll_read`, the two write tools as `ll_write`, and the hand-off tool has no database access at all;
- each tool has its own timeout, log group and deployment package;
- a read tool can't write, even with a bug: only `block_credit_card` and `open_claim` run with the write role.

A Lambda target could route several tools by name. LedgerLens doesn't: each handler serves exactly one tool and refuses any other name (see [Output](#output)).

## How it is built

Everything is in `createAgentCoreGateway()` in `infra-cdk/lib/backend-construct.ts`. It uses the L2 constructs from `aws-cdk-lib/aws-bedrockagentcore` (imported as `agentcore`).

### The Gateway

```typescript
const gateway = new agentcore.Gateway(this, "AgentCoreGateway", {
  gatewayName: `${config.stack_name_base}-gateway`,
  role: gatewayRole,
  protocolConfiguration: new agentcore.McpProtocolConfiguration({
    supportedVersions: [agentcore.MCPProtocolVersion.MCP_2025_03_26],
  }),
  authorizerConfiguration: agentcore.GatewayAuthorizer.usingCustomJwt({
    discoveryUrl: cognitoDiscoveryUrl,
    allowedClients: [this.machineClient.userPoolClientId],
  }),
  description: "AgentCore Gateway with MCP protocol and JWT authentication",
})
```

- **Authorizer.** The custom JWT authorizer fetches the user pool's signing keys from its OIDC discovery URL. `allowedClients` holds only the machine client (`ledgerlens-bank-assistant-machine-client`). A token issued to the web client, even from the same user pool, is rejected.
- **Gateway role.** Trusted by `bedrock-agentcore.amazonaws.com`. `addLambdaTarget()` grants it `lambda:InvokeFunction` on each tool. It also has `GetPolicyEngine`, `AuthorizeAction`, `PartiallyAuthorizeActions` and `CheckAuthorizePermissions`, which the Gateway needs to evaluate Cedar. The rest of its grants: Bedrock invoke, SSM read under `/<stack>/`, `cognito-idp:DescribeUserPoolClient` and `InitiateAuth` on the user pool, and CloudWatch Logs under `/aws/bedrock-agentcore/*`.
- **SSM.** The Gateway URL is stored at `/ledgerlens-bank-assistant/gateway_url`. The stack also outputs `GatewayId`, `GatewayUrl`, `GatewayArn`, `PolicyEngineId` and `CedarPolicyId`.

### The targets

The `toolTargets` array has one entry per tool. For each entry, CDK creates a `PythonFunction` and wires it as a target:

```typescript
return gateway.addLambdaTarget(`${id}Target`, {
  gatewayTargetName: target ?? `${slug}-target`,
  description: `LedgerLens ${tool} tool`,
  lambdaFunction: toolFunction,
  toolSchema: agentcore.ToolSchema.fromLocalAsset(
    path.join(__dirname, "../../gateway/tools", tool, "tool_spec.json")
  ),
})
```

- **Target name:** `<slug>-target`, where the slug is the tool name with `-` for `_`. An entry can override it (see [Tool names](#tool-names)).
- **Schema:** read from `gateway/tools/<tool>/tool_spec.json` at deploy time.
- **Outbound credentials:** none are set, so the Gateway calls the Lambda with its own IAM role (the L2 default).

Each tool Lambda:

| Setting | Value |
|---|---|
| Function name | `ledgerlens-<slug>` (e.g. `ledgerlens-list-credit-cards`) |
| Code | the whole `gateway/tools/<tool>/` folder, without `__pycache__` and `.pyc` files |
| Handler | `<tool>_lambda/delivery/handler.py`, function `handler` |
| Runtime | Python 3.13, ARM64 |
| Log group | `/aws/lambda/ledgerlens-bank-assistant-<slug>`, one-week retention |

Roles and network depend on what the tool touches:

| Tools | Role | Network | Timeout | Environment |
|---|---|---|---|---|
| The 6 read tools | `data.toolsRole` (`ledgerlens-tools`, DSQL user `ll_read`) | Data stack VPC | 30 s | `DSQL_CLUSTER_ENDPOINT`, `AS_OF` |
| `block_credit_card`, `open_claim` | `data.writeToolsRole` (`ledgerlens-write-tools`, DSQL user `ll_write`) | Data stack VPC | 30 s | `DSQL_CLUSTER_ENDPOINT`, `AS_OF` |
| `human_agent_hand_off` | CDK's default Lambda role | Outside any VPC | 10 s | none |

The DSQL tools run in the data stack's public subnets with the tools security group, but Lambdas get no public IP there. So they reach only the DSQL PrivateLink endpoint. The hand-off tool calls no AWS service, so it stays outside the VPC.

### The Cedar policy

A custom resource attaches a Cedar policy engine to the Gateway in `ENFORCE` mode and loads `gateway/policies/policy.cedar`. It depends on every target, because `CreatePolicy` fails for an action whose target doesn't exist yet. See [Authorization](#authorization-cedar-and-the-agent-hooks) below and the [Cedar Policy Guide](CEDAR_POLICY_GUIDE.md).

## Tool names

The Gateway names each tool `<target>___<tool>`, with three underscores:
- `<target>` is the Gateway target name from `toolTargets`.
- `<tool>` is the `name` in the tool's `tool_spec.json`.

For example: `list-credit-cards-target___list_credit_cards`. The same string is the tool's Cedar action name.

The agent's MCP client adds the prefix `gateway`, so the model sees `gateway_list-credit-cards-target___list_credit_cards`. Bedrock rejects every request (not just that tool's) if any tool name is longer than 64 characters. That's why `transaction_fraud_detection` uses the target `fraud-detection-target`: with the default target, its name would be 72 characters; with the short one it is 60.

`infra-cdk/test/backend-gateway.test.ts` checks the target names, the 64-character limit, and that every Cedar action matches a deployed target and its `tool_spec.json` name.

## Tool Lambda contract

Every handler in `gateway/tools/<tool>/<tool>_lambda/delivery/handler.py` follows the same contract. `list_credit_cards` is the reference below.

### Input

The Gateway passes the tool arguments directly as the Lambda `event`, a JSON object such as `{"customer_id": "CLI-..."}`. There is no envelope.

The tool name is **not** in the event. It arrives in the Lambda context, with the target prefix:

```python
full_name = context.client_context.custom["bedrockAgentCoreToolName"]
# "list-credit-cards-target___list_credit_cards"
tool_name = full_name.rpartition("___")[2]
# "list_credit_cards"
```

### Output

| Case | Return value |
|---|---|
| Success | `{"content": [{"type": "text", "text": "<JSON>"}]}` |
| Known error | `{"error": "<agent-facing message>"}` |
| Unexpected exception | `{"error": "<generic message>"}`: raw exception text is never returned, because it could leak SQL, hosts or driver details to the model |
| Wrong tool name | `{"error": "This function only serves the 'list_credit_cards' tool. Don't retry; offer a hand-off to a human agent."}` |

The handler builds its dependencies (settings, DSQL connector, use case) once, when the module loads, so a warm Lambda reuses them.

### Folder layout

```
gateway/tools/list_credit_cards/
├── tool_spec.json                 # MCP schema, loaded by CDK
├── requirements.txt               # the 8 DSQL tools have one; the hand-off tool doesn't
└── list_credit_cards_lambda/
    ├── delivery/handler.py        # Lambda entry point
    ├── application/               # use case and ports
    ├── domain/                    # entities and errors
    ├── infrastructure/            # DSQL repository, query loader
    ├── queries/postgresql/        # SQL files
    └── utils/connectors/          # DSQL connection
```

Each folder is self-contained: `PythonFunction` bundles the folder and installs its `requirements.txt`.

### Tool schema

`tool_spec.json` is a JSON array with one tool:

```json
[
  {
    "name": "list_credit_cards",
    "description": "Lists the customer's credit cards in every status ...",
    "inputSchema": {
      "type": "object",
      "properties": {
        "customer_id": {
          "type": "string",
          "description": "The authenticated customer's id from get_session_context."
        }
      },
      "required": ["customer_id"]
    }
  }
]
```

All 9 tools require `customer_id`. The agent's `CustomerIdHook` and Cedar both depend on it. `block_credit_card` and `open_claim` also require `customer_confirmed`, which Cedar checks.

Use these JSON schema types:
- `"integer"` for integers (not `"int"`)
- `"number"` for floats
- `"string"`, `"boolean"`, `"array"`, `"object"`

## Authentication

The Gateway accepts only tokens that Cognito issues to the machine client with the client credentials grant and the scopes `ledgerlens-bank-assistant-gateway/read` and `/write`.

What a caller needs, and where it lives:

| Value | Where |
|---|---|
| Gateway URL | SSM `/ledgerlens-bank-assistant/gateway_url` |
| Machine client ID | SSM `/ledgerlens-bank-assistant/machine_client_id` |
| Machine client secret | Secrets Manager `/ledgerlens-bank-assistant/machine_client_secret` (not SSM) |
| Cognito domain for `/oauth2/token` | SSM `/ledgerlens-bank-assistant/cognito_provider` |

The agent asks for one token per request and passes the signed-in user's Cognito `sub` as `aws_client_metadata`. The V3 pre-token Lambda turns that `sub` into a `customer_id` claim. See [RUNTIME_GATEWAY_AUTH.md](RUNTIME_GATEWAY_AUTH.md) for the token flow and [IDENTITY_POLICY.md](IDENTITY_POLICY.md) for the `sub` to `customer_id` mapping.

## Authorization: Cedar and the agent hooks

The policy engine is attached in `ENFORCE` mode, so its decisions are applied, not just logged. `gateway/policies/policy.cedar` has three statements:
1. **Permit** the 9 tools when the token has a non-empty `customer_id`.
2. **Forbid** any call whose `customer_id` input differs from the token's.
3. **Forbid** `block_credit_card` and `open_claim` unless `customer_confirmed` is `true`.

The agent enforces the same rules before a call leaves the runtime:
- `CustomerIdHook` (`agent/ledgerlens/tools/customer_id_hook.py`) overwrites `customer_id` on every tool call with the token's value, whatever the model wrote. When the token's `customer_id` is blank, it cancels the call instead.
- `ConfirmationHook` (`agent/ledgerlens/tools/confirmation_hook.py`) pauses `block_credit_card`, `open_claim` and `human_agent_hand_off` until the customer taps Yes. Only then does it set `customer_confirmed` to `true` on the first two.

So in normal use Cedar never has to deny anything. It is the backstop if the agent code is wrong or bypassed. Details: [Cedar Policy Guide](CEDAR_POLICY_GUIDE.md).

## How the agent connects

`create_gateway_mcp_client()` in `agent/ledgerlens/tools/gateway.py` builds a Strands `MCPClient`:

```python
def create_gateway_mcp_client(access_token: str) -> MCPClient:
    stack_name = os.environ.get("STACK_NAME")
    ...
    gateway_url = get_ssm_parameter(f"/{stack_name}/gateway_url")

    return MCPClient(
        lambda: streamablehttp_client(
            url=gateway_url,
            headers={"Authorization": f"Bearer {access_token}"},
        ),
        prefix="gateway",
    )
```

`invocations()` in `agent/ledgerlens/ledgerlens_agent.py` fetches the token once per request with `get_gateway_access_token(user_id)` and reads `customer_id` from it. The same token goes to the MCP client, so the `customer_id` the agent passes always matches the one Cedar checks. The agent is rebuilt on every invocation, and a Cognito token outlives one invocation, so a reconnection within a request never uses an expired token.

The agent passes only this client as its tools (`tools = [gateway_client]`); tools from an AWS Agent Registry are added only when `mcp_registry.enabled` is true, and it is false.

`gateway.py` also keeps a commented-out alternative that gets the token from the AgentCore Token Vault. That token can't carry `customer_id`, so it would break access to every tool. See [IDENTITY_POLICY.md, Two authentication approaches](IDENTITY_POLICY.md#two-authentication-approaches).

## Testing the Gateway directly

`test-scripts/test-gateway.py` calls the Gateway without the agent or the frontend. It acts as a Cognito user: it passes `--user-sub` as `aws_client_metadata`, the same way the agent does, so the token carries that user's `customer_id`.

```bash
pip install -r test-scripts/requirements.txt
export AWS_PROFILE=ledgerlens

python test-scripts/test-gateway.py                          # token with no user claims
python test-scripts/test-gateway.py --user-sub <sub>         # list the tools this login can see
python test-scripts/test-gateway.py --user-sub <sub> --customer-id <customer_id>   # also call list_credit_cards
```

The script:
1. Reads the stack name from `infra-cdk/config.yaml`.
2. Reads `gateway_url`, `machine_client_id` and `cognito_provider` from SSM, and the client secret from Secrets Manager.
3. Gets a client credentials token from `https://<cognito_provider>/oauth2/token`.
4. Calls `tools/list` and prints the tool names.
5. With `--customer-id`, calls `list_credit_cards` only, and exits with code 1 if the call is refused or fails.

What to expect:

| Arguments | `customer_id` claim | Result |
|---|---|---|
| none | absent (no custom claims at all) | No tools listed |
| `--user-sub` not in `USER_CUSTOMER_IDS_MAP` | blank | No tools listed |
| `--user-sub` in the map | the mapped customer | The 9 tools listed |
| ... `--customer-id` = that customer | same | The customer's cards |
| ... `--customer-id` = another customer | different | Denied by Cedar statement 2 |

## Adding a tool

Follow [DEPLOYMENT.md, Updating](DEPLOYMENT.md#updating). In short:
1. Add `gateway/tools/<tool>/` with `tool_spec.json` and `<tool>_lambda/delivery/handler.py`, following the [contract](#tool-lambda-contract). Make `customer_id` a required input.
2. Add an entry to `toolTargets` in `backend-construct.ts`, with `role: readRole` or `writeRole` if it uses DSQL.
3. Add the `<target>___<tool>` action to statements 1 and 2 in `policy.cedar`, and to statement 3 if it writes.
4. Add the tool to `TARGETS` in `infra-cdk/test/backend-gateway.test.ts` and run `npm test` in `infra-cdk`.
5. Deploy the main stack: `AWS_PROFILE=ledgerlens python scripts/deploy-with-codebuild.py ledgerlens-bank-assistant`.

Steps 2 and 3 go together:
- A target that isn't in the policy is denied by Cedar and hidden from `tools/list`.
- A policy action without a target makes `CreatePolicy` fail, and the deploy rolls back.

The test in step 4 catches both before you deploy.

## Logs

| What | Log group |
|---|---|
| Tool Lambdas | `/aws/lambda/ledgerlens-bank-assistant-<slug>` |
| Cedar custom resource | `/aws/lambda/ledgerlens-bank-assistant-cedar-policy` |
| OAuth2 provider custom resource | `/aws/lambda/ledgerlens-bank-assistant-oauth2-provider` |
| Pre-token Lambda (`[PRE-TOKEN]` lines) | `/aws/lambda/ledgerlens-bank-assistant-pretoken-v3` |
| Agent (`[GATEWAY]` and `[CUSTOMER-ID]` lines) | `/aws/bedrock-agentcore/runtimes/<runtime-id>-DEFAULT` |

`infra-cdk` configures no log or trace delivery for the Gateway itself. To see Cedar's allow and deny decisions, turn on tracing in the console: see [Verifying policy decisions via tracing](IDENTITY_POLICY.md#verifying-policy-decisions-via-tracing).

## Troubleshooting

**No tools listed, or the agent says the account isn't linked.** The login's `sub` isn't in `USER_CUSTOMER_IDS_MAP`, or a redeploy reset the map to its committed value. Check with `test-gateway.py --user-sub <sub>`, and link the login as in [DEPLOYMENT.md](DEPLOYMENT.md#5-create-logins-and-link-them-to-customers).

**401 from the Gateway.** The token wasn't issued to the machine client, has expired, or comes from another user pool.

**A tool returns "This function only serves the '...' tool".** The Lambda behind that target received a different tool name. Check `toolTargets` against the `name` in `tool_spec.json`.

**Bedrock rejects every request.** A tool name the model sees is over 64 characters. Shorten that tool's target name.

**The deploy fails at `GatewayPolicy`.** `CreatePolicy` rejected a statement. The usual causes are an action whose target doesn't exist, or a `forbid` that doesn't list its actions ("Overly Restrictive"). The error is in `/aws/lambda/ledgerlens-bank-assistant-cedar-policy`.

**Tools fail with connection or "table does not exist" errors.** A data load is running, or the cluster was never loaded. See [DEPLOYMENT.md, Troubleshooting](DEPLOYMENT.md#troubleshooting).

**The Gateway returns "An internal error occurred".** Set the Gateway's exception level to `DEBUG` to see detailed errors. In CDK, add one property to the `agentcore.Gateway` props and deploy:

```typescript
exceptionLevel: agentcore.GatewayExceptionLevel.DEBUG,
```

Or with the CLI. `update-gateway` replaces the whole configuration, and leaving out `--policy-engine-configuration` detaches Cedar: that is exactly how the cedar-policy Lambda detaches the engine on stack delete. Copy every field from `get-gateway` first:

```bash
aws bedrock-agentcore-control get-gateway --gateway-identifier <gateway-id>

aws bedrock-agentcore-control update-gateway \
  --gateway-identifier <gateway-id> \
  --name ledgerlens-bank-assistant-gateway \
  --role-arn <roleArn> \
  --protocol-type MCP \
  --authorizer-type CUSTOM_JWT \
  --authorizer-configuration '<authorizerConfiguration JSON>' \
  --policy-engine-configuration '{"arn": "<policy-engine-arn>", "mode": "ENFORCE"}' \
  --exception-level DEBUG
```

Debug steps that usually find the problem:
1. Run `test-gateway.py` with and without `--customer-id`, to separate auth, Cedar and Lambda failures.
2. Read the tool Lambda's log group.
3. Invoke the tool Lambda directly with a test event, setting `bedrockAgentCoreToolName` in the client context.

## Related documentation

- [Cedar Policy Guide](CEDAR_POLICY_GUIDE.md): the three statements, how they are deployed, Cedar reference
- [Identity Propagation & Cedar Policy](IDENTITY_POLICY.md): how the user's `sub` becomes the `customer_id` claim
- [Runtime-Gateway Authentication](RUNTIME_GATEWAY_AUTH.md): the machine token flow
- [Replacing Cognito](REPLACING_COGNITO.md): swapping the identity provider, Gateway interceptors
- [Deployment Guide](DEPLOYMENT.md): deploy, tool table, adding a tool
- [AWS: AgentCore Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html)
- [AWS: Lambda targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-lambda.html)
