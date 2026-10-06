# Cedar Policy Guide

This guide covers the Cedar policy that controls the LedgerLens Gateway tools: what it says, how it is deployed, and how to change it safely. The second half is a general reference for writing Cedar policies for AgentCore Gateway.

For how the signed-in user's identity becomes the `customer_id` claim the policy reads, see [Identity Propagation & Cedar Policy](IDENTITY_POLICY.md).

## The LedgerLens policy

`gateway/policies/policy.cedar` holds three statements. Together they say: a login can use the tools only for its own linked customer, and the two write tools need the customer's explicit confirmation.

### Statement 1: permit a linked customer

```cedar
permit(
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"list-credit-cards-target___list_credit_cards",
    AgentCore::Action::"list-card-transactions-target___list_card_transactions",
    AgentCore::Action::"get-session-context-target___get_session_context",
    AgentCore::Action::"fraud-detection-target___transaction_fraud_detection",
    AgentCore::Action::"explain-transaction-target___explain_transaction",
    AgentCore::Action::"classify-call-type-target___classify_call_type",
    AgentCore::Action::"block-credit-card-target___block_credit_card",
    AgentCore::Action::"open-claim-target___open_claim",
    AgentCore::Action::"human-agent-hand-off-target___human_agent_hand_off"
  ],
  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"
)
when { principal.hasTag("customer_id") && principal.getTag("customer_id") != "" };
```

The pre-token Lambda sets `customer_id` to `""` for a login that isn't linked to a customer, and adds no claims at all to a token requested without a user. Neither matches, so Cedar's default deny applies and that login gets no tools.

### Statement 2: forbid another customer's data

```cedar
forbid(
  principal is AgentCore::OAuthUser,
  action in [ /* the same 9 actions */ ],
  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"
)
when {
  principal.hasTag("customer_id") &&
  context.input.customer_id != principal.getTag("customer_id")
};
```

- **Why:** the model writes the tool arguments, and a prompt injection could ask it for another customer's data. This statement makes that impossible at the Gateway, whatever the agent sends.
- **Why the actions are listed:** AgentCore rejects a `forbid` over all actions (a bare `action`) as "Overly Restrictive", because it would also cover tools that don't exist yet.
- **No `has` guard on `customer_id`:** every listed tool requires `customer_id` in its `tool_spec.json`.

### Statement 3: forbid unconfirmed writes

```cedar
forbid(
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"block-credit-card-target___block_credit_card",
    AgentCore::Action::"open-claim-target___open_claim"
  ],
  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"
)
when {
  !(context.input has customer_confirmed) ||
  context.input.customer_confirmed != true
};
```

- **Why:** blocking a card and opening a claim change the customer's account, so they need the customer's explicit Yes. The agent's `ConfirmationHook` sets `customer_confirmed` to `true` only after the customer taps Yes in the chat.
- **Why the `has` guard matters:** without it, a call that omits `customer_confirmed` makes the condition fail to evaluate. Cedar skips a `forbid` whose condition errors, so the call would be **allowed**. `!(context.input has customer_confirmed) ||` makes a missing argument a denial.

### How they combine

Cedar is deny-by-default, and a matching `forbid` always wins over a `permit`.

| Token `customer_id` | Call | Result |
|---|---|---|
| absent or `""` | any tool | Denied (no permit matches); hidden from `tools/list` |
| `CLI-A` | `list_credit_cards(customer_id="CLI-A")` | Allowed |
| `CLI-A` | `list_credit_cards(customer_id="CLI-B")` | Denied by statement 2 |
| `CLI-A` | `block_credit_card(customer_id="CLI-A", customer_confirmed=false, ...)` | Denied by statement 3 |
| `CLI-A` | `block_credit_card(customer_id="CLI-A", customer_confirmed=true, ...)` | Allowed |

The agent already applies the first three rows itself: `CustomerIdHook` overwrites `customer_id` with the token's value and cancels the call when it is blank. Cedar is the backstop for when the agent code is wrong or bypassed.

## How the policy is deployed

### From file to policies

1. `createAgentCoreGateway()` in `infra-cdk/lib/backend-construct.ts` reads `policy.cedar` at synth time. It drops every line that starts with `//` and replaces `{{GATEWAY_ARN}}` with the Gateway's ARN.
2. The result goes to the `GatewayPolicy` custom resource as `PolicyDocument`.
3. The custom resource Lambda (`infra-cdk/lambdas/cedar-policy/index.py`) splits the document into statements with `split_cedar_statements()`. It splits on the semicolons that end statements, skips semicolons inside strings and `//` comments, and fails if text is left after the last semicolon. `CreatePolicy` takes one statement per policy, so each statement becomes its own policy.

### Lifecycle

| CloudFormation event | What the Lambda does |
|---|---|
| Create | Creates the engine `ledgerlens_bank_assistant_policy_engine`, one policy per statement, then attaches the engine to the Gateway in `ENFORCE` mode |
| Update (the file changed) | Deletes every policy it manages, creates one per statement again, and re-attaches the engine if a failed rollback detached it. The engine itself is kept. |
| Delete | Detaches the engine from the Gateway, deletes the policies, deletes the engine |

Notes:
- **Same `PhysicalResourceId` on update.** An update returns the ID that Create returned, so CloudFormation doesn't treat it as a replacement. A replacement would run Delete on the old resource and detach Cedar from the Gateway.
- **Brief deny-all during an update.** Between deleting the old policies and activating the new ones, the engine has no `permit`, so every tool call is denied. Don't deploy a policy change during a demo.
- **Policy names.** The API limits names to 48 characters. Names are `<engine name, first 31 characters>_cp<n>_<unix time>`: `ledgerlens_bank_assistant_polic_cp1_<ts>`, `_cp2_`, `_cp3_`. On update, the Lambda also deletes policies named with the older `<engine>_cp_<ts>` format.
- **Order.** The custom resource depends on every Gateway target, because `CreatePolicy` fails for an action whose target doesn't exist yet.
- **Why a custom resource.** The project manages the engine and policies with a custom resource Lambda. `aws-cdk-lib` 2.260 (the version in `infra-cdk/package.json`) also has `CfnPolicyEngine` and `CfnPolicy` L1 constructs, which the project doesn't use.

To apply a change, edit `policy.cedar` and deploy the main stack:

```bash
AWS_PROFILE=ledgerlens python scripts/deploy-with-codebuild.py ledgerlens-bank-assistant
```

### What catches mistakes

**Before deploy:** `cd infra-cdk && npm test`. Synthesizing the main stack takes about 2 minutes.
- `infra-cdk/test/policy-cedar.test.ts` checks that every `forbid` lists its actions, and that statement 3 covers both write tools with the `has` guard.
- `infra-cdk/test/backend-gateway.test.ts` checks that the policy's actions are exactly the deployed targets with their `tool_spec.json` names, and that the policy waits for every target.

**At deploy:** `CreatePolicy` validates each statement against the Gateway's tools. A rejected statement fails the deploy and CloudFormation rolls back; nothing is silently denied. Causes seen or documented:
- an action whose target doesn't exist;
- a `forbid` over all actions ("Overly Restrictive");
- a reference to a field the tool schema doesn't have.

The error is in `/aws/lambda/ledgerlens-bank-assistant-cedar-policy`.

**What the deploy doesn't catch:** a tool in `toolTargets` but missing from statement 1 deploys fine, and Cedar then denies it for everyone. Only the `backend-gateway` test catches that, so run it.

## Action name format

Cedar action names are `<TargetName>___<tool_name>` (three underscores):
- `TargetName` is the `gatewayTargetName` from `toolTargets` in `backend-construct.ts`: `<slug>-target`, or the override (`fraud-detection-target`).
- `tool_name` is the `name` in the tool's `tool_spec.json`.
- Combined: `list-credit-cards-target___list_credit_cards`.

Names are case-sensitive.

## Claims available to Cedar

Cedar reads JWT claims with `principal.getTag("claim_name")`. The Gateway's custom JWT authorizer maps the token's claims to principal tags, so a new claim needs no Gateway change.

### Custom claims (added by the pre-token Lambda)

The V3 pre-token Lambda (`infra-cdk/lambdas/pretoken-v3/index.py`) adds these through `claimsToAddOrOverride`, but only when the token request carried a `verified_user_id`:

| Claim | Value | Used by the policy |
|---|---|---|
| `customer_id` | The customer linked to the login in `USER_CUSTOMER_IDS_MAP`, or `""` | Yes: statements 1 and 2 |
| `user_id` | The user's Cognito `sub` | No |
| `department` | Always `"guest"` | No |
| `role` | Always `"viewer"` | No |

`department` and `role` come from the template the project started from. Their map (`USER_ROLE_MAP`) holds only placeholder keys, so every user gets the default. See [IDENTITY_POLICY.md](IDENTITY_POLICY.md#v3-pre-token-lambda).

To add a claim, put it in the Lambda's `claimsToAddOrOverride` dict and read it with `principal.getTag("claim_name")`. Other claim ideas:

| Claim | Use case | Cedar usage |
|---|---|---|
| `tenant_id` | Multi-tenant isolation | `principal.getTag("tenant_id") == "example-corp"` |
| `clearance_level` | Tiered data access | `principal.getTag("clearance_level") == "top-level"` |
| `region` | Geo-restricted access | `principal.getTag("region") == "us-east-1"` |
| `runtime_env` | Runtime-level isolation | `principal.getTag("runtime_env") == "production"` |

### Standard claims (set by Cognito)

Cognito adds these to every token. The pre-token Lambda can't override them.

| Claim | Description |
|---|---|
| `sub` | Subject; the app client ID for a machine token |
| `iss` | Token issuer (the user pool URL) |
| `client_id` | The app client ID |
| `token_use` | Always `"access"` |
| `scope` | OAuth scopes granted |
| `exp` / `iat` / `jti` | Token timing and ID |

They are also tags, but they suit infrastructure checks better than business rules.

### What isn't available as a claim

| Data | Why | Alternative |
|---|---|---|
| Request headers, IP | Not exposed to Cedar | None |
| Runtime ARN | Not in the Cedar schema | A `runtime_env` claim (see [Runtime-level access control](IDENTITY_POLICY.md#runtime-level-access-control)) |
| Tool input | Not a claim | `context.input.<field>` |

## Deny-by-default

If no `permit` matches a request, Cedar denies it. You don't need a `forbid` to keep someone out: leave them out of the `permit`. That is how an unlinked login is blocked: statement 1 requires a non-empty `customer_id`, and nothing else permits.

Use `forbid` to cut exceptions out of a broad `permit`, as statements 2 and 3 do.

## Tool discovery vs execution

The policy engine checks requests at two points.

### 1. Discovery (`tools/list`): tool filtering

When the agent calls `tools/list`, the engine evaluates every tool against the caller's claims with `PartiallyAuthorizeActions`. Tools the caller can't use are removed from the response, so the agent never sees them.

```
Agent → Gateway tools/list → Policy engine (PartiallyAuthorizeActions)
                                 ↓
                         each tool vs the principal's claims
                                 ↓
                         only permitted tools are returned
```

### 2. Execution (`tools/call`): full context

When the agent calls a tool, the engine evaluates it with `AuthorizeAction`, including the tool's arguments in `context.input`. This is stricter, because it sees the actual request.

```
Agent → Gateway tools/call → Policy engine (AuthorizeAction)
                                 ↓
                         principal's claims + context.input
                                 ↓
                         allow → the Lambda runs
                         deny  → authorization error to the agent
```

### What this means for LedgerLens

- Statement 1 depends only on the principal, so it acts at discovery: an unlinked login's `tools/list` comes back empty.
- Statements 2 and 3 read `context.input`, which exists only on `tools/call`. A linked login sees all 9 tools, and the customer and confirmation checks run when a tool is called.

For example, `block_credit_card` is listed for every linked customer, but a call without `customer_confirmed: true` is denied.

### Summary

| Stage | API | Evaluates | On deny |
|---|---|---|---|
| Discovery (`tools/list`) | `PartiallyAuthorizeActions` | Principal claims only | Tool hidden from the agent |
| Execution (`tools/call`) | `AuthorizeAction` | Principal claims + `context.input` | Call rejected with an authorization error |

### Checking what a login can see

- `python test-scripts/test-gateway.py --user-sub <sub>` prints the `tools/list` result for that login (see [GATEWAY.md](GATEWAY.md#testing-the-gateway-directly)).
- To see the engine's decisions, turn on tracing (see [Verifying policy decisions via tracing](IDENTITY_POLICY.md#verifying-policy-decisions-via-tracing)). Then filter the `aws/spans` log group for `PartiallyAuthorizeActions`. The span has:
  - `aws.agentcore.policy.allowed_tools`: tools returned to the agent
  - `aws.agentcore.policy.denied_tools`: tools filtered out
  - `aws.agentcore.gateway.policy.mode`: should be `ENFORCE`

## Cedar schema constraints

AgentCore validates policies against a schema it builds from the Gateway's tool schemas. A policy that references something outside it fails at `CreatePolicy`, and the deploy rolls back.

**Supported:**

| Element | What it can reference | Example |
|---|---|---|
| `principal` | Must be `AgentCore::OAuthUser` | `principal is AgentCore::OAuthUser` |
| `principal.hasTag()` / `getTag()` | Any JWT claim | `principal.getTag("customer_id")` |
| `action` | Tool actions, `<TargetName>___<tool_name>` | `AgentCore::Action::"open-claim-target___open_claim"` |
| `resource` | The Gateway ARN | `AgentCore::Gateway::"arn:aws:..."` |
| `context.input` | The tool's arguments, as defined in its schema | `context.input.customer_id` |
| `context.system.now` | The request time, for [time-based rules](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-time-based.html) | `context.system.now` |

**Not supported:**

| Element | Why |
|---|---|
| `context.runtime.arn` | Not in the schema |
| Custom entity types | Entities can't be defined outside the `AgentCore` namespace |
| Custom attributes on `OAuthUser` | Use `hasTag()`/`getTag()` instead |
| Request metadata (headers, IP) | Not exposed to Cedar |

If a decision needs data that isn't in `context.input`, add it as a claim in the pre-token Lambda and read it with `principal.getTag()`. [Runtime-level access control](IDENTITY_POLICY.md#runtime-level-access-control) shows this pattern.

## Cedar policy capabilities

This section shows what else Cedar can express for AgentCore Gateway.

> **Already used in `policy.cedar`:**
> - Claim-based access: `principal.getTag("customer_id") != ""` (statement 1)
> - Multi-tool policies: `action in [...]` (all three statements)
> - Input validation against a claim: `context.input.customer_id != principal.getTag("customer_id")` (statement 2)
> - Explicit deny with `forbid` (statements 2 and 3)
> - A presence guard with `has` (statement 3)

The examples below use made-up targets and claims to show more patterns. They work with the same engine.

### Capability 1: input validation (`context.input`)

**Scenario:** finance users can process refunds up to $1000.

`context.input` holds the tool's arguments. The tool still appears in `tools/list` for finance users, because discovery checks only claims. The limit is enforced at `tools/call`.

```cedar
permit(
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"billing-target___process_refund",
  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"
)
when {
  principal.hasTag("department") &&
  principal.getTag("department") == "finance" &&
  context.input.amount < 1000
};
```

- Finance user, amount 500: permitted
- Finance user, amount 5000: denied
- Engineering user, amount 100: denied

### Capability 2: multi-tool policies (`action in [...]`)

**Scenario:** developers can use the read tools but not the write tools.

```cedar
permit(
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"data-target___list_records",
    AgentCore::Action::"data-target___get_record",
    AgentCore::Action::"data-target___search_records"
  ],
  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"
)
when {
  principal.hasTag("role") &&
  principal.getTag("role") == "developer"
};
```

`delete_record` isn't in the list, so it is denied. Separate `permit` statements per tool work too; `action in` just groups tools that share conditions.

### Capability 3: explicit deny (`forbid`)

**Scenario:** block one compromised login from writes, whatever else permits it.

`forbid` overrides `permit`: if both match, the request is denied.

```cedar
forbid(
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"block-credit-card-target___block_credit_card",
    AgentCore::Action::"open-claim-target___open_claim"
  ],
  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"
)
when {
  principal.hasTag("user_id") &&
  principal.getTag("user_id") == "<compromised-user-sub>"
};
```

Deny-by-default often makes this unnecessary. Use `forbid` to override a broad `permit` for specific cases: a compromised user, a tool disabled during an incident, an emergency stop. Remember to list the actions: a `forbid` over all actions is rejected.

### Capability 4: wildcard string matching (`like`)

**Scenario:** only users with an internal email can use internal tools. This needs an `email` claim, which the pre-token Lambda doesn't add today.

```cedar
permit(
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"internal-target___internal_tool",
  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"
)
when {
  principal.hasTag("email") &&
  principal.getTag("email") like "*@example.com"
};
```

- `alice@example.com`: permitted
- `contractor@external.com`: denied

`like` supports only `*`, which matches zero or more characters of any kind. It has no regex, single-character wildcard or character classes.

### Capability 5: environment-based access control

**Scenario:** production tools only from the production runtime, even for a user with the right claims.

The pre-token Lambda maps the Cognito `clientId` to a `runtime_env` claim (see [Runtime-level access control](IDENTITY_POLICY.md#runtime-level-access-control)). Cedar checks both the runtime and the user.

```cedar
permit(
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"prod-target___production_tool",
  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"
)
when {
  principal.hasTag("runtime_env") &&
  principal.getTag("runtime_env") == "production" &&
  principal.hasTag("customer_id") &&
  principal.getTag("customer_id") != ""
};
```

### Quick reference: operators

| Operator | Meaning | Example |
|---|---|---|
| `==` | Equals | `principal.getTag("role") == "admin"` |
| `!=` | Not equals | `principal.getTag("customer_id") != ""` |
| `&&` | AND | `condition_a && condition_b` |
| `\|\|` | OR | `value == "a" \|\| value == "b"` |
| `!` | NOT | `!(context.input has customer_confirmed)` |
| `<`, `>`, `<=`, `>=` | Numeric comparison | `context.input.amount < 1000` |
| `in [...]` | Action is one of a set | `action in [Action::"a", Action::"b"]` |
| `like` | Wildcard string match | `principal.getTag("email") like "*@example.com"` |
| `hasTag()` | Claim exists in the token | `principal.hasTag("customer_id")` |
| `getTag()` | Claim value | `principal.getTag("customer_id")` |
| `has` | Field exists | `context.input has customer_confirmed` |
| `.contains()` | Set membership | `["US", "CA", "MX"].contains(context.input.country)` |

### What Cedar can't do

| Limitation | Workaround |
|---|---|
| Regular expressions | `like` with `*` for simple patterns |
| Division and floating-point math | Compute it in the pre-token Lambda or the tool |
| External data lookups (e.g. a database query) | Resolve it in the pre-token Lambda and add a claim, as `customer_id` is |
| Dynamic lists ("user in a list stored somewhere") | Hard-coded lists work with `.contains()`. For dynamic ones, resolve in the pre-token Lambda and add a boolean claim |
| Request headers, IP address, network context | Not available |

Time-based rules are possible: AgentCore supplies `context.system.now` on every request (see the [AWS guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-time-based.html)).

> **Pattern:** when Cedar can't evaluate something directly, resolve it in the pre-token Lambda and add the result as a claim. Cedar then checks the precomputed value. LedgerLens does exactly this: the Lambda looks up the user's customer, and Cedar only compares strings. Policies stay simple, deterministic and auditable.
