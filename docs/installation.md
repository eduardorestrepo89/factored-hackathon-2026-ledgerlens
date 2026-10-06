# Installation

This guide sets up a development machine. You end up with the React frontend running on your machine against the deployed backend (AgentCore Runtime, Gateway, tool Lambdas, Aurora DSQL), plus everything needed to run the tests. Deploying the stacks to AWS is a separate guide: [DEPLOYMENT.md](DEPLOYMENT.md).

Why the frontend runs locally but the backend doesn't:
- **The data can't leave the VPC.** Aurora DSQL accepts connections only from inside the data stack's VPC, so there is no local database.
- **The agent runs in AWS.** Its Gateway tools need the deployed Cognito, pre-token Lambda and Cedar policy.

The working loop is: edit `frontend/` with hot reload on `localhost:3000`, and deploy agent or tool changes to AWS.

## Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| git | any | Cloning |
| Python | 3.11 or newer | Unit tests, deploy scripts, evals. The tool packages use `enum.StrEnum` (3.11+). The Lambdas and the agent image run 3.13; CI lint uses 3.11. |
| Node.js and npm | 20.19+ or 22.12+ | Frontend and CDK. Vite 8 requires `^20.19.0 \|\| >=22.12.0`. CI uses Node 20. |
| AWS CLI | v2 | Everything that touches AWS, through the `ledgerlens` profile |
| uv | any | Optional. The smoke-script and data `check` commands use `uv run`, which installs their dependencies on the fly. |
| Docker | with ARM64 builds | Only for a local CDK deploy. The team deploys through CodeBuild instead: [DEPLOYMENT.md, Prerequisites](DEPLOYMENT.md#prerequisites). |

Check them:

```bash
git --version
python --version     # 3.11+
node --version       # v20.19+ or v22.12+
aws --version        # aws-cli/2.x
```

### Windows notes

- **Use Git Bash.** The commands in these docs are bash: a variable set for one command (`AWS_PROFILE=ledgerlens python ...`), shell functions, `read -s`. PowerShell and cmd don't run them as written. In PowerShell the frontend step, for example, is `$env:AWS_PROFILE = "ledgerlens"; python scripts/deploy-frontend.py --config-only`.
- **Virtual environments** keep their scripts in `Scripts\`, not `bin/`: `source .venv/Scripts/activate` in Git Bash, `.venv\Scripts\Activate.ps1` in PowerShell.
- **`make` isn't installed by default.** You only need it for `make lint` and `make load-data`; each target is a short command you can run by hand (see the `Makefile`).

## 1. Clone

```bash
git clone https://github.com/eduardorestrepo89/ledgerlens-bank-assistant.git
cd ledgerlens-bank-assistant
git switch stage
```

`stage` is the team's integration branch; `main` still tracks the upstream FAST template ([CONTRIBUTING.md](../CONTRIBUTING.md)).

## 2. Configure the AWS profile

All the project's commands use the CLI profile `ledgerlens`: account `704650059996`, region `us-east-1`. The default profile on the team's machines points to a different account, so a command without `AWS_PROFILE=ledgerlens` fails with AccessDenied or "stack does not exist".

```bash
aws configure --profile ledgerlens        # access key, secret, region us-east-1, output json
aws sts get-caller-identity --profile ledgerlens --query Account --output text   # 704650059996
aws configure get region --profile ledgerlens                                     # us-east-1
```

The region matters: `scripts/deploy-frontend.py` reads the stack outputs with the profile's default region.

You don't need to edit `infra-cdk/config.yaml` to work on the frontend; it drives deployments. What each key does: [DEPLOYMENT.md, Configuration](DEPLOYMENT.md#configuration).

## 3. Install dependencies

Each part of the repo has its own dependencies. Install only what you'll use.

**Python, for the unit tests.** From the repo root:

```bash
python -m venv .venv
source .venv/bin/activate              # Git Bash on Windows: source .venv/Scripts/activate
python -m pip install pytest -r agent/ledgerlens/requirements.txt -r data_load/requirements.txt
```

The tests import the agent's code (Strands, PyJWT, requests) and the data pipeline's (DuckDB, psycopg, the DSQL connector), so those two requirement files cover them. With this set, `pytest` passes on Python 3.11 (2,696 tests). For linting, add `python -m pip install ruff==0.14.1`.

Don't use `requirements-dev.txt` for now: pip can't install it. It pins `aws-cdk-lib==2.253.0` together with `constructs==10.0.79`, and that `aws-cdk-lib` release requires `constructs>=10.5.0`. No Python code uses those two packages anyway; the CDK app is TypeScript, in `infra-cdk/`.

**Frontend:**

```bash
cd frontend
npm ci          # exact versions from package-lock.json; `npm install` also works
cd ..
```

**CDK**, only for the CDK tests or a local deploy:

```bash
cd infra-cdk
npm ci
cd ..
```

**Evaluation harness**, only to run evals: it has its own virtual environment in `evals/.venv`. See [evals/README.md, Setup](../evals/README.md#setup-once).

**Smoke scripts and deploy scripts:** nothing to install. The smoke scripts run through `uv run --no-project --with-requirements test-scripts/requirements.txt` ([usage.md, Smoke scripts](usage.md#smoke-scripts)). `scripts/deploy-frontend.py` and `scripts/deploy-with-codebuild.py` use only the standard library and the AWS CLI.

## 4. Database

There is nothing to set up on your machine. The deployed cluster is already loaded, and laptops can't connect to it: the cluster policy refuses every identity from outside the VPC, admin credentials included.

For a new account, the database comes from steps 1–3 of [DEPLOYMENT.md, First deployment](DEPLOYMENT.md#first-deployment):
1. Deploy the stacks.
2. Set the organizer's S3 keys.
3. Load the data.

## 5. Run the frontend locally

```bash
AWS_PROFILE=ledgerlens python scripts/deploy-frontend.py --config-only
cd frontend && npm install && npm run dev
```

What happens:
1. **`--config-only` writes the config.** It reads the main stack's outputs and writes `frontend/public/aws-exports.json`: the Cognito authority and client id, the runtime ARN, the region and the feedback API URL. The redirect URIs point at `http://localhost:3000`. It skips the build and the Amplify deployment. The file is generated and gitignored; [DEPLOYMENT.md](DEPLOYMENT.md#understanding-aws-exportsjson) shows its fields.
2. **The dev server starts.** Vite serves the app on port 3000 and opens the browser. Cognito's web client already allows `http://localhost:3000` as a callback URL.
3. **The browser talks to AWS directly.** It calls the deployed AgentCore Runtime (`frontend/src/lib/agentcore-client/client.ts`) and the feedback API. Changes under `frontend/src` reload at once; changes to `agent/` or `gateway/` need a deploy ([DEPLOYMENT.md, Updating](DEPLOYMENT.md#updating)).

Keep port 3000 free. Vite moves to the next free port when 3000 is busy, and Cognito rejects any other redirect.

## 6. Verify

1. **Sign in.** Open http://localhost:3000 and choose **Iniciar sesión** with a login that is linked to a customer: the demo login or an evaluation login ([usage.md, Logins and personas](usage.md#logins-and-personas)).
2. **Chat.** Choose the suggestion *¿Por qué rechazaron mi compra?*. You see tool steps such as *Revisando movimientos* or *Revisando la compra*, then a reply built from that customer's records.
3. **Check the result.**
   - If the agent says the account isn't linked, the login's `sub` isn't in `USER_CUSTOMER_IDS_MAP`: see [usage.md, Common errors and fixes](usage.md#common-errors-and-fixes).
   - If sign-in sends you to the Amplify site instead, `aws-exports.json` is stale: rerun the `--config-only` step.
4. **Optional: run the unit tests.** Run `pytest` from the repo root (about a minute); [testing.md](testing.md) covers the other suites.

## Running the agent locally

Running the agent itself on your machine isn't a supported path right now. The FAST template's local tooling (`docker/docker-compose.yml`, `test-scripts/test-agent.py --local`, [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md), [LOCAL_DOCKER_TESTING.md](LOCAL_DOCKER_TESTING.md)) predates LedgerLens and misses what this agent needs:

- **It doesn't set the agent's required variables.** It passes only `MEMORY_ID`, `STACK_NAME` and the region. Every turn also needs `MODEL_ID` (`tools/eval_override.py`) and `GUARDRAIL_ID` plus `GUARDRAIL_VERSION` (`tools/guardrail.py`). Without them, each turn ends in an error event.
- **Its user isn't linked to a customer.** Local mode sends an unsigned JWT whose `sub` is `local-test-user`. That sub isn't in `USER_CUSTOMER_IDS_MAP`, so the Gateway token has a blank `customer_id`: `CustomerIdHook` cancels every tool call and Cedar would deny them anyway.
- **The web frontend can't reach a local agent.** `client.ts` always calls `https://bedrock-agentcore.<region>.amazonaws.com`; there is no setting to point it at `localhost:8080`.

To try agent or tool changes, deploy the main stack and test against it with the app, `test-scripts/test-agent.py` or the eval harness.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `pip install -r requirements-dev.txt` fails on `constructs` | The pins conflict (see step 3) | Use the install command in step 3. |
| `ImportError: cannot import name 'StrEnum'` in the tests | Python 3.10 or older | Use Python 3.11+. |
| `npm ci` warns about an unsupported engine, or `npm run dev` fails at startup | Node older than 20.19: Vite 8 declares `^20.19.0 \|\| >=22.12.0` | Install Node 20.19+ or 22.12+. |
| `deploy-frontend.py` fails with AccessDenied or "Stack ... does not exist" | It ran without `AWS_PROFILE=ledgerlens`, or the profile's region isn't `us-east-1` | Set the profile and its region (step 2). |
| `deploy-frontend.py` stops with "npm is not installed" | The script checks for `npm`, `aws` and `node` on `PATH`, even with `--config-only` | Install the missing tool or fix `PATH`. |
| The local app can't sign in on a fresh clone | `frontend/public/aws-exports.json` doesn't exist yet | Run step 5's `--config-only` command. |
