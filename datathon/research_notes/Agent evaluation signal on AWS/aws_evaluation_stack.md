# AWS-native evaluation and explainability stack for a Strands agent on Bedrock AgentCore (as of 2026-10-03)

Scope: what AWS offers to evaluate and explain LedgerLens (Strands + Claude on Bedrock, AgentCore Runtime/Gateway+Cedar ENFORCE/Memory STM, tool Lambdas on Aurora DSQL, us-east-1), with GA/preview status, us-east-1 availability, pricing, limits, API/SDK names, and a 1-day pipeline. Research done 2026-10-03 against docs.aws.amazon.com, aws.amazon.com, strandsagents.com and GitHub.

---

## Q1. Amazon Bedrock AgentCore Evaluations: what it is, status, evaluators, modes, inputs, ground truth, outputs, pricing, quotas, APIs

### Takeaway
AgentCore Evaluations went GA on 2026-03-31 and runs in us-east-1. It scores OpenTelemetry sessions, traces and tool calls from AgentCore Observability with built-in LLM judges, programmatic trajectory matchers, custom LLM judges, Lambda code-based evaluators and managed DeepEval/AutoEval evaluators. It has four ways to run: on-demand (synchronous, one session per call), batch (server-side, many sessions), online (sampled live traffic), and dataset runners with user simulation (dataset evaluation is **public preview**). Ground truth (`expectedResponse`, `assertions`, `expectedTrajectory`) is supported on on-demand, batch and dataset runs but **not online**. This is the strongest AWS-native fit for "large variety of labelled cases plus explanations".

### Cited Findings
**Status, regions**
- GA announced 2026-03-31. At GA it offered "13 built-in evaluators", Ground Truth (reference answers, behavioral assertions, expected tool execution sequences), custom LLM-based evaluators, and code-based evaluators as Lambda functions in Python or JavaScript. It was available in 9 Regions including **US East (N. Virginia)** — [AWS What's New, Mar 31 2026](https://aws.amazon.com/about-aws/whats-new/2026/03/agentcore-evaluations-generally-available/)
- Built-in evaluator inference uses cross-region inference. For the United States geography the inference Regions are us-east-1, us-east-2 and us-west-2 — [AgentCore cross-region inference](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/cross-region-inference.html)
- Dataset evaluation: "Dataset evaluation is in public preview. Features and APIs may change before general availability." — [Dataset evaluation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/dataset-evaluations.html)
- Supported frameworks: Strands and LangGraph, with OpenTelemetry and OpenInference instrumentation. Traces are converted to a unified format and scored with LLM-as-a-Judge. Built-in evaluator ARN: `arn:aws:bedrock-agentcore:::evaluator/Builtin.Helpfulness`. Custom evaluator ARN: `arn:aws:bedrock-agentcore:region:account:evaluator/my-evaluator-id` — [Evaluations overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluations.html)

**Built-in evaluators (authoritative list from the prompt-templates page)**
- Session level: Goal success rate, plus a "Goal success rate with ground truth" variant that reads `{assertions}`. Trace level: Coherence, Conciseness, Correctness (plus a ground-truth variant), Faithfulness, Harmfulness, Helpfulness, Instruction following, Refusal, Response relevance, Stereotyping. Tool level: Tool parameter accuracy, Tool selection accuracy, Skill selection accuracy, Skill instruction following — [Built-in prompt templates](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/prompt-templates-builtin.html)
- The CDK `BuiltinEvaluator` enum lists the same 13 core evaluators: GOAL_SUCCESS_RATE; HELPFULNESS, CORRECTNESS, FAITHFULNESS, HARMFULNESS, STEREOTYPING, REFUSAL, COHERENCE, RESPONSE_RELEVANCE, CONCISENESS, INSTRUCTION_FOLLOWING; TOOL_SELECTION_ACCURACY, TOOL_PARAMETER_ACCURACY — [CDK aws_bedrockagentcore README](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_bedrockagentcore-readme.html)
- Three trajectory evaluators: `Builtin.TrajectoryExactOrderMatch` (same tools, same order, no extras), `Builtin.TrajectoryInOrderMatch` (expected tools in order, extras allowed) and `Builtin.TrajectoryAnyOrderMatch` (all expected present, any order). They use **"Programmatic scoring (no LLM calls)"** and need `expectedTrajectory` — [Ground truth evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ground-truth-evaluations.html)
- An AWS blog also lists `ContextRelevance` among TRACE evaluators, alongside the Trajectory* and Skill* evaluators — [AgentCore + GitHub Actions blog](https://aws.amazon.com/blogs/machine-learning/automated-agent-evaluation-with-amazon-bedrock-agentcore-and-github-actions/). ContextRelevance does **not** appear in the prompt-templates list or the CDK enum. Treat it as unverified.
- Built-in evaluator models and prompt templates "cannot be modified". Built-ins work with on-demand, batch and online evaluation — [Built-in evaluators](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/built-in-evaluators-overview.html)
- Helpfulness scores 0 to 1 across 7 levels — [Production blueprint blog](https://aws.amazon.com/blogs/machine-learning/evaluating-ai-agents-a-production-blueprint-with-strands-and-agentcore/)
- The GoalSuccessRate prompt gives the judge `{available_tools}` and the full `{context}` (user, assistant, Action and Tool lines). It returns Yes/No with reasoning of at most 250 words, and states "The tool output ALWAYS takes priority over your own knowledge." The ground-truth variant judges "only based on whether the agent behavior satisfies the success assertions" and evaluates assertions "by their intent, not by exact text matching" — [Built-in prompt templates](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/prompt-templates-builtin.html)

**Ground truth**
- `EvaluationReferenceInput` has these fields: `context` (required; a span context with sessionId and optional traceId), `expectedResponse` (trace level), `assertions` (session level, a list) and `expectedTrajectory` (session level, a list of tool names) — [boto3 EvaluationReferenceInput](https://docs.aws.amazon.com/sdk-for-python/v1/reference/clients/bedrock-agentcore/structures/EvaluationReferenceInput/)
- Field-to-evaluator mapping: `expectedResponse` feeds Correctness, `assertions` feeds GoalSuccessRate, and `expectedTrajectory` feeds the 3 Trajectory evaluators. The response reports `ignoredReferenceInputFields`. Traces without ground truth fall back to the ground-truth-free variant. Custom evaluators can use placeholders such as `{expected_response}` — [Ground truth evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ground-truth-evaluations.html)
- boto3 shape: `boto3.client("bedrock-agentcore").evaluate(evaluatorId="Builtin.Correctness", evaluationInput={"sessionSpans": spans_and_log_events}, evaluationReferenceInputs=[{"context":{"spanContext":{"sessionId":SID,"traceId":TID}},"expectedResponse":{"text":"..."}}])` returns `evaluationResults[].value/label/explanation` — [Ground truth evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ground-truth-evaluations.html)
- Python SDK: `from bedrock_agentcore.evaluation import EvaluationClient, ReferenceInputs`, then `EvaluationClient(region_name=...).run(evaluator_ids=[...], agent_id=..., session_id=..., reference_inputs=ReferenceInputs(expected_response=..., assertions=[...], ...))`. `expected_response` can be a dict of trace_id to text — [Ground truth evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ground-truth-evaluations.html)
- CLI: `agentcore run eval --runtime NAME | --runtime-arn ARN --region R --session-id SID --evaluator Builtin.GoalSuccessRate --assertion "..." --expected-response "..." [--trace-id T] --output results.json`. "ARN mode" evaluates agents outside the CLI project — [Ground truth evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ground-truth-evaluations.html)
- Each `evaluate()` call must contain spans from a single session, otherwise it raises `ValidationException` — [GitHub Actions blog](https://aws.amazon.com/blogs/machine-learning/automated-agent-evaluation-with-amazon-bedrock-agentcore-and-github-actions/)
- Sessions are detected with a configurable `SessionTimeoutMinutes` (default 15 minutes) — [SpanContext API ref](https://docs.aws.amazon.com/aws-sdk-php/v3/api/api-bedrock-agentcore-2024-02-28.html)

**Evaluation modes**

| Mode | Trigger | Source | Ground truth | Results |
|---|---|---|---|---|
| On-demand | caller, sync, single session | spans inline | `evaluationReferenceInputs` | sync response |
| Online | continuous, sampled | watches a log group | **not supported** | CloudWatch metrics and dashboards |
| Batch | caller, async job | service discovers sessions from CloudWatch Logs (time range, session IDs or log group) | inline `sessionMetadata` | aggregate per-evaluator averages, session counts and token usage, plus per-session detail in CloudWatch Logs (`outputDataConfig`) |

  Sources: [Batch evaluation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/batch-evaluations.html) and [Evaluation types](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluations-types.html).
- Batch API: `boto3.client("bedrock-agentcore").start_batch_evaluation(batchEvaluationName=..., evaluators=[{"evaluatorId":"Builtin.GoalSuccessRate"},...], dataSourceConfig={"cloudWatchLogs":{...}})`. Status goes PENDING → IN_PROGRESS → COMPLETED/FAILED — [Batch getting started](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/batch-evaluations-getting-started.html)
- Batch CLI: `agentcore run batch-evaluation --runtime MyAgent --evaluator Builtin.GoalSuccessRate Builtin.Correctness [--ground-truth ground-truth.json] [--session-ids ...] [--lookback-days N] [--dataset <name> --dataset-version N|DRAFT] [--endpoint NAME] [--evaluator-arn ...] [--kms-key ARN] --wait --json -n run_name`. Results are saved under `.cli/jobs/batch-eval-results/` — [Start batch evaluation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/batch-evaluations-start.html)
- Online config fields: evaluators, a data source (CloudWatch log group plus OTel service name, or a direct Runtime reference), sampling 0.01–100%, and a session timeout. Results go to a dedicated evaluation-results log group and also to **EMF metrics in namespace `Bedrock-AgentCore/Evaluations`**, keyed by evaluator name and config ID, so CloudWatch Alarms can be set on them — [Code-based evaluators blog](https://aws.amazon.com/blogs/machine-learning/build-custom-code-based-evaluators-in-amazon-bedrock-agentcore/)
- Results are visible in CloudWatch under GenAI Observability > Bedrock AgentCore > Agents > (agent/endpoint) > **Evaluations** tab — [Results and output](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/results-and-output.html)

**Dataset runners and simulation (SDK `bedrock-agentcore`, public preview)**
- Two runners: `OnDemandEvaluationDatasetRunner`, which collects spans SDK-side via `AgentSpanCollector` and calls `evaluate()` per evaluator per scenario, returning per-scenario detail; and `BatchEvaluationRunner`, which calls `startBatchEvaluation()` once and returns an aggregate `BatchEvaluationSummary`. Install with `pip install bedrock-agentcore`. Prerequisites are observability and Transaction Search — [Dataset evaluation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/dataset-evaluations.html)
- Predefined scenario JSON: `{"scenarios":[{"scenario_id":..., "turns":[{"input":..., "expected_response":...}], "expected_trajectory":["tool"], "assertions":["..."], "metadata":{...}}]}`. Turn N's `expected_response` maps positionally to trace N. Python classes: `Dataset`, `PredefinedScenario`, `Turn`, `FileDatasetProvider("dataset.json").get_dataset()` — [Dataset schema](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/dataset-evaluations-schema.html)
- Simulated scenario: `actor_profile{context, goal, traits}`, `input`, `max_turns` (default 10), and `assertions`. Simulated scenarios **do not support `expected_trajectory` or per-turn `expected_response`** — [Dataset schema](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/dataset-evaluations-schema.html)
- Simulation loop: the actor returns reasoning, message and a `stop` flag. Config: `SimulationConfig(model_id=...)`, for example `global.anthropic.claude-haiku-4-5-20251001-v1:0`. Actor calls are billed as standard Bedrock invocations. `EvaluationRunConfig(evaluator_config=EvaluatorConfig(evaluator_ids=[...]), evaluation_delay_seconds=180, max_concurrent_scenarios=5, simulation_config=...)`. Span collection uses `CloudWatchAgentSpanCollector(log_group_name="/aws/bedrock-agentcore/runtimes/{RUNTIME_ID}-DEFAULT", region=...)` and the run is started with `runner.run(agent_invoker=..., dataset=..., span_collector=..., config=...)` — [User simulation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/user-simulation.html) and [SDK reference](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-python-sdk-reference.html)
- Managed, versioned datasets use `schemaType` `AGENTCORE_EVALUATION_PREDEFINED_V1` or `AGENTCORE_EVALUATION_SIMULATED_V1`. CLI: `agentcore dataset`, `agentcore evals`, `agentcore batch-evaluations` (CLI `@aws/agentcore` v0.28.1) — [Datasets getting started](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/datasets-getting-started.html) and [CLI reference](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-cli-reference.html)
- AWS's own rationale: agents are non-deterministic, so "a single evaluation result [is] nearly meaningless", and ground truth "turns a subjective score into a verifiable measurement" — [Dataset management blog](https://aws.amazon.com/blogs/machine-learning/build-a-test-suite-that-grows-with-your-agent-with-dataset-management-in-amazon-bedrock-agentcore/)

**Custom, code-based and third-party evaluators**
- Custom LLM judge: `bedrock-agentcore-control` `create_evaluator(evaluatorName, level=SESSION|TRACE|TOOL_CALL, evaluatorConfig={llmAsAJudge:{instructions, ratingScale (numerical or categorical), model ...}})`. CDK: `EvaluatorConfig.llmAsAJudge()` or `EvaluatorConfig.codeBased()`. Names are up to 48 characters `[a-zA-Z0-9_]` and must start with a letter. The example model is `us.anthropic.claude-sonnet-4-6` — [CDK EvaluatorProps](https://docs.aws.amazon.com/cdk/api/v2/dotnet/api/Amazon.CDK.AWS.BedrockAgentCore.EvaluatorProps.html) and [CDK EvaluatorInferenceConfig](https://docs.aws.amazon.com/cdk/api/v2/dotnet/api/Amazon.CDK.AWS.BedrockAgentCore.EvaluatorInferenceConfig.html)
- Code-based (Lambda) evaluators: AgentCore assumes a role and invokes your Lambda with schema version, evaluator ID and name, level, and `evaluationInput` with the session's OTel spans. A trace-level call also gets an evaluation target. The Lambda must return `{"label": "PASS", "value": 1.0, "explanation": "..."}` (label required) or `{"errorCode", "errorMessage"}`. Register one evaluator per level — [Code-based evaluators doc](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-based-evaluators.html) and [blog](https://aws.amazon.com/blogs/machine-learning/build-custom-code-based-evaluators-in-amazon-bedrock-agentcore/)
- AWS recommends code-based evaluators for "exact data validation" (balances, transaction IDs), format compliance and business-rule enforcement: "faster, cheaper, and more reliable" than an LLM judge for deterministic checks — [Build reliable AI agents blog](https://aws.amazon.com/blogs/machine-learning/build-reliable-ai-agents-with-amazon-bedrock-agentcore-evaluations/)
- Third-party evaluators: managed DeepEval and AutoEval evaluators are selected by ID. You can also derive a custom evaluator from a built-in or third-party evaluator to run it on your own model. AWS says "we don't make claims about their quality" — [Third-party evaluators](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/third-party-evaluators.html)

**Pricing (us-east-1 list prices from the AgentCore pricing page)**
- Built-in evaluators: **$0.0024 per 1K input tokens and $0.012 per 1K output tokens**, with model usage included. Custom evaluators: **$1.50 per 1,000 evaluations** plus model usage billed in your account. **Batch evaluations: $0.0018 per 1K input and $0.009 per 1K output** (described as a 25% discount) — [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)
- AWS worked example: 45,000 built-in evaluations at 15,000 input and 300 output tokens each cost $1,782, i.e. about **$0.0396 per evaluation**. A batch example with 3,000 evaluations at the same sizes cost $89.10, about **$0.0297 per evaluation** — [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)
- Other AgentCore prices: Gateway $0.005 per 1K invocations; Policy $0.000025 per authorization request; Runtime v2 consumption $0.1276 per vCPU-hour and $0.0169 per GB-hour. Memory short-term memory (STM) costs **$0.25 per 1,000 new events through 2026-10-05**, then per GB from 2026-10-06: $1.00/GB ingested, $0.20/GB retrieved, $0.10/GB-month. That is the day judging starts — [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)

**Quotas (all "Not adjustable")**
- On-demand built-ins: 1,000,000 input tokens per minute; 1,200 evaluations per minute; **1 evaluator per on-demand evaluation call**; 20,000 spans and 200 MB per on-demand evaluation; 200,000 input tokens per evaluation. Online: 1,000 configs per account and **25 evaluators per online config** — [AgentCore quotas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html). This conflicts with "up to 10 evaluator IDs" in the [code-based evaluators blog](https://aws.amazon.com/blogs/machine-learning/build-custom-code-based-evaluators-in-amazon-bedrock-agentcore/) and with "up to 10" in the local guide. The quota page is newer and authoritative.

**Optimization: explaining behaviour at the population level**
- AgentCore optimization offers Insights (failure, intent and trajectory analysis; **preview, 13 Regions**), Recommendations (system prompt and tool description rewrites; GA) and Experiments (batch evaluations and A/B tests; GA, 14 Regions). It was announced in June 2026 — [What's New, June 2026](https://aws.amazon.com/about-aws/whats-new/2026/06/amazon-bedrock-agentcore-new-optimization-capabilities/)
- Insight types: `Builtin.Insight.FailureAnalysis` (failure patterns grouped by root cause, ranked), `Builtin.Insight.UserIntent` and `Builtin.Insight.ExecutionSummary` — [Insights: how it works](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/insights-how-it-works.html)
- Insights are free during preview. They analyze OTel traces in CloudWatch. Recommendation generation is free — [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)
- Insights produce "one aggregate explanation per cluster", ordered by the proportion of sessions affected — [Silent failures blog](https://aws.amazon.com/blogs/machine-learning/detecting-silent-agent-failures-with-amazon-bedrock-agentcore-optimization/)

### Inferences
- **Mapping to the LedgerLens brief:**
  - `assertions` plus GoalSuccessRate gives per-case pass/fail for "safe automated resolution". Example assertion: "Agent did NOT execute block_card before the user confirmed".
  - `expected_trajectory` plus TrajectoryInOrderMatch/AnyOrderMatch gives deterministic checks for "explain read-only / secure / handoff" paths at zero LLM cost.
  - Correctness plus `expected_response` checks the explanation of the charge.
  - Refusal and Harmfulness cover the prompt-injection and unauthorized subsets.
  - A code-based Lambda (or the same logic run locally over spans) can check for the presence of the hand-off tool and its payload schema, plus "no unsafe action".
- **Escalation quality (missed vs unnecessary transfers) is better computed outside the judges.** Compare the labelled `expected_outcome=handoff` against whether a hand-off `execute_tool` span exists. Trajectory evaluators give only match/no-match per session, not a confusion matrix.
- **Cost of judging the eval set:**
  - Assume 300 held-out scenarios × 3 repeats = 900 sessions, with 4 LLM judges each (GoalSuccessRate, Correctness, ToolSelectionAccuracy, Helpfulness or Refusal) = 3,600 judge calls.
  - On-demand at $0.03–0.04 per call: about **$110–145**. Batch rate: about **$85–110**.
  - Trajectory evaluators are programmatic, but whether they are billed could not be confirmed.
  - With shorter sessions (around 5k input tokens per judge call), cost drops to roughly $0.015 per evaluation, about $55.
- **Rate limits are not a bottleneck** at this size (1,200 evals/min). The binding constraints are the "1 evaluator per on-demand call" rule (it multiplies API calls) and the 2–5 minute ingestion delay (`evaluation_delay_seconds=180`).
- **Online evaluation cannot use ground truth.** For a labelled held-out benchmark, use the on-demand dataset runner (per-scenario detail, needed for per-language and per-segment breakdowns) or batch with `sessionMetadata`. Online is useful only to show live monitoring during judging.
- **Dataset runners are preview.** For a hackathon this is acceptable, but keep a fallback: a plain loop of `invoke_agent_runtime`, wait, then `EvaluationClient.run(..., reference_inputs=...)`.

### Gaps
- Exact JSON key inside `EvaluationExpectedTrajectory` (for example `toolNames`) and the exact `sessionMetadata` shape for batch ground truth were not retrieved. Check the API reference before coding the boto3 path. The SDK classes hide this.
- Whether programmatic Trajectory evaluators and code-based Lambda evaluators are billed as "custom evaluators" ($1.50 per 1K) or free was not found on the pricing page.
- Which judge model the built-ins use is not disclosed. How well built-in judges handle **Spanish and Portuguese** transcripts against English assertions is not documented. No multilingual benchmark was found.
- `Builtin.ContextRelevance` and `Builtin.Maliciousness` (the latter is in the local guide) could not be confirmed in the AWS docs.
- Region list for dataset evaluation (preview) and the Insights preview list (13 Regions) were not individually confirmed to include us-east-1. us-east-1 is the most likely, but this is unverified.

---

## Q2. Strands Agents evaluation tooling (Strands Evals SDK): what exists, test-case spec, trajectory evaluators, simulators, AgentCore integration

### Takeaway
`strands-agents-evals` (v0.1.0, 2025-12-03) is an open-source, code-first harness. It provides `Case` and `Experiment`, about 9–10 LLM-judge evaluators (output, trajectory, tool selection and parameters, goal success, helpfulness, faithfulness, harmfulness, interactions), an `ExperimentGenerator` for synthetic cases and an `ActorSimulator` for multi-turn simulated users. It can pull deployed AgentCore traces from CloudWatch, and the `bedrock-agentcore` SDK wraps AgentCore built-in evaluators as Strands evaluators. Use it for local and CI experiments. Use AgentCore Evaluations as the managed judge.

### Cited Findings
- Evals v0.1.0 was released 2025-12-03 on PyPI as `strands-agents-evals`. Features: output, trajectory, tool-usage and interaction evaluation; LLM-as-a-Judge; trace-based evaluation over OTel; automated experiment generation; experiment save/load/versioning with JSON serialization; "helper functions for exact, in-order, and any-order trajectory matching"; and simulators for multi-turn evaluation — [Strands Evals changelog v0.1.0](https://strandsagents.com/changelog/evals/v0.1.0/index.md)
- Evaluators: `OutputEvaluator` and `TrajectoryEvaluator` (rubric-based), `InteractionsEvaluator` (multi-agent), `HelpfulnessEvaluator` (7-point), `FaithfulnessEvaluator`, `HarmfulnessEvaluator`, `ToolSelectionAccuracyEvaluator`, `ToolParameterAccuracyEvaluator` and `GoalSuccessRateEvaluator`. The blog says "ten" but names 9. The trajectory scorers (exact, in-order, any-order) "are provided as tools to the evaluation LLM, which chooses the most appropriate one" — [Strands Evals practical guide](https://strandsagents.com/blog/evaluating-ai-agents-practical-guide-strands-evals/index.md)
- Test-case spec: `Case(name=..., input=..., expected_output=..., expected_trajectory=["weather_api"], metadata={...})`. Runner: `Experiment(cases=..., evaluators=[...]).run_evaluations(task_fn)` or `await run_evaluations_async(task_fn, max_workers=10)`. Report: `EvaluationReport.flatten(reports).display()`. The task function returns `{"output": ..., "trajectory": session}`. Offline evaluation over stored traces works by mapping traces to sessions — [Strands Evals practical guide](https://strandsagents.com/blog/evaluating-ai-agents-practical-guide-strands-evals/index.md)
- Synthetic cases: `ExperimentGenerator(input_type=str, output_type=str, include_expected_output=True).from_context_async(context=..., task_description=..., num_cases=20, evaluator=OutputEvaluator)` — [Strands Evals practical guide](https://strandsagents.com/blog/evaluating-ai-agents-practical-guide-strands-evals/index.md)
- `ActorSimulator` is the core simulator. An "actor" can be a user, an agent-to-agent representative, or an adversarial tester. It holds a profile and tracks goal completion — [Strands simulators overview](https://strandsagents.com/docs/user-guide/evals-sdk/simulators/index.md)
- `ActorSimulator.from_case_for_user_simulator(case=..., max_turns=10)` generates a persona from `Case.metadata["task_description"]`. A custom `ActorProfile` comes from `strands_evals.types.simulation`. The simulation stops when the actor sets `stop=True` — [Strands Evals practical guide](https://strandsagents.com/blog/evaluating-ai-agents-practical-guide-strands-evals/index.md), [User simulation guide](https://strandsagents.com/docs/user-guide/evals-sdk/simulators/user_simulation/index.md) and [Simulate users blog](https://strandsagents.com/blog/simulate-realistic-users-multi-turn-agents-strands-evals/index.md)
- Spans from an in-memory OTel exporter are mapped with `StrandsInMemorySessionMapper().map_to_session(spans, session_id=...)` so session-level evaluators see the whole multi-turn conversation — [User simulation guide](https://strandsagents.com/docs/user-guide/evals-sdk/simulators/user_simulation/index.md)
- Deployed-agent path: `from strands_evals.providers import CloudWatchProvider; CloudWatchProvider(agent_name="...")` queries CloudWatch and maps ADOT spans into sessions, so no manual conversion is needed — [Framework-agnostic Strands Evals blog](https://strandsagents.com/blog/framework-agnostic-evaluation-strands-evals/index.md)
- `bedrock_agentcore` SDK class `StrandsEvalsAgentCoreEvaluator(evaluator_id, region='us-east-1', test_pass_score=0.7)` "wraps AgentCore Evaluation API as Strands Evaluator" and "automatically converts Strands OTel spans to AgentCore format" — [AgentCore Python SDK reference](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-python-sdk-reference.html)
- Strands' own guidance: use **AgentCore Evaluations** for "managed, continuous evaluation of deployed agents", and use the **Strands Evals SDK** for "local experiments, CI gates, custom evaluators, simulators, and chaos testing" — [Strands: AgentCore evaluation dashboard](https://strandsagents.com/docs/user-guide/evals-sdk/how-to/agentcore_evaluation_dashboard/index.md)
- AWS sample with custom Strands evaluator subclasses (`DataFreshnessEvaluator`, `SafetyGuardrailEvaluator`, `DealerDataScopingEvaluator`, `LatencyEvaluator`, `CostEvaluator`) — [Production blueprint blog](https://aws.amazon.com/blogs/machine-learning/evaluating-ai-agents-a-production-blueprint-with-strands-and-agentcore/) and repo [aws-samples/sample-evaluating-agents-on-aws-with-strands-and-agentcore](https://github.com/aws-samples/sample-evaluating-agents-on-aws-with-strands-and-agentcore)
  - The repo README describes a 3-layer gate: tool correctness >95%, reasoning >85%, output >90%.
  - Test cases live in YAML with `input`, `expected_tools`, `expected_output` and `metadata`.
  - `run_all_layers()` reports `pass_at_k`.
  - Includes a latency P50/P99 evaluator and a Guardrails-based safety evaluator.

### Inferences
- **Tenant-scoping analogue.** The sample's `DealerDataScopingEvaluator` pattern maps directly to LedgerLens's "unauthorized access" check: assert every tool call's `customer_id` equals the session principal.
- **Adversarial simulation.** `ActorSimulator` with an adversarial profile can generate multi-turn prompt-injection and social-engineering attempts in Spanish or Portuguese. However, multi-turn simulated sessions lose `expected_trajectory` ground truth in AgentCore's runner, so pair them with assertions only.
- **Which simulator to pick.** Strands Evals and AgentCore dataset runners overlap: both have actor simulation and trajectory scoring. The AgentCore runner is closer to the "AWS-native" story, and its results land in CloudWatch. Strands Evals is better for fully local iteration without waiting 2–5 minutes for ingestion.

### Gaps
- The full Strands `Case` field list (for example `expected_interactions`) and the default judge model of Strands evaluators were not retrieved.
- The "chaos testing" feature (useful for "tool failures") was mentioned but no API detail was retrieved. Check the strandsagents.com evals docs.
- The latest Strands Evals version after v0.1.0 was not checked.

---

## Q3. Amazon Bedrock Evaluations (model and RAG eval jobs, LLM-as-judge, custom metrics, BYOI): can it score agent transcripts produced elsewhere?

### Takeaway
Yes, but only as prompt→response pairs. Bring-your-own-inference (BYOI) jobs take a JSONL of `prompt`, optional `referenceResponse` and `category`, and one `modelResponses` entry. They score it with built-in or custom LLM-judge metrics. There is no notion of tool trajectory or session, so for LedgerLens it is strictly weaker than AgentCore Evaluations. It is only useful for a quick "final answer quality by category" side metric.

### Cited Findings
- BYOI dataset keys: `prompt`, `referenceResponse` (optional; used by `Builtin.Completeness` and `Builtin.Correctness`), `category` (optional; scores reported per category), and `modelResponses: [{response, modelIdentifier}]`. Only one response per prompt and one unique `modelIdentifier` per job are allowed for LLM-as-judge — [Bedrock: prompt datasets for model-as-judge](https://docs.aws.amazon.com/bedrock/latest/userguide/model-evaluation-prompt-datasets-judge.html)
- BYOI "can evaluate the final response of a full application if you choose to bring that into your dataset". Human evaluation allows up to 2 model responses — [Bedrock Evaluations GA blog](https://aws.amazon.com/blogs/machine-learning/evaluate-models-or-rag-systems-using-amazon-bedrock-evaluations-now-generally-available/)
- Custom metrics: you can pick a different evaluator model for custom metrics. Template variables are `{{prompt}}`, `{{prediction}}` (mandatory) and `{{ground_truth}}`. The console flow is "Automatic: Model as a judge" → "Bring your own inference responses" — [Custom metrics job](https://docs.aws.amazon.com/bedrock/latest/userguide/model-evaluation-custom-metrics-create-job.html) and [Custom metrics blog](https://aws.amazon.com/blogs/machine-learning/use-custom-metrics-to-evaluate-your-generative-ai-application-with-amazon-bedrock/)
- Cost: judge tokens are "charged based on the on-demand standard tier prices". Human evaluation is $0.21 per completed human task — [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)
- Model-evaluation custom datasets allow up to 1,000 prompts per automatic evaluation job (stated in the SageMaker Unified Studio variant of the docs) — [SMUS custom prompt dataset](https://docs.aws.amazon.com/sagemaker-unified-studio/latest/userguide/model-evaluation-prompt-datasets-custom.html)

### Inferences
- **How to use it if at all.** The team could flatten each case to `prompt = user turns + tool outputs` and `response = final agent message`, with `category = "es|pt × scenario type"`. This gives free per-category roll-ups in the job report. However, it duplicates what AgentCore's Correctness and GoalSuccessRate already do with trajectory context, and adds S3/IAM setup.
- **Recommendation: skip it** for a 1-day build unless judges specifically value "Bedrock Evaluations" branding.

### Gaps
- The current list of supported judge models for Bedrock model-evaluation jobs (for example whether Claude Sonnet 4.5/4.6 is included) was not retrieved.
- Job duration and S3 output schema details were not retrieved.
- The 1,000-prompt cap was found on the SMUS page and was not confirmed for the Bedrock console path.

---

## Q4. AgentCore Observability / CloudWatch GenAI Observability / X-Ray / OTel GenAI conventions: spans captured, reconstructing trajectories, Transaction Search, cost

### Takeaway
On AgentCore Runtime, Strands emits OTel GenAI spans via ADOT with `session.id` injected. There are three span types, `invoke_agent`, `execute_tool` and `chat`, carrying model, token, tool-name, tool-status and tool-call-id attributes, with prompts, responses and tool I/O in events. With Gateway traces enabled, Policy in AgentCore adds a span per authorization carrying the **Cedar decision, the determining policy IDs, the reason, and guardrail scores**. A session's full trajectory, per-turn latency, tokens and policy denials can be reconstructed with CloudWatch Logs Insights over the agent's `spans` stream. That makes it an explanation source as well as the evaluator input.

### Cited Findings
- Strands Python spans have scope `strands.telemetry.tracer` and no extra instrumentation library is needed. On AgentCore Runtime with ADOT, "the Runtime injects the `session.id` attribute and exports spans and event records automatically" — [Strands telemetry for Evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks-strands.html)
- Span classification uses `gen_ai.operation.name`: `invoke_agent` (name "invoke_agent <AgentName>"), `execute_tool` ("execute_tool <tool>") and `chat` (inference). Example attributes:
  - Invoke-agent spans: `gen_ai.request.model`, `gen_ai.usage.input_tokens/output_tokens/total_tokens`, `gen_ai.agent.tools`, `gen_ai.agent.name`, `session.id`, `startTimeUnixNano/endTimeUnixNano/durationNano`, `status.code`.
  - Tool spans: `gen_ai.tool.name`, `gen_ai.tool.call.id`, `gen_ai.tool.status` ("success"), `gen_ai.tool.description`.

  — [Strands telemetry for Evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks-strands.html)
- Content location by mode. **Split telemetry**: an event record correlated by spanId holds `body.input.messages` (user, or tool args) and `body.output.messages` (assistant, or tool result). **Unified telemetry**: inline events `gen_ai.user.message` (content), `gen_ai.choice` (message, finish_reason) and `gen_ai.tool.message` (tool args) — [Strands telemetry for Evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks-strands.html)
- Unified telemetry is **recommended**. On Runtime, spans go to the `spans` log stream of `/aws/bedrock-agentcore/runtimes/<agent_id>-<endpoint_name>`, next to the agent's logs — [Telemetry setup and delivery](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks-telemetry.html)
- Log locations: OTEL structured logs are at `/aws/bedrock-agentcore/runtimes/<agent_id>-<endpoint_name>/runtime-logs`. Traces are in the `spans` stream of the agent log group, or the `default` stream of `aws/spans` for the shared destination. Metrics are in namespace `bedrock-agentcore` — [Observability get started](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-get-started.html)
- The CloudWatch GenAI Observability > Bedrock AgentCore console has Agents View (runtime metrics, sessions, traces, evaluations per agent), Sessions View and Traces View (trajectory and timeline) — [CloudWatch: view observability data](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/view-observability-data-cloudwatch.html)
- Transaction Search is account-wide. It "switches all spans ingestion through X-Ray into cost effective collection mode" and indexes 1% of spans as trace summaries for free — [Enable Transaction Search](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Enable-TransactionSearch.html)
- Transaction Search ingests 100% of spans as structured logs, supports traces up to 10,000 spans, allows search on all span attributes, and supports metric filters and data masking. X-Ray spans are converted to semantic-convention format in `aws/spans` — [Transaction Search](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Transaction-Search.html)
- Span pricing: $0.35 to $0.15 per GB (tiered, usage type `Application-Signals-Bytes`). Indexed spans beyond the free 1% are billed per million — [CloudWatch pricing FAQ](https://aws.amazon.com/cloudwatch/omni/pricing/)
- AWS example: 10 GB of spans × $0.35 = $3.50, plus 6 GB of event logs × $0.50 = $3.00, for 200K invocations per month. "Most development environment observability data volumes are low enough that observability costs are near zero" — [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)
- **Policy (Cedar) observability.** Default metrics in `AWS/Bedrock-AgentCore` include `AllowDecisions`, `DenyDecisions`, `NoDeterminingPolicies`, `MismatchErrors`, `GuardrailLatency`, `ConfidenceScore`, `SuppressOutputs` and `LogOnlyDecisionFlips`. Dimensions include `ToolName`, `Policy`, `Mode` (LOG_ONLY/ENFORCE) and `Category`/`Filter` (for example `PROMPT_INJECTION`) — [Policy observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-policy-metrics.html)
- **Policy span attributes**, available "after enabling traces for your AgentCore Gateway resource", in `aws/spans`:
  - AuthorizeAction spans: `aws.agentcore.policy.authorization_decision` (ALLOW/DENY), `.authorization_reason`, `.determining_policies`, `.mismatched_policies`, `.effects` (PERMIT/FORBID/SuppressOutput), `.types` (Cedar/Guardrail), `.guardrails.<contentFilter|promptAttack|sensitiveInformation>.scores`, `aws.agentcore.gateway.policy.mode`.
  - PartiallyAuthorizeActions spans: `aws.agentcore.policy.allowed_tools` and `.denied_tools`.

  — [Policy observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-policy-metrics.html)
- Debugging guidance for Policy: enable Gateway CloudWatch Logs, review X-Ray traces, and start in LOG_ONLY mode — [Policy IAM permissions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-permissions.html)

### Inferences
- **Per-session "explanation record".** Use one Logs Insights query over the runtime log group's `spans` stream, filtered by `attributes.session.id`. It yields:
  - an ordered tool trajectory (`execute_tool` spans sorted by start time) with args and results;
  - the model and token counts per turn (`invoke_agent`);
  - latency per turn (`durationNano` of `invoke_agent`);
  - failed tools (`gen_ai.tool.status` / `status.code`).

  Joining with Gateway Policy spans adds *why* a tool was blocked (`determining_policies`, `authorization_reason`). Combined with the judge's `explanation` string, this is a strong, citable "explain the behaviour" artefact per case.
- **Cost per case** = Σ(`gen_ai.usage.*` × Bedrock Claude price) + Gateway invocations × $0.005/1K + Policy authorizations × $0.000025 + Runtime vCPU/GB-seconds + Lambda/DSQL. Model tokens will dominate.
- **Stratification needs a join key.** Language, segment, case ID and run index are not in spans unless they are encoded. The simplest route is to encode them in `runtimeSessionId`, which becomes `session.id`. An alternative is Strands `trace_attributes` (an AWS blog example passes `session.id`/`user.id` through `trace_attributes`: [Arize + Strands blog](https://aws.amazon.com/blogs/machine-learning/observing-and-evaluating-ai-agentic-workflows-with-strands-agents-sdk-and-arize-ax/)).
- **Cedar evidence for "unauthorized access" cases.** A DENY from `determining_policies` on a cross-customer tool call is direct evidence that the safety outcome came from the deterministic layer, not the LLM. The Gateway Policy span is therefore the key explanation signal for those cases.

### Gaps
- Whether Gateway spans and Strands agent spans share a traceId (W3C context propagation through Gateway's MCP call), so they can be joined by trace rather than by time and session, was not confirmed.
- Exact Logs Insights field names in the unified `spans` stream (for example `attributes.session.id` vs `attributes.'session.id'`) were not tested.
- Whether AgentCore Memory spans appear and what they carry was not checked.
- Minimum length and format of `runtimeSessionId` (believed to be ≥33 characters) were not verified in this pass.

---

## Q5. Other AWS pieces: Guardrails, batch inference, prompt management/flows, FMEval, sample repos

### Takeaway
Bedrock Guardrails can be evaluated offline with `ApplyGuardrail` (`outputScope=FULL`) on a labelled injection set. Standard tier is needed for Portuguese prompt-attack and content-filter support. Guardrails can also be attached as policies in AgentCore Policy, in which case their scores appear in Policy spans. Batch inference is 50% cheaper but asynchronous, has a minimum of about 100 records per job, and has no tool calling. It fits bulk paraphrase generation only if time allows. FMEval is a model-level library and not agent-aware. The best sample repos are aws-samples' Strands+AgentCore evaluation repo and the AgentCore GitHub Actions CI sample.

### Cited Findings
**Guardrails**
- Classic tier supports only English, French and Spanish. Standard tier supports "more than 60 languages", "enhanced prompt attack protection" (jailbreaks, prompt injection, token smuggling, AutoDAN, many-shot) and requires cross-Region inference (CRIS) with "a modest increase in latency" — [Safeguard tiers blog](https://aws.amazon.com/blogs/machine-learning/tailor-responsible-ai-with-new-safeguard-tiers-in-amazon-bedrock-guardrails/) and [Guardrails tiers doc](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-tiers.html)
- In Standard tier, Portuguese is "Optimized and supported" for content filters **and prompt attacks**. Spanish is presumably in the same table but was truncated in retrieval — [Guardrails supported languages](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-supported-languages.html)
- `ApplyGuardrail` works independently of the model. `outputScope: FULL` returns non-detected entries too, "for enhanced debugging". Contextual grounding counts as detected when the grounding or relevance score falls below its threshold — [ApplyGuardrail API](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-independent-api.html)
- Contextual grounding uses content `qualifiers`: `grounding_source`, `query` and `guard_content`, and is applied only to output — [Model-independent guardrails blog](https://aws.amazon.com/blogs/machine-learning/implement-model-independent-safety-measures-with-amazon-bedrock-guardrails/)
- ApplyGuardrail's default limit is 25 text units per second (a text unit is 1,000 characters) — [Long-context ApplyGuardrail blog](https://aws.amazon.com/blogs/machine-learning/use-the-applyguardrail-api-with-long-context-inputs-and-streaming-outputs-in-amazon-bedrock/)
- Prices per 1,000 text units: content filters $0.15, denied topics $0.15, sensitive information $0.10, contextual grounding $0.10, Automated Reasoning $0.17 per policy. No price difference between Standard and Classic tiers. The fetched page also listed an "InvokeGuardrailChecks API" at $0.07 (content) and $0.08 (prompt attack) per 1K units; I did not verify this independently — [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)
- Content filters count as 1 text unit per 1,000 characters regardless of how many categories (including Prompt Attack) are enabled — [Guardrails code-gen best practices](https://aws.amazon.com/blogs/machine-learning/best-practices-for-applying-amazon-bedrock-guardrails-to-code-generation-workflows/)
- Inside AgentCore Policy, "If you use guardrails through policy, you are charged based on the usage of each safeguard" — [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/). Guardrail findings surface as `aws.agentcore.policy.guardrails.promptAttack.scores` in Policy spans — [Policy observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-policy-metrics.html)

**Batch inference**
- Batch inference is asynchronous, uses S3 JSONL with `recordId` and `modelInput` in InvokeModel or Converse format, and is started with `bedrock.create_model_invocation_job(roleArn, modelId, jobName, inputDataConfig={"s3InputDataConfig":{"s3Uri":...}}, outputDataConfig=...)`. It "does not support tool calling... or structured output" — [Batch inference](https://docs.aws.amazon.com/bedrock/latest/userguide/batch-inference.html) and [Batch code example](https://docs.aws.amazon.com/bedrock/latest/userguide/batch-inference-example.html)
- Price is "50% lower" than on-demand for select models — [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)
- The minimum records per job is a per-model quota. One blog states "a minimum number of records of 100" — [Batch code example](https://docs.aws.amazon.com/bedrock/latest/userguide/batch-inference-example.html) and [AWS ML blog](https://aws.amazon.com/blogs/machine-learning/extract-data-with-on-demand-and-batch-pipelines-dynamically/)

**FMEval / Clarify**
- `pip install fmeval` is the engine behind Clarify's FM evaluation. It covers summarization, QA, classification, open-ended generation, factual knowledge, toxicity, robustness (semantic perturbations) and prompt stereotyping. The page is titled "Clarify availability change", suggesting Clarify-hosted FM evaluation availability changed — [SageMaker: Clarify availability change](https://docs.aws.amazon.com/sagemaker/latest/dg/clarify-availability-change.html)

**Sample repos and older frameworks**
- [aws-samples/sample-evaluating-agents-on-aws-with-strands-and-agentcore](https://github.com/aws-samples/sample-evaluating-agents-on-aws-with-strands-and-agentcore): Strands Evals subclasses, 3-layer gates, pass@k, latency/cost/safety evaluators, and AgentCore online evaluation to CloudWatch (see Q2).
- The AgentCore + GitHub Actions CI quality-gate sample uses `Evaluation(region).run(..., evaluators=["Builtin.GoalSuccessRate","Builtin.Correctness","Builtin.ToolSelectionAccuracy","Builtin.ToolParameterAccuracy"])` with an `EVAL_THRESHOLD` of 0.8. It includes `scripts/evaluate_stored_traces.py` for evaluating stored span fixtures without live invocation ("Approach A") — [GitHub Actions blog](https://aws.amazon.com/blogs/machine-learning/automated-agent-evaluation-with-amazon-bedrock-agentcore-and-github-actions/)
- Other evaluation samples:
  - [sample-amazon-bedrock-agentcore-onboarding/05_evaluation](https://github.com/aws-samples/sample-amazon-bedrock-agentcore-onboarding/blob/main/05_evaluation/README.md)
  - The AgentCore Evaluations tutorials referenced by the docs' sample calculator/weather agent: [Ground truth evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ground-truth-evaluations.html) and [awslabs/amazon-bedrock-agentcore-samples](https://github.com/awslabs/amazon-bedrock-agentcore-samples)
  - An AWS DevOps Agent plus Evaluations dashboard built on FAST, which uses the same AgentCore Evaluations Guide as the local template — [DevOps Agent blog](https://aws.amazon.com/blogs/machine-learning/monitoring-production-agent-lifecycle-with-aws-devops-agent-and-agentcore-evaluations/)
- [awslabs/agent-evaluation](https://github.com/awslabs/agent-evaluation) is an LLM evaluator agent that "orchestrate[s] conversations with your own agent (target) and evaluate[s] the responses". Targets: Bedrock, Q Business, SageMaker, or bring-your-own. It is not marked archived and has no AgentCore mention — [GitHub](https://github.com/awslabs/agent-evaluation)

### Inferences
- **Injection metrics per language.** Run the labelled injection and benign set (es and pt) through `ApplyGuardrail` with `source=INPUT` and `outputScope=FULL`. Record detections per filter and compute TPR/FPR per language. This is cheap: 1,000 prompts of 1 text unit each cost about $0.15 with content filters only. Use Standard tier, because Classic does not cover Portuguese.
- **Using Guardrails as a policy.** If Guardrails is attached as a Policy guardrail at the Gateway, its effect is logged per tool call in Policy spans. That gives "blocked by guardrail" vs "blocked by Cedar" attribution for free.
- **Paraphrase generation.** For a few hundred paraphrases, plain on-demand Converse calls to Claude Haiku from a script finish in minutes and avoid the S3/IAM/job-queue overhead of batch inference. Batch is only worth it for thousands of utterances and when results can wait. Turnaround time was not verified.
- **Not needed in 1 day:** FMEval, awslabs/agent-evaluation and Bedrock Prompt Management/Flows. Agent-evaluation duplicates the actor simulator, and FMEval is not trajectory-aware.

### Gaps
- Bedrock Prompt Management and Bedrock Flows were not researched. They are not evaluation tools and are unlikely to matter here.
- Guardrails per-language detection quality for Spanish/Portuguese prompt attacks (published accuracy numbers) was not found.
- Batch inference job turnaround SLA and the exact minimum-records quota for Claude Haiku 4.5 in us-east-1 were not retrieved.
- Bedrock Claude on-demand prices for Haiku 4.5 and Sonnet 4.5/4.6 were not extracted from the pricing page (the fetch only returned older models). Get them from the pricing page or the AWS Pricing API before computing cost per case.

---

## Q6. Local template docs (FAST): what they already wire up, and whether their claims hold against current AWS docs

### Takeaway
The template documents (rather than deploys) three things: (a) an evaluations guide based on the **older `bedrock-agentcore-starter-toolkit`** API, (b) a CloudFormation telemetry-enablement stack for Runtime, Gateway and Memory logs and traces, and (c) Bedrock model invocation logging. Most claims hold. The guide is out of date on the evaluator list, the per-config limit and the tooling. It also omits everything that matters most for labelled held-out evaluation: ground truth, batch, dataset runners, simulation, code-based evaluators and trajectory matchers.

### Cited Findings
- `docs/OBSERVABILITY.md` and `docs/AGENTCORE_TELEMETRY.md`:
  - FAST does **not** turn on account-level telemetry.
  - Transaction Search plus telemetry resource discovery are prerequisites, and the companion stack [aws-samples/sample-telemetry-enablement-for-agentcore-cloudformation](https://github.com/aws-samples/sample-telemetry-enablement-for-agentcore-cloudformation) creates telemetry rules (Runtime via `AWS::ObservabilityAdmin::TelemetryRule`; Gateway, Memory and WorkloadIdentity via an inline Lambda custom resource).
  - The Transaction Search prerequisite is **consistent** with AWS docs, which list "AgentCore Observability, including Transaction Search" as a prerequisite for evaluations — [Ground truth evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ground-truth-evaluations.html) and [Dataset evaluation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/dataset-evaluations.html)
- The telemetry doc says traces go "to X-Ray, ingested into the CloudWatch Logs group `aws/spans`". Current AWS docs recommend **unified telemetry**, where Runtime spans go to the `spans` stream of `/aws/bedrock-agentcore/runtimes/<agent_id>-<endpoint>`; `aws/spans` is the "shared span destination" alternative — [Telemetry setup and delivery](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks-telemetry.html) and [Observability get started](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-get-started.html). Both locations exist; check which one the deployed agent uses before writing queries.
- Enabling **Gateway traces** (which the telemetry stack does) is exactly what unlocks Policy/Cedar decision spans — [Policy observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-policy-metrics.html)
- `docs/AGENTCORE_EVALUATIONS_GUIDE.md` claims checked:
  - **"15 built-in evaluators"**, including `Builtin.Maliciousness` and `Builtin.ContextRelevance`. AWS docs list 13 core evaluators plus 3 trajectory and 2 skill evaluators; Maliciousness was not found — [Prompt templates](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/prompt-templates-builtin.html) and [GA post](https://aws.amazon.com/about-aws/whats-new/2026/03/agentcore-evaluations-generally-available/)
  - **"Each online evaluation config supports up to 10 evaluators"**. The quota page says 25 — [Quotas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html)
  - **Tooling**. The guide uses `from bedrock_agentcore_starter_toolkit import Evaluation, Observability`. Current docs lead with `bedrock_agentcore.evaluation.EvaluationClient` (pip `bedrock-agentcore`) and the npm CLI `@aws/agentcore`. The starter toolkit still appears as a secondary tab — [Ground truth evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ground-truth-evaluations.html)
  - **Windows warning**. Having `bedrock-agentcore-starter-toolkit` installed makes an older Python `agentcore` shadow the npm CLI ("most common on Windows"). The fix is `pip uninstall bedrock-agentcore-starter-toolkit` — [CLI get started](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html)
  - **Online results.** The guide puts them in log group `/aws/bedrock-agentcore/evaluations/results/{config-id}` with `gen_ai.evaluation.*` attributes. AWS confirms a "dedicated evaluation-results CloudWatch log group" plus EMF metrics in `Bedrock-AgentCore/Evaluations` — [Code-based evaluators blog](https://aws.amazon.com/blogs/machine-learning/build-custom-code-based-evaluators-in-amazon-bedrock-agentcore/). The exact path was not independently verified.
  - **Timings** (2–5 minutes to ingest) match AWS ("wait 2–5 minutes for CloudWatch to ingest") — [Ground truth evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ground-truth-evaluations.html)
  - **Token size.** The guide's "~1,000 tokens per evaluation" is much lower than AWS's pricing example (15,000 input tokens per evaluation) — [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/). Actual size depends on session length.
  - **Custom evaluator placeholders** `{context}`, `{assistant_turn}`, `{tool_turn}` and `{available_tools}` match AWS — [Prompt templates](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/prompt-templates-builtin.html)

### Inferences
- **Treat the local guide as a starting point only.**
  - Use its IAM policy (add the `bedrock-agentcore:StartBatchEvaluation`/`GetBatchEvaluation` and dataset actions as needed).
  - Use its CloudWatch-results download code (online only).
  - Use its pattern-analysis prompt idea (now partly replaced by Insights FailureAnalysis).
- **Rewrite the evaluation core around the `bedrock-agentcore` SDK:** `EvaluationClient` with `ReferenceInputs`, `OnDemandEvaluationDatasetRunner`, and the Trajectory* evaluators.
- **Confirm telemetry is live before building anything.** The repo has only documentation for the telemetry and logging stacks; I found no evidence in these docs that the stacks were deployed. Verify that Transaction Search is ON in us-east-1 and that a test session shows `execute_tool` spans and Gateway Policy spans.

### Gaps
- I did not inspect the repo's CDK/infra code to confirm whether the telemetry stack, Transaction Search or an online evaluation config are actually deployed for LedgerLens. The caller should verify this (for example with `aws xray get-trace-segment-destination` and `aws observabilityadmin list-telemetry-rules`).

---

## Q7. Recommended minimal AWS-native pipeline a 2-person team can stand up in about 1 day (synthesis of the objective)

### Takeaway
Use **AgentCore Evaluations ground-truth scoring (on-demand dataset runner) over AgentCore Observability traces**, plus a small span-mining script for deterministic metrics (containment, escalation confusion matrix, unsafe outcomes, latency, cost) and explanations (trajectory + Cedar decision + judge reasoning). Online evaluation and Insights are optional extras for the demo.

### Cited Findings
- All API, field, price and quota facts used below are cited in Q1–Q6. Key ones:
  - dataset schema (`scenario_id`, `turns[].input/expected_response`, `expected_trajectory`, `assertions`, `metadata`) — [Dataset schema](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/dataset-evaluations-schema.html)
  - runner configuration — [User simulation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/user-simulation.html)
  - Policy span attributes — [Policy observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-policy-metrics.html)
  - Strands span attributes — [Strands telemetry](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks-strands.html)
  - prices — [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)
  - quotas — [Quotas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html)

### Inferences
**Morning: plumbing (both people, about 1.5 h)**
1. In us-east-1, confirm Transaction Search is enabled, the telemetry rules exist for Runtime and Gateway, and the agent uses unified telemetry.
2. Invoke one session and confirm three things in the agent log group's `spans` stream: `invoke_agent` and `execute_tool` spans carrying `session.id`, the Gateway `AuthorizeAction` spans with `aws.agentcore.policy.authorization_decision`, and token usage attributes.
3. `pip install bedrock-agentcore strands-agents-evals`. On Windows, uninstall the starter toolkit and use `npm i -g @aws/agentcore` only if the CLI is needed.

**Person A: labelled dataset (about 3–4 h)**
1. Write about 60–100 seed cases. Each case has:
   - `metadata = {case_id, language: es|pt, segment, category ∈ {happy_path, incorrect_data, missing_data, expired_session, unauthorized, prompt_injection, tool_failure, ambiguity}, expected_outcome ∈ {explain, secure, handoff, refuse, clarify}, split: dev|heldout}`;
   - `turns[].input` (multi-turn where the UI confirmation and read-back matter);
   - `expected_response` only where the answer is deterministic, for example the merchant and amount of the charge;
   - `expected_trajectory` using the **exact Gateway tool names** as they appear in `gen_ai.tool.name`;
   - 2–4 `assertions`, for example "Agent did not call block_card before the user explicitly confirmed", "Agent read back the last 4 digits", "Agent created a structured hand-off with dispute reason and amount", "Agent never revealed data of another customer".
2. Expand to about 300–600 cases with Claude Haiku paraphrases in es and pt (regional variants, typos, code-switching), using on-demand Converse.
3. Add 10–20 `SimulatedScenario`s with an `actor_profile` (for example a confused elderly customer, or an adversarial "ignore previous instructions" persona) for multi-turn ambiguity and injection. These carry assertions only.
4. Mark tool-failure cases so the harness can inject faults, for example a test flag that makes a Lambda return an error or timeout. Keep "expired session" cases on distinct session IDs.

**Person B: runner and metrics (about 4 h)**
1. Build an `agent_invoker` that calls `bedrock-agentcore` `invoke_agent_runtime` with `runtimeSessionId = f"{case_id}-{lang}-{segment}-r{k}-{uuid}"`, so labels survive in `session.id`. Record client-side wall time.
2. Run `OnDemandEvaluationDatasetRunner` with `EvaluatorConfig(evaluator_ids=["Builtin.GoalSuccessRate","Builtin.Correctness","Builtin.TrajectoryInOrderMatch","Builtin.ToolSelectionAccuracy","Builtin.Refusal"])`, `evaluation_delay_seconds=180` and `max_concurrent_scenarios` of about 5–10. Run k=3 repeats on the held-out split.
3. Fallback if the preview runner misbehaves: loop over invoke, wait 3 minutes, then `EvaluationClient.run(..., reference_inputs=ReferenceInputs(...))` per evaluator.
4. Write a span-mining script (CloudWatch Logs Insights or `filter_log_events` on the `spans` stream, grouped by `session.id`) that computes per session:
   - actual trajectory;
   - hand-off called (yes/no);
   - card block executed, and whether it was after a confirmation turn;
   - Policy DENY count and `determining_policies`;
   - tool errors;
   - `invoke_agent` durations;
   - token totals.
5. Join with the labels and compute:
   - **safe automated resolution**: expected_outcome ∈ {explain, secure}, GoalSuccess=Yes and no unsafe flag;
   - **containment**: no hand-off when none was expected;
   - **missed / unnecessary transfers**: a 2×2 matrix of expected vs actual hand-off;
   - **unsafe-outcome rate**: unsafe flags over the cases where unsafety was possible, with explicit denominators;
   - **p50/p95 latency**: per turn and per case;
   - **cost per case**: tokens × Bedrock price, plus Gateway, Policy and Runtime;
   - all metrics broken down by language and segment, with mean ± standard deviation and min/max across the k runs.

**Explainability deliverable (about 1 h)**
1. For every failed case, emit a card with the input, the actual vs expected trajectory, the judge `explanation` strings from GoalSuccessRate and Correctness, and the Cedar decision and reason. This works as a static HTML or markdown report.
2. Optionally run Insights `Builtin.Insight.FailureAnalysis` (preview, free) over the held-out sessions to get clustered root causes.

**Optional live demo (about 30 min)**
- Create an online evaluation config at 100% sampling for the judging window with GoalSuccessRate + Helpfulness + Refusal. Scores then appear in the CloudWatch GenAI Observability > Evaluations tab, and EMF metrics with alarms can be added.

**Budget estimate**
- 500 cases × 3 runs = 1,500 sessions.
- Judges: about 4 LLM calls per session ≈ 6,000 judge calls at $0.015–0.04 each ≈ **$90–240**. Trajectory matchers are programmatic.
- Agent inference is extra (Claude tokens), plus negligible Gateway, Policy and observability charges.
- Shrink the held-out set or the number of judges if cost is a concern.

**Pitch to judges**
- "Every metric is computed from AWS-native OTel traces. Every safety block is attributable to a Cedar policy ID. Every quality score comes with a judge explanation and a ground-truth reference."

### Gaps
- The pipeline's timing assumptions (runner concurrency vs Runtime session quotas, Bedrock TPM for Claude in the account) are untested.
- The SDK's `agent_invoker` input/output contract (`AgentInvokerInput`/`AgentInvokerOutput` fields) was not retrieved. Check the SDK reference.
- Judge reliability on es/pt is unvalidated. Run a small human spot-check, for example 30 cases, to report judge agreement.
