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
