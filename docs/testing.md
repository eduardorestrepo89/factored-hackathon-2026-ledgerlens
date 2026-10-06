# Testing

LedgerLens has three offline test suites and two kinds of checks against the deployed stack:

| Suite | Where | Command | Touches AWS | Size |
|---|---|---|---|---|
| Python unit tests | `tests/unit/` | `python -m pytest` | no | 2,696 tests, about a minute |
| Frontend | `frontend/src/test/` | `npm run build && npm test` | no | 17 files, 146 tests |
| CDK | `infra-cdk/test/` | `npm test` | no (and no Docker) | 6 suites, 69 tests, about 2 minutes |
| Evaluations | `evals/` | `python -m evals.runner ...` | yes, and it costs money | scripted cases × models × runs |
| Smoke scripts | `test-scripts/` | `uv run ... test-scripts/<script>.py` | yes | manual |

No coverage tool is configured for any suite.

## Python unit tests

Install the dependencies first ([installation.md, step 3](installation.md#3-install-dependencies)), then run from the repo root:

```bash
python -m pytest                                              # everything under tests/
python -m pytest tests/unit/open_claim                        # one tool
python -m pytest tests/unit/test_confirmation_hook.py -k typed  # tests whose name matches
```

- **Configuration.** `testpaths = ["tests"]` comes from `[tool.pytest.ini_options]` in `pyproject.toml`.
- **The `PytestUnknownMarkWarning` lines are harmless.** The `unit` and `integration` markers are registered in `tests/pytest.ini`, but from the repo root pytest reads `pyproject.toml` instead.
- **Run from the repo root.** `data_load` and `evals` are imported as top-level packages from there.

### How the tests import the code

The tool Lambdas and the agent import their own code by the names their runtime uses (`block_credit_card_lambda...`, `tools...`, `utils...`), not by repo paths. So the tests put each folder on `sys.path` the way its runtime does:
- **Tool Lambdas.** Each `tests/unit/<tool>/conftest.py` puts `gateway/tools/<tool>` on `sys.path`. That folder is the Lambda's asset root, so `<tool>_lambda.delivery.handler` imports exactly as the Lambda handler string resolves it.
- **The agent.** The agent tests add `agent/ledgerlens` (for `tools.*`) or `agent/` (for `utils.*`) to `sys.path` and import with `importlib`, matching the Docker image's `/app/tools` and `/app/utils`.
  - Some stub a runtime-only module in `sys.modules` first: `strands.hooks` in the hook tests, `bedrock_agentcore.runtime` in `test_auth_claims.py`.
  - `test_confirmation_hook.py`'s stub mirrors strands-agents 1.32.0's `interrupt()`: it raises until a response is set.
- **Files that can't be imported by name** are loaded from their path with `importlib.util.spec_from_file_location`:
  - the pre-token Lambda (`infra-cdk/lambdas/pretoken-v3/index.py`);
  - the Cedar policy custom resource, with `boto3.client` patched first;
  - the DSQL read-check Lambda;
  - `scripts/deploy-frontend.py` and `scripts/deploy-with-codebuild.py`.

### Strategy

The unit tests need no AWS account or database. They pass with every AWS credential and profile removed from the environment.

**The 9 tools.** Every tool but the hand-off has the same layers: `domain`, `application` (use case and ports), `infrastructure` (DSQL repository, SQL file loader) and `delivery` (handler, presenter, settings, wiring). Each layer is tested on its own:
- **Use cases** against fake repositories (`fakes.py` in each tool's test folder): validation, the agent-facing error messages, the write tools' `customer_confirmed` check.
- **Presenters:** the exact JSON the model sees (2-decimal amount strings, ISO dates, `null` sections).
- **Handlers:**
  - the tool-name check;
  - the mapping of failures to `{"error": ...}` with no raw exception text.
- **DSQL repository and connectors** against fake psycopg connections: IAM auth tokens, connection recycling, failures.
- **Settings:** environment parsing, such as `AS_OF` and the database engine.
- **Drift tests:**
  - `test_query_contracts.py` checks that the SQL files match the Python contracts and `data_load/schema.sql`;
  - `human_agent_hand_off/test_tool_spec.py` checks that `tool_spec.json` matches the use case's rules.

**The agent:** the hooks, the session-start context, the prompt, the guardrail settings, the eval override and the stream filter, each against stubs.

**The system prompt is pinned.** `test_system_prompt.py` pins the hash of every released `PROMPT_VERSION`, so an edit to `BASE_SYSTEM_PROMPT` without a version bump fails. The steps for a prompt change are in [CONTRIBUTING.md](../CONTRIBUTING.md#changing-the-system-prompt).

**The data pipeline:**
- tiny hand-built tables (`data_load_fixtures.py`, `curate_fixtures.py`);
- an in-memory S3 (`data_load_s3.py`);
- a fake DSQL connection.

**The eval harness:** fake Cognito, a fake `send` and httpx's `MockTransport`.

### What each file covers

| Path under `tests/unit/` | Covers |
|---|---|
| `list_credit_cards/`, `list_card_transactions/`, `get_session_context/`, `classify_call_type/`, `explain_transaction/`, `transaction_fraud_detection/`, `block_credit_card/`, `open_claim/`, `human_agent_hand_off/` | One folder per Gateway tool, layered as above. Tool-specific extras include `test_transaction_filters.py`, `test_reason_ranking.py`, `test_call_reasons.py`, `test_decline_codes.py`, `test_fraud_bands.py`, `test_fraud_check_request.py` and `test_text_folding.py`. |
| `cedar_policy/` | The Cedar policy custom resource creates one policy per statement. |
| `pretoken_v3/` | The pre-token Lambda's `customer_id` claim from `USER_CUSTOMER_IDS_MAP`, blank for a missing, invalid or unmapped entry. |
| `test_customer_id_hook.py`, `test_confirmation_hook.py` | The agent's two tool hooks: `customer_id` overwrite and cancel; Yes/No pause, resume, typed reply as No. |
| `test_session_context.py`, `test_system_prompt.py`, `test_conversation_memory.py` | Session-start context, the prompt builder and its pinned versions, the short-term memory window and summarization. |
| `test_auth_claims.py`, `test_auth_customer_id.py` | Reading the runtime JWT's claims and the Gateway token's `customer_id`. |
| `test_eval_override.py`, `test_guardrail.py`, `test_leaked_markup.py`, `test_mcp_registry.py` | The evaluators' override gate, the guardrail settings, the stream's markup filter, Agent Registry discovery. |
| `test_data_load_*.py`, `test_dsql_read_check.py` | Every pipeline stage: CLI, ingest, source fingerprints, transform and repairs R1–R6, curate and rules C1–C12, DDL, DSQL steps, run records; the read check (`ll_read` reads every table and is refused an `INSERT`). |
| `eval_harness/` | The eval harness: cases, config, graders, metrics, runner, stream parser, report, CloudWatch dashboard, AWS evaluation, eval users. |
| `test_deploy_frontend.py`, `test_deploy_with_codebuild.py` | `--config-only` writes `aws-exports.json` for localhost; CodeBuild deploys every stack or only those named. |
| `test_tool_requirements.py` | The tool Lambdas bundle only what the Python runtime lacks. |

`tests/integration/` holds only an `__init__.py`: there are no integration tests. The end-to-end checks are the smoke scripts and the evaluations below.

## Frontend tests

```bash
cd frontend
npm ci
npm run build    # build.test.ts checks frontend/build, so build first
npm test         # vitest --run; `npm run test:watch` to rerun on save
```

- **Setup:** Vitest with jsdom and Testing Library (`vitest.config.ts`, setup file `src/test/setup.ts`).
- **No config file needed:** the suite passes without `frontend/public/aws-exports.json`.
- **Without a build,** `build.test.ts` fails, since it checks `frontend/build`.

| File | Covers |
|---|---|
| `confirm-card.test.tsx`, `confirmation-flow.test.tsx` | The Yes/No card, the biometric check before a block, and the request that answers a confirmation |
| `handoff.test.ts`, `handoff-ticket.test.tsx`, `handoff-flow.test.tsx` | Parsing the hand-off result, the ticket, and the split into the phone and the agent desk |
| `strands-parser.test.ts`, `tool-renderer.test.ts` | Turning the SSE stream into UI events; picking a renderer per tool |
| `chat-messages.test.tsx`, `components.test.tsx` | Message list scrolling and component integration |
| `i18n.test.tsx` | Language and theme switching |
| `config.test.ts`, `env.test.ts`, `routing.test.ts`, `build.test.ts` | Configuration, environment variables, routing, the build output |
| `property-auth-routing.test.tsx`, `property-config-compatibility.test.ts`, `property-env-vars.test.ts` | Property-based tests (fast-check) of auth routing and configuration |

## CDK tests

```bash
cd infra-cdk
npm ci
npm test         # Jest with ts-jest, test/*.test.ts
```

- **No Docker, no AWS.** The tests build the stacks in memory with the context `aws:cdk:bundling-stacks: []`, which skips Docker bundling, and assert on the synthesized templates.
- **The `ts-jest[config] (WARN) ... TS151002` lines are harmless.**

| File | Covers |
|---|---|
| `ledgerlens-cdk.test.ts` | Both stacks build, the main stack depends on the data stack, `deploy_scope` from `config.yaml` and `-c`, the Amplify security headers |
| `data-construct.test.ts`, `data-stack.test.ts` | The DSQL cluster policy (only the loader from outside the VPC), the tool roles never admin, the VPC endpoint, the read check, the Step Functions stages, CodeBuild getting the secret's name and never its value |
| `backend-gateway.test.ts` | One Gateway target per tool, tool names within Bedrock's 64-character limit, every Cedar action naming a deployed target and its `tool_spec.json` tool, the hand-off Lambda outside the VPC, the guardrail, the runtime's memory settings |
| `policy-cedar.test.ts` | Every forbid lists its actions; the write tools are forbidden unless `customer_confirmed` is present and true |
| `config-manager.test.ts` | Reading and validating `config.yaml` |

## Evaluations

The harness in `evals/` runs scripted cases against the **deployed** agent, signed in as the evaluation logins. It grades each session locally and can score it again with AgentCore Evaluations. Setup, commands and results: [evals/README.md](../evals/README.md).

Every run costs money:
- **Run `--dry-run` first.** It prints the job list and a cost estimate.
- **Always pass `--max-cost`.** It stops new sessions once the estimate passes the limit (default $15).
- **Follow the harness rules.** No case may click Yes on `block_credit_card` or `open_claim`; the loader refuses it. Never edit `USER_CUSTOMER_IDS_MAP` during a run.
- **Results stay local.** They go to `evals/results/`, which is gitignored.

## Smoke scripts

`test-scripts/test-gateway.py` (Gateway and Cedar without the agent), `test-agent.py` (chat with the deployed agent), `test-feedback-api.py` and `test-memory.py` check a deployment by hand. How to run them: [usage.md, Smoke scripts](usage.md#smoke-scripts) and [test-scripts/README.md](../test-scripts/README.md).

## CI

The workflows in `.github/workflows/` run only on pushes and pull requests to `main`:

| Workflow | What it runs |
|---|---|
| `python-lint.yml` | `ruff check` and `ruff format --check` on the changed `.py` files (Python 3.11) |
| `js-lint.yml` | On changed frontend files: `npm ci`, ESLint and Prettier on them, then `npm run build && npm test` (Node 20) |
| `ash-security-scan.yml`, `ash-full-repository-scan.yml`, `ash-security-comment.yml` | AWS Automated Security Helper scans and their PR comments; the full scan also runs monthly |

Two consequences:
- **Two suites never run in CI.** No workflow runs `pytest` or the CDK tests.
- **Pull requests into `stage` get no CI at all,** because the team's pull requests target `stage`, not `main`.

So run the three offline suites yourself before opening a pull request ([CONTRIBUTING.md](../CONTRIBUTING.md#checks-before-a-pull-request)).
