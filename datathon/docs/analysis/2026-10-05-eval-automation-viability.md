# Running the LedgerLens evaluation automatically: viability and a recommended design

**Date:** 2026-10-05 (submission day). **Branch read:** `feat/eval-resume`. **Scope:** a desk study. No AWS API was called, nothing was deployed, and no repo file was edited.
**Inputs:** `evals/*.py`, `evals/README.md`, the harness spec (`docs/superpowers/specs/2026-10-04-eval-harness-design.md`), the run outputs in `evals/results/`, `scripts/deploy-with-codebuild.py`, `infra-cdk/lib/{data,backend,cognito}-construct.ts`, `.github/workflows/`, the installed `bedrock-agentcore==1.24.0` SDK source, and the AWS and GitHub docs listed at the end.

---

## 1. Summary and recommendation

**Verdict per option**

| Option | Viable? | One-line reason |
|---|---|---|
| Lambda alone (one function runs the whole thing) | **No** | A 60-session run takes about 13.5 min end to end, which is 90% of Lambda's 900 s ceiling. A 120-session run takes about 22 min. |
| Step Functions + Lambda fan-out (one Lambda per session) | Yes, but over-built | Every piece fits the limits. But it needs a rewrite of persistence (S3 instead of JSONL) and of the cost guard, plus 4 handlers and the ASL, for parallelism the run can't use (Bedrock quotas, demo traffic). |
| **CodeBuild running the existing CLI** | **Yes: recommended** | The same commands as the laptop, in a container with an IAM role. It needs about 4 small code changes and one small CDK stack, and costs about $0.05 of compute per run. |
| GitHub Actions + OIDC | Yes, with caveats | Technically fine. But the repo is **public** (logs and artifacts are world-readable), the user has WRITE rather than admin (secrets, environments and branch rules need the owner), schedules run only on `main`, and a PR-time run measures the *deployed* agent, not the PR. |

**Recommendation for after the hackathon:**

- **What it is:** a CodeBuild project, `ledgerlens-eval`, in its **own** CDK stack (`ledgerlens-bank-assistant-eval`), modelled on `ledgerlens-data-load`.
- **What it runs:** `runner → aws_eval → report → cw_dashboard → gate`, almost unchanged. Passwords come from Secrets Manager, and results are synced to an S3 bucket.
- **Triggers:**
  1. **Manual:** `aws codebuild start-build`, or a tiny wrapper script.
  2. **Post-deploy smoke:** an EventBridge rule on `CloudFormation Stack Status Change` = `UPDATE_COMPLETE` for the main stack. It runs a 10-session subset.
  3. **Weekly full baseline:** EventBridge Scheduler, with a start date after judging.
- **On failure:** a failed build publishes to SNS (email).
- **Phase 2:** a GitHub Actions workflow assumes an OIDC role that can only *start* that CodeBuild build. It runs on PRs that touch `evals/prompts/**` and posts aggregate numbers to the PR. AWS permissions, secrets and transcripts stay inside the account.

**Gate rules:**

- **Hard fail:**
  - `unsafe_cases > 0`;
  - any harness error after the built-in retry;
  - an `eval override rejected`;
  - a failed P07 precheck.
- **Pass rates are reported, not gated.** With 10 cases, the baseline's pass^3 interval is 17–69% (`evals/results/report-v10/report.md`), so a pass-rate threshold would be noise.

**By the 2026-10-05 submission (today):**

- **Deploy nothing.** The judged deployment must stay untouched: judging runs 2026-10-06 to 10-15, and the rule is deploy-after-review.
- **A main-stack redeploy also resets** any console-edited demo persona in `USER_CUSTOMER_IDS_MAP` (cognito-construct.ts:151-154).
- **Feasible today without risk:**
  - this note;
  - a "roadmap: automated evaluation in CodeBuild" line in the pitch or README;
  - optionally, adding the existing eval unit tests (`tests/unit/eval_harness/`, no AWS needed) to `python-lint.yml`, which today runs only ruff.
- **The code changes in section 8** can be written and unit-tested in about half a day. They aren't needed for the submission.
- **Infra and the first cloud run** come after 2026-10-15.

---

## 2. What a run actually does (measured and read from code)

### 2.1 Timings from `evals/results/baseline-v10` (60 sessions, 2 models × 10 cases × 3 runs, v10, concurrency 4)

| Phase | Evidence | Duration |
|---|---|---|
| Sessions | `run.json` written 00:12:41, last `sessions.jsonl` write 00:16:22 | **3 min 41 s** |
| Span-ingestion wait | `aws_eval.INGESTION_WAIT_S = 300`, measured from the `sessions.jsonl` mtime | **5 min** |
| AgentCore Evaluations, serial, 60 calls | last `aws_eval.jsonl` write 00:26:08 | **about 4 min 46 s**, about 4.8 s per session |
| Report | `report-v10/*` written 00:26:16 | seconds |
| **Total** | | **about 13.5 min** |

**Per session** (sum of request latencies):
- min 5.1 s, median 10.8 s, p90 25.4 s, max 32.4 s;
- 1–5 requests per session (median 2), longest single request 19.3 s;
- 124 requests, **0 throttled**;
- 854,701 input and 26,904 output tokens in total, so **$0.348 of model tokens** (`config.session_cost`).

The pilot (20 sessions) and smoke (6) runs agree: medians 13.2 s and 9.1 s, no throttling.

**AgentCore results:**
- 28 of the 60 sessions contain a confirmation.
- 52 evaluator results came back `SpanEventParsingException`: the known interrupt-span limitation in `evals/README.md`.
- So the AWS scores cover only the read-only sessions.

**Extrapolation to 120 sessions** (e.g. v10 + v11):
- sessions about 7.4 min at concurrency 4;
- 5 min wait;
- evaluation about 9.5 min serial, or about 2.5 min with 4 threads;
- so **about 15–22 min** in total.

**State payload size:** `sessions.jsonl` is 164,450 bytes for 60 sessions, about 2.7 KB each. A 120-session run would pass Step Functions' 256 KiB payload limit if the records travelled inline.

### 2.2 What `EvaluationClient.run` calls (bedrock-agentcore 1.24.0 source)

`bedrock_agentcore/evaluation/client.py:141-240` and `utils/cloudwatch_span_helper.py`:

1. `bedrock-agentcore-control:GetEvaluator`, to read each evaluator's level. It is cached, and **falls back to SESSION silently if denied**.
2. Two CloudWatch Logs Insights queries, `StartQuery` then a `GetQueryResults` poll:
   - one on `aws/spans`;
   - one on `/aws/bedrock-agentcore/runtimes/<agentId>-DEFAULT`;
   - each over a **7-day look-back** by default, polling up to 60 s for spans.
3. `bedrock-agentcore:Evaluate`, once per evaluator, batched by 10 targets.

**Consequences:**
- The evaluation step must be code: the SDK's span shaping isn't reproducible in ASL.
- Two Insights queries per session count against the account's 100 concurrent Insights queries, which also covers dashboard widgets.
- Passing `look_back_time=timedelta(hours=6)` would cut the bytes scanned. Today's scan volume is unmeasured.

**The SDK also has `StartBatchEvaluation` / `GetBatchEvaluation`** (botocore 1.43.108 model; `runner/batch/batch_evaluation_runner.py`):
- one asynchronous job over up to 500 session ids;
- inline ground truth per session (`assertions`, `expectedTrajectory`);
- output to CloudWatch Logs, with an optional metrics namespace.

The SDK docstrings mark it **preview**. Quotas:
- 5 active jobs per account;
- 500 sessions per job;
- 10 evaluators per job;
- Start at 3 TPS.

It is priced at **$1.80 / $9 per M judge tokens**, against $2.40 / $12 on demand. It could replace the serial loop later, but `report.py` would then need a reader for the per-session output log stream.

### 2.3 Auth constraints that rule out shortcuts

- **The runtime authorizer is JWT-only.** `RuntimeAuthorizerConfiguration.usingJWT(discoveryUrl, [userPoolClientId])` is in backend-construct.ts:241-245.
- **The SDK's `InvokeAgentRuntime` can't be used.** AWS's own comparison says JWT bearer calls need "HTTPS requests required, not managed by AWS SDKs". So `boto3` `InvokeAgentRuntime` (SigV4) and the Step Functions `aws-sdk:bedrockagentcore:invokeAgentRuntime` integration can't drive these sessions.
- **The Step Functions HTTP Task can't either.** It can't do a Cognito password grant or consume a multi-minute SSE stream.
- **So session driving must be Python code:** Lambda, CodeBuild or a GitHub runner.
- **Tokens must be user tokens.** The pre-token Lambda maps a **user** sub to a persona. A `client_credentials` (M2M) token has no persona, and is not in the runtime's `allowedClients` anyway. So the eval logins and their passwords stay. The AWS blog's M2M pattern does not apply here.
- **`cognito-idp:InitiateAuth` is an unauthenticated operation.** It needs no IAM permission (Cognito developer guide, "Unauthenticated user operations").

### 2.4 What stops the harness running unattended today (code facts)

1. **Fixed profile.** `config.aws_session()` hard-codes `boto3.Session(profile_name="ledgerlens")`. A container, Lambda or runner has no such profile: `ProfileNotFound`.
2. **Profile forced in `aws_eval`.** `aws_eval.main()` does `os.environ.setdefault("AWS_PROFILE", "ledgerlens")` before building `EvaluationClient`. Same failure.
3. **Passwords from a local file.** They come only from `evals/.env` (`config.read_env`); the runner exits via `parser.error` if any is missing.
4. **Local results only.** Results go only to local `evals/results/<run>/`, and the runner refuses an existing `sessions.jsonl` without `--resume`.
5. **One fixed dashboard.** `cw_dashboard` always rewrites `LedgerLens-Evaluation`, the pitch dashboard. The `Run` dimension is the folder names, so unique folder names give a new series per run and no trend line.
6. **No gate command.** `runner` exits 0, 1 (precheck) or 2 (override rejected), but nothing turns the report into pass/fail.

---

## 3. Option A: Lambda alone

| Question | Finding |
|---|---|
| 15-minute limit | The whole pipeline is about 13.5 min for 60 sessions and about 22 min for 120 (2.1). The sessions alone (3.7 min for 60) fit. Session + wait + evaluate does not fit with margin, and the 300 s wait would be paid compute. **Infeasible as one function.** |
| Package size | `evals/.venv/Lib/site-packages` is 65 MB, of which pip is 13 MB and botocore 25 MB. So the package is about 52 MB unzipped with boto3 vendored: well under the 250 MB zip limit. The heaviest parts are pydantic_core (5.3 MB, compiled), pydantic (3.9 MB) and bedrock_agentcore (3.4 MB). Vendor boto3, since the managed runtime's copy may lag the AgentCore Evaluations APIs. |
| SSE | No issue. Lambda is only an HTTP **client** reading a streamed response (`httpx.stream`). Lambda response streaming is irrelevant. The function must **not** join the tools VPC, which has no NAT or route out (data-construct.ts:51-52). Outside a VPC, egress to the Cognito and AgentCore endpoints works. |
| Cold start | Not measured. The imports (boto3, pydantic, httpx) are on the order of 1–3 s, which is negligible against 5–32 s sessions. |
| Lambda durable functions | They lift the total-duration limit: checkpointed steps, free waits of up to a year, but still 15 min per invocation. Python is supported. It is a newer programming model (replay semantics) that the team hasn't used. It is not worth it for a 15-minute batch. |

---

## 4. Option B: Step Functions + per-session Lambda fan-out

**Shape (Standard workflow):**

1. **Freeze check:** `aws-sdk:ssm:getParameter`, then a Choice.
2. **`Plan` Lambda:**
   - runs the P07 precheck;
   - builds the matrix and the cost estimate;
   - writes `run.json` to S3;
   - returns about 60–120 small item keys.
3. **Inline `Map`, `MaxConcurrency` 4** (Inline allows up to 40). Each item calls the **`Session` Lambda**, with a timeout of 300–900 s, which:
   - runs `run_with_retry(case, key, payload, send)`;
   - writes `s3://…/runs/<run>/sessions/<key>.json`;
   - returns `{key, session_id, harness_error, cost}`.
4. **`Wait` 300 s.** No compute charge.
5. **Evaluation**, either:
   - (a) an inline `Map` with `MaxConcurrency` 4 over an **`Eval` Lambda** (`EvaluationClient.run`, about 5 s each), writing `aws_eval/<session>.json`; or
   - (b) `arn:aws:states:::aws-sdk:bedrockagentcore:startBatchEvaluation`, plus a Wait/Choice poll on `getBatchEvaluation`. Both actions are supported: the SDK-integration page lists only `InvokeCodeInterpreter`, `InvokeAgentRuntimeCommand` and `InvokeHarness` as unsupported for Bedrock AgentCore. This path still needs a Lambda to turn the CloudWatch per-session output into `aws_eval.jsonl` rows.
6. **`Report` Lambda:**
   - syncs the S3 prefix to `/tmp/<run>/`, concatenating the per-session objects into `sessions.jsonl` / `aws_eval.jsonl`;
   - calls `report.write_report` and `cw_dashboard.publish` unchanged;
   - uploads `report.md`, `report.csv` and `grades.jsonl`.
7. **Gate:** a Choice, then SNS on failure.

| Question | Finding |
|---|---|
| Fits the limits? | Yes:<br>- the longest session is 32 s;<br>- the history is about 120 items × about 8 events × 2 maps ≈ 2,000 events, under the 25,000 limit;<br>- each item's payload is small once records live in S3;<br>- Standard workflows run up to 1 year. |
| Error handling | Lambda `Retry` on `Lambda.ServiceException`, `Lambda.TooManyRequestsException` and `Lambda.SdkClientException` with backoff. The harness-level retry stays in `run_with_retry`. A `Catch` per item records a harness error and keeps going, so the report counts it as it does today. |
| What gets worse | - **Cost guard:** `CostGuard` is in-process shared state, and a fan-out loses it. Replace it with a pre-run estimate check in `Plan` (the dry-run estimate exists), or a DynamoDB counter.<br>- **Persistence:** `sessions.jsonl` append, `--resume` and `done_keys` all become S3 listing logic.<br>- **Code to maintain:** four handlers plus ASL. |
| What gets better | Per-session visibility in the console. A concurrency that could go to 40, but shouldn't: shared Bedrock quotas and demo traffic. A natural place for the batch-evaluation API. |
| Cost per 60-session run | About 400 state transitions × $0.025/1k ≈ $0.01. Lambda: about 425 GB-s for sessions at 512 MB, plus about 60 × 5 s for eval ≈ $0.01. **About $0.02.** |

**Verdict:** viable, but it optimises the part that isn't slow. Of the 13.5 min, 9.8 is the fixed wait plus evaluation; session execution is 3.7. Revisit it only if runs grow past several hundred sessions, or when moving evaluation to the batch API.

**A cheaper hybrid exists** if Step Functions is wanted for consistency: mirror `ledgerlens-data-pipeline` exactly. That means `tasks.CodeBuildStartBuild` (RUN_JOB) for a `run` stage, then a `Wait` 300 s, then CodeBuild `evaluate`, then CodeBuild `report`, all one project with a `STAGE` variable (data-construct.ts:229-252). It saves only about $0.02 of CodeBuild wait time, so it is optional.

---

## 5. Option C: CodeBuild running the existing CLI (recommended)

| Question | Finding |
|---|---|
| Fit | The build timeout runs from 5 to 2,160 minutes (36 h). The runs take 15–25 min. Set `timeout: 120 min` and `concurrentBuildLimit: 1`: a second trigger queues instead of overlapping, the same pattern as data-load. |
| Image | `LinuxArmBuildImage.AMAZON_LINUX_2_STANDARD_3_0` with Python 3.12, the same as data-load. The work is I/O-bound (HTTP streams, sleeps), so **`ComputeType.SMALL`** is enough (arm1.small, 2 vCPU / 3 GB). |
| Source | An `s3assets.Asset` of `evals/`, as data-load does with `data_load/`:<br>- **exclude `.env`, `.venv`, `results`, `__pycache__`**, or the passwords would be uploaded to the CDK assets bucket;<br>- the harness version then equals the deployed eval stack;<br>- for prompt PRs (phase 2), an anonymous shallow `git clone` of the public repo at a given ref works in the buildspec. |
| Triggers | 1. **Manual:** `aws codebuild start-build --project-name ledgerlens-eval [--environment-variables-override …]`.<br>2. **After a deploy:** an EventBridge rule, `source aws.cloudformation`, `detail-type "CloudFormation Stack Status Change"`, status `UPDATE_COMPLETE`, stack-id prefix of the main stack. The target is the project, with `EVAL_PROFILE=smoke`. A rule is needed because deploys are laptop-driven (`deploy-with-codebuild.py`) and there's no CodePipeline to hook into.<br>3. **Schedule:** EventBridge Scheduler (the universal target `aws-sdk:codebuild:startBuild`) or an EventBridge schedule rule.<br>4. **Failure alerts:** an EventBridge rule on `CodeBuild Build State Change` = `FAILED` for this project, sending to SNS email. |
| Post-deploy caveat | The runtime returns `424 Failed Dependency` until it is READY after a deploy (AWS blog, "Lessons from testing"). Add a readiness poll (`bedrock-agentcore-control:GetAgentRuntime` until READY) before the smoke run. |
| Buildspec sketch | **install:** `pip install -r evals/requirements.txt` and the package-dir copy trick from data-load.<br>**pre_build:** `python -m evals.ci preflight`: account-ID guard, freeze flag, runtime READY.<br>**build:**<br>- `python -m evals.runner $MATRIX --out evals/results/$RUN_LABEL`<br>- `python -m evals.aws_eval evals/results/$RUN_LABEL`<br>- `python -m evals.report … --out …/report`<br>- `python -m evals.cw_dashboard … --apply --dashboard LedgerLens-Evaluation-Auto`<br>- `python -m evals.gate …/report/grades.jsonl`<br>**post_build:** `aws s3 sync evals/results/ s3://$RESULTS_BUCKET/runs/$CODEBUILD_BUILD_NUMBER/`. A non-zero exit fails the build, so a precheck failure fails the build before any session. |
| Cost per run | About 16–18 min including install × $0.0034/min (arm1.small) ≈ **$0.06**. The free tier is 100 min/month on small, about 6 runs. |
| Effort | About 1–1.5 days (section 8). |

**Why it wins:**
- It is the laptop workflow, verified on 2026-10-05, with three credential and storage tweaks.
- The 300 s wait, `--resume`, `CostGuard`, the P07 precheck and the Yes-on-writes loader guard all keep working as written.
- The team already operates two CodeBuild-based automations: the deploy script and data-load.

---

## 6. Option D: GitHub Actions (direct)

| Question | Finding |
|---|---|
| AWS access | OIDC: `permissions: id-token: write`; an IAM OIDC provider at `https://token.actions.githubusercontent.com` with audience `sts.amazonaws.com`; a trust policy on `token.actions.githubusercontent.com:sub`; then `aws-actions/configure-aws-credentials`. The role ARN isn't secret, so with passwords in Secrets Manager **no GitHub secret is needed at all**. |
| Repo facts (`gh repo view`, 2026-10-05) | - The repo `eduardorestrepo89/ledgerlens-bank-assistant` is **PUBLIC**, with default branch `main`.<br>- The user's permission is **WRITE**: creating environments, repository secrets or branch protection needs the owner.<br>- The current workflows run only on push and PR to `main` (lint and ASH security). There is no `stage` trigger, no AWS access and no pytest. |
| Public-repo consequences | - Action logs and artifacts are readable by anyone.<br>- `sessions.jsonl` holds per-persona transcripts (names, card last4, amounts) derived from organizer data, so **never upload results as artifacts and never print transcripts**. Post only the aggregate table.<br>- Fork PRs get no secrets and a read-only token, so they can't assume the role. Keep it that way: no `pull_request_target`. |
| Limits | 6 h per job on GitHub-hosted runners. Standard runners are free for public repos. **Scheduled workflows run only on the default branch (`main`)**, and in public repos they are auto-disabled after 60 days without activity. |
| PR to `stage` vs nightly | - **A PR-time run measures the deployed agent, not the PR's code.** Deploys are manual, from a laptop.<br>- PR gating is meaningful only for **prompt** changes: `evals/prompts/vNN.md` travels in the `eval` override and needs no deploy.<br>- Agent, tool or infra changes can only be evaluated after deploy, which is the post-deploy trigger in Option C. |
| Merge gating | A required status check on `stage` (owner sets branch protection).<br>**Hard-fail:**<br>- `unsafe_cases > 0`;<br>- a harness error after retry;<br>- override rejected;<br>- a precheck failure.<br>**Soft and reported:** pass^1 and pass^k against the baseline, and `report.regressions(...)` when two prompts run together.<br>Don't gate on pass rates: 10 cases, LLM variance, and the AWS blog itself warns about judge variance. |
| Token cost per PR | Model tokens are $0.35 per 60 sessions (measured). The full per-run cost is about $1.5–3 (section 9), so prefer a **10-session smoke** (1 model, 1 run, all cases): about $0.25–0.5 per PR. |
| Security of PR code | A same-repo PR job runs PR code with the eval role. A PR could edit the `cases.py` guard (`YES_ALLOWED`) and click Yes on `block_credit_card`. Mitigations:<br>- run the harness from `stage` and fetch only the PR's prompt file;<br>- **server-side**, add a Cedar `forbid` on the write tools for evaluator principals. The pre-token Lambda already emits a `role` claim from `USER_ROLE_MAP`, so map the eval subs to `role: "evaluator"`. Current cases never execute writes, because the No path interrupts before the Gateway call, so this costs nothing and makes the no-Yes-on-writes rule enforced by AWS, not by the harness. |

**Hybrid (phase 2 of the recommendation):**
- The workflow (`workflow_dispatch`, plus `pull_request` on `paths: evals/prompts/**`, base `stage`) assumes an OIDC role that can only `codebuild:StartBuild` / `BatchGetBuilds` on `ledgerlens-eval` and read its log group.
- It runs `aws-actions/aws-codebuild-run-build`, then comments the aggregate table.
- Credentials, transcripts and the database-facing role never touch GitHub.

**Alternative:** CodeBuild-hosted GitHub Actions runners give the same in-account execution. They need a CodeConnections GitHub app installed on the repo, which is again the owner's job.

---

## 7. Comparison

| | A: Lambda only | B: Step Functions + Lambda | **C: CodeBuild** | D: GitHub Actions direct | C + D hybrid |
|---|---|---|---|---|---|
| Fits time limits | No (13.5–22 min vs 15 min) | Yes | Yes (36 h max) | Yes (6 h max) | Yes |
| Code reuse | Low | Low: persistence, guard and resume rewritten | **High: CLI unchanged** except 4 small changes | High | High |
| Cost guard / resume / precheck | Lost | Must be redesigned | **Kept** | Kept | Kept |
| Where secrets live | Secrets Manager | Secrets Manager | Secrets Manager | Secrets Manager via OIDC role | Secrets Manager |
| Transcript exposure | In-account | In-account | In-account (S3, CW Logs) | **Public logs and artifacts risk** | In-account; aggregates on PR |
| Post-deploy trigger | EventBridge | EventBridge | EventBridge | Not natural (deploys are local) | EventBridge (C) |
| PR gating | No | No | No | Yes (prompt PRs only) | Yes (prompt PRs only) |
| Needs repo-owner action | No | No | No | Yes (branch rules, environments) | Yes (branch rules) |
| Orchestration cost per 60-session run | n/a | ≈ $0.02 | ≈ $0.06 | $0 (public repo) | ≈ $0.06 |
| Effort | n/a | 3–4 days | **1–1.5 days** | 1–1.5 days + owner | C + 0.5–1 day |

---

## 8. Code and infra changes needed

### 8.1 Python (needed by B, C and D), each with unit tests in `tests/unit/eval_harness/`

1. **Credentials:**
   - `config.aws_session()` uses the default credential chain when `EVAL_AWS_PROFILE` is set to empty; on the laptop the default stays `ledgerlens`;
   - `aws_eval` gets the same switch instead of `setdefault("AWS_PROFILE", …)`;
   - add an **account guard**: `sts.get_caller_identity()["Account"] == "704650059996"`, else exit. The project memory records a run that landed in the default-profile account, which was then wiped. About 15 lines.
2. **Passwords:** when `EVAL_PASSWORDS_SECRET_ID` is set, read `{"EVAL_PASSWORD_P01": …}` from Secrets Manager instead of `evals/.env`. Add `eval_users create --to-secret` (or one manual `put-secret-value`) to seed it from the existing `.env`. About 20 lines.
3. **Dashboard:** `cw_dashboard --dashboard <name>` (default unchanged), so automated runs never overwrite the pitch dashboard. Use a stable `Run` label (e.g. `scheduled`, `post-deploy`) for automated runs so CloudWatch draws a trend. About 5 lines.
4. **Gate:** a new `evals/gate.py`, about 60 lines.
   - It exits non-zero on: unsafe cases, harness errors, override rejected, or an optional hard regression (a case that was 3/3 in the baseline goes 0/3).
   - It prints a Markdown summary for SNS and PR comments.
5. **Preflight**, optional but recommended for unattended runs:
   - a freeze flag (SSM `/ledgerlens/eval/freeze`);
   - a runtime READY poll;
   - a precheck extended to every persona the cases depend on (e.g. P10's card 7718 must stay Blocked), not just P07;
   - `look_back_time=timedelta(hours=6)` in `aws_eval`.
   About 40 lines.
6. **B only:**
   - per-session S3 writes, and an S3-backed `done_keys` / `--resume`;
   - a cost guard in `Plan`;
   - 4 Lambda handlers;
   - `report`/`cw_dashboard` reading from a synced temp dir.
   About 300–400 lines.

### 8.2 Infra (C): a new `infra-cdk/lib/eval-stack.ts`, about 150–200 lines, plus a CDK test

- **A separate stack** keeps eval changes from redeploying the main stack, which would reset `USER_CUSTOMER_IDS_MAP`. The runner keeps reading the main stack outputs through `DescribeStacks`, so no cross-stack references are needed.
- **Resources:**
  - an S3 results bucket: SSE-S3, block public access, `enforceSSL`, 90-day expiry;
  - a `secretsmanager.Secret` `ledgerlens/eval-passwords`, created with a placeholder and set manually, like `ledgerlens/hackathon-s3` (data-construct.ts:146-150);
  - a CodeBuild project with an `s3assets.Asset` of `evals/` and the exclusions above;
  - the scheduler schedule (**start date 2026-10-16**, or created disabled), the post-deploy rule (created **disabled** until after judging), the build-failed rule and an SNS topic.
- **IAM for the CodeBuild role** (least privilege):

| Action | Resource |
|---|---|
| `cloudformation:DescribeStacks` | `arn:aws:cloudformation:us-east-1:704650059996:stack/ledgerlens-bank-assistant/*` |
| `secretsmanager:GetSecretValue` | `…:secret:ledgerlens/eval-passwords-*` |
| `lambda:InvokeFunction` | `…:function:ledgerlens-get-session-context` (plus `ledgerlens-list-credit-cards` if the precheck grows) |
| `bedrock-agentcore:Evaluate`, `bedrock-agentcore:GetEvaluator` | evaluator resources (scope down per the service authorization reference) |
| `bedrock-agentcore:GetAgentRuntime` | the runtime ARN (readiness poll) |
| `logs:StartQuery` | `log-group:aws/spans:*` and `log-group:/aws/bedrock-agentcore/runtimes/<runtimeId>-DEFAULT:*`. The runtime id (today `…-VuhAwlER4L`) changes if the runtime is replaced, so derive it from the construct. |
| `logs:GetQueryResults`, `logs:StopQuery` | `*` |
| `cloudwatch:PutMetricData` | `*`, with condition `cloudwatch:namespace = LedgerLens/Eval` |
| `cloudwatch:PutDashboard` | `arn:aws:cloudwatch::704650059996:dashboard/LedgerLens-Evaluation*` |
| `s3:PutObject`, `s3:GetObject`, `s3:ListBucket` | the results bucket |
| `ssm:GetParameter` | `/ledgerlens/eval/freeze` |

  - **Not needed:** Cognito (`InitiateAuth` is unauthenticated), Bedrock model invoke (the runtime's role does that), DSQL.
  - **Later:** batch evaluation would add `StartBatchEvaluation` / `GetBatchEvaluation`.
- **Phase 2 (hybrid):**
  - an OIDC provider plus a role trusted for `repo:eduardorestrepo89/ledgerlens-bank-assistant:ref:refs/heads/stage` and/or `…:pull_request` (or an `environment:eval` with required reviewers, set by the owner), allowed only `codebuild:StartBuild` / `BatchGetBuilds` and read access to the project's log group and the `report.md` object;
  - a workflow file of about 60 lines.

---

## 9. Effort and cost estimates

**Effort (one developer who knows the repo):**

| Work | Estimate |
|---|---|
| Python changes 8.1 items 1–5, with tests | 0.5 day |
| Eval stack (CDK) plus CDK test, reviewed and deployed with `deploy-with-codebuild.py <stack>-eval` | 0.5 day |
| First cloud run, and a parity check against the laptop baseline (same session shape, pass rates within noise) | 0.25–0.5 day |
| **Option C total** | **about 1–1.5 days** |
| Phase 2 (OIDC role, workflow, PR comment) plus owner setup | +0.5–1 day |
| Option B instead of C | 3–4 days |

**Cost per full 60-session run.** The workload is the same for every option; only the orchestration differs.

| Item | Per run | Basis |
|---|---|---|
| Model tokens | **$0.35** | measured, baseline-v10 |
| AgentCore Evaluations (GoalSuccessRate on about 32 read-only sessions; trajectory has no LLM) | about $0.5–1.5 | **estimate:** $2.40/$12 per M judge tokens × an unmeasured judge input of about 10–20K tokens per session. Check Cost Explorer for 2026-10-05. |
| Runtime, guardrail, memory, Lambda, Logs Insights | about $0.7–1.2 | spec section 10 estimates, scaled to 60 sessions; unmeasured |
| Orchestration | $0.02 (B), $0.06 (C), $0 (D) | section 4 and 5 arithmetic |
| **Total** | **about $1.5–3** | orchestration is under 5% of it |

**Monthly:**

| Cadence | Cost |
|---|---|
| Weekly full run | about $6–13 |
| Nightly full run | about $45–90 |
| Post-deploy smoke (10 sessions) | about $0.25–0.5 each |
| Secrets Manager | $0.40 per month |
| S3 and SNS | negligible |
| Custom metrics | prorated hourly; negligible at this cadence |

The `--max-cost` cap ($15) keeps working in Options C and D.

---

## 10. Data safety and demo concurrency

- **No-Yes-on-writes:**
  - `cases.load_cases` rejects any `answer: yes` on `block_credit_card` or `open_claim` (cases.py:15, 61-62), and every automated option loads the cases the same way;
  - hand-off Yes stays allowed, since it stores and sends nothing, so repeated scheduled runs leave no side effects in DSQL;
  - harden it for unattended and PR-triggered runs with the Cedar evaluator `forbid` (section 6).
- **When the P07 precheck fails** (card 4497 not Active, or an open case):
  - the runner exits 1 before any session: no cost, no grading;
  - the build fails and SNS emails a human.
  - **Never auto-reset.** The only reset is the data pipeline's load stage. It drops and recreates all 13 tables (`data_load/dsql.py:32-37`), takes about 10 minutes, and would wipe whatever a demo did.
  - The human chooses: reload outside judging, or run with `--cases` excluding E1a and E1b, and say so in the report.
  - Likely cause: the demo login is switched to P07 in the Lambda console and someone confirms a block.
- **Other persona states** aren't prechecked today (e.g. P10's 7718 must be Blocked for E4b). Extend the precheck (8.1 item 5).
- **Concurrency with demos:**
  - judging is a window (2026-10-06 to 10-15), not a slot, and judges may open the app at any time;
  - eval sessions share the runtime, Bedrock model quotas (0 throttles at concurrency 4 so far) and the GenAI Observability console;
  - so: **no automated runs during the window**:
    - the schedule's start date is 2026-10-16;
    - the post-deploy rule stays disabled;
    - the freeze flag is checked in preflight;
  - keep concurrency at 4;
  - publish automated runs to `LedgerLens-Evaluation-Auto`, never to the pitch dashboard.
- **Memory:** `use_long_term_memory: false` today. If it is ever enabled, eval logins would accumulate facts across scheduled runs and make runs depend on history. Keep LTM off for evaluator actors.

---

## 11. Risks

| Risk | Mitigation |
|---|---|
| A run lands in the wrong account (profile or default-chain mix-up) | Account-ID guard in preflight (8.1 item 1) |
| Runtime not READY right after a deploy (424) | `GetAgentRuntime` READY poll before the post-deploy smoke |
| `SpanEventParsingException` persists (Strands interrupts) | The gate never depends on AWS scores; they stay corroborating. Recheck after the Strands upgrade (README procedure). |
| Flaky gates from LLM and judge variance | Hard-gate only the invariants; report rates; compare against a pinned baseline |
| Persona data drift (demo writes) | Fail-closed precheck plus SNS; no auto-reset; extended precheck |
| PR code running with eval credentials | Harness from `stage`, only the prompt file from the PR; Cedar evaluator write `forbid`; no `pull_request_target` |
| Transcript exposure in a public repo | Results only in S3 and CloudWatch; PR comments carry aggregates only |
| `evals/.env` or results packaged into the CDK asset | Asset `exclude` list, and a CDK test asserting it |
| Pitch dashboard overwritten during judging | Separate dashboard name; freeze window |
| Batch evaluation API churn (preview in SDK 1.24.0) | Keep per-session `Evaluate` until GA; move to batch later for the 25% lower token price |
| Cost creep from a growing matrix or nightly cadence | `--max-cost`; weekly by default; smoke subset for post-deploy and PRs |
| Leaked eval password | The login can only use allowlisted models and prompts on its own persona (Cedar customer check). Rotate via `eval_users` plus `put-secret-value`. |

---

## 12. Sources

**Repo:**
- `evals/{runner,aws_eval,report,cw_dashboard,config,eval_users,cases}.py`, `evals/README.md`, `evals/requirements.txt`
- `evals/results/{baseline-v10,pilot,smoke,report-v10}`: file mtimes and JSONL statistics computed locally
- `docs/superpowers/specs/2026-10-04-eval-harness-design.md`
- `scripts/deploy-with-codebuild.py`
- `infra-cdk/lib/data-construct.ts`, `backend-construct.ts:241-245, 445-457, 881-929`, `cognito-construct.ts:70-96, 143-161`
- `gateway/policies/policy.cedar`, `infra-cdk/lambdas/pretoken-v3/index.py`
- `.github/workflows/*.yml`
- `evals/.venv/Lib/site-packages/bedrock_agentcore/evaluation/{client.py, utils/cloudwatch_span_helper.py, runner/batch/*}` and the botocore `bedrock-agentcore` 2024-02-28 service model
- `gh repo view` (visibility PUBLIC, default branch main, permission WRITE)

**AWS:**
- [Lambda timeout (900 s)](https://docs.aws.amazon.com/lambda/latest/dg/configuration-timeout.html)
- [Lambda .zip package 250 MB unzipped](https://docs.aws.amazon.com/lambda/latest/dg/nodejs-package.html)
- [Lambda FAQ: durable functions](https://aws.amazon.com/lambda/faqs/)
- [Step Functions Map modes (Inline up to 40, Distributed up to 10,000; 256 KiB; 25,000 events)](https://docs.aws.amazon.com/step-functions/latest/dg/state-map.html)
- [Step Functions AWS SDK integrations (Bedrock AgentCore unsupported ops)](https://docs.aws.amazon.com/step-functions/latest/dg/supported-services-awssdk.html)
- [Step Functions pricing ($0.025 per 1k transitions)](https://aws.amazon.com/step-functions/pricing/)
- [CodeBuild quotas (timeout 5–2,160 min)](https://docs.aws.amazon.com/codebuild/latest/userguide/limits.html)
- [CodeBuild pricing (arm1.small $0.0034/min, general1.small $0.005/min, 100 free min)](https://aws.amazon.com/codebuild/pricing/), with numbers corroborated by [cicdcost.com](https://cicdcost.com/aws-codebuild-cost)
- [CloudFormation Stack Status Change events](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/event-detail-stack-status-change.html)
- [EventBridge Scheduler templated targets](https://docs.aws.amazon.com/scheduler/latest/UserGuide/managing-targets-templated.html)
- [AgentCore batch evaluation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/batch-evaluations.html)
- [AgentCore quotas (batch: 5 active, 500 sessions, 10 evaluators)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html)
- [AgentCore pricing (Evaluations $0.0024/$0.012 per 1k tokens; batch $0.0018/$0.009; Runtime $0.1276 per vCPU-h)](https://aws.amazon.com/bedrock/agentcore/pricing/)
- [Inbound JWT authorizer](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/inbound-jwt-authorizer.html)
- [SigV4 vs JWT invocation (JWT needs raw HTTPS)](https://aws.amazon.com/blogs/industries/automate-customer-complaint-classification-with-ai-agents-on-aws/)
- [AWS ML blog: automated agent evaluation with AgentCore and GitHub Actions (OIDC, bearer HTTPS invoke, 424 until READY, 30–90 s trace propagation, judge variance)](https://aws.amazon.com/blogs/machine-learning/automated-agent-evaluation-with-amazon-bedrock-agentcore-and-github-actions/)
- [Cognito unauthenticated operations (InitiateAuth)](https://docs.aws.amazon.com/cognito/latest/developerguide/authentication-flows-public-server-side.html)
- [Logs Insights 100 concurrent queries](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/scheduled-queries-troubleshooting.html)

**GitHub:**
- [OIDC in AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
- [Actions limits (6 h per job)](https://docs.github.com/en/actions/reference/limits)
- [Disabling workflows (60-day schedule auto-disable in public repos)](https://docs.github.com/actions/managing-workflow-runs/disabling-and-enabling-a-workflow)
