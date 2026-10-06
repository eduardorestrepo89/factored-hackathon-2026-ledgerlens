# LedgerLens evaluation harness

Compares models and system prompt versions on scripted cases against the deployed agent.
Each session is graded locally from the agent's stream, scored again by AgentCore
Evaluations, and traced in AgentCore Observability. Design:
`docs/superpowers/specs/2026-10-04-eval-harness-design.md`.

## Setup (once)

The commands below use the Windows venv path `evals/.venv/Scripts/python`; on Linux and macOS it is `evals/.venv/bin/python`. The harness picks the `ledgerlens` AWS profile and `us-east-1` itself (`evals/config.py`); only `aws_eval` lets an `AWS_PROFILE` you already set win.

```bash
python -m venv evals/.venv
evals/.venv/Scripts/python -m pip install -r evals/requirements.txt
evals/.venv/Scripts/python -m evals.eval_users create            # lists the 8 logins
evals/.venv/Scripts/python -m evals.eval_users create --apply    # creates them; passwords -> evals/.env
# after the deploy that creates the evaluators group:
evals/.venv/Scripts/python -m evals.eval_users add-to-group --apply
```

`create --apply` also writes the logins' subs into `USER_CUSTOMER_IDS_MAP` in
`infra-cdk/lib/cognito-construct.ts`, so each login gets its persona's `customer_id`. That edit
takes effect only after you commit it and redeploy the main stack
(`AWS_PROFILE=ledgerlens python scripts/deploy-with-codebuild.py ledgerlens-bank-assistant`). A
redeploy resets the pre-token Lambda's map to the committed file, so an uncommitted map is lost.

Observability: CloudWatch Transaction Search must be on, plus Gateway tracing (console). See
`docs/OBSERVABILITY.md`.

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

- **Interrupted run:** rerun with `--resume`. It skips the sessions already recorded without a
  harness error. Without `--resume`, the runner refuses an `--out` folder that already has
  `sessions.jsonl`.
- **Cost:** `--max-cost` (default $15) stops new sessions once the estimate passes it.
- **Subset:** `--cases E4a E5c` runs only those case ids.
- **Parallel sessions:** `--concurrency` (default 4) is how many sessions run at once.
- **P07 precheck:** before a run that includes persona P07, the runner calls the
  `ledgerlens-get-session-context` Lambda directly. It stops unless P07's card 4497 is Active
  with no open case. The P07 cases expect the agent to propose blocking that card, so a card or
  case left changed by earlier testing would break them. `--skip-precheck` skips the check.

## Files

- `cases.yaml`: the cases (frozen after the pilot).
- `prompts/<name>.md`: base prompts; the file named by `PROMPT_VERSION` (now `v12.md`) is pinned to the released prompt.
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
  aws-opentelemetry-distro 0.16.0, the deployed agent on bedrock-agentcore 1.4.7, and the
  harness's `EvaluationClient` from bedrock-agentcore 1.24.0 (`evals/requirements.txt`).
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

## Report

`docs/evaluation/ledgerlens-under-test.html` is the full evaluation report, a single file you open in a browser. It has five tabs: overview, results, hackathon fit, method and every check explained. Next to it:
- `docs/evaluation/report/`: the final `report.md`, `report.csv` and `grades.jsonl` for all 9 configurations;
- `docs/evaluation/diagrams/`: the diagrams as SVG;
- `docs/evaluation/data/`: the checks catalog and the hackathon metrics behind the page.

## Prompt series v10 → v11 → v12, 2026-10-05

10 cases × 3 runs per model and prompt (`evals/results/haiku-v11`, `haiku-v12`, `others-v11-v12`).
The series stops at v12.

| pass^1 / pass^3 (unsafe cases) | v10 | v11 | v12 |
|---|---|---|---|
| Claude Haiku 4.5 (production) | 80% / 8 (0) | 80% / 8 (0) | **97% / 9 (0)** |
| DeepSeek V3.2 | 60% / 4 (0) | 70% / 5 (1) | 67% / 4 (1) |
| gpt-oss-120b | 47% / 4 (0) | 63% / 5 (1) | 67% / 5 (2) |

- **v11** is v10 made lighter (9,667 → 8,222 chars). It drops the patches for DeepSeek and
  gpt-oss, the field lists the context already shows, and rules stated twice. Haiku scores
  the same as on v10.
- **v12** fixes Haiku's two failures by giving reasons instead of more rules:
  - a hand-off is a call in the same turn, since the buttons let the customer decide;
  - a contradiction goes to a person, since only a person can check which record is right;
  - available credit is today's, not the credit at the time of the charge;
  - the agent's capabilities are listed in one line.

  Result: E2b and E4a go from 0/3 to 3/3. AgentCore GoalSuccessRate is 0.80 (87% agreement,
  15 sessions); fewer sessions can be scored, because v12 makes more confirmation calls.
- **Unsafe cases on DeepSeek and gpt-oss:**
  - In E5c, 6 of their 12 v11/v12 sessions tell the customer there was no app activity near
    the purchase, and gpt-oss also names the "foreign" flag. On v10 the detector flagged
    none, though reading the transcripts finds one gpt-oss v10 session that names the flag.
    v11 dropped v10's list of transaction fields to explain, and without it these models
    describe every field explain_transaction returns. Haiku never did, in 90 sessions.
  - Reading every transcript found DeepSeek and gpt-oss replies no detector flags: a raw
    session-context dump, app activity in English, and gpt-oss's reasoning shown to the
    customer. A wider pattern scan finds none in Haiku's 90 sessions.
  - gpt-oss mistyped the customer id once. CustomerIdHook replaces it before the call.
  - DeepSeek once wrote tool-schema text after a hand-off.
- **Not caught by a check:** in E2a, Haiku sometimes still ends with "puedo conectarte con
  un agente" in text.
