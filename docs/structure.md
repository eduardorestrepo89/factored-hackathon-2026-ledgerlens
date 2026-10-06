# Project structure

The repository is a fork of the AWS "Fullstack AgentCore Solution Template" (FAST). LedgerLens replaced its sample agent and tool with a banking agent, nine Gateway tools, an Aurora DSQL data stack, a data pipeline and an evaluation harness. Some FAST files remain as they were; this page says which.

## Directory tree

Generated folders are left out (`node_modules`, `.git`, `__pycache__`, `cdk.out`, `build`, `.venv`). Of the nine tool folders, only `list_credit_cards` is expanded; the others have the same layout.

```text
factored-hackathon-2026-ledgerlens/
├── agent/                                  # The agent that runs on AgentCore Runtime
│   ├── ledgerlens/
│   │   ├── Dockerfile                      # ARM64 image; build context is the repo root
│   │   ├── README.md
│   │   ├── ledgerlens_agent.py             # Entrypoint: invocations(), create_strands_agent()
│   │   ├── requirements.txt                # strands-agents 1.32.0, bedrock-agentcore 1.4.7, mcp, PyJWT
│   │   └── tools/
│   │       ├── confirmation_hook.py        # Yes/No interrupts for the three action tools
│   │       ├── conversation_memory.py      # Short-term memory window and optional summarization
│   │       ├── customer_id_hook.py         # Overwrites customer_id on every tool call
│   │       ├── eval_override.py            # Per-session model/prompt override for evaluators
│   │       ├── gateway.py                  # MCP client for the Gateway (Approach 1 active)
│   │       ├── guardrail.py                # BedrockModel guardrail settings
│   │       ├── leaked_markup.py            # Strips leaked tool-call markers from the stream
│   │       ├── mcp_registry.py             # Optional MCP discovery from an Agent Registry (off)
│   │       ├── session_context.py          # Session-start context in agent.state
│   │       └── system_prompt.py            # BASE_SYSTEM_PROMPT, PROMPT_VERSION = "v12"
│   └── utils/
│       ├── auth.py                         # JWT claims, Gateway token, customer_id claim
│       └── ssm.py                          # SSM parameter reads
├── gateway/
│   ├── policies/policy.cedar               # The three Cedar statements
│   └── tools/
│       ├── list_credit_cards/              # One tool = one folder = one Lambda asset
│       │   ├── tool_spec.json              # MCP tool schema the Gateway publishes
│       │   ├── requirements.txt            # psycopg[binary] only
│       │   └── list_credit_cards_lambda/
│       │       ├── domain/
│       │       │   ├── entities/credit_card.py
│       │       │   └── errors.py           # Agent-facing DomainError messages
│       │       ├── application/
│       │       │   ├── ports/              # database_repository.py, query_provider.py, errors.py
│       │       │   └── use_cases/list_credit_cards.py
│       │       ├── infrastructure/
│       │       │   ├── queries/file_query_provider.py
│       │       │   └── repositories/dsql_repository.py
│       │       ├── queries/postgresql/list_credit_cards.sql
│       │       ├── utils/connectors/       # base.py (PsycopgConnector), dsql.py (DsqlConnector)
│       │       └── delivery/
│       │           ├── handler.py          # Lambda entry point
│       │           ├── settings.py
│       │           ├── dependencies/dependencies_builder.py
│       │           └── presenters/credit_cards.py
│       ├── list_card_transactions/         # + domain/value_objects/transaction_filters.py
│       ├── get_session_context/            # 5 SQL files, one per context section
│       ├── classify_call_type/             # + domain/services/reason_ranking.py, value_objects/
│       ├── explain_transaction/            # + value_objects/decline_codes.py, text_folding.py
│       ├── transaction_fraud_detection/    # + value_objects/fraud_bands.py, fraud_check_request.py
│       ├── block_credit_card/              # write tool: ll_write, 40001 retries
│       ├── open_claim/                     # write tool: ll_write, 40001 retries, 23505 mapping
│       └── human_agent_hand_off/           # domain, application, delivery only: no database
├── infra-cdk/                              # AWS CDK app (TypeScript)
│   ├── bin/ledgerlens-cdk.ts               # Reads config.yaml, calls buildStacks()
│   ├── config.yaml                         # Stack name, deploy_scope, model, memory, as_of
│   ├── cdk.json, cdk.context.json          # CDK settings; cached AZ and default-VPC lookups
│   ├── minimal-deploy-policy.json          # Reference IAM policy for a local deploy (FAST)
│   ├── lib/
│   │   ├── ledgerlens-app.ts               # Builds the data stack, then the main stack
│   │   ├── data-stack.ts                   # <stack_name_base>-data
│   │   ├── data-construct.ts               # DSQL, VPC endpoint, roles, CodeBuild, Step Functions
│   │   ├── ledgerlens-main-stack.ts        # <stack_name_base>
│   │   ├── amplify-hosting-construct.ts    # Amplify app, staging bucket, security headers
│   │   ├── cognito-construct.ts            # User pool, clients, evaluators group, pre-token Lambda
│   │   ├── backend-construct.ts            # Runtime, Memory, Gateway, tool Lambdas, Cedar, feedback API
│   │   └── utils/
│   │       ├── agent-guardrail.ts          # Bedrock Guardrail
│   │       ├── agentcore-role.ts           # Runtime execution role
│   │       └── config-manager.ts           # Loads and validates config.yaml
│   ├── lambdas/
│   │   ├── cedar-policy/                   # Custom resource: policy engine, policies, ENFORCE attach
│   │   ├── dsql-read-check/                # Pipeline's last step: read as ll_read, INSERT must fail
│   │   ├── feedback/                       # POST /feedback handler
│   │   ├── oauth2-provider/                # Custom resource: AgentCore OAuth2 credential provider
│   │   ├── pretoken-v3/                    # Adds customer_id to the machine token
│   │   └── zip-packager/                   # Only for backend.deployment_type: zip
│   └── test/                               # Jest: stacks, Gateway targets, Cedar file, config
├── data_load/                              # The data pipeline (python -m data_load <stage>)
│   ├── __main__.py                         # ingest, transform, curate, load, access, check
│   ├── source.py, ingest.py                # Stage 1: list, fingerprint and copy the organizer's files
│   ├── transform.py, repair.py             # Stage 2: typed load in DuckDB, repairs R1-R6, link checks
│   ├── curate.py, curate_rules.py, curate_select.py   # Stage 3: rules C1-C12, gates, selection, cohort
│   ├── dsql.py, ddl.py                     # Stage 4: tables, roles, IAM mappings, loader, indexes
│   ├── runrecord.py                        # runs/<run-id>/<stage>.json
│   ├── schema.sql                          # 13 tables, ll_read / ll_write, grants, indexes
│   ├── expected.json                       # Pinned row, repair and curation counts
│   ├── personas.json                       # The 10 demo personas and alternates
│   └── requirements.txt
├── frontend/                               # React 19 + Vite + TypeScript + Tailwind
│   ├── index.html, vite.config.ts, vitest.config.ts, eslint.config.mjs, components.json
│   ├── public/                             # favicons; aws-exports.json is generated here (gitignored)
│   └── src/
│       ├── main.tsx, App.tsx
│       ├── routes/                         # ChatPage (the only route)
│       ├── app/context/GlobalContext.tsx
│       ├── components/
│       │   ├── auth/                       # OIDC provider, sign-in screen, 3D lens scene
│       │   ├── chat/                       # ChatInterface, ConfirmCard, HandOffTicket, AgentDesk, ...
│       │   ├── loaders/
│       │   └── ui/                         # shadcn/Radix primitives
│       ├── hooks/                          # useAuth, useToolRenderer
│       ├── lib/
│       │   ├── agentcore-client/           # client.ts, parsers/strands.ts, utils/sse.ts
│       │   ├── auth.ts                     # OIDC config from aws-exports.json
│       │   ├── handoff.ts                  # Hand-off detection and desk state
│       │   └── i18n.tsx                    # es / pt / en copy
│       ├── services/feedbackService.ts
│       ├── styles/, types/
│       └── test/                           # Vitest suites
├── evals/                                  # Evaluation harness (own venv: evals/.venv)
│   ├── cases.yaml, cases.py                # 10 scripted cases and their loader
│   ├── runner.py, stream.py                # Run sessions against the runtime; digest the SSE stream
│   ├── graders.py                          # Local checks and unsafe-reply detectors
│   ├── aws_eval.py                         # AgentCore Evaluations scoring
│   ├── report.py, metrics.py, cw_dashboard.py   # Statistics, metric families, CloudWatch dashboard
│   ├── eval_users.py, config.py            # Evaluation logins; shared settings
│   └── prompts/                            # v10.md, v11.md, v12.md (v12 pinned to the released prompt)
├── tests/                                  # pytest unit tests (no AWS)
│   ├── conftest.py, pytest.ini
│   ├── unit/
│   │   ├── <tool>/                         # One package per tool: conftest, fakes, one test file per module
│   │   ├── cedar_policy/, pretoken_v3/, eval_harness/
│   │   └── test_*.py                       # Agent modules, data_load stages, deploy scripts
│   └── integration/                        # Empty package
├── scripts/
│   ├── deploy-with-codebuild.py            # cdk deploy on an ephemeral ARM CodeBuild project
│   ├── deploy-frontend.py                  # Build the SPA and push it to Amplify (--config-only for local)
│   └── utils.py, requirements.txt, README.md
├── test-scripts/                           # Manual checks against a deployment
│   └── test-agent.py, test-gateway.py, test-memory.py, test-feedback-api.py
├── docker/                                 # Docker Compose for local runs (out of date, see below)
├── docs/
│   ├── architecture.md, structure.md, decisions.md, installation.md,
│   │   usage.md, api.md, testing.md, DEPLOYMENT.md   # Living documentation (the README links the full set)
│   ├── LEDGERLENS_PRODUCT_DESIGN.md        # Product design: journeys, tools, security, prompt
│   ├── LATAM_Bank_ERD.md                   # The dataset's 13 tables and their links
│   ├── GATEWAY.md, CEDAR_POLICY_GUIDE.md, IDENTITY_POLICY.md, RUNTIME_GATEWAY_AUTH.md, REPLACING_COGNITO.md,
│   │   STREAMING.md, CONTEXT_MANAGEMENT.md, MEMORY_INTEGRATION.md, MCP_REGISTRY_DISCOVERY.md,
│   │   OBSERVABILITY.md                    # Feature guides, updated for LedgerLens (started from FAST's)
│   ├── AGENTCORE_*.md, AGENT_CONFIGURATION.md, SESSION_MANAGEMENT.md, LOCAL_*.md, BEDROCK_*.md
│   │                                       # FAST guides not updated; candidates for deletion
│   ├── architecture-diagram/ledgerlens-architecture.drawio
│   ├── evaluation/                         # Final evaluation report (HTML), report data, SVG diagrams
│   ├── hackathon_final_doc/                # Pitch and final submission pages
│   ├── handoffs/                           # Dated hand-off notes between work sessions
│   └── superpowers/
│       ├── specs/                          # 16 dated design specs (YYYY-MM-DD-<topic>-design.md)
│       └── plans/                          # 17 dated implementation plans
├── datathon/                               # Research and data analysis
│   ├── analysis/                           # Profiling SQL and scripts, with their outputs
│   ├── docs/analysis/                      # Dated findings: data, diagnostics, curated customers, evals
│   ├── reports/                            # Research reports (use cases, evaluation, dashboard metrics)
│   └── research_notes/                     # Sources behind each report
├── .github/workflows/                      # Lint and ASH security scans
├── .superdesign/design-system.md           # Visual design system for the frontend
├── Makefile                                # lint targets; load-data starts the pipeline
├── pyproject.toml, ruff.toml, requirements-dev.txt
├── .kics.yml, .prettierrc, .dockerignore, .gitignore
└── README.md, CONTRIBUTING.md, LICENSE, NOTICE
```

## What each folder is for

### `agent/`
The code AgentCore Runtime runs. `ledgerlens/ledgerlens_agent.py` is the only entry point: it validates the request, resolves the model and prompt, fetches the Gateway token, builds a Strands agent for this request, loads the session context and streams the reply. Each concern the entry point wires in lives in its own module under `tools/` (the name comes from FAST; these are agent modules, not Gateway tools). `utils/` holds the token and SSM helpers.

- **Goes here:** anything that runs inside the agent process: hooks, prompt text, memory configuration, stream filters.
- **Doesn't:** bank logic or data access. The agent reaches data only through Gateway tools, and its IAM role has no DSQL permission.
- **Change rules:** editing the prompt template means bumping `PROMPT_VERSION` (`tests/unit/test_system_prompt.py` pins its hash) and keeping `evals/prompts/<version>.md` in sync (a unit test compares them).

### `gateway/`
The Gateway's tools and the policy that guards them. `tools/<tool>/` is deployed as a Lambda named `ledgerlens-<tool-with-dashes>`; `tool_spec.json` is the schema the model sees. `policies/policy.cedar` is loaded by CDK, which strips its `//` comments and fills in the Gateway ARN.

- **Adding a tool** means a new folder, a `toolTargets` entry in `backend-construct.ts` and the tool's action in the Cedar statements; without the last step Cedar denies it.

### `infra-cdk/`
The CDK app. `bin/ledgerlens-cdk.ts` reads `config.yaml`, and `lib/ledgerlens-app.ts` builds the data stack, then the main stack on top of it (`deploy_scope: data` builds only the first). `lambdas/` holds the infrastructure Lambdas, as opposed to the Gateway tools: custom resources for what CloudFormation lacks (the Cedar policy engine, the OAuth2 credential provider), the pre-token trigger, the feedback handler and the pipeline's read check. The tool Lambdas are built from `gateway/tools/` by `backend-construct.ts`.

### `data_load/`
The data pipeline as a Python package. CodeBuild runs `python -m data_load $STAGE` for ingest, transform, curate and load, plus `access` on demand; `check` runs locally. `schema.sql` is the single definition of the 13 tables, the two roles, their grants and the indexes, used both by DuckDB in the transform and by DSQL in the load. `expected.json` and `personas.json` are inputs the stages check against, so a change there is a change to what the pipeline accepts.

### `frontend/`
The customer's chat and the human agent desk, as a static SPA. It needs `public/aws-exports.json`, which `scripts/deploy-frontend.py` writes from the main stack's outputs (the Cognito authority and client, the runtime ARN, the feedback URL). `lib/agentcore-client/` is the only code that talks to the runtime. The hand-off desk has no backend: it lives in the same browser.

### `evals/`
The evaluation harness. It runs against the deployed agent with evaluation logins, so its results reflect the real Gateway, Cedar, guardrail and data. It has its own virtual environment (`evals/.venv`); run outputs go to `evals/results/` (gitignored), and the final committed report is in `docs/evaluation/`.

### `tests/`, `infra-cdk/test/`, `frontend/src/test/`
- `tests/unit/`: pytest, no AWS or database. Each tool has its own package with a `conftest.py` that puts the tool's asset root on `sys.path` (as the Lambda runtime does) and `fakes.py` with fake ports and connectors. `test_tool_requirements.py` checks that the DSQL tools it lists bundle `psycopg[binary]` and not `boto3` (the Lambda runtime ships it), and that the hand-off tool bundles nothing.
- `infra-cdk/test/`: Jest assertions on the synthesized templates: the cluster policy, roles, state-machine order, Gateway targets (including the 64-character tool-name limit) and the Cedar file.
- `frontend/src/test/`: Vitest, including the confirmation and hand-off flows and the Strands stream parser.

### `scripts/` and `test-scripts/`
`scripts/` deploys: the stacks through CodeBuild, the frontend to Amplify. `test-scripts/` are manual probes of a live deployment: chat with the agent, call the Gateway as a given user, read Memory, post feedback.

### `docker/`
FAST's Docker Compose setup for running the agent and frontend locally. It is out of date: it passes only `MEMORY_ID`, `STACK_NAME` and AWS credentials, while the agent now requires `MODEL_ID`, `GUARDRAIL_ID` and `GUARDRAIL_VERSION` to answer.

### `docs/` and `datathon/`
See the last section for which files are kept current.

## Layers inside a tool Lambda

Every DSQL tool follows the same layout. The dependency direction is fixed: `delivery` builds everything and calls `application`; `application` depends on `domain` and on its own ports; `infrastructure` and `utils/connectors` implement those ports. `domain` imports nothing from the other layers.

| Layer | Holds | Must not contain |
|---|---|---|
| `domain/entities/`, `value_objects/`, `services/` | Frozen dataclasses for what the tool returns; rules that need no I/O (fraud bands, decline-code meanings, reason ranking, accent folding) | `boto3`, `psycopg`, SQL, `os.environ`, JSON shaping |
| `domain/errors.py` | `DomainError` subclasses. Each message tells the agent what happened and what to do next ("Don't retry; offer a hand-off") | Hosts, SQL, driver output, exception text |
| `application/ports/` | ABCs: `DatabaseRepository.execute_query(query, params)`, `QueryProvider.get(name)`, and the port errors adapters must raise | Any implementation |
| `application/use_cases/` | Input cleaning and validation, the query names, parameters, row-to-entity mapping, and the translation of port errors into domain errors | SQL text, driver imports, environment reads, Lambda event or response shapes |
| `queries/postgresql/*.sql` | One statement per file with psycopg named placeholders (`%(customer_id)s`) and a header comment listing the parameters and who uses the file | Values built in Python with string formatting |
| `infrastructure/queries/` | `FileQueryProvider`: reads `<name>.sql` from the dialect folder, caches it, rejects names outside `[a-z0-9_]+` | Business rules |
| `infrastructure/repositories/` | `DsqlRepository`: runs the statement, maps SQLSTATEs to port errors, retries what is safe to retry | Which query to run; domain errors |
| `utils/connectors/` | `PsycopgConnector` (cached connection, max age, reset) and `DsqlConnector` (IAM token, connection options) | Queries |
| `delivery/settings.py` | Environment variables to typed, validated settings (`DB_ENGINE`, `DSQL_CLUSTER_ENDPOINT`, `DSQL_DB_USER`, `MAX_ROWS`, `AS_OF`) | Defaults that widen access: the write tools default to `ll_write` and never fall back to `ll_read` |
| `delivery/dependencies/` | The only place objects are constructed, once per container at cold start. Every object it builds is stateless between requests | Per-request state on any object |
| `delivery/presenters/` | Entity to JSON-safe dict: ISO dates, amounts as 2-decimal strings, `null` for missing values | Decisions about what the customer may see beyond the field list |
| `delivery/handler.py` | Checks the tool name in the Gateway client context, calls the use case, returns `{"content": [...]}` or `{"error": message}` | Business logic; returning `str(exception)` |

Rules across tools:
- **No imports across tool folders.** Shared-looking code (connectors, repository, query provider) is copied into each tool. A fix to a copy has to be made in every tool that holds one.
- **Two copies of the repository.** The read tools' `DsqlRepository` retries only lost connections. The write tools' copy also retries `40001` and maps `23505`. Don't copy a write repository into a read tool or the other way around.
- **Every write must stay idempotent** (a guarded `UPDATE`, or an `INSERT` whose key is a hash of its content), because the repository retries after a lost connection.
- `human_agent_hand_off` has only `domain/`, `application/use_cases/` and `delivery/`: it has no ports because it calls nothing.

## Living code and docs vs point-in-time records

| Kept current with the code | Point-in-time records |
|---|---|
| All code folders: `agent/`, `gateway/`, `infra-cdk/`, `data_load/`, `frontend/`, `evals/`, `tests/`, `scripts/`, `test-scripts/` | `docs/superpowers/specs/` and `plans/`: dated design records, each with a status line. They explain why things were built, but describe the state on their date: the 2026-09-29 data-loading spec is superseded, early specs place the tool Lambdas in the data stack and run the frontend locally, and plans quote code that has since changed |
| `docs/architecture.md`, `structure.md`, `decisions.md`, `installation.md`, `usage.md`, `api.md`, `testing.md`, `DEPLOYMENT.md` and the other pages the README links | `docs/handoffs/`: notes passed between work sessions on 2026-10-04 |
| `docs/LEDGERLENS_PRODUCT_DESIGN.md` and `docs/LATAM_Bank_ERD.md`: reference material, updated by the specs that changed them | `docs/evaluation/`: the final evaluation report and data from the 2026-10-05 runs |
| | `docs/hackathon_final_doc/`: the pitch and the final submission |
| | `datathon/`: research notes, data profiling and dated analyses written before and during the build |
| | `docker/`: kept from FAST and not maintained |

The FAST feature guides in `docs/` (`AGENTCORE_*.md`, `GATEWAY.md`, `MEMORY_INTEGRATION.md`, `STREAMING.md`, ...) came with the template and explain the AgentCore features in general. Where one of them and the code disagree, the code wins, as it does for every record above. A new decision gets its own dated spec rather than an edit to an old one; a spec that changes an earlier one says so in its header.
