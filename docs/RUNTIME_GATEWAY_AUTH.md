# AgentCore Runtime to Gateway Authentication
**AgentCore Runtime → Cognito → AgentCore Gateway → Cedar → tool Lambda**

This page describes how the agent running in AgentCore Runtime gets the token it sends to the AgentCore Gateway, and how the Gateway checks it. It has two phases: **deployment** (what CDK sets up) and **per request** (the live token flow).

The live path calls Cognito directly. The stack also deploys an OAuth2 credential provider for the AgentCore Token Vault, but the live path doesn't use it; it is described at the end as [Approach 2](#approach-2-the-token-vault-path-deployed-not-used).

## User auth vs machine auth

Two tokens are involved. Both come from the same user pool, from different app clients.

**Flow 1: user → runtime.**
- Web client `ledgerlens-bank-assistant-client`, Authorization Code grant, no secret.
- The runtime validates the user's JWT with `RuntimeAuthorizerConfiguration.usingJWT(<user pool discovery URL>, [web client ID])`.
- The `Authorization` header is allowlisted (`requestHeaderConfiguration`), so the agent can read the user's `sub` from it.

**Flow 2: runtime → Gateway.**
- Machine client `ledgerlens-bank-assistant-machine-client`, client credentials grant, with a secret.
- The Gateway accepts only tokens issued to this client.

The two flows are linked on purpose. The agent passes the user's `sub` when it asks for the machine token, so the machine token carries the user's `customer_id`. Cedar needs that claim.

```
User
  → Cognito (Authorization Code, web client) → user JWT
  → AgentCore Runtime (validates the JWT against the web client)
  → agent code: sub = the user JWT's sub claim
      → Cognito /oauth2/token (client credentials, machine client,
                               aws_client_metadata = {"verified_user_id": sub})
          → V3 pre-token Lambda adds customer_id
      ← machine JWT with customer_id
  → AgentCore Gateway (validates the JWT against the machine client)
  → Cedar policy engine (customer_id claim vs tool input)
  → tool Lambda
```

## Secrets and parameters

| Item | Store | Created by | Read by |
|---|---|---|---|
| `/ledgerlens-bank-assistant/machine_client_secret` ("Secret 1") | Secrets Manager | CDK (`secretsmanager.Secret`), from the machine client's generated secret. It holds only the secret string. | `agent/utils/auth.py`, `test-scripts/test-gateway.py`, the oauth2-provider Lambda at deploy |
| A secret under `bedrock-agentcore-identity!default/oauth2/` ("Secret 2") | Secrets Manager | AgentCore Identity, when the OAuth2 credential provider is created | Only the Token Vault (Approach 2); nothing live |
| `/ledgerlens-bank-assistant/machine_client_id` | SSM | CDK | `auth.py`, `test-gateway.py` |
| `/ledgerlens-bank-assistant/cognito_provider` | SSM | CDK: `<domain-prefix>.auth.<region>.amazoncognito.com` | `auth.py`, `test-gateway.py` |
| `/ledgerlens-bank-assistant/gateway_url` | SSM | CDK | `agent/ledgerlens/tools/gateway.py`, `test-gateway.py` |

The code reads these parameters by name. Renaming one in CDK breaks `auth.py` or `gateway.py` (and so every agent request) and `test-gateway.py`, unless you change them too.

## IAM roles

1. **Runtime execution role** (`AgentCoreRole`, plus statements added in `createAgentCoreRuntime()`):
   - `ssm:GetParameter(s)` on `/ledgerlens-bank-assistant/*`: live path.
   - `secretsmanager:GetSecretValue` on Secret 1: live path. It is also granted on Secret 2, for Approach 2.
   - `bedrock-agentcore:GetOauth2CredentialProvider` and `GetResourceOauth2Token`: Approach 2 only.
2. **GatewayRole**, trusted by `bedrock-agentcore.amazonaws.com`:
   - `lambda:InvokeFunction` on each tool Lambda, granted by `addLambdaTarget()`.
   - `GetPolicyEngine`, `AuthorizeAction`, `PartiallyAuthorizeActions`, `CheckAuthorizePermissions`, to evaluate Cedar.
   - Bedrock invoke, SSM read under `/ledgerlens-bank-assistant/*`, `cognito-idp:DescribeUserPoolClient` and `InitiateAuth` on the user pool, and CloudWatch Logs under `/aws/bedrock-agentcore/*`.
3. **oauth2-provider Lambda role:**
   - Read Secret 1.
   - `Create/Get/DeleteOauth2CredentialProvider` on `token-vault/default` and `token-vault/default/oauth2credentialprovider/*`.
   - `Create/Get/DeleteTokenVault` on `token-vault/default` and `token-vault/default/*`.
   - `CreateSecret`, `PutSecretValue`, `DescribeSecret`, `DeleteSecret` on `bedrock-agentcore-identity!default/oauth2/*`, for the secret AgentCore Identity manages. The Lambda's own code writes no secret.
4. **cedar-policy Lambda role:** policy engine and policy CRUD; `UpdateGateway`, `GetGateway`, `InvokeGateway`, `ManageResourceScopedPolicy`, `ListGatewayTargets` on the Gateway; `iam:PassRole` on GatewayRole, because `update_gateway` re-sends the Gateway's role.

## Phase 1: deployment

These steps run during the main stack deploy.

### D1: Cognito machine client

`createMachineAuthentication()` in `infra-cdk/lib/backend-construct.ts` creates:
- the resource server `ledgerlens-bank-assistant-gateway`, with scopes `read` and `write`;
- the machine client, with `clientCredentials: true` and `generateSecret: true`;
- Secret 1, holding the client secret.

`createCognitoSSMParameters()` writes `machine_client_id` and `cognito_provider` to SSM.

Separately, `cognito-construct.ts` attaches the V3 pre-token Lambda to the user pool (Essentials tier). See [IDENTITY_POLICY.md](IDENTITY_POLICY.md#v3-pre-token-lambda).

### D2: Gateway with a custom JWT authorizer

`createAgentCoreGateway()` creates the Gateway with the L2 construct:

```typescript
authorizerConfiguration: agentcore.GatewayAuthorizer.usingCustomJwt({
  discoveryUrl: cognitoDiscoveryUrl,   // https://cognito-idp.<region>.amazonaws.com/<pool-id>/.well-known/openid-configuration
  allowedClients: [this.machineClient.userPoolClientId],
}),
```

- The `discoveryUrl` tells the Gateway which issuer to trust. The Gateway fetches the signing keys (JWKS) from it.
- `allowedClients` limits it to the machine client.

Each tool is added with `gateway.addLambdaTarget()`. With no credential provider set, the Gateway calls the Lambda with its own IAM role. The Gateway URL goes to SSM as `gateway_url`.

### D3: Cedar policy engine

After every target exists, the `GatewayPolicy` custom resource creates the policy engine and one policy per statement in `gateway/policies/policy.cedar`. It attaches the engine in `ENFORCE` mode. From then on, Cedar sits between JWT validation and the tool Lambda. See the [Cedar Policy Guide](CEDAR_POLICY_GUIDE.md).

### D4: OAuth2 credential provider (deployed, not used by the live path)

The `RuntimeCredentialProvider` custom resource runs `infra-cdk/lambdas/oauth2-provider/index.py`:

```
oauth2-provider Lambda (Create)
    |-- 1. Reads Secret 1 → client_secret
    |
    └-- 2. bedrock-agentcore-control create_oauth2_credential_provider(
               name="ledgerlens-bank-assistant-runtime-gateway-auth",
               credentialProviderVendor="CustomOauth2",
               oauth2ProviderConfigInput={"customOauth2ProviderConfig": {
                   "clientId": <machine client ID>,
                   "clientSecret": <client_secret, inline>,
                   "oauthDiscovery": {"discoveryUrl": <user pool discovery URL>},
               }})
            → AgentCore Identity stores the secret itself (Secret 2)
              and registers the provider in the default Token Vault
```

- **Update** calls `update_oauth2_credential_provider` with the same fields.
- **Delete** deletes the provider by name, and ignores "not found".

### D5: Runtime

`createAgentCoreRuntime()` creates the runtime with:
- `STACK_NAME=ledgerlens-bank-assistant`: `auth.py` and `gateway.py` build every SSM and Secrets Manager name from it.
- `GATEWAY_CREDENTIAL_PROVIDER_NAME=ledgerlens-bank-assistant-runtime-gateway-auth`: used only by Approach 2.
- The inbound JWT authorizer on the web client, and the `Authorization` header allowlist.

## Phase 2: per request (live path)

This runs on every message the agent receives, in `invocations()` in `agent/ledgerlens/ledgerlens_agent.py`.

### R1: who is the user?

`extract_user_id_from_context(context)` in `agent/utils/auth.py` decodes the user JWT from the `Authorization` header and returns its `sub`. It skips signature verification because the runtime's authorizer already validated the token.

### R2: request the machine token

`get_gateway_access_token(user_id)`:

```
1. Read cognito_provider and machine_client_id from SSM,
   and the secret (Secret 1) from Secrets Manager
2. POST https://<cognito_provider>/oauth2/token
     Authorization: Basic base64(<client_id>:<client_secret>)
     Content-Type: application/x-www-form-urlencoded
     grant_type=client_credentials
     scope=ledgerlens-bank-assistant-gateway/read ledgerlens-bank-assistant-gateway/write
     aws_client_metadata={"verified_user_id": "<sub>"}
3. Non-200 → raise. Otherwise return access_token.
```

The code doesn't cache the values or the token: each request makes these calls again.

### R3: Cognito enriches the token

Cognito runs the V3 pre-token Lambda for the client credentials grant. The Lambda reads `verified_user_id` and adds `customer_id` (from `USER_CUSTOMER_IDS_MAP`, or `""`), plus `user_id`, `department` and `role`. See [IDENTITY_POLICY.md](IDENTITY_POLICY.md#v3-pre-token-lambda).

`aws_client_metadata` is a Cognito feature. That makes `auth.py` Cognito-specific, along with the token URL it builds from `cognito_provider` and the scope names.

### R4: read customer_id from the token

`extract_customer_id_from_token(access_token)` decodes the token without checking the signature and returns the `customer_id` claim as written, or `""`. It never raises.
- **Why no signature check:** the token came straight from Cognito over HTTPS, and the Gateway validates it on every call.
- **Where the value goes:** into the system prompt and `CustomerIdHook`.

### R5: build the MCP client

`create_gateway_mcp_client(access_token)` in `agent/ledgerlens/tools/gateway.py` reads `gateway_url` from SSM and returns:

```python
MCPClient(
    lambda: streamablehttp_client(
        url=gateway_url,
        headers={"Authorization": f"Bearer {access_token}"},
    ),
    prefix="gateway",
)
```

**Why one token per request:** the `customer_id` in the prompt and the hook must come from the same token the Gateway checks. The agent is rebuilt on every invocation. Cognito's default access token lifetime is one hour, and the machine client doesn't change it, so the token outlives the request and an MCP reconnection within the request still has a valid token.

### R6: the Gateway validates the JWT

```
AgentCore Gateway (custom JWT authorizer)
    |-- 1. Takes the Bearer token from the Authorization header
    |-- 2. Gets the JWKS through the user pool's discovery URL
    |-- 3. Verifies the signature
    |-- 4. Checks the claims: client_id in allowedClients (the machine client),
    |       not expired, issuer is the user pool
    └-- 5. Valid → Cedar (R7). Invalid → 401 Unauthorized
```

**Why `allowedClients`:** only the machine client's tokens are accepted. A token another client of the same user pool obtained, including the web client's, is rejected.

### R7: Cedar decides

The policy engine evaluates the request with the token's claims as principal tags:
- **`tools/list`:** `PartiallyAuthorizeActions` with the claims only. Denied tools are removed from the list.
- **`tools/call`:** `AuthorizeAction` with the claims and the tool's arguments (`context.input`). A denied call returns an authorization error to the agent and the Lambda never runs.

### R8: the Gateway calls the tool Lambda

```
AgentCore Gateway (GatewayRole)
    → lambda:InvokeFunction on ledgerlens-<slug>
        event = the tool arguments
        context.client_context.custom["bedrockAgentCoreToolName"] = "<target>___<tool>"
    ← {"content": [{"type": "text", "text": ...}]} or {"error": ...}
    ← MCP response to the agent
```

## Approach 2: the Token Vault path (deployed, not used)

`gateway.py` keeps a commented-out alternative that gets the token with the AgentCore Identity SDK's `@requires_access_token` decorator. It is what the D4 provider and the runtime role's Token Vault grants are for. It can't pass `aws_client_metadata`, so its tokens carry no `customer_id`, and with the current Cedar policy every tool would be denied. See [IDENTITY_POLICY.md, Approach 2](IDENTITY_POLICY.md#approach-2-commented-out-requires_access_token).

How it would work:

1. **MCP client.** The Approach 2 `create_gateway_mcp_client()` calls `_fetch_gateway_token()` *inside* the `MCPClient` factory lambda. Every connection and reconnection then gets a token. Calling it outside the lambda would capture one token at creation time, and a reconnection after it expires would get a 401.
2. **Decorator.** `@requires_access_token(provider_name=os.environ["GATEWAY_CREDENTIAL_PROVIDER_NAME"], auth_flow="M2M", scopes=[])` intercepts the call:
   - `auth_flow="M2M"` selects the client credentials grant.
   - `scopes=[]` because Cognito grants the scopes the machine client is configured for.
3. **Provider lookup.** `GetOauth2CredentialProvider` resolves the provider name to its discovery URL, client ID and Secret 2.
4. **Token.** `GetResourceOauth2Token` returns a cached token if one is valid. Otherwise AgentCore Identity reads Secret 2 and calls Cognito's token endpoint.
   - Tokens are cached per workload identity (resolved through `workload-identity-directory`), not per IAM role.
   - Secret 2 is read with the runtime role's permissions, not the service's: that is why the runtime role has `GetSecretValue` on Secret 2. A caller can't use AgentCore Identity to read a secret it couldn't read itself.
5. The decorator passes the token in as `access_token`, and the MCP client sends it as the Bearer token. R6 to R8 are the same as in the live path.

## Replacing Cognito

To use another identity provider for this flow, see [Replacing Cognito, section 8](REPLACING_COGNITO.md#8-replacing-cognito-for-the-machine-token). In short: the Gateway authorizer, `createMachineAuthentication()`, `auth.py` and the pre-token Lambda all change, and the new provider must still put a `customer_id` claim in the machine token.
