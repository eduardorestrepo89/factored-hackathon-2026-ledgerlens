# LedgerLens infrastructure (CDK)

This folder is the AWS CDK app (TypeScript) that deploys LedgerLens. This README covers working on the CDK code. The full deploy guide (team route, frontend, data load, cleanup) is [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md).

## Stacks

The app builds two stacks (`bin/ledgerlens-cdk.ts` → `buildStacks` in `lib/ledgerlens-app.ts`):

| Stack | Code | Holds |
|---|---|---|
| `<stack_name_base>-data` (`ledgerlens-bank-assistant-data`) | `lib/data-stack.ts`, `lib/data-construct.ts` | Aurora DSQL, its VPC endpoint, the tool IAM roles and the data load pipeline |
| `<stack_name_base>` (`ledgerlens-bank-assistant`) | `lib/ledgerlens-main-stack.ts` | Amplify, Cognito and the backend, as three constructs in this one stack |

The main stack's constructs are `AmplifyHostingConstruct`, `CognitoConstruct` and `BackendConstruct` (Runtime, Memory, Gateway, Cedar, guardrail, tool Lambdas, feedback API). They are not separate stacks.

The tool Lambdas use the data stack's VPC, security group, roles and DSQL host, so the main stack depends on the data stack and deploys after it. For every resource each stack creates, see [What each stack creates](../docs/DEPLOYMENT.md#what-each-stack-creates).

## Prerequisites

- **Node.js 20+ and npm.** `aws-cdk-lib` 2.260 requires Node 20.
- **AWS CLI** with the `ledgerlens` profile.
- **Docker that builds `linux/arm64`.** `cdk synth`, `diff` and `deploy` bundle the Python Lambdas in Docker, and `deploy` also builds the agent image, all for ARM64. On an x86_64 machine you need ARM64 emulation (see [Prerequisites](../docs/DEPLOYMENT.md#prerequisites)). The team avoids local Docker altogether with `scripts/deploy-with-codebuild.py`.
- **CDK CLI:** none to install. `aws-cdk` is a dev dependency, so `npx cdk` runs the pinned version.

## Getting started

Run these from `infra-cdk/`.

```bash
export AWS_PROFILE=ledgerlens
npm ci
npx cdk bootstrap          # once per account/region
npx cdk deploy --all
```

With `deploy_scope: full` the app has two stacks, so plain `npx cdk deploy` stops and asks which stacks to use. Pass `--all` or a stack name.

### What `--all` deploys

`deploy_scope` in `config.yaml` decides:

- `full` (default): `<stack_name_base>-data` (Aurora DSQL and its load pipeline), then
  `<stack_name_base>` (Amplify, Cognito, the agent, the Gateway and the tool Lambdas).
- `data`: only `<stack_name_base>-data`.

Override it for one run with `npx cdk deploy --all -c deploy_scope=data`.

### After `cdk deploy`

- **The frontend is not published.** CDK creates the Amplify app and its `main` branch with nothing deployed. Run `AWS_PROFILE=ledgerlens python scripts/deploy-frontend.py` from the repo root.
- **A new data stack has an empty database.** Set the organizer's S3 secret once, then run `AWS_PROFILE=ledgerlens make load-data` from the repo root. Both steps are in [First deployment](../docs/DEPLOYMENT.md#first-deployment).

### Team route: CodeBuild

`AWS_PROFILE=ledgerlens python scripts/deploy-with-codebuild.py [STACK ...]` runs the same `cdk bootstrap` and `cdk deploy` on an ARM CodeBuild machine, so it needs no local Node, CDK or Docker. See [scripts/README.md](../scripts/README.md).

## Useful commands

* `npm run build`: compile with `tsc`. Use it as a type check: `cdk` runs the `.ts` files through `ts-node` (`cdk.json`).
* `npm run watch`: compile on every change.
* `npm test`: run the Jest unit tests. They skip Docker bundling and need no AWS credentials.
* `npx cdk deploy --all`: deploy both stacks, data first.
* `npx cdk diff`: compare the deployed stacks with the code.
* `npx cdk synth`: emit the CloudFormation templates.
* `npx cdk destroy --all`: delete both stacks, main first. The DSQL cluster stays behind (see [Cleanup](../docs/DEPLOYMENT.md#cleanup)).

## Configuration

`config.yaml` holds every setting. The core of it:

```yaml
stack_name_base: ledgerlens-bank-assistant   # at most 35 characters
deploy_scope: full                           # full or data

backend:
  pattern: ledgerlens                        # agent folder under agent/
  model_id: "global.anthropic.claude-haiku-4-5-20251001-v1:0"

data:
  as_of: "2026-06-17T23:59:59"               # the bank's "today" for the tools
```

Every key and its effect is in [Configuration](../docs/DEPLOYMENT.md#configuration).

`lib/utils/config-manager.ts` loads the file and fails the synth on a bad value:
- `stack_name_base` is required and capped at 35 characters, because AgentCore runtime names derive from it.
- `deployment_type` must be `docker` or `zip`.
- `network_mode` must be `PUBLIC` or `VPC`.
- `deploy_scope` must be `full` or `data`.

### Cached lookups (`cdk.context.json`)

The data stack uses the account's default VPC (`ec2.Vpc.fromLookup` in `data-construct.ts`) and the stack's availability zones. `cdk.context.json` caches both for account `704650059996` in `us-east-1`, so deploys there make no lookup. A deploy to another account or region looks them up again, which needs credentials that can describe the VPC, and writes new entries to `cdk.context.json`. Commit those entries.

## Project structure

```
infra-cdk/
├── bin/
│   └── ledgerlens-cdk.ts            # App entry: reads config.yaml, calls buildStacks
├── lib/
│   ├── ledgerlens-app.ts            # Builds the stacks for deploy_scope
│   ├── data-stack.ts                # Data stack and its outputs
│   ├── data-construct.ts            # DSQL, VPC endpoint, tool roles, team bucket, pipeline
│   ├── ledgerlens-main-stack.ts     # Main stack and its outputs
│   ├── amplify-hosting-construct.ts # Amplify app, staging bucket, security headers
│   ├── cognito-construct.ts         # User pool, clients, pre-token Lambda, USER_CUSTOMER_IDS_MAP
│   ├── backend-construct.ts         # Runtime, Memory, Gateway, Cedar, tool Lambdas, feedback API
│   └── utils/
│       ├── config-manager.ts        # Loads and validates config.yaml
│       ├── agentcore-role.ts        # The Runtime's IAM role
│       └── agent-guardrail.ts       # The Bedrock guardrail
├── lambdas/
│   ├── cedar-policy/                # Custom resource: Cedar policy engine and policy
│   ├── dsql-read-check/             # Pipeline's last stage: the tools can read the data
│   ├── feedback/                    # Feedback API handler
│   ├── oauth2-provider/             # Custom resource: OAuth2 credential provider
│   ├── pretoken-v3/                 # Cognito V3 pre-token Lambda (customer_id claim)
│   └── zip-packager/                # Packages the agent when deployment_type is zip
├── test/                            # Jest tests (below)
├── cdk.json                         # App command (ts-node) and CDK feature flags
├── cdk.context.json                 # Cached default VPC and AZs of 704650059996/us-east-1
├── config.yaml                      # Deployment settings
├── minimal-deploy-policy.json       # Reference IAM policy for a local deploy (see below)
├── jest.config.js
├── package.json
└── tsconfig.json
```

The Gateway tool Lambdas aren't here: each one's code and schema live in `gateway/tools/<tool>/`, and `backend-construct.ts` builds them.

### Tests

| File | Covers |
|---|---|
| `ledgerlens-cdk.test.ts` | `deploy_scope`, stack order, the Amplify security headers |
| `config-manager.test.ts` | `config.yaml` defaults and validation |
| `backend-gateway.test.ts` | Runtime settings, one Gateway target per tool, the 64-character tool name limit, Cedar actions, the guardrail |
| `policy-cedar.test.ts` | The forbids in `gateway/policies/policy.cedar` |
| `data-construct.test.ts`, `data-stack.test.ts` | DSQL access rules, the VPC, the read check, the pipeline, the data stack's outputs |

## Agent image

The Runtime runs a container built from `agent/ledgerlens/Dockerfile` for `linux/arm64`, the only platform AgentCore Runtime accepts. CDK builds it as an image asset and pushes it to the bootstrap stack's `cdk-*` container assets repository. LedgerLens creates no ECR repository of its own.

### Build context

The build context is the repository root, so the Dockerfile can copy the shared `agent/utils/` package next to the agent code.

### Keeping the context small

A large build context (`node_modules/`, `.git/` and so on) makes the "transferring context" step slow and can make CDK deployments hang. The root `.dockerignore` excludes:
- `node_modules/` directories (root, `frontend/` and `infra-cdk/`)
- `.git/`
- build output: `infra-cdk/cdk.out/`, `frontend/dist/`, `dist/`, `build/`, `*.egg-info/`
- caches: `.ruff_cache/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.coverage`, `htmlcov/`
- editor folders: `.vscode/`, `.idea/`

### Image contents

The Dockerfile installs `agent/ledgerlens/requirements.txt` and `aws-opentelemetry-distro`, then copies only what the agent imports:

- `agent/ledgerlens/ledgerlens_agent.py` (entry point)
- `agent/ledgerlens/tools/` → `tools/`
- `agent/utils/` → `utils/`

It starts the agent under `opentelemetry-instrument`, which sends traces and logs to CloudWatch ([docs/OBSERVABILITY.md](../docs/OBSERVABILITY.md)).

## Minimal IAM policy (`minimal-deploy-policy.json`)

The file has 29 actions in 7 statements:
- CloudFormation on `stack/*`;
- S3, SSM and ECR on the CDK bootstrap resources (`cdk-*`);
- `ecr:GetAuthorizationToken`;
- `iam:PassRole` on `cdk-*` roles;
- `amplify:StartDeployment`.

It assumes the account is already bootstrapped. It does not cover `cdk bootstrap`, which needs IAM permissions to create roles and policies.

It is **not enough** for LedgerLens as the code stands:
- **VPC lookup.** Outside the cached account and region (see [Cached lookups](#cached-lookups-cdkcontextjson)), the default VPC and AZ lookups need the CDK lookup role or `ec2:Describe*` permissions. The policy has neither.
- **Frontend deploy.** `scripts/deploy-frontend.py` uploads to the main stack's staging bucket, whose name CloudFormation generates (not `cdk-*`). It also calls `amplify get-job` and `amplify get-app`. The policy allows only `amplify:StartDeployment` and `cdk-*` buckets.

Its resources use wildcards such as `arn:aws:cloudformation:*:*:stack/*`. Scope them to your ARNs before using it anywhere that matters. The team doesn't use this policy: it deploys with `deploy-with-codebuild.py`, whose permissions are listed in [scripts/README.md](../scripts/README.md#permissions).

## Development workflow

1. Change the TypeScript in `lib/`.
2. Run `npm test`.
3. Run `npx cdk diff` to see what will change.
4. Run `npx cdk deploy --all`, or name one stack.

Which stack to deploy after each kind of change is in [Updating](../docs/DEPLOYMENT.md#updating).

For faster iteration, use watch mode:
```bash
npm run watch
```

## Troubleshooting

- **"Since this app includes more than a single stack":** add `--all` or a stack name.
- **Docker errors or "exec format error":** the machine can't build ARM64. Use `deploy-with-codebuild.py`, or set up ARM64 emulation.
- **AccessDenied, or "stack does not exist":** the command ran without `AWS_PROFILE=ledgerlens` and reached another account.
- **A deploy fails:** check the stack's events in the CloudFormation console.
- **TypeScript errors:** run `npm run build` to see them all.

More cases: [Troubleshooting](../docs/DEPLOYMENT.md#troubleshooting).

### Clean build

```bash
rm -rf node_modules cdk.out
npm ci
npm run build
```

## Learn more

- [AWS CDK Documentation](https://docs.aws.amazon.com/cdk/)
- [AWS CDK TypeScript Reference](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-construct-library.html)
- [Amazon Bedrock AgentCore Documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)
