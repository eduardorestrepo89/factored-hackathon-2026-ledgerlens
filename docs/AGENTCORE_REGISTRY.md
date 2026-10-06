# AgentCore Registry Integration — Steering Doc

This document is the implementation guide for registering a deployed agent runtime
in an **existing** [Amazon Bedrock AgentCore Registry](https://docs.aws.amazon.com/bedrock-agentcore/)
so it can be discovered by other agents and services (A2A, MCP, agent skills, or a
custom descriptor).

It is written as a *steering doc*: it describes the full intended design so the
feature can be (re-)implemented consistently in the CDK stack. The reference
implementation lives on the `feat/agentcore-registry` branch's stash — this doc is
the source of truth for what to build.

> **Scope.** This feature registers into a registry that already exists. It does
> **not** create or manage the registry itself. The registry is referenced by
> `registry_id`, and the feature is entirely opt-in: when no `registry_id` is
> configured, nothing is provisioned.

---

## 1. Architecture overview

```
infra-cdk/config.yaml
        │  registry_id (+ optional name/version/type/auto_submit)
        ▼
┌──────────────────────────────────────────────┐
│ IaC layer (CDK L2 construct)                    │
│   - builds descriptor JSON from runtime ARN     │
│   - provisions registry-record Lambda + IAM     │
│   - invokes Lambda on create/update/delete       │
└──────────────────────────────────────────────┘
        │  RequestType + ResourceProperties
        ▼
┌──────────────────────────────────────────────┐
│ registry-record Lambda (shared Python handler)  │
│   boto3 → bedrock-agentcore-control:            │
│     Create / Update / Delete RegistryRecord      │
│     (+ optional SubmitRegistryRecordForApproval) │
└──────────────────────────────────────────────┘
```

**Key design principle: one Lambda owns the registry logic.** The Python handler in
`infra-cdk/lambdas/registry-record/index.py` is the single source of registry
logic. CDK wires it as a CloudFormation Custom Resource (lifecycle events delivered
natively by CloudFormation). Keep the registry API contract in that one place.

---

## 2. Configuration surface

The feature is opt-in.

### CDK — `infra-cdk/config.yaml`

```yaml
# AgentCore Registry — register this agent in an existing registry for discovery
# registry:
#   registry_id: <your-registry-id>
#   record_name: MyAgent
#   record_version: "1.0"
#   descriptor_type: CUSTOM  # A2A | MCP | AGENT_SKILLS | CUSTOM
#   auto_submit: false
```

### Field reference

| Field | Required | Default | Notes |
|-------|----------|---------|-------|
| `registry_id` | **Yes** (enables feature) | `null` | ID of the existing registry. When unset/null, nothing is provisioned. |
| `record_name` | No | `stack_name_base` | Must start with a letter or digit. |
| `record_version` | No | `"1.0"` | Free-form version string. |
| `descriptor_type` | No | `CUSTOM` | One of `A2A`, `MCP`, `AGENT_SKILLS`, `CUSTOM`. Validated. |
| `auto_submit` | No | `false` | If true, submit the record for approval after create/update. |

---

## 3. The shared Lambda handler (contract)

`infra-cdk/lambdas/registry-record/index.py` — `requirements.txt`: `boto3>=1.38.0`,
runtime `python3.13`, handler `handler`.

It dispatches on CloudFormation-style events:

| `RequestType` | boto3 call | Physical ID source |
|---------------|-----------|--------------------|
| `Create` | `create_registry_record(...)` | record ID parsed from returned `recordArn` |
| `Update` | `update_registry_record(...)` | reuses `PhysicalResourceId` from event |
| `Delete` | `delete_registry_record(...)` | `PhysicalResourceId`; swallows `ResourceNotFoundException` |

**`ResourceProperties` payload** (the IaC → Lambda contract):

```json
{
  "RegistryId":        "...",
  "RecordName":        "...",
  "RecordVersion":     "1.0",
  "DescriptorType":    "CUSTOM",
  "DescriptorContent": "<json string>",
  "Description":       "...",
  "AutoSubmit":        "true|false"
}
```

**Descriptor shaping (`_build_descriptors`).** The handler wraps the raw
`DescriptorContent` JSON string into the boto3 shape keyed by descriptor type:

| `DescriptorType` | boto3 `descriptors` shape |
|------------------|---------------------------|
| `A2A` | `{"a2a": {"agentCard": {"inlineContent": <content>}}}` |
| `MCP` | `{"mcp": {"server": {"inlineContent": <content>}}}` |
| `AGENT_SKILLS` | `{"agentSkills": {"inlineContent": <content>}}` |
| `CUSTOM` (default) | `{"custom": {"inlineContent": <content>}}` |

**Approval (`_submit_for_approval`).** When `AutoSubmit == "true"`, call
`submit_registry_record_for_approval(...)` after create/update. Failures here are
logged as warnings, **not** raised — approval is best-effort and must not fail the
deployment.

**Return shape:** `{"PhysicalResourceId": <recordId>, "Data": {"RecordId", "RecordArn", "Status"}}`.

---

## 4. Descriptor content

CDK builds the descriptor JSON from deployment facts. The canonical content:

```json
{
  "name":        "<record_name or stack_name_base>",
  "description": "<pattern> agent runtime for <stack_name_base>",
  "version":     "<record_version>",
  "runtimeArn":  "<agent runtime ARN>",
  "pattern":     "<backend pattern>"
}
```

It is built in `backend-construct.ts` using `this.agentRuntime.agentRuntimeArn`
and `JSON.stringify(...)`, then passed as `descriptorContent`.

---

## 5. CDK implementation

### Construct — `infra-cdk/lib/utils/agentcore-registry.ts`

`AgentCoreRegistry extends Construct`. Responsibilities:

1. **`PythonFunction`** (`RegistryRecordHandler`), python3.13, 60s timeout, entry
   `../../lambdas/registry-record`, with an explicit `LogGroup`
   (`/aws/lambda/<stackNameBase>-registry-record`, 1-week retention, `DESTROY`).
2. **IAM** — `addToRolePolicy` granting the five registry actions (see §6),
   scoped to the registry ARN and its `/*` children.
3. **`cr.Provider`** wrapping the handler, then a **`cdk.CustomResource`** passing
   the `ResourceProperties` payload from §3.
4. **Exposes** `recordId` / `recordArn` via `getAttString`, plus two `CfnOutput`s.

Props interface (`AgentCoreRegistryProps`): `registryId`, `recordName`,
`recordVersion`, `descriptorType` (union type), `descriptorContent`, optional
`description`, optional `autoSubmit`, `stackNameBase`.

### Wiring — `backend-construct.ts`

After the agent runtime + memory are created, gate on config and instantiate:

```ts
if (config.registry?.registry_id) {
  const registryConfig = config.registry
  const descriptorType = registryConfig.descriptor_type || "CUSTOM"
  const descriptorContent = JSON.stringify({
    name: registryConfig.record_name || config.stack_name_base,
    description: `${pattern} agent runtime for ${config.stack_name_base}`,
    version: registryConfig.record_version || "1.0",
    runtimeArn: this.agentRuntime.agentRuntimeArn,
    pattern: pattern,
  })
  new AgentCoreRegistry(this, "AgentCoreRegistryRecord", {
    registryId: registryConfig.registry_id,
    recordName: registryConfig.record_name || config.stack_name_base,
    recordVersion: registryConfig.record_version || "1.0",
    descriptorType,
    descriptorContent,
    description: `${pattern} agent runtime for ${config.stack_name_base}`,
    autoSubmit: registryConfig.auto_submit ?? false,
    stackNameBase: config.stack_name_base,
  })
}
```

### Config typing/validation — `config-manager.ts`

- Add an optional `registry?` block to the `AppConfig` interface with the five
  fields (`registry_id` required, the rest optional; `descriptor_type` as the union).
- In the parser: if a `registry` section exists, require `registry_id` and validate
  `descriptor_type` against `["A2A","MCP","AGENT_SKILLS","CUSTOM"]`, throwing a
  descriptive error referencing the config path. Pass `registry: registryConfig`
  through to the returned `AppConfig`.

---

## 6. IAM permissions

The registry-record Lambda role requires these `bedrock-agentcore` actions, scoped
to the registry ARN and its `/*` children:

```
bedrock-agentcore:CreateRegistryRecord
bedrock-agentcore:UpdateRegistryRecord
bedrock-agentcore:DeleteRegistryRecord
bedrock-agentcore:GetRegistryRecord
bedrock-agentcore:SubmitRegistryRecordForApproval
```

Resource ARNs:

```
arn:aws:bedrock-agentcore:<region>:<account>:registry/<registry_id>
arn:aws:bedrock-agentcore:<region>:<account>:registry/<registry_id>/*
```

---

## 7. Review checklist

When implementing or reviewing, confirm:

- [ ] Registry logic lives only in `index.py` (not duplicated in the construct).
- [ ] `ResourceProperties` payload keys/casing match §3.
- [ ] Descriptor content object keys/values match §4.
- [ ] Five IAM actions with the ARN scoping in §6.
- [ ] Default values (`record_version` `"1.0"`, `descriptor_type` `CUSTOM`, `auto_submit` `false`).
- [ ] `descriptor_type` validated against the four allowed values.
- [ ] Feature fully no-ops when `registry_id` is unset/null.
- [ ] Delete path is idempotent / best-effort (missing record is not an error).

---

## 8. Testing & verification

1. **No-registry path** — deploy without `registry_id`; confirm no registry Lambda,
   role, or log group is synthesized.
2. **Create** — set `registry_id`, deploy, confirm a record appears in the registry
   with the expected descriptor and the runtime ARN.
3. **Update** — bump `record_version` or change descriptor; redeploy; confirm the
   record updates in place (same record ID).
4. **auto_submit** — set true; confirm the record moves to a submitted/approval
   status; confirm a submit failure does not fail the deploy (warning only).
5. **Destroy** — tear down; confirm the record is deleted and a missing record does
   not error.
