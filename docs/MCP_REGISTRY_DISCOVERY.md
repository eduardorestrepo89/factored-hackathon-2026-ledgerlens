# MCP server discovery from an AWS Agent Registry

The agent can discover MCP servers in an [AWS Agent Registry](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/registry.html) and connect to them on every request. Their tools then sit next to the 9 Gateway tools. The feature needs no DynamoDB table, no UI and no per-user settings.

It is **off by default** (`backend.mcp_registry.enabled: false` in `infra-cdk/config.yaml`). Read [Security](#security) before turning it on: registry tools bypass the Gateway and Cedar, and they receive the customer's id.

## How it works

On each request, `create_strands_agent()` in `agent/ledgerlens/ledgerlens_agent.py` does the following when `is_discovery_enabled()` is true:

1. `discover_registry_mcp_servers()` (`agent/ledgerlens/tools/mcp_registry.py`) opens a boto3 `agent-registry` client in `AWS_REGION` (or `AWS_DEFAULT_REGION`).
2. It pages through `list_discoverable_registry_records` with the filter `recordType == "MCP"`. The API returns only Approved records.
3. It fetches the full records with `batch_get_discoverable_registry_record`, 100 ids per call.
4. It reads the endpoint from `descriptors.mcpServer`. The `data` field holds the MCP server definition, as a JSON string or an object, and the code uses `remotes[0].url` and `remotes[0].type`. A `remotes` list directly on `mcpServer` also works.
5. It skips records with no URL, and records whose transport is something other than `streamable-http`. A record with no transport counts as `streamable-http`.
6. `build_registry_mcp_clients()` creates one Strands `MCPClient` per server, with the prefix `registry_<slug>` and no request headers.
7. The clients go into the agent's `tools` after the Gateway client. If `build_registry_mcp_clients()` raises, the agent logs `[MCP-REGISTRY] Registry discovery failed; continuing without registry tools` and runs with the Gateway tools only.

```
Agent runtime (ledgerlens_agent.py)
   |  list_discoverable_registry_records, batch_get_discoverable_registry_record
   v
AWS Agent Registry (agent-registry API)
   |  remotes[0].url of each approved MCP record
   v
Strands MCPClient per server ---- streamable HTTP, no credentials ----> MCP server
```

There is no cache: every request lists the registry, reads the records and connects to each server again. That adds latency to every chat message.

## Turning it on

In `infra-cdk/config.yaml`:

```yaml
backend:
  mcp_registry:
    enabled: true
    registry_id: arn:aws:agent-registry:us-east-1:123456789012:registry/my-registry
```

Then deploy the main stack:

```bash
AWS_PROFILE=ledgerlens python scripts/deploy-with-codebuild.py ledgerlens-bank-assistant
```

A plain `cdk deploy` fails because the app has two stacks. To deploy locally, use `cd infra-cdk && npx cdk deploy --all`. See [DEPLOYMENT.md](DEPLOYMENT.md#configuration).

## Configuration

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | `false` | Master switch. Only YAML `true` turns it on. |
| `registry_id` | `""` | ARN or id of the registry. Required when `enabled` is true. |

What each value of `enabled` does:

- **`false`:** the CDK adds no IAM statements and the agent makes no registry calls. The two environment variables are still set, to `"false"` and `""`.
- **`true` with an empty `registry_id`:** `config-manager.ts` throws at CDK synth time, so the deploy fails before anything changes.
- At runtime, the module raises `ValueError` if discovery is on without `MCP_REGISTRY_ID`. The agent catches that, logs it and goes on without registry tools.

## Environment variables

The CDK sets these on the runtime (`infra-cdk/lib/backend-construct.ts`):

| Variable | Value |
|----------|-------|
| `MCP_REGISTRY_DISCOVERY_ENABLED` | `"true"` or `"false"`. Only `"true"` (any case) turns discovery on. |
| `MCP_REGISTRY_ID` | `registry_id`, or `""` |
| `AWS_REGION`, `AWS_DEFAULT_REGION` | The stack's region, also used for the registry |

## IAM

When the feature is on, the agent role gets two read-only statements. The IAM action names differ from the API names. `List`/`Search` authorize on the **registry** resource. The `BatchGetDiscoverableRegistryRecord` API is authorized by the permission-only action `agent-registry:GetDiscoverableRegistryRecord` on the **record** resource.

```json
[
  {
    "Sid": "AgentRegistryDiscoveryList",
    "Effect": "Allow",
    "Action": [
      "agent-registry:ListDiscoverableRegistryRecords",
      "agent-registry:SearchDiscoverableRegistryRecords"
    ],
    "Resource": "<registry ARN>"
  },
  {
    "Sid": "AgentRegistryDiscoveryGetRecord",
    "Effect": "Allow",
    "Action": "agent-registry:GetDiscoverableRegistryRecord",
    "Resource": "<registry ARN>/record/*"
  }
]
```

- With a full ARN as `registry_id`, the statements are scoped to that registry.
- With a bare id, they fall back to `arn:aws:agent-registry:<region>:<account>:registry/*` and `registry/*/record/*`.
- `SearchDiscoverableRegistryRecords` is granted, but the code doesn't call it.

> Granting `agent-registry:BatchGetDiscoverableRegistryRecord` (the API name) does nothing. It isn't an IAM action, so record reads fail with `AccessDenied`.

## Namespace

The discovery APIs are under the `agent-registry` namespace, and the code uses `boto3.client("agent-registry")`. The older `bedrock-agentcore` namespace doesn't expose these APIs and was scheduled to be discontinued after 2026-09-17. A registry created under the old namespace has to be migrated first: see the [registry FAQ](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/registry-faq.html). boto3 and botocore 1.43.66 or later ship the `agent-registry` client, and `agent/ledgerlens/requirements.txt` pins that minimum.

## Tool names

Each server gets the Strands prefix `registry_<slug>`, so its tools reach the model as `registry_<slug>_<tool_name>`. The slug is built like this:

1. Each run of characters other than letters and digits becomes `_`.
2. Leading and trailing `_` are stripped, and the result is lowercased.
3. The slug is cut to 24 characters, then trailing `_` are stripped again. An empty slug becomes `server`.
4. If two servers end up with the same prefix, the second gets `_2`, the third `_3`, and so on.

The 24-character cap keeps the prefix short. Bedrock rejects every request when a tool name is over 64 characters. The code doesn't check the tool names themselves, so a long tool name can still push the full name past that limit.

## Failure behavior

- **Discovery fails soft.** If listing or batch-getting fails (registry unreachable, access denied, throttled), the agent logs a warning and runs without registry tools. A record that can't be fetched or has no usable endpoint is logged and skipped.
- **Connecting fails hard.** Strands connects each `MCPClient` and lists its tools while it builds the `Agent`, with a 30-second startup timeout by default. That step is outside the `try` that guards discovery. If an approved server is down, slow or refuses the connection, building the agent raises, and the request ends with `{"status": "error", ...}`. One broken approved record therefore breaks every chat request until the record is removed from the registry or discovery is turned off.
- **No credentials are sent.** Only public `streamable-http` servers are meant to be connected. The module docstring says records that advertise authentication are skipped, but the code doesn't check for that. A server that needs credentials is connected without them, and its failure is handled as in the point above.

## Security

Registry tools don't get the protections the Gateway tools have:

- **No Gateway, no Cedar.** The agent connects to each server directly. There is no Cognito machine token, no Cedar policy and no Gateway logging on these calls.
- **The customer's id reaches the server.** `CustomerIdHook` (`agent/ledgerlens/tools/customer_id_hook.py`) works on any tool whose input schema has a `customer_id` property, and registry tools are no exception. The hook writes the signed-in customer's real `customer_id` into the call, so a third-party server with that input receives it. For a user with no linked customer, the hook cancels the call.
- **No Yes/No confirmation.** `ConfirmationHook` matches on the part of the tool name after the last `___`. A registry tool name has no `___` unless the server's own tool name contains one, so registry tools aren't paused for a confirmation.
- **Tool descriptions and results come from a third party.** The model reads them. The system prompt tells the model to ignore instructions in tool results. It also lists only the card tools and says the agent can do nothing else, and it doesn't mention registry tools.

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| No registry tools appear | Discovery off, or no Approved MCP records | Set `enabled: true` and `registry_id`, and approve records in the registry |
| Synth fails on `registry_id` | `enabled` is true but `registry_id` is empty | Set the registry ARN or id |
| A known server isn't connected | Transport isn't `streamable-http`, or the record has no `remotes[0].url` | Check the record's `mcpServer` descriptor |
| Every request fails after turning it on | An approved server can't be reached or refuses the connection | Check the runtime logs for `Failed to load tool`, then fix the server, remove the record, or turn discovery off |
| `AccessDeniedException` in the logs | The role lacks the discovery permissions for this registry | Check the `AgentRegistryDiscoveryList` and `AgentRegistryDiscoveryGetRecord` statements and the `registry_id` they were built from |
| `ValidationException` about the namespace | The registry is under the old `bedrock-agentcore` namespace | Migrate it to `agent-registry` |

## Files

- `agent/ledgerlens/tools/mcp_registry.py`: discovery and client builder.
- `agent/ledgerlens/ledgerlens_agent.py`: adds the clients to the agent.
- `infra-cdk/config.yaml`, `infra-cdk/lib/utils/config-manager.ts`, `infra-cdk/lib/backend-construct.ts`: config, validation, IAM and environment variables.
- `tests/unit/test_mcp_registry.py`: unit tests.
