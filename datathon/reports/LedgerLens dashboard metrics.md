# Chart the failures the stream already records

LedgerLens's CloudWatch dashboard publishes eight numbers per model, prompt and run. The v10 baseline files it already reads support **nineteen more metric families**, and those families change the story. **Both models score 0% on the E2 explanation cases.** DeepSeek V3.2 is flaky (pass^1 60%, pass^3 40%, case-level ICC ≈ 0.44), while gpt-oss-120b is consistently wrong (47%, 40%, ICC ≈ 0.87). **60% of DeepSeek's Yes clicks returned "Unknown tool"** because it proposed under a bare tool name. **AgentCore's GoalSuccessRate scored only 32 of 60 sessions**, and the 28 it missed are exactly the sessions that contain a confirmation. All of these come from `sessions.jsonl`, `grades.jsonl` and `aws_eval.jsonl` and need changes only to `report.py` and `cw_dashboard.py`, so they can ship for today's submission with no deploy and no new sessions. The live stack adds free AWS metrics for every component. However, the agent and the tool Lambdas turn failures into successful responses, so the Runtime and Lambda error panels read zero exactly when something breaks. The real failure, consent, overwrite and hand-off signals come from Logs Insights widgets over log lines that already exist today, and from metric filters and alarms after judging. For the business row, the honest headline is **safe automated resolution: 4 of 10 cases on every run for both models (Wilson 17–69%), with 0 unsafe cases (95% upper bound 30%)**, shown beside containment rather than replaced by it. Live resolution, time-to-protect and deadline-disclosure KPIs need one structured outcome event and two small tool changes, and these wait until after review. History across prompt versions holds only if every data point carries its own run folder, a hashed prompt id and its publish time. CloudWatch rejects data stamped more than two weeks back and searches only the last two weeks.

## Nineteen metric families already sit in the v10 baseline files

### What the dashboard publishes today

Today the dashboard sends eight metrics to namespace `LedgerLens/Eval`, with dimensions Model × Prompt × Run ([cw_dashboard.py:58-79](../../evals/cw_dashboard.py#L58-L79)):

| Metric | What it measures |
|---|---|
| `PassRate1` | Mean trial pass rate (pass^1) |
| `PassRateK` | Share of cases passing on every run (pass^k) |
| `UnsafeCases` | Cases with any unsafe run |
| `HarnessErrors` | Sessions the harness failed to complete |
| `AwsGoalSuccess` | AgentCore `GoalSuccessRate` score |
| `AwsTrajectory` | AgentCore `TrajectoryInOrderMatch` score |
| `MedianLatencySeconds` | Median session latency |
| `CostUSD` | Model-token cost |

### What the baseline records

The baseline is **60 sessions: 10 cases × 3 runs × 2 models, on prompt v10, started 2026-10-05T05:12Z** ([run.json](../../evals/results/baseline-v10/run.json)). For each session the stream digest keeps every tool call with the model-emitted name and its raw arguments, every tool result, every confirmation proposal together with the click that answered it, and per-request latency, token usage and stop reasons ([stream.py:56-116](../../evals/stream.py#L56-L116); [runner.py:65-125](../../evals/runner.py#L65-L125)). The grader records every failing check, not only the first ([graders.py:352-369](../../evals/graders.py#L352-L369)). Every value in this section was computed read-only from [sessions.jsonl](../../evals/results/baseline-v10/sessions.jsonl), [grades.jsonl](../../evals/results/report-v10/grades.jsonl) and [aws_eval.jsonl](../../evals/results/baseline-v10/aws_eval.jsonl). It reproduces the session medians in the report, 12.9 s and 10.8 s ([report.md](../../evals/results/report-v10/report.md)), which cross-checks the computation.

### Per-check failure rates tell v11 what to fix

**The most useful single addition is `CheckFailureRate`**: failing sessions ÷ sessions whose case runs the check. It needs a `Check` dimension (27 values) and two companion counts, `CheckFailures` and `FirstFailures`.

**Build the Pareto from all failures, not from `first_failure`.** The grader lists the two runner checks, `unexpected_confirmation` and `missing_confirmation`, before the scripted ones, so `first_failure` leans toward them because of list order, not because they happen first in the session ([graders.py:358-366](../../evals/graders.py#L358-L366)). First failure remains a useful secondary view, in line with Hamel Husain's advice to note "the first failure observed in a trace" ([AI Evals FAQ](https://hamel.dev/blog/posts/evals-faq/)).

**The two models fail differently.** DeepSeek misses *when* to propose: it fails the confirmation-details check 5/15 (33%) and the missing-confirmation check 4/15, and it skips `explain_transaction` in 2 of 3 E2a runs because it answers from session context. gpt-oss fails on *what it says*: it prints decline code 51 in all 3 E2a runs and re-proposes the block after a No in all 3 E1a runs. Unexpected proposals touch 20% of all sessions for both (DeepSeek 17%, gpt-oss 23%). Fifteen of the 27 checks never failed, among them privacy, foreign id, typed yes, language, currency and cause-guessing.

**Add an `Evaluation` dimension (5 values) to `PassRate1`.** It produces the single most actionable bar for a v11 slide:

| Evaluation | DeepSeek | gpt-oss |
|---|---|---|
| E1 (block, consent) | 5/6 | 3/6 |
| E2 (explain a charge) | **0/6** | **0/6** |
| E3 (list cards) | 2/3 | 3/3 |
| E4 (hand-off) | 2/6 | 3/6 |
| E5 (privacy, language) | 9/9 | 5/9 |

**Don't add a per-language metric yet.** E5c is the only Portuguese case ([cases.yaml:167-180](../../evals/cases.yaml#L167-L180)), so a "PT 100%" bar would invite a Spanish-versus-Portuguese claim that a single case can't support. Show it as a labelled count ("PT: 1 case, 3/3 runs") until at least three cases carry a `language: pt` field.

### Confirmation and tool metrics expose a product bug

The confirmation protocol makes proposal quality the most precisely measurable behaviour in the stream. The runner answers scripted confirmations in order. It records any other confirmation as unexpected and answers it No ([runner.py:89-110](../../evals/runner.py#L89-L110)).

**Proposal precision** is scripted proposals ÷ all proposals: **72% for DeepSeek (13/18) and 64% for gpt-oss (14/22)**. Recall is 73% and 80%. A small `report.py` classifier can split the 13 unexpected proposals into three causes:

| Cause | Count | Where |
|---|---|---|
| Re-proposals after a No | 5 | 4 from gpt-oss |
| Hand-offs no case asked for | 5 | 4 from gpt-oss, three of them in E5a |
| Re-proposals after a Yes failed with "Unknown tool" | 3 | All DeepSeek |

The third cause is what a pass rate hides. DeepSeek proposed `human_agent_hand_off` without the `gateway_…___` prefix, so **3 of its 5 Yes clicks returned "Unknown tool"**, and each time it then proposed again under the right name. In production that means the customer taps Yes, the hand-off fails, and a second button appears. A `YesUnknownToolRate` tile, red above zero, is therefore a **product-bug detector**, not only an eval score. The likely root cause is that the confirmation hook matches the bare name while Strands registers only the prefixed one. That is inferred from the stream and not yet verified in the hook code.

Three more confirmation metrics complete the set. `ReproposalAfterNoRate`, sessions that propose a declined tool again ÷ sessions with a No, is **11% for DeepSeek and 33% for gpt-oss**; it should run on every session rather than only E1a, since the grader is already case-independent ([graders.py:157-164](../../evals/graders.py#L157-L164)). `HandoffReasonAccuracy` is **75% for DeepSeek and 50% for gpt-oss**: gpt-oss used `CUSTOMER_REQUEST` instead of `UNRESOLVED` in E4b, and DeepSeek twice sent `CARD_NOT_ACTIVE`, a value outside the tool's enum. `TypedYesExecuted` shows that **0 of 6 typed "Sí, bloquéala" replies executed a write**, which turns the consent guarantee from an assertion into a measured fact.

**Tool-call validity is 62/69 = 90% overall: 84.6% for DeepSeek and 93.0% for gpt-oss.** The defects split cleanly by model:

| Defect | DeepSeek | gpt-oss |
|---|---|---|
| Bare (unprefixed) tool names | 3 | 1 |
| `related_ids` sent as the string `"[]"` | 3 | — |
| Off-enum hand-off reasons | 2 | — |
| Explicit `null` optional arguments | — | 2 |

Every defect type produced either a failed call or a broken confirmation flow, and each can be fixed in the prompt or the schema.

**The tool error rate needs a careful denominator.** The raw share of results with `status == "error"` is 35/69 = 51%. But 29 of those 69 results are the "Not done:" messages the hook writes after a No or a typed reply, so the raw share mostly counts scripted clicks. **On executed calls only, the error rate is 23% for DeepSeek (3/13) and 11% for gpt-oss (3/27)**. Every one of those errors is an "Unknown tool" or a `ValidationException`.

**A local in-order trajectory match scores 67% for DeepSeek and 83% for gpt-oss** over the 36 sessions whose case lists expected tools. It agrees with AWS `TrajectoryInOrderMatch` on **all 12 sessions AWS could score** and also covers the 24 confirmation sessions AWS can't. That agreement supports equivalence with AWS's programmatic matcher ([Ground truth evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ground-truth-evaluations.html)) but doesn't prove it.

**Two tempting metrics should stay off the slides for now.** The first is a silent-proposal rate: 20 of gpt-oss's 22 proposals carry no assistant text, although v10 requires the agent to "say in one sentence that you can block the card" ([v10.md:61-63](../../evals/prompts/v10.md#L61-L63)). The digest keeps only `text` blocks ([stream.py:96-98](../../evals/stream.py#L96-L98)), so one raw stream has to be inspected before the claim is made. The second is a "model sent `customer_confirmed: true`" counter, which measures instruction-following rather than a bypass attempt, because v10 tells the model to send it ([v10.md:61-66](../../evals/prompts/v10.md#L61-L66)).

### Reliability, cost and safety each need their own denominator

The reliability split is cheap to show, and it changes what to do next.

| Model | pass^1 | pass^3 (Wilson 95%) | pass@3 | Mixed cases | Always-fail cases | Case ICC |
|---|---|---|---|---|---|---|
| DeepSeek V3.2 | 60% | 4/10 (16.8–68.7%) | 8/10 | 4 | 2 | 0.44 |
| gpt-oss-120b | 47% | 4/10 (16.8–68.7%) | 5/10 | 1 | 5 | 0.87 |

**This adds `PassAtK`, `FlakyCases` and `AlwaysFailCases`.** The pass^1 − pass^3 gap needs no new metric, because the widget can compute it with metric math (`m1 - m2`).

gpt-oss's failures are mostly deterministic, so prompt fixes should move them; DeepSeek's need lower variance or more runs. With 10 cases, neither the pass^3 tie nor the ICC difference is statistically established. τ-bench's definition of pass^k ([arXiv 2406.12045](https://arxiv.org/abs/2406.12045)) and Anthropic's point that pass^k matters "for customer-facing agents where users expect reliable behavior every time" ([Anthropic](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)) justify showing both numbers side by side.

**The pilot sets a noise floor of 10–13 points.** It ran the same prompt and models two minutes before the baseline and scored pass^1 70% and 60%. Publish `PassRateKLower` and `PassRateKUpper` as a band around `PassRateK`, so a v10-to-v11 delta is never read without its interval.

**AWS coverage becomes a number instead of a caveat.** `GoalSuccessRate` scored **32/60 sessions (53%)**. All 28 unscored sessions returned `SpanEventParsingException`, and they are exactly the sessions with a confirmation ([evals/README.md](../../evals/README.md)). Where AWS did score, it agreed with the local verdict on **31 of 32 sessions (Cohen's κ ≈ 0.93)**; the one disagreement was DeepSeek's E2a, where AWS passed a reply that skipped `explain_transaction`. Publish `AwsScoredShare`, `AwsGoalAgreement` and `AwsSpanParseErrors`, and recheck them after the Strands upgrade. The harness was clean, with 0 harness errors, 0 retries and 0 throttles. A `HarnessRetries` count warns early, before a retry turns into an error.

**Publish latency as raw values.** CloudWatch computes percentiles only from "raw, unsummarized data points" ([Metrics concepts](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/cloudwatch_concepts.html)). The `Values`/`Counts` form carries up to 150 values per metric per request ([PutMetricData](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_PutMetricData.html)), so a run's 60–64 requests per model fit in one datum. That replaces `MedianLatencySeconds`, which can't be re-aggregated across runs.

| Latency | DeepSeek | gpt-oss |
|---|---|---|
| Customer-turn request, p50 / p95 | 6.6 s / 17.4 s | 6.1 s / 13.1 s |
| Button-click request, p50 | 5.1 s | 4.4 s |

Across both models, a request that calls a tool costs about 2.5 s more at p50 (8.4 s vs 5.9 s). Compare time to first proposal only within a single case, because the two models propose in different sessions.

**Put cost beside accuracy**, following the argument that agents should be optimised jointly for both ([AI Agents That Matter](https://arxiv.org/abs/2407.01502)). Model-token prices are $0.62/$1.85 per million tokens (input/output) for DeepSeek and $0.15/$0.60 for gpt-oss ([config.py:26-29](../../evals/config.py#L26-L29)). At those prices, **gpt-oss is about 3.5× cheaper**:

| Cost | DeepSeek | gpt-oss |
|---|---|---|
| Per session | $0.0090 | $0.0026 |
| Per pass^3 case | $0.068 | $0.019 |

That holds even though gpt-oss writes 2.3× more output tokens. These figures cover model tokens only.

**Safety needs an honest bound and its opportunities.** All four unsafe detectors (write without Yes, foreign customer id, privacy leak, card-number echo; [graders.py:344-349](../../evals/graders.py#L344-L349)) found **zero hits in 60 sessions**. That is 0 of 10 cases per model, so the rule-of-three bound is a weak ≤30% ([Rule of three](https://en.wikipedia.org/wiki/Rule_of_three_(statistics))). The opportunity counts are stronger: 21 block proposals with none executed without a Yes, 69 of 69 tool calls carrying the session's own `customer_id`, and no card-number echo in 124 replies. Publishing `UnsafeHits` beside `UnsafeOpportunities`, with an `UnsafeType` dimension, makes that visible.

**Guardrail interventions** are counted from `guardrail_intervened` stop reasons:

| Run | Interventions | Turn that triggered it |
|---|---|---|
| Baseline | 1 of 124 requests | gpt-oss, the typed-consent resume |
| Pilot | 1 of 39 requests | DeepSeek, a Portuguese follow-up |

Both look like false positives on benign turns. Give the metric a `Kind` dimension (customer turn vs resume) so the pattern stays visible.

### Summary of the nineteen metric families

| Metric (unit) | Formula | Extra dimension | Widget | DeepSeek / gpt-oss, v10 |
|---|---|---|---|---|
| CheckFailureRate (%), CheckFailures, FirstFailures | failing sessions ÷ sessions whose case runs the check | Check (27) | metric `table` or sorted bar | unexpected proposals 17% / 23%; confirmation details 33% / 40% |
| PassRate1 by evaluation (%) | trial pass rate per E1–E5 | Evaluation (5) | grouped bar | E2 0% / 0%; E5 100% / 56% |
| ToolCallValidity (%), ToolCallDefects | 1 − defective ÷ model tool calls | DefectType (4) | tile + stacked bar | 84.6% / 93.0% |
| ToolExecErrorRate (%), ToolErrors | errored ÷ executed results (excludes "Not done:") | ErrorType (3) | tile + bar | 23% / 11% |
| ToolCallsPerSession, RepeatToolCallRate (%) | calls ÷ sessions; repeated tool + args ÷ calls | — | bar | 0.87 / 1.43; 11.5% / 20.9% |
| LocalTrajectoryMatch (%), beside AwsTrajectory | expected tools in order | — | bar | 67% / 83%; agrees with AWS 12/12 |
| ProposalPrecision, ProposalRecall (%), UnexpectedProposals | (proposals − unexpected) ÷ proposals; (expected − missing) ÷ expected | Cause (3), on the count | tiles + stacked bar | 72% / 64%; 73% / 80% |
| ReproposalAfterNoRate (%) | sessions re-proposing a declined tool ÷ sessions with a No | — | tile | 11% / 33% |
| HandoffReasonAccuracy (%), HandoffReasonInvalid | gold reason ÷ hand-off proposals with a gold reason | — | tile | 75% / 50%; invalid 2 / 0 |
| YesUnknownToolRate (%) | Yes clicks whose result is "Unknown tool" ÷ Yes clicks | — | tile, red above 0 | 60% / 0% |
| TypedYesExecuted, TypedYesOpportunities | typed answers followed by a successful write | — | tile, red above 0 | 0 of 3 / 0 of 3 |
| PassAtK (%), FlakyCases, AlwaysFailCases | ≥1 pass; 0 < passes < k; 0 passes | — | bar + `m1-m2` math | 80% / 50%; 4 / 1; 2 / 5 |
| PassRateKLower / Upper (%) | Wilson bounds over cases | — | band around PassRateK | 16.8–68.7% for both |
| AwsScoredShare, AwsGoalAgreement (%), AwsSpanParseErrors | scored ÷ applicable; local = AWS | Evaluator (2) | bar | GoalSuccess scored 60% / 47%; agreement 94% / 100% |
| HarnessRetries | sessions with `attempt == 2` | — | tile | 0 / 0 |
| RequestLatency, SessionLatency (s, raw values) | every `latency_s` | Kind (2), on requests | p50/p95 bar | customer-turn p95 17.4 s / 13.1 s |
| Tokens per session; CostPerPassingTrialUSD, CostPerPassKCaseUSD | sums; cost ÷ passes | — | bar | $0.0150 / $0.0055; $0.068 / $0.019 |
| GuardrailInterventions, GuardrailRate | `guardrail_intervened` in stop reasons | Kind (2) | tile | 0 / 1 of 124 requests |
| UnsafeHits, UnsafeOpportunities, UnsafeBound95 | per detector; 3/n over cases when zero | UnsafeType (4) | tile grid, red above 0 | 0 everywhere; ≤30% per model |

### The next tier needs small grader or runner changes

The silent-proposal rate joins a second tier that needs a small grader or runner change and is not for today. That tier counts searches dated after the tools' fixed 2026-06-17 clock, which gpt-oss sent on 3 of 43 baseline calls and 5 of 14 pilot calls. It checks hand-off summary language, since gpt-oss wrote 6 of 10 summaries in English for Spanish-speaking customers. It adds markup leaks, customer ids in any tool field rather than only `customer_id`, time to first token (which needs the runner to timestamp the first SSE line), and a per-session Logs Insights drill-down.

## The live stack reports health for free but reads zero when the agent fails

### Free metrics already cover every component

AWS includes basic monitoring metrics in its own namespaces at no charge ([re:Post](https://repost.aws/knowledge-center/optimize-cloudwatch-custom-metrics)). Every LedgerLens component already publishes them, so all of the following can sit on the dashboard today with no code or infrastructure change.

| Component | Namespace and key metrics | What it tells LedgerLens |
|---|---|---|
| AgentCore Runtime | `AWS/Bedrock-AgentCore`: Invocations, SessionCount, Latency, Throttles, System/User/Total Errors, by `Resource` ([Runtime observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html)) | Turns, new conversations and end-to-end turn time. A confirmation pause ends the stream, so paused time isn't counted |
| AgentCore Gateway | Invocations, Latency, Duration, `TargetExecutionTime`, by tool `Name` ([Gateway observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-gateway-metrics.html)) | Tool mix, and Gateway overhead versus Lambda time |
| Cedar Policy | `AllowDecisions`, `DenyDecisions`, by `OperationName`, `ToolName` and `Mode`; published by default, no tracing needed ([Policy observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-policy-metrics.html)) | Whether the safety backstop ever fired |
| Bedrock models | `AWS/Bedrock`, per `ModelId`: invocations, input/output tokens, `InvocationLatency`, `TimeToFirstToken`, throttles ([Bedrock runtime metrics](https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring-runtime-metrics.html)); output tokens per second via metric math ([OTPS](https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring-runtime-otps.html)) | Per-model load, cost and latency. Account-wide, so harness and judge traffic are included |
| Guardrails | `AWS/Bedrock/Guardrails`: `InvocationsIntervened`, split by `GuardrailPolicyType` ([Guardrails metrics](https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring-guardrails-cw-metrics.html)) | Prompt-attack and content blocks (`ContentPolicy`) versus off-topic blocks (`TopicPolicy`). The guardrail defines only content filters and four denied topics ([agent-guardrail.ts:18-116](../../infra-cdk/lib/utils/agent-guardrail.ts#L18-L116)) |
| Tool Lambdas | `AWS/Lambda`, per `FunctionName` | Usage mix, duration, timeouts |
| Aurora DSQL | `AWS/AuroraDSQL`: total and read-only transactions, commit latency, DPUs ([DSQL monitoring](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/cloudwatch-monitoring.html)) | Writes (blocks, claims) as total minus read-only, and DSQL cost |
| Cognito, feedback API | Cognito sign-ins ([AWS/Cognito metrics](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/SupportedMetricsForResourceTagsForTelemetry.html)); the API's request, 4XX and 5XX counts ([CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)) | Logins (customer and evaluator) and feedback submissions |

**The metric with the most demo value is Cedar `DenyDecisions` on `OperationName=AuthorizeAction`.** The hooks overwrite `customer_id` and set `customer_confirmed` before any call reaches the Gateway. A deny on `AuthorizeAction` therefore means a hook was bypassed, and the expected value is zero ([policy.cedar:56-91](../../gateway/policies/policy.cedar#L56-L91)). Denies on `PartiallyAuthorizeActions` are expected and harmless: they come from listing tools for a login whose `customer_id` is blank ([policy.cedar:35-50](../../gateway/policies/policy.cedar#L35-L50)).

### Three error panels under-count failures

| Panel | Why it stays at zero | Source |
|---|---|---|
| Runtime `SystemErrors` | The agent's entrypoint catches every exception, logs "Agent run failed" and then yields `{"status":"error"}`. The HTTP stream completes normally, so model, Gateway, memory and tool exceptions never count | [ledgerlens_agent.py:234-236](../../agent/ledgerlens/ledgerlens_agent.py#L234-L236) |
| Lambda `Errors` | Every tool handler catches its errors and returns `{"error": …}`. `Errors` counts only thrown exceptions and timeouts, so it stays near zero while tools fail | [hand-off handler.py:74-81](../../gateway/tools/human_agent_hand_off/human_agent_hand_off_lambda/delivery/handler.py#L74-L81); [Lambda metrics](https://docs.aws.amazon.com/lambda/latest/dg/monitoring-metrics-types.html) |
| Bedrock client errors | A guardrail block is a successful Converse response | — |

**On this stack a green error panel means nothing unless a log-derived failure count sits beside it.**

### Existing log lines already carry the LedgerLens signals

Those counts are available today, without code changes, as Logs Insights widgets over log lines the code already writes. Structured span attributes in `aws/spans` add Cedar decisions with their determining policies, and Gateway latency per tool. Where a span attribute and a text log line carry the same signal, read the span.

| Signal | Log line or source | Caveat |
|---|---|---|
| Turns and sessions per model × prompt; evaluator vs customer traffic | `[PROMPT] version=… model=… session=…`, or `invoke_agent` spans | Evaluator sessions carry hashed `prompt.version` values. Check once that the line isn't duplicated across log streams |
| Consent: approved vs declined, per tool | `[CONFIRM] Customer approved/declined …` ([confirmation_hook.py:32-71](../../agent/ledgerlens/tools/confirmation_hook.py#L32-L71)) | "Declined" also covers typed replies and unanswered interrupts |
| Customer-id overwrites | `[CUSTOMER-ID] Replaced…` ([customer_id_hook.py:55-67](../../agent/ledgerlens/tools/customer_id_hook.py#L55-L67)) | Also fires when the model simply omits the id. Label it "model didn't pass the session customer_id", not "attack blocked" |
| Turns that failed inside the agent | "Agent run failed" | — |
| Handled tool errors, per tool | The tool Lambdas' "returned an error" and "Unexpected error in" lines | — |
| Hand-offs, by priority | "queued HO-… (priority=…)" | The reason is never logged ([handler.py:83-86](../../gateway/tools/human_agent_hand_off/human_agent_hand_off_lambda/delivery/handler.py#L83-L86)) |
| Feedback ratings | DynamoDB only | Not in any log ([feedback/index.py:139-170](../../infra-cdk/lambdas/feedback/index.py#L139-L170)) |

The Cedar proof that a cross-customer call was blocked is `DenyDecisions`, not the overwrite line.

**Logs Insights widgets have side effects.** They "run every time you load the dashboard and every time that the dashboard refreshes" and count toward the account's 100 concurrent queries ([Add query to dashboard](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CWL_ExportQueryResults.html)). The AgentCore evaluation client draws on the same pool, two queries per scored session ([automation viability §2.2](../docs/analysis/2026-10-05-eval-automation-viability.md)).

### Link to GenAI Observability; leave invocation logging off

**CloudWatch's GenAI Observability page** already shows sessions, traces and evaluations for each agent ([View observability data](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/view-observability-data-cloudwatch.html)). It is a console page, not a set of widgets, so the custom dashboard should deep-link to it from a Markdown text widget rather than try to embed it.

**Bedrock model invocation logging should stay off.** It would fill the Model Invocations view ([Model Invocations](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/model-invocations.html)), but it logs full prompts and responses, which contain card digits and transactions that the guardrail does not mask ([agent-guardrail.ts:88-92](../../infra-cdk/lib/utils/agent-guardrail.ts#L88-L92)). The free per-model metrics already cover tokens and latency.

### Alarms wait for review

Alarms need metric filters or confirmed dimension sets, and both belong after review. A tight set fits within the free tier's 10 alarm metrics ([CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)): Cedar `DenyDecisions` on `AuthorizeAction` at one or more in five minutes, Runtime system errors and throttles, Bedrock throttles and server errors for the customer model, an "Agent run failed" metric filter, and Lambda `Errors` on the two write tools. All of them should treat missing data as not breaching, because most hackathon periods have no data at all. AWS guidance also suggests alarming on `InvocationsIntervened` to catch jailbreak waves ([re:Post](https://repost.aws/articles/AR-ZBYACEoSSeYSLhKzu83uQ/troubleshooting-and-monitoring-amazon-bedrock-guardrails-usage-with-amazon-cloudwatch)).

**Four facts are still unverified**, and each needs one read-only `aws cloudwatch list-metrics` call per namespace before anyone writes an alarm: which dimension combinations AWS actually publishes for Gateway and Policy, whether the tool `Name` value is `<target>___<tool>` or the bare name, whether guardrail metrics are emitted at all when the guardrail is attached inline through Converse, and whether the ADOT 0.16.0 exporter emits Strands' own OTel metrics. Until those are confirmed, dashboard widgets should use SEARCH expressions rather than hard-coded dimension sets. Any custom metric the agent publishes itself must use the `bedrock-agentcore` namespace unless its role changes ([agentcore-role.ts:68-77](../../infra-cdk/lib/utils/agentcore-role.ts#L68-L77)).

## Verified resolution, not containment, should headline the business row

### Vendor resolution rates are inflated

Contact centres and AI-agent vendors report the same family of metrics: first-contact resolution, containment (or "resolution rate"), escalation, CSAT, handle time and cost per contact. The vendor figures are generous by definition. Intercom claims a 76% average resolution rate for Fin ([fin.ai](https://fin.ai/)), and its help centre counts an "assumed resolution" when a customer simply leaves without asking for more help ([Intercom](https://www.intercom.com/help/en/articles/8205718-fin-ai-agent-outcomes)). Gartner's 2024 survey, by contrast, found only **14% of customer-service issues fully resolved in self-service** ([Gartner](https://www.gartner.com/en/newsroom/press-releases/2024-08-19-gartner-survey-finds-only-14-percent-of-customer-service-issues-are-fully-resolved-in-self-service)), and SQM puts the human contact-centre average for first-call resolution at 71% ([SQM](https://www.sqmgroup.com/resources/library/blog/fcr-metric-operating-philosophy)). Both of those figures come from search summaries, so if they appear on the chart as reference lines they need the caption "different definitions". The CFPB's chatbot report names the two harms a bank dashboard should measure directly: "doom loops" with no way to reach a human, and failing to recognise that a customer is raising a dispute ([CFPB](https://www.consumerfinance.gov/data-research/research-reports/chatbots-in-consumer-finance/chatbots-in-consumer-finance/)).

LedgerLens earns credibility by headlining a strict, verified end state, and by putting containment beside it under the caption "containment ≠ resolution". Showing the gap is the point. It also answers the hackathon brief, which asks for "an ops/decision dashboard (e.g., containment rate, escalation reasons)" ([hackathon_judging.md](../research_notes/LATAM%20bank%20AI%20agent%20use%20cases/hackathon_judging.md)).

### Regulators set the clocks the agent should disclose

LATAM regulators supervise complaint handling against statutory clocks:

| Country | Requirement | Source |
|---|---|---|
| Colombia (SFC) | Resolve a complaint within **15 business days**; responses classified favourable, partly favourable or unfavourable | [Kreston summary](https://krestoncolombia.com/interes/CircularKRMNo.011-ImplementaciondesarrollotecnologicoSmartsupervisionySACSuperfinanciera1.pdf); [SFC](https://www.superfinanciera.gov.co/publicaciones/20650/consumidor-financieroinformacion-generalquejas-contra-entidades-vigiladasquejas-contra-entidades-vigiladas-por-la-superintendencia-financiera-de-colombia-20650/) |
| Argentina (BCRA) | Claim number issued on the spot; answer within **10 business days** | [BCRA PUSF](https://www.bcra.gob.ar/archivos/Pdfs/texord/t-pusf.pdf) |
| Mexico | Immediate reference number, plus date and time, for card notices | [DOF, Circular 14/2018](https://www.dof.gob.mx/nota_detalle.php?codigo=5539863&fecha=03%2F10%2F2018) |
| Brazil (SAC) | Answer within **7 calendar days**; a human must stay reachable | [Decreto 11.034](https://www2.camara.leg.br/legin/fed/decret/2022/decreto-11034-5-abril-2022-792480-publicacaooriginal-164911-pe.html) |

None of these rules targets AI, but each maps onto something the agent controls. **Registration with a reference** asks whether the agent read a reference back to the customer; **deadline disclosure** asks whether it stated the correct country clock; **dispute capture** asks whether it called `open_claim` on the right transaction ids; **human-on-request honoured** asks whether a request for a person reached a hand-off; and **hand-off completeness** asks whether the summary is complete enough that the human never has to re-ask. The final dispute outcome belongs to the back office, not to the agent, and should not be scored as an agent metric.

### What v10 already shows

| Rank | KPI | Definition | v10 baseline (eval) | Live status |
|---|---|---|---|---|
| 1 | Safe automated resolution (+ share attempted) | Cases whose every run reaches the gold exit with no unsafe flag (pass^k); pass^1 beside it | **4/10 cases for both models (Wilson 17–69%)**; pass^1 60% / 47% | Needs a `SessionOutcome` event |
| 2 | Unsafe outcomes, plus attacks stopped | Cases with any unsafe run; per-type rates over opportunities; Cedar denies and guardrail stops counted separately | **0/10 per model (≤30%)**; 0 of 21 block proposals executed without a Yes; typed "sí" 0/6 | `DenyDecisions` free today |
| 3 | Hand-off rate, reason mix, escalation quality | Missed and unnecessary transfers, measured against gold | E2b hand-off **missed in all 6 sessions**; unrequested hand-offs 1 / 4; reason accuracy 75% / 50% | Priority today; reason needs a log line |
| 4 | Time-to-protect | Seconds and turns from disowning a charge to a successful block read-back | Derivable only within a single case; the pooled time-to-first-proposal (p50 13.6 s / 8.2 s) isn't comparable | Needs a timestamp and a reference in the block result |
| 5 | Dispute capture and deadline disclosure | `open_claim` on the right ids ÷ eligible conversations; correct clock stated ÷ claims | **No claim was proposed in the 60 sessions**; no deadline exists anywhere in the code | Needs a per-country deadline field |
| 6 | Containment (context only) | Sessions without a hand-off ÷ sessions | Fixed by the case mix, so not meaningful in eval | Live, from hand-off counts |
| 7 | Cost per resolved conversation | Cost ÷ pass^3 cases, beside a labelled human comparator | $0.068 / $0.019 (model tokens only) | Add Runtime, Gateway and DSQL unit costs |
| 8 | CSAT / feedback | Rated sessions whose last rating is positive, shown as counts | None (the eval doesn't rate) | DynamoDB only |
| 9–10 | Language coverage, fairness by country | pass^k per language or country, with n | Portuguese: 1 case, 3/3 for both; n too small | Needs span attributes |
| 11–12 | Repeat contact within 7 days, abandonment | Same customer returns with the same intent; session ends at a pending step | Not measurable in scripted eval | Needs ≥7 days of live traffic and an actor hash |

Baseline values come from [report.md](../../evals/results/report-v10/report.md) and [sessions.jsonl](../../evals/results/baseline-v10/sessions.jsonl).

### Three numbers must stay labelled for what they are

**The dataset's 76–77% "resolved" rate is a generator constant, not a baseline.** It is flat across every country × segment cell, and repeat-contact rates don't differ by it ([data findings](../docs/analysis/2026-09-26-data-findings-and-workflow-decision.md)). It must never stand in as the human benchmark.

**Any human-cost comparison is a projection.** Nearshore contact-centre labour costs $12–23 an hour fully loaded ([CallForce](https://callforce.global/blog/cost-of-nearshore-outsourcing/), a vendor source). At the dataset's handle times of 221 s and 435 s, that is **roughly $0.74–$2.78 of talk time per contact**, a lower bound, against $0.003–$0.009 of model tokens per eval conversation, a gap of 80× to 1,000×. But handed-off conversations still cost a human, and the team's own rule is that the data doesn't support money-savings claims ([LATAM use cases report](LATAM%20bank%20AI%20agent%20use%20cases.md)), so the dashboard should present the comparison as a formula with its assumptions, not as a savings claim.

**Live traffic during judging will be a handful of sessions.** Live tiles should show counts with sparklines, not rates.

### What the live versions need

**The cheapest high-value change is one structured outcome event per session**: a `SessionOutcome` record in embedded metric format (EMF) carrying prompt version and model, country and language, the exit and hand-off reason, whether a claim was opened and a block done, turns, seconds-to-protect and unsafe flags. With that record in place every live KPI becomes metric math, and the slices come from Logs Insights. **Two tool changes** complete the picture. `block_credit_card` returns only `{card_last4, status, already_blocked}`, with no reference and no timestamp ([card_block.py](../../gateway/tools/block_credit_card/block_credit_card_lambda/delivery/presenters/card_block.py)), and time-to-protect and registration-with-reference need both. `open_claim` returns a historical median and p90 resolution estimate rather than a statutory deadline ([open_claim.py](../../gateway/tools/open_claim/open_claim_lambda/application/use_cases/open_claim.py)), so deadline disclosure needs a per-country rule id and date in its result. The hand-off reason, an enum with no personal data, belongs in the hand-off Lambda's existing `logger.info`. Feedback is rated per message, so it should appear as positive and negative counts, read either from a custom widget over the existing `feedbackType-timestamp-index` GSI ([backend-construct.ts:528-555](../../infra-cdk/lib/backend-construct.ts#L528-L555)), or later from Powertools Metrics in the feedback Lambda.

## History survives only if every point carries its run, prompt hash and publish time

CloudWatch "treats each unique combination of dimensions as a separate metric" and "does not aggregate across dimensions for your custom metrics" ([Metrics concepts](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/cloudwatch_concepts.html)). The dimension design therefore *is* the history design, and the current code has two flaws that will corrupt it on the next publish.

### Two flaws corrupt the next publish

**Joined run labels.** `run_label()` joins every run folder into one `Run` value ([cw_dashboard.py:38-40](../../evals/cw_dashboard.py#L38-L40)). Publish `baseline-v10` today and `baseline-v10` plus `v11` tomorrow, and the baseline's numbers sit under two Run values, so the charts double-count. **Fix:** each data point should carry the Run of the folder its own sessions came from.

**Stamping with the run's start time.** Each datum is stamped with its run's `started_at` ([cw_dashboard.py:43-55](../../evals/cw_dashboard.py#L43-L55)). PutMetricData's limits make that risky ([PutMetricData](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_PutMetricData.html)):

| Data point stamped | What CloudWatch does |
|---|---|
| More than two weeks back | Rejects it |
| 3–24 hours back | It "can take as much as 2 hours" to appear |
| More than 24 hours back | It takes at least 48 hours to appear |

The baseline started at 05:12Z today, so publishing it this afternoon with that stamp risks a two-hour blank on deadline day, and publishing it again with the same stamp after 2026-10-19 will be rejected. **Fix:** stamp points at publish time, keep `started_at` in the text header, and publish straight after each run.

### Prompt ids and two time horizons

**Name prompts by hash.** Set `Prompt` to the name plus its hash, for example `v10-0085ea98`. That is the value the spans' `prompt.version` already carries ([evals/README.md](../../evals/README.md)), so eval metrics and runtime spans join on one key.

**The short view (two weeks) uses SEARCH.** SEARCH "can find only metrics that have reported data within the past two weeks" ([Search expression syntax](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/search-expression-syntax.html)), and Metrics Insights is limited to the same window ([Metrics Insights quotas](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/cloudwatch-metrics-insights-limits.html)). Within it, a widget built on `SEARCH('{LedgerLens/Eval,Model,Prompt,Run} MetricName="PassRate1"', 'Maximum')` picks up every new run automatically.

**The long view uses explicit metric arrays.** `cw_dashboard.py` should keep writing an explicit metric array for every past run, as `_series()` does now. Explicit metrics stay retrievable for 15 months: hourly data is kept for 455 days, and metrics that stop receiving data drop out of the console after two weeks but can still be read with `get-metric-data` ([Metrics concepts](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/cloudwatch_concepts.html)).

**A Run-less trend copy gives the cross-prompt line.** Publish five headline metrics a second time with dimensions `{Model, Prompt}` only, drawn as a time series at a one-hour period. That yields one point per run, readable across prompt versions. A prompt comparison is then a single metric-math expression (`e2 - e1`) over two `PassRateK` series, drawn with its Wilson band so that a change inside the 10–13-point noise floor visibly reads as noise.

Automated runs, once they exist, should go to a separate `LedgerLens-Evaluation-Auto` dashboard and never overwrite the pitch dashboard ([automation viability](../docs/analysis/2026-10-05-eval-automation-viability.md)).

### Cardinality and cost

Give each metric family **at most one dimension beyond Model, Prompt and Run**:

| Family | Extra dimension | Values |
|---|---|---|
| Check failures | `Check` | 27 |
| Pass rate | `Evaluation` | 5 |
| Unexpected proposals | `Cause` | 3 |
| Tool-call defects | `DefectType` | 4 |
| Tool errors | `ErrorType` | 3 |
| Unsafe hits | `UnsafeType` | 4 |
| Latency, guardrail | `Kind` | 2 |

Never use Case, Session or Persona as a dimension. That keeps a run to about 110 streams per model, roughly **220 in total**.

Custom metrics cost $0.30 per metric-month, prorated by the hour and charged only in hours that receive data ([CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)). A run published within one hour therefore costs **about $0.09**. The dashboard then exceeds the free tier's 50-metric limit and costs **$3 a month**.

### Per-session drill-down goes to logs

Per-session and per-case detail belongs in logs, not in dimensions. Write one JSON event per graded session, its `grades.jsonl` row plus the computed fields, to a log group such as `/ledgerlens/eval/grades`, and read it with a Logs Insights `log` widget in table view, for example failures by model and first failing check; the session ids in that table can be pasted into GenAI Observability to open the traces. A run is about 60 events of 1–3 KB each. PutLogEvents rejects events older than 14 days ([PutLogEvents](https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_PutLogEvents.html)), so these events must also be written at run time.

### A layout that reads top to bottom

A dashboard can hold up to 500 widgets, with metric views including `singleValue`, `gauge`, `bar`, `pie` and `table`, plus horizontal annotations and log widgets ([Dashboard body structure](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/CloudWatch-Dashboard-Body-Structure.html)). That supports this layout:

| Row | Content |
|---|---|
| 0. Text header | Definitions (the case is the unit; pass^k; Wilson; rule of three), the n behind every number, benchmark captions, and deep links to GenAI Observability |
| 1. Business tiles | Safe resolution x/n cases, unsafe 0/n (≤3/n), Cedar `AuthorizeAction` denies, containment as context, cost per pass^3 case |
| 2. Where it fails | `PassRate1` by evaluation, and `CheckFailureRate` as a table |
| 3. Confirmation quality | Proposal precision and recall, re-proposal after No, hand-off reason accuracy, the Cause stacked bar, Yes → Unknown tool |
| 4. Tool quality | Validity, error type, repeats, local vs AWS trajectory |
| 5. Reliability | PassAtK, PassRate1 and PassRateK; flaky and always-fail counts; AWS scored share and agreement |
| 6. Efficiency | Latency p50/p95 by Kind, tokens, cost |
| 7. Safety | Unsafe hits by type with their opportunities, guardrail interventions, typed-yes executed |
| 8. Live operations | Free metrics: Runtime, Gateway, Policy, Bedrock per model, Guardrails, Lambda, DSQL |
| 9. Live behaviour | Logs Insights tables: consent, overwrites, agent failures, tool errors, hand-offs |
| 10. History | Run-less trend lines and the per-session failures table |

## Submission day gets the eval panel and free widgets; instrumentation waits for review

**Today's work touches no deployed resource.** Re-grading and publishing the existing baseline needs no new sessions and no model tokens, and it calls only `PutMetricData` and `PutDashboard`. The judged runtime, the tools and the persona map stay as they are. That matters because judging runs from 2026-10-06 to 10-15, and a main-stack redeploy would also reset any demo persona edited in the console ([automation viability §1](../docs/analysis/2026-10-05-eval-automation-viability.md)).

**Everything else waits until after the review gate.** That covers metric filters, alarms, Lambda or agent code changes, and CDK constructs. Little is lost by waiting: on the evidence above, the live rows would show almost no traffic during judging anyway.

| Horizon | Work | Deploy? | Delivers |
|---|---|---|---|
| **Today (2026-10-05)** | **`report.py`:** the 19 metric families above, including the unexpected-proposal cause classifier and a re-proposal check run on every session.<br>**`cw_dashboard.py`:** Run per folder, hashed Prompt, publish-time stamps, raw-value latency, Wilson band, Run-less trend copy, text header.<br>**Widgets:** free-metric widgets via SEARCH; Logs Insights widgets over existing log lines | No | The full eval panel on the v10 baseline; live operations and behaviour rows; the business row computed from eval |
| **Today, only if time remains** | Silent proposals (after a raw-stream check); searches dated after the tools' clock; hand-off summary language; markup leaks; customer ids in any field; a `language` field on cases; per-session log events | No (grader or runner change; one new log group) | Prompt-level defects ready for v11 |
| **After judging (from 2026-10-16)** | **Monitoring:** metric filters for agent failures, consent, overwrites, hand-offs and tool errors; the free-tier alarm set; the hand-off reason log line; feedback metrics.<br>**Live KPIs:** the `SessionOutcome` event; a block reference and timestamp; a per-country deadline in `open_claim`; country and language span attributes.<br>**Harness:** time to first token in the runner; CodeBuild automation publishing to `LedgerLens-Evaluation-Auto` | Yes | Alarms; live resolution, time-to-protect and deadline-disclosure KPIs; one trend point per scheduled run |
| **Later** | Judge metrics (summary adequacy, faithfulness); AWS scoring of confirmation sessions after the Strands upgrade; alarms on online-evaluation scores; repeat contact and abandonment from ≥7 days of live traffic; LATAM-specific benchmarks (none were found) | Mixed | The claims a 10-case suite can't make |

Three uncertainties remain. Whether a `table` metric widget can sort rows by value is unconfirmed, and the Metrics Insights syntax for a top-N checks widget wasn't fetched. More fundamentally, every per-check and per-evaluation number rests on three runs of a single 10-case suite, so the dashboard should show them as counts with their n, not as precise rates.

## Conclusion

The best additions to the dashboard are denominators, not more headline rates. Today's dashboard reads the 60 sessions as "60% vs 47% pass"; with the right denominators the same data shows three distinct problems with three different owners. gpt-oss has two deterministic behaviours a prompt change should fix, printing decline codes and not taking No for an answer. DeepSeek has a tool-naming defect that is really a product bug in the confirmation path, on top of variance that more runs must tame. And AWS's own evaluator goes blind precisely in the confirmation sessions where LedgerLens's safety story lives. None of this needs a new run, only the right formulas over data already on disk, which makes it the strongest data-analytics evidence the submission can still add today.

The live side teaches the opposite lesson: on this stack an absence of AWS errors is not evidence of health, because the agent and every tool turn failures into successful responses, so any post-judging live dashboard has to rest on log-derived counts and an explicit outcome event rather than on vended error metrics. The history design, finally, has to be settled before the next publish rather than after. CloudWatch can't backfill beyond two weeks, SEARCH forgets runs after two weeks, and a joined Run label silently double-counts the baseline, so unless the Run label, prompt hash and timestamp are fixed before v11 is published, the v10 reference point that v11 is meant to beat will not reliably be on the chart.
