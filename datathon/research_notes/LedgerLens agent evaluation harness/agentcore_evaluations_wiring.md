# Wiring AgentCore Evaluations onto the deployed LedgerLens agent (as of 2026-10-04)

Scope: what it takes to add Amazon Bedrock AgentCore Evaluations, as an AWS-native layer, on top of the local stream-based runner and pure-Python grader, for the deployed `ledgerlens-bank-assistant` stack (us-east-1). This builds on `../Agent evaluation signal on AWS/verification_2026-10-03.md` (cited below as "verification note"), `../Agent evaluation signal on AWS/aws_evaluation_stack.md` and `../../docs/analysis/2026-10-03-eval-observability-on-hold.md` (limitation L7). It does not repeat their verified facts unless they changed or matter for this agent.

Method:
- AWS docs were downloaded on 2026-10-04 and read as text. They include the AgentCore devguide, the CloudWatch user guide, the CloudFormation reference, the AgentCore pricing page and the release notes. The newest release-notes entry is dated "October 2026".
- Shipped code was read from wheels downloaded into the scratchpad (not installed): `bedrock-agentcore==1.24.0` (2026-09-28), `strands-agents==1.32.0` (the version the agent pins), and `aws-opentelemetry-distro` 0.16.0 (pinned in the image), 0.18.0 and 0.21.0 (latest, 2026-10-01).
- The CDK source was read from `aws-cdk-lib` 2.260.0 in the main checkout's `infra-cdk/node_modules`. The worktree has no `node_modules`.
- No AWS API was called, nothing was deployed, and the agent was not invoked. "Verified" below means a primary doc or the shipped source states it. Nothing here was tested against the live account.

Repo links are relative to this file (the repo root is `../../../`).

---

## Q1. Telemetry mode for this agent: is it new enough, does it emit spans today, and what would change?

### Takeaway
The Runtime was created around 2026-10-03, after the 2026-07-20 cut-over, so the platform default for it is unified telemetry. But the image pins ADOT 0.16.0, and AWS says ADOT versions before 0.18.0 ignore the span destination and send spans to the shared `aws/spans` group. So the agent runs in **split telemetry**: spans go to `aws/spans`, and content goes to event records in the runtime log group's `otel-rt-logs` stream. AgentCore Evaluations reads both modes.

The real blocker is that Transaction Search is off. Evaluations requires it in both modes, and `aws/spans` only exists once it is on. **Minimum fix: enable Transaction Search. This needs no code change and no redeploy.**

Unified telemetry is optional. It needs:
- ADOT 0.18.0 or later;
- `logs:PutResourcePolicy` on the execution role;
- a new image and a redeploy.

It also turns on ADOT's new MCP instrumentation.

### Cited Findings
**What AWS documents**
- "Agents that you created on or after July 20, 2026 use unified telemetry by default, and agents that you created before that date use split telemetry. Unified telemetry needs ADOT version 0.18.0 or later (`aws-opentelemetry-distro>=0.18.0`). Earlier versions send spans to the shared `aws/spans` log group." Also: "Enable Amazon CloudWatch Transaction Search. Evaluation requires it in both delivery modes." — [Telemetry setup and delivery](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks-telemetry.html)
- The service reads both modes: "AgentCore Evaluations reads both modes … the same evaluators give you the same results either way." In split mode, "Spans go to the shared `aws/spans` log group. CloudWatch creates this log group when you turn on Transaction Search." Event records go to the agent's log group, `otel-rt-logs` stream, and "the service reads spans from `aws/spans` and matches them to their event records." — [Telemetry setup and delivery](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks-telemetry.html)
- Requirements for the agent-log-group (unified) destination:
  1. "Enable CloudWatch Transaction Search … Without Transaction Search, AgentCore can't deliver spans to the agent's log group."
  2. "Grant the `logs:PutResourcePolicy` action on the agent's log group to the agent's execution role."
  3. "The agent uses ADOT version 0.18.0 or later … Earlier versions ignore the span destination configuration and deliver spans to the shared `aws/spans` log group."

  The override is `UNIFIED_TRACES_DESTINATION_ENABLED=true|false` on the agent runtime. — [Add observability … (Span destination for agents hosted in AgentCore runtime)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html)
- July 2026 release note "Runtime: Unified span destination for agents": "Starting July 20, 2026, newly created agents in supported AWS Regions use the agent's log group by default… This feature requires CloudWatch Transaction Search with trace segments sent to CloudWatch Logs, `logs:PutResourcePolicy` on the agent's execution role, and ADOT version 0.18.0 or later." — [Release notes](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html)
- Transaction Search is a prerequisite for any AgentCore spans in CloudWatch: "To view metrics, spans, and traces generated by the AgentCore service, you first need to complete a one-time setup to turn on Amazon CloudWatch Transaction Search." — [Add observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html). And "When you enable Transaction Search, spans sent to X-Ray are ingested in a log group called `aws/spans`." — [CloudWatch Transaction Search](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Transaction-Search.html)

**What an AgentCore-hosted agent needs**
- The ADOT SDK in requirements, at `aws-opentelemetry-distro>=0.18.0` plus `boto3`, and the entry point run as `opentelemetry-instrument python …`. For Docker: `CMD ["opentelemetry-instrument", "python", "main.py"]`. To propagate the session ID, send the `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` header. — [Add observability (Enabling observability in agent code for AgentCore-hosted agents)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html)
- The `AGENT_OBSERVABILITY_ENABLED`, `OTEL_PYTHON_DISTRO`, `OTEL_PYTHON_CONFIGURATOR` and `OTEL_EXPORTER_OTLP_*_HEADERS` variables are documented **only for agents hosted outside AgentCore Runtime**. — [Add observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html); [Get started](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-get-started.html)
- On Runtime the wiring is automatic: "the runtime automatically instruments your agent with OpenTelemetry — no additional OTEL libraries or configuration are needed" (CLI deploys) — [Get started](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-get-started.html). An AWS blog of 2026-08-13 says "For agents on AgentCore runtime, observability is configured automatically", with "Automatic in-built OTEL variables" — [AWS ML blog](https://aws.amazon.com/blogs/machine-learning/monitor-on-premises-and-multi-cloud-ai-agents-with-agentcore-observability/)
- The execution-role doc includes `logs:PutResourcePolicy` on `arn:aws:logs:<region>:<acct>:log-group:/aws/bedrock-agentcore/runtimes/agentName-*`, plus `xray:PutTraceSegments`, `PutTelemetryRecords`, `GetSamplingRules` and `GetSamplingTargets`. — [Execution role for running an agent in AgentCore runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html)

**ADOT source**
- ADOT exports agent spans only when `AGENT_OBSERVABILITY_ENABLED=true` and an OTLP traces endpoint is set. It then always exports 100% of spans and adds `session.id` from baggage. — [aws-opentelemetry-distro 0.21.0 wheel](https://pypi.org/project/aws-opentelemetry-distro/0.21.0/), `amazon/opentelemetry/distro/aws_opentelemetry_configurator.py:441-457, 646-652`. Since the repo sets neither variable, the Runtime must inject them for spans to exist.
- ADOT releases on PyPI: 0.16.0 (2026-03-13), 0.17.0 (2026-04-09), 0.18.0 (2026-06-19), 0.19.0 (2026-07-23), 0.20.0 (2026-09-17), 0.21.0 (2026-10-01) — [PyPI aws-opentelemetry-distro](https://pypi.org/project/aws-opentelemetry-distro/)
- 0.16.0 already has the content-extraction ("LLO") handler for Strands events (`gen_ai.user.message`, `gen_ai.tool.message`, `gen_ai.choice`), so split telemetry works on it. — 0.16.0 wheel, `amazon/opentelemetry/distro/llo_handler.py:144-165`
- 0.18.0 adds `AWS_GENAI_CONTENT_EXTRACTION_OPT_OUT`, which keeps payloads on spans (`_utils.py:15`), and an MCP instrumentor (entry point `aws_mcp`, `entry_points.txt:11`). Neither exists in 0.16.0: its `instrumentation/` has only `common`, `crewai` and `langchain`. — 0.16.0 and 0.18.0 wheels
- Dependency pins:
  - ADOT 0.16.0 pins `opentelemetry-api==1.40.0`, 0.18.0 pins `1.42.1`, and 0.21.0 pins `1.44.0`.
  - `strands-agents` 1.32.0 requires `opentelemetry-api>=1.30.0,<2.0.0` and the same range for the SDK.
  - ADOT 0.18.0 and later require Python 3.10 or newer.

  — wheel `METADATA` files ([PyPI strands-agents 1.32.0](https://pypi.org/project/strands-agents/1.32.0/))

**This repo (worktree `feat/eval-resume`, from `stage` at 1b4b4ed)**
- The image pins ADOT 0.16.0 and starts the agent under `opentelemetry-instrument`. The only OTEL variable it sets is `OTEL_PYTHON_LOG_CORRELATION=true`. — [Dockerfile:12](../../../agent/ledgerlens/Dockerfile#L12), [:17-18](../../../agent/ledgerlens/Dockerfile#L17-L18), [:36](../../../agent/ledgerlens/Dockerfile#L36)
- The Runtime's environment variables set no `OTEL_*`, `AGENT_OBSERVABILITY_ENABLED` or `UNIFIED_TRACES_DESTINATION_ENABLED`. — [backend-construct.ts:402-437](../../../infra-cdk/lib/backend-construct.ts#L402-L437)
- The Runtime L2 is built without `tracingEnabled` or `loggingConfigs`. Its name is `${stack_name_base with - → _}_${agent_name}` = `ledgerlens_bank_assistant_ledgerlens_agent`. Deployment type is `docker`. — [backend-construct.ts:443-455](../../../infra-cdk/lib/backend-construct.ts#L443-L455); [config.yaml:1, 12-14](../../../infra-cdk/config.yaml#L1-L14)
- The execution role grants:
  - `logs:CreateLogGroup` and `logs:DescribeLogStreams` on `/aws/bedrock-agentcore/runtimes/*`;
  - `logs:CreateLogStream` and `logs:PutLogEvents` on that group's streams;
  - the four X-Ray actions.

  It does **not** grant `logs:PutResourcePolicy`. — [agentcore-role.ts:36-67](../../../infra-cdk/lib/utils/agentcore-role.ts#L36-L67)
- The CDK `Runtime` construct adds log-group and describe permissions, but not `PutResourcePolicy`. — `aws-cdk-lib` 2.260.0, `aws-bedrockagentcore/lib/runtime/runtime.js` (`addExecutionRolePermissions`); the `RUNTIME_*` action lists in `runtime/perms.js`
- Runtime-provided spans (operation `InvokeAgentRuntime`, with attributes such as `session.id`, `latency_ms` and `error_type`) need observability "enabled on your agent resource", meaning the Runtime "Tracing" toggle. — [Observability runtime metrics](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html). The CDK equivalent is `tracingEnabled: true` (`runtime/runtime.d.ts:89-95`), which creates a `TRACES` delivery source to an `XRAY` destination (`runtime/observability.js:44-49`).

### Inferences
- **Telemetry mode today: split.** The agent's spans would go to `aws/spans` and its content to `otel-rt-logs` in `/aws/bedrock-agentcore/runtimes/<agentRuntimeId>-DEFAULT`, but only once Transaction Search is on. Today (destination `XRay`) any spans the Runtime exports are at best stored as classic X-Ray segments. That is not a place Evaluations reads.
- **Is the 0.16.0 pin a problem?** Not for evaluation. It blocks only the unified destination. Split telemetry is fully supported and needs no image change.
- **What unified would take** (skip it for 2026-10-05):
  1. Bump the pin in [Dockerfile:18](../../../agent/ledgerlens/Dockerfile#L18) to `aws-opentelemetry-distro==0.21.0` (or `>=0.18.0`).
  2. Add `UNIFIED_TRACES_DESTINATION_ENABLED: "true"` to `envVars` ([backend-construct.ts:402-437](../../../infra-cdk/lib/backend-construct.ts#L402-L437)). This should already be the default for this agent; setting it explicitly removes the doubt.
  3. Add a statement to `AgentCoreRole` ([agentcore-role.ts](../../../infra-cdk/lib/utils/agentcore-role.ts)): `actions: ["logs:PutResourcePolicy"]`, `resources: ["arn:aws:logs:<region>:<acct>:log-group:/aws/bedrock-agentcore/runtimes/ledgerlens_bank_assistant_ledgerlens_agent-*"]`.
  4. Optionally add `OTEL_PYTHON_DISABLED_INSTRUMENTATIONS: "aws_mcp"` (see Q5).
  5. Rebuild the image and run `cdk deploy`.

  This costs a redeploy. The sibling note says a redeploy must wait for code review and resets `USER_CUSTOMER_IDS_MAP` ([architecture_runner_contract.md:595](architecture_runner_contract.md)). The only gain is that batch jobs can use `logGroupNamePrefixes`, plus one log group per agent.
- **Runtime "Tracing" toggle is not needed for evaluation.** It adds the service-side `InvokeAgentRuntime` span, which is not a Strands span. Use it only as a fallback if the smoke test (Q10, step 3) shows no Strands spans.

### Gaps
- **Unverified:** which OTEL variables the Runtime injects into a custom (CDK, Docker) container, and whether agent spans flow without the Runtime "Tracing" toggle. The docs only say instrumentation is automatic. One traced session settles both (Q10, step 3).
- **Unverified:** whether a Runtime created after 2026-07-20 but running ADOT 0.16.0 ever writes anything to a `spans` stream. The docs say older ADOT "ignore[s]" the destination, so expect `aws/spans` only.
- ADOT 0.21.0 was not exercised with strands-agents 1.32.0. Compatibility rests only on the version ranges in `METADATA`.

---

## Q2. Transaction Search and Gateway tracing: exact steps, CDK options, cost, time to take effect

### Takeaway
Transaction Search is one account-wide setting. It takes three CLI calls, or two CloudFormation resources: `AWS::Logs::ResourcePolicy` plus `AWS::XRay::TransactionSearchConfig`, which CDK 2.260.0 exposes as `xray.CfnTransactionSearchConfig`. Allow about 10 minutes for it to take effect.

Gateway tracing has no Gateway L2 property. Enable it with the console toggle or with three CloudWatch Logs vended-delivery resources (`TRACES` source, `XRAY` destination, delivery). CDK's own `@internal` helper builds exactly that pattern.

For about 300 sessions, span cost is cents.

### Cited Findings
**Enabling Transaction Search**
- API steps:
  1. `aws logs put-resource-policy` allowing `xray.amazonaws.com` `logs:PutLogEvents` on `log-group:aws/spans:*` and `log-group:/aws/application-signals/data:*`, with `aws:SourceArn` `arn:aws:xray:<region>:<acct>:*` and `aws:SourceAccount` conditions;
  2. `aws xray update-trace-segment-destination --destination CloudWatchLogs`;
  3. optionally `aws xray update-indexing-rule --name "Default" --rule '{"Probabilistic": {"DesiredSamplingPercentage": N}}'`.

  Console: CloudWatch > Application Signals (APM) > Transaction search > Enable, and tick "ingest spans as structured logs". — [Add observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html)
- Timing: "After you enable Transaction Search, it can take ten minutes for spans to become available for search and analysis." The alternative console path is Settings > Account > X-Ray traces > Transaction Search > Edit. "You can index 1% of traces at no cost… Wait till Ingest OpenTelemetry spans shows Enabled before sending traces." — [Get started with AgentCore Observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-get-started.html)
- Scope and permissions: Transaction Search "is configured for the entire account and switches all spans ingestion through X-Ray into cost effective collection mode using Amazon CloudWatch Pricing", and indexes 1% of spans free. The enabling principal needs:
  - `xray:GetTraceSegmentDestination`, `UpdateTraceSegmentDestination`, `GetIndexingRules` and `UpdateIndexingRule`;
  - `logs:CreateLogGroup`, `CreateLogStream` and `PutRetentionPolicy` on the two log groups;
  - `logs:PutResourcePolicy` and `DescribeResourcePolicies`;
  - `application-signals:StartDiscovery`.

  — [Enable transaction search](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Enable-TransactionSearch.html)
- CloudFormation: "To enable Transaction Search using CloudFormation, you need to create the following two resources. `AWS::Logs::ResourcePolicy`, `AWS::XRay::TransactionSearchConfig`." Also: "Make sure Transaction Search is disabled before you enable using AWS CDK or CloudFormation." Verify with `aws xray get-trace-segment-destination`, which should return `{"Destination": "CloudWatchLogs", "Status": "ACTIVE"}`. — [Using Transaction Search with CloudFormation](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Transaction-Search-Cloudformation.html)
- `AWS::XRay::TransactionSearchConfig` has one optional property, `IndexingPercentage` (0–100). `Ref` returns the account ID. — [CFN reference](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-xray-transactionsearchconfig.html). The installed `aws-cdk-lib` 2.260.0 has `class CfnTransactionSearchConfig` with `indexingPercentage?: number` (`aws-xray/lib/xray.generated.d.ts:765-772`).
- Current account state (from the on-hold doc, not re-read): the destination is `XRay` / `ACTIVE`, so Transaction Search is off. — [2026-10-03-eval-observability-on-hold.md, L7](../../docs/analysis/2026-10-03-eval-observability-on-hold.md)

**Enabling Gateway tracing**
- Console: Gateways > (gateway) > Tracing > Edit > Enable. "Tracing will be enabled for the selected gateway and spans will be available in the `aws/spans` log group." "You must have CloudWatch Transaction Search enabled before you can enable tracing." — [Add observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html)
- SDK path: `logs.put_delivery_source(logType="TRACES", resourceArn=<gateway ARN>)`, then `put_delivery_destination(deliveryDestinationType='XRAY')`, then `create_delivery`. The same doc says tracing delivery sources "are only applicable for memory and gateway resources". That conflicts with the CDK Runtime `tracingEnabled`, which builds the same pattern for a runtime ARN. — [Add observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html)
- CDK 2.260.0:
  - The `Gateway` L2 has no tracing property. Only `runtime/*.d.ts` declares `tracingEnabled` and `loggingConfigs`.
  - The internal helper `configureTracingDelivery(scope, sourceArn)` is exported from the module but marked `@internal` (`runtime/observability.d.ts:88-95`).
  - The helper creates `logs.CfnDeliverySource({logType: "TRACES", resourceArn})`, a stack-level `xray.CfnResourcePolicy` allowing `delivery.logs.amazonaws.com` `xray:PutTraceSegments` (conditions `logs:LogGeneratingResourceArns`, `aws:SourceAccount`, and `aws:SourceArn` = `logs:…:delivery-source:*`), `logs.CfnDeliveryDestination({deliveryDestinationType: "XRAY"})` and `logs.CfnDelivery`.

  — `aws-cdk-lib/aws-bedrockagentcore/lib/runtime/observability.js:44-49`
- The repo builds the Gateway at [backend-construct.ts:854-865](../../../infra-cdk/lib/backend-construct.ts#L854-L865) and stores `gateway.gatewayArn`, `gatewayId` and `gatewayUrl` (lines 1044-1078).

**Cost**
- AgentCore pricing example: "10 GB × $0.35/GB = $3.50" for spans and "6 GB × $0.50/GB" for event logs. "Most development environment observability data volumes are low enough that observability costs are near zero." — [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)

### Inferences
- **Recommended for the deadline:** enable Transaction Search with the CLI, as `AWS_PROFILE=ledgerlens` in `us-east-1` (the user's memory notes that the `hackathon` profile is read-only). Keep it out of the app stack:
  - it is an account-wide singleton;
  - `cdk destroy` would remove it;
  - FAST deliberately leaves it out of the stack ([docs/OBSERVABILITY.md:3-9](../../../docs/OBSERVABILITY.md#L3-L9)).

  If IaC is wanted later, put the two resources in a tiny separate stack.
- **Gateway tracing for the deadline:** use the console toggle. No deploy is needed. For reproducibility later, add L1s inside `createAgentCoreGateway`, after line 865 of [backend-construct.ts](../../../infra-cdk/lib/backend-construct.ts#L854-L865). This mirrors CDK's internal helper and is untested:
  ```ts
  import * as xray from "aws-cdk-lib/aws-xray"
  const gwTraceSrc = new logs.CfnDeliverySource(this, "GatewayTracesSource", {
    name: `${config.stack_name_base}-gw-traces`, logType: "TRACES", resourceArn: gateway.gatewayArn })
  const gwXrayPolicy = new xray.CfnResourcePolicy(this, "GatewayTracesXRayPolicy", {
    policyName: `${config.stack_name_base}-gw-traces`,
    policyDocument: cdk.Stack.of(this).toJsonString({ Version: "2012-10-17", Statement: [{
      Effect: "Allow", Principal: { Service: "delivery.logs.amazonaws.com" },
      Action: "xray:PutTraceSegments", Resource: "*",
      Condition: { "ForAllValues:ArnLike": { "logs:LogGeneratingResourceArns": [gateway.gatewayArn] },
                   StringEquals: { "aws:SourceAccount": this.account },
                   ArnLike: { "aws:SourceArn": `arn:aws:logs:${this.region}:${this.account}:delivery-source:*` } } }] }) })
  const gwTraceDst = new logs.CfnDeliveryDestination(this, "GatewayTracesDest", {
    name: `${config.stack_name_base}-gw-traces-xray`, deliveryDestinationType: "XRAY" })
  gwTraceDst.addDependency(gwXrayPolicy)
  const gwTraceDelivery = new logs.CfnDelivery(this, "GatewayTracesDelivery", {
    deliverySourceName: gwTraceSrc.name, deliveryDestinationArn: gwTraceDst.attrArn })
  gwTraceDelivery.addDependency(gwTraceSrc); gwTraceDelivery.addDependency(gwTraceDst)
  ```
  Do not combine this with the console toggle on the same gateway: pick one.
- **Span volume estimate** (not measured):
  - Each invocation emits one `invoke_agent`, a few `execute_event_loop_cycle`, `chat` and `execute_tool` spans, plus ADOT HTTP, botocore and ASGI spans.
  - The event records repeat the conversation on every `chat` span. The prompt template file alone is 13 KB ([system_prompt.py](../../../agent/ledgerlens/tools/system_prompt.py)).
  - A two-invocation session is probably 0.3–1 MB in total, so 300 sessions come to roughly 0.1–0.3 GB.
  - At $0.35/GB for spans and $0.50/GB for logs, that is **under $0.50**. Even 10× is under $5.
- Turning Transaction Search on also routes the account's other X-Ray traces (for example the feedback API, `tracingEnabled: true` at [backend-construct.ts:652](../../../infra-cdk/lib/backend-construct.ts#L652)) into `aws/spans`. The cost is negligible at hackathon volume.

### Gaps
- The CloudFormation/CDK Gateway `TRACES` delivery was not deployed or tested. The verification note's item 5 is still open.
- The exact CloudWatch per-GB rates for Transaction Search spans were taken from the AgentCore pricing example, not from the CloudWatch pricing table, which was not read.
- Whether the X-Ray resource-policy count limits matter: a July 2026 release note says "Unlimited X-Ray Policy Limits", but its body was not read.

---

## Q3. CDK evaluator constructs in the installed aws-cdk-lib: API, required props, version, stability

### Takeaway
`aws-cdk-lib` **2.260.0** includes **stable**, not alpha, L2s:
- `Evaluator`, which takes `EvaluatorConfig.codeBased({lambdaFunction, timeout?})` or `.llmAsAJudge(...)`;
- `OnlineEvaluationConfig`, which takes `EvaluatorSelector.builtin/custom` and `DataSourceConfig.fromAgentRuntimeEndpoint(runtime)`.

The code-based construct grants the service invoke rights on the Lambda. The online construct creates its own execution role. There is no construct for batch jobs or datasets.

### Cited Findings
- **Version:** `infra-cdk/package.json` declares `"aws-cdk-lib": "^2.260.0"` ([package.json](../../../infra-cdk/package.json)). `package-lock.json` locks `node_modules/aws-cdk-lib` at `2.260.0` ([package-lock.json:2225-2228](../../../infra-cdk/package-lock.json#L2225-L2228)). The installed copy in `D:\Proyectos\ledgerlens-bank-assistant\infra-cdk\node_modules\aws-cdk-lib\package.json` reports `2.260.0`.
- **Stability:** the jsii manifest (`node_modules/aws-cdk-lib/.jsii.gz`) marks `aws_bedrockagentcore.Evaluator`, `OnlineEvaluationConfig`, `EvaluatorConfig` and `Runtime` as `stable`. They are in `aws-cdk-lib`, not an `-alpha` package. The repo already imports `aws-cdk-lib/aws-bedrockagentcore` ([backend-construct.ts:11](../../../infra-cdk/lib/backend-construct.ts#L11)).
- **`Evaluator`** (`lib/evaluation/custom-evaluator.d.ts:20-58, 101`):
  - required props are `evaluatorName` (pattern `^[a-zA-Z][a-zA-Z0-9_]{0,47}$`), `evaluatorConfig` and `level` (`EvaluationLevel.SESSION|TRACE|TOOL_CALL`);
  - optional props are `description` (up to 200 characters) and `tags`;
  - attributes are `evaluatorArn`, `evaluatorId`, `evaluatorName` and `status`;
  - it can import an existing evaluator with `fromEvaluatorId`, `fromEvaluatorArn` or `fromEvaluatorAttributes`;
  - it maps to `@resource AWS::BedrockAgentCore::Evaluator`.
- **`EvaluatorConfig.codeBased(options: CodeBasedOptions)`** takes `lambdaFunction: lambda.IFunction` (required) and an optional `timeout?: Duration`. The default timeout is the service's 60 s, and the documented range is 1–300 s. — `evaluator-config.d.ts:74-92, 183`
  - The implementation emits `{codeBased: {lambdaConfig: {lambdaArn, lambdaTimeoutInSeconds?}}}` (`evaluator-config.js`).
  - The `Evaluator` construct then calls `lambdaFunction.addPermission("BedrockAgentCoreEvaluatorInvoke", {principal: ServicePrincipal("bedrock-agentcore.amazonaws.com"), sourceAccount, sourceArn: <evaluator ARN>})` (`custom-evaluator.js:60`).
- **`EvaluatorConfig.llmAsAJudge`** takes `instructions`, `modelId`, `ratingScale` (`EvaluatorRatingScale.categorical|numerical`), plus optional `inferenceConfig` and `additionalModelRequestFields`. Reference-input placeholders are "only compatible with on-demand evaluation, not online". — `evaluator-config.d.ts:23-67, 174`
- **`OnlineEvaluationConfig`** (`online-evaluation.d.ts:22-37, 68`; `types.d.ts:241-301`):
  - required props are `onlineEvaluationConfigName` (same name pattern), `evaluators: EvaluatorSelector[]` (CDK validates 1–10) and `dataSource: DataSourceConfig`;
  - optional props are `executionRole`, `description`, `samplingPercentage` (default **10**, range 0.01–100), `filters` (up to 5), `sessionTimeout` (default **15 min**, range 1–1440 min), `executionStatus` (default `ENABLED`) and `tags`.
- **`DataSourceConfig`:**
  - `fromAgentRuntimeEndpoint(runtime, endpoint?)` builds `logGroupNames: ["/aws/bedrock-agentcore/runtimes/${agentRuntimeId}-${endpoint ?? "DEFAULT"}"]` and `serviceNames: ["${agentRuntimeName}.${endpoint}"]` (`data-source.d.ts:80`; `data-source.js` `buildFromRuntime`);
  - `fromCloudWatchLogs({logGroupNames (1–5), serviceNames (exactly 1)})` is the alternative (`types.d.ts:216-235`).
- **Default online execution role** (`online-evaluation.js:67-68`; `perms.js`):
  - trust: `bedrock-agentcore.amazonaws.com`, with SourceAccount, ResourceAccount and SourceArn limited to `evaluator/*` and `online-evaluation-config/*`;
  - `logs:DescribeLogGroups` on `*`;
  - `logs:StartQuery` and `GetQueryResults` on the data-source log groups **and `aws/spans`**;
  - `logs:CreateLogGroup`, `CreateLogStream` and `PutLogEvents` on `/aws/bedrock-agentcore/evaluations/*`;
  - `logs:DescribeIndexPolicies` and `PutIndexPolicy` on `aws/spans`;
  - `bedrock:InvokeModel*` on foundation models and inference profiles.
- **`BuiltinEvaluator`** has 13 static values: CORRECTNESS, FAITHFULNESS, HELPFULNESS, RESPONSE_RELEVANCE, CONCISENESS, COHERENCE, INSTRUCTION_FOLLOWING, REFUSAL, GOAL_SUCCESS_RATE, TOOL_SELECTION_ACCURACY, TOOL_PARAMETER_ACCURACY, HARMFULNESS and STEREOTYPING. It has **no Trajectory\*** values, but the constructor `new BuiltinEvaluator(value: string)` is public. — `types.d.ts:21-82`
- **Prerequisites** in the CDK README (local copy at `node_modules/aws-cdk-lib/aws-bedrockagentcore/README.md:2726-2733`): "CloudWatch Transaction Search enabled — this creates the `aws/spans` log group required by the evaluation service", and "ADOT SDK instrumenting your agent to emit traces".
- The API allows up to 25 evaluators per online config — [Create online evaluation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/create-online-evaluations.html). CDK still validates 10 (`online-evaluation.d.ts:29`).
- The CloudFormation types `AWS::BedrockAgentCore::Evaluator` and `AWS::BedrockAgentCore::OnlineEvaluationConfig` exist, and there is no resource for batch jobs or datasets. — verification note, row 13

### Inferences
- Proposed code for the next allowed deploy, in [backend-construct.ts](../../../infra-cdk/lib/backend-construct.ts). Put it after the Runtime is created (around line 463, where `this.agentRuntime` exists), behind a new `config.yaml` flag (for example `evaluation.enabled`, which needs an `AppConfig` field in `lib/utils/config-manager.ts`):
  ```ts
  // Code-based evaluator: the pure-Python grader behind a span adapter (see Q10, step 7)
  const evalFn = new PythonFunction(this, "PolicyChecksEvaluatorFn", {
    functionName: `${config.stack_name_base}-eval-policy-checks`,
    runtime: lambda.Runtime.PYTHON_3_13, architecture: lambda.Architecture.ARM_64,
    entry: path.join(__dirname, "..", "..", "evaluation", "agentcore_evaluator"), // new folder
    index: "handler.py", handler: "lambda_handler",
    timeout: cdk.Duration.seconds(90), memorySize: 512,
  })
  const policyEvaluator = new agentcore.Evaluator(this, "PolicyChecksEvaluator", {
    evaluatorName: "ll_policy_checks", level: agentcore.EvaluationLevel.SESSION,
    evaluatorConfig: agentcore.EvaluatorConfig.codeBased({ lambdaFunction: evalFn, timeout: cdk.Duration.seconds(60) }),
    description: "LedgerLens record-and-policy checks over Strands spans",
  })
  new cdk.CfnOutput(this, "PolicyEvaluatorId", { value: policyEvaluator.evaluatorId })

  // Online evaluation for the demo (no ground truth)
  new agentcore.OnlineEvaluationConfig(this, "OnlineEval", {
    onlineEvaluationConfigName: `${config.stack_name_base.replace(/-/g, "_")}_online`,
    evaluators: [
      agentcore.EvaluatorSelector.builtin(agentcore.BuiltinEvaluator.GOAL_SUCCESS_RATE),
      agentcore.EvaluatorSelector.builtin(agentcore.BuiltinEvaluator.HELPFULNESS),
    ],
    dataSource: agentcore.DataSourceConfig.fromAgentRuntimeEndpoint(this.agentRuntime),
    samplingPercentage: 100, sessionTimeout: cdk.Duration.minutes(5),
  })
  ```
- **Order matters:** create the `OnlineEvaluationConfig` only after Transaction Search is on, because `aws/spans` must exist.
- **Locking:** do not put `ll_policy_checks` into an *enabled* online config while you are still iterating on it. An enabled config locks custom evaluators (Q8). A Lambda code update does not change the evaluator resource, but evaluator-property changes would fail while it is locked.
- **Avoiding a redeploy:** both resources can be created instead with boto3 (`bedrock-agentcore-control.create_evaluator` / `create_online_evaluation_config`) or in the console. The online config can create its execution role in the console. This is the deadline path (Q10).

### Gaps
- **Untested:** whether `CreateEvaluator` validates the Lambda (`lambda:GetFunction`) before the CDK `addPermission` exists. CloudFormation ordering could make the first deploy fail. Not tested; no doc found.
- The CDK `sessionTimeout` range (1–1440 min) differs from the console's "between 1 and 60 minutes" ([Create online evaluation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/create-online-evaluations.html)). Which one the API enforces was not checked.

---

## Q4. Running evaluations: on-demand vs batch, code-based in batch, ingestion wait, and the fit for about 10 personas × variants × 3 trials

### Takeaway
For the runner, the backbone is **on-demand**: one `EvaluationClient.run` per session, after a wait of about 180 s. It is synchronous, it supports code-based evaluators (documented), and it returns per-session results the runner can join directly to its local grades.

**Batch** is a good optional single AWS-native job per run:
- ≤10 evaluators;
- ≤500 sessions with inline ground truth;
- 25% cheaper;
- per-session rows in CloudWatch.

But AWS still documents custom (code-based) evaluators only for online and on-demand, so batch should run **built-ins only**.

One correction to the earlier sketches: this Runtime accepts **only JWT bearer auth**, so the boto3 `invoke_agent_runtime` (SigV4) call in the verification note's sketch (a) cannot invoke it. The runner must POST over HTTPS with the Cognito token.

### Cited Findings
**On-demand**
- One evaluator per `Evaluate` call; synchronous. — verification note, row 4a
- The SDK's `EvaluationClient.run(evaluator_ids, session_id, agent_id=None, look_back_time=timedelta(days=7), log_group_name=None, trace_id=None, reference_inputs=None)` does four things:
  1. derives `/aws/bedrock-agentcore/runtimes/{agent_id}-DEFAULT` when only `agent_id` is given;
  2. collects spans;
  3. looks up each evaluator's level;
  4. calls `evaluate()` with at most 10 target IDs per request.

  — [bedrock-agentcore 1.24.0](https://pypi.org/project/bedrock-agentcore/1.24.0/), `bedrock_agentcore/evaluation/client.py:141-184`
- The span collector runs a Logs Insights query (`fields @timestamp, @message | filter attributes.session.id = "<sid>" | filter ispresent(scope.name) | …`) against **both** `aws/spans` and the runtime log group. — `evaluation/agent_span_collector/agent_span_collector.py:108-121`. It therefore works in split mode, and the caller needs `logs:StartQuery` and `logs:GetQueryResults` on both groups.
- Code-based on-demand is documented: "use the custom code-based evaluator with the `Evaluate` API the same way you would use any other evaluator. The service handles Lambda invocation, parallel fan-out, and result mapping automatically". Example: `EvaluationClient(region_name=…).run(evaluator_ids=["code-based-evaluator-id"], session_id=…, log_group_name=…)`. — [Custom code-based evaluator](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-based-evaluators.html)

**Batch**
- Request limits: `evaluators` at most 10; `evaluationMetadata.sessionMetadata` at most 500 entries; `dataSourceConfig.cloudWatchLogs` takes `serviceNames` (exactly 1, by convention `{RuntimeName}.DEFAULT`) and either `logGroupNames` (1–10) or `logGroupNamePrefixes` (1–5). — [Start batch evaluation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/batch-evaluations-start.html)
- Filters and output: `filterConfig.sessionIds` / `timeRange`; `outputConfig.cloudWatchConfig.resultDestination` = `DEDICATED_LOG_GROUP` (default, optional custom `logGroupName`) or `SOURCE_LOG_GROUP`; optional `metricsNamespace` (default `Bedrock-AgentCore/Evaluations`). Status values are `COMPLETED`, `COMPLETED_WITH_ERRORS`, `FAILED` and `STOPPED`. Prefix matching for Runtime log groups needs unified spans ("set `UNIFIED_TRACES_DESTINATION_ENABLED=true`"). — [Start batch evaluation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/batch-evaluations-start.html)
- Batch takes ground truth "Via `sessionMetadata` with inline ground truth". Its results are "Aggregate summaries with per-evaluator averages, plus per-session detail in CloudWatch". — [Batch evaluation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/batch-evaluations.html). Batch went GA in July 2026 — [Release notes](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html)

**Code-based evaluators in batch: still undocumented**
- Built-ins: "You can use built-in evaluators with on-demand, batch, and online evaluations." — [Built-in evaluators](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/built-in-evaluators-overview.html)
- Custom evaluators: "You can use custom evaluators with both online and on-demand evaluations." Batch is not mentioned. — [Custom evaluators](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/custom-evaluators.html)
- The code-based page has sections only for on-demand and online. — [Custom code-based evaluator](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-based-evaluators.html)
- The SDK's batch model only hints at more: `evaluator_ids` is "List of evaluator IDs (built-in names or custom ARNs)". — `evaluation/runner/batch/batch_evaluation_models.py:306`
- No newer release note changes this; the September and October 2026 entries add TypeScript framework support and gateway CA support.

**Timing**
- "invoke your agent and wait 2–5 minutes for CloudWatch to ingest the telemetry data" — [Ground truth evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ground-truth-evaluations.html)
- Put-to-get latency for complete traces is under 10 s — [Release notes](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html)
- The SDK's batch data source waits `ingestion_delay_seconds` in `pre_evaluation_run_hook` before calling the API (`batch_evaluation_models.py:86-89`). The SDK default delay is 180 s (verification note, row 6).

**Runtime auth**
- "An AgentCore Runtime can support either IAM SigV4 or JWT Bearer Token based inbound auth, but not both simultaneously." — [JWT inbound auth](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html)
- The Runtime is created with `RuntimeAuthorizerConfiguration.usingJWT(...)` ([backend-construct.ts:242-245, 450](../../../infra-cdk/lib/backend-construct.ts#L242-L245)).
- The repo's remote client POSTs to `https://bedrock-agentcore.<region>.amazonaws.com/runtimes/<escaped ARN>/invocations?qualifier=DEFAULT` with `Authorization: Bearer`, `X-Amzn-Trace-Id` and `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`. — [test-agent.py:355-372](../../../test-scripts/test-agent.py#L355-L372); [client.ts:32-54](../../../frontend/src/lib/agentcore-client/client.ts#L32-L54). The Cognito login is `authenticate_cognito` with `USER_PASSWORD_AUTH` ([scripts/utils.py:119-151](../../../scripts/utils.py#L119-L151)).

**Session IDs and quotas**
- Session ID length: 33–100 characters from `[A-Za-z0-9_-]`, starting alphanumeric (verification note, row 9). `generate_session_id()` returns a 36-character UUID4 ([scripts/utils.py:184-186](../../../scripts/utils.py#L184-L186)).
- On-demand quotas: 1,200 evaluations per minute, 1 evaluator per call, 20,000 spans / 200 MB per evaluation. — [aws_evaluation_stack.md, Q1 quotas](../Agent%20evaluation%20signal%20on%20AWS/aws_evaluation_stack.md)

### Inferences
- **Fit for the runner.** Ten personas × 2–3 variants × 3 trials is 60–90 sessions (300 at most).
  - On-demand: 2–3 evaluators per session means 120–900 synchronous calls. That is minutes, well under quota, and the results land in the runner's own records next to the local grade.
  - Batch: one job per run with `filterConfig.sessionIds` = the run's sessions and `sessionMetadata[].groundTruth.inline`. That fits easily under 500. Read the aggregate from `get_batch_evaluation` and the per-session rows from the output log group.
- **Minimal run procedure** (split telemetry; `AGENT_RUNTIME_ID` from the stack output `AgentRuntimeId`, [backend-construct.ts:466-469](../../../infra-cdk/lib/backend-construct.ts#L466-L469)):
  ```python
  import time, boto3
  from bedrock_agentcore.evaluation import EvaluationClient, ReferenceInputs
  REGION, AGENT_RUNTIME_ID = "us-east-1", "<AgentRuntimeId output>"
  SERVICE = "ledgerlens_bank_assistant_ledgerlens_agent.DEFAULT"
  LOG_GROUP = f"/aws/bedrock-agentcore/runtimes/{AGENT_RUNTIME_ID}-DEFAULT"
  # 1. runner: HTTPS POST + Bearer per turn (JWT-only runtime), Yes/No turn sends {"confirmations": [...]}
  #    record {sid, case_id, trial, expected_trajectory, assertions, t_start, t_end} per session
  time.sleep(180)                                   # 2. after the LAST session of the run
  ec = EvaluationClient(region_name=REGION)         # 3. on-demand, per session (SigV4 with AWS_PROFILE=ledgerlens)
  for s in sessions:
      s["aws"] = ec.run(evaluator_ids=["Builtin.TrajectoryInOrderMatch", "Builtin.GoalSuccessRate"],
                        session_id=s["sid"], agent_id=AGENT_RUNTIME_ID,
                        reference_inputs=ReferenceInputs(expected_trajectory=s["expected_trajectory"],
                                                         assertions=s["assertions"]))
  dp = boto3.client("bedrock-agentcore", region_name=REGION)   # 4. optional: one batch job per run
  job = dp.start_batch_evaluation(
      batchEvaluationName=f"ll_run_{run_id}",
      evaluators=[{"evaluatorId": "Builtin.TrajectoryInOrderMatch"}, {"evaluatorId": "Builtin.GoalSuccessRate"}],
      dataSourceConfig={"cloudWatchLogs": {"serviceNames": [SERVICE], "logGroupNames": [LOG_GROUP],
                                           "filterConfig": {"sessionIds": [s["sid"] for s in sessions]}}},
      evaluationMetadata={"sessionMetadata": [{"sessionId": s["sid"], "testScenarioId": s["case_id"],
          "groundTruth": {"inline": {"assertions": [{"text": a} for a in s["assertions"]],
                                     "expectedTrajectory": {"toolNames": s["expected_trajectory"]}}}} for s in sessions]},
      outputConfig={"cloudWatchConfig": {"resultDestination": "DEDICATED_LOG_GROUP",
                                         "logGroupName": "/ledgerlens/eval/batch-results"}})
  # poll get_batch_evaluation(batchEvaluationId=...) every 30 s until a terminal status
  ```
  Add the code-based evaluator ID to step 3 only, not to the batch job, until batch support is confirmed.
- **Batch log group is a guess.** For split telemetry, passing only the runtime log group is an inference from "the service reads spans from `aws/spans` and matches them to their event records". If the job finds 0 sessions, add `aws/spans` to `logGroupNames`.
- **Don't use the dataset runners here.** `OnDemandEvaluationDatasetRunner` and `BatchEvaluationRunner` are preview and own the invocation loop. The local runner already owns the stream recording and the Yes/No clicks.

### Gaps
- **Unverified:** code-based evaluators in `StartBatchEvaluation`, and whether batch passes `sessionMetadata.metadata` or `testScenarioId` into a Lambda. Both are unchanged from the verification note.
- **Unverified:** whether batch needs `aws/spans` listed explicitly in split mode.
- The batch permissions model: the documented request has no execution-role parameter, and the IAM list on [Prerequisites](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluations-prerequisites.html) omits the batch actions. The runner principal will at least need `bedrock-agentcore:StartBatchEvaluation`/`GetBatchEvaluation` (unconfirmed names).

---

## Q5. Built-ins for this agent: which tool names appear in spans, do the session-start calls produce spans, and which LLM judges are worth running

### Takeaway
- **Trajectory names.** On Strands `execute_tool` spans, `gen_ai.tool.name` is the model-visible name **`gateway_<target>___<tool>`**, for example `gateway_block-credit-card-target___block_credit_card`. That is what `Builtin.Trajectory*` ground truth must list. The earlier `<target>___<tool>` advice applies only to Gateway, Cedar and MCP-level spans.
- **Session-start calls.** `get_session_context` and `classify_call_type`, which code calls at session start, produce **no Strands `execute_tool` span**, so they never appear in the evaluator's trajectory. ADOT ≥0.18.0 would add MCP client spans for them, but the evaluation service excludes that scope.
- **LLM judges.** Run `Builtin.GoalSuccessRate` (session level, with assertions) as a diagnostic, at about $0.02–0.04 per session. Skip trace-level and tool-level judges for the deadline.

### Cited Findings
- **Strands tool span names.** Strands builds tool spans from the model's `toolUse`: `"gen_ai.tool.name": tool["name"]`, `"gen_ai.tool.call.id": tool["toolUseId"]`, and span name `f"execute_tool {tool['name']}"`. The agent's `trace_attributes` are copied onto it. — [strands-agents 1.32.0](https://pypi.org/project/strands-agents/1.32.0/), `strands/telemetry/tracer.py:378-410`; `strands/tools/executors/_executor.py:309-311`. `start_tool_call_span` has only that one call site.
- **MCP prefixing.** `MCPClient` with a prefix registers each tool as `f"{prefix}_{tool.name}"` (`strands/tools/mcp/mcp_client.py:424-427`) but calls the server with the original name (`mcp_agent_tool.py:113-115`). The agent's client is built with `prefix="gateway"` ([gateway.py:172-178](../../../agent/ledgerlens/tools/gateway.py#L172-L178)).
- **Gateway naming.** Gateway names tools `${target_name}___${tool_name}` — [Gateway tool naming](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-tool-naming.html). LedgerLens target names are `<slug>-target`; fraud detection uses `fraud-detection-target` so the full name stays under 64 characters. — [backend-construct.ts:875-891, 918-920](../../../infra-cdk/lib/backend-construct.ts#L875-L891)
- **How the service reads tool spans.** It classifies spans by `gen_ai.operation.name` (`execute_tool`), takes "the tool name from the `gen_ai.tool.name` attribute on the execute tool span", and reads Python Strands spans under scope `strands.telemetry.tracer`. — [Strands telemetry for Evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks-strands.html)
- **Trajectory matchers.** They "compare the agent's actual tool call sequence against an expected sequence of tool names". They are session level and programmatic, with zero tokens. ExactOrder means "same tools, same order, no extras"; InOrder allows extras; AnyOrder ignores order. — [Ground truth evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ground-truth-evaluations.html)
- **Session-start calls bypass the executor.** `apply_session_context` finds the tool in `agent.tool_registry.registry` by suffix and runs `registry[name].stream(tool_use, {})` directly, with `toolUseId` `session-start___get_session_context`. It does this concurrently for both tools, once per session. — [session_context.py:30-32, 52-68, 76-81, 99-103](../../../agent/ledgerlens/tools/session_context.py#L52-L68); called at [ledgerlens_agent.py:184](../../../agent/ledgerlens/ledgerlens_agent.py#L184). This skips `ToolExecutor`, the only place that opens `execute_tool` spans.
- **ADOT ≥0.18.0 MCP instrumentation.**
  - It wraps `mcp.shared.session.BaseSession.send_request`.
  - For a `CallToolRequest` it names the span `mcp tools/call <name>` and sets `gen_ai.tool.name` to the MCP name (`<target>___<tool>`, unprefixed) and **`gen_ai.operation.name = execute_tool`**, plus tool arguments and result.
  - The scope is `amazon.opentelemetry.distro.instrumentation.mcp`.
  - It auto-loads when `mcp>=1.10,<2` is installed (the agent pins `mcp==1.28.1`, [requirements.txt](../../../agent/ledgerlens/requirements.txt)).
  - Disable it with `OTEL_PYTHON_DISABLED_INSTRUMENTATIONS=aws_mcp`.

  — ADOT 0.21.0 wheel, `instrumentation/mcp/__init__.py:39-48`, `_wrappers.py:117-122`, `README.rst` ("Disable the instrumentation")
- **The service ignores those spans.** It "selects how to read each span from the span's `scope.name`". MCP instrumentation, HTTP clients, web frameworks and botocore scopes "are excluded … so that their spans do not produce spurious agent, tool, or inference spans". — [Generic framework support](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks-generic.html); [Supported frameworks](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks.html)
- **Built-in judges.** Each has a fixed prompt and an undisclosed model. Levels: GoalSuccessRate is session level (uses `assertions`); Correctness (uses `expectedResponse`), Helpfulness, Faithfulness and others are trace level; ToolSelectionAccuracy and ToolParameterAccuracy are tool level. — verification note, rows 2b, 10a-b; [Built-in evaluators](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/built-in-evaluators-overview.html)
- **The ground-truth GoalSuccessRate is lenient.** It accepts "an alternative approach" to an assertion, so ordering and "must not call X" rules belong in code. — verification note, row 2f
- **Pricing.** Built-in evaluators cost $0.0024 per 1K input tokens and $0.012 per 1K output tokens; batch costs $0.0018 and $0.009. AWS's worked example is 15,000 input and 300 output tokens per evaluation, or $1,782 for 45,000 evaluations (≈ $0.0396 each). — [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)
- **Prompt and tool size.** The tool specs total about 13 KB across nine tools, and the prompt template file is 13 KB. — [gateway/tools/*/tool_spec.json](../../../gateway/tools); [system_prompt.py](../../../agent/ledgerlens/tools/system_prompt.py)

### Inferences
- **Names to put in `expectedTrajectory`.** Use the Strands span names, not the Gateway names:

  | Tool | `gen_ai.tool.name` on Strands spans | Cedar, Gateway and MCP-span name |
  |---|---|---|
  | list_credit_cards | `gateway_list-credit-cards-target___list_credit_cards` | `list-credit-cards-target___list_credit_cards` |
  | list_card_transactions | `gateway_list-card-transactions-target___list_card_transactions` | `list-card-transactions-target___list_card_transactions` |
  | transaction_fraud_detection | `gateway_fraud-detection-target___transaction_fraud_detection` | `fraud-detection-target___transaction_fraud_detection` |
  | explain_transaction | `gateway_explain-transaction-target___explain_transaction` | `explain-transaction-target___explain_transaction` |
  | block_credit_card | `gateway_block-credit-card-target___block_credit_card` | `block-credit-card-target___block_credit_card` |
  | open_claim | `gateway_open-claim-target___open_claim` | `open-claim-target___open_claim` |
  | human_agent_hand_off | `gateway_human-agent-hand-off-target___human_agent_hand_off` | `human-agent-hand-off-target___human_agent_hand_off` |
  | get_session_context, classify_call_type | absent, unless the model also calls them | `<slug>-target___<tool>` |

  This corrects the verification note's sketch (a) and its "`expectedTrajectory` must use `<target>___<tool>`" line for this agent.
- **Which matcher.** Use `Builtin.TrajectoryInOrderMatch` as the AWS-side trajectory check. `ExactOrderMatch` is brittle here: confirmation sessions repeat the write tool (Q6), and the model may list cards before transactions or call them in either order. None of the three matchers can express "must NOT call X". That stays with the local grader or the code-based evaluator.
- **Filter tool spans by scope in the code-based Lambda.** It receives raw `sessionSpans`. Filter on `scope.name == "strands.telemetry.tracer"` as well as `gen_ai.operation.name == "execute_tool"`. The verification note's sketch (b) filters only on the operation, so it would double-count once ADOT ≥0.18.0 adds MCP spans. Those MCP spans are, however, the only span evidence of the two session-start calls.
- **Judges worth running, as diagnostics only:**
  - `Builtin.GoalSuccessRate` with 2–3 assertions per case (session level, one evaluation per session). The judge input is roughly the conversation, tool I/O and nine tool descriptions, about 6–15K tokens. That gives ≈ $0.015–0.04 per session on-demand, ≈ $0.011–0.03 in batch, and ≈ $5–12 for 300 sessions.
  - Optionally `Builtin.Refusal` or `Builtin.Harmfulness` on the injection cases only.
- **Judges to skip:**
  - `Correctness`, which needs a per-trace `expectedResponse`.
  - `Helpfulness` and other trace-level judges, because confirmation traces end in an interrupt (Q6).
  - `ToolSelectionAccuracy` and `ToolParameterAccuracy`, which produce one evaluation per tool span and so multiply cost.
- **Judge language is untested.** The judges' Spanish and Portuguese quality is undocumented. Report agreement with the local grader rather than treating judge scores as truth.

### Gaps
- **Not observed yet:** the exact `gen_ai.tool.name` on live spans. The value above comes from source code; check it in the first traced session.
- Whether the trajectory evaluators count `execute_tool` spans that carry no `gen_ai.tool.status`, such as interrupted calls (Q6). Undocumented.
- Billing for Trajectory\* matchers (zero tokens, so presumably $0) and for code-based evaluators (presumably the custom $1.50 per 1K): neither is on the pricing page.

---

## Q6. Interrupted sessions: how the proposal and resume invocations appear in spans, and what session-level evaluators see

### Takeaway
A confirmation session is two Runtime invocations with the **same `session.id`**. The frontend and test client send a fresh `X-Amzn-Trace-Id` per request, so they are **two traces**. SESSION-level evaluators (trajectory, GoalSuccessRate, a SESSION code-based evaluator) receive both. TRACE-level judges score each half alone.

From the Strands source, each half leaves an `execute_tool` span for the write tool:
- **Yes:** the tool appears twice, once interrupted (no status) and once executed.
- **No:** it appears interrupted, then `status: error` (cancelled).

Trajectory matchers therefore cannot tell Yes from No, which means status-aware checks have to be done in code.

### Cited Findings
- **The confirmation hook.** It raises a Strands interrupt before `block_credit_card`, `open_claim` or `human_agent_hand_off` runs, so the agent "stops with stop_reason "interrupt"". The runtime streams a `confirmation` event. The click returns as the next request, where only Yes runs the tool and No cancels it. — [confirmation_hook.py:7-12, 53-78, 80-105, 108-115](../../../agent/ledgerlens/tools/confirmation_hook.py#L53-L78)
- **The resume path.** When `agent._interrupt_state.activated`, the next request's prompt becomes `resume_prompt(...)`, a list of `interruptResponse` blocks. — [ledgerlens_agent.py:186-191](../../../agent/ledgerlens/ledgerlens_agent.py#L186-L191)
- **Session and trace IDs on the wire.**
  - Each call sends the same `runtimeSessionId` in the body and in the `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` header, and a newly generated `X-Amzn-Trace-Id`. — [client.ts:36-54](../../../frontend/src/lib/agentcore-client/client.ts#L36-L54); [test-agent.py:59-67, 365-366](../../../test-scripts/test-agent.py#L59-L67)
  - The agent also sets `session.id`, `user.id` and `prompt.version` as Strands `trace_attributes` from the payload's `runtimeSessionId`. — [ledgerlens_agent.py:148-153, 165](../../../agent/ledgerlens/ledgerlens_agent.py#L148-L153)
- **Interrupted tool span.** The span is opened before the hook runs. On a `ToolInterruptEvent` it is ended with `tool_result=None`, so it gets no `gen_ai.tool.status` and no result event. — `strands/tools/executors/_executor.py:309-323`; `strands/telemetry/tracer.py:448-465`
- **Cancelled tool span.** A cancelled call becomes a tool result with `"status": "error"` and the cancel message ("tool cancelled by user" by default). — `_executor.py:161-169`
- **Interrupted agent span.** `AgentResult.__str__` returns the stringified interrupt list when interrupts are present (`strands/agent/agent_result.py:38-50`). `end_agent_span` writes `str(response)` and `finish_reason = str(response.stop_reason)` into the `gen_ai.choice` event (`tracer.py:684-685`). The interrupted trace's "agent response" is therefore the interrupt list, with `finish_reason` `interrupt`.
- **How session-level evaluation works.**
  - Code-based evaluators at `SESSION` receive all reference inputs, and `evaluationTarget` is `None`. — [Custom code-based evaluator](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-based-evaluators.html)
  - The SDK collects spans by `attributes.session.id` across all traces of the session (Q4).
  - Online evaluation treats a session as complete after `sessionTimeout` of inactivity: default 15 min in CDK (`types.d.ts:285-292`), 1–60 min in the console ([Create online evaluation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/create-online-evaluations.html)).

### Inferences
- **Same session, two traces.** Both invocations share `session.id`: from the Runtime header via ADOT baggage, and from `trace_attributes`. So session-level evaluators see the full proposal → click → result arc.
- **Tool sequence per path, for `expectedTrajectory`:**
  - Yes path: `[..., block(interrupted), block(success)]`. `InOrderMatch` passes with `[..., block]`. `ExactOrderMatch` fails unless the write tool is listed twice.
  - No path: `[..., block(interrupted), block(error)]`. A trajectory expecting no block cannot be written with these matchers.

  The grader that matters (status `success` present or absent, the confirmation answer, the Cedar outcome) must read `gen_ai.tool.status`. That is the local grader's job, or the code-based evaluator's.
- **Trace-level judges score the halves badly.** On trace 1, Helpfulness and similar judges see a stringified interrupt dict as the "response". On trace 2 the "user message" is an `interruptResponse` JSON block. Use GoalSuccessRate at session level only.
- **No issue with `stop_reason == "interrupt"` itself.** The span ends normally, so `status.code` should be `OK` (inferred). The risk is only the odd-looking content.
- **Online evaluation splits slow clicks.** If a human waits longer than `sessionTimeout` before clicking, the session is scored without its second half, and the resume is scored again later (inferred). The runner clicks within seconds, so this only affects the online demo. Set `sessionTimeout` to 5–10 minutes.

### Gaps
- **Not observed yet:** the duplicated write-tool spans, the empty status on the interrupted span, and the service-side handling of a span with no status or result. All are derived from strands 1.32.0 source; confirm with one Yes session and one No session.
- Whether the repo's `X-Amzn-Trace-Id` format (`1-<hex>-<uuid4 with dashes>`, not 24 hex digits; [test-agent.py:66-67](../../../test-scripts/test-agent.py#L66-L67)) is accepted or replaced by the Runtime. Either way each request gets its own trace (inferred).

---

## Q7. Without CloudWatch: can locally captured spans be sent to `Evaluate` directly?

### Takeaway
- **Spans from an in-process run: yes, in principle.** `Evaluate` takes caller-supplied `evaluationInput.sessionSpans`. `bedrock-agentcore` 1.24.0 ships a converter from Strands in-memory OTel spans to the required ADOT document format, and an evaluator wrapper that calls `Evaluate` with them. That is an SDK path, not a devguide walkthrough.
- **Spans rebuilt from the deployed agent's stream: undocumented and speculative.** Don't do it.
- **Not for the deadline.** Running LedgerLens in-process needs Memory, Cognito/Gateway token and SSM wiring plus an exporter hook.

### Cited Findings
- On-demand evaluation: "Caller provides spans inline" — [Batch evaluation (comparison table)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/batch-evaluations.html). The `Evaluate` call shape is `evaluationInput={"sessionSpans": session_spans_and_log_events}` — [Ground truth evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ground-truth-evaluations.html); [Custom code-based evaluator](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-based-evaluators.html)
- **The SDK converter.** `convert_strands_to_adot(raw_spans)` takes "OpenTelemetry Span objects from Strands agent" (for example from a `strands_evals` in-memory exporter) and returns "ADOT documents (spans and log records)".
  - Each span becomes `{"resource": {"attributes"}, "scope": {"name", "version"}, "traceId", "spanId", "parentSpanId", "flags", "name", "kind", "startTimeUnixNano", "endTimeUnixNano", "durationNano", "attributes", "status": {"code"}}`.
  - Conversation and tool content becomes log records with `body`, `traceId` and `spanId`. These are built from the `gen_ai.user.message`, `gen_ai.choice`, `gen_ai.assistant.message` and `gen_ai.tool.message` events.

  — [bedrock-agentcore 1.24.0](https://pypi.org/project/bedrock-agentcore/1.24.0/), `bedrock_agentcore/evaluation/span_to_adot_serializer/strands_converter.py:30-129, 137-211`; `adot_models.py:217-262`
- **The SDK wrapper.** `StrandsEvalsAgentCoreEvaluator.evaluate` converts the case's `actual_trajectory` with `convert_strands_to_adot` when it is not already ADOT documents, then calls `client.evaluate(evaluatorId=…, evaluationInput={"sessionSpans": spans})`. — `evaluation/integrations/strands_agents_evals/evaluator.py:112-142`. The SDK reference describes it as wrapping the AgentCore Evaluation API and "automatically convert[ing] Strands OTel spans to AgentCore format" — [aws_evaluation_stack.md, Q2](../Agent%20evaluation%20signal%20on%20AWS/aws_evaluation_stack.md)
- **What the service needs from a span.** The documented Strands schema requires `scope.name = strands.telemetry.tracer`, `gen_ai.operation.name` (`invoke_agent`, `execute_tool` or `chat`), `gen_ai.tool.name`, `session.id`, and content in events or in event records. — [Strands telemetry for Evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks-strands.html)
- **Minimal fallback.** For a custom scope, the service reads `agentcore.invocation.user_prompt` and `agentcore.invocation.agent_response` "from any scope", but these cover only the top-level prompt and response, with no tool spans. — [Generic framework support](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks-generic.html)
- **Local mode in the repo.** It starts the agent on `localhost:8080` and sends a mock JWT. — [test-agent.py:90-110, 204-232, 351](../../../test-scripts/test-agent.py#L90-L110)

### Inferences
- **What is documented:** caller-supplied spans for `Evaluate`, and the Strands span schema.
- **What is SDK-level, not walkthrough-documented:** that in-memory Strands spans → `convert_strands_to_adot` → `Evaluate` is accepted.
- **What is speculative:** turning the deployed agent's SSE stream into span dicts. The stream has no trace or span IDs, timestamps per span, or `gen_ai.*` attributes, so you would be fabricating telemetry. That is a weak story for "AWS-native" and not worth it.
- **What it would take** (post-deadline):
  1. Run the agent locally, using test-agent local mode against the real Memory and Gateway with `AWS_PROFILE=ledgerlens`.
  2. Install an in-memory `SpanExporter` on the global tracer provider; this needs a code hook or a `StrandsTelemetry` setup.
  3. Convert the spans and call `Evaluate` per evaluator.

  Note this evaluates a local copy, not the deployed Runtime.

### Gaps
- Whether `Evaluate` with inline spans works with Transaction Search off. The prerequisites page lists observability "including Transaction Search" generally ([Prerequisites](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluations-prerequisites.html)). No doc states that inline-span `Evaluate` is exempt.
- Whether the service accepts ADOT documents with no `resource.attributes` like `service.name` or `aws.log.group.names`, which the converter copies from the span resource when present. Untested.

---

## Q8. Online evaluation as a cheap demo add

### Takeaway
An online config on the Runtime's DEFAULT endpoint makes scores appear in CloudWatch GenAI Observability > Bedrock AgentCore > Agents > Evaluations, with no ground truth. Use 100% sampling, a 5-minute session timeout, and `Builtin.GoalSuccessRate` (plus `Builtin.Helpfulness` if desired).

It can be created in the console or with boto3 today, with no redeploy, or in CDK at the next deploy. Expect a few dollars for a judging window.

### Cited Findings
- **Ground truth:** none. "Ground truth: Not supported" in online mode, and custom evaluators with reference placeholders are rejected (verification note, row 4e). The batch comparison table also lists online ground truth as "Not supported" — [Batch evaluation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/batch-evaluations.html)
- **API:** `bedrock-agentcore-control.create_online_evaluation_config(onlineEvaluationConfigName, rule={"samplingConfig": {"samplingPercentage": …}}, dataSourceConfig={"cloudWatchLogs": {"logGroupNames": […], "serviceNames": […]}}, evaluators=[{"evaluatorId": …}], evaluationExecutionRoleArn=…, enableOnCreate=True)`. It allows up to 25 evaluators and can use an agent endpoint as the data source. The console can create the service role. "When you create an evaluation configuration with `executionStatus` set to `ENABLED`, the system automatically locks any custom evaluators you've selected." — [Create online evaluation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/create-online-evaluations.html)
- **Results:** default log group `/aws/bedrock-agentcore/evaluations/results/<online-evaluation-config-id>`; metrics in `Bedrock-AgentCore/Evaluations`; events "parented to the original span ID and include the original trace ID and session ID". View them in CloudWatch > GenAI Observability > Bedrock AgentCore > (agent and endpoint) > **Evaluations** tab. — [Results and output](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/results-and-output.html)
- **Latency:**
  - Scores appear after the session-idle timeout, then "within roughly 15 minutes" (verification note, row 6).
  - Scores "now arrive approximately 50% faster" after the pipeline moved off 5-minute rescans — [Release notes](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html)
- **CDK:** defaults are sampling 10% and session timeout 15 min. `fromAgentRuntimeEndpoint` derives the log group and service name, and an execution role is created automatically (Q3).
- **Prerequisite:** Transaction Search must be on first (CDK README, Q3).
- **Pricing:** built-in token rates, as in Q5. — [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)

### Inferences
- **Setup for the demo** (about 20–30 minutes once Transaction Search is on):
  - Console: AgentCore > Evaluation > Create evaluation configuration.
  - Data source: agent endpoint `ledgerlens_bank_assistant_ledgerlens_agent` / DEFAULT.
  - Evaluators: `Builtin.GoalSuccessRate` (and optionally `Builtin.Helpfulness`).
  - Sampling 100%, idle timeout 5 min, "Create and use a new service role", enabled.
- **Cost:** GoalSuccessRate costs ≈ $0.015–0.04 per session. Adding trace-level Helpfulness on about 2 traces per session gives ≈ $0.03–0.08 per session. Fifty demo sessions cost about $2–4.
- **Leave the code-based evaluator out** of the online config: it would lock the evaluator. An online code-based run gets no ground truth anyway, so it could only check invariants. Pause or delete the online config after judging.
- **Expect lower Helpfulness on confirmation turns,** because interrupt traces look odd to the judge (Q6). Present those scores as live monitoring, not as the benchmark.

### Gaps
- Whether `fromAgentRuntimeEndpoint` / agent-endpoint online configs find split-telemetry spans in `aws/spans` without that group being listed. The auto role's `aws/spans` grants suggest the service reads it. Not tested.

---

## Q9. Cedar decisions: what the Policy span carries, and the metrics emitted without tracing

### Takeaway
Gateway Policy spans appear in `aws/spans` once Gateway tracing is on. They carry the decision, the reason and the determining policy IDs, but no tool name and no documented `session.id`.

`AllowDecisions` and `DenyDecisions` (with a `ToolName` dimension) are emitted to `AWS/Bedrock-AgentCore` by default, without tracing. They give per-run counts at 1-minute resolution, so they cannot be attributed to individual sessions.

Each Cedar statement is its own policy here, so `determining_policies` identifies which of the three rules fired.

### Cited Findings
- **Metrics:** "For policy and policy engine resource types, Amazon Bedrock AgentCore publishes invocation metrics to CloudWatch by default." The namespace is `AWS/Bedrock-AgentCore`, and the metrics are `AllowDecisions` and `DenyDecisions`. Dimensions are `OperationName` (`AuthorizeAction`, `PartiallyAuthorizeActions`), `PolicyEngine`, `Policy`, `TargetResource`, `ToolName`, `Mode`, `Category`, `Filter` and `PolicyEnforcementMode`. — [Policy observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-policy-metrics.html)
- **Spans:** "Policy in AgentCore span data is available after enabling traces for your AgentCore Gateway resource", in `aws/spans`. `AuthorizeAction` attributes:
  - `aws.agentcore.policy.authorization_decision` (`ALLOW`/`DENY`)
  - `.authorization_reason`
  - `.determining_policies`
  - `.mismatched_policies`
  - `.target_resource.id`
  - `aws.agentcore.gateway.policy.arn`
  - `aws.agentcore.gateway.policy.mode`
  - `.guardrails.<category>.scores`
  - `.types`
  - `.effects`
  - `.guardrails.latency_ms`
  - `.log_only_matched_policies`
  - `.log_only_decision_flipping_policies`

  — [Policy observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-policy-metrics.html)
- **Gateway "call tool" spans:** `kind:SERVER` and `kind:CLIENT`, with attributes including `gateway.id`, `tool.name`, `latency_ms`, `error_type`, `jsonrpc.error.code` and `http.response.status_code`. Vended logs carry `trace_id` and `span_id`. — [Gateway observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-gateway-metrics.html)
- **One policy per Cedar statement.** The custom resource splits `policy.cedar` into statements and calls `CreatePolicy` once per statement. — [cedar-policy/index.py:22-23, 153-156](../../../infra-cdk/lambdas/cedar-policy/index.py#L22-L23). The document has three statements: a permit and two forbids. — [policy.cedar:35, 56, 80](../../../gateway/policies/policy.cedar#L35)
- **Trace join is unverified.** Whether Gateway and Policy spans share the agent's `traceId` for agent → Gateway MCP calls is still open. The verification note has a Logs Insights test for it (row 8d and item 4).

### Inferences
- **Without tracing:** after each run, call `cloudwatch.get_metric_data` for `DenyDecisions` and `AllowDecisions`, summed over the run window and grouped by `ToolName` and `Policy`. That gives "Cedar blocked N cross-customer or unconfirmed calls" with no extra setup. Per-session attribution is only possible if sessions are serialised and spaced more than 1 minute apart, which is impractical.
- **With Gateway tracing:** build per-session failure cards by joining `AuthorizeAction` spans to the session's Strands `execute_tool` spans on time window plus tool name. Strip the `gateway_` prefix from the Strands name to get the Gateway/Cedar name. Use `traceId` instead if the test in the verification note shows the trace is shared.
- **Map policy IDs to rules.** Record each policy ID → statement mapping once from `ListPolicies`, so that `determining_policies` reads as a rule name. Because there is one policy per statement, the mapping is unambiguous.

### Gaps
- The `ToolName` dimension value format (presumably `<target>___<tool>`) and the policy name format were not observed.
- **Untested:** the trace-ID join between agent and Gateway spans (unchanged).

---

## Q10. Step-by-step wiring plan, cost and time, and what fits by 2026-10-05

### Takeaway
A **zero-redeploy path fits the deadline.** It has five steps:
1. Enable Transaction Search (CLI).
2. Turn on Gateway tracing (console).
3. Smoke-test one read-only and one Yes/No session.
4. Add an on-demand `EvaluationClient.run` step to the runner, with `Builtin.TrajectoryInOrderMatch` on prefixed names plus `Builtin.GoalSuccessRate` with assertions.
5. Optionally, one batch job per run and a console-created online config for the demo.

Expected cost is under about $20 and time about 3–5 hours. A Lambda code-based evaluator (CDK), unified telemetry and the ADOT bump all need a redeploy, and should wait until after the review gate or the deadline.

### Cited Findings
- All facts used here are cited in Q1–Q9. The constraints that drive the plan:
  - Transaction Search is required in both telemetry modes ([Telemetry setup](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks-telemetry.html)), and current ADOT 0.16.0 gives split telemetry, which is evaluable (Q1).
  - Online configs and custom evaluators can be created by API or in the console ([Create online evaluation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/create-online-evaluations.html); [Custom code-based evaluator](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-based-evaluators.html)).
  - The Runtime is JWT-only ([JWT inbound auth](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html)).
- Team rules from the user's memory: deploy only with `AWS_PROFILE=ledgerlens`; never start an AWS deploy while the branch's code review is running; commit on a `feat/<name>` branch from `origin/stage`.
- A CDK redeploy resets `USER_CUSTOMER_IDS_MAP` on the pre-token Lambda. — [architecture_runner_contract.md:595](architecture_runner_contract.md)
- IAM for a principal that creates and runs evaluations: `bedrock-agentcore:CreateEvaluator`, `GetEvaluator`, `ListEvaluators`, `UpdateEvaluator`, `DeleteEvaluator`, `CreateOnlineEvaluationConfig`, `GetOnlineEvaluationConfig`, `ListOnlineEvaluationConfigs`, `UpdateOnlineEvaluationConfig`, `DeleteOnlineEvaluationConfig` and `Evaluate`; `iam:PassRole` to `bedrock-agentcore.amazonaws.com`; `logs:DescribeIndexPolicies`, `PutIndexPolicy` and `CreateLogGroup`. — [Prerequisites](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluations-prerequisites.html)

### Inferences
**Step-by-step plan (in order)**

1. **Account (5 min plus up to 10 min to take effect).** Done by a person with `AWS_PROFILE=ledgerlens` in `us-east-1`; this research did not do it.
   - Run `aws logs put-resource-policy --policy-name TransactionSearchAccess --policy-document file://ts.json`, using the doc's JSON for `aws/spans:*` and `/aws/application-signals/data:*`.
   - Run `aws xray update-trace-segment-destination --destination CloudWatchLogs`.
   - Poll `aws xray get-trace-segment-destination` until it returns `CloudWatchLogs` / `ACTIVE`.
   - Leave indexing at the free 1%.
2. **Gateway tracing (5 min).** Console: AgentCore > Gateways > `ledgerlens-bank-assistant-gateway` > Tracing > Edit > Enable. Gateway application logs are optional.
3. **Smoke test (20–30 min).** Use the P03 demo login, one read-only session and one block-card session answered Yes. After 3 minutes:
   - Run Logs Insights on `aws/spans` with `filter attributes.session.id = "<sid>" | stats count(*) by scope.name, name`. Expect `invoke_agent strands_agent` ([ledgerlens_agent.py:137-138](../../../agent/ledgerlens/ledgerlens_agent.py#L137-L138)), `chat`, and `execute_tool gateway_…` spans.
   - Check that the spans carry `prompt.version` = `v10`.
   - Check that the runtime log group has an `otel-rt-logs` stream.
   - Check the duplicated write-tool spans (Q6) and the `AuthorizeAction` spans in the same time window.
   - Then call `EvaluationClient.run(["Builtin.TrajectoryInOrderMatch"], sid, agent_id=…, reference_inputs=…)` once.
   - **If no Strands spans appear,** enable Runtime Tracing in the console (no deploy) and retry (Q1 gap).
4. **Runner integration (1–2 h).** Add a post-run step to the local runner, using the Q4 code:
   - record `sid`, `expected_trajectory` (the prefixed names from Q5) and `assertions` per session;
   - wait 180 s after the last session;
   - run `EvaluationClient.run` per session;
   - store `aws.trajectory_in_order` and `aws.goal_success` (with `explanation`) next to the local grade;
   - report agreement between the local grader and the AWS trajectory check, and keep GoalSuccessRate as a diagnostic.

   The runner principal needs `bedrock-agentcore:Evaluate`, `GetEvaluator` and `ListEvaluators`, plus `logs:StartQuery` and `GetQueryResults` on `aws/spans` and the runtime log group.
5. **Batch job (30–60 min, optional).** One `start_batch_evaluation` per run, built-ins only, with inline ground truth. Read the aggregate, and pull per-session rows from `/ledgerlens/eval/batch-results` with Logs Insights. This is the slide-friendly "AWS batch evaluation of N sessions" result.
6. **Online demo (20–30 min plus 15–30 min latency, optional).** Create the config in the console (Q8), enabled during judging. Pause it afterwards.
7. **Deferred: code-based evaluator (2–4 h plus a deploy).**
   - Write `evaluation/agentcore_evaluator/handler.py` (a new folder). It turns `sessionSpans` into the grader's input: Strands-scope `execute_tool` spans with name, status, arguments and results, plus the agent responses. Then it calls the same pure-Python grader and returns `{label, value, explanation}`.
   - Wire it with the Q3 CDK snippet, or create the Lambda and evaluator with boto3.
   - It is worth doing only if the grader can run on spans alone. In split mode, tool arguments and results sit in event records, and the docs do not say whether the Lambda's `sessionSpans` includes them.
8. **Deferred: unified telemetry** (the Q1 changes: ADOT pin, environment variable, `PutResourcePolicy`, optionally `aws_mcp` disabled) **and CDK-managed Gateway tracing** (Q2 snippet). Do these after the deadline, through the normal review and deploy flow.

**Cost estimate for about 300 sessions** (estimates, not measured)

| Item | Basis | Estimate |
|---|---|---|
| Span and event-log ingestion | about 0.1–0.3 GB at $0.35/GB (spans) and $0.50/GB (logs) | < $0.50 |
| `Builtin.TrajectoryInOrderMatch` | programmatic, zero tokens; billing undocumented | $0, or ≤ $0.45 if billed as custom |
| `Builtin.GoalSuccessRate` on-demand | ≈ 6–15K input and 300 output tokens per session | ≈ $5–12 (batch about 25% less) |
| Code-based evaluator (if added) | $1.50 per 1K assumed, plus Lambda | ≈ $0.50 |
| Online demo, 50 sessions | GoalSuccessRate (+ Helpfulness) | ≈ $2–4 |
| Logs Insights queries | standard CloudWatch rates, small scans | not quantified, expected cents |

**What is verified, and what is not**

| Claim | Status |
|---|---|
| Transaction Search is required for evaluation in both modes; how to enable it (CLI or CloudFormation); about 10 min to take effect | Verified (docs) |
| This agent is in split mode: created after 2026-07-20 but on ADOT 0.16.0, which ignores the span destination | Verified rule (docs), applied to repo facts; not observed live |
| Runtime injects the OTEL configuration automatically, with no variables in the repo | Documented in general terms; exact variables unverified |
| Unified mode needs ADOT ≥0.18.0, `logs:PutResourcePolicy` and Transaction Search | Verified (docs, release notes) |
| ADOT ≥0.18.0 adds MCP `execute_tool`-like spans; the service excludes that scope | Verified (ADOT source, generic-framework doc) |
| CDK 2.260.0 `Evaluator`, `OnlineEvaluationConfig` and `DataSourceConfig` APIs are stable | Verified (installed `.d.ts`/`.js`, jsii manifest) |
| The Gateway L2 has no tracing property; L1 vended delivery (TRACES → XRAY) works for the Gateway | First half verified; second half untested |
| `gen_ai.tool.name` = `gateway_<target>___<tool>`; the session-start calls produce no Strands tool span | Verified from source; not observed live |
| A Yes session shows the write tool twice; a No session shows interrupted then error | Derived from source; not observed live |
| Code-based evaluators in on-demand and online modes | Verified (docs) |
| Code-based evaluators in batch | **Unverified.** The docs list custom evaluators for online and on-demand only |
| Batch: ≤10 evaluators, ≤500 sessions, inline ground truth, per-session results in CloudWatch | Verified (docs) |
| The Runtime cannot be invoked with SigV4 (JWT only) | Verified (docs plus repo) |
| In-memory Strands spans → `convert_strands_to_adot` → `Evaluate` | SDK source; not a devguide walkthrough; untested |
| Agent and Gateway spans share a `traceId` | Unverified |
| Billing for code-based and trajectory evaluators | Unverified |

**Fits by 2026-10-05:** steps 1–4, plus 5 and/or 6 if time remains.

**Skip:**
- unified telemetry and the ADOT bump;
- CDK changes of any kind (they need a deploy, which waits for review and resets the persona map);
- the code-based Lambda, unless the grader already runs on span dicts;
- dataset runners and user simulation (preview, and they duplicate the runner);
- Insights;
- trace-level and tool-level LLM judges;
- `ExactOrderMatch`.

### Gaps
- None of steps 1–6 was executed. Times are estimates.
- The smoke test (step 3) is the gate. If spans are missing, or the tool names or the duplicated write spans differ from the source-derived expectations, steps 4–6 change.
- The CDK deploy duration for this stack is not known.
