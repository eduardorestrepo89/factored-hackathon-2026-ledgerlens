# Technical decisions

The decisions that shape LedgerLens, with what each one costs and what was rejected. Most were made in dated design specs under [`docs/superpowers/specs/`](superpowers/specs/); each entry links its source. When a spec and the code disagree, the code is current: several specs were later superseded, and the entries below say so where it matters.

How the pieces fit together is in [architecture.md](architecture.md).

## Scope

### One journey with three exits

- **Decision.** Build one journey, "¿Qué es este cargo?" (what is this charge?), with three exits: the charge is **explained** (read-only), the card is **secured** (a confirmed block with read-back) or the case goes to **dispute intake** and a human. Everything the agent can do serves that journey: 6 read tools, 2 write tools, 1 hand-off.
- **Why.** The data analysis found that the dataset is a system-of-record simulator: it can ground answers about specific records, but it has no behavioral links between events, no learnable labels for priority or escalation, and template-only transcripts. Unrecognized-charge complaints are the largest grounded demand (18.3% of complaints), and this journey is the only option that runs the full understand → decide → act → verify → escalate loop with a real write and a structured hand-off.
- **Trade-off.** Requests outside cards and charges (loans, limit increases, investments, personal data changes) are declined and handed off, never served.
- **Rejected.** Account and payment inquiries (mostly read-only, the human case is forced), card support alone (no dispute path), credit eligibility (no valid target).
- **Source.** [`datathon/docs/analysis/2026-09-26-data-findings-and-workflow-decision.md`](../datathon/docs/analysis/2026-09-26-data-findings-and-workflow-decision.md), DEC-5.

## Data

### Aurora DSQL as the only database

- **Decision.** All bank data lives in Aurora DSQL: the organizer's 13 tables in `public`. The tool Lambdas connect with psycopg using IAM auth tokens. Aurora DSQL replaced the first tool's Aurora PostgreSQL connector on 2026-09-30.
- **Why.** DSQL is serverless and PostgreSQL-compatible, so the relational data model and plain SQL stay. Tools sign a 15-minute IAM token locally for each connection, so there's no database password, Secrets Manager secret or RDS Proxy. Only the connector, the repository's error mapping and the wiring changed in the swap; the domain, use case, SQL file and handler didn't.
- **Trade-off.** DSQL's differences from PostgreSQL leak into the code:
  - no foreign keys, `TRUNCATE` or materialized views;
  - `statement_timeout` and `default_transaction_read_only` are rejected, so there's no per-query timeout and the role grants are the only write guard;
  - optimistic concurrency, so writes retry SQLSTATE `40001`;
  - connections close after 60 minutes, transactions stop at 300 s, queries at 128 MiB;
  - indexes only build asynchronously.
- **Rejected.** Aurora PostgreSQL with credentials in Secrets Manager (`AuroraPostgreSQLConnector`, `DB_SECRET_ARN`, `DB_STATEMENT_TIMEOUT_MS`), removed rather than kept beside DSQL.
- **Source.** [DSQL engine spec](superpowers/specs/2026-09-30-dsql-engine-design.md) §1-2; `docs/LEDGERLENS_PRODUCT_DESIGN.md` §4.

### VPC-only database access, laptops refused

- **Decision.** Three access layers: IAM (only the two tool roles have `dsql:DbConnect`, only the loader has `dsql:DbConnectAdmin`), database roles (`ll_read` SELECT-only, `ll_write` limited to blocking cards and inserting claims), and a cluster resource policy that denies both connect actions unless the request comes through the stack's VPC, except for the loader role. The tools reach the cluster through a PrivateLink endpoint.
- **Why.** IAM alone would let anyone with admin credentials connect from anywhere. With the cluster policy, a connection from a laptop is refused even with the `ledgerlens` admin profile; this was tested on the first cloud run ("FATAL: unable to accept connection, access denied").
- **Trade-off.**
  - The endpoint is about 80% of the data stack's monthly cost ($7.30 of about $9.70).
  - Nobody can query the data by hand. Ad-hoc access needs a temporary `aws:PrincipalArn` exception in the policy and a redeploy.
  - The evaluation harness can't restore rows from a laptop, so its cases never click Yes on a block or a claim.
  - The account root user, and any principal allowed `dsql:PutClusterPolicy`, can still lift the network layer.
- **Rejected.** IAM permissions alone.
- **Source.** [Pipeline spec](superpowers/specs/2026-10-02-data-pipeline-design.md) D8, §7, §11.4, §13 check 4; `infra-cdk/lib/data-construct.ts`.

### The default VPC in one AZ

- **Decision.** The stack uses the account's default VPC instead of creating one. The DSQL endpoint and every DSQL Lambda share one subnet in one AZ. The subnets are public, but Lambda network interfaces get no public IP, so the tools have no internet path and reach only the endpoint.
- **Why.** Each extra AZ costs another endpoint interface, and the stack creates no NAT gateway, subnet or route.
- **Trade-off.** Anything else running in the default VPC passes the cluster policy's `aws:SourceVpc` check, so IAM, the database roles and the endpoint's security group carry more of the weight. One AZ means no zone redundancy for the tools.
- **Rejected.** A dedicated isolated VPC (the first version, replaced on 2026-10-02); a multi-AZ endpoint.
- **Source.** [Pipeline spec](superpowers/specs/2026-10-02-data-pipeline-design.md) §7.2; `data-construct.ts` comments.

### A staged pipeline instead of a direct load

- **Decision.** The data goes through ingest, transform, curate and load, each a CodeBuild run selected by `STAGE`, then a read-check Lambda, chained by a Step Functions state machine. Each stage writes its output and a run record (`runs/<run-id>/<stage>.json`) to the team bucket. `schema.sql` is the contract in both DuckDB and DSQL, and `expected.json` pins every count.
- **Why.**
  - The source is static (7,671 files uploaded once), so it runs once, but as a real pipeline: raw data lands first, and only ingest needs the organizer's keys.
  - Step Functions shows the run as a graph, and each stage reruns on its own.
  - CodeBuild has no 15-minute limit. The read check is a Lambda because it must run where the tools run.
  - Checking types, constraints, lengths and links in DuckDB first means nothing reaches DSQL unless all of them pass.
  - DuckDB plus AWS's `aurora-dsql-loader` leaves parallelism, retries and token refresh to the loader.
- **Trade-off.** More moving parts than a script. A reload drops and recreates the tables, so tools fail for about 2 minutes during a load.
- **Rejected.** A load reading the organizer's bucket directly (the 2026-09-29 design); a scheduled daily replay; ELT inside DSQL; AWS Glue (too much for 5 GB); one Lambda per stage (15-minute limit); a local script or CloudShell; our own batched inserts (we would own OCC retries and token refresh); a load manifest table in the database.
- **Source.** [Pipeline spec](superpowers/specs/2026-10-02-data-pipeline-design.md) D1-D3, D9; [data-loading spec](superpowers/specs/2026-09-29-data-loading-design.md) D2, D4 (superseded).

### Repairs in place and no foreign keys

- **Decision.** Six repairs (R1-R6) fix broken links and impossible dates in place. A link that can't be proven becomes `NULL`; no row is deleted. DSQL gets no foreign keys; the transform checks all 24 declared links, ownership and date order instead.
- **Why.** The schema stays as delivered, and `NULL` already means "no link" in the data. Deleting the 10,422 customers without products, for example, would also delete about 1M rows of their history. When this was decided nothing wrote after the load, so a foreign key would have protected nothing, and it would slow 23.5M inserts and force parent-first ordering.
- **Trade-off.** Repaired values replace the originals in the database; the originals survive only in `raw/`. The write tools added later have to keep links valid themselves: `open_claim` only accepts transactions that its query finds on the customer's own credit cards.
- **Rejected.** Repaired values in extra columns; deleting rows; foreign keys on the clean links.
- **Source.** [Pipeline spec](superpowers/specs/2026-10-02-data-pipeline-design.md) D6, D7, §6.

### A curate stage with a defect cohort

- **Decision.** A separate curate stage applies twelve rules (C1-C7 derive values from other columns, C8-C12 are labelled synthetic) to every row, then loads only 1,500 coherent customers (125 per country × segment cell, 10 pinned personas first) plus 159 customers kept as delivered, covering 17 defect classes.
- **Why.** Each customer's statuses, expiry dates, codes and cases are independent random draws, so the raw data contradicts itself inside one customer, and about 97% of customers have no card charge in the last 3 days before `as_of`. An agent can only be judged on records that agree. The defect cohort still tests behavior on bad data, with evidence row ids per class. As a separate stage it reruns alone in minutes while the selection is tuned, and the full repaired data stays in `clean/`.
- **Trade-off.** The served data is curated, partly synthetic, and much smaller (270,866 rows). The upside: the load dropped from about 24 minutes to 1.2, DSQL writes about 1.2% of the rows the full load wrote, and storage fits the free tier.
- **Rejected.** Curating inside transform (a retune would rerun it and lose the full data); the curated set beside the full data in a second schema; rules applied only to the selected customers (counts would drift); a blanket card reissue for C8 (it would erase 239 correct "expired card" declines); proportional allocation.
- **Source.** [Curate spec](superpowers/specs/2026-10-03-curate-stage-design.md) E1-E11, §13.1; [`datathon/docs/analysis/2026-10-03-curated-customers.md`](../datathon/docs/analysis/2026-10-03-curated-customers.md).

### C2 in plain Python, not a DuckDB UDF

- **Decision.** Rule C2 (`amount_usd` for ARS and COP rows) is computed with Python's float `round(amount / rate, 2)`.
- **Why.** That expression reproduces all 1,887,552 stored `amount_usd` values; DuckDB's `round` misses 1,089 half-cents.
- **Rejected.** A DuckDB Python UDF: it needs numpy and ran about 600× slower (95 s per 200,000 rows).
- **Source.** [Curate spec](superpowers/specs/2026-10-03-curate-stage-design.md) §2.

### A fixed bank date as a query rule

- **Decision.** The bank's "today" is `as_of = 2026-06-17T23:59:59`, the last day in the data. Every row is loaded; each DSQL tool gets `AS_OF` and filters events on `process_date BETWEEN <from> AND as_of`.
- **Why.** The real date (October 2026) is months past the data, so "the last 72 hours" by the wall clock would always be empty. Time is a rule in the queries, not a load window, so nothing is lost and the window can change without a reload. `process_date` is used because the business day ends at 06:00: 1,352 transactions timestamped early on 2026-06-18 belong to 2026-06-17.
- **Trade-off.** The value lives in two places, `config.yaml` (`data.as_of`) for the tools and `data_load/curate_rules.py` for curation, which must change together. Agent writes stamp `last_updated` with the same fixed time.
- **Rejected.** A load-time window (`window_years`, the 2026-09-29 design); a daily replay with a moving clock.
- **Source.** [Pipeline spec](superpowers/specs/2026-10-02-data-pipeline-design.md) D5, §5.3; [data-loading spec](superpowers/specs/2026-09-29-data-loading-design.md) D6.

## Tools

### One self-contained Lambda per tool

- **Decision.** Each Gateway tool is one folder, one Lambda asset and one function, holding every layer it needs. Code is copied between tools, never imported across folders.
- **Why.** A reader sees everything one Lambda does in one folder, and what gets packaged is exactly what is in it. Separate functions also get separate IAM roles, timeouts and Cedar actions.
- **Trade-off.** A fix to copied code (a connector, the repository) must be made in every copy. Two literals shared by two tools (the fraud bands 50 and 30) are pinned by both tools' tests so they can't drift. Each tool bundles its own `psycopg[binary]`, about 7.7 MB per function.
- **Rejected.** One shared `ledgerlens` package imported by every tool (the 2026-09-29 layout). A shared psycopg Lambda layer was designed and deferred.
- **Source.** [Self-contained tool folders spec](superpowers/specs/2026-10-01-self-contained-tool-folders-design.md) §1; [v1 wiring spec](superpowers/specs/2026-10-03-v1-agent-wiring-design.md) §11.

### Clean architecture with SQL in files

- **Decision.** Inside each tool: domain, application (use case and ports), infrastructure (adapters) and delivery layers. The use case asks a `QueryProvider` for SQL by name and runs it through a `DatabaseRepository` port; the SQL lives in `queries/postgresql/<name>.sql`.
- **Why.** Tools don't depend on a particular database. Adding a tool means a use case, a query file, a handler and a `tool_spec.json`; adding an engine means a connector, a repository and a dialect folder, selected by `DB_ENGINE`. The Aurora PostgreSQL → DSQL swap proved it. SQL in files can be read and reviewed as SQL, with its parameters documented in a header comment, and every layer can be unit-tested with fakes.
- **Trade-off.** More files per tool than a single handler would need. The engine (`aurora_dsql`) and the dialect folder (`postgresql`) are separate ideas linked by one mapping.
- **Source.** [list_card_transactions spec](superpowers/specs/2026-09-29-list-card-transactions-lambda-design.md) §1; [DSQL engine spec](superpowers/specs/2026-09-30-dsql-engine-design.md) §1.

### Idempotent single-statement writes

- **Decision.** `block_credit_card` and `open_claim` write with single autocommit statements that are safe to repeat: a guarded `UPDATE ... WHERE product_status NOT IN ('Blocked', 'Closed')` and an `INSERT` whose `complaint_id` is `CMP-` plus a hash of the claim's content. Repeats return `already_blocked` / `already_existed`. They connect as `ll_write`, whose grants are limited to `UPDATE products` and `INSERT complaints` (plus reads).
- **Why.** DSQL conflicts (`40001`) and lost connections both call for a retry, and the model may repeat a call. With idempotent statements, retrying is always safe and nothing is blocked twice or claimed twice. The repository port stays the same as for the read tools.
- **Trade-off.** Writes persist until the next full load; there is no reset stage. Smoke tests use non-demo customers.
- **Rejected.** Server-side confirmation records and an audit table (left as proposals); a `call_center_interactions` row for the hand-off (the table has no column for the summary).
- **Source.** [Write tools spec](superpowers/specs/2026-10-03-write-tools-design.md) §1, §6.

### Agent-facing error messages only

- **Decision.** A tool returns either its JSON result or `{"error": <message>}`, where the message is a fixed domain-error text telling the agent what to do next ("temporarily unavailable, offer to retry or hand off", "don't retry; offer a hand-off"). Raw exception text is logged, never returned.
- **Why.** Exception text could leak SQL, host names or driver details to the model, and from there to the customer. A fixed message also makes the model's next step predictable.
- **Rejected.** FAST's sample tool returned the exception text.
- **Source.** `gateway/tools/<tool>/<tool>_lambda/delivery/handler.py` and `domain/errors.py`.

### The fraud score is read, not learned

- **Decision.** `transaction_fraud_detection` maps the dataset's stored `fraud_score` to a verdict (`fraud` above 50, `review` above 30) and adds no heuristic. The prompt keeps scores and verdicts from the customer, and a `fraud` verdict alone never starts the fraud flow: the agent first asks whether the customer recognizes the charge.
- **Why.** The score leaks the label (the 2026-09-26 analysis found every score above 30 is fraud), so learning from it would be meaningless. Treating it as the feed of a bank fraud engine is honest about what it is.
- **Trade-off.** The bands fit this simulated dataset, not a real engine.
- **Source.** [`datathon/docs/analysis/2026-09-26-data-findings-and-workflow-decision.md`](../datathon/docs/analysis/2026-09-26-data-findings-and-workflow-decision.md) DEC-10; `transaction_fraud_detection_lambda/domain/value_objects/fraud_bands.py`.

### A short Gateway target name for the fraud tool

- **Decision.** Gateway targets are named `<slug>-target`, except `transaction_fraud_detection`, whose target is `fraud-detection-target`.
- **Why.** The model sees each tool as `gateway_<target>___<tool>`, and Bedrock rejects every request, for every tool, if one tool name is over 64 characters. `gateway_transaction-fraud-detection-target___transaction_fraud_detection` would be 72.
- **Trade-off.** One tool breaks the naming pattern, so its Cedar action is `fraud-detection-target___transaction_fraud_detection`. A CDK test checks every name against the limit and every Cedar action against the deployed targets.
- **Source.** `infra-cdk/lib/backend-construct.ts` (`toolTargets`); `infra-cdk/test/backend-gateway.test.ts`; commit `8c2855b`.

### Hand-off to a frontend desk instead of SNS

- **Decision.** `human_agent_hand_off` validates the hand-off, gives it a content-hash id and returns it. It stores and sends nothing, and runs outside the VPC. The frontend detects the result and switches to a split screen: the customer's chat beside a human agent desk where the presenter types as the agent.
- **Why.** The hand-off is meant to be the moment judges remember: the app visibly passes the conversation to a person who already has the whole case, with no manual step but the agent's first message. Everything the desk shows comes from the agent's stream, so no backend, queue or database write is needed.
- **Trade-off.** No real contact-center delivery and no multi-browser sync. A real queue would be a new adapter behind the same tool output.
- **Rejected.** Publishing to SNS (the original write-tools design).
- **Source.** [Hand-off frontend spec](superpowers/specs/2026-10-03-human-hand-off-frontend-design.md) §1-2, replacing [write tools spec](superpowers/specs/2026-10-03-write-tools-design.md) §5.

## Identity and authorization

### Direct Cognito token call instead of the Token Vault decorator

- **Decision.** The agent gets its Gateway token by calling Cognito's `/oauth2/token` itself (client credentials grant), passing `aws_client_metadata={"verified_user_id": <sub>}` ("Approach 1", `agent/utils/auth.py`).
- **Why.** Cognito hands that metadata to the V3 pre-token Lambda, which can then put the user's `customer_id` into the machine token. That token is what Cedar evaluates. AgentCore Identity's `@requires_access_token` decorator ("Approach 2") caches and refreshes tokens for you, but can't pass `aws_client_metadata`, so its token would carry no user.
- **Trade-off.**
  - The agent fetches and handles the machine client's secret itself (from Secrets Manager).
  - The user pool needs the Essentials plan, because V3 triggers are what fire on client-credentials grants.
  - The OAuth2 credential provider is still deployed but only Approach 2 would use it.
  - In VPC network mode, the runtime needs a NAT gateway, because the Cognito domain has no VPC endpoint.
- **Rejected.** Approach 2, kept commented out in `agent/ledgerlens/tools/gateway.py` with the steps to switch back.
- **Source.** `agent/ledgerlens/tools/gateway.py`, `agent/utils/auth.py`, `infra-cdk/lib/cognito-construct.ts`.

### Customer link in a pre-token Lambda map

- **Decision.** The pre-token Lambda maps a Cognito `sub` to a `customer_id` through `USER_CUSTOMER_IDS_MAP`, a JSON object in its environment, committed in `cognito-construct.ts`. An unmapped user gets a blank claim and the token is still issued; Cedar then refuses that user's tool calls.
- **Why.** There's no table and no database connection, so the trigger stays fast and never fails a token request. Switching the demo login to another persona is an edit in the Lambda console, needs no deploy, and takes effect on the next message. Only someone with AWS credentials can do it, never the person chatting.
- **Trade-off.** Demo-grade: a redeploy resets the map to the committed value, so console-only edits are lost, and a new login has to be added to the committed map and deployed to last. A switched persona needs a new chat, because the old chat's memory still holds the previous customer's data.
- **Rejected for now.** A store written by an onboarding flow, such as a DynamoDB table keyed by `sub`, is the documented path beyond the demo; the claim name and the rest of the chain wouldn't change.
- **Source.** `docs/LEDGERLENS_PRODUCT_DESIGN.md` §5.2; [v1 wiring spec](superpowers/specs/2026-10-03-v1-agent-wiring-design.md) §5; `infra-cdk/lambdas/pretoken-v3/index.py`.

### The model never supplies the customer id

- **Decision.** `customer_id` is a required input on every tool, but its value always comes from the machine token. `CustomerIdHook`, a Strands `BeforeToolCallEvent` hook, overwrites it on every call whose schema has the property, whatever the model wrote, and cancels the call when the login has no linked customer. Cedar then forbids any call whose argument differs from the token's claim, and every SQL query filters on it again.
- **Why.** The Gateway doesn't forward JWT claims to Lambda targets: a tool's event holds only its input properties. So the id has to be an input, and an input the model writes can be prompt-injected or mistyped. With the hook, a wrong id never leaves the agent; with Cedar, a hook bug still can't reach another customer's data. In the evaluation, gpt-oss mistyped the id once and the hook corrected it before the call.
- **Trade-off.** The id is enforced in three places (hook, Cedar statement 2, SQL), each to be kept in step.
- **Rejected for now.** A Gateway REQUEST interceptor that rewrites the arguments, so neither the model nor the agent handles the id. It's open whether Cedar evaluates the arguments before or after an interceptor rewrites them.
- **Source.** `docs/LEDGERLENS_PRODUCT_DESIGN.md` §5.3 (Q2, Q8); `agent/ledgerlens/tools/customer_id_hook.py`; `evals/README.md`.

### Button confirmation before any action

- **Decision.** `block_credit_card`, `open_claim` and `human_agent_hand_off` pause on a Strands interrupt until the customer taps Yes or No in the app. After a Yes, the hook itself sets `customer_confirmed: true` on the block or claim, and Cedar statement 3 forbids both tools unless that flag is present and `true`.
- **Why.** The model decides when to propose an action; the customer decides whether it runs. The value Cedar checks comes from the click, never from the model. A typed "yes" is passed to the model as words and counts as No, so only a deliberate tap acts. The interrupt and the waiting call are saved with the session, so the click resumes that exact call.
- **Trade-off.**
  - Every action costs the customer one tap, and a card block adds a simulated biometric step in the app.
  - The flow depends on a Strands internal (`agent._interrupt_state`, pinned at strands-agents 1.32.0).
  - AgentCore Evaluations can't score sessions with an interrupt (`SpanEventParsingException`), so those cases are graded locally only.
- **Rejected.** `customer_confirmed` as a boolean the model sets (the write-tools design), and a text consent check (`consent_hook.py`), both removed.
- **Source.** [`docs/handoffs/2026-10-04-confirmation-buttons-frontend.md`](handoffs/2026-10-04-confirmation-buttons-frontend.md); [write tools spec](superpowers/specs/2026-10-03-write-tools-design.md) §1; `gateway/policies/policy.cedar`; `evals/README.md`.

### One Gateway token per request

- **Decision.** The agent fetches a new machine token on every request and uses that same token both to read `customer_id` and to call the Gateway.
- **Why.** The id the agent writes into tool calls and the id Cedar checks come from the same token, by construction. A changed persona mapping takes effect on the next message. The agent is rebuilt per request and a token outlives one request, so reconnections within a request never see an expired token.
- **Trade-off.** One Cognito M2M token per message, at $0.00225 each with no free tier, plus the latency of one extra HTTPS call.
- **Rejected for now.** Caching the token across messages.
- **Source.** [v1 wiring spec](superpowers/specs/2026-10-03-v1-agent-wiring-design.md) §1; `agent/ledgerlens/ledgerlens_agent.py`, `tools/gateway.py`.

## Agent

### A guardrail that masks nothing

- **Decision.** A Bedrock Guardrail on the model with content filters (prompt attack on input; misconduct at LOW on output), four denied topic groups unrelated to banking (software, general knowledge, entertainment, politics/religion/legal/medical), and no sensitive-information, word or grounding policy. It checks only the newest customer message and holds each reply chunk until it is checked.
- **Why.**
  - Card digits, amounts and merchants have to reach the customer unchanged, and a PII mask would hide exactly what the agent exists to explain.
  - Guardrails can only deny named topics, so off-topic areas are listed. Banking requests the agent can't serve are left to the prompt, which declines them and offers a person.
  - Misconduct output is LOW because the agent's own replies about suspected fraud discuss misconduct.
  - The Standard tier covers Spanish and Portuguese; it requires the cross-region profile `us.guardrail.v1:0`.
- **Trade-off.** Privacy depends on the tools selecting only the columns they need and on the prompt's privacy rules, not on output masking.
- **Rejected.** Output redaction: Bedrock already returns the guardrail's blocked message, and redaction would overwrite it with "[Assistant output redacted.]".
- **Source.** `infra-cdk/lib/utils/agent-guardrail.ts`, `agent/ledgerlens/tools/guardrail.py`; commit `4087944`.

### Claude Haiku as the production model

- **Decision.** The agent runs `global.anthropic.claude-haiku-4-5-20251001-v1:0` at temperature 0.1.
- **Why.** On 2026-10-05, 10 scripted cases × 3 runs per model on prompt v10:

  | | DeepSeek V3.2 | Claude Haiku 4.5 | gpt-oss-120b |
  |---|---|---|---|
  | pass^1 | 60% | **80%** | 47% |
  | Cases passing every run | 4/10 | **8/10** | 4/10 |
  | Bare tool names after a Yes | 3 | 0 | 1 |
  | Malformed arguments | 5 | 0 | 0 |
  | Model cost, 30 sessions | $0.27 | $0.55 | $0.08 |

  Haiku was the only model with no malformed tool calls. Prompt v12 then fixed its two failing cases by giving reasons instead of more rules (97% pass^1, 9/10 every run, no unsafe replies in 90 sessions).
- **Trade-off.** About twice DeepSeek's model cost per session.
- **Rejected.** DeepSeek V3.2 (the model before the evaluation) and gpt-oss-120b, which stay available to evaluation logins only. Claude Sonnet 4.5 was dropped for cost and Sonnet 5.5 couldn't be enabled (Marketplace agreement unavailable).
- **Source.** [`evals/README.md`](../evals/README.md) "Model decision"; `infra-cdk/config.yaml` comment; [eval harness spec](superpowers/specs/2026-10-04-eval-harness-design.md) §2; `docs/evaluation/ledgerlens-under-test.html`.

### Short-term memory only

- **Decision.** AgentCore Memory keeps the conversation; the agent sends the last 30 messages to the model (`stm_window_size: 30`). Summarizing older messages is built but off, and the long-term semantic strategy is defined but its retrieval is off.
- **Why.**
  - A tool-using question is about 4-6 messages, so 30 messages hold several exchanges, and the customer's context doesn't depend on the window (next entry).
  - Each summary costs one extra model call.
  - Long-term memory costs $0.75 per 1,000 records stored and $0.50 per 1,000 retrievals. With it off, nothing from one chat carries into the next, which keeps switched demo personas apart.
- **Trade-off.** In a very long chat, the oldest turns drop out of what the model sees.
- **Source.** `infra-cdk/config.yaml`; `agent/ledgerlens/tools/conversation_memory.py`; [v1 wiring spec](superpowers/specs/2026-10-03-v1-agent-wiring-design.md) §5.

### Session context in the system prompt

- **Decision.** On a session's first turn, the agent code (not the model) calls `get_session_context` and `classify_call_type` in parallel, saves both results in `agent.state`, and renders them into the system prompt on every turn as JSON inside `<session_context>` tags.
- **Why.**
  - The first step never varies, so code runs it: it always happens, costs no model round trip, and the model can open with the likely reason for the contact.
  - The agent is rebuilt per request and the system prompt isn't saved with the session, so it must be rebuilt each turn; `agent.state` is saved, so the context is fetched only once.
  - The system prompt sits outside the message list, so the window never drops the context and a summary never rewords it.
- **Trade-off.** The context is a snapshot from the session's start; the tool's description tells the model to call `get_session_context` again only when the customer asks for a refresh or more than 30 minutes have passed. It is treated as data: `<` and `>` are escaped so database text can't close the tag.
- **Rejected.** Recording the tool call into the messages on the first turn (the v1 approach): the window drops it and summarization rewords it.
- **Source.** [Short-term memory and session context plan](superpowers/plans/2026-10-03-agent-short-term-memory-and-session-context.md) §2; `agent/ledgerlens/tools/session_context.py`.

### No Code Interpreter

- **Decision.** The agent's only tools are the Gateway's. FAST's Code Interpreter tool and its IAM access were removed.
- **Why.** Card questions don't need it, and running generated code is extra risk in a banking context.
- **Source.** `agent/ledgerlens/ledgerlens_agent.py`; [v1 wiring spec](superpowers/specs/2026-10-03-v1-agent-wiring-design.md) §2.3.

### Per-session overrides for evaluation logins

- **Decision.** A request may carry `"eval": {"model_id", "prompt_name", "system_prompt"}`. It is honored only for a login in the Cognito `evaluators` group and a model in `EVAL_MODEL_IDS`; anyone else's field is ignored. The override replaces only the base prompt: the customer block, both hooks, the guardrail and Cedar apply as for a customer.
- **Why.** Comparing models and prompt versions against the real deployment (real Gateway, Cedar, guardrail and data) took one deploy in total; new prompts are files in `evals/prompts/`. An invalid override from an evaluator is an error rather than a silent fallback, so the harness never grades the wrong configuration.
- **Trade-off.** The production runtime carries an evaluation code path, gated by a Cognito group.
- **Source.** [Eval harness spec](superpowers/specs/2026-10-04-eval-harness-design.md) §2, §4.1; `agent/ledgerlens/tools/eval_override.py`.

## Infrastructure and delivery

### Two CDK stacks

- **Decision.** `ledgerlens-bank-assistant-data` holds DSQL, its network path, the tool roles and the pipeline; `ledgerlens-bank-assistant` holds everything else, including the tool Lambdas, which use the data stack's VPC, subnet, security group, roles and private host. `deploy_scope: data` deploys only the first.
- **Why.** The database and its pipeline can be deployed and loaded without the agent backend or the frontend, and a main-stack redeploy never touches the data. The cluster has deletion protection and a RETAIN policy, so deleting the stack keeps the data.
- **Trade-off.** The main stack depends on the data stack's exports, so the data stack deploys first and is deleted last.
- **Rejected.** The tool Lambdas in the data stack, imported by name into the Gateway (the v1 layout, moved on 2026-10-03).
- **Source.** `infra-cdk/lib/data-stack.ts`, `ledgerlens-app.ts`; commits `fbfcca2`, `4087944`.

### Deploys run on ARM CodeBuild

- **Decision.** `scripts/deploy-with-codebuild.py` zips the git-tracked files, runs `cdk deploy` on an ephemeral ARM CodeBuild project (`amazonlinux2-aarch64-standard:3.0`), streams the log, and deletes the project, role and bucket on success.
- **Why.** AgentCore Runtime runs only ARM64 images and the Lambdas are bundled for ARM64. The team's machines can't build ARM64 with local Docker without emulation; CodeBuild builds natively, from a clean copy of the repo.
- **Trade-off.** Untracked files are skipped, so new files must be staged first. Each deploy pays build minutes. A failed deploy leaves its resources for debugging until the next success.
- **Rejected as the team route.** Local `cdk deploy` with binfmt ARM64 emulation (still documented).
- **Source.** `scripts/deploy-with-codebuild.py`; commit `fbfcca2`; [DEPLOYMENT.md](DEPLOYMENT.md#first-deployment).

### Amplify Hosting with manual deploys

- **Decision.** The SPA is served by the Amplify app that came with FAST, as a manual-deploy app with no Git connection. `scripts/deploy-frontend.py` writes `aws-exports.json` from the main stack's outputs, builds with Vite, zips the build to a staging bucket and starts the Amplify job. Amplify sends the security headers, including a CSP.
- **Why.** The Amplify app already existed in the stack. The build needs `aws-exports.json`, which comes from the deployed stack's outputs, so the script builds after the backend is up. The CSP matters because the login tokens are kept in `localStorage`: `connect-src` lists only the origins the app calls.
- **Trade-off.** A frontend change needs its own deploy step; the stack deploy doesn't include it.
- **Rejected.** CloudFront + S3, dropped from the design.
- **Source.** [v1 wiring spec](superpowers/specs/2026-10-03-v1-agent-wiring-design.md) §1, §6; `infra-cdk/lib/amplify-hosting-construct.ts`; `scripts/deploy-frontend.py`.
