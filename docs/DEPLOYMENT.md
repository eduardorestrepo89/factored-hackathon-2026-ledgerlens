# Deployment Guide

LedgerLens deploys to one AWS account and region as two CDK stacks, plus a React frontend pushed to Amplify Hosting by a script:

| Stack | Holds | Code |
|---|---|---|
| `ledgerlens-bank-assistant-data` | Aurora DSQL, its VPC endpoint, the tool IAM roles and the data load pipeline | `infra-cdk/lib/data-stack.ts`, `data-construct.ts` |
| `ledgerlens-bank-assistant` | Amplify app, Cognito, AgentCore Runtime, Memory, Gateway, Cedar policy, the 9 tool Lambdas, the guardrail and the feedback API | `infra-cdk/lib/ledgerlens-main-stack.ts`, `backend-construct.ts`, `cognito-construct.ts`, `amplify-hosting-construct.ts` |

The main stack uses the data stack's VPC, security group, roles and DSQL host, so the data stack always deploys first. `cdk deploy --all` handles that order.

## Current deployment

| | |
|---|---|
| AWS account / region | `704650059996` / `us-east-1` |
| CLI profile | `ledgerlens` (always set `AWS_PROFILE=ledgerlens`; the default profile is a different account) |
| App URL | https://main.dteq5fgkcy7a4.amplifyapp.com |
| Cognito user pool | `us-east-1_XEG5COTSy` (web client `1jlfd5jrsta9pdup2iijguu255`, group `evaluators`) |
| Cognito domain | `ledgerlens-bank-assistant-704650059996-us-east-1.auth.us-east-1.amazoncognito.com` |
| AgentCore Runtime | `ledgerlens_bank_assistant_ledgerlens_agent-VuhAwlER4L` |
| AgentCore Gateway | `ledgerlens-bank-assistant-gateway-0emkqlikrv` |
| Cedar policy engine | `ledgerlens_bank_assistant_policy_engine-e2smpf2suo` |
| Feedback API | `https://t886ssi6jk.execute-api.us-east-1.amazonaws.com/prod/` |
| Aurora DSQL cluster | `cfud6ejrtw4cwqwbnac6njkokm` (private host `cfud6ejrtw4cwqwbnac6njkokm.dsql-fnh4.us-east-1.on.aws`) |
| Data pipeline | Step Functions `ledgerlens-data-pipeline`, CodeBuild `ledgerlens-data-load` |

These IDs change if a stack is deleted and recreated. Read the current values from the stack outputs:

```bash
export AWS_PROFILE=ledgerlens
aws cloudformation describe-stacks --stack-name ledgerlens-bank-assistant \
  --query "Stacks[0].Outputs[].[OutputKey,OutputValue]" --output table
aws cloudformation describe-stacks --stack-name ledgerlens-bank-assistant-data \
  --query "Stacks[0].Outputs[].[OutputKey,OutputValue]" --output table
```

## What each stack creates

### Data stack (`ledgerlens-bank-assistant-data`)

- **Aurora DSQL cluster.** Deletion protection is on and the removal policy is RETAIN, so deleting the stack keeps the cluster. A cluster policy denies `dsql:DbConnect` and `dsql:DbConnectAdmin` from outside the VPC, except for the loader role.
- **Network.** The account's default VPC, one AZ. An interface (PrivateLink) endpoint for DSQL on port 5432 with private DNS, reachable only from the tools security group. The subnets are public, but Lambdas get no public IP, so the tools reach only the DSQL endpoint.
- **IAM roles.**
  - `ledgerlens-tools`: the read tools, `dsql:DbConnect` as `ll_read`.
  - `ledgerlens-write-tools`: `block_credit_card` and `open_claim`, `dsql:DbConnect` as `ll_write`.
  - Loader role: the CodeBuild stages, `dsql:DbConnectAdmin`.
- **Team bucket** (S3, SSE-S3, public access blocked): raw, clean and curated data plus the run records.
- **Secret `ledgerlens/hackathon-s3`**: the organizer's read-only S3 keys. CDK creates it with a placeholder value, and a person sets the real value once.
- **CodeBuild `ledgerlens-data-load`**: ARM, LARGE, 8 h timeout, one build at a time. It runs `python -m data_load $STAGE` with a pinned `aurora-dsql-loader` release (checksum verified).
- **Lambda `ledgerlens-dsql-read-check`**: runs in the tools' subnet as `ledgerlens-tools` and checks that the tools can read what was loaded.
- **Step Functions `ledgerlens-data-pipeline`**: Ingest → Transform → Curate → Load (CodeBuild) → ReadCheck (Lambda).

### Main stack (`ledgerlens-bank-assistant`)

- **Amplify Hosting app** `ledgerlens-bank-assistant-frontend`, branch `main`. It is a manual-deploy app: there is no Git connection, and `scripts/deploy-frontend.py` uploads a zip to the staging bucket and starts the job. Responses carry a CSP, HSTS, `X-Frame-Options: DENY` and related headers (`amplify-hosting-construct.ts`).
- **Cognito.**
  - User pool `ledgerlens-bank-assistant-user-pool`: no self sign-up, email sign-in, strong password policy, Essentials plan, managed login v2.
  - Web client: Authorization Code grant, no secret. Callbacks are the Amplify URL and `http://localhost:3000`.
  - Machine client: client credentials grant, with the resource server `ledgerlens-bank-assistant-gateway` (`read`/`write` scopes). Its secret is stored in Secrets Manager as `/ledgerlens-bank-assistant/machine_client_secret`.
  - Group `evaluators`: logins that may switch the model and base prompt per session.
  - V3 pre-token Lambda `ledgerlens-bank-assistant-pretoken-v3`: adds `customer_id` to the M2M token, looked up from `USER_CUSTOMER_IDS_MAP` (hard-coded in `cognito-construct.ts`).
- **AgentCore Runtime** `ledgerlens_bank_assistant_ledgerlens_agent`.
  - Built as an ARM64 Docker image from `agent/ledgerlens/Dockerfile`, with the repo root as the build context.
  - PUBLIC network mode, HTTP protocol.
  - JWT authorizer on the web client; the `Authorization` header is allowlisted so the agent can read the user's `sub`.
  - Its environment variables come from `config.yaml` (see [Configuration](#configuration)).
- **AgentCore Memory**: 30-day expiry. A semantic `FactExtractor` strategy is defined, but retrieval only runs when `use_long_term_memory: true`.
- **Bedrock Guardrail** `ledgerlens-bank-assistant-agent-guardrail` (`lib/utils/agent-guardrail.ts`).
  - Content filters (prompt attack included) and four denied off-topic groups, on the Standard tier through the `us.guardrail.v1:0` cross-region profile.
  - It masks nothing. A new guardrail version is published whenever its policy changes.
- **AgentCore Gateway** `ledgerlens-bank-assistant-gateway`: MCP `2025-03-26`, with a custom JWT authorizer that accepts only the machine client. It has one Lambda target per tool (table below).
- **OAuth2 credential provider** `ledgerlens-bank-assistant-runtime-gateway-auth` (custom resource, `lambdas/oauth2-provider`). The agent itself fetches the Gateway token straight from the Cognito `/oauth2/token` endpoint, passing the user's `sub` as `aws_client_metadata` (`agent/utils/auth.py`). That way the pre-token Lambda can add the `customer_id` claim.
- **Cedar policy engine** `ledgerlens_bank_assistant_policy_engine` (custom resource, `lambdas/cedar-policy`) loads `gateway/policies/policy.cedar`:
  - It permits the 9 tools only for a token with a non-empty `customer_id`.
  - It forbids any call whose `customer_id` input differs from that claim.
  - It forbids `block_credit_card` and `open_claim` unless `customer_confirmed` is `true`. The confirmation hook sets that flag only after the customer taps Yes.
- **Feedback API.**
  - DynamoDB table `ledgerlens-bank-assistant-feedback` (on-demand, PITR).
  - Lambda `ledgerlens-bank-assistant-feedback`.
  - REST API `ledgerlens-bank-assistant-api`, stage `prod`, `POST /feedback` behind a Cognito authorizer.
- **SSM parameters** under `/ledgerlens-bank-assistant/`: `runtime-arn`, `gateway_url`, `cognito-user-pool-id`, `cognito-user-pool-client-id`, `machine_client_id`, `cognito_provider`, `feedback-api-url`.

#### Gateway tools

Each tool is `gateway/tools/<tool>/`: `tool_spec.json` is the MCP schema, `<tool>_lambda/delivery/handler.py` the handler. Every tool Lambda runs Python 3.13 on ARM64, logs to `/aws/lambda/ledgerlens-bank-assistant-<slug>` with one-week retention, and gets `DSQL_CLUSTER_ENDPOINT` (the private host) and `AS_OF` (`data.as_of`) when it uses DSQL.

| Tool | Lambda | Gateway target | DSQL access |
|---|---|---|---|
| `list_credit_cards` | `ledgerlens-list-credit-cards` | `list-credit-cards-target` | `ll_read`, in VPC |
| `list_card_transactions` | `ledgerlens-list-card-transactions` | `list-card-transactions-target` | `ll_read`, in VPC |
| `get_session_context` | `ledgerlens-get-session-context` | `get-session-context-target` | `ll_read`, in VPC |
| `transaction_fraud_detection` | `ledgerlens-transaction-fraud-detection` | `fraud-detection-target` | `ll_read`, in VPC |
| `explain_transaction` | `ledgerlens-explain-transaction` | `explain-transaction-target` | `ll_read`, in VPC |
| `classify_call_type` | `ledgerlens-classify-call-type` | `classify-call-type-target` | `ll_read`, in VPC |
| `block_credit_card` | `ledgerlens-block-credit-card` | `block-credit-card-target` | `ll_write`, in VPC |
| `open_claim` | `ledgerlens-open-claim` | `open-claim-target` | `ll_write`, in VPC |
| `human_agent_hand_off` | `ledgerlens-human-agent-hand-off` | `human-agent-hand-off-target` | none, outside the VPC |

## Prerequisites

- **AWS CLI v2** with the `ledgerlens` profile, and **git**.
- **Python 3.11+**. The deploy scripts use only the standard library.
- **Node.js 20.19+ or 22.12+ and npm**, to build the frontend (`deploy-frontend.py`). Vite 8 needs one of those.
- **Bedrock model access** in the account for `backend.model_id` (Claude Haiku 4.5 through the `global.` inference profile). The extra `eval_model_ids` (DeepSeek V3.2, gpt-oss-120b) are third-party models and need their Marketplace agreement accepted before first use.
- **Only for a local CDK deploy (Option B):** Docker with ARM64 builds and the CDK CLI (`infra-cdk` pins `aws-cdk` as a dev dependency, so `npx cdk` works).

## Configuration

Everything is set in `infra-cdk/config.yaml`. The values in use:

| Key | Value | Effect |
|---|---|---|
| `stack_name_base` | `ledgerlens-bank-assistant` | Main stack name; the data stack adds `-data`. It prefixes most resource names. Max 35 characters. |
| `deploy_scope` | `full` | `full` = data + main stacks; `data` = only the data stack. Override per run with `-c deploy_scope=data`. |
| `admin_user_email` | empty | When set, CDK creates that Cognito user and emails a temporary password. |
| `backend.agent_name` | `ledgerlens_agent` | Runtime name suffix. |
| `backend.pattern` | `ledgerlens` | Agent folder under `agent/`. |
| `backend.deployment_type` | `docker` | `zip` packages the agent with a Lambda instead of building an image. |
| `backend.network_mode` | `PUBLIC` | `VPC` moves the runtime into a VPC you provide ([appendix](#appendix-vpc-mode-for-the-runtime)). |
| `backend.model_id` | `global.anthropic.claude-haiku-4-5-20251001-v1:0` | The agent's model (`MODEL_ID`). |
| `backend.eval_model_ids` | DeepSeek V3.2, gpt-oss-120b, Haiku 4.5 | Models an `evaluators` login may pick per session (`EVAL_MODEL_IDS`). |
| `backend.use_long_term_memory` | `false` | Turns on semantic memory retrieval (`ltm_top_k`, `ltm_relevance_score`). |
| `backend.stm_window_size` | `30` | Messages sent to the model per turn. |
| `backend.use_stm_summarization` | `false` | Summarizes messages that fall out of the window (`stm_*` keys). |
| `backend.mcp_registry.enabled` | `false` | Auto-connects MCP servers from an AWS Agent Registry. |
| `data.as_of` | `2026-06-17T23:59:59` | The bank's "today" for the tools (`AS_OF`). The curate stage has its own copy in `data_load/curate_rules.py`; change both together. |

Some names don't use `stack_name_base`: the IAM roles `ledgerlens-tools` and `ledgerlens-write-tools`, `ledgerlens-data-load`, `ledgerlens-data-pipeline`, `ledgerlens-dsql-read-check`, the secret `ledgerlens/hackathon-s3` and the `ledgerlens-<slug>` tool Lambdas. A second copy of the stacks in the same account would collide with the first on these names.

## First deployment

All commands run from the repo root.

### 1. Deploy the stacks

**Option A, CodeBuild (what the team uses):**

```bash
AWS_PROFILE=ledgerlens python scripts/deploy-with-codebuild.py
```

The script runs `cdk bootstrap` and `cdk deploy --all` on an ARM CodeBuild machine, because local Docker can't bundle the ARM64 image and Lambdas without emulation.
- It zips git-tracked and staged files only; untracked files are skipped with a warning, so stage new files first.
- It streams the build log to your terminal.
- It creates temporary `ledgerlens-deploy*` resources: a source bucket, a project, and an IAM role with a permission boundary. On success they are deleted. On failure they are kept for debugging and reused on the next run.
- It does not deploy the frontend (step 4).

To deploy one stack, name it (the data stack must already exist before the main stack can deploy):

```bash
AWS_PROFILE=ledgerlens python scripts/deploy-with-codebuild.py ledgerlens-bank-assistant-data
AWS_PROFILE=ledgerlens python scripts/deploy-with-codebuild.py ledgerlens-bank-assistant
```

Your IAM user needs the permissions listed in `scripts/README.md` to run it.

**Option B, local CDK (ARM64 machine or Docker with ARM64 emulation):**

```bash
export AWS_PROFILE=ledgerlens
cd infra-cdk
npm ci
npx cdk bootstrap          # once per account/region
npx cdk deploy --all       # or a stack name; -c deploy_scope=data for only the data stack
```

On an x86_64 machine, enable ARM64 builds first (see [Docker cross-platform setup](#docker-cross-platform-setup)).

### 2. Set the organizer's S3 keys (once)

Write a JSON file outside the repo, set it as the secret's value, then delete the file. Never commit it.

```json
{"aws_access_key_id": "...", "aws_secret_access_key": "...", "bucket": "<datathon bucket>", "region": "us-east-2", "prefix": "data/"}
```

```bash
aws secretsmanager put-secret-value --profile ledgerlens --secret-id ledgerlens/hackathon-s3 \
  --secret-string file://<file-outside-the-repo>.json
```

### 3. Load the data

```bash
AWS_PROFILE=ledgerlens make load-data
```

This starts `ledgerlens-data-pipeline` and prints the console link for the execution. A full run takes about 10 minutes and costs under $1. To rerun one stage, retune the curation or run the `access` stage after adding a DB role, see [Operating the data pipeline](#operating-the-data-pipeline). A load drops and recreates the tables, so the tools fail for about 2 minutes: never reload during a demo.

### 4. Deploy the frontend

```bash
AWS_PROFILE=ledgerlens python scripts/deploy-frontend.py
```

The script:
1. Reads the main stack's outputs.
2. Writes `frontend/public/aws-exports.json`.
3. Runs `npm install` if needed, then `npm run build` (Vite, output `frontend/build`).
4. Zips the build to the staging bucket and starts an Amplify deployment on `main`.
5. Waits for it and prints the App URL.

### 5. Create logins and link them to customers

Cedar refuses every tool call from a login whose Cognito `sub` isn't in `USER_CUSTOMER_IDS_MAP`, because its `customer_id` claim is blank.
- **Demo login:** create `demo@ledgerlens.example` and switch it between personas, following [Logins and personas](usage.md#logins-and-personas).
- **Evaluation logins:** `python -m evals.eval_users create --apply` creates them and writes their subs into `cognito-construct.ts`. After the deploy that creates the `evaluators` group, run `python -m evals.eval_users add-to-group --apply`. See `evals/README.md`.

After adding subs to the map in `infra-cdk/lib/cognito-construct.ts`, commit them and redeploy the main stack. A redeploy resets the Lambda's map to the committed value, so subs that are only in the console are lost.

## Updating

| What changed | Deploy |
|---|---|
| Agent code (`agent/`), tool code or schemas (`gateway/tools/`), `gateway/policies/policy.cedar`, the guardrail, `backend.*` or `data.as_of` in `config.yaml`, `USER_CUSTOMER_IDS_MAP` | `AWS_PROFILE=ledgerlens python scripts/deploy-with-codebuild.py ledgerlens-bank-assistant` |
| Frontend (`frontend/`) | `AWS_PROFILE=ledgerlens python scripts/deploy-frontend.py` |
| `data_load/`, `data-construct.ts` | `... deploy-with-codebuild.py ledgerlens-bank-assistant-data`, then rerun the pipeline if the data must change |
| Demo persona | No deploy: [switch the persona](usage.md#logins-and-personas) |
| Frontend on your machine against the deployed backend | `AWS_PROFILE=ledgerlens python scripts/deploy-frontend.py --config-only`, then `cd frontend && npm install && npm run dev` (http://localhost:3000) |

When agent code changes, the main stack deploy builds a new image and the runtime moves to a new version.

**Adding a Gateway tool** takes four steps:
1. Add `gateway/tools/<tool>/` with `tool_spec.json` and `<tool>_lambda/delivery/handler.py`.
2. Add an entry to `toolTargets` in `backend-construct.ts` (with `role: readRole` or `writeRole` if it uses DSQL).
3. Add its `<target>___<tool>` action to the permit and the `customer_id` forbid in `policy.cedar`, and to the `customer_confirmed` forbid if it writes. Without step 3, Cedar denies the tool.
4. Deploy the main stack.

The model sees each tool as `gateway_<target>___<tool>`, and Bedrock rejects every request if any tool name is over 64 characters. Give a long tool a shorter `target` name, as `fraud-detection-target` does.

## Verifying a deployment

- **Stack outputs:** see [Current deployment](#current-deployment).
- **Data:** `aws lambda invoke --profile ledgerlens --function-name ledgerlens-dsql-read-check out.json`.
- **Gateway and Cedar without the agent:** `test-scripts/test-gateway.py --user-sub <sub> [--customer-id <id>]`.
- **The deployed agent:** `test-scripts/test-agent.py` (as the demo login). `test-feedback-api.py` and `test-memory.py` cover the other pieces; see `test-scripts/README.md`.
- **Logs:**
  - Agent: `/aws/bedrock-agentcore/runtimes/<runtime-id>-DEFAULT`
  - Tools and other Lambdas: `/aws/lambda/ledgerlens-bank-assistant-<name>`
  - Data stages: `/aws/codebuild/ledgerlens-data-load`
  - Feedback API access log: `/aws/apigateway/ledgerlens-bank-assistant-api-access`

## Operating the data pipeline

`make load-data` runs the whole pipeline: Ingest → Transform → Curate → Load → ReadCheck. The execution name is the run id. Each stage writes `runs/<run-id>/<stage>.json` in the team bucket. Curate fixes per-customer incoherence (rules C1–C12) and selects the customers; Load reads `curated/<run-id>/`. Design: [data pipeline spec](superpowers/specs/2026-10-02-data-pipeline-design.md) and [curate stage spec](superpowers/specs/2026-10-03-curate-stage-design.md).

- **Rerun one stage** of an existing run (stages: `ingest`, `transform`, `curate`, `load`):

  ```bash
  aws codebuild start-build --profile ledgerlens --project-name ledgerlens-data-load \
    --environment-variables-override name=STAGE,value=<stage>,type=PLAINTEXT name=RUN_ID,value=<run-id>,type=PLAINTEXT
  ```

- **Retune the customer selection:** rerun `curate`, then `load`, for the same run (about 6 minutes). Transform isn't rerun.
- **After a manual rerun,** run the read check yourself:

  ```bash
  aws lambda invoke --profile ledgerlens --function-name ledgerlens-dsql-read-check out.json
  ```

- **Add a DB role to a loaded cluster:** after a data stack deploy that adds a role, run the `access` stage once. It creates the roles, maps them to their IAM roles and re-runs the grants, without touching the data:

  ```bash
  aws codebuild start-build --profile ledgerlens --project-name ledgerlens-data-load \
    --environment-variables-override name=STAGE,value=access,type=PLAINTEXT
  ```

- **Check for an organizer re-upload:** this compares the organizer's bucket (read with the `hackathon` profile) to an ingest run's record (read with the `ledgerlens` profile):

  ```bash
  uv run --no-project --with-requirements data_load/requirements.txt python -m data_load check --run <run-id> --team-bucket <team-bucket>
  ```

- **Follow a stage's log:** `aws logs tail /aws/codebuild/ledgerlens-data-load --follow --profile ledgerlens`.
- **Reload downtime:** a load drops and recreates the 13 tables, so the tools fail for about 2 minutes. Never reload during a demo.
- **Cost and deleting the cluster:** see [Cleanup](#cleanup).
- **Query the database by hand:** laptops are refused, admin credentials included, by the cluster policy. Ad-hoc queries need a temporary exception in that policy (pipeline spec section 7.3).

## Understanding aws-exports.json

`deploy-frontend.py` generates `frontend/public/aws-exports.json` from the main stack's outputs and copies it into the build. Don't edit it by hand: every deploy regenerates it. With `--config-only`, the redirect URIs point to `http://localhost:3000` instead of the Amplify URL.

```json
{
  "authority": "https://cognito-idp.<region>.amazonaws.com/<CognitoUserPoolId>",
  "client_id": "<CognitoClientId>",
  "redirect_uri": "<AmplifyUrl>",
  "post_logout_redirect_uri": "<AmplifyUrl>",
  "response_type": "code",
  "scope": "email openid profile",
  "automaticSilentRenew": true,
  "agentRuntimeArn": "<RuntimeArn>",
  "awsRegion": "<region>",
  "feedbackApiUrl": "<FeedbackApiUrl>",
  "agentPattern": "ledgerlens"
}
```

## Cleanup

Delete the main stack first: it imports the data stack's exports.

```bash
export AWS_PROFILE=ledgerlens
aws cloudformation delete-stack --stack-name ledgerlens-bank-assistant
aws cloudformation wait stack-delete-complete --stack-name ledgerlens-bank-assistant
aws cloudformation delete-stack --stack-name ledgerlens-bank-assistant-data
```

(`cd infra-cdk && npx cdk destroy --all` does the same.) The buckets, the stacks' log groups, the user pool and the feedback table are deleted with the stacks. These stay behind:

- **The DSQL cluster** (deletion protection and RETAIN). To remove it:

  ```bash
  aws dsql update-cluster --identifier <cluster-id> --no-deletion-protection-enabled
  aws dsql delete-cluster --identifier <cluster-id>
  ```

  Redeploying the data stack afterwards creates a new, empty cluster that has to be loaded again.
- **The `CDKToolkit` bootstrap stack** and its asset bucket and ECR repository.
- **Failed CodeBuild deploy resources** (`ledgerlens-deploy*`), until the next successful run removes them.
- **The runtime's log groups** (`/aws/bedrock-agentcore/runtimes/*`), which AgentCore creates itself.

While the stacks exist, the data stack costs about $9.70 a month, mostly the DSQL endpoint. The feedback API's 0.5 GB stage cache bills by the hour on top of that.

## Troubleshooting

- **AccessDenied, or "stack does not exist":** the command ran without `AWS_PROFILE=ledgerlens` and reached another account.
- **Local `cdk deploy` fails with Docker or "exec format error":** the machine can't build ARM64. Use `deploy-with-codebuild.py`, or set up [ARM64 emulation](#docker-cross-platform-setup).
- **A new file isn't in the CodeBuild deploy:** it was untracked. `git add` it and rerun.
- **The pipeline fails in Ingest:** the `ledgerlens/hackathon-s3` secret still holds its placeholder, or a key is missing (`aws_access_key_id`, `aws_secret_access_key`, `bucket`, `region`, `prefix`).
- **The agent says it can't see the customer's cards, or tool calls are denied:** the login's `sub` isn't in `USER_CUSTOMER_IDS_MAP`, or a redeploy reset the map to its committed value. Check the `customer_id` claim with `test-gateway.py`.
- **Tools fail with connection or "table does not exist" errors:** a load is running, or the cluster was never loaded. After adding a DB role, run the `access` stage.
- **Bedrock AccessDenied on the model:** the account can't invoke `model_id` yet, or a third-party model's Marketplace agreement hasn't been accepted.
- **Sign-in redirects fail:** `aws-exports.json` is stale. Rerun `deploy-frontend.py` (or `--config-only` for local).
- **A failed CodeBuild deploy:** the script prints the project console URL. The build log is under `/aws/codebuild/ledgerlens-deploy*`.

## Docker cross-platform setup

AgentCore Runtime runs only ARM64 images, and the Lambdas are bundled for ARM64. To deploy with local CDK from an x86_64 machine (`uname -m` prints `x86_64`), enable emulation once:

```bash
docker run --privileged --rm tonistiigi/binfmt --install all
docker buildx create --use --name multiarch --driver docker-container
docker buildx inspect --bootstrap
docker buildx ls   # should list linux/arm64
```

## Appendix: VPC mode for the runtime

The deployed runtime uses `network_mode: PUBLIC`. This mode is about the agent runtime only: the tool Lambdas join the data stack's VPC either way. To put the runtime in your own VPC:

```yaml
backend:
  network_mode: VPC
  vpc:
    vpc_id: vpc-0abc1234def56789a
    subnet_ids: [subnet-aaaa1111bbbb2222c, subnet-cccc3333dddd4444e]
    security_group_ids: [sg-0abc1234def56789a]   # optional; a default SG is created if omitted
```

The private subnets need interface endpoints with private DNS for `bedrock-runtime`, `bedrock-agent-runtime`, `bedrock-agentcore`, `bedrock-agentcore.gateway`, `ssm`, `secretsmanager`, `logs`, `ecr.api`, `ecr.dkr` and `xray`, plus a gateway endpoint for `s3`. The runtime's security group must allow TCP 443 to them.

You also need a **NAT gateway**: the agent calls the Cognito hosted domain's `/oauth2/token` directly to get the Gateway token (`agent/utils/auth.py`), and that endpoint has no VPC endpoint.
