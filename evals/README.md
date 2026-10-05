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
