# Identity Propagation & Cedar Policy

This page explains how the signed-in user's identity reaches the AgentCore Gateway, so Cedar can limit every tool call to that user's own customer. The code comments in `infra-cdk/lambdas/pretoken-v3/index.py` and `infra-cdk/lib/cognito-construct.ts` point here.

## Overview

The Gateway authenticates with a machine token: the agent gets it from Cognito with the client credentials grant. On its own, that token carries no user, so every call would look the same to the Gateway.

LedgerLens adds the user to that token:
1. When the agent asks Cognito for the machine token, it passes the user's Cognito `sub` as `aws_client_metadata`.
2. The V3 pre-token Lambda looks the `sub` up in `USER_CUSTOMER_IDS_MAP` and adds a `customer_id` claim to the token.
3. Cedar at the Gateway compares the tool's `customer_id` argument with that claim.

The result: access is per customer. A login can read and act on its linked customer only, and a login with no linked customer gets no tools.

## What is AgentCore Policy?

AgentCore Policy decides, on every tool call, whether the agent may make it. You write the rules as [Cedar](https://www.cedarpolicy.com/) policies; the policy engine applies them at the Gateway.
- If no rule allows an action, it is denied (deny-by-default).
- The decision is deterministic: unlike instructions in a prompt, a clever message can't talk its way past it.

| Capability | Example rule | Used in LedgerLens? |
|---|---|---|
| Claim-based access | "Only a login linked to a customer can use the tools" | Yes, statement 1 |
| Input validation | "The `customer_id` argument must match the token" | Yes, statements 2 and 3 |
| Multi-tool policies | One rule for a list of tools | Yes, `action in [...]` |
| Environment isolation | "Only the production runtime can use production tools" | No (see [Runtime-level access control](#runtime-level-access-control)) |

See the [Cedar Policy Guide](CEDAR_POLICY_GUIDE.md) for the full policy and the syntax reference.

Key concepts:
- **Policy engine:** evaluates the Cedar policies. One engine is attached to the Gateway.
- **Cedar policy:** one declarative rule. LedgerLens has three, one per statement in `policy.cedar`.
- **Custom JWT authorizer:** the Gateway component that validates the token and maps its claims to Cedar principal tags.
- **Tool filtering:** tools a caller can't use are hidden from `tools/list`, not only blocked at call time. See [Tool discovery vs execution](CEDAR_POLICY_GUIDE.md#tool-discovery-vs-execution).

## Flow

```
1. User signs in → the frontend gets a JWT from Cognito (web client)
2. Frontend calls the runtime → its JWT authorizer validates the token;
   the Authorization header is allowlisted, so the agent can read it
3. extract_user_id_from_context() reads the sub claim
4. get_gateway_access_token(sub) → POST https://<cognito_provider>/oauth2/token
       grant_type=client_credentials
       aws_client_metadata={"verified_user_id": "<sub>"}
5. Cognito runs the V3 pre-token Lambda → customer_id = USER_CUSTOMER_IDS_MAP[sub] or ""
6. extract_customer_id_from_token() reads customer_id from that same token
       → system prompt, CustomerIdHook
7. The agent calls tools through the Gateway with that token
       → JWT authorizer → Cedar (customer_id claim vs context.input) → tool Lambda
```

Security properties:
- The `sub` comes from the token the runtime already validated, never from the model or the request body.
- The `customer_id` comes from the machine token, never from the model. The model is told which id to pass, but `CustomerIdHook` overwrites whatever it writes, and Cedar checks it again.

## Components

### Cognito Essentials tier

**File:** `infra-cdk/lib/cognito-construct.ts`

The user pool uses `featurePlan: ESSENTIALS`. V3 pre-token triggers fire on client credentials grants only on the Essentials tier (or higher). Without it, the Lambda wouldn't run for the machine token and no `customer_id` would be added.

The CDK `UserPool.addTrigger()` supports only trigger versions V1 and V2, so the construct sets `LambdaConfig.PreTokenGenerationConfig` with `LambdaVersion: "V3_0"` through an L1 property override.

### V3 pre-token Lambda

**File:** `infra-cdk/lambdas/pretoken-v3/index.py`, deployed as `ledgerlens-bank-assistant-pretoken-v3`.

It fires on every token Cognito issues and acts only on client credentials grants (`TokenGeneration_ClientCredentials`). For those:
- With no `verified_user_id` in `clientMetadata`, it returns the event unchanged: the token gets **no** custom claims.
- Otherwise it adds four claims through `claimsToAddOrOverride`:

| Claim | Value | Used by |
|---|---|---|
| `customer_id` | `USER_CUSTOMER_IDS_MAP[sub]`, or `""` | Cedar statements 1 and 2, the agent |
| `user_id` | The user's `sub` | Nothing |
| `department` | Always `"guest"` | Nothing |
| `role` | Always `"viewer"` | Nothing |

`department` and `role` come from the template the project started from. `USER_ROLE_MAP` maps `sub` values to them, but it holds only placeholder keys (`<fastprojectadmin-user-sub-uuid>`, `<fastuser-user-sub-uuid>`). So every user gets `DEFAULT_GROUP`, guest/viewer. The "two-step deployment" in the Lambda's docstring is about filling `USER_ROLE_MAP`; for LedgerLens, the mapping that matters is `USER_CUSTOMER_IDS_MAP`.

`customer_id` is `""` when:
- `USER_CUSTOMER_IDS_MAP` is missing or blank, isn't valid JSON, or isn't a JSON object;
- the `sub` has no entry;
- the entry isn't a string.

The token is still issued in every case. Cedar then denies the tools. The Lambda logs which case applied (`[PRE-TOKEN] ...` lines), but never the `sub` or the customer id.

### USER_CUSTOMER_IDS_MAP

The Lambda's `USER_CUSTOMER_IDS_MAP` environment variable is a JSON object, as a string, from Cognito `sub` to customer id:

```json
{"<cognito-sub>": "CLI-50OIF5EIYSWK", "<another-sub>": "CLI-70U0WJ1NH1MN"}
```

- **Where it is set:** hard-coded in `cognito-construct.ts`. It holds 15 subs today (the demo, evaluation and judge logins); several map to the same customer.
- **Console edits:** a change in the Lambda console applies to the next token. The agent fetches a new token on every request, so the next message already uses it. This is how the demo login switches personas.
- **Redeploys:** a deploy of the main stack resets the variable to the committed value. Subs added only in the console are lost.

To link a new login: create the user, find its `sub`, add it to the map in `cognito-construct.ts`, commit, and deploy the main stack. The full steps, including the evaluation logins, are in [DEPLOYMENT.md, Create logins and link them to customers](DEPLOYMENT.md#5-create-logins-and-link-them-to-customers).

To find a login's `sub`:

```bash
aws cognito-idp list-users --profile ledgerlens --user-pool-id <pool-id> \
  --filter 'email = "demo@ledgerlens.example"' \
  --query "Users[0].Attributes[?Name=='sub'].Value" --output text
```

### Cedar policy file

**File:** `gateway/policies/policy.cedar`. One file, three statements:
1. Permit the 9 tools when `customer_id` is present and non-empty.
2. Forbid a call whose `customer_id` argument differs from the claim.
3. Forbid `block_credit_card` and `open_claim` unless `customer_confirmed` is `true`.

CDK strips the `//` comment lines and replaces `{{GATEWAY_ARN}}` at synth time. The custom resource creates one AgentCore policy per statement. See the [Cedar Policy Guide](CEDAR_POLICY_GUIDE.md#the-ledgerlens-policy) for the statements and why each is written the way it is.

### Policy engine custom resource

**Files:**
- `infra-cdk/lambdas/cedar-policy/index.py`: the custom resource Lambda
- `infra-cdk/lib/backend-construct.ts`: the `GatewayPolicy` custom resource, in `createAgentCoreGateway()`

The Lambda handles three CloudFormation events:
- **Create:** creates the engine `ledgerlens_bank_assistant_policy_engine`, one policy per statement, then attaches the engine to the Gateway in `ENFORCE` mode.
- **Update:** deletes the policies it manages, creates one per statement from the new document, and re-attaches the engine if it was detached. The engine is kept.
- **Delete:** detaches the engine, deletes the policies, deletes the engine.

It waits with the boto3 waiters `policy_engine_active`, `policy_engine_deleted`, `policy_active` and `policy_deleted`. Gateway status changes have no waiter, so it polls until the Gateway is `READY` (up to 5 minutes).

### Gateway authorizer

**File:** `infra-cdk/lib/backend-construct.ts`

```typescript
authorizerConfiguration: agentcore.GatewayAuthorizer.usingCustomJwt({
  discoveryUrl: cognitoDiscoveryUrl,
  allowedClients: [this.machineClient.userPoolClientId],
}),
```

It accepts only tokens issued to the machine client and maps their claims to Cedar principal tags:

| JWT claim | Cedar | Read by the policy? |
|---|---|---|
| `customer_id` | `principal.getTag("customer_id")` | Yes |
| `user_id` | `principal.getTag("user_id")` | No |
| `department` | `principal.getTag("department")` | No |
| `role` | `principal.getTag("role")` | No |

### Agent side: system prompt and hooks

The agent uses the same `customer_id` as Cedar, read from the same token:
- `build_system_prompt(customer_id, ...)` in `agent/ledgerlens/tools/system_prompt.py` tells the model the customer's id. With `""`, it uses a different block for a user with no linked customer.
- `CustomerIdHook` (`agent/ledgerlens/tools/customer_id_hook.py`) runs before every tool call whose schema has a `customer_id` property. It overwrites the argument with the token's value. With `""`, it cancels the call with "This user's account is not linked to a customer, so customer data can't be looked up."
- `ConfirmationHook` (`agent/ledgerlens/tools/confirmation_hook.py`) sets `customer_confirmed` to `true` on `block_credit_card` and `open_claim` only after the customer taps Yes.

Why both the hooks and Cedar: the hooks make the normal path correct and give the model a clear message. Cedar enforces the same rules even if the agent code has a bug or is bypassed.

## Two authentication approaches

`agent/ledgerlens/tools/gateway.py` holds two ways to get the Gateway token. Only the first is active.

> **Replacing Cognito?** For swapping Cognito for another identity provider, or using Gateway interceptors instead of Cedar, see [Replacing Cognito](REPLACING_COGNITO.md).

### Approach 1 (active): direct Cognito call

- `get_gateway_access_token(user_id: str) -> str` in `agent/utils/auth.py` calls the Cognito `/oauth2/token` endpoint with `aws_client_metadata`. The pre-token Lambda reads that metadata and adds `customer_id`.
- `extract_customer_id_from_token(access_token: str) -> str` reads the claim back.
- `create_gateway_mcp_client(access_token: str) -> MCPClient` in `gateway.py` uses the same token for the Gateway.

**Why:** it is the only way to get user claims into the machine token. Cedar needs them.

**Trade-off:** the runtime needs outbound HTTPS to the Cognito domain. The deployed runtime is in PUBLIC network mode, so it has it. In VPC mode it needs a NAT gateway (see [VPC mode](#vpc-mode)).

### Approach 2 (commented out): `@requires_access_token`

The commented code uses the AgentCore Identity SDK decorator. The decorator gets the token from the Token Vault through the OAuth2 credential provider `ledgerlens-bank-assistant-runtime-gateway-auth`, with caching and refresh built in. The stack still deploys that provider and the runtime's `GATEWAY_CREDENTIAL_PROVIDER_NAME` variable, but nothing uses them.

The decorator can't pass `aws_client_metadata`. So in LedgerLens, switching to it breaks every tool:
1. The pre-token Lambda sees no `verified_user_id` and adds no claims, so the token has no `customer_id`.
2. Cedar statement 1 doesn't match, so `tools/list` returns nothing and every call is denied.
3. The agent reads `""` as the customer id, so `CustomerIdHook` cancels every call (all 9 tools take `customer_id`).

Use it only if access control moves somewhere else, for example to Gateway interceptors (see [Replacing Cognito](REPLACING_COGNITO.md)).

### Switching from Approach 1 to Approach 2

The steps from `gateway.py`'s docstring:
1. Uncomment the decorator-based `_fetch_gateway_token()`.
2. Comment out the Approach 1 `create_gateway_mcp_client(access_token)`.
3. Uncomment the Approach 2 `create_gateway_mcp_client()` (no parameter).
4. In `invocations()` in `agent/ledgerlens/ledgerlens_agent.py`, stop fetching and passing the token. The agent then has no `customer_id`.
5. Check that `GATEWAY_CREDENTIAL_PROVIDER_NAME` is set in the runtime's environment. `createAgentCoreRuntime()` in `backend-construct.ts` already sets it.

## Customization

### Replacing the user-to-customer mapping

`USER_CUSTOMER_IDS_MAP` is a demo shortcut: every new login needs a code change and a deploy. In `pretoken-v3/index.py`, replace `_lookup_customer_id()` with a real lookup:
- **DynamoDB table:** partition key `sub`, attribute `customer_id`. The Lambda queries it with the `verified_user_id` from `clientMetadata`. Linking a login then needs no deploy. Grant the Lambda's role read access to the table.
- **Email-based lookup:** resolve the user's email from the `sub` with the Cognito `ListUsers` API, then map the email to a customer. This needs `cognito-idp:ListUsers` on the Lambda's role. Prefer the `sub`: it is immutable and isn't PII.
- **The bank's own directory:** call the customer system with the `sub` as the key.

Keep two behaviours whatever you choose:
- Return `""` when there is no customer, so Cedar denies.
- Don't fail the token request. The Lambda never raises today.

### Using department and role

To use `department` and `role` in Cedar, replace the placeholder keys in `USER_ROLE_MAP` with real `sub` values, deploy, and add conditions on `principal.getTag("department")` or `principal.getTag("role")`. Remember that every statement change goes through `CreatePolicy` validation at deploy.

### Adding new claims

1. Add the claim to `claimsToAddOrOverride` in the pre-token Lambda.
2. Read it in Cedar with `principal.getTag("claim_name")`.
3. No Gateway change is needed: the custom JWT authorizer maps all claims to tags.

### VPC mode

In VPC mode, Approach 1 needs a **NAT gateway**: the Cognito `/oauth2/token` domain is a public HTTPS endpoint with no VPC endpoint.

Approach 2 doesn't: AgentCore Identity exchanges the token on the AWS side, reachable through the `bedrock-agentcore` VPC endpoint. But see above for why Approach 2 breaks LedgerLens.

See [DEPLOYMENT.md, VPC mode](DEPLOYMENT.md#appendix-vpc-mode-for-the-runtime).

### Runtime-level access control

LedgerLens has one runtime and one machine client. If you ever run several runtimes against one Gateway and need to control which runtime may use which tools, use the Cognito `clientId` as the runtime's identity. This pattern is not implemented here.

**Why not `context.runtime.arn` in Cedar?** The schema has no such field, so policy creation would fail.

**Why not Cognito groups?** Groups apply to users, not app clients. A client credentials token never has `cognito:groups`.

**Solution: one Cognito machine client per runtime.** The `clientId` is verified by the client secret, so the runtime can't fake it. The pre-token Lambda maps the `clientId` to a `runtime_env` claim:

```
Runtime A (production) → client A + secret A → Cognito verifies clientId "abc123"
                       → pre-token Lambda: "abc123" → runtime_env "production"
Runtime B (staging)    → client B + secret B → Cognito verifies clientId "def456"
                       → pre-token Lambda: "def456" → runtime_env "staging"
```

What changes:
1. **Machine clients:** create one per runtime in `createMachineAuthentication()` in `backend-construct.ts`, each with the same resource server scopes. Add every client to the Gateway's `allowedClients`.
2. **Mapping:** pass `{clientId: runtime_env}` to the pre-token Lambda, for example as a `CLIENT_RUNTIME_MAP` environment variable. The Lambda is created in `cognito-construct.ts`, so the client IDs must be passed into that construct.
3. **Pre-token Lambda:** read `event["callerContext"]["clientId"]`, look it up, and add `runtime_env` to `claimsToAddOrOverride` next to `customer_id`:

```python
client_id = event["callerContext"]["clientId"]  # verified by Cognito
client_runtime_map = json.loads(os.environ.get("CLIENT_RUNTIME_MAP", "{}"))
runtime_env = client_runtime_map.get(client_id, "unknown")
```

4. **Cedar:** add `principal.hasTag("runtime_env") && principal.getTag("runtime_env") == "production"` to the `permit` (see [Capability 5](CEDAR_POLICY_GUIDE.md#capability-5-environment-based-access-control)).

Two layers of identity result:

| Layer | Claim | Source | Trust |
|---|---|---|---|
| Runtime | `runtime_env` | `callerContext.clientId` | Cryptographic: needs the client secret |
| User | `customer_id`, `user_id` | `clientMetadata.verified_user_id`, the `sub` from the runtime-validated user JWT | JWT-verified, extracted server-side by `extract_user_id_from_context()` |

## Verifying the deployed policy

In the console:
1. Open **Amazon Bedrock AgentCore → Policy**.
2. Open the policy engine `ledgerlens_bank_assistant_policy_engine`.
3. Under **Policies** there are three, one per statement: `ledgerlens_bank_assistant_polic_cp1_<timestamp>`, `_cp2_`, `_cp3_`.
4. Each policy's **Definition** shows the effect (`permit` or `forbid`), the principal (`AgentCore::OAuthUser`), the actions, the Gateway and the conditions. The **Cedar** section shows the statement as deployed.

From the CLI:

```bash
export AWS_PROFILE=ledgerlens
aws bedrock-agentcore-control list-policies --policy-engine-id <PolicyEngineId>
aws bedrock-agentcore-control get-gateway --gateway-identifier <GatewayId> \
  --query policyEngineConfiguration   # should show the engine ARN and "mode": "ENFORCE"
```

`PolicyEngineId` and `GatewayId` are main stack outputs. The `CedarPolicyId` output is the ID of the first policy only.

## Verifying policy decisions via tracing

CDK doesn't turn on tracing for the runtime or the Gateway. To see Cedar's decisions, turn it on in the console. Trace delivery also needs CloudWatch Transaction Search (see [OBSERVABILITY.md](OBSERVABILITY.md)).

1. Go to **Amazon Bedrock AgentCore → Runtimes** and open `ledgerlens_bank_assistant_ledgerlens_agent`.
2. Under **Tracing**, choose **Edit** and enable tracing.
3. Go to **Amazon Bedrock AgentCore → Gateways**, open `ledgerlens-bank-assistant-gateway`, and enable tracing the same way.
4. Send a message from the frontend that makes the agent call a tool.
5. In **CloudWatch → Log groups**, open `aws/spans` and its default log stream.
6. Filter events for `policy`.
7. Find the `AgentCore.Policy.PartiallyAuthorizeActions` span. It has:
    - `aws.agentcore.policy.allowed_tools`: tools the login may use
    - `aws.agentcore.policy.denied_tools`: tools it may not
    - `aws.agentcore.gateway.policy.mode`: should be `ENFORCE`

For a quicker check without tracing, run `python test-scripts/test-gateway.py --user-sub <sub>` (see [GATEWAY.md](GATEWAY.md#testing-the-gateway-directly)).
