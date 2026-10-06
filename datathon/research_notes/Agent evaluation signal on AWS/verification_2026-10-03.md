# Verification of the AWS evaluation-stack claims (2026-10-03, us-east-1)

Scope: this file checks the report sections "AgentCore Evaluations holds the ground truth; Lambda evaluators deliver the verdicts" and "Observability and Cedar spans supply the evidence" in `datathon/reports/Agent evaluation signal on AWS.md`, plus the matching raw notes in `aws_evaluation_stack.md`.

Method: every claim was checked against AWS docs read on 2026-10-03 (devguide, boto3/API reference, pricing page, What's New, release notes, CloudFormation reference). Where the docs were silent, the shipped code was read instead: wheels `bedrock-agentcore==1.24.0` and `strands-agents-evals==1.4.0`, and the `bedrock-agentcore` service models inside `botocore==1.43.108`.

Verdicts: **CONFIRMED** means a primary source states it. **CORRECTED** means the claim is wrong or out of date, and the correct fact is given. **UNVERIFIED** means no primary source was found.

## Verdict table

| # | Claim | Verdict | Correct / verified fact | Source |
|---|---|---|---|---|
| 1 | Evaluations went GA on 2026-03-31 in nine Regions, us-east-1 included | **CONFIRMED** | Posted Mar 31, 2026. Regions: us-east-1, us-east-2, us-west-2, ap-south-1, ap-southeast-1, ap-southeast-2, ap-northeast-1, eu-central-1, eu-west-1. **Batch evaluation went GA separately in July 2026.** Dataset evaluation (runners) is still public preview. | https://aws.amazon.com/about-aws/whats-new/2026/03/agentcore-evaluations-generally-available/ ; https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html |
| 2a | Ground-truth fields are `assertions`, `expectedTrajectory` and `expectedResponse` | **CONFIRMED** | Each field takes a specific API shape: `expectedResponse: {"text": str}` (trace scope, tied to a trace by `context.spanContext.traceId`); `assertions: [{"text": str}, ...]` (session); `expectedTrajectory: {"toolNames": [str, ...]}` (session). Every reference input needs `context.spanContext.sessionId`. | https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agentcore/client/evaluate.html |
| 2b | Which evaluators consume each field | **CONFIRMED** | `Builtin.Correctness` (trace) uses `expectedResponse`. `Builtin.GoalSuccessRate` (session) uses `assertions`. The three trajectory evaluators (session) use `expectedTrajectory`. Fields an evaluator doesn't use are reported in `ignoredReferenceInputFields`. Without ground truth, each evaluator falls back to its ground-truth-free variant. | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ground-truth-evaluations.html |
| 2c | The trajectory matcher IDs are `ExactOrderMatch` / `InOrderMatch` / `AnyOrderMatch` | **CORRECTED** (ID form) | The exact API IDs are `Builtin.TrajectoryExactOrderMatch`, `Builtin.TrajectoryInOrderMatch` and `Builtin.TrajectoryAnyOrderMatch`. They are **session-level**; one blog's table lists them as TOOL_CALL, and the docs win. | ground-truth-evaluations.html (above) |
| 2d | The matchers are programmatic, with no LLM calls | **CONFIRMED** | "use programmatic scoring (no LLM calls, so token usage is zero)". | ground-truth-evaluations.html |
| 2e | Built-in IDs use the form `Builtin.GoalSuccessRate` | **CONFIRMED** | The ID format is `Builtin.<Name>`. The ARN is `arn:aws:bedrock-agentcore:::evaluator/Builtin.<Name>`. | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/built-in-evaluators-overview.html |
| 2f | (report) The ground-truth GoalSuccessRate prompt judges "by their intent…" **and** says "the tool output ALWAYS takes priority over your own knowledge" | **CORRECTED** | The "tool output ALWAYS takes priority" line is in the **ground-truth-free** GoalSuccessRate prompt. The ground-truth variant contains "by their intent, not by exact text matching" and also: *"If an assertion describes a specific action or tool call … and the agent achieved the same outcome through an alternative approach … consider the assertion satisfied."* That leniency matters: ordering and "did NOT call X before Y" checks belong in code, not in assertions. | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/prompt-templates-builtin.html |
| 3a | A code-based evaluator receives the session's OTel spans | **CONFIRMED, plus more** | The event has these keys: `schemaVersion` ("1.0"), `evaluatorId`, `evaluatorName`, `evaluationLevel` (`TRACE`/`TOOL_CALL`/`SESSION`), `evaluationInput.sessionSpans` (truncated if over 6 MB), **`evaluationReferenceInputs`** (ground truth, filtered by level: SESSION gets all; TRACE gets session-level plus matching traceId; TOOL_CALL gets session-level plus matching spanId), and `evaluationTarget.traceIds` / `.spanIds` (`None` at session level). **There is no top-level session-id field.** Read it from span `attributes["session.id"]` or from `evaluationReferenceInputs[].context.spanContext.sessionId`. Lambda limits: 5-minute maximum runtime, 6 MB payload. | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-based-evaluators.html |
| 3b | It returns `{"label":"PASS","value":1.0,"explanation":"..."}` | **CONFIRMED** | `label` is required; `value` (number) and `explanation` are optional. The error form is `{"errorCode", "errorMessage"}`, both required. | code-based-evaluators.html |
| 3c | It is registered through an API call | **CONFIRMED** | Call `boto3.client("bedrock-agentcore-control").create_evaluator(evaluatorName=…, level="SESSION"\|"TRACE"\|"TOOL_CALL", evaluatorConfig={"codeBased":{"lambdaConfig":{"lambdaArn":…, "lambdaTimeoutInSeconds":1-300 (default 60)}}})`. The name must match `[a-zA-Z][a-zA-Z0-9_]{0,47}`. The `evaluatorConfig` union is `llmAsAJudge` \| `codeBased` \| `derived`. The Lambda must be in the same Region, and the service needs `lambda:InvokeFunction` and `lambda:GetFunction`. The CDK construct grants invoke to `bedrock-agentcore.amazonaws.com` with SourceArn/SourceAccount conditions. | code-based-evaluators.html ; botocore `bedrock-agentcore-control` model ; https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_bedrockagentcore-readme.html |
| 3d | Works in on-demand AND batch AND online modes | **PARTLY CONFIRMED** | On-demand (`Evaluate`) and online (`CreateOnlineEvaluationConfig`) are documented with examples. For batch, the API accepts "built-in evaluators and custom evaluators", and the ID pattern admits custom IDs. Code-based evaluators sit under "Custom evaluators" in the docs, but **no doc shows a code-based evaluator in a batch job**. An enabled online config **locks** the code-based evaluator, so it can't be updated or deleted until the config is disabled. | code-based-evaluators.html ; https://docs.aws.amazon.com/cli/latest/reference/bedrock-agentcore/start-batch-evaluation.html |
| 3e | Code-based evaluator billing | **UNVERIFIED** | The pricing page lists only built-in token rates, "Custom evaluators: $1.50 per 1,000 evaluations (model usage billed separately)" and batch token rates. Code-based is never named. Conservative assumption: $1.50 per 1K plus your own Lambda cost. | https://aws.amazon.com/bedrock/agentcore/pricing/ |
| 4a | On-demand: one evaluator per call, synchronous | **CONFIRMED** | `Evaluate` takes a single `evaluatorId`. The quota "Evaluators per on-demand evaluation" is 1 and not adjustable. The API is described as "This synchronous API…". (The code-based blog's "up to 10 evaluators per on-demand call" is wrong; the SDK's `EvaluationClient.run` loops one call per evaluator and splits trace/span targets into batches of up to 10.) | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html ; evaluate.html |
| 4b | Batch takes ground truth through session metadata | **CONFIRMED** | Shape: `evaluationMetadata={"sessionMetadata":[{"sessionId", "testScenarioId", "groundTruth":{"inline":{"assertions":[{"text"}], "expectedTrajectory":{"toolNames":[…]}, "turns":[{"input":{"prompt"}, "expectedResponse":{"text"}}]}}, "metadata":{str:str}}]}`. A job allows **at most 10 evaluators**, 10 log groups (or 5 prefixes), and requires `serviceNames`. | https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agentcore/client/start_batch_evaluation.html |
| 4c | Batch is about 25% cheaper | **CONFIRMED** | "$0.0018 per 1,000 input token, $0.009 per 1,000 output tokens"; "Batch evaluations are charged at a 25% discount on standard AgentCore Evaluations rates". | pricing page |
| 4d | (report) `BatchEvaluationRunner` returns only an aggregate summary | **CORRECTED** (minor) | It returns an aggregate `BatchEvaluationSummary` **plus per-session detail in CloudWatch Logs** (`outputConfig.cloudWatchConfig`; event attributes `gen_ai.evaluation.score.value`, `gen_ai.evaluation.score.label` and `gen_ai.evaluation.explanation`). | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/dataset-evaluations.html ; https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/batch-evaluations-getting-started.html |
| 4e | Online mode has no ground truth | **CONFIRMED** | "Ground truth: Not supported". Custom evaluators that use `{assertions}`, `{expected_response}` or `{expected_tool_trajectory}` are rejected in online configs. | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/batch-evaluations.html ; https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/create-evaluator.html |
| 4f | boto3 client and operation names | **CONFIRMED** | Data plane `bedrock-agentcore`: `evaluate`, `start_batch_evaluation`, `get_batch_evaluation` (also list/stop/delete), `invoke_agent_runtime`. Control plane `bedrock-agentcore-control`: `create_evaluator`, `create_online_evaluation_config` (also get/list/update/delete). **The batch APIs are on the data-plane client, not the control plane.** Batch status values: `PENDING`, `IN_PROGRESS`, `COMPLETED`, `COMPLETED_WITH_ERRORS`, `FAILED`, `STOPPING`, `STOPPED`, `DELETING`. | botocore 1.43.108 service models ; start_batch_evaluation.html |
| 5a | Dataset runners are in preview | **CONFIRMED** | "Dataset evaluation is in public preview." The batch models in SDK 1.24.0 say "This feature is in preview". The runners are client-side SDK code that call the GA `Evaluate` and `StartBatchEvaluation` APIs, so us-east-1 support follows from those APIs. | dataset-evaluations.html |
| 5b | Package and version | **CONFIRMED** (version added) | `pip install bedrock-agentcore`; the current release is **1.24.0** (2026-09-28). `from bedrock_agentcore.evaluation import OnDemandEvaluationDatasetRunner, BatchEvaluationRunner, EvaluationRunConfig, EvaluatorConfig, CloudWatchAgentSpanCollector, FileDatasetProvider, Dataset, PredefinedScenario, Turn, SimulationConfig`. Signatures: `EvaluationRunConfig(evaluator_config=EvaluatorConfig(evaluator_ids=[…]), evaluation_delay_seconds=180, max_concurrent_scenarios=5, simulation_config=None)`; `OnDemandEvaluationDatasetRunner(region).run(config, dataset, agent_invoker, span_collector)`. | https://pypi.org/project/bedrock-agentcore/ ; https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-python-sdk-reference.html |
| 5c | Scenario JSON schema | **CONFIRMED** | Predefined scenario: `scenario_id` (required), `turns[]` (required; each has `input` (required, a string or object) and an optional `expected_response`), `expected_trajectory`, `assertions`, `metadata`. Simulated scenario: `scenario_id`, `actor_profile{context, goal, traits?}`, `input`, `scenario_description?`, `max_turns` (default 10), `assertions`, `metadata`. Turn N's `expected_response` maps positionally to trace N. | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/dataset-evaluations-schema.html |
| 5d | Simulated scenarios lack `expected_trajectory` and per-turn `expected_response` | **CONFIRMED** | "Simulated scenarios do not support `expected_trajectory` or per-turn `expected_response`… Use `assertions`." | dataset-evaluations-schema.html |
| 6 | Spans are ready 2–5 minutes after a session; `evaluation_delay_seconds=180` | **CONFIRMED** (with nuance) | The ground-truth page says "wait 2–5 minutes for CloudWatch to ingest". The batch walkthrough says 2–3 minutes. The SDK default is 180 s, and `CloudWatchAgentSpanCollector` polls every 30 s for up to 300 s. A release note (April 2026) says put-to-get latency for complete traces is under 10 s, so 180 s is conservative. Online results appear only after the session has been idle for `sessionTimeoutMinutes` (default 15), "then within roughly 15 minutes" of the next scoring cycle. | ground-truth-evaluations.html ; batch-evaluations-getting-started.html ; release-notes.html ; https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ab-testing-3p-agents.html |
| 7a | Strands span names `invoke_agent`, `execute_tool`, `chat`; attributes `session.id`, `gen_ai.tool.name` | **CONFIRMED** | Spans are classified by `gen_ai.operation.name`, and names look like `invoke_agent <Agent>`, `execute_tool <tool>` and `chat`. Tool spans carry `gen_ai.tool.name`, `gen_ai.tool.call.id`, `gen_ai.tool.status` and `session.id` (the Runtime injects it). Python scope: `strands.telemetry.tracer`. Tool arguments are in `events[gen_ai.tool.message].attributes.content` (unified telemetry) or in the event record's `body.input.messages` (split telemetry). | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks-strands.html |
| 7b | Spans land in the `spans` stream of `/aws/bedrock-agentcore/runtimes/<agent_id>-<endpoint>` | **CONFIRMED only for unified telemetry** | **Unified telemetry is the default only for agents created on or after 2026-07-20.** Older agents use split telemetry: spans go to `aws/spans` and event records go to the `otel-rt-logs` stream of the runtime log group. Switch with the env var `UNIFIED_TRACES_DESTINATION_ENABLED=true`, which needs ADOT `aws-opentelemetry-distro>=0.18.0` and `logs:PutResourcePolicy` on the execution role. **Gateway and Policy spans always go to `aws/spans`.** | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks-telemetry.html ; release-notes.html |
| 7c | Transaction Search must be enabled, as a one-time account setting | **CONFIRMED** | AgentCore calls it a "one-time setup", and CloudWatch says it "is configured for the entire account". Enable it in the console (CloudWatch > Application Signals > Transaction Search > Enable, ingest spans as structured logs) or by API: `aws logs put-resource-policy` (allow `xray.amazonaws.com` `logs:PutLogEvents` on `aws/spans` and `/aws/application-signals/data`), then `aws xray update-trace-segment-destination --destination CloudWatchLogs`, then optionally `aws xray update-indexing-rule`. Check with `aws xray get-trace-segment-destination`, which should return `{"Destination":"CloudWatchLogs","Status":"ACTIVE"}`. It can take 10 minutes to take effect. The API calls are regional, so run them in us-east-1. | https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Enable-TransactionSearch.html ; https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html |
| 8a | Policy span attributes `aws.agentcore.policy.authorization_decision`, `.authorization_reason`, `.determining_policies` | **CONFIRMED** | These appear on `AuthorizeAction` spans (values `ALLOW`/`DENY`), along with `.mismatched_policies`, `.effects`, `.types`, `.guardrails.<contentFilter\|promptAttack\|sensitiveInformation>.scores`, `aws.agentcore.gateway.policy.mode` and `.target_resource.id`. `PartiallyAuthorizeActions` spans carry `.allowed_tools` and `.denied_tools`. **The documented AuthorizeAction attributes include no tool name**; tool name is only a metric dimension, and Gateway "Call Tool" spans carry `tool.name`. | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-policy-metrics.html |
| 8b | Metrics `AllowDecisions` / `DenyDecisions` | **CONFIRMED** | Namespace `AWS/Bedrock-AgentCore`, emitted by default without tracing. Dimensions include `OperationName`, `PolicyEngine`, `Policy`, `TargetResource`, `ToolName` and `Mode`. | observability-policy-metrics.html |
| 8c | How Gateway tracing is enabled | **CONFIRMED** (console/API); CFN **UNVERIFIED** | Console: Gateway > Tracing > Edit > Enable; Transaction Search must already be on. API: CloudWatch Logs vended delivery, i.e. `put_delivery_source(logType="TRACES", resourceArn=<gateway ARN>)`, then `put_delivery_destination(deliveryDestinationType="XRAY")`, then `create_delivery`. There is no `Gateway` resource property for it. The CloudFormation equivalent is presumably `AWS::Logs::DeliverySource` + `AWS::Logs::DeliveryDestination` (X-Ray is a supported destination) + `AWS::Logs::Delivery`, but that path wasn't tested. The aws-samples telemetry stack uses a Lambda custom resource for Gateway. | observability-configure.html ; https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-logs-deliverydestination.html |
| 8d | Gateway spans share the trace ID with the agent's spans | **UNVERIFIED** | Gateway vended spans and logs carry `trace_id`/`span_id`. For the **gateway → agent** direction (A/B routing), the docs say the pipeline "joins the gateway span to your agent's spans by `traceId`". For **agent → gateway** (our tool calls), Strands' `MCPClient` injects OTel context into the MCP `_meta` field, but no doc says Gateway reads `_meta` or `traceparent`. Test it empirically (see the last section). | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ab-testing-3p-agents.html ; https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-gateway-metrics.html ; https://strandsagents.com/docs/api/python/strands.tools.mcp.mcp_instrumentation/index.md |
| 9 | `runtimeSessionId` minimum length "believed ≥ 33" | **CONFIRMED** (now verified) | On the request it must be 33–256 characters, with no pattern; it is an idempotency token that is auto-filled if omitted. **The echoed response header is 1–100 characters and must match `[a-zA-Z0-9][a-zA-Z0-9-_]*`.** Use 33–100 characters drawn from `[A-Za-z0-9_-]`, starting alphanumeric. (AWS's own batch walkthrough generates 21-character IDs such as `acme-eval-<12 hex>`, which break the 33 minimum.) | https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_InvokeAgentRuntime.html ; botocore model |
| 10a | 13 built-in evaluators | **CONFIRMED, now outdated** | There were 13 "core" built-ins at GA: GoalSuccessRate, Helpfulness, Correctness, Faithfulness, Harmfulness, Stereotyping, Refusal, Coherence, ResponseRelevance, Conciseness, InstructionFollowing, ToolSelectionAccuracy, ToolParameterAccuracy. There are also 3 `Builtin.Trajectory*` evaluators, plus `Builtin.SkillSelectionAccuracy` and `Builtin.SkillInstructionFollowing` (August 2026), for **18 `Builtin.*` IDs**. Managed DeepEval/AutoEval third-party evaluators are also available. `ContextRelevance` appears only in a blog and `Maliciousness` nowhere, so neither is confirmed. | prompt-templates-builtin.html ; https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/skill-evaluators.html ; release-notes.html |
| 10b | The judge model is undisclosed or not configurable | **CONFIRMED** | Built-ins "use predefined evaluator models… cannot be modified", via geography-bounded cross-region inference; for the US that is us-east-1, us-east-2 and us-west-2. No model ID is published. A "derived" evaluator can run a built-in's logic on your own model. | built-in-evaluators-overview.html ; https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/cross-region-inference.html ; https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/third-party-evaluators.html |
| 10c | A custom LLM evaluator can use a non-Anthropic Bedrock model | **CONFIRMED** | `modelConfig.bedrockEvaluatorModelConfig.modelId` accepts any supported Bedrock foundation model in the Region (bedrock-runtime). `responsesEvaluatorModelConfig` uses the bedrock-mantle endpoint; the docs' example is `openai.gpt-oss-120b`. | create-evaluator.html |
| 11 | Pricing | **CONFIRMED** (code-based still unknown) | Built-ins: $0.0024 per 1K input tokens and $0.012 per 1K output tokens, model included. Custom: $1.50 per 1K evaluations plus your model usage. Batch: $0.0018 per 1K input and $0.009 per 1K output. Worked examples: $1,782 / 45,000 ≈ **$0.0396** per built-in evaluation; $89.10 / 3,000 ≈ **$0.0297** per batch evaluation (15K input / 300 output tokens). Trajectory matchers use zero tokens, so they cost $0 at token rates (by inference). Policy: $0.000025 per authorization. Gateway: $0.005 per 1K invocations. | pricing page |
| 12 | `strands-agents-evals` is at v0.1.0 | **CORRECTED** | The current version is **1.4.0** (2026-09-22; Python ≥ 3.10; v0.1.0 was 2025-12-03). 1.4.0 exports `Case`, `Experiment`, `ActorSimulator`, `UserSimulator`, `EvaluationReport`, `providers.CloudWatchProvider(region, log_group, agent_name, lookback_days=30, …)` (also Langfuse and OpenSearch providers), and `simulation.ToolSimulator`. Its LLM evaluators include GoalSuccessRate, Trajectory, ToolSelection/ToolParameterAccuracy, Correctness, Helpfulness and others. **New deterministic evaluators** are `ToolCalled(tool_name)`, `Equals`, `Contains`, `StartsWith` and `StateEquals`, and there is a `chaos` module (`ChaosCase`, effects) for tool-failure injection. `Case` fields: `name`, `session_id`, `input`, `expected_output`, `expected_assertion`, `expected_trajectory`, `expected_interactions`, `expected_environment_state`, `metadata`. | https://pypi.org/project/strands-agents-evals/ (wheel inspected) |
| 13 | CloudFormation/CDK resource types exist | **CONFIRMED** | `AWS::BedrockAgentCore::Evaluator` (its `EvaluatorConfig` supports `CodeBased` and `LlmAsAJudge`) and `AWS::BedrockAgentCore::OnlineEvaluationConfig`, both added 2026-02-27. CDK L2 in `aws-cdk-lib.aws_bedrockagentcore`: `Evaluator`, `EvaluatorConfig.codeBased({lambdaFunction, timeout})`, `OnlineEvaluationConfig` and `EvaluatorSelector.builtin/custom`. **There is no resource for batch jobs or datasets**; those are runtime API calls. | https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrockagentcore-evaluator.html ; https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-bedrockagentcore-evaluator-evaluatorconfig.html ; CDK README (above) |

### Other corrections found while checking

| Topic | Fact | Source |
|---|---|---|
| Supported frameworks | The report says "Strands and LangGraph". It is now Strands, LangGraph, OpenAI Agents, LlamaIndex, Google ADK, Claude Agent SDK, Vercel AI SDK (TypeScript), and generic OTel/OpenInference. | release-notes.html |
| SDK code-based decorator | The devguide's sample imports `bedrock_agentcore.evaluation.code_based_evaluators.code_based_evaluator` and uses a one-argument function. **That module does not exist in `bedrock-agentcore` 1.24.0.** The shipped API is `from bedrock_agentcore.evaluation import custom_code_based_evaluator, EvaluatorInput, EvaluatorOutput`, applied as `@custom_code_based_evaluator()` to `def fn(input: EvaluatorInput, context) -> EvaluatorOutput`. The doc sample also filters on span names (`Model:` and `Agent.invoke`) that Strands doesn't emit. | code-based-evaluators.html vs. wheel `bedrock_agentcore/evaluation/custom_code_based_evaluators/` |
| Gateway tool names in `expectedTrajectory` | Gateway exposes tools as `${target_name}___${tool_name}`, with **three** underscores (the CDK README renders two). The `gen_ai.tool.name` the agent records, and therefore the trajectory ground truth, must use the prefixed name. | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-tool-naming.html |
| `EvaluationClient.run` log group | When given only `agent_id`, the SDK derives `/aws/bedrock-agentcore/runtimes/{agent_id}-DEFAULT` and queries **both** `aws/spans` and that group with `filter attributes.session.id = "<sid>"`. This works for split and unified telemetry. Pass `log_group_name` for a non-DEFAULT endpoint. | wheel `evaluation/client.py`, `agent_span_collector.py` |
| Online evaluators per config | The quota page says 25, not adjustable. The code-based blog's "up to 10" is out of date, and batch jobs separately cap at 10 evaluators. | bedrock-agentcore-limits.html ; start-batch-evaluation CLI ref |

## Sketch (a): evaluate one finished Runtime session with a built-in evaluator and ground truth

Sources: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ground-truth-evaluations.html (the SDK and boto3 tabs). The `invoke_agent_runtime` call follows https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/batch-evaluations-getting-started.html. Signatures were checked against `bedrock-agentcore` 1.24.0.

```python
import json, time, uuid
from datetime import datetime, timedelta, timezone
import boto3
from bedrock_agentcore.evaluation import EvaluationClient, ReferenceInputs

REGION, ACCOUNT, AGENT_ID = "us-east-1", "<account-id>", "<agent_id>"
AGENT_ARN = f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:runtime/{AGENT_ID}"

# runtimeSessionId: request 33-256 chars; response echo 1-100 chars, [a-zA-Z0-9][a-zA-Z0-9-_]*  -> keep 33..100
sid = f"ll-c0042-es-retail-r1-{uuid.uuid4().hex}"          # 54 chars; case/lang/segment/run encoded
dp = boto3.client("bedrock-agentcore", region_name=REGION)
r = dp.invoke_agent_runtime(agentRuntimeArn=AGENT_ARN, runtimeSessionId=sid,
                            payload=json.dumps({"prompt": "Bloquea mi tarjeta terminada en 4821"}).encode())
r["response"].read()
time.sleep(180)                                             # docs: wait 2-5 min for CloudWatch ingestion

# Option 1: SDK (fetches spans for you; one Evaluate call per evaluator under the hood)
ec = EvaluationClient(region_name=REGION)
results = ec.run(
    evaluator_ids=["Builtin.GoalSuccessRate", "Builtin.TrajectoryInOrderMatch"],
    agent_id=AGENT_ID,                                      # -> /aws/bedrock-agentcore/runtimes/<id>-DEFAULT + aws/spans
    session_id=sid,
    reference_inputs=ReferenceInputs(
        assertions=["Agent read back the last 4 digits before blocking the card"],
        expected_trajectory=["<target>___get_cards", "<target>___block_card"],  # Gateway-prefixed names
        # expected_response="..." or {trace_id: "..."} for Builtin.Correctness
    ),
)
for x in results:
    print(x["evaluatorId"], x.get("value"), x.get("label"), x.get("ignoredReferenceInputFields"), x.get("explanation", "")[:200])

# Option 2: raw boto3 (you supply the spans; exactly one evaluatorId per call)
from bedrock_agentcore.evaluation import CloudWatchAgentSpanCollector
spans = CloudWatchAgentSpanCollector(log_group_name=f"/aws/bedrock-agentcore/runtimes/{AGENT_ID}-DEFAULT",
                                     region=REGION).collect(session_id=sid,
                                     start_time=datetime.now(timezone.utc) - timedelta(hours=1),
                                     end_time=datetime.now(timezone.utc))
resp = dp.evaluate(
    evaluatorId="Builtin.TrajectoryExactOrderMatch",
    evaluationInput={"sessionSpans": spans},
    evaluationReferenceInputs=[{
        "context": {"spanContext": {"sessionId": sid}},
        "assertions": [{"text": "Agent read back the last 4 digits before blocking the card"}],
        "expectedTrajectory": {"toolNames": ["<target>___get_cards", "<target>___block_card"]},
    }],
)
for x in resp["evaluationResults"]:
    print(x["evaluatorId"], x.get("value"), x.get("label"), x.get("errorCode"), x.get("explanation"))
```

## Sketch (b): code-based evaluator Lambda handler

Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-based-evaluators.html (input schema, response schema, and ground truth in code-based evaluators). The span field names come from https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks-strands.html.

The handler has no SDK dependency. The event fields it reads are exactly the documented ones.

```python
import json

def _a(s):  # span attributes
    return s.get("attributes") or {}

def lambda_handler(event, context):
    try:
        level   = event["evaluationLevel"]                      # "SESSION" | "TRACE" | "TOOL_CALL"
        spans   = event["evaluationInput"]["sessionSpans"]      # OTel span dicts (+ event records in split telemetry); may be truncated >6 MB
        refs    = event.get("evaluationReferenceInputs") or []  # ground truth, pre-filtered by level
        target  = event.get("evaluationTarget") or {}           # None for SESSION
        trace_ids = set(target.get("traceIds") or [])           # TRACE and TOOL_CALL
        span_ids  = set(target.get("spanIds") or [])            # TOOL_CALL
        # also present: event["schemaVersion"] == "1.0", event["evaluatorId"], event["evaluatorName"]
    except (KeyError, TypeError) as e:
        return {"errorCode": "VALIDATION_FAILED", "errorMessage": f"unexpected event shape: {e}"}

    expected_tools, assertions, expected_text = [], [], None
    for ref in refs:   # each: {"context":{"spanContext":{"sessionId","traceId"?,"spanId"?}}, "expectedResponse"?, "assertions"?, "expectedTrajectory"?}
        expected_tools = (ref.get("expectedTrajectory") or {}).get("toolNames") or expected_tools
        assertions += [a.get("text") for a in ref.get("assertions") or []]
        expected_text = (ref.get("expectedResponse") or {}).get("text") or expected_text

    tool_spans = sorted(
        (s for s in spans
         if _a(s).get("gen_ai.operation.name") == "execute_tool"
         and (not trace_ids or s.get("traceId") in trace_ids)
         and (not span_ids or s.get("spanId") in span_ids)),
        key=lambda s: s.get("startTimeUnixNano", 0))
    actual_tools = [_a(s).get("gen_ai.tool.name") for s in tool_spans]
    session_id = next((_a(s)["session.id"] for s in spans if "session.id" in _a(s)), None)  # no top-level session field
    # tool args: unified -> span["events"][name=="gen_ai.tool.message"]["attributes"]["content"];
    #            split   -> separate event record (same traceId/spanId) body.input.messages

    passed = True   # <- LedgerLens deterministic grader goes here (ordering, key args, cross-customer IDs, ...)
    return {        # success shape: label REQUIRED; value, explanation optional
        "label": "PASS" if passed else "FAIL",
        "value": 1.0 if passed else 0.0,
        "explanation": json.dumps({"session": session_id, "level": level,
                                   "actual": actual_tools, "expected": expected_tools})[:4000],
    }
    # error shape (both required): {"errorCode": "...", "errorMessage": "..."}
```

Registration: `boto3.client("bedrock-agentcore-control").create_evaluator(evaluatorName="ll_record_checks", level="SESSION", evaluatorConfig={"codeBased":{"lambdaConfig":{"lambdaArn": ARN, "lambdaTimeoutInSeconds": 60}}})` (same page). The equivalent with the SDK 1.24.0 helper is `@custom_code_based_evaluator()` on `def fn(input: EvaluatorInput, context) -> EvaluatorOutput`.

## Still unverified

1. **Code-based evaluator billing.** The pricing page doesn't name it. Assume $1.50 per 1K evaluations plus Lambda cost until AWS says otherwise.
2. **Code-based evaluators in batch jobs.** The API accepts custom evaluator IDs, but there is no documented example. Test with a single-session `start_batch_evaluation`.
3. **Whether batch passes `sessionMetadata.metadata` / `testScenarioId` through to a code-based Lambda.** Only `evaluationReferenceInputs` is documented. If structured labels are needed inside the Lambda, carry them in `assertions[].text` (for example as JSON) and keep LLM evaluators in a separate call or job, so `GoalSuccessRate` doesn't read them.
4. **Whether Gateway and Policy spans share the agent's `traceId` for agent → Gateway MCP calls.** To test: run one session, take the `traceId` of an `execute_tool` span from the runtime log group, then run a Logs Insights query on `aws/spans` with `filter traceId = "<id>" and ispresent(attributes.aws.agentcore.policy.authorization_decision)`. If nothing comes back, join by time window plus `tool.name`/`gateway.id` instead.
5. **A CloudFormation-native Gateway tracing path** (`AWS::Logs::DeliverySource` with `LogType: TRACES` + an `XRAY` `DeliveryDestination`) is untested. The aws-samples stack uses a custom resource.
6. **The built-in judge model identity, and judge quality on Spanish/Portuguese transcripts.** Neither is documented.
7. **`Builtin.ContextRelevance` / `Builtin.Maliciousness`.** Neither is in the docs. Call `ListEvaluators` in us-east-1 to settle it.
8. **Whether the deployed LedgerLens agent uses unified or split telemetry.** It depends on whether it was created before or after 2026-07-20 and on the ADOT version. Check the runtime log group for a `spans` stream.
