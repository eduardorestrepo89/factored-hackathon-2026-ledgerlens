# Agent evaluation and observability: review and limitations

**Status:** resumed on 2026-10-04, after being on hold since 2026-10-03 by team decision. No evaluation harness has been built yet. The agent now exists: blockers L1–L4 are cleared, L5, L6 and L8 are partly cleared, and L7, L9 and L10 are still open (section 3, rechecked 2026-10-04). This document records:
- what was reviewed;
- what still holds;
- what blocks the work;
- what is needed to resume.

**Context:** this was sub-project 2, after the curate stage (spec `docs/superpowers/specs/2026-10-03-curate-stage-design.md`). Its goal was to evaluate the LedgerLens agent on many labelled cases and explain its behaviour with AWS-native tooling: AgentCore Evaluations, AgentCore Observability and the Gateway's Cedar policy decisions.

**Why it was on hold:** on 2026-10-03 the agent under test did not exist in a testable form. An evaluation harness built then would have tested the template agent, not LedgerLens. The v1 wiring (spec `docs/superpowers/specs/2026-10-03-v1-agent-wiring-design.md`), the write tools and the hand-off have since landed in `stage`.

## 1. What was reviewed

| Source | What it is |
|---|---|
| [`datathon/reports/Agent evaluation signal on AWS.md`](../../reports/Agent%20evaluation%20signal%20on%20AWS.md) | Research report (2026-10-03) on how to build labelled evaluation signal for this dataset and measure the agent on AWS |
| `datathon/research_notes/Agent evaluation signal on AWS/` | The report's four raw note files: `aws_evaluation_stack`, `benchmarks_and_datasets`, `metrics_and_explanation`, `verifiable_test_generation` |
| [`verification_2026-10-03.md`](../../research_notes/Agent%20evaluation%20signal%20on%20AWS/verification_2026-10-03.md) | Check of 13 AWS claims against AWS docs, the boto3 service models and the shipped SDK wheels (`bedrock-agentcore` 1.24.0, `strands-agents-evals` 1.4.0) |
| `docs/AGENTCORE_EVALUATIONS_GUIDE.md`, `docs/OBSERVABILITY.md`, `docs/AGENTCORE_TELEMETRY.md`, `docs/BEDROCK_MODEL_INVOCATION_LOGGING.md` | FAST template guides |
| `docs/LEDGERLENS_PRODUCT_DESIGN.md` §7, §10, §13 | Tool catalog, Cedar sketch and evaluation targets |
| The `stage` branch at `3372213` and the AWS account (us-east-1, profile `ledgerlens`) | What was built and deployed on 2026-10-03 |
| The `stage` branch at `1b4b4ed` and the AWS account (stack list and X-Ray destination only) | The 2026-10-04 recheck in section 3 |

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

The report plans for two people over two days. Submission is due 2026-10-05, one day after the work resumed. These parts do not fit and are cut first:
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

First checked on 2026-10-03 against `stage` at `3372213` and the AWS account. Rechecked on 2026-10-04 against `stage` at `1b4b4ed`. The 2026-10-04 AWS check covered only the stack list and the X-Ray trace destination. The live Gateway targets, Cedar policies, Runtime environment and Cognito users were not read, so "cleared" below means cleared in the code that `stage` deploys.

| # | Status (2026-10-04) | Limitation (as of 2026-10-03) | What changed | What still unblocks it |
|---|---|---|---|---|
| L1 | **Cleared** | **The agent is not deployed.** Only the data stack existed. | `aws cloudformation list-stacks` shows `ledgerlens-bank-assistant` (last updated 2026-10-04 23:11 UTC) next to `ledgerlens-bank-assistant-data` and `CDKToolkit`. Not checked: whether that deploy carries prompt v10 (commit `bc0787a`, 23:01 UTC). | Read `prompt.version` from the first traced session (needs L7). |
| L2 | **Cleared** | **The system prompt is still the FAST template.** | LedgerLens prompt `v10` (`agent/ledgerlens/tools/system_prompt.py:20`). Every agent span carries it as `prompt.version` (`agent/ledgerlens/ledgerlens_agent.py:148-152`). | — |
| L3 | **Cleared in code** | **The LedgerLens tools are not on the Gateway.** The only target was `sample-tool-target`. | Nine tool Lambdas are Gateway targets named `<slug>-target`; fraud detection is `fraud-detection-target` (`infra-cdk/lib/backend-construct.ts:881-891`). Trajectory names are therefore `gateway_<target>___<tool>` as the model sees them, and `<target>___<tool>` in Cedar. | — |
| L4 | **Cleared in code** | **No per-customer Cedar rule.** | `gateway/policies/policy.cedar`: (1) permit the nine tools only with a non-blank `customer_id` tag; (2) forbid any call whose `customer_id` input differs from the token's; (3) forbid `block_credit_card` and `open_claim` without `customer_confirmed == true`. So a cross-customer call and an unconfirmed write both produce a Cedar DENY. | — |
| L5 | **Partly cleared** | **No write tools.** | `block_credit_card`, `open_claim` and `human_agent_hand_off` are built, so the secure exit and P07's expected outcome can now be reached. But the two DSQL writers change the shared data, as `ll_write` (UPDATE on `products`, INSERT on `complaints`), with no sandbox. Their writes are idempotent: once a trial blocks a persona's card, the next trial finds it already Blocked, a different case with a different correct answer ("card already Blocked: inform, don't block again"). pass^3 on write cases is therefore wrong without a reset, and the demo personas change state too. | Run write cases only on `EVL-` clones (L10), or restore the touched `products` and `complaints` rows after each trial. |
| L6 | **Partly cleared** | **No observable exit.** | Blocking, the claim and the hand-off are now tool calls behind a Strands interrupt (`agent/ledgerlens/tools/confirmation_hook.py`). The runtime streams a `confirmation` event, and only a Yes click sent back as `resume_prompt` runs the tool. A typed "yes" never does. Read-only exits (explain, abstain) still leave no record, and there is no `disposition` field. | Make the runner answer `confirmation` events with Yes or No per case. Grade read-only exits as "no write or hand-off call" plus a response check, or add a `disposition` field. |
| L7 | **Open** | **Observability is off.** | No change found. The X-Ray trace segment destination is still `XRay` (`ACTIVE`), not `CloudWatchLogs`. The image still pins `aws-opentelemetry-distro==0.16.0` (`agent/ledgerlens/Dockerfile:18`). `infra-cdk/lib` sets no `OTEL_*`, `AGENT_OBSERVABILITY_ENABLED` or `UNIFIED_TRACES_DESTINATION_ENABLED` variable. Telemetry deliveries and Gateway tracing were not rechecked. | Enable Transaction Search (one account setting). Deliver Runtime and Gateway traces. Check the unified-spans rule in §2.2, which may need ADOT 0.18.0 or later. |
| L8 | **Partly cleared** | **No test logins mapped to customers.** | One demo login, `demo@ledgerlens.example`, maps to P03 (`CLI-70U0WJ1NH1MN`, `infra-cdk/lib/cognito-construct.ts:146`). Other personas are reached by editing `USER_CUSTOMER_IDS_MAP` on the pre-token Lambda (README, "Switch persona"). A runner can step through personas one at a time, starting a new session after each switch. It cannot run personas in parallel, and every switch changes the login the team and the judges use. | One Cognito user per persona (and per `EVL-` clone used), with its `sub` in the map. |
| L9 | **Open** | **The design's evaluation targets rest on signal the data lacks.** | No change. Design doc §13 still scores reason accuracy against `reason_category` and fraud detection against `is_fraud` (`docs/LEDGERLENS_PRODUCT_DESIGN.md:1063-1064`). Its other rows are record-and-policy checks and can stay: fraud protocol, no data change without confirmation, grounding, privacy leaks, latency. | Replace the two rows with the record-and-policy metrics in §4.2. |
| L10 | **Open** | **No evaluation clones exist.** | No change. The only `EVL-` code is the curate gate that rejects that prefix in delivered data (`data_load/curate_rules.py:52-71`). | A clone or mutation step, local DuckDB first, then a load into DSQL. This is now also what isolates the write tools (L5). |
| L11 | **New** | — | A persona evaluation was run and fixed in prompt v10 (`bc0787a`, PR #15: findings on P01, P03 and P07). Its cases, transcripts and scores are not in the repo (`docs/agent-handoff/` is gitignored), so a new run has no baseline to compare with. | Get the run's notes from the teammate, or treat the first harness run as the baseline. |
| L12 | **New (2026-10-05)** | — | AgentCore Evaluations rejects every session with a Yes/No confirmation: `GoalSuccessRate` and `TrajectoryInOrderMatch` both return `SpanEventParsingException`. Read-only sessions score normally. Seen with strands-agents 1.32.0 and the custom `ConfirmationHook` interrupt, so the confirmation cases (E1a, E1b, E2b, E4a, E4b) are graded locally only. | Recheck after the planned Strands upgrade (1.57.2, `HumanInTheLoop` interrupts); the steps are in `evals/README.md`. Otherwise use a code-based evaluator or open an AWS support case. |

Also new since 2026-10-03: a Bedrock guardrail sits in front of the agent (commit `4087944`). Injection cases (`inject_text`) therefore test the guardrail and the agent together, unless the guardrail is turned off for an ablation.

## 4. When resuming

### 4.1 Prerequisites, in order

1. **Agent:** done on 2026-10-04 for the prompt (L2), the Gateway tools (L3), the Cedar rules (L4) and the deploy (L1). Still open: one login per persona (L8).
2. **Observability (L7):** still open.
   - enable Transaction Search;
   - deliver Runtime and Gateway traces;
   - confirm that one traced session shows `execute_tool` spans, `prompt.version`, and a Policy span carrying a Cedar decision.
3. **Scope decision on writes (L5, L6).** Three scopes were offered on 2026-10-03:
   - **minimal agent plus evaluation** of read-only exits;
   - **evaluation harness only**, while a teammate builds the agent;
   - **full**, adding sandboxed write tools.

   The team put the work on hold instead of choosing. Since then the agent and the write tools have been built, so the second option is gone. What remains is a choice between:
   - **read-only exits only**, on the personas and the defect cohort, with no data changes;
   - **write cases too**, which need `EVL-` clones or a row reset first (L5, L10).

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
