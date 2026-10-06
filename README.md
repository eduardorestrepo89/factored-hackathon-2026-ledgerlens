# LedgerLens

LedgerLens is a customer-service agent for LATAM Bank's credit card holders. It answers questions about their cards and charges in the bank's app chat, blocks a card or opens a fraud claim when the customer confirms, and hands the case to a person with a summary. It is the team's entry to the Factored AI & Data Hackathon 2026, built on AWS from the [Fullstack AgentCore Solution Template (FAST)](https://github.com/awslabs/fullstack-solution-template-for-agentcore).

Live app: https://main.dteq5fgkcy7a4.amplifyapp.com (us-east-1). Repository: [eduardorestrepo89/ledgerlens-bank-assistant](https://github.com/eduardorestrepo89/ledgerlens-bank-assistant).

## 📚 Documentation

| Document | What it covers |
|---|---|
| [Architecture](docs/architecture.md) | Components, the request path and the security layers |
| [Structure](docs/structure.md) | What each folder holds |
| [Installation](docs/installation.md) | Setting up a development machine |
| [Technical decisions](docs/decisions.md) | Why the system is built the way it is |
| [Usage guide](docs/usage.md) | Using the app, logins and personas, smoke scripts |
| [API](docs/api.md) | The runtime invocation, the stream events, the Gateway tools and the feedback API |
| [Testing](docs/testing.md) | Unit, frontend, CDK and evaluation tests |
| [Deployment](docs/DEPLOYMENT.md) | Deploying the stacks and the frontend, and operating the data pipeline |

More docs, by topic:
- **Agent:** [agent/ledgerlens/README.md](agent/ledgerlens/README.md), [STREAMING](docs/STREAMING.md), [CONTEXT_MANAGEMENT](docs/CONTEXT_MANAGEMENT.md), [MEMORY_INTEGRATION](docs/MEMORY_INTEGRATION.md), [MCP_REGISTRY_DISCOVERY](docs/MCP_REGISTRY_DISCOVERY.md).
- **Frontend:** [frontend/README.md](frontend/README.md).
- **Gateway and auth:** [GATEWAY](docs/GATEWAY.md), [CEDAR_POLICY_GUIDE](docs/CEDAR_POLICY_GUIDE.md), [IDENTITY_POLICY](docs/IDENTITY_POLICY.md), [RUNTIME_GATEWAY_AUTH](docs/RUNTIME_GATEWAY_AUTH.md), [REPLACING_COGNITO](docs/REPLACING_COGNITO.md).
- **Data:** [LATAM_Bank_ERD](docs/LATAM_Bank_ERD.md), the [data pipeline spec](docs/superpowers/specs/2026-10-02-data-pipeline-design.md) and the [curate stage spec](docs/superpowers/specs/2026-10-03-curate-stage-design.md).
- **Operations:** [OBSERVABILITY](docs/OBSERVABILITY.md), [evals/README.md](evals/README.md) (the evaluation harness).
- **Design:** [LEDGERLENS_PRODUCT_DESIGN](docs/LEDGERLENS_PRODUCT_DESIGN.md), the [architecture diagram](docs/architecture-diagram/ledgerlens-architecture.drawio) (draw.io). `docs/superpowers/specs/` and `docs/superpowers/plans/` are dated design records: they show what was decided and when, not necessarily the current code.

## Description

Card holders contact the bank about a few recurring things: a purchase that was declined, a charge they don't recognise, a charge in another currency, a card that was lost or stolen. A generic chatbot makes them explain the problem from scratch and can't act on it. LedgerLens starts from the customer's own records and can act, but only with their consent.

What it does:
- **Knows why the customer is likely here.** At the start of a session the agent loads the customer's profile, cards, last 72 hours of card transactions, recent app signals and open cases (`get_session_context`), plus up to 3 likely reasons for the contact (`classify_call_type`). It opens with the most likely one and asks whether that's it.
- **Explains charges from the records.** Merchant, amount, status, a decline's recorded meaning and, for a charge in another currency, the amount in the card's currency at that day's rate. When the records don't explain something, it says so instead of guessing.
- **Acts only after a Yes.** Blocking a card, opening a claim and handing off to a person each wait for the customer to tap Yes on buttons in the chat.
- **Speaks the customer's language.** The data's customers are in Argentina, Colombia and México. The agent replies in Spanish, Portuguese or English, following the customer, and the UI is available in the same three languages.

A typical journey, a charge the customer doesn't recognise:
1. The agent finds the charge (`list_card_transactions`) and explains it (`explain_transaction`).
2. It can check the charge with the bank's fraud engine (`transaction_fraud_detection`). The verdict is never shown to the customer and never starts the fraud flow on its own: the customer saying they don't recognise the charge does.
3. It offers to block the card. The app shows Yes/No, then a demo identity check; only Yes runs `block_credit_card`.
4. It lists the card's recent charges, asks which ones the customer doesn't recognise, and opens a fraud claim for them (`open_claim`, again behind Yes/No). It gives the claim id and, when the bank's history has one, how long similar claims usually take.
5. If the customer asks for a person, it hands off (`human_agent_hand_off`) with a summary. The screen splits into the customer's phone and a human agent's desk, so the person continues in the same chat and the customer repeats nothing. The desk is a front-end demo: the hand-off tool calls no other service.

Other journeys: a declined purchase, a pending or reversed charge, a foreign-currency charge, "which card?", a card that isn't active, and out-of-scope requests (loans, limit increases), which go to a person. The data is the organizer's synthetic LATAM Bank dataset.

## Quick start

**Use the live app.** Open https://main.dteq5fgkcy7a4.amplifyapp.com. Self sign-up is off, so ask the team for a login. Each login is linked to one customer; without that link the agent can't read any data. See [Logins and personas](docs/usage.md#logins-and-personas).

**Deploy.** From the repo root, with the AWS CLI profile `ledgerlens` (the commands use bash syntax; Git Bash works on Windows):

```bash
AWS_PROFILE=ledgerlens python scripts/deploy-with-codebuild.py   # data stack, then main stack, built on CodeBuild
AWS_PROFILE=ledgerlens python scripts/deploy-frontend.py         # build the frontend and publish it to Amplify
```

A first deployment also needs the organizer's S3 keys, a data load and logins. [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) has the full steps.

**Run the frontend locally** against the deployed backend:

```bash
AWS_PROFILE=ledgerlens python scripts/deploy-frontend.py --config-only   # writes frontend/public/aws-exports.json
cd frontend && npm install && npm run dev                                # http://localhost:3000
```

## Technologies used

| Area | Technology |
|---|---|
| Frontend | React 19, TypeScript 5.9, Vite 8, Tailwind CSS 4, shadcn/ui (Radix UI), Lucide icons, React Router 6, react-markdown 10, react-oidc-context 3 with oidc-client-ts 3, three.js with React Three Fiber (the sign-in scene) |
| Agent | Python 3.13 container on AgentCore Runtime, Strands Agents 1.32.0, bedrock-agentcore 1.4.7, MCP 1.28.1, PyJWT 2.13 |
| Model | Claude Haiku 4.5 on Amazon Bedrock through the global inference profile (`global.anthropic.claude-haiku-4-5-20251001-v1:0`), with a Bedrock guardrail. Evaluation logins may switch to DeepSeek V3.2 or gpt-oss-120b. |
| AgentCore | Runtime, Memory (short-term), Gateway (MCP), Policy (Cedar), Observability, Evaluations (used by the eval harness) |
| Identity | Amazon Cognito: managed login, Authorization Code grant for customers, client credentials for the agent, a V3 pre-token Lambda |
| Tools and data | AWS Lambda (Python 3.13, ARM64) with psycopg 3, Aurora DSQL behind a PrivateLink endpoint, Amazon S3, AWS Step Functions, AWS CodeBuild, DuckDB 1.5 (transform and curate), aurora-dsql-loader 3.3.0 |
| Infrastructure | AWS CDK v2 in TypeScript (aws-cdk-lib 2.260), Amplify Hosting, API Gateway and DynamoDB (feedback), Secrets Manager, SSM Parameter Store |
| Development | ruff 0.14, pytest, Vitest 4 with Testing Library, Jest 30 (CDK), ESLint 9, Prettier 3, uv (smoke and data scripts) |

## Quick installation

You need git, Python 3.11+, Node.js 20.19+ or 22.12+, and the AWS CLI v2 with the `ledgerlens` profile. Full steps, including Windows notes: [docs/installation.md](docs/installation.md).

1. Clone the repo:

   ```bash
   git clone https://github.com/eduardorestrepo89/ledgerlens-bank-assistant.git
   cd ledgerlens-bank-assistant
   ```

2. Install the Python test dependencies and the frontend (`requirements-dev.txt` doesn't install: its CDK pins conflict):

   ```bash
   python -m pip install pytest -r agent/ledgerlens/requirements.txt -r data_load/requirements.txt
   cd frontend && npm install && cd ..
   ```

3. Point the frontend at the deployed backend and start it, as in [Quick start](#quick-start).

## Architecture (summary)

Two CDK stacks plus a frontend on Amplify. The data stack (`ledgerlens-bank-assistant-data`) holds Aurora DSQL, its VPC endpoint, the tool IAM roles and the data pipeline. The main stack (`ledgerlens-bank-assistant`) holds the Amplify app, Cognito, the AgentCore Runtime, Memory and Gateway, the Cedar policy, the guardrail, the 9 tool Lambdas and the feedback API. The tool Lambdas live in the main stack but use the data stack's VPC, roles and DSQL host, so the data stack deploys first.

One chat turn:
1. The browser loads the React app from AWS Amplify Hosting.
2. The customer signs in through Cognito's managed login (Authorization Code grant) and gets a user JWT.
3. The frontend sends the message to the AgentCore Runtime with that JWT and reads the answer as a stream. The Runtime's JWT authorizer validates it against the user pool. The agent takes the user's identity from the validated token, never from the request body.
4. The agent gets a machine token for the Gateway: it POSTs to Cognito's `/oauth2/token` itself (client credentials), passing the verified user id in `aws_client_metadata`. The V3 pre-token Lambda looks that user up in `USER_CUSTOMER_IDS_MAP` and adds a `customer_id` claim, blank when the login isn't linked.
5. The agent reads `customer_id` from that token. `CustomerIdHook` overwrites `customer_id` on every tool call with it, so the model is never the source of the value.
6. On a session's first turn, the agent calls `get_session_context` and `classify_call_type` and keeps the result in the agent state. It renders it into the system prompt on every turn, out of reach of the conversation window. AgentCore Memory keeps the conversation and that state.
7. The agent calls Claude Haiku 4.5 on Amazon Bedrock, behind a guardrail that blocks prompt attacks, harmful content and topics unrelated to banking. The guardrail masks nothing.
8. The agent calls the 9 tools on the AgentCore Gateway (MCP) with the machine token. The Gateway's Cedar policy has three rules:
   1. Only a token with a non-blank `customer_id` can use the tools.
   2. No call may carry a `customer_id` different from the token's.
   3. `block_credit_card` and `open_claim` need `customer_confirmed` set to true.
9. Before `block_credit_card`, `open_claim` and `human_agent_hand_off` run, `ConfirmationHook` pauses the call and the frontend shows Yes/No buttons. Only a click on Yes runs the call and sets `customer_confirmed`, so the flag Cedar checks comes from the click, never from the model.
10. The Gateway invokes the tool Lambda. The DSQL tools run in the data stack's VPC and reach Aurora DSQL only through its private endpoint: the read tools as `ll_read`, `block_credit_card` and `open_claim` as `ll_write`. `human_agent_hand_off` uses no database and runs outside the VPC.
11. Thumbs up/down feedback goes through API Gateway (Cognito authorizer) to a Lambda that writes to DynamoDB.

An evaluation harness ([evals/](evals/README.md)) runs scripted cases against the deployed agent. Logins in the Cognito group `evaluators` may switch the model and base prompt per session; the hooks, guardrail and Cedar apply to them as to customers.

Full description: [docs/architecture.md](docs/architecture.md). Diagram: [docs/architecture-diagram/ledgerlens-architecture.drawio](docs/architecture-diagram/ledgerlens-architecture.drawio) (open it in draw.io).

## LedgerLens database (Aurora DSQL)

Aurora DSQL holds a curated slice of the organizer's LATAM Bank dataset: 1,500 coherent customers (10 pinned demo personas among them) plus a 159-customer defect cohort kept as delivered for evaluation. That is 270,866 rows across the 13 tables, in the `public` schema. S3 `clean/` keeps all 23,495,188 repaired rows. The database lives in the data stack, which deploys without the agent backend or the frontend.

- **Pipeline:** a Step Functions state machine runs ingest, transform (repairs R1–R6), curate (rules C1–C12, then the customer selection) and load on CodeBuild, then a read-check Lambda. It runs on demand.
- **Tool access:** the read tools connect as `ll_read` (IAM role `ledgerlens-tools`, SELECT only). `block_credit_card` and `open_claim` connect as `ll_write` (IAM role `ledgerlens-write-tools`): SELECT on `products`, `transactions` and `complaints`, UPDATE on `products`, INSERT on `complaints`. Both connect only from inside the VPC, through the private endpoint.
- **The loader's exception:** the loader (CodeBuild) is the only identity allowed in from outside the VPC.
- **No laptop access:** the cluster policy refuses laptops, admin credentials included. Ad-hoc queries need a temporary exception in that policy.

Design: the [data pipeline spec](docs/superpowers/specs/2026-10-02-data-pipeline-design.md) and the [curate stage spec](docs/superpowers/specs/2026-10-03-curate-stage-design.md). Customers and personas: [datathon/docs/analysis/2026-10-03-curated-customers.md](datathon/docs/analysis/2026-10-03-curated-customers.md). Code: `data_load/`, `infra-cdk/lib/data-stack.ts`, `infra-cdk/lib/data-construct.ts`.

Loading the data, rerunning a stage, the reload downtime, cost and deleting the cluster: [docs/DEPLOYMENT.md, Operating the data pipeline](docs/DEPLOYMENT.md#operating-the-data-pipeline).

## Project structure

```
ledgerlens-bank-assistant/
├── agent/
│   ├── ledgerlens/          # Strands agent: ledgerlens_agent.py, Dockerfile
│   │   └── tools/           # system prompt, hooks (customer_id, confirmation), guardrail, memory, session context
│   └── utils/               # auth.py (Gateway token), ssm.py
├── gateway/
│   ├── policies/policy.cedar   # the Gateway's Cedar policy
│   └── tools/               # 9 tool Lambdas, one folder each with tool_spec.json:
│                            #   list_credit_cards, list_card_transactions, get_session_context,
│                            #   classify_call_type, explain_transaction, transaction_fraud_detection,
│                            #   block_credit_card, open_claim, human_agent_hand_off
├── infra-cdk/
│   ├── bin/ledgerlens-cdk.ts   # CDK app entry
│   ├── lib/                 # ledgerlens-app.ts, data-stack.ts, ledgerlens-main-stack.ts, *-construct.ts, utils/
│   ├── lambdas/             # cedar-policy, dsql-read-check, feedback, oauth2-provider, pretoken-v3, zip-packager
│   ├── test/                # Jest tests
│   └── config.yaml          # deployment configuration (model, memory, scope)
├── frontend/                # React + Vite app (see frontend/README.md)
├── data_load/               # data pipeline stages (python -m data_load)
├── evals/                   # evaluation harness: cases, graders, runner, report
├── scripts/                 # deploy-with-codebuild.py, deploy-frontend.py
├── test-scripts/            # smoke scripts against the deployed stack
├── tests/unit/              # pytest unit tests
├── datathon/                # data analysis and research notes
├── docker/                  # docker-compose for running the agent and frontend containers locally
├── docs/                    # documentation
└── Makefile                 # lint, lint-cicd, load-data
```

Folder by folder: [docs/structure.md](docs/structure.md).

## License

Apache-2.0, see [LICENSE](LICENSE). The project is forked from AWS's FAST template; [NOTICE](NOTICE) keeps its notices. It is a hackathon prototype on synthetic data, not a production banking system.
