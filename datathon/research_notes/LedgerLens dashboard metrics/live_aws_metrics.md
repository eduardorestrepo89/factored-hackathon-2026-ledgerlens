# Live AWS metrics for the LedgerLens CloudWatch dashboard (as of 2026-10-05)

Scope: which operational and live-traffic signals the deployed `ledgerlens-bank-assistant` stack (us-east-1) already emits, or can emit cheaply, for a CloudWatch dashboard placed next to the evaluation results. This builds on `../LedgerLens agent evaluation harness/agentcore_evaluations_wiring.md` (cited below as "wiring note") and `../Agent evaluation signal on AWS/aws_evaluation_stack.md` ("eval-stack note"). Their verified facts (Transaction Search, split telemetry with ADOT 0.16.0, Policy span attributes, Evaluations namespace) are reused, not re-derived.

Method and limits:
- AWS docs were read on 2026-10-05 through the AWS documentation MCP and WebFetch. CDK metric helpers were read from the installed `aws-cdk-lib` 2.260.0 in the main checkout's `infra-cdk/node_modules/aws-cdk-lib/aws-bedrockagentcore/lib/{runtime/runtime-base.js, gateway/gateway-base.js, memory/memory.js}`.
- Repo code was read in this worktree. Repo paths below are relative to the repo root (`../../../` from this file).
- No AWS API was called. Nothing was deployed or tested against the live account. "Exact dimensions" means what AWS docs or the CDK helpers state. The live dimension sets should be confirmed once with `aws cloudwatch list-metrics --namespace <ns>` (a read-only call the user can run).

Names this stack uses (from the repo):
- Stack base `ledgerlens-bank-assistant` ([infra-cdk/config.yaml:1](../../../infra-cdk/config.yaml)). Customer model `deepseek.v3.2`; the evaluator allowlist is `["deepseek.v3.2", "openai.gpt-oss-120b-1:0"]` (config.yaml:29, 32).
- Runtime name `ledgerlens_bank_assistant_<agent_name>` ([backend-construct.ts:446](../../../infra-cdk/lib/backend-construct.ts#L446)). Runtime log group `/aws/bedrock-agentcore/runtimes/<agentRuntimeId>-DEFAULT`.
- 9 tool Lambdas. The **function name** is `ledgerlens-<slug>` (backend-construct.ts:896), but the **log group** is `/aws/lambda/ledgerlens-bank-assistant-<slug>` (backend-construct.ts:914-918). `AWS/Lambda` metrics use the first; Logs Insights and metric filters use the second.
- Gateway target names are `<slug>-target`, except `fraud-detection-target` (backend-construct.ts:921, 887).
- Feedback: table `ledgerlens-bank-assistant-feedback` with GSI `feedbackType-timestamp-index` (pk `feedbackType`, sk `timestamp` in ms) (backend-construct.ts:528-555). Lambda `ledgerlens-bank-assistant-feedback` (590-615). REST API `ledgerlens-bank-assistant-api`, stage `prod`, with `metricsEnabled: true` and `tracingEnabled: true` (626-656).
- Pre-token Lambda `ledgerlens-bank-assistant-pretoken-v3` ([cognito-construct.ts:143-160](../../../infra-cdk/lib/cognito-construct.ts#L143-L160)). DSQL cluster `CfnCluster` ([data-construct.ts:101-103](../../../infra-cdk/lib/data-construct.ts#L101-L103)).
- The agent role may call `cloudwatch:PutMetricData` only in namespace `bedrock-agentcore` ([agentcore-role.ts:68-77](../../../infra-cdk/lib/utils/agentcore-role.ts#L68-L77)). Any custom EMF/PutMetricData from the agent must use that namespace, or the role must change.

---

## Q1. Built-in vended metrics: exact namespaces, metric names and dimensions, and what each tells about LedgerLens

### Takeaway
Almost every component already publishes free metrics in an `AWS/*` namespace: AgentCore Runtime, Gateway, Policy and Memory in `AWS/Bedrock-AgentCore`, Bedrock models in `AWS/Bedrock` (by `ModelId`), the guardrail in `AWS/Bedrock/Guardrails`, plus Lambda, DSQL, Cognito, API Gateway and DynamoDB. The one with the most demo value is Policy `DenyDecisions` by `ToolName`. Because of how LedgerLens handles errors, several of them under-count real failures. The agent, the tool Lambdas and Bedrock all return HTTP 200 for many failures, so error panels need the log-derived metrics from Q2.

### Cited Findings

**AgentCore Runtime (`AWS/Bedrock-AgentCore`)**
- Metrics: Invocations, Invocations (aggregated), Throttles, System Errors, User Errors, Latency ("between receiving the request and sending the final response token"), Total Errors, Session Count (new sessions only, "a cumulative counter, not a gauge"), Sessions (aggregated), and ActiveSessionCount (a real-time gauge with dimension `Service` = `AgentCore.Runtime` / `AgentCore.CodeInterpreter` / `AgentCore.Browser`). They are batched at 1-minute intervals. — [AgentCore runtime observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html)
- The CDK helpers build these exact metric names in `AWS/Bedrock-AgentCore` with `dimensionsMap: {Resource: <agentRuntimeArn>}`:
  - `Invocations`, `Throttles`, `SystemErrors`, `UserErrors`, `TotalErrors` and `SessionCount` use Sum;
  - `Latency` uses Average;
  - the account aggregates are `Invocations` and `Sessions` with `{Resource: "All"}`.
  — local `aws-cdk-lib` 2.260.0 `aws-bedrockagentcore/lib/runtime/runtime-base.js` (`metricInvocations` … `metricSessionsAggregated`); also listed in [CDK RuntimeBase API](https://docs.aws.amazon.com/cdk/api/v2/dotnet/api/Amazon.CDK.AWS.BedrockAgentCore.RuntimeBase.html)
- Resource usage: `CPUUsed-vCPUHours` and `MemoryUsed-GBHours`. Dimension sets are `Service`; `Service, Resource`; and `Service, Resource, Name`, where Service = `AgentCore.Runtime`, Resource = agent ARN, and Name = `AgentName::EndpointName`. "Resource usage data may be delayed by up to 60 minutes." Session-level `USAGE_LOGS` (1-second granularity) need a log delivery to be enabled. — [AgentCore runtime observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html)
- Error taxonomy: user errors are `InvocationError.Validation` (400), `.ResourceNotFound` (404), `.AccessDenied` (403) and `.Conflict` (409). The system error is `.Internal` (500). Throttling errors are `.Throttling` (429) and `.ServiceQuota` (402). — same page
- Runtime span `InvokeAgentRuntime` carries `session.id`, `latency_ms` and `error_type` (throttle/system/user). It needs observability enabled on the resource. — same page

**AgentCore Gateway (`AWS/Bedrock-AgentCore`)**
- Dimensions: `Operation` (for example `InvokeGateway`), `Protocol` (`MCP`), `Method` (for example `tools/list`), `Resource` (gateway ARN), and `Name` ("the name of the tool").
- Metrics:
  - `Invocations`, `Throttles`, `SystemErrors` (5xx), `UserErrors` (4xx except 429);
  - `Latency` (time to first response token);
  - `Duration` (end to end);
  - `TargetExecutionTime` ("time taken to execute the target over Lambda");
  - usage metric `TargetType` (count by MCP/Lambda/OpenAPI).
- Statistics include p50/p90/p99. "These metrics aren't available on the CloudWatch generative AI observability page."
— [AgentCore gateway observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-gateway-metrics.html)
- The CDK gateway helpers use `{Resource: <gatewayArn>}`, and `TargetType` uses `{TargetType: <type>}`. — local `gateway/gateway-base.js`
- "Call Tool" spans: `kind:SERVER` plus `kind:CLIENT`, with `tool.name`, `latency_ms`, `error_type`, `jsonrpc.error.code`, `http.response.status_code` and `overhead_latency_ms`. Vended APPLICATION_LOGS (which need a delivery) go to `/aws/vendedlogs/bedrock-agentcore/gateway/APPLICATION_LOGS/{gateway_id}` and include `requestBody` with the tool arguments. — [Gateway observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-gateway-metrics.html)

**AgentCore Policy / Cedar (`AWS/Bedrock-AgentCore`, published by default with no tracing needed)**
- Metrics:
  - `Invocations`, `SystemErrors`, `UserErrors`, `Latency`;
  - `AllowDecisions`, `DenyDecisions`;
  - `TotalMismatchedPolicies`, `PolicyMismatch`, `MismatchErrors`;
  - `DeterminingPolicies`, `NoDeterminingPolicies`;
  - `GuardrailLatency`, `ConfidenceScore`, `ConfidenceThreshold`, `SuppressOutputs`;
  - `LogOnlyMatches`, `LogOnlyDecisionFlips`, `LogOnlyEvalIncomplete`, `TemporalLatency`.
- Dimensions:
  - `OperationName` (`AuthorizeAction`, `PartiallyAuthorizeActions`);
  - `PolicyEngine`, `Policy`, `TargetResource`, `ToolName`;
  - `Mode` (`LOG_ONLY`/`ENFORCE`), `Category`, `Filter`, `PolicyEnforcementMode`.
- The `AuthorizeAction` span attribute `aws.agentcore.policy.authorization_decision` (ALLOW/DENY) lands in `aws/spans` once Gateway tracing is on.
— [Policy observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-policy-metrics.html)

**AgentCore Memory (`AWS/Bedrock-AgentCore`, published by default)**
- Metrics: Latency, Invocations (also counts "memory ingestion events"), System Errors, User Errors, Errors, Throttles, and Creation Count ("created memory events and memory records"). — [Memory observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-memory-metrics.html)
- The CDK memory helpers use `{Resource: <memoryArn>}`; per-API metrics add `{Operation: <api>}` (for example `CreateEvent`, `ListEvents`), and `CreationCount` uses `{ItemType: "Event"}` or `{ItemType: "MemoryRecordsExtracted"}`. — local `memory/memory.js` (`metricForApiOperation`, `metricEventCreationCount`, `metricMemoryRecordCreationCount`)

**Bedrock runtime per model (`AWS/Bedrock`, dimension `ModelId`)**
- Metrics:
  - `Invocations` ("successful requests to the Converse, ConverseStream, InvokeModel, and InvokeModelWithResponseStream");
  - `InvocationLatency` (to last token);
  - `InvocationClientErrors`, `InvocationServerErrors`;
  - `InvocationThrottles` ("Throttled requests and other invocation errors don't count as either Invocations or Errors");
  - `InputTokenCount`, `OutputTokenCount`;
  - `TimeToFirstToken` (ConverseStream / InvokeModelWithResponseStream);
  - `EstimatedTPMQuotaUsage`, `CacheReadInputTokenCount`, and others.
  — [Bedrock runtime metrics](https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring-runtime-metrics.html)
- The console selects them "By ModelId". OTPS can be graphed as `m2 / (m1 - m3) * 1000`, where m1 = `InvocationLatency`, m2 = `OutputTokenCount` and m3 = `TimeToFirstToken`, all at p50. — [Diagnose InvocationLatency using OTPS](https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring-runtime-otps.html)
- With a cross-Region profile, "the `ModelId` dimension corresponds to your inference profile identifier". — [TTFT / quota metrics blog](https://aws.amazon.com/blogs/machine-learning/improve-operational-visibility-for-inference-workloads-on-amazon-bedrock-with-new-cloudwatch-metrics-for-ttft-and-estimated-quota-consumption/). LedgerLens calls the plain IDs `deepseek.v3.2` / `openai.gpt-oss-120b-1:0` (config.yaml:29, 32), so those are the dimension values.

**Bedrock Guardrails (`AWS/Bedrock/Guardrails`)**
- Metrics: `Invocations`, `InvocationLatency`, `InvocationClientErrors`, `InvocationServerErrors`, `InvocationThrottles`, `TextUnitCount`, `InvocationsIntervened` (plus Automated Reasoning metrics that do not apply here).
- Dimensions:
  - `Operation` = `ApplyGuardrail`;
  - `GuardrailContentSource` = `Input` | `Output`;
  - `GuardrailPolicyType` = `ContentPolicy` | `TopicPolicy` | `WordPolicy` | `SensitiveInformationPolicy` | `ContextualGroundingPolicy` (only on `InvocationsIntervened` and `TextUnitCount`);
  - `GuardrailArn, GuardrailVersion`.
— [Guardrails CloudWatch metrics](https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring-guardrails-cw-metrics.html)
- With Converse/ConverseStream, "the system … sends user input to the `ApplyGuardrail` API to evaluate against your defined policies" and evaluates output again. For streaming, the output is evaluated "in chunks". — [Guardrails best-practices blog](https://aws.amazon.com/blogs/machine-learning/build-safe-generative-ai-applications-like-a-pro-best-practices-with-amazon-bedrock-guardrails/)
- LedgerLens attaches the guardrail inline: `guardrail_trace: "enabled"`, `guardrail_stream_processing_mode: "sync"` and `guardrail_latest_message: True` ([agent/ledgerlens/tools/guardrail.py:33-46](../../../agent/ledgerlens/tools/guardrail.py#L33-L46)). Its policies are content filters including PROMPT_ATTACK, plus 4 denied topics, on the STANDARD tier ([agent-guardrail.ts:18-82, 109-116](../../../infra-cdk/lib/utils/agent-guardrail.ts#L18-L116)). So the `GuardrailPolicyType` values to expect are `ContentPolicy` and `TopicPolicy` only.

**Lambda per tool function (`AWS/Lambda`, dimension `FunctionName`)**
- `Invocations`; `Errors` ("exceptions that your code throws and exceptions that the Lambda runtime throws", for example timeouts); `Throttles` ("don't count as either Invocations or Errors"); and Duration and ConcurrentExecutions. — [Lambda metric types](https://docs.aws.amazon.com/lambda/latest/dg/monitoring-metrics-types.html); [Lambda concurrency blog](https://aws.amazon.com/blogs/compute/investigating-spikes-in-aws-lambda-function-concurrency/)
- Every LedgerLens tool handler catches `DomainError` and every other `Exception`, and *returns* `{"error": …}`. It logs `logger.warning("%s returned an error…")` or `logger.exception("Unexpected error in %s")`. Examples: [human_agent_hand_off handler.py:74-81](../../../gateway/tools/human_agent_hand_off/human_agent_hand_off_lambda/delivery/handler.py#L74-L81); the same pattern is in all 9 `gateway/tools/*/…/delivery/handler.py`.

**Aurora DSQL (`AWS/AuroraDSQL`, dimension `ClusterId`)**
- Metrics: `TotalTransactions`, `ReadOnlyTransactions`, `QueryTimeouts`, `OccConflicts`, `CommitLatency` (P50), `BytesWritten`, `BytesRead`, `ComputeTime`, `ClusterStorageSize`. DPU metrics are `WriteDPU`, `ReadDPU`, `ComputeDPU` and `TotalDPU`. `AWS/Usage` has `ResourceCount` (ClusterConnectionCount) and `CallCount` (DbConnect/DbConnectAdmin). — [DSQL CloudWatch monitoring](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/cloudwatch-monitoring.html); [DSQL billing/DPU metrics](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/billing-metering.html)
- Database Insights for DSQL: "Upto 15 months of per-minute standard database metrics are included at no additional cost." — [CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)

**Cognito (`AWS/Cognito`)**
- `SignInSuccesses`, `SignInThrottles`, `SignUpSuccesses`, `TokenRefreshSuccesses` and `TokenRefreshThrottles` with dimensions `UserPool, UserPoolClient`; `FederationSuccesses` with `IdentityProvider, UserPool, UserPoolClient`. — [Supported metrics for resource tags (AWS/Cognito)](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/SupportedMetricsForResourceTagsForTelemetry.html)

**API Gateway (feedback API)**
- "By default, API Gateway publishes 4XXError, 5XXError, CacheHitCount, CacheMissCount, Count, IntegrationLatency and Latency per API. Once detailed metrics … is enabled, all the above metrics along with dimensions - ApiName, method, resource, stage will be emitted". The pricing example bills detailed metrics as custom metrics (40 metrics → $12/month). — [CloudWatch pricing, example](https://aws.amazon.com/cloudwatch/pricing/)

**Cost of vended metrics**
- "Basic monitoring metrics for AWS services under AWS namespaces are included at no additional charge." — [re:Post KC: optimize custom metrics](https://repost.aws/knowledge-center/optimize-cloudwatch-custom-metrics)

### Inventory: vended metrics (all free to collect; needs no code or infra change unless noted)

| # | Namespace · Metric · Dimensions | What it tells about LedgerLens | Widget | Change? |
|---|---|---|---|---|
| V1 | `AWS/Bedrock-AgentCore` · `Invocations`, `SessionCount` (Sum) · `Resource=<runtime ARN>` | turns and new conversations per period; turns per session = ratio | line (stacked) + single value | none |
| V2 | same · `Latency` (p50/p90/Max) · `Resource=<runtime ARN>` | end-to-end turn time, including tool calls. A confirmation pause ends the stream, so it isn't counted | line | none |
| V3 | same · `SystemErrors`, `UserErrors`, `Throttles`, `TotalErrors` · `Resource=<runtime ARN>` | platform-level failures only (403 JWT, 429, 500). Agent exceptions are **not** included (see Inferences) | line / number | none |
| V4 | same · `ActiveSessionCount` · `Service=AgentCore.Runtime` | live concurrent sessions in the account | number + sparkline | none |
| V5 | same · `CPUUsed-vCPUHours`, `MemoryUsed-GBHours` · `Service, Resource, Name` | runtime compute spend proxy (up to 60 min delayed) | line (Sum, 1 h) | none |
| V6 | same · Gateway `Invocations`, `Latency`, `Duration`, `TargetExecutionTime`, `UserErrors`, `SystemErrors` · `Operation, Protocol, Method, Resource, Name` (exact combination to confirm) | MCP calls per tool (`Name`), tool latency vs Gateway overhead, `tools/list` vs `tools/call` | line by `Name`; bar of p90 | none |
| V7 | same · Policy `AllowDecisions`, `DenyDecisions` · `OperationName, PolicyEngine, Policy, TargetResource, ToolName, Mode` | Cedar allow/deny per tool. With the hooks working, `AuthorizeAction` denies should be ~0 | stacked bar by `ToolName`; number | none |
| V8 | same · Policy `NoDeterminingPolicies`, `MismatchErrors`, `Latency` | denies caused by "no permit matched", and policy schema/attribute mismatches | number | none |
| V9 | same · Memory `Invocations`/`Errors`/`Latency` with `Operation` (`CreateEvent`, `ListEvents`); `CreationCount` with `ItemType=Event` / `MemoryRecordsExtracted` · `Resource=<memory ARN>` | STM health; whether long-term extraction runs (the memory defines a semantic strategy, [backend-construct.ts:259-262](../../../infra-cdk/lib/backend-construct.ts#L259-L262)) | line | none |
| V10 | `AWS/Bedrock` · `Invocations`, `InputTokenCount`, `OutputTokenCount`, `InvocationLatency`, `TimeToFirstToken`, `InvocationThrottles`, `InvocationClientErrors`, `InvocationServerErrors` · `ModelId=deepseek.v3.2` / `openai.gpt-oss-120b-1:0` | per-model load, tokens (cost), latency, throttling. Account-wide per model, so evaluator runs are included | line per model; OTPS metric math | none |
| V11 | `AWS/Bedrock/Guardrails` · `Invocations`, `InvocationsIntervened`, `TextUnitCount`, `InvocationLatency` · `GuardrailArn, GuardrailVersion`; `GuardrailContentSource`; `GuardrailPolicyType` | blocked inputs/outputs; split prompt-attack/content (`ContentPolicy`) vs off-topic (`TopicPolicy`); guardrail cost (text units) | stacked bar by policy type; line | none (confirm the inline Converse use emits them) |
| V12 | `AWS/Lambda` · `Invocations`, `Errors`, `Throttles`, `Duration` (p90), `ConcurrentExecutions` · `FunctionName=ledgerlens-<slug>` (×9), `ledgerlens-bank-assistant-pretoken-v3`, `ledgerlens-bank-assistant-feedback` | tool usage mix (the hand-off Lambda's invocations ≈ hand-off attempts); cold-start and DSQL latency; timeouts. `Errors` misses handled tool failures | line by function; table | none |
| V13 | `AWS/AuroraDSQL` · `TotalTransactions`, `ReadOnlyTransactions`, `CommitLatency`, `OccConflicts`, `QueryTimeouts`, `TotalDPU` · `ClusterId` | DB load; writes (block card, open claim) = Total − ReadOnly; DPU = DSQL cost | line | none |
| V14 | `AWS/Cognito` · `SignInSuccesses`, `TokenRefreshSuccesses`, `SignInThrottles` · `UserPool, UserPoolClient` | logins (customers and evaluators) | number / line | none |
| V15 | `AWS/ApiGateway` · `Count`, `4XXError`, `5XXError`, `Latency` · `ApiName=ledgerlens-bank-assistant-api, Stage=prod` (+ `Method, Resource` from detailed metrics) | feedback submissions and failures | number | none (detailed metrics already on, so already billed) |

### Inferences
- **Runtime error metrics under-count agent failures.** The entrypoint catches every exception and *yields* `{"status": "error", …}` after `logger.exception("Agent run failed")` ([ledgerlens_agent.py:234-236](../../../agent/ledgerlens/ledgerlens_agent.py#L234-L236)). A rejected eval override also yields an error event (ledgerlens_agent.py:202-204). The HTTP stream therefore completes normally, and Runtime `SystemErrors`/`UserErrors` should stay at 0 for model, Gateway, memory or tool exceptions. A "turns that failed inside the agent" metric must come from the `Agent run failed` log line (Q2, M1).
- **Lambda `Errors` will be ~0 even when tools fail.** The handlers return `{"error": …}`, which is a successful Lambda invocation (handler pattern above, and the Lambda definition of `Errors`). Only timeouts (30 s for DSQL tools, 10 s for the hand-off, backend-construct.ts:905), init crashes or OOM increment it. Tool failure rate has to come from the handlers' WARNING/ERROR log lines (Q2, M6) or from spans.
- **Guardrail blocks are not errors.** A guardrail intervention is a successful Converse response, so it never shows in `InvocationClientErrors`. `InvocationsIntervened` in `AWS/Bedrock/Guardrails` is the right metric. With `sync` streaming, the output is checked in chunks, so expect several guardrail `Invocations` per turn on the `Output` side. Compare intervention *counts*, not rates against `Invocations`.
- **Alarm on `OperationName=AuthorizeAction` only.** Listing tools uses `PartiallyAuthorizeActions`, and for a login with a blank `customer_id` the Cedar permit never matches ([gateway/policies/policy.cedar:35-50](../../../gateway/policies/policy.cedar#L35-L50)). Those listing denies are expected and harmless. A `DenyDecisions` on `AuthorizeAction` means a real tools/call was blocked: a cross-customer id that got past `CustomerIdHook`, or a write without `customer_confirmed` (policy.cedar:56-91). In normal operation both hooks prevent that, so the expected value is 0.
- **Bedrock metrics are account-wide per model.** They include evaluator traffic (the harness runs the same models) and any STM summarization calls. Separate customer and evaluation traffic with the log/span recipes in Q2 (`[EVAL] override`, `prompt.version`).
- **A cheap health cross-check.** The agent fetches one Gateway M2M token per request (ledgerlens_agent.py:207). Each token issue fires the V3 pre-token Lambda, so `AWS/Lambda Invocations` for `ledgerlens-bank-assistant-pretoken-v3` should track Runtime `Invocations`, plus user sign-ins and refreshes. A widening gap would point at token-issuance failures.
- **Memory extraction check.** The memory resource defines a `FactExtractor` semantic strategy even though `USE_LONG_TERM_MEMORY` is false (backend-construct.ts:257-262, 411). `CreationCount{ItemType=MemoryRecordsExtracted}` will show whether long-term extraction runs on every event anyway. That would be a cost signal. Not verified.
- **Use SEARCH expressions where dimension sets are unsure.** For Runtime/Gateway/Policy/Memory, a SEARCH expression such as `SEARCH('{AWS/Bedrock-AgentCore,OperationName,ToolName} MetricName="DenyDecisions"', 'Sum', 300)` avoids hard-coding sets that are not confirmed. These are standard CloudWatch metric-math search expressions and were not re-verified this session. Alarms need concrete metrics, so confirm the dimension set before writing one.

### Gaps
- The exact **dimension combinations** AWS publishes are documented only as lists, not as combinations, for Runtime (CDK uses only `Resource`), Gateway (`Operation, Protocol, Method, Resource, Name`) and Policy. They should be confirmed once with `aws cloudwatch list-metrics --namespace AWS/Bedrock-AgentCore`.
- The **`ToolName` / `Name` values** are not documented: the Policy `ToolName` and Gateway `Name` may be `<target>___<tool>` (for example `open-claim-target___open_claim`) or the bare tool name. Confirm the same way.
- **Inline guardrail metrics:** whether `AWS/Bedrock/Guardrails` metrics (`Operation=ApplyGuardrail`) are emitted for a guardrail attached through Converse/ConverseStream. The metrics page describes them as "requests to the `ApplyGuardrail` API". The blog says inline use goes through ApplyGuardrail, but no doc states that the metrics are emitted for inline use.
- **CPU/memory namespace:** the namespace for `CPUUsed-vCPUHours` / `MemoryUsed-GBHours` is not stated on the page (presumably `AWS/Bedrock-AgentCore`).
- **Cedar deny over HTTP:** whether a Cedar deny or a tool `{"error"}` makes the Gateway count `UserErrors`/`SystemErrors`, or return a JSON-RPC error over HTTP 200, is undocumented.

---

## Q2. Metrics derived from logs and spans: hand-offs, confirmations, customer-id overwrites, tool errors, sessions per model/prompt, guardrail blocks

### Takeaway
Every LedgerLens-specific behavior signal can be read today, with no code change, by Logs Insights query widgets over the runtime log group, the tool Lambda log groups and `aws/spans`. Turning a signal into an alarmable metric needs a CloudWatch Logs metric filter, which is an infra-only change at $0.30 per metric per month. There are two blind spots. The hand-off **reason** is not logged anywhere cheap: the Lambda logs only id and priority. Feedback **ratings** are not logged at all. Each needs a one-line code change or a custom widget.

### Cited Findings
- Logs Insights queries added to dashboards "run every time you load the dashboard and every time that the dashboard refreshes. These queries count toward your limit of 100 concurrent CloudWatch Logs Insights queries." — [Add query to dashboard](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CWL_ExportQueryResults.html). CDK has `LogQueryWidget` (`logGroupNames`, `view`, `queryLines` / `queryString`) — [CDK aws-cloudwatch README](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_cloudwatch/README.html)
- Metric filters "are assigned to log groups, and all of the filters assigned to a log group are applied to their log streams". They can carry dimensions taken "from values in JSON or space-delimited log events". — [Filter pattern syntax for metric filters](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/FilterAndPatternSyntaxForMetricFilters.html)
- JSON keys that contain a period need bracket notation with single quotes, for example `{ $.['cluster.name'] = "c" }`. Double quotes inside the brackets are a syntax error. — [Filter pattern syntax](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/FilterAndPatternSyntax.html)
- Transaction Search ingests spans as structured logs in `aws/spans` and "supports metric filters". — eval-stack note, citing [Transaction Search](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Transaction-Search.html)
- The `bedrock-agentcore` 1.24.0 span collector queries `aws/spans` with `filter attributes.session.id = "<sid>" | filter ispresent(scope.name) | filter ispresent(traceId) | filter ispresent(spanId)`. It sorts by `endTimeUnixNano`, which confirms the flattened field names in Logs Insights. — local `evals/.venv/Lib/site-packages/bedrock_agentcore/evaluation/agent_span_collector/agent_span_collector.py:102-125`
- Strands span attributes LedgerLens sets on the agent: `user.id`, `session.id`, `model.id`, `prompt.version` ([ledgerlens_agent.py:165-171](../../../agent/ledgerlens/ledgerlens_agent.py#L165-L171)). The span kinds the service reads are `gen_ai.operation.name` ∈ {`invoke_agent`, `execute_tool`, `chat`}, the tool name is in `gen_ai.tool.name`, and the scope is `strands.telemetry.tracer`. — wiring note, citing [Strands telemetry for Evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks-strands.html)
- Telemetry mode today is split: spans go to `aws/spans`; content (prompts, tool I/O) goes to event records in the runtime log group's `otel-rt-logs` stream. — wiring note Q1, citing [Telemetry setup and delivery](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks-telemetry.html)
- Runtime log group streams: standard stdout/stderr (`logging.info(...)` appears in standard logs) under `…/runtime-logs`, and "OTEL structured logs" under `…/otel-rt-logs`. — [View observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-view.html)
- The agent's ADOT instrumentation also sends OTel **metrics** via EMF to namespace `bedrock-agentcore` ("Custom metrics generated by your agent code and frameworks … No additional code required"). — [View observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-view.html)
- The Strands metric names (current `main`) are:
  - `strands.event_loop.cycle_count`, `strands.event_loop.start_cycle`, `strands.event_loop.end_cycle`;
  - `strands.tool.call_count`, `strands.tool.success_count`, `strands.tool.error_count`, `strands.tool.duration`;
  - `strands.event_loop.latency`, `strands.event_loop.cycle_duration`;
  - `strands.event_loop.input.tokens`, `strands.event_loop.output.tokens`, `strands.event_loop.cache_read.input.tokens`, `strands.event_loop.cache_write.input.tokens`;
  - `strands.model.time_to_first_token`.
  — [strands-py metrics_constants.py](https://raw.githubusercontent.com/strands-agents/harness-sdk/main/strands-py/src/strands/telemetry/metrics_constants.py)
- Policy span attributes in `aws/spans`: `aws.agentcore.policy.authorization_decision`, `.authorization_reason`, `.determining_policies`, `aws.agentcore.gateway.policy.mode`. The `PartiallyAuthorizeActions` span has `aws.agentcore.policy.allowed_tools` / `.denied_tools`. — [Policy observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-policy-metrics.html)

Log lines in the repo that recipes can key on:
- `[PROMPT] version=%s model=%s session=%s`, once per invocation (turn) — [ledgerlens_agent.py:210-215](../../../agent/ledgerlens/ledgerlens_agent.py#L210-L215)
- `Agent run failed` (logger.exception) — ledgerlens_agent.py:235
- `[CONFIRM] Customer approved %s` / `[CONFIRM] Customer declined %s`. The tool is `block_credit_card`, `open_claim` or `human_agent_hand_off`. It is logged only on the resumed request, when the customer answered — [confirmation_hook.py:32, 66-71](../../../agent/ledgerlens/tools/confirmation_hook.py#L32-L71). "Declined" also covers a typed reply instead of a click and an interrupt left unanswered in a multi-confirmation response (confirmation_hook.py:92-102).
- `[CUSTOMER-ID] Replaced the model's customer_id on %s` and `[CUSTOMER-ID] No linked customer - cancelling %s` — [customer_id_hook.py:55-67](../../../agent/ledgerlens/tools/customer_id_hook.py#L55-L67). "Replaced" fires whenever `tool_input.get("customer_id") != self.customer_id`. That **includes the model omitting the field**, not only writing another customer's id.
- `[EVAL] override sub=%s model=%s prompt=%s` and `[EVAL] override ignored: not an evaluator sub=%s` — [eval_override.py:78, 101-106](../../../agent/ledgerlens/tools/eval_override.py#L78-L106)
- Tool Lambdas: `<tool> returned an error: <msg>` (WARNING, with traceback) and `Unexpected error in <tool>` (ERROR) — handler.py of each tool (for example block_credit_card handler.py:87-93)
- Hand-off Lambda: `human_agent_hand_off queued HO-XXXXXXXX (priority=high|normal)`. The summary is deliberately never logged, and **the reason is not logged** — [human_agent_hand_off handler.py:83-86](../../../gateway/tools/human_agent_hand_off/human_agent_hand_off_lambda/delivery/handler.py#L83-L86). The reason enum is `FRAUD_CONFIRMED`, `CUSTOMER_REQUEST`, `UNRESOLVED`, `OUT_OF_SCOPE` ([hand_off.py:15](../../../gateway/tools/human_agent_hand_off/human_agent_hand_off_lambda/application/use_cases/hand_off.py#L15)).
- Feedback Lambda: logs only validation and DynamoDB errors. `feedbackType` is written to DynamoDB but never logged ([infra-cdk/lambdas/feedback/index.py:139-170](../../../infra-cdk/lambdas/feedback/index.py#L139-L170)).

### Inventory: derived signals (recipes)

Abbreviations: **RT** = `/aws/bedrock-agentcore/runtimes/<agentRuntimeId>-DEFAULT`; **TL** = the 9 tool Lambda log groups `/aws/lambda/ledgerlens-bank-assistant-<slug>`; **SP** = `aws/spans`.

| # | Signal | Source / recipe | Widget | Cost | Change? |
|---|---|---|---|---|---|
| L1 | Turns and sessions per model and prompt version (customer vs eval) | RT: `filter @message like /\[PROMPT\] version=/ \| parse @message "[PROMPT] version=* model=* session=*" as pv, model, sid \| stats count(*) as turns, count_distinct(sid) as sessions by model, pv` | Logs Insights table / bar | Logs Insights scan per refresh | none |
| L1b | The same from spans | SP: `filter attributes.gen_ai.operation.name = "invoke_agent" \| stats count(*) as turns, count_distinct(attributes.session.id) as sessions by attributes.model.id, attributes.prompt.version` | table / pie | scan | none |
| L2 | Confirmation approve vs decline per tool | RT: `filter @message like /\[CONFIRM\] Customer/ \| parse @message "[CONFIRM] Customer * *" as decision, tool \| stats count(*) by tool, decision` | stacked bar | scan | none |
| L3 | Customer-id overwrites per tool | RT: `filter @message like /\[CUSTOMER-ID\] Replaced/ \| parse @message "customer_id on *" as tool \| stats count(*) by tool, bin(1h)` | bar / line | scan | none |
| L4 | Evaluator traffic and rejected overrides | RT: `filter @message like /\[EVAL\] override/ \| parse @message "model=* prompt=*" as model, prompt \| stats count(*) by model, prompt` | table | scan | none |
| L5 | Agent-internal failures (turns that yielded an error) | RT: `filter @message like /Agent run failed/ \| stats count(*) by bin(5m)` | line | scan | none |
| L6 | Tool errors by tool (handled) | TL (select all 9, or prefix `/aws/lambda/ledgerlens-bank-assistant-`): `filter @message like /returned an error\|Unexpected error in/ \| stats count(*) by @log` | bar | scan | none |
| L7 | Tool calls and errors from spans | SP: `filter attributes.gen_ai.operation.name = "execute_tool" \| stats count(*) by attributes.gen_ai.tool.name, status.code` | stacked bar | scan | none (the error-status attribute needs verifying) |
| L8 | Gateway per-tool latency and errors from spans | SP: `filter ispresent(attributes.tool.name) \| stats count(*), avg(attributes.latency_ms), pct(attributes.latency_ms, 90) by attributes.tool.name, attributes.error_type` | table | scan | none (Gateway tracing is ON) |
| L9 | Cedar decisions with reasons | SP: `filter ispresent(attributes.aws.agentcore.policy.authorization_decision) \| stats count(*) by attributes.aws.agentcore.policy.authorization_decision, attributes.aws.agentcore.policy.determining_policies` | table | scan | none |
| L10 | Hand-offs queued, by priority | TL hand-off group `/aws/lambda/ledgerlens-bank-assistant-human-agent-hand-off`: `filter @message like /queued HO-/ \| parse @message "(priority=*)" as priority \| stats count(*) by priority, bin(1d)` | bar | scan | none |
| L11 | **Hand-off reason mix** | Not logged. Options: (a) add `reason` to the existing `logger.info` at handler.py:84-86 (an enum, no PII), then the L10 recipe; (b) parse the tool input from `otel-rt-logs` event records or from Gateway APPLICATION_LOGS `requestBody`, both of which also carry the free-text summary (PII) | bar | scan | (a) one-line code change and redeploy of the Lambda |
| L12 | Guardrail blocks per turn | Prefer V11. Span route: SP `filter attributes.gen_ai.operation.name = "chat" \| stats count(*) by attributes.gen_ai.response.finish_reasons` (attribute name unverified) | bar | scan | none |
| M1 | `AgentRunFailed` alarmable count | Metric filter on RT, pattern `"Agent run failed"`, value 1, namespace e.g. `LedgerLens/Agent` | line + alarm | $0.30/mo | infra only (CDK `logs.MetricFilter`) |
| M2 | `ConfirmApproved`, `ConfirmDeclined` | Metric filters on RT: `"[CONFIRM] Customer approved"` / `"[CONFIRM] Customer declined"` | line; ratio via metric math | $0.60/mo | infra only |
| M3 | `CustomerIdReplaced` | Metric filter on RT: `"[CUSTOMER-ID] Replaced"` | line + alarm | $0.30/mo | infra only |
| M4 | `HandOffQueued` | Metric filter on the hand-off log group: `"queued HO-"` | number | $0.30/mo | infra only |
| M5 | `PolicyDeny` (span-level) | Metric filter on SP: `{ $.attributes.['aws.agentcore.policy.authorization_decision'] = "DENY" }`. Redundant with the free V7, so only worth it if V7 dimensions prove awkward | number | $0.30/mo | infra only (nested bracket syntax untested) |
| M6 | `ToolHandledError` per tool | One metric filter per TL group: `"returned an error"` / `"Unexpected error in"`, with the same metric name and a static dimension value per group (e.g. `Tool=block_credit_card`) | stacked line | $0.30 × 9 | infra only |
| E1 | Strands OTel metrics (`strands.tool.error_count`, `strands.tool.call_count`, tokens, TTFT) | ADOT EMF → namespace `bedrock-agentcore`, if the runtime exports metrics (see Gaps) | line | custom-metric rate per series, if present | none, if already emitted |

### Inferences
- **What to compute where.** For a demo dashboard, Logs Insights widgets (L1-L10) are the cheapest and most flexible route: no metrics, no deploy, and they render in the dashboard's time range. Metric filters (M1-M6) are needed only for (1) alarms and (2) long-range trends without re-scanning logs.
- **Mind the free tier.** About 10 metric-filter metrics would use the whole 10-metric free tier (Q4).
- **Dimensions from text log lines.** Metric filters can extract dimensions only from JSON or space-delimited events. The runtime lines are plain text, and their prefix format is not known: it depends on how the AgentCore runtime/ADOT formats Python `logging` output. Splitting `[CONFIRM]` by tool or decision as a metric dimension is therefore not reliable. Use one filter per (event, tool) if needed, or keep the per-tool split in Logs Insights.
- **"Replaced" is a model-quality signal, not proof of an attack.** Because it fires when the model omits `customer_id` too (customer_id_hook.py:63), the panel should be labeled "model didn't pass the session customer_id". The Cedar-level proof of a blocked cross-customer call is V7/L9 (`DENY` on `AuthorizeAction`).
- **Decline rate.** decline rate = declined / (approved + declined) per tool (M2 via metric math, or L2). Confirmations that are shown but never answered are not logged, so "abandoned confirmations" can't be measured from logs today.
- **Separate eval traffic from real traffic.** For L1/L1b, evaluator sessions are identifiable by `prompt.version` values of the form `<name>-<sha8>` and by `[EVAL] override` lines (eval_override.py:98-106). Customer traffic always carries `PROMPT_VERSION` and `MODEL_ID`.
- **Strands metrics depend on the exporter.** If the Strands OTel metrics (E1) do land in `bedrock-agentcore`, they give tool error counts and tokens per agent for free in code. They are billed as custom metrics, and every attribute combination is a separate metric. Whether ADOT 0.16.0 on Runtime actually exports them is not confirmed.
- **Prefer spans over log text where both exist.** L7/L8/L9 read structured attributes, so they need no log-format assumptions. They do depend on Transaction Search staying on.

### Gaps
- **Possible double counting.** Whether the agent's Python `logging` lines appear only in the `runtime-logs` stream, or also as OTel log records in `otel-rt-logs`, is not known. If both, text metric filters on RT would double-count. Run `filter @message like /\[PROMPT\]/ | stats count(*) by @logStream` once, and scope widgets with `filter @logStream like /runtime-logs/` if needed.
- **Tool error status on spans.** The exact Strands attribute or status for a failed tool on `execute_tool` spans (span `status.code` = ERROR vs a `tool.status` attribute) was not verified for strands-agents 1.32.0. Neither was whether a Lambda `{"error": …}` result reaches Strands as an MCP `isError` result.
- **Guardrail outcome on spans.** No source confirms the span attribute that records a guardrail intervention (`gen_ai.response.finish_reasons` is a guess).
- **Nested-key metric filters.** Whether metric-filter bracket notation works for nested keys (`$.attributes.['aws.agentcore.policy.authorization_decision']`) is documented only for a top-level key. Test it with `aws logs test-metric-filter` before relying on M5.
- **Are Strands metrics emitted at all?** Whether any Strands metrics are present today in namespace `bedrock-agentcore`; the list above is from the `main` branch, not 1.32.0. Check with `list-metrics --namespace bedrock-agentcore`.

---

## Q3. AgentCore Observability / CloudWatch GenAI Observability built-in dashboards: what they show, and whether a custom dashboard can link to or embed them

### Takeaway
GenAI Observability already gives per-agent runtime metrics, sessions, traces with trajectories, Policy data under the Gateway tab, and (once an online config exists) Evaluations. It is a console experience, not a set of widgets. A custom CloudWatch dashboard cannot embed it, but it can deep-link to it from a Markdown text widget, and it can reproduce its numbers with the vended metrics and span queries above. The "Model invocations" part of GenAI Observability needs Bedrock model invocation logging, which this stack does not enable.

### Cited Findings
- GenAI Observability > Bedrock AgentCore has three views:
  - "**Agents View** – Lists all your agents… Choose an agent to view runtime metrics, sessions, traces, and evaluations specific to that agent";
  - "**Sessions View**";
  - "**Traces View** – … explore the trace trajectory and timeline".
  — [View observability data in CloudWatch](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/view-observability-data-cloudwatch.html)
- "The CloudWatch generative AI observability page displays all of the service-provided metrics output by the AgentCore agent runtime, as well as span- and trace-derived data if you have enabled instrumentation". — [View observability data (AgentCore)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-view.html)
- Runtime resource-usage graphs: account-level graphs are under the **Runtime** tab and endpoint-level graphs on the AgentEndpoint page. Session-level CPU/memory charts come from USAGE_LOGS. — [Runtime observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html)
- "Policy related observability is displayed under the AgentCore Gateway tab in CloudWatch gen AI observability". The resource table marks Gateway as available in gen AI observability. — [AgentCore generated observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-service-provided.html). This conflicts with the Gateway page: "These metrics aren't available on the CloudWatch generative AI observability page." — [Gateway observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-gateway-metrics.html)
- Evaluation results show in GenAI Observability > Bedrock AgentCore > (agent/endpoint) > **Evaluations**. Online/batch metrics go to namespace `Bedrock-AgentCore/Evaluations` (EMF, keyed by evaluator and config). — wiring note Q8, citing [Results and output](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/results-and-output.html); eval-stack note, citing the [code-based evaluators blog](https://aws.amazon.com/blogs/machine-learning/build-custom-code-based-evaluators-in-amazon-bedrock-agentcore/)
- The Model Invocations dashboard: "You must enable Model invocation logging in Amazon Bedrock to view the invocations". It then shows invocation count, latency, token counts by model, daily tokens by ModelID, requests grouped by input tokens, throttles and errors. — [Model Invocations (CloudWatch)](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/model-invocations.html)
- "All Automatic Dashboards are free." — [CloudWatch pricing (free tier)](https://aws.amazon.com/cloudwatch/pricing/)
- A text widget "shows an arbitrary piece of MarkDown". — [CDK aws-cloudwatch README](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_cloudwatch-readme.html)
- Custom widgets call a Lambda that "returns HTML to the CloudWatch dashboard", get a `widgetContext` (dashboard time range, parameters), and support `<cwdb-action>` interactivity. — [Custom widgets blog](https://aws.amazon.com/blogs/mt/introducing-amazon-cloudwatch-dashboards-custom-widgets/)

### Inferences
- **Link, don't embed.** Put a Markdown text widget at the top of the custom dashboard with deep links to the GenAI Observability agent page (Sessions, Traces, Evaluations), Transaction Search and the Gateway tab. Clicking a link opens the console page; there is no iframe-style embedding of console pages. This is an inference from the widget types above, as no doc says embedding is possible.
- **What the custom dashboard should add.** GenAI Observability does not show the LedgerLens business signals: confirmations, customer-id overwrites, hand-offs, feedback, and per-tool Cedar denies on one screen. It is also not co-located with harness evaluation results. That is the custom dashboard's job.
- **Skip model invocation logging.** It would fill the Model Invocations dashboard, but it logs full prompts and responses, which here contain card digits and transactions (the guardrail masks nothing, agent-guardrail.ts:88-92). It also adds ingestion cost. The free `AWS/Bedrock` metrics (V10) already give tokens and latency per model, so it isn't needed.

### Gaps
- Whether GenAI Observability graphs have an "Add to dashboard" action, as Logs Insights does, was not found in the docs.
- The Gateway-page vs overview-page conflict (whether Gateway metrics appear in GenAI Observability) is unresolved.
- No stable, documented deep-link URL format for GenAI Observability agent and session pages was found. Copy the URLs from the console.

---

## Q4. Business signals: feedback ratings (DynamoDB) and hand-off ticket counts, and the cost of the dashboard pieces

### Takeaway
Hand-off counts are available today: hand-off Lambda `Invocations` (V12), Policy `AllowDecisions{ToolName=hand-off}` (V7), the `[CONFIRM] … human_agent_hand_off` approvals (L2) and the "queued HO-" log line (L10/M4). The reason mix needs a one-line log change. Feedback ratings exist only as DynamoDB items, so charting them needs one of three things:
- a custom widget that queries the existing `feedbackType-timestamp-index` GSI (infra only);
- Powertools Metrics in the feedback Lambda, which already has the Powertools layer (small code change);
- a log line plus a metric filter.

Overall dashboard cost is near zero: vended metrics are free, 3 dashboards are free, Logs Insights is $0.005/GB scanned, and each metric-filter metric is $0.30/month after the 10 free.

### Cited Findings
- Feedback item fields: `feedbackId`, `sessionId`, `message`, `userId`, `feedbackType` (`positive`/`negative`), `timestamp` (ms), optional `comment` — [feedback/index.py:139-154](../../../infra-cdk/lambdas/feedback/index.py#L139-L154). GSI `feedbackType-timestamp-index` (pk feedbackType, sk timestamp, projection ALL) — [backend-construct.ts:544-555](../../../infra-cdk/lib/backend-construct.ts#L544-L555)
- The feedback Lambda already uses `aws_lambda_powertools` `Logger` and `Tracer`, with the `AWSLambdaPowertoolsPythonV3-python313-arm64:18` layer — [index.py:12, 42-43](../../../infra-cdk/lambdas/feedback/index.py#L12-L43); [backend-construct.ts:601-609](../../../infra-cdk/lib/backend-construct.ts#L601-L609)
- Custom widgets run a Lambda and render its HTML. The dashboard's time range is passed in `widgetContext`. — [Custom widgets blog](https://aws.amazon.com/blogs/mt/introducing-amazon-cloudwatch-dashboards-custom-widgets/). "When your dashboard displays custom widgets … you incur charges for the execution of the corresponding Lambda function." — [CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)
- Free tier: "3 Custom Dashboards referencing up to 50 metrics each per month"; "10 Metrics (of Custom Metrics and Detailed Monitoring Metrics)"; "10 Alarm metrics (only applicable to Standard resolution alarms…)"; "5 GB Data (ingestion, archive storage, and data scanned by Logs Insights queries)"; "1 Contributor Insights rule per month". — [CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)
- Custom metrics are "$0.30 per metric for first 10,000 metrics". "CloudWatch treats each unique combination of dimensions as a separate metric". PutMetricData costs "$0.01/M requests". — [CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)
- Dashboards beyond the free tier: "$3.00 per dashboard per month" (the "first 3 dashboards for up to 50 metrics" are free). — [Distributed Load Testing solution cost](https://docs.aws.amazon.com/solutions/latest/distributed-load-testing-on-aws/cost.html); [IVS dashboard blog](https://aws.amazon.com/blogs/media/monitoring-amazon-ivs-with-a-cloudwatch-dashboard/)
- "When your dashboard loads data from a logs query, you incur charges for the execution of the query." — [CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/). An AWS solution's cost table prices "72GB data scanned" by Logs Insights at "$0.36", which is $0.005/GB. — [Secure Media Delivery solution cost](https://docs.aws.amazon.com/solutions/latest/secure-media-delivery-at-the-edge-on-aws/cost.html)
- EMF-based metrics carry "3 billing dimensions: Logs Ingestion, Logs Storage and Metrics Storage". This is stated for Container Insights, but EMF works the same way. — [CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)
- Transaction Search span ingestion: an AgentCore pricing example uses "$0.35/GB" for spans. The hackathon volume estimate was under $0.50. — wiring note Q2, citing [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)

### Inventory: business signals

| # | Signal | Recipe | Widget | Cost | Change? |
|---|---|---|---|---|---|
| B1 | Hand-offs per day | `AWS/Lambda Invocations{FunctionName=ledgerlens-human-agent-hand-off}`. It counts every call, including validation failures, so subtract `"returned an error"` lines (L6), or use M4 / L10 | number + bar | free / $0.30 | none / infra |
| B2 | Hand-offs the customer approved vs declined | L2 filtered to `human_agent_hand_off` (the hook covers the hand-off, confirmation_hook.py:32) | stacked bar | scan | none |
| B3 | Hand-off reason and priority mix | priority: L10 today; reason: L11(a) | pie / bar | scan | reason: one-line log change |
| B4 | Hand-off share of sessions ("containment" proxy) | queued hand-offs (M4) / `SessionCount` (V1) via metric math | single value | $0.30 | infra only |
| B5 | Feedback positive/negative counts and rate | Option A: a custom widget Lambda queries the GSI per `feedbackType` with `timestamp BETWEEN start AND end` from `widgetContext` (`Select=COUNT`) and returns an HTML table or rate. Option B: Powertools `Metrics` in the feedback Lambda (EMF, namespace e.g. `LedgerLens/Feedback`, dimension `FeedbackType`), 2 metrics. Option C: `logger.info("feedback", extra={"feedback_type": …})` plus a JSON metric filter `{ $.feedback_type = "negative" }` on `/aws/lambda/ledgerlens-bank-assistant-feedback` | A: custom widget; B/C: line + number | A: Lambda + DynamoDB reads; B/C: $0.60/mo | A: infra only (new Lambda + IAM read on the GSI); B/C: small code change + deploy |
| B6 | Feedback API traffic and failures | `AWS/ApiGateway Count/4XXError/5XXError{ApiName=ledgerlens-bank-assistant-api, Stage=prod}` | number | already billed (detailed metrics) | none |
| B7 | Blocked cards / opened claims (business actions) | `AWS/Lambda Invocations` for `ledgerlens-block-credit-card` / `ledgerlens-open-claim`, minus errors; or the success `logger.info` in each handler (block_credit_card handler.py:95, open_claim handler.py:90) as a metric filter. `AWS/AuroraDSQL TotalTransactions − ReadOnlyTransactions` is a coarse cross-check | number | free / $0.30 each | none / infra |

### Inferences
- **The cheapest feedback panel today is Option A**, a custom widget over the existing GSI, because it needs no change to the deployed feedback Lambda. Option B (Powertools Metrics) is the cleanest long-term design, since the layer is already attached, and it makes ratings alarmable. With Option B, emit only `FeedbackType` as a dimension, never `sessionId`, so the series count stays at 2.
- **API Gateway settings worth a second look.** `deployOptions.metricsEnabled: true` (backend-construct.ts:645) turns on detailed metrics, which the pricing example bills per method × resource × stage × metric. The same stage enables a 0.5 GB cache cluster for a POST-only API (backend-construct.ts:638-642). Both are small standing costs with no dashboard value; this is outside this question's scope and noted only as an observation.
- **Likely total for one LedgerLens dashboard** at hackathon volume:
  - $0 for the dashboard, if it is one of the account's first 3 and has ≤ 50 metrics;
  - $0 for all vended metrics (V1-V15);
  - cents for Logs Insights widgets (MB-scale scans at $0.005/GB, inside the 5 GB free tier if the account is otherwise idle);
  - about $0.30 per metric-filter metric beyond the 10 free;
  - $0.10 per standard alarm metric beyond the 10 free (a rate taken from a pricing-page summary; see Gaps).

### Gaps
- The standard alarm price ($0.10 per alarm metric-month) and the absence of any charge for metric filters themselves came only from a WebFetch summary of the pricing page. That same summary misreported other rates (dashboards, Logs Insights), and the page text read directly did not show the rate tables. Treat both as unconfirmed.
- Whether Logs Insights widgets count toward the "50 metrics" free-dashboard limit was not found.
- No source covers how the frontend shows feedback or hand-off outcomes beyond what the Lambdas return, for example whether the human-agent desk records a resolution.

---

## Q5. Alarms worth adding

### Takeaway
A small set of high-signal alarms fits in the 10 free alarm metrics:
- Cedar `DenyDecisions` on `AuthorizeAction` above 0 (it should never fire);
- Runtime system errors and throttles;
- Bedrock throttles and server errors for the customer model;
- an "Agent run failed" log metric;
- guardrail-intervention and customer-id-overwrite spikes;
- tool handled-error rate.

The last three need metric filters (infra only).

### Cited Findings
- Gateway alarm example: `put-metric-alarm --metric-name SystemErrors --namespace AWS/Bedrock-AgentCore --statistic Sum --dimensions Name=Resource,Value=<gateway-arn> --period 300 --threshold 5 …`. — [Gateway observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-gateway-metrics.html)
- `ActiveSessionCount` is suggested "to set alarms for unexpected usage spikes, and understand your session quota consumption". — [Runtime observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html)
- Guardrails: alarm on `InvocationsIntervened` to "catch jailbreak or data leakage attempts or discussions of sensitive topics". — [re:Post: monitoring Bedrock Guardrails](https://repost.aws/articles/AR-ZBYACEoSSeYSLhKzu83uQ/troubleshooting-and-monitoring-amazon-bedrock-guardrails-usage-with-amazon-cloudwatch)
- Bedrock example: an alarm on `InputTokenCount` (Sum, 300 s) scoped with `ModelId`, and threshold guidance to "Set the production threshold at 3–5 times the observed peak" or use anomaly detection. — [re:Post: Bedrock cost spikes](https://repost.aws/articles/AR_gbMkpbaTJOwRyCpqGf6uA/analyze-amazon-bedrock-cost-spikes-with-aws-devops-agent)
- Anomaly-detection alarms bill "two additional alarm-metric costs" for the band. Log query alarms incur "a standard alarm cost plus query charges". — [CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)
- Evaluation scores are EMF metrics in `Bedrock-AgentCore/Evaluations`, "so CloudWatch Alarms can be set on them". — eval-stack note, citing the [code-based evaluators blog](https://aws.amazon.com/blogs/machine-learning/build-custom-code-based-evaluators-in-amazon-bedrock-agentcore/)

### Inventory: proposed alarms

| # | Alarm | Metric | Condition | Why for LedgerLens | Change? |
|---|---|---|---|---|---|
| A1 | Cedar blocked a real tool call | `AWS/Bedrock-AgentCore DenyDecisions{OperationName=AuthorizeAction, …}` (or a SEARCH-based widget plus a concrete alarm once dimensions are confirmed) | Sum ≥ 1 in 5 min | Both hooks should make this impossible. A deny means a hook was bypassed, a cross-customer id or an unconfirmed write (policy.cedar:56-91) | infra only |
| A2 | Runtime platform errors | `AWS/Bedrock-AgentCore SystemErrors` + `Throttles{Resource=<runtime ARN>}` | Sum ≥ 1 in 5 min | outage or quota | infra only |
| A3 | Agent-internal failures | M1 `AgentRunFailed` | Sum ≥ 3 in 5 min (or ≥ 1 during a demo) | catches Bedrock, Gateway, memory and code exceptions that the runtime metrics miss | infra only (metric filter + alarm) |
| A4 | Model throttling or server errors | `AWS/Bedrock InvocationThrottles`, `InvocationServerErrors{ModelId=deepseek.v3.2}` | Sum ≥ 1 in 5 min | the customer model is degraded (retries inflate latency) | infra only |
| A5 | Guardrail intervention spike | `AWS/Bedrock/Guardrails InvocationsIntervened{GuardrailArn, GuardrailVersion}` (optionally `GuardrailPolicyType=ContentPolicy` for prompt attacks) | static threshold above the observed peak, or anomaly band | jailbreak / prompt-attack wave, or a guardrail over-blocking legitimate card questions after a config change | infra only (confirm the metric exists, Q1 gap) |
| A6 | Customer-id overwrite spike | M3 `CustomerIdReplaced` | Sum > N per hour | a model/prompt regression where the model stops passing the session customer_id, or a prompt-injection attempt | infra only |
| A7 | Tool handled-error rate | M6 per tool, or the sum vs the Lambda `Invocations` via metric math | error rate > 20% over 15 min | DSQL connectivity or data bugs, hidden because Lambda `Errors` stays 0 | infra only |
| A8 | Tool timeouts / crashes | `AWS/Lambda Errors{FunctionName=ledgerlens-<slug>}` | Sum ≥ 1 | the only failures Lambda `Errors` does catch (timeouts 30 s/10 s) | infra only |
| A9 | Evaluation score drop (later) | `Bedrock-AgentCore/Evaluations` metric for GoalSuccessRate | below the baseline | quality regression in live traffic once online eval is enabled | after the online eval config exists |

### Inferences
- **Fit within the free alarms.** A1-A4 plus A8 for the two write tools uses about 8 alarm metrics, within the 10-metric free tier. Each alarm counts every metric it lists, so prefer one alarm per critical metric over math expressions with many metrics.
- **Treat missing data as not breaching.** At hackathon volume most periods have no data. Set `treatMissingData: notBreaching` on count alarms so A1-A8 don't flap to INSUFFICIENT_DATA. This is standard alarm configuration, not specific to these metrics.
- **Keep A1 even though it duplicates the Policy spans.** The vended metric needs no tracing and is free, so it is the most robust "safety layer worked" signal for the demo. The `aws/spans` L9 widget then explains *which* policy denied.

### Gaps
- The concrete dimension set needed to alarm on `DenyDecisions` for `OperationName=AuthorizeAction` across all tools, without one alarm per `ToolName`, depends on which combinations AWS publishes (Q1 gap). A Metrics Insights query alarm could aggregate across tools, but its pricing ("each metric analyzed by the query") and syntax were not checked for this namespace.
- No source gives baseline volumes for LedgerLens, so the thresholds above are placeholders to tune after a pilot run.
