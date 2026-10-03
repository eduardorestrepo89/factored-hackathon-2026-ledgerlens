# Agent evaluation and observability: review and limitations (on hold)

**Status:** on hold since 2026-10-03, by team decision. Nothing has been built for this sub-project. This document records:
- what was reviewed;
- what still holds;
- what blocks the work;
- what is needed to resume.

**Context:** this was sub-project 2, after the curate stage (spec `docs/superpowers/specs/2026-10-03-curate-stage-design.md`). Its goal was to evaluate the LedgerLens agent on many labelled cases and explain its behaviour with AWS-native tooling: AgentCore Evaluations, AgentCore Observability and the Gateway's Cedar policy decisions.

**Why it is on hold:** the agent under test does not exist yet in a testable form (section 3). An evaluation harness built now would test the template agent, not LedgerLens.

## 1. What was reviewed

| Source | What it is |
|---|---|
| [`datathon/reports/Agent evaluation signal on AWS.md`](../../reports/Agent%20evaluation%20signal%20on%20AWS.md) | Research report (2026-10-03) on how to build labelled evaluation signal for this dataset and measure the agent on AWS |
| `datathon/research_notes/Agent evaluation signal on AWS/` | The report's four raw note files: `aws_evaluation_stack`, `benchmarks_and_datasets`, `metrics_and_explanation`, `verifiable_test_generation` |
| [`verification_2026-10-03.md`](../../research_notes/Agent%20evaluation%20signal%20on%20AWS/verification_2026-10-03.md) | Check of 13 AWS claims against AWS docs, the boto3 service models and the shipped SDK wheels (`bedrock-agentcore` 1.24.0, `strands-agents-evals` 1.4.0) |
| `docs/AGENTCORE_EVALUATIONS_GUIDE.md`, `docs/OBSERVABILITY.md`, `docs/AGENTCORE_TELEMETRY.md`, `docs/BEDROCK_MODEL_INVOCATION_LOGGING.md` | FAST template guides |
| `docs/LEDGERLENS_PRODUCT_DESIGN.md` §7, §10, §13 | Tool catalog, Cedar sketch and evaluation targets |
| The `stage` branch at `3372213` and the AWS account (us-east-1, profile `ledgerlens`) | What is actually built and deployed |

## 2. Review of the research

### 2.1 What holds (verified)

- **Labels from records plus policy.**
  - Clone a coherent customer, apply one typed mutation (inject a charge, block a card, open a case), and derive the expected outcome as a pure function of the mutated records and a written policy (`POLICY.md`).
  - This is how τ²-bench built its machine-checkable tasks. The dataset's flatness helps: the injected mutation is the only thing that can change the correct outcome.
- **Deterministic checks run as AgentCore code-based evaluators.**
  - **Input:** a Lambda receives `evaluationInput.sessionSpans` and the ground truth in `evaluationReferenceInputs`.
  - **Output:** it returns `{label, value, explanation}`.
  - **Registration:** `bedrock-agentcore-control.create_evaluator(... evaluatorConfig.codeBased.lambdaConfig ...)`, or in CloudFormation with `AWS::BedrockAgentCore::Evaluator`.
  - The same Python module can be imported locally.
- **Tool-call sequence checks make no LLM calls.** `Builtin.TrajectoryExactOrderMatch`, `Builtin.TrajectoryInOrderMatch` and `Builtin.TrajectoryAnyOrderMatch` score programmatically, at zero tokens.
- **Statistics:**
  - **pass^k:** with k = 3, a case passes only if all three runs pass.
  - **Single rates:** Wilson intervals.
  - **Clustered metrics:** a cluster bootstrap at case level.
  - **Zero-event safety claims:** the rule of three, counted over cases, never over runs.
  - **Customers as clusters:** three runs of 320 cases are not 960 independent observations.
- **Failure cards.** One CloudWatch Logs Insights query on `session.id` assembles a failure card from:
  - the agent's spans;
  - the Gateway Policy span, which carries `aws.agentcore.policy.authorization_decision`, `...authorization_reason` and `...determining_policies`.

  A Cedar DENY on a cross-customer call shows that the deterministic layer, not the model, stopped it.
- **LLM judges stay secondary.**
  - Built-in judges use an undisclosed model that cannot be changed, and their Spanish and Portuguese quality is undocumented.
  - Custom LLM judges can use non-Anthropic Bedrock models (the AWS docs use `openai.gpt-oss-120b`).

### 2.2 Corrections to the report

| Report says | Correct fact |
|---|---|
| Trajectory matchers `ExactOrderMatch` / `InOrderMatch` / `AnyOrderMatch` | The IDs are `Builtin.TrajectoryExactOrderMatch` / `Builtin.TrajectoryInOrderMatch` / `Builtin.TrajectoryAnyOrderMatch`. They are session level. |
| The ground-truth `GoalSuccessRate` prompt says "the tool output ALWAYS takes priority" | That line is in the ground-truth-free prompt. The ground-truth prompt accepts "an alternative approach" that reaches the same outcome. So ordering rules and "did NOT call X" rules must be checked in code, not as `assertions`. |
| `strands-agents-evals` v0.1.0 | Version 1.4.0 (2026-09-22). It adds deterministic evaluators (`ToolCalled`, `Equals`, `StateEquals`) and a `chaos` module for tool-failure injection. |
| 13 built-in evaluators | 13 at GA. There are now 18 `Builtin.*` IDs: 13 core, 3 trajectory and 2 skill. |
| `expectedTrajectory` uses the tool names | Gateway tools appear as `<target>___<tool>`, with three underscores. `expectedTrajectory` must use those prefixed names. |
| Spans land in the runtime log group's `spans` stream | Only for agents created on or after 2026-07-20. Older agents need `UNIFIED_TRACES_DESTINATION_ENABLED=true` and ADOT 0.18.0 or later, otherwise spans go to `aws/spans`. Gateway and Policy spans always go to `aws/spans`. |
| `runtimeSessionId` is at least 33 characters | The request accepts 33–256 characters, but the echoed header accepts only 1–100 characters of `[a-zA-Z0-9][a-zA-Z0-9-_]*`. Use 33–100. |
| The batch runner returns only an aggregate | Batch evaluation (GA July 2026) also writes per-session results to CloudWatch Logs. A batch job takes at most 10 evaluators. |
| (docs sample) The code-based evaluator decorator | In SDK 1.24.0 it is `custom_code_based_evaluator()`, with an `(input, context)` signature. |

Unchanged:
- On-demand evaluation takes exactly one evaluator per `Evaluate` call.
- Online evaluation cannot use ground truth.
- Batch evaluation takes ground truth through `evaluationMetadata.sessionMetadata[].groundTruth.inline` and costs about 25% less.
- Pricing matches the report ($0.0396 per built-in evaluation in AWS's example, $0.0297 batch).

Still unverified:
- billing for code-based evaluators;
- whether code-based evaluators run inside batch jobs;
- whether Gateway and Policy spans share the agent's trace ID (the verification note has a Logs Insights test for it);
- a CloudFormation-native switch for Gateway tracing.

### 2.3 Out of date since the curate stage

The report was written before curation, so its population figures are the pre-curation ones: 9,509 usable customers, 16 fraud-flagged and 68 unrecognized-charge customers, tiers A/B of 439 and 1,387, and a pool of about 1.4M rows. What exists now (curated-customers doc [`2026-10-03-curated-customers.md`](2026-10-03-curated-customers.md)):

- **Two groups of customers:**
  - 1,500 coherent customers, balanced at 125 per country × segment cell;
  - a 159-customer defect cohort kept as delivered.

  DSQL holds 270,866 rows in total.
- **The report's "data defect" factor is already built:** the defect cohort carries the 17 classes K01–K17. Examples:
  - K02, an Approved charge after the card's expiry;
  - K07, a code-54 decline on a valid card;
  - K13, a Resolved complaint with no `closing_date`.
- **Seed cases:** the 10 pinned personas P01–P10 each carry a use case, an expected outcome and evidence rows (`data_load/personas.json`).
- **Clone IDs:** the `EVL-` customer-ID prefix is reserved for evaluation clones (curate spec, decision E11).

### 2.4 Too much for the deadline

The report plans for two people over two days. Submission is due 2026-10-05, and the agent is not built. These parts do not fit and would be cut first when resuming:
- a covering array of about 130 scenarios rendered into about 1,500 cases;
- a non-Claude model to write test phrasing;
- 100–150 human labels per judged criterion;
- multiple-comparison corrections (Holm) and an intraclass-correlation variance analysis;
- ablations beyond the baseline.

### 2.5 Citation caveats

- The report itself flags some figures as "as summarised in search results": the NIST combinatorial-testing percentages, the `judgy` correction package, and a 2026 self-preference study.
- Several 2026 arXiv references were not opened during this review: τ-Multilingual 2609.35820, FraudBench 2608.18136, Lost in Simulation 2601.17087 and ReliabilityBench 2601.06112.
- The AWS facts were verified; see section 2.2.

### 2.6 The FAST template guides

`docs/AGENTCORE_EVALUATIONS_GUIDE.md` uses the older `bedrock-agentcore-starter-toolkit` API. It also claims 15 built-ins, including `Maliciousness` and `ContextRelevance`, which AWS does not document, and a 10-evaluator online limit, where the quota is 25. `OBSERVABILITY.md`, `AGENTCORE_TELEMETRY.md` and `BEDROCK_MODEL_INVOCATION_LOGGING.md` describe companion stacks that this repo has not deployed. None of the four is wired into the CDK.

## 3. Limitations: what blocks evaluation today

Checked on 2026-10-03 against `stage` at `3372213` and the AWS account.

| # | Limitation | Evidence | What unblocks it |
|---|---|---|---|
| L1 | **The agent is not deployed.** Only the data stack exists. | `aws cloudformation list-stacks` shows only `ledgerlens-bank-assistant-data` and `CDKToolkit`. | Deploy the backend stack (`python scripts/deploy-with-codebuild.py`; local Docker cannot build the ARM64 images). |
| L2 | **The system prompt is still the FAST template.** It describes a "helpful assistant with access to tools via the Gateway and Code Interpreter", with no banking persona or policy. | `patterns/strands-single-agent/tools/system_prompt.py:10` | A LedgerLens prompt (design doc §9). |
| L3 | **The LedgerLens tools are not on the Gateway.** `list_credit_cards`, `list_card_transactions` and `get_session_context` exist only as standalone Lambdas in the data stack. The Gateway has a single target, `sample-tool-target` (`text_analysis_tool`). So the `customer_id` hook never fires. | `infra-cdk/lib/data-construct.ts:217-219`; `infra-cdk/lib/backend-construct.ts:898-899`; `patterns/strands-single-agent/tools/customer_id_hook.py` | Add the three Lambdas as Gateway targets. |
| L4 | **No per-customer Cedar rule.** The deployed policy permits only the sample tool, by department. The rule `context.input.customer_id == principal.getTag("customer_id")` exists only as a sketch. | `gateway/policies/policy.cedar:41-51`; design doc §10 | Write and deploy the per-customer permit for each LedgerLens tool. Without it there is no Cedar DENY to show. |
| L5 | **No write tools.** `block_credit_card`, `open_claim` and `human_agent_hand_off` are designed only. The secure exit (confirm → block → read back the last 4 digits) and dispute intake cannot be tested, and persona P07's expected outcome cannot be reached. | design doc §7 | Build them, writing to a sandbox table or recording intent, or keep the evaluation to read-only exits. |
| L6 | **No observable exit.** Read-only exits (explain, abstain, hand off as text) leave no record. A grader would have to infer the exit from free text. | report §"Flat records…" | A terminal `disposition` field or a hand-off tool. |
| L7 | **Observability is off.** CloudWatch Transaction Search is not enabled: the trace segment destination is `XRay`, not `CloudWatchLogs`. There are no telemetry rules or deliveries, and Gateway tracing is not enabled. The Runtime sets no `AGENT_OBSERVABILITY_ENABLED` or other `OTEL_*` variable beyond log correlation, although the image runs `opentelemetry-instrument` with `aws-opentelemetry-distro==0.16.0`. AgentCore Evaluations reads spans from CloudWatch, so it has nothing to score. | `aws xray get-trace-segment-destination` → `XRay`, `ACTIVE`; `patterns/strands-single-agent/Dockerfile`; `infra-cdk/lib/backend-construct.ts` Runtime env vars | Enable Transaction Search (one account setting). Deliver Runtime and Gateway traces. Check the unified-spans rule in §2.2, which may need ADOT 0.18.0 or later. |
| L8 | **No test logins mapped to customers.** The pre-token Lambda maps Cognito `sub` → `customer_id` from `USER_CUSTOMER_IDS_MAP`, which holds placeholders only. An automated runner cannot call the agent as a persona. | `infra-cdk/lib/cognito-construct.ts:146` | One Cognito user per persona (and per `EVL-` clone used), with its `sub` in the map. |
| L9 | **The design's evaluation targets rest on signal the data lacks.** Design doc §13 measures fraud detection against `is_fraud` and reason accuracy against `reason_category`. The diagnostics found fraud unlearnable without the leaking `fraud_score` (AUC about 0.48), and reasons uniform. | design doc §13; [`2026-10-02-agent-data-diagnostic.md`](2026-10-02-agent-data-diagnostic.md) | Replace §13 with the record-and-policy metrics in §4 below. |
| L10 | **No evaluation clones exist.** The `EVL-` prefix is reserved, but no pipeline stage writes mutated clones to DSQL, and the tool Lambdas read `public` only. | curate spec E11 | A clone or mutation step, local DuckDB first, then a load into DSQL. |

## 4. When resuming

### 4.1 Prerequisites, in order

1. **Agent:** LedgerLens prompt (L2); tools on the Gateway (L3); the per-customer Cedar rule (L4); persona logins (L8); deploy (L1).
2. **Observability (L7):**
   - enable Transaction Search;
   - deliver Runtime and Gateway traces;
   - confirm that one traced session shows `execute_tool` spans and a Policy span carrying a Cedar decision.
3. **Scope decision on writes (L5, L6).** Three scopes were offered on 2026-10-03:
   - **minimal agent plus evaluation** of read-only exits;
   - **evaluation harness only**, while a teammate builds the agent;
   - **full**, adding sandboxed write tools.

   The team put the work on hold instead of choosing.

### 4.2 The smallest evaluation worth building

Keep these from the report:
- **Policy:** `POLICY.md` as a numbered decision table.
- **Labels:**
  - two independent label functions;
  - a scripted oracle that must score 100%.
- **Cases:**
  - the 10 personas as hand-checked seeds;
  - the defect cohort as the data-defect slice;
  - a handful of mutation ops on `EVL-` clones.
- **Graders:**
  - deterministic graders in one module, deployed as a code-based evaluator;
  - `Builtin.TrajectoryInOrderMatch` on the prefixed tool names.
- **Measurement:**
  - pass^1 and pass^3 with Wilson intervals over cases;
  - failure cards from spans plus the Cedar decision.

Defer everything in section 2.4.

### 4.3 Existing assets to reuse

| Asset | Where |
|---|---|
| Personas with use case, expected outcome and evidence rows | `data_load/personas.json`; [`2026-10-03-curated-customers.md`](2026-10-03-curated-customers.md) |
| Defect cohort classes K01–K17 and their detection SQL | `data_load/curate_select.py` (`CLASSES`) |
| Data defects and readiness probes | [`2026-10-02-agent-data-diagnostic.md`](2026-10-02-agent-data-diagnostic.md); `datathon/analysis/agent_readiness.sql` |
| Invoking the deployed agent (Cognito `USER_PASSWORD_AUTH`, Bearer JWT, `runtimeSessionId`) | `test-scripts/test-agent.py`; `scripts/utils.py` |
| Calling a tool Lambda directly, with the Gateway's tool name in the client context (`client_context.custom.bedrockAgentCoreToolName` = `<target>___<tool>`) | curate spec §13.1 (smoke test) |
| User feedback store (DynamoDB `<stack>-feedback`, `POST /feedback`) | `infra-cdk/lib/backend-construct.ts`; `infra-cdk/lambdas/feedback/` |
| Verified evaluation API facts and code sketches | [`verification_2026-10-03.md`](../../research_notes/Agent%20evaluation%20signal%20on%20AWS/verification_2026-10-03.md) |
