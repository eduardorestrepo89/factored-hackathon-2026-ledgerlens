# Observability

This page covers what LedgerLens records about each request, where to find it, and which account settings it depends on.

The stacks set up the application side: the agent's OpenTelemetry instrumentation, the log groups, and the feedback API's logging and tracing. Two account and region level settings are not in any stack: CloudWatch Transaction Search and Gateway tracing. The team turned both on in the console for account `704650059996` in `us-east-1`. They are one-time, account-wide decisions, so they stay outside the application stacks. A new account or region needs them turned on again (see [Account and region settings](#account-and-region-settings)).

## What LedgerLens emits

### Agent (AgentCore Runtime)

- **Traces.** The container starts the agent under `opentelemetry-instrument`. This is the AWS Distro for OpenTelemetry, `aws-opentelemetry-distro==0.16.0`, installed in `agent/ledgerlens/Dockerfile`. It auto-instruments the Strands agent: the `invoke_agent`, `chat`, `execute_event_loop_cycle` and `execute_tool` spans. Tool spans are named after the tool the model sees, `gateway_<target>___<tool>`.
- **Trace attributes.** `agent/ledgerlens/ledgerlens_agent.py` puts four attributes on the agent's spans, so evaluation and dashboards can tell requests apart:
  - `user.id`: the Cognito `sub`;
  - `session.id`: the runtime session;
  - `model.id`: the model that answered;
  - `prompt.version`: the prompt template (`PROMPT_VERSION`, now `v12`). For an evaluator's custom prompt, it is the prompt's name plus an 8-character hash of its text, such as `v10-0085ea98`.
- **Logs.** They go to `/aws/bedrock-agentcore/runtimes/<runtime-id>-DEFAULT`. Each line appears in both a `runtime-logs` stream and an `otel-rt-logs` stream. `OTEL_PYTHON_LOG_CORRELATION=true` (set in the Dockerfile) adds the trace and span IDs to each log record. Useful tags to search for:
  - `[PROMPT]`: prompt version, model and session of each request.
  - `[CONFIRM]`: the customer approved or declined a card block, claim or hand-off.
  - `[CUSTOMER-ID]`: a tool call was cancelled because the login has no linked customer, or the model's `customer_id` was replaced with the token's.
  - `[EVAL]`: an evaluator's model or prompt override, or an ignored one.
  - `Agent run failed`: an exception, with its stack trace.

  AgentCore creates this log group itself, so it stays behind when the stack is deleted.
- **Metrics.** The runtime role may send X-Ray segments and put CloudWatch metrics in the `bedrock-agentcore` namespace (`infra-cdk/lib/utils/agentcore-role.ts`). AWS also publishes runtime invocation metrics in `AWS/Bedrock-AgentCore`.

### Gateway and Cedar

With Gateway tracing on, each tool call adds an `AgentCore.Policy.AuthorizeAction` span, which carries the Cedar decision in `aws.agentcore.policy.authorization_decision`, and an `AgentCore.Gateway.InvokeTool` span. Cedar denies are also counted as `DenyDecisions` in `AWS/Bedrock-AgentCore`.

### Lambdas

Each Lambda LedgerLens defines logs to `/aws/lambda/<stack_name_base>-<name>` and keeps one week of logs. The group is deleted with its stack. The names:
- the nine tools, by slug, such as `ledgerlens-bank-assistant-list-credit-cards`;
- `-pretoken-v3`, `-feedback`, `-cedar-policy` and `-oauth2-provider` in the main stack;
- `-dsql-read-check` in the data stack.

CDK's own helper Lambdas (the custom resource providers and the S3 auto-delete handler) use default log groups. No Lambda turns on X-Ray active tracing.

### Feedback API

The REST API's `prod` stage (`infra-cdk/lib/backend-construct.ts`):
- **Tracing:** X-Ray on.
- **Execution logs:** level INFO, with data trace, so request and response bodies, feedback text included, land in the execution logs.
- **Metrics:** detailed metrics on.
- **Access logs:** JSON lines to `/aws/apigateway/<stack_name_base>-api-access`, kept one week.

### Data pipeline

Each CodeBuild stage logs to `/aws/codebuild/ledgerlens-data-load`, and the read check to its Lambda log group. The Step Functions execution history shows which stage failed; `make load-data` prints the link to the execution.

## Account and region settings

These were turned on in the console and are not in CDK:

- **CloudWatch Transaction Search.** Spans are written to the `aws/spans` log group and can be searched by attribute (`session.id`, `user.id`). AgentCore Evaluations reads the spans from there, so `evals.aws_eval` needs it (`evals/aws_eval.py`). Ingestion takes 2 to 5 minutes, so score a run at least 180 seconds after its last session. See [Enable Transaction Search](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Enable-TransactionSearch.html).
- **Gateway tracing.** A vended log delivery, `ledgerlens-gateway-traces`, sends the Gateway's traces to X-Ray. It adds the policy and tool spans above.

## Where to look

| Question | Where |
|---|---|
| What happened in one chat turn | Transaction Search on `aws/spans`, filtered by `session.id` |
| Why a tool call was refused | The `AgentCore.Policy.AuthorizeAction` span; `[CUSTOMER-ID]` lines in the runtime log |
| Why the agent returned an error | `Agent run failed` in the runtime log group |
| Why a tool failed | `/aws/lambda/<stack_name_base>-<tool-slug>` |
| A feedback request | `/aws/apigateway/<stack_name_base>-api-access` |
| A data load | `/aws/codebuild/ledgerlens-data-load` and the Step Functions execution |
| How models and prompts compare | The `LedgerLens-Evaluation` dashboard |

## Evaluation dashboard

`python -m evals.cw_dashboard <run folders> --apply` (`evals/cw_dashboard.py`) publishes the evaluation results as custom metrics in `LedgerLens/Eval` and rewrites the `LedgerLens-Evaluation` dashboard. Besides the evaluation numbers, it charts live AWS metrics:
- Cedar denies (`AWS/Bedrock-AgentCore`);
- Bedrock tokens and latency per model (`AWS/Bedrock`);
- guardrail interventions (`AWS/Bedrock/Guardrails`);
- Gateway invocations;
- tool Lambda errors.

It also shows Logs Insights rows from the runtime log group. See the "CloudWatch dashboard" section of [evals/README.md](../evals/README.md).

## Optional: companion telemetry stacks

The solution template LedgerLens started from points to two standalone CloudFormation samples. Nothing in this repo deploys them.

| Solution | What it adds | Guide |
|---|---|---|
| AgentCore telemetry enablement | Region-wide telemetry rules: CloudWatch logs and X-Ray traces for AgentCore Runtime, Gateway, Memory, Code Interpreter, Browser and Workload Identity | [AgentCore Telemetry Enablement](AGENTCORE_TELEMETRY.md) |
| Bedrock model invocation logging | The prompts, completions and metadata of every Bedrock model call, to S3 and CloudWatch Logs | [Bedrock Model Invocation Logging](BEDROCK_MODEL_INVOCATION_LOGGING.md) |

- The telemetry stack needs Transaction Search and CloudWatch telemetry resource discovery turned on first.
- Model invocation logs would hold the agent's full prompts. Those include the customer's cards and transactions, and the guardrail masks nothing, so treat that log destination as sensitive.
- Both are proof-of-value samples, not production-ready. Review them against the AWS Shared Responsibility Model before using them in production.
