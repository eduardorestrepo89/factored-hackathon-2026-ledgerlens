# LedgerLens evaluation harness

Compares models and system prompt versions on scripted cases against the deployed agent.
Each session is graded locally from the agent's stream, scored again by AgentCore
Evaluations, and traced in AgentCore Observability. Design:
`docs/superpowers/specs/2026-10-04-eval-harness-design.md`.

## Setup (once)

```bash
python -m venv evals/.venv
evals/.venv/Scripts/python -m pip install -r evals/requirements.txt
evals/.venv/Scripts/python -m evals.eval_users create            # lists the 8 logins
evals/.venv/Scripts/python -m evals.eval_users create --apply    # creates them; passwords -> evals/.env
# after the deploy that creates the evaluators group:
evals/.venv/Scripts/python -m evals.eval_users add-to-group --apply
```

Observability: CloudWatch Transaction Search must be on, plus Gateway tracing (console).

## Run

Run from the repo root.

```bash
PY=evals/.venv/Scripts/python
$PY -m evals.runner --models deepseek.v3.2 openai.gpt-oss-120b-1:0 --prompts v10 --runs 3 \
    --out evals/results/baseline-v10 --dry-run          # job list and cost estimate
$PY -m evals.runner --models deepseek.v3.2 openai.gpt-oss-120b-1:0 --prompts v10 --runs 3 \
    --out evals/results/baseline-v10
AWS_PROFILE=ledgerlens $PY -m evals.aws_eval evals/results/baseline-v10
$PY -m evals.report evals/results/baseline-v10 --out evals/results/report
```

- **Interrupted run:** rerun with `--resume`.
- **Cost:** `--max-cost` (default $15) stops new sessions once the estimate passes it.

## Files

- `cases.yaml`: the cases (frozen after the pilot).
- `prompts/<name>.md`: base prompts; `v10.md` is pinned to the released prompt.
- `graders.py`: the checks.
- `results/<run>/`:
  - `sessions.jsonl`, `run.json`, `aws_eval.jsonl` per run;
  - `report.md`, `report.csv` and `grades.jsonl` from `report.py`.

## Rules

- No case may click Yes on `block_credit_card` or `open_claim`; the loader refuses it.
- Never edit the pre-token Lambda's `USER_CUSTOMER_IDS_MAP` during a run.

## Observed on 2026-10-05 (smoke test, 6 sessions, v10)

- Transaction Search on: each session's spans land in `aws/spans`. Strands spans (`invoke_agent`,
  `chat`, `execute_event_loop_cycle`, `execute_tool`) carry `model.id` and `prompt.version`
  (`v10-0085ea98`); tool spans are named `gateway_<target>___<tool>`.
- A confirmed tool shows two `execute_tool` spans: the call paused at the confirmation, then the
  executed one after the click.
- Gateway tracing (vended delivery `ledgerlens-gateway-traces` → X-Ray) adds
  `AgentCore.Policy.AuthorizeAction` and `AgentCore.Gateway.InvokeTool` spans with
  `attributes.aws.agentcore.policy.authorization_decision`.
- AgentCore Evaluations scores read-only sessions, but every session with a confirmation
  (interrupt) returns `errorCode: SpanEventParsingException` for both built-ins. Confirmation
  cases (E1a, E1b, E2b, E4a, E4b) are therefore graded locally only.
- `GoalSuccessRate` passed a gpt-oss E2a reply that said "el código 51"; the local grader failed
  it. The AWS judge corroborates; it does not decide.
- Real usage: about 5-10K input tokens per request; the 6 sessions cost $0.02.

## CloudWatch dashboard

```bash
evals/.venv/Scripts/python -m evals.cw_dashboard evals/results/baseline-v10 evals/results/haiku-v10          # print
evals/.venv/Scripts/python -m evals.cw_dashboard evals/results/baseline-v10 evals/results/haiku-v10 --apply  # publish
```

Publishes the numbers behind `report.md` plus the metric families in `evals/metrics.py` (research:
`datathon/reports/LedgerLens dashboard metrics.md`) as custom metrics in `LedgerLens/Eval`, and rewrites
the `LedgerLens-Evaluation` dashboard:

- **Dimensions:** `Model`, `Prompt` (name + content hash, the id the spans carry as `prompt.version`),
  `Run` (the run folder), and at most one extra dimension per family (`Check`, `Evaluation`,
  `DefectType`, `ErrorType`, `Cause`, `Evaluator`, `UnsafeType`, `Kind`). Data is stamped at publish
  time. About 150 data points per model.
- **Rows:** business tiles (safe automated resolution, unsafe cases with the 3/n bound, cost per case
  passing every run); where it fails (pass rate by evaluation, failure rate per check); confirmation
  quality; tool quality; reliability (pass@k, Wilson band, flaky and always-failing cases, AgentCore
  coverage); efficiency (p50/p95 latency from raw values, tokens, cost); safety (unsafe hits with their
  opportunities); live AWS metrics; live log rows; history.
- **Live AWS metrics:** Cedar `AuthorizeAction` denies on the current gateway, Bedrock tokens and latency
  per model, guardrail interventions, Gateway invocations, tool Lambda errors.
- **Live log rows (Logs Insights):** they read only the `runtime-logs` streams, since every line is also
  in `otel-rt-logs`. They show sessions per model × prompt, consent clicks, agent failures and
  overwrites, handled tool errors, and hand-offs by priority.
- **History:** a copy of pass^1/pass^k without the `Run` dimension, one point per publish, so a model's
  line runs across prompt versions.
- **Timing:** new metric names take a few minutes to become visible to `SEARCH`, so the per-check and
  per-evaluation charts fill in shortly after the first publish.

## Known AWS limitation: confirmation sessions can't be scored by AgentCore Evaluations

- **What:** every session with a Yes/No confirmation fails both built-ins (`GoalSuccessRate`,
  `TrajectoryInOrderMatch`) with `errorCode: SpanEventParsingException`. Read-only sessions score
  normally. Seen on 2026-10-05 with strands-agents 1.32.0, the custom `ConfirmationHook`
  (`agent/ledgerlens/tools/confirmation_hook.py`, a `BeforeToolCallEvent.interrupt()`),
  aws-opentelemetry-distro 0.16.0 and bedrock-agentcore 1.24.0.
- **Likely cause:** an interrupted tool call leaves an `execute_tool` span without a result, and
  the resumed call adds a second one; the evaluators' span parser rejects that shape.
- **Effect:** E1a, E1b, E2b, E4a and E4b are graded locally only; the dashboard header says so.
- **Recheck after upgrading Strands** (planned 1.32 → 1.57.2, see
  `docs/handoffs/2026-10-04-confirmation-buttons-frontend.md`), including with Strands' built-in
  `HumanInTheLoop` interrupts:
  1. deploy the upgraded agent;
  2. `python -m evals.runner --models deepseek.v3.2 --prompts v10 --runs 1 --cases E4a --out evals/results/hitl-check`;
  3. `AWS_PROFILE=ledgerlens python -m evals.aws_eval evals/results/hitl-check`;
  4. scores instead of `SpanEventParsingException` mean the limitation is gone.
- **Other routes if it stays:** a code-based evaluator (a Lambda reading the spans, deferred in the
  spec), trace-level evaluation of the traces without an interrupt, or an AWS support case.

## Model decision, 2026-10-05

Prompt v10, 10 cases × 3 runs per model (`evals/results/baseline-v10`, `evals/results/haiku-v10`):

| | DeepSeek V3.2 | Claude Haiku 4.5 | gpt-oss-120b |
|---|---|---|---|
| pass^1 | 60% | **80%** | 47% |
| pass^3 | 4/10 (17-69%) | **8/10 (49-94%)** | 4/10 (17-69%) |
| bare tool names ("Unknown tool" after a Yes) | 3 | 0 | 1 |
| malformed arguments (string arrays, enum values outside the spec) | 5 | 0 | 0 |
| write proposals without text | 3 of 18 | 0 of 12 | 20 of 22 |
| model cost for 30 sessions | $0.27 | $0.55 | $0.08 |

The production `model_id` moved from `deepseek.v3.2` to `global.anthropic.claude-haiku-4-5-20251001-v1:0`.
Haiku's remaining failure (E2b, E4a) is offering a person in text instead of calling the hand-off.
