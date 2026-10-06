# Deployment scripts

This folder holds the two LedgerLens deploy scripts and a helper module for the test scripts. The full deploy guide is [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md).

| File | What it does |
|---|---|
| `deploy-with-codebuild.py` | Deploys the CDK stacks from a temporary CodeBuild project |
| `deploy-frontend.py` | Builds the frontend and publishes it to Amplify Hosting |
| `utils.py` | Helpers the `test-scripts/` import; the deploy scripts don't use it |
| `requirements.txt` | Packages `utils.py` and the test scripts import |

Both deploy scripts use only the Python standard library and the AWS CLI, so deploying needs no `pip install`. Run them from the repo root with `AWS_PROFILE=ledgerlens`.

## Deploy order

1. **Stacks:** `AWS_PROFILE=ledgerlens python scripts/deploy-with-codebuild.py`. With local Docker that builds ARM64, `cd infra-cdk && npx cdk deploy --all` does the same. Plain `cdk deploy` fails: the app has two stacks.
2. **Data (first time only):** set the organizer's S3 secret, then `AWS_PROFILE=ledgerlens make load-data`.
3. **Frontend:** `AWS_PROFILE=ledgerlens python scripts/deploy-frontend.py`.

Each step is explained in [First deployment](../docs/DEPLOYMENT.md#first-deployment). What to redeploy after a change is in [Updating](../docs/DEPLOYMENT.md#updating).

---

## deploy-with-codebuild.py

Runs `cdk bootstrap` and `cdk deploy` on an ARM CodeBuild machine. You need Python 3.11+, the AWS CLI and git, but no local Node.js, CDK or Docker. The team deploys this way because AgentCore Runtime runs only ARM64 images and the Lambdas are bundled for ARM64: an ARM build machine needs no emulation.

```bash
AWS_PROFILE=ledgerlens python scripts/deploy-with-codebuild.py                                  # every stack in deploy_scope
AWS_PROFILE=ledgerlens python scripts/deploy-with-codebuild.py ledgerlens-bank-assistant-data   # one stack
AWS_PROFILE=ledgerlens python scripts/deploy-with-codebuild.py ledgerlens-bank-assistant        # needs the data stack deployed
```

With no stack names it runs `cdk deploy --all`, which deploys every stack in `deploy_scope`: with `full` (the default), the data stack and then the main stack. Stack names must match `[A-Za-z][A-Za-z0-9-]*`, because they go into a shell command inside CodeBuild.

### What it does

1. Reads `stack_name_base` from `infra-cdk/config.yaml`. It takes the region from `AWS_REGION`, `AWS_DEFAULT_REGION` or the profile.
2. Zips the git-tracked and staged files (`git ls-files`). Untracked files are skipped with a warning that lists them, so `git add` new files first.
3. Creates these resources, or reuses them if a failed run left them behind:
   - Source bucket `ledgerlens-deploy-src-<account>-<stack>`. Its objects expire after one day.
   - Permission boundary policy `ledgerlens-deploy-boundary-<stack>`.
   - IAM role `ledgerlens-deploy-role-<stack>`: `AdministratorAccess`, limited by the boundary.
   - CodeBuild project `ledgerlens-deploy-<stack>`: ARM container (`amazonlinux2-aarch64-standard:3.0`), large, privileged for Docker builds, 60-minute timeout.
4. Starts the build. It installs `aws-cdk`, runs `npm ci` in `infra-cdk/`, `cdk bootstrap`, then `cdk deploy ${DEPLOY_STACKS:---all} --require-approval never`. The stack names you pass arrive as `DEPLOY_STACKS`.
5. Streams the build log to your terminal.
6. On success, deletes the four resources. On failure, keeps them for debugging, prints the project's console URL and the log group `/aws/codebuild/ledgerlens-deploy-<stack>`. The next run reuses them.

The boundary denies what a CDK deployment never needs, so the role can't escalate privileges: `iam:CreateUser`, `iam:CreateAccessKey`, `iam:CreateLoginProfile`, `iam:AttachUserPolicy`, `iam:PutUserPolicy`, `organizations:*`, `account:*`, `kms:PutKeyPolicy`, `kms:CreateGrant`.

What it does **not** do:
- **Deploy the frontend.** A successful run ends with "Frontend not deployed - run scripts/deploy-frontend.py when needed".
- **Remove the deployed stacks.** To tear them down, delete the main stack first, then the data stack, or run `cd infra-cdk && npx cdk destroy --all`. See [Cleanup](../docs/DEPLOYMENT.md#cleanup).

### Permissions

Your IAM user or role needs these to run the script. Each one maps to an AWS CLI call in the script.

- **S3:** `s3:ListBucket` (`head-bucket`, and listing objects before deleting the bucket), `s3:CreateBucket`, `s3:PutLifecycleConfiguration`, `s3:PutObject`, `s3:DeleteObject`, `s3:DeleteBucket`
- **IAM:**
  - `iam:GetPolicy`, `iam:CreatePolicy`, `iam:DeletePolicy` (the boundary)
  - `iam:GetRole`, `iam:CreateRole`, `iam:AttachRolePolicy`, `iam:DetachRolePolicy`, `iam:DeleteRole` (the role)
  - `iam:PassRole`, to hand the role to the CodeBuild project
- **CodeBuild:** `codebuild:BatchGetProjects`, `codebuild:CreateProject`, `codebuild:UpdateProject`, `codebuild:DeleteProject`, `codebuild:StartBuild`, `codebuild:BatchGetBuilds`
- **CloudWatch Logs:** `logs:GetLogEvents`

The script also calls `sts get-caller-identity` to find the account, which needs no permission.

---

## deploy-frontend.py

Builds the React frontend and publishes it to the main stack's Amplify app. It needs Python, the AWS CLI, Node.js and npm. It checks for all of them, even with `--config-only`.

```bash
AWS_PROFILE=ledgerlens python scripts/deploy-frontend.py                  # stack from config.yaml
AWS_PROFILE=ledgerlens python scripts/deploy-frontend.py <stack-name>     # another stack
AWS_PROFILE=ledgerlens python scripts/deploy-frontend.py --config-only    # only aws-exports.json, for local dev
```

Usage is `deploy-frontend.py [<stack-name>] [--config-only]`. The stack name comes from the first argument, else the `STACK_NAME` environment variable, else `stack_name_base` in `infra-cdk/config.yaml`.

### What it does

1. Checks that `npm`, `aws` and `node` are on the PATH and that AWS credentials work.
2. Reads the main stack's outputs, and the region from the stack ARN.
3. Writes `frontend/public/aws-exports.json` (below).
4. With `--config-only`, stops here. The redirect URIs point to `http://localhost:3000`, so you can run `cd frontend && npm install && npm run dev` against the deployed backend.
5. Runs `npm install` if `node_modules` is missing or older than `package.json`, then `npm run build` (output `frontend/build`).
6. Copies `aws-exports.json` into the build and zips it. It uploads the zip to the staging bucket as `amplify-deploy-<timestamp>.zip` and starts an Amplify deployment on branch `main`. The Amplify app has no Git connection: this upload is the only way the frontend gets deployed.
7. Polls the job every 10 seconds until it succeeds, fails or is cancelled, then prints the App URL.

It needs these main stack outputs:
- `CognitoClientId`, `CognitoUserPoolId`, `AmplifyUrl`, `RuntimeArn`, `FeedbackApiUrl`, for `aws-exports.json`;
- `AmplifyAppId`, `StagingBucketName`, for the deployment.

Its AWS calls: `cloudformation:DescribeStacks`, `s3:PutObject` on the staging bucket, `amplify:StartDeployment`, `amplify:GetJob` and `amplify:GetApp`.

### aws-exports.json

The React app reads this file to configure Cognito sign-in, the AgentCore Runtime and the feedback API. If a value is wrong, sign-in or the chat fails. The script regenerates it on every run, so don't edit it by hand.

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

`agentPattern` is `backend.pattern` from `config.yaml`.

---

## utils.py and requirements.txt

`utils.py` holds the helpers the four scripts in `test-scripts/` share. They import it by adding `scripts/` to `sys.path`.
- `get_stack_config`: the main stack's outputs, region and account, plus the agent pattern from `config.yaml`.
- `get_ssm_params`: parameters under `/<stack_name_base>/`.
- `authenticate_cognito`: signs a user in with `USER_PASSWORD_AUTH` on the web client. It returns the access token, the ID token and the `sub`.
- `create_mock_jwt`: an unsigned token that carries a `sub`, for a locally run agent.
- `create_bedrock_client`, `generate_session_id` and the print helpers.

`requirements.txt` lists what they import (`boto3`, `requests`, `PyYAML`, `colorama`). It is the same list as `test-scripts/requirements.txt`.

## Test scripts

The test and verification scripts are in `test-scripts/`. See [test-scripts/README.md](../test-scripts/README.md).
