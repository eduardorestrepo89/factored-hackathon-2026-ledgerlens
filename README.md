# Fullstack AgentCore Solution Template (FAST)

_Author's note: for the official name for this solution is the "Fullstack Solution Template for Agentcore" but it is referred to throughout this code base as FAST for convenience._

The Fullstack AgentCore Solution Template (FAST) is a starter project repository that enables users (delivery scientists and engineers) to quickly deploy a secured, web-accessible React frontend connected to an AgentCore backend. Its purpose is to accelerate building full stack applications on AgentCore from weeks to days by handling the undifferentiated heavy lifting of infrastructure setup and to enable vibe-coding style development on top. The only central dependency of FAST is AgentCore. It is agnostic to agent SDK (this repository's agent uses Strands) and to coding assistant platforms (Q, Kiro, Cline, Claude Code, etc).

FAST is designed with security and vibe-codability as primary tenets. Best practices and knowledge from experts are codified in _documentation_ in this repository rather than in _code_. By including this documentation in an AI coding assistant's context, or by instructing the AI coding assistant to leverage best practices and code snippets found in the documentation, delivery scientists and developers can quickly vibe-build AgentCore applications for any use case. AI coding assistants can be used to fully customize the frontend and the infrastructure, enabling scientists to focus the areas where their knowledge is most impactful: the actual prompt engineering and GenAI implementation details.

With FAST as a starting point and development framework, delivery scientists and engineers will accelerate their development process and deliver production quality AgentCore code following architecture and security best practices without having to learn any frontend or infrastructure code.

## FAST Baseline System

FAST comes deployable out-of-the-box with a fully functioning, full-stack application. This application represents starts as a basic multi-turn chat agent where the backend agent has access to tools. **Do not let this deter you, even if your use case is entirely different! If your application requires AgentCore, customizing FAST to any use case is extremely straightforward. That is the intended use of FAST!**

The application is intentionally kept very, very simple to allow developers to easily build up whatever they want on top of the baseline. The tools shipped out of the box include:

1. **Gateway Tools** - Lambda-based tools behind AgentCore Gateway with authentication:
   - Text analysis tool (counts words and letter frequency)

Try asking the agent to analyze text to see these tools in action.


## FAST User Setup

If you are a delivery scientist or engineer who wants to use FAST to build a full stack application, this is the section for you.

FAST is designed to be forked and deployed out of the box with a security-approved baseline system working. Your task will be to customize it to create your own full stack application to do (literally) anything on AgentCore.

Deploying the full stack out-of-the-box FAST baseline system is only a few cdk commands once you have forked the repo, namely: 

```bash
cd infra-cdk
npm install
cdk bootstrap # Once ever
cdk deploy
cd ..
python scripts/deploy-frontend.py
```

See the [deployment guide](docs/DEPLOYMENT.md) for detailed instructions on how to deploy FAST into an AWS account.

What comes next? That's up to you, the developer. With your requirements in mind, open up your coding assistant, describe what you'd like to do, and begin. The steering docs in this repository help guide coding assistants with best practices, and encourage them to always refer to the documentation built-in to the repository to make sure you end up building something great.

## LedgerLens Database (Aurora DSQL)

Aurora DSQL holds a curated slice of the organizer's LATAM Bank dataset: 1,500 coherent customers (10 pinned demo personas among them) plus a 159-customer defect cohort kept as delivered for evaluation, 270,866 rows across the 13 tables. S3 `clean/` keeps all 23,495,188 repaired rows. The database lives in its own stack, `ledgerlens-bank-assistant-data`, which deploys without the agent backend or the frontend.
- **Design:** [docs/superpowers/specs/2026-10-02-data-pipeline-design.md](docs/superpowers/specs/2026-10-02-data-pipeline-design.md) and [docs/superpowers/specs/2026-10-03-curate-stage-design.md](docs/superpowers/specs/2026-10-03-curate-stage-design.md).
- **Customers and personas:** [datathon/docs/analysis/2026-10-03-curated-customers.md](datathon/docs/analysis/2026-10-03-curated-customers.md).
- **Code:** `data_load/`, `infra-cdk/lib/data-stack.ts` and `infra-cdk/lib/data-construct.ts`.

**What's in it:**
- **One schema:** `public`, holding the 13 tables with their delivered columns: the repairs R1–R6 applied in the transform (pipeline spec section 6), then the curation rules C1–C12 applied in curate (curate spec section 5) to every customer except the defect cohort.
- **Tool access:**
  - The read tools connect as `ll_read` (IAM role `ledgerlens-tools`, SELECT only).
  - `block_credit_card` and `open_claim` connect as `ll_write` (IAM role `ledgerlens-write-tools`): UPDATE on `products`, INSERT on `complaints`.
  - Both connect only from inside the stack's VPC, through the private host `DsqlPrivateHost`.
- **The loader's exception:** the loader (CodeBuild) is the only identity allowed in from outside the VPC.
- **No laptop access:** laptops are refused, admin credentials included. Ad-hoc queries need a temporary exception in the cluster policy (spec section 7.3).

**Deploy only the database:**

```bash
AWS_PROFILE=ledgerlens python scripts/deploy-with-codebuild.py ledgerlens-bank-assistant-data
```

The script deploys from an ARM CodeBuild machine, because local Docker can't bundle the ARM64 Lambdas without emulation. Without stack names, it deploys every stack, as before.

**Set the organizer's S3 keys (once):** write a JSON file outside the repo with `aws_access_key_id`, `aws_secret_access_key`, `bucket`, `region` (`us-east-2`) and `prefix` (`data/`), then:

```bash
aws secretsmanager put-secret-value --profile ledgerlens --secret-id ledgerlens/hackathon-s3 --secret-string file://<file-outside-the-repo>.json
```

Delete the file afterwards and never commit it.

**Load the data (about 10 minutes, under $1):**

```bash
AWS_PROFILE=ledgerlens make load-data
# without make:
arn=$(aws stepfunctions list-state-machines --profile ledgerlens --query "stateMachines[?name=='ledgerlens-data-pipeline'].stateMachineArn" --output text)
aws stepfunctions start-execution --profile ledgerlens --state-machine-arn "$arn"
```

- **Stages:** the pipeline runs ingest → transform → curate → load → read check. Each stage writes `runs/<run-id>/<stage>.json` in the team bucket. Curate fixes per-customer incoherence (rules C1–C12) and selects the customers; load reads `curated/<run-id>/`.
- **Retuning the selection:** rerun `curate`, then `load`, for the same run (about 6 minutes); transform isn't rerun.
- **Downtime:** a load drops and recreates the 13 tables, so the tools see missing tables for about 2 minutes. Never reload during a demo.
- **Rerunning one stage** of an existing run:

  ```bash
  aws codebuild start-build --profile ledgerlens --project-name ledgerlens-data-load \
    --environment-variables-override name=STAGE,value=<stage>,type=PLAINTEXT name=RUN_ID,value=<run-id>,type=PLAINTEXT
  ```

- **After a manual rerun,** run the read check yourself:

  ```bash
  aws lambda invoke --profile ledgerlens --function-name ledgerlens-dsql-read-check out.json
  ```

- **Adding a tool role to a loaded cluster:** after a data stack deploy that adds a role, run the `access` stage once. It creates the roles, maps them to their IAM roles and re-runs the grants, without touching the data:

  ```bash
  aws codebuild start-build --profile ledgerlens --project-name ledgerlens-data-load \
    --environment-variables-override name=STAGE,value=access,type=PLAINTEXT
  ```

**Check for an organizer re-upload:** this uses the `hackathon` profile for the organizer's bucket and the `ledgerlens` profile for the team bucket.

```bash
uv run --no-project --with-requirements data_load/requirements.txt python -m data_load check --run <run-id> --team-bucket <team-bucket>
```

**Cost:**
- **While the stack exists:** about $9.70 a month, mostly the private endpoint ($7.30).
- **Deleting the stack keeps the cluster** (deletion protection). To get to zero, also run:

  ```bash
  aws dsql update-cluster --profile ledgerlens --identifier <cluster-id> --no-deletion-protection-enabled
  aws dsql delete-cluster --profile ledgerlens --identifier <cluster-id>
  ```

- **Redeploying after a delete:** redeploying the data stack after deleting it creates a new, empty cluster.

## LedgerLens Agent (v1)

The Strands agent on AgentCore Runtime answers card questions from the signed-in customer's own records, through three read tools on the Gateway: `list_credit_cards`, `list_card_transactions` and `get_session_context`.
- **Design:** [docs/superpowers/specs/2026-10-03-v1-agent-wiring-design.md](docs/superpowers/specs/2026-10-03-v1-agent-wiring-design.md).
- **Prompt:** `agent/ledgerlens/tools/system_prompt.py`. Bump `PROMPT_VERSION` on any change; `tests/unit/test_system_prompt.py` pins each version's hash.

**Deploy:** the data stack first (it holds the tool Lambdas), then the agent stack:

```bash
AWS_PROFILE=ledgerlens python scripts/deploy-with-codebuild.py ledgerlens-bank-assistant
```

**Run the frontend locally** (nothing is deployed to Amplify in v1):

```bash
AWS_PROFILE=ledgerlens python scripts/deploy-frontend.py --config-only
cd frontend && npm install && npm run dev   # http://localhost:3000
```

**Demo login:** one Cognito user, `demo@ledgerlens.example`, linked to one persona at a time. Create it once after the first deploy. The password must have 8+ characters with upper, lower, digit and symbol; share it with the team and the judges, never in git.

```bash
export AWS_PROFILE=ledgerlens
POOL_ID=$(aws cloudformation describe-stacks --stack-name ledgerlens-bank-assistant \
  --query "Stacks[0].Outputs[?OutputKey=='CognitoUserPoolId'].OutputValue" --output text)
aws cognito-idp admin-create-user --user-pool-id "$POOL_ID" --username demo@ledgerlens.example \
  --user-attributes Name=email,Value=demo@ledgerlens.example Name=email_verified,Value=true \
  --message-action SUPPRESS
aws cognito-idp admin-set-user-password --user-pool-id "$POOL_ID" \
  --username demo@ledgerlens.example --password "$DEMO_PASSWORD" --permanent
SUB=$(aws cognito-idp admin-get-user --user-pool-id "$POOL_ID" --username demo@ledgerlens.example \
  --query "UserAttributes[?Name=='sub'].Value" --output text)
```

**Switch persona:** the pre-token Lambda's `USER_CUSTOMER_IDS_MAP` links the login to a customer. Either edit it in the Lambda console (`ledgerlens-bank-assistant-pretoken-v3` → Configuration → Environment variables), or run:

```bash
set_persona() {  # usage: set_persona <customer_id>
  aws lambda update-function-configuration --function-name ledgerlens-bank-assistant-pretoken-v3 \
    --cli-input-json "$(python -c 'import json,sys; print(json.dumps({"Environment": {"Variables": {"USER_CUSTOMER_IDS_MAP": json.dumps({sys.argv[1]: sys.argv[2]})}}}))' "$SUB" "$1")" \
    --query "Environment.Variables" --output text
  aws lambda wait function-updated --function-name ledgerlens-bank-assistant-pretoken-v3
}
set_persona CLI-50OIF5EIYSWK   # P05
```

- **Start a new chat after every switch.** The old chat's memory still holds the previous persona's data.
- **Who can switch:** only someone with AWS credentials. The person chatting never can.
- **After a redeploy:** the login goes back to the persona committed in `USER_CUSTOMER_IDS_MAP` in `infra-cdk/lib/cognito-construct.ts`. Commit the demo login's sub there, mapped to P03, right after creating it: until then a redeploy resets the map to placeholders and the login becomes unlinked.

| Persona | Customer id | Use case | v1 note |
|---|---|---|---|
| P01 | CLI-1GL7QBDG3QG0 | Decline explained | The tools return no decline reason, so the agent says it can't tell why |
| P02 | CLI-7EC6UCDZMSKV | Pending charge | |
| **P03 (default)** | CLI-70U0WJ1NH1MN | Reversed charge with app context | Shows the session-start opening |
| P04 | CLI-N4FPJIEGD917 | Which card? | |
| P05 | CLI-50OIF5EIYSWK | Portuguese persona, foreign charge | |
| P06 | CLI-PV0OIEA8DAAE | Limit increase (out of scope) | |
| P07 | CLI-EX6BOAOEFZHQ | Suspected fraud | Can't block: the agent says a human must, and gives a summary |
| P08 | CLI-GG3Z1440277M | Open unrecognized-charge case | No hand-off tool: a text hand-off |
| P09 | CLI-UBR2NCZWTD4K | Records contradict | No decline reason in the tools, so the contradiction can't be seen |
| P10 | CLI-Z3V3SBS18YWQ | Card not active | |

**Smoke scripts** (`AWS_PROFILE=ledgerlens`, with `uv run --no-project --with-requirements test-scripts/requirements.txt python ...`):
- `test-scripts/test-gateway.py --user-sub "$SUB" [--customer-id <id>]`: the Gateway and Cedar, without the agent. A sub that isn't in the map tests an unlinked login.
- `test-scripts/test-agent.py`: chats with the deployed agent as the demo login.


## Architecture

The diagram is [`docs/architecture-diagram/ledgerlens-architecture.drawio`](docs/architecture-diagram/ledgerlens-architecture.drawio) (open it in draw.io). One chat turn goes through it like this:
1. The browser loads the React app from AWS Amplify Hosting.
2. The customer signs in to the Cognito user pool (Authorization Code grant) and gets a user JWT.
3. The frontend calls the AgentCore Runtime with that JWT, which the Runtime validates against Cognito. The Strands agent builds its system prompt from the session context (`get_session_context` and `classify_call_type`).
4. AgentCore Memory keeps the short-term conversation history.
5. The agent calls `deepseek.v3.2` on Amazon Bedrock, behind a Bedrock guardrail.
6. AgentCore Identity's Token Vault gets an M2M token from Cognito (client credentials); the V3 Pre-Token Lambda adds the customer's `customer_id` claim.
7. The agent calls tools on the AgentCore Gateway (MCP) with that token.
8. The Gateway's Cedar policy engine allows a call only when the token has a `customer_id` and the call's `customer_id` input matches it.
9. The Gateway invokes the tool Lambda. Before `block_credit_card`, `open_claim` and `human_agent_hand_off` run, the customer confirms with Yes/No buttons.
10. The tool Lambdas run in the data stack's VPC and reach Aurora DSQL only through its VPC endpoint: the read tools as `ll_read`, the write tools as `ll_write`. `human_agent_hand_off` uses no database and runs outside the VPC.
11. Feedback goes through API Gateway (Cognito authorizer) to a Lambda and DynamoDB.

The data stack's pipeline (Step Functions and CodeBuild: ingest, transform, curate, load, then a read check) loads the organizer's data into DSQL on demand.

### Tech Stack

- **Frontend**: React with TypeScript, Vite, Tailwind CSS, and shadcn components - infinitely flexible and ready for coding assistants
- **Agent Provider**: Strands agent (`agent/ledgerlens/`) running within AgentCore Runtime
- **Authentication**: AWS Cognito User Pool with OAuth support for easy swapping out Cognito
- **Infrastructure**: CDK deployment with Amplify Hosting for frontend and AgentCore backend

## Project Structure

```
fullstack-agentcore-solution-template/
├── .github/                # GitHub Actions workflows
│   └── workflows/
├── docker/                 # Docker development environment
│   ├── docker-compose.yml  # Local development stack
│   └── Dockerfile.frontend.dev # Frontend development container
├── frontend/               # React frontend application
│   ├── src/
│   │   ├── app/            # Application pages
│   │   ├── components/     # React components (shadcn/ui)
│   │   ├── hooks/          # Custom React hooks
│   │   ├── lib/            # Utility libraries
│   │   │   └── agentcore-client/ # AgentCore streaming client
│   │   ├── routes/         # React Router routes
│   │   ├── services/       # API service layers
│   │   ├── styles/         # Global styles
│   │   ├── test/           # Frontend tests
│   │   └── types/          # TypeScript type definitions
│   ├── public/             # Static assets
│   ├── components.json     # shadcn/ui configuration
│   ├── vite.config.ts      # Vite configuration
│   └── package.json
├── infra-cdk/              # CDK infrastructure code
│   ├── lib/                # CDK stack definitions
│   │   ├── utils/          # Shared CDK utilities
│   │   ├── amplify-hosting-stack.ts
│   │   ├── backend-stack.ts
│   │   ├── cognito-stack.ts
│   │   └── ledgerlens-main-stack.ts
│   ├── bin/                # CDK app entry point
│   ├── lambdas/            # Lambda function code
│   │   ├── cedar-policy/    # Cedar Policy Engine lifecycle
│   │   ├── oauth2-provider/ # OAuth2 Credential Provider lifecycle
│   │   ├── pretoken-v3/     # Cognito V3 Pre-Token Generation Lambda
│   │   ├── feedback/       # Feedback API handler
│   │   └── zip-packager/   # Runtime ZIP packager
│   └── config.yaml         # Deployment configuration
├── agent/                  # Agent implementation
│   ├── ledgerlens/         # LedgerLens Strands agent
│   │   ├── ledgerlens_agent.py  # Agent implementation
│   │   ├── tools/          # Agent-side helpers (Gateway client, memory, guardrail, prompt)
│   │   ├── Dockerfile      # Container configuration
│   │   ├── requirements.txt # Agent dependencies
│   │   └── README.md       # Agent overview
│   └── utils/              # Shared agent utilities
│       ├── auth.py         # Authentication helpers
│       └── ssm.py          # SSM parameter helpers
├── gateway/                # Gateway utilities and tools
│   ├── policies/           # Cedar policy definitions
│   │   └── policy.cedar    # Per-customer access control policy
│   └── tools/              # Gateway tool implementations (deployed in the data stack)
│       ├── list_credit_cards/
│       ├── list_card_transactions/
│       └── get_session_context/
├── scripts/                # Deployment and utility scripts
│   ├── deploy-frontend.py  # Cross-platform frontend deployment
│   └── utils.py            # Shared script utilities
├── test-scripts/           # Testing scripts
│   ├── test-agent.py       # Agent testing
│   ├── test-feedback-api.py # Feedback API testing
│   ├── test-gateway.py     # Gateway testing
│   └── test-memory.py      # Memory testing
├── tests/                  # Test suite
│   ├── unit/               # Unit tests
│   ├── integration/        # Integration tests
│   └── conftest.py         # Pytest configuration
├── docs/                   # Documentation source files
│   ├── architecture-diagram/ # Architecture diagrams
│   ├── DEPLOYMENT.md       # Deployment guide
│   ├── LOCAL_DEVELOPMENT.md # Local development guide
│   ├── AGENT_CONFIGURATION.md # Agent setup guide
│   ├── MEMORY_INTEGRATION.md # Memory integration guide
│   ├── GATEWAY.md          # Gateway integration guide
│   ├── IDENTITY_POLICY.md  # Identity propagation & Cedar policy guide
│   ├── CEDAR_POLICY_GUIDE.md # Cedar policy syntax, capabilities & reference
│   ├── REPLACING_COGNITO.md # Identity provider swap & Gateway interceptors guide
│   ├── RUNTIME_GATEWAY_AUTH.md # M2M authentication workflow
│   ├── SESSION_MANAGEMENT.md # Session persistence & resumption guide
│   ├── CONTEXT_MANAGEMENT.md # Context window management guide
│   ├── STREAMING.md        # Streaming implementation guide
│   ├── OBSERVABILITY.md    # Observability overview (telemetry & logging)
│   ├── AGENTCORE_TELEMETRY.md # AgentCore telemetry enablement guide
│   └── BEDROCK_MODEL_INVOCATION_LOGGING.md # Bedrock model invocation logging guide
├── Makefile                # Project-level build commands
└── README.md
```

## DeepWiki
Have a question about how FAST works? Consider asking DeepWiki!


[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/awslabs/fullstack-solution-template-for-agentcore)

## Security

Note: this asset represents a proof-of-value for the services included and is not intended as a production-ready solution. You must determine how the AWS Shared Responsibility applies to their specific use case and implement the needed controls to achieve their desired security outcomes. AWS offers a broad set of security tools and configurations to enable our customers.

Ultimately it is your responsibility as the developer of a full stack application to ensure all of its aspects are secure. We provide security best practices in repository documentation and provide a secure baseline but Amazon holds no responsibility for the security of applications built from this tool.

## License

This project is licensed under the Apache-2.0 License.
