# LedgerLens data pipeline: design

- **Date:** 2026-10-02
- **Branch:** `feat/database-pipeline` (pushed; built as `feat/data-pipeline`, from `feat/database` at `d74e75d`)
- **Status:** approved in brainstorming; written spec awaiting review
- **Supersedes:** `docs/superpowers/specs/2026-09-29-data-loading-design.md` in full. In `docs/LEDGERLENS_PRODUCT_DESIGN.md` (v3) it replaces "Lambda tools (no VPC)", the `bank`/`pii`/`app` schemas, section 8 and Appendix A. Those documents are updated in the last task of the plan.

## 1. Goal

Run a **simulated data pipeline once**: the organizer's dataset goes from their bucket through a raw layer and a clean layer into Aurora DSQL. In that pipeline:

- **All 13 tables, all rows.** The database keeps the organizer's schema as delivered: one schema, the original table and column names.
- **Values are unchanged except the documented repairs R1–R6** (section 6). Each repair has evidence in the data, an exact count, and a check.
- **The database is read-only for the agent.** Only the tool Lambdas, from inside our VPC, can read it. Only the loader can write. Agent writes come later, in their own design.
- **Lineage:** every loaded value can be traced to a raw file, through per-run records in S3.

## 2. Facts this design rests on

The 2026-09-29 facts were checked against the bucket; the 2026-10-02 facts against the byte-identical local copy (`datathon/analysis/bank.duckdb`).

| Fact | Consequence |
|---|---|
| **The source is static.** `data/` in the organizer bucket holds 7,671 files (5,349,322,481 bytes), uploaded in one batch on 2026-09-01; nothing has changed since. The local copy matches it byte for byte (2026-09-29) | Run once. `check` detects a re-upload |
| The bucket is in **us-east-2**; the stack is in **us-east-1** | Ingest reads cross-region |
| Event data covers process dates 2023-06-17 to 2026-06-17 (1,097 day folders) | `as_of` = 2026-06-17 is the bank's "today" |
| The full dataset is **23,495,188 rows** (table in section 5) | Load time is dominated by `digital_events` (15,620,994 rows) |
| All 13 table definitions run unchanged in DuckDB 1.5.5 and enforce types, `NOT NULL`, `CHECK` and primary keys (prototype, 2026-09-29) | One DDL file is the contract, checked in DuckDB before anything reaches DSQL |
| Every `CHECK` value list holds on the full data: product type and status, transaction status, response code (`'00'`, `'05'`, `'14'`, `'51'`, `'54'` or null), complaint category and channel (2026-10-02) | The constraints stay as they are |
| `call_transcripts.duration_seconds` is null in 24,029 of 171,321 rows | The column is nullable |
| Of the 24 declared links between tables, **22 have no broken references**. Two do: `customers.registration_branch_id` (149,995 of 150,000 point at no branch) and `service_agents.assigned_branch_id` (831 of 833). `complaints.origin_interaction_id` is null in every row | Repairs R1 and R2. No foreign keys in DSQL (decision D6) |
| Every `complaints.affected_product_id` points at a real product, but it belongs to the complainant in 0 of 44,570 rows. For `digital_events.product_id`, the product belongs to the event's customer in 16 of 1,094,242 rows | Repairs R3 and R4 |
| 117,640 products have a transaction dated before their opening date; customers have products opened before they registered | Repair R6 |
| 1,352 transactions are timestamped 00:00–05:59 on 2026-06-18 with `process_date` 2026-06-17 (the business day ends at 06:00) | Tools filter on `process_date` (section 5.3) |

## 3. Decisions

| # | Decision | Why | Rejected |
|---|---|---|---|
| D1 | **Four stages run once** (ingest, transform, load, read check), orchestrated by **Step Functions** | Shows the pipeline as a graph in the console. Each stage can be rerun on its own | A scheduled daily replay (a moving clock for static data); ELT inside DSQL |
| D2 | Stages 1–3 run in **one CodeBuild project**, selected by `STAGE`; the read check is a **Lambda in the VPC** | CodeBuild already works and has no 15-minute limit. The read check must run where the tools will run | Glue (too much for 5 GB); one Lambda per stage (15-minute limit) |
| D3 | **Ingest copies the raw files** into the team bucket | A real pipeline lands raw data first. Only ingest needs the organizer's keys; later stages read our copy | Reading the organizer bucket in every stage |
| D4 | **One schema (`public`), the 13 tables as delivered** | The database matches the data dictionary | `bank`/`pii` split with views |
| D5 | **All rows**; time control moves to the tools' queries | Nothing is lost; "from X to today" is a query, not a load setting | A load-time window (`window_years`) |
| D6 | **No foreign keys** in DSQL; links are checked in the transform | Nothing writes after the load, so a foreign key protects nothing. Foreign keys would also slow 23.5M inserts and force parent-first ordering | Foreign keys on the 22 clean links |
| D7 | **Repairs in place** (R1–R6); an unprovable link becomes `NULL`; rows are never deleted | The schema stays as delivered and the agent reads consistent data. `NULL` already means "no link" in the delivered data. The originals stay in `raw/` | Repaired values in extra columns (schema no longer as delivered); deleting rows (about 1M rows of valid history would go with them, section 6.3) |
| D8 | **Three access layers**: IAM permission, database role, cluster network policy | Only the tool Lambdas inside the VPC can read; admin credentials on a laptop are refused | IAM alone (anyone with admin credentials could connect) |
| D9 | **The run record lives in S3** (`runs/<run-id>/`), not in the database | The database holds exactly the 13 delivered tables | `app.load_manifest` |

## 4. The pipeline

### 4.1 Stages

`RUN_ID` is the Step Functions execution name. Stage outputs in the team bucket:

```text
raw/<run-id>/<organizer key below the prefix>     stage 1: byte-for-byte copy of the CSVs
clean/<run-id>/<table>.parquet, <table>.parquet.sha256   stage 2
runs/<run-id>/ingest.json, transform.json, load.json     one record per stage
```

| # | Stage | What it does | Fails when |
|---|---|---|---|
| 1 | **ingest** (`python -m data_load ingest`) | Fetches the organizer's keys from Secrets Manager at runtime. Lists `data/`, copies every object to `raw/<run-id>/` (read with the organizer's keys, write with the CodeBuild role), and checks each copy's byte size. Writes `ingest.json`: per table, the source keys, sizes, ETags and the ETag digest (SHA-256 over the sorted `key etag` lines) | A table has no files; a copy's size differs; S3 fails |
| 2 | **transform** (`python -m data_load transform`) | Downloads `raw/<run-id>/` to local disk, then, in an on-disk DuckDB database: creates the 13 tables from `schema.sql`; reads each table's CSVs as text and runs `INSERT … BY NAME` (DuckDB casts to the DDL types and enforces `NOT NULL`, `CHECK` and primary keys); checks every `varchar(n)` length; applies R1–R6; runs the link checks (section 6.2); writes each table to Parquet and uploads it with its SHA-256. Writes `transform.json`: per table, row count, Parquet URI and SHA-256; per rule, rows repaired and rows set to `NULL` | Any constraint, length or link check fails; a repair count differs from section 6.1 |
| 3 | **load** (`python -m data_load load`) | Connects as `admin` and recreates the 13 tables. Creates `ll_read` if it's missing, maps it to the tools role (`AWS IAM GRANT`, if the mapping is missing) and reapplies the grants. Runs `aurora-dsql-loader` for all 13 tables, first with `--dry-run`, then with `--on-conflict do-nothing --verify count`. Builds the 3 indexes and polls `sys.jobs` until each completes. Writes `load.json`: per table, rows loaded | A dry run or load fails; a count differs; an index job fails |
| 4 | **read check** (Lambda `ledgerlens-dsql-read-check`) | Connects through the private endpoint as `ll_read` with the tools role. Reads one row from each of the 13 tables. Then, in a transaction it rolls back, runs `INSERT INTO branches SELECT * FROM branches WHERE false`, which must fail with SQLSTATE `42501` (insufficient privilege) | A read fails, or the insert is allowed |

*Amended 2026-10-03:* a curate stage runs between transform and load; load reads `runs/<run-id>/curate.json` and `curated/<run-id>/` (`docs/superpowers/specs/2026-10-03-curate-stage-design.md`).

A failed stage fails the execution; its CodeBuild log or Lambda log names the cause. To rerun one stage of an existing run:

```bash
aws codebuild start-build --project-name ledgerlens-data-load \
  --environment-variables-override name=STAGE,value=load name=RUN_ID,value=<run-id>
```

`python -m data_load check --run <run-id>` (run locally with the `hackathon` profile for the organizer bucket) compares the bucket's current ETag digests with `ingest.json` and names the tables that changed.

### 4.2 Orchestration

Step Functions **Standard** state machine `ledgerlens-data-pipeline`:

```text
Ingest (CodeBuild .sync, STAGE=ingest)
  -> Transform (CodeBuild .sync, STAGE=transform)
  -> Load (CodeBuild .sync, STAGE=load)
  -> ReadCheck (Lambda invoke)
```

Each CodeBuild task overrides `STAGE` and sets `RUN_ID` from `$$.Execution.Name`. `make load-data` starts an execution and prints its console link. `make` isn't installed on the team's Windows shell, so the README also shows the plain `aws stepfunctions start-execution` command.

## 5. The database

### 5.1 Schema

`data_load/schema.sql` holds, in order:

1. The 13 `CREATE TABLE` statements in `public`. These are the definitions validated on 2026-09-29, unqualified, with `call_transcripts.duration_seconds` nullable and the observed `reception_channel` values in the complaints `CHECK`.
2. `CREATE ROLE ll_read WITH LOGIN;`
3. `GRANT SELECT ON ALL TABLES IN SCHEMA public TO ll_read;`. It runs after every load, because recreated tables lose their grants. There's no USAGE grant on `public`: DSQL refuses grants on that system schema ("feature not supported on system entity", first cloud run), and every role already has USAGE on it through `PUBLIC`.
4. Three secondary indexes, built with `CREATE INDEX ASYNC` after every load, only for queries the read tools run:
   - `transactions (customer_id, transaction_date)`
   - `products (customer_id)`
   - `complaints (customer_id, creation_date)`

The primary keys stay. There are no foreign keys (D6), no views, and no other schemas, tables or roles.

### 5.2 Rows

| Table | Rows | Table | Rows |
|---|---|---|---|
| digital_events | 15,620,994 | satisfaction_surveys | 212,759 |
| transactions | 4,425,008 | call_transcripts | 171,321 |
| campaign_sends | 1,746,801 | customers | 150,000 |
| call_center_interactions | 686,296 | complaints | 67,095 |
| products | 400,000 | daily_exchange_rates | 13,164 |
| service_agents | 1,200 | branches | 350 |
| marketing_campaigns | 200 | **Total** | **23,495,188** |

### 5.3 Time control (a rule for the tools)

- "Today" is `as_of` = 2026-06-17. It stays in `infra-cdk/config.yaml` (`data.as_of`) for the tools; `data.window_years` is removed.
- Event reads filter `process_date BETWEEN <from> AND as_of::date`, never `transaction_date`, because the business day ends at 06:00 (section 2).
- The tools are built later. This spec only fixes the rule.

### 5.4 Reloads

- **Recreated tables:** each load drops and recreates the 13 tables. DSQL has no `TRUNCATE`, and recreating is faster than batched deletes.
- **Downtime:** while a load runs, about 1.5 hours, tools see missing or partial tables. The pipeline runs once, outside demo and judging windows.

## 6. Data repairs

### 6.1 Rules

The repairs run in this order; later rules use earlier results. The counts are exact on the static data. `data_load/expected.json` holds them, together with the per-table row counts from section 5.2. The transform fails if a run on the full data differs from it. Unit tests pass their own expectations.

| Rule | Column | Rule | Evidence | Expected counts |
|---|---|---|---|---|
| **R6a** | `products.opening_date` | `least(opening_date, min(transaction_date)::date)` over the product's transactions | A card can't be used before it's opened | 117,640 products moved earlier |
| **R1** | `customers.registration_branch_id` | Only where the value isn't in `branches`: the `opening_branch_id` of the customer's earliest product (by R6a `opening_date`, then `product_id`). `NULL` if the customer has no products | `products.opening_branch_id` is 100% valid, and the first product's branch is always in the customer's country | 149,995 broken: **139,573 resolved, 10,422 → `NULL`**; 5 valid values kept |
| **R6b** | `customers.registration_date` | If the customer's earliest product `opening_date` (after R6a) is before `registration_date::date`, set it to that date at 00:00 | A customer can't hold a product before registering | 99,633 customers moved earlier |
| **R2** | `service_agents.assigned_branch_id` | `NULL` where the value isn't in `branches` | No other table links agents to branches | **831 → `NULL`**; 2 valid kept |
| **R3** | `complaints.affected_product_id` | Where the product belongs to someone else: the complainant's only product of the same `product_type`. `NULL` if they have none, or several | The referenced product's type is plausible; its owner is random | 44,570 checked: **13,808 resolved, 30,762 → `NULL`** |
| **R4** | `digital_events.product_id` | Same rule as R3, using the event's `customer_id`. `NULL` when the event has no `customer_id`: a specific customer's product can't be checked against an anonymous event | Same as R3 | 1,440,338 non-null: **16 kept, 337,760 resolved, 1,102,562 → `NULL`** (756,466 wrong owner with no unique match, 346,096 anonymous) |

### 6.2 Link checks (after the repairs)

All of these must hold; otherwise the transform fails and names the check:

- **All 24 declared links:** 0 broken references. The list is the ERD's relationships, including the repaired ones (`customers.registration_branch_id`, `service_agents.assigned_branch_id`, `complaints.affected_product_id`, `digital_events.product_id`).
- **Ownership:**
  - `transactions.product_id` belongs to `transactions.customer_id` (true for all 4,425,008 delivered rows);
  - every non-null `complaints.affected_product_id` belongs to the complainant;
  - every non-null `digital_events.product_id` belongs to the event's customer.
- **Dates:** 0 transactions dated before their product's `opening_date`, and 0 products opened before their customer's `registration_date`.

### 6.3 Not repaired, on purpose

| Item | Why it stays |
|---|---|
| **R5:** `complaints.origin_interaction_id`, null in every row | Only 134 of 33,761 call-center complaints have a call from the same customer in the day before. That's too few to be a real link |
| Activity before registration after R6b: 11,214 calls, 1,077 complaints, 199,495 digital events, 27,215 campaign sends, 3,560 surveys | Prospects can browse, call and receive marketing before they register. Only product ownership requires registration |
| Rows whose link becomes `NULL` | Deleting them would orphan their own history. Deleting the 10,422 customers without products, for example, would also remove 4,409 complaints, 47,584 calls, 11,833 transcripts, 14,821 surveys, 827,261 digital events and 120,997 campaign sends |

## 7. Access

### 7.1 Layers

| Layer | Mechanism | Effect |
|---|---|---|
| 1. IAM | Only the tools role has `dsql:DbConnect` on the cluster; only the loader (CodeBuild role) has `dsql:DbConnectAdmin`. The AgentCore runtime role has no DSQL permission | Nobody else can get a connection token |
| 2. Database role | `ll_read` (SELECT on the 13 tables; USAGE on `public` comes from the default `PUBLIC` grant) is mapped to the tools role with `AWS IAM GRANT` | A tools connection can only read, even with a leaked token |
| 3. Network | A cluster resource policy (`CfnCluster.policyDocument`) denies `dsql:DbConnect` and `dsql:DbConnectAdmin` unless the request comes through our VPC, with an exception for the loader role (`aws:PrincipalArn`) | Connections from outside our VPC are refused, including admin credentials on a laptop. Only the AWS account root user bypasses resource policies |

The policy (CDK resolves the tokens with `Stack.toJsonString`):

```json
{ "Version": "2012-10-17",
  "Statement": [
    { "Sid": "DenyOutsideAnyVpcExceptLoader",
      "Effect": "Deny", "Principal": {"AWS": "*"}, "Resource": "*",
      "Action": ["dsql:DbConnect", "dsql:DbConnectAdmin"],
      "Condition": { "Null": {"aws:SourceVpc": "true"},
                     "StringNotEquals": {"aws:PrincipalArn": "<loader-role-arn>"} } },
    { "Sid": "DenyOtherVpcsExceptLoader",
      "Effect": "Deny", "Principal": {"AWS": "*"}, "Resource": "*",
      "Action": ["dsql:DbConnect", "dsql:DbConnectAdmin"],
      "Condition": { "StringNotEquals": {"aws:SourceVpc": "<vpc-id>",
                                         "aws:PrincipalArn": "<loader-role-arn>"} } } ] }
```

The first statement is the AWS-documented "block public internet" pattern: a request from outside any VPC has no `aws:SourceVpc`. The second refuses every other VPC.

### 7.2 Network resources

- **VPC:** the account's default VPC (looked up at synth, `Vpc.fromLookup({ isDefault: true })`); the stack creates no VPC, subnet or gateway. The endpoint and the Lambdas share one default subnet (one AZ). Default subnets are public, so the Lambdas set `allowPublicSubnet`; Lambda ENIs get no public IP, so the tools still have no internet path and reach only the DSQL endpoint. DNS support and DNS hostnames are on in a default VPC. *Amended 2026-10-02: replaced the dedicated one-AZ isolated VPC.* Anything else running in the default VPC passes the policy's `aws:SourceVpc` check, so layers 1 and 2 (IAM and `ll_read`) and the endpoint's security group carry more of the weight.
- **Interface endpoint:** for the cluster's `attrVpcEndpointServiceName`, port 5432, private DNS on. Its security group allows 5432 only from the tools security group.
- **Private hostname:** `<cluster-id>.<service-id>.us-east-1.on.aws`, where `<service-id>` is the last dot-separated part of the service name. It's passed to Lambdas as `DSQL_HOST`.
- **No S3 endpoint:** the read check needs nothing but DSQL. The tools sign DSQL tokens locally, so they need no AWS endpoint besides DSQL.

### 7.3 Identities

| Identity | Name | Permissions | Logs in as |
|---|---|---|---|
| Tools role | `ledgerlens-tools` (Lambda service principal) | `dsql:DbConnect` on the cluster; VPC access for Lambda; CloudWatch Logs | `ll_read` |
| Loader role | the CodeBuild project's role | `dsql:DbConnectAdmin` on the cluster; read/write on the team bucket; `secretsmanager:GetSecretValue` on `ledgerlens/hackathon-s3`; CloudWatch Logs | `admin` |
| Step Functions role | generated | Start and watch the CodeBuild project; invoke the read-check Lambda | — |

**Break-glass:** to query from a laptop, add your role ARN to the policy's `aws:PrincipalArn` list and redeploy; remove it afterwards.

## 8. Components

| Path | Change |
|---|---|
| `data_load/schema.sql` | Rewritten as section 5.1 |
| `data_load/ddl.py` | `SchemaPlan` keeps `data_tables`, `roles`, `grants`, `indexes`; `schemas`, `views`, `app_tables` and `app_indexes` go |
| `data_load/ingest.py` | New: stage 1 |
| `data_load/transform.py` | Replaces `stage.py`: stage 2 without the date window or the DuckDB S3 secret, plus the length check. `--source <dir>` skips the download for local rehearsals |
| `data_load/repair.py` | New: R1–R6 as DuckDB SQL, and the link checks. Returns per-rule counts |
| `data_load/expected.json` | New: the per-table row counts (section 5.2) and per-rule repair counts (section 6.1) the transform must reproduce |
| `data_load/runrecord.py` | New: write and read `runs/<run-id>/<stage>.json` |
| `data_load/dsql.py` | `apply_schema` for the new plan plus the IAM mapping; `load_all` and `build_indexes` unchanged; `record_manifest` and `recorded_digests` go |
| `data_load/source.py` | Unchanged (listing, ETag digest, drift) |
| `data_load/__main__.py` | Commands `ingest`, `transform`, `load`, `check`; `run` and `stage` go |
| `infra-cdk/lib/data-construct.ts` | Adds the VPC, endpoint, security groups, cluster policy, tools role, read-check Lambda and state machine. The CodeBuild environment loses `AS_OF`, `WINDOW_YEARS` and `HACKATHON_S3`, and gains `STAGE`, `RUN_ID`, `TOOLS_ROLE_ARN` and `HACKATHON_SECRET_ID` (the secret's name, not its value). New outputs: `DataPipelineStateMachine`, `DsqlPrivateHost` |
| `infra-cdk/lambdas/dsql-read-check/` | New: `index.py`, `requirements.txt`; `PythonFunction`, ARM_64, Python 3.12, in the VPC, using the tools role |
| `infra-cdk/lib/utils/config-manager.ts`, `infra-cdk/config.yaml` | `window_years` removed; `as_of` kept |
| `Makefile` | `load-data` starts the state machine |

## 9. Failure handling

| Failure | Behavior |
|---|---|
| A constraint, length, link or repair-count check fails | The transform fails and names the table and check. DSQL is untouched |
| The load fails partway | Rerun the `load` stage for the same `RUN_ID`: it recreates the tables and reloads from `clean/<run-id>/` |
| An index job fails | The load stage fails. A rerun recreates the tables and their indexes |
| The read check fails | The data is loaded but access is misconfigured. Fix the CDK and redeploy, then rerun the Lambda; no reload is needed |
| The organizer re-uploads data | `check --run <run-id>` names the changed tables; start a new execution |
| Tools are queried during a load | They see missing tables (section 5.4) |

## 10. Testing

- **Unit tests (no AWS):**
  - one fixture per repair rule, R1–R6, each a tiny CSV set where the right answer is obvious, plus the `NULL` cases (no products, several same-type products, an anonymous event);
  - a broken link, an over-long `varchar` value and a `CHECK` violation, each of which must fail the transform;
  - `ingest` with fake S3 clients, checking keys, sizes, the ETag digest and that the secret is read from Secrets Manager rather than the environment;
  - `apply_schema` issuing the role, the IAM mapping and the grants;
  - the read-check handler against a fake connection: 13 reads, and the insert denied (`42501`). A permitted insert fails the check.
- **CDK tests (jest):**
  - the cluster policy denies both actions outside the VPC, except the loader;
  - the tools role has `dsql:DbConnect` and no `DbConnectAdmin`;
  - the Lambda is attached to the VPC;
  - the state machine has the four states in order;
  - the CodeBuild environment holds no secret value.
- **Local rehearsal:** `python -m data_load transform --source datathon/data --out <tmp>` produces the per-table counts in section 5.2 and the repair counts in section 6.1.
- **First cloud run:** section 13.

## 11. Cost and duration

### 11.1 Unit prices (verified 2026-10-02, AWS Price List API, us-east-1)

| Item | Price |
|---|---|
| Aurora DSQL | $8.00 per 1M DPU; storage $0.33/GB-month. Free tier: 100,000 DPU and 1 GB-month per month |
| DSQL write metering | Each row written to a table or index is billed at max(row size, 128 B), at 0.00004883 DPU per byte (about 1 DPU per 20 KiB). Writes also read the primary key to check uniqueness, at 0.00000183105 DPU per byte. Compute DPU (CPU-seconds) comes on top ([billing doc](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/billing-metering.html)) |
| CodeBuild `arm1.large` | $0.015 per build-minute. The free tier covers only `arm1.small`/`general1.small` |
| PrivateLink interface endpoint | $0.01 per endpoint per AZ per hour, plus $0.01/GB processed |
| S3 Standard | $0.023/GB-month; PUT $0.005 per 1,000; GET $0.0004 per 1,000 |
| Data transfer us-east-2 → us-east-1 | $0.01/GB. The bucket owner (the organizer) pays, because the bucket isn't Requester Pays |
| Step Functions Standard | $0.025 per 1,000 transitions; 4,000 a month free |
| Lambda arm64 | $0.0000133334/GB-s and $0.20 per 1M requests; 400,000 GB-s and 1M requests a month free |
| Secrets Manager | $0.40 per secret per month |
| CloudWatch Logs | $0.50/GB ingested; $0.03/GB-month stored |
| Security groups (default VPC) | Free (no NAT gateway or public IP) |

### 11.2 Inputs (measured on the local copy, 2026-10-02)

- **Source:** 5,349,322,481 bytes of CSV in 7,671 files, 23,495,188 rows.
- **Parquet from the transform:** 1,217 MB. The full rehearsal of the transform, with all repairs and checks, took 429 s on a laptop.
- **Index rows:** 4,892,103, all under 128 B, so each is billed as 128 B. That's 4,425,008 transactions, 400,000 products and 67,095 complaints.

### 11.3 Approximation

**One pipeline run:**

| Item | Basis | Estimate |
|---|---|---|
| CodeBuild | Ingest about 10 min, transform about 12 min, load about 90 min, plus about 1.5 min of install per stage ≈ 115 min (range 90–150) | **$1.73** ($1.35–2.25) |
| DSQL write DPU | Table rows: 3.2–5.4 GB. The upper bound is the CSV size; the lower assumes binary columns are about 60% of their text form. Plus 0.63 GB of index rows. Total 3.8–6.0 GB × 0.00004883 | 187,000–292,000 DPU |
| DSQL read DPU | Uniqueness checks: 23.5M rows × 128 B × 0.00000183105 | about 5,500 DPU |
| DSQL compute DPU | About 13% of write DPU, the ratio in AWS's bulk-insert example | 24,000–37,000 DPU |
| DSQL total | 217,000–335,000 DPU | **$1.74–2.68**, or $0.94–1.88 after the 100,000 free DPU |
| S3 requests | About 7,700 PUTs (ingest), 7,700 GETs (transform), Parquet uploads and loader reads | **$0.06** |
| Step Functions, Lambda | 6 transitions; one invocation of a few seconds | $0 (free tier) |
| Cross-region copy | 5.35 GB × $0.01, billed to the organizer | $0 to us |
| **Per run** | | **≈ $3.50–4.50** |

**Every month the stack exists:**

| Item | Basis | Estimate |
|---|---|---|
| DSQL interface endpoint | 1 AZ × 730 h × $0.01 | **$7.30** |
| DSQL storage | 3.5–6 GB, minus the 1 GB free tier | **$0.83–1.65** |
| S3 storage | `raw/` 5.35 GB + `clean/` 1.22 GB | $0.15 |
| Secrets Manager | 1 secret | $0.40 |
| Tool reads during judging | Indexed point reads, a few DPU each | Inside the 100,000 free DPU |
| **Per month** | | **≈ $8.70–9.50** |

**Hackathon window (deploy 2026-10-03, judging ends 2026-10-15; 13 days ≈ 0.43 month):** one run plus 0.43 month of fixed costs ≈ **$7–9**. Each extra full run adds $3.50–4.50. Keeping the stack to the end of October costs about $12–14.

**What drives the cost:**
- **The endpoint (layer 3):** 80% of the monthly cost. Deleting the endpoint and the VPC after judging, or dropping layer 3, saves $7.30 a month.
- **A rerun of the `load` stage:** costs the DSQL DPU and about 95 CodeBuild minutes again. A rerun of `transform` costs about 12 minutes.
- **The previous design** (2-year window, no VPC) cost about $1.38 for the hackathon window (design doc §16). The difference is all rows (+49%) and the endpoint.

### 11.4 Measured on the first run (2026-10-02)

The clean run is `fc74b48e-6c0a-4a54-9645-255cdfe72bef`, started 15:00 UTC. The figures come from Step Functions history, CodeBuild, and the cluster's CloudWatch metrics (namespace `AWS/AuroraDSQL`, dimension `ClusterId`).

| Item | Estimate (11.3) | Measured |
|---|---|---|
| Ingest | about 10 min | **1.7 min** (7,671 files, 5.35 GB) |
| Transform | about 12 min | **4.7 min** |
| Load | about 90 min | **23.8 min**. `transactions` took 237 s (about 18,700 rows/s); `digital_events` finished last |
| Read check | — | 0.1 min |
| Whole run | about 2 h | **30.3 min** |
| CodeBuild per run | about 115 min, $1.73 | about 30 min, **about $0.45** |
| DSQL DPU per run | 217,000–335,000 ($1.74–2.68) | **371,356** (write 329,262; read 29,389; compute 12,705) = **$2.97** |
| DSQL storage | 3.5–6 GB | **6.63 GB** at 15:30 UTC. That may still include the first attempt's dropped tables until DSQL reclaims them. About $1.86/month after the free GB |
| OCC conflicts | — | 7 during the load, absorbed by the loader's retries |

- **Corrected per-run cost:** about $3.50 ($2.97 DSQL, $0.45 CodeBuild, about $0.06 S3).
- **Monthly while the stack exists:** about $9.70 (the endpoint $7.30, storage about $1.86, S3 $0.15, the secret $0.40).
- **Total spent on 2026-10-02:** about $6.
  - DSQL 667,231 DPU, which is $5.34, or about $4.54 after the 100,000 free DPU. That includes 295,875 DPU from the first attempt, whose load failed and was stopped.
  - CodeBuild: 54 pipeline minutes ($0.81), plus three short deploy builds.

The load is about 4× faster than estimated. A rerun of the load stage costs about 25 minutes and $3, not 95 minutes.

## 12. Security

- **Organizer keys:**
  - They live only in Secrets Manager. Ingest fetches them at runtime by the secret's name.
  - They're never in a CodeBuild environment variable, a file, the run record or a log.
  - They're over-permissioned (they can list the organizer's other buckets); we read only `data/`, and the team should tell the organizers.
- **Personal data:**
  - **Who can read it:** `ll_read` can read every column, including names, document numbers, emails, phones and addresses in `customers` and `service_agents`. The tools must select only the columns they need.
  - **Column-level grants:** these would let the database enforce that. They're out of scope until DSQL support is tested.
  - **The raw copy:** `raw/` contains the same personal data, so the team bucket stays private, encrypted and SSL-only.
- **Access:** section 7. The agent's runtime has no database permission; it reaches data only through the tools.

## 13. To confirm on the first run

1. The loader authenticates as `admin` from CodeBuild (outside the VPC) with the cluster policy attached, through the `aws:PrincipalArn` exception. **Passed.**
2. `aurora-dsql-loader --dry-run` accepts the typed Parquet against the recreated tables. **Failed at first, now fixed.** The dry run passed, but the real load of `branches` failed: loader v3.3.0 can't read Parquet TIME columns (`Time64`). The transform now writes TIME columns as `HH:MM:SS` text (commit `d6f3370`). A second problem surfaced in the same stage: DSQL refuses `GRANT USAGE ON SCHEMA public` ("feature not supported on system entity"), and every role already has USAGE through `PUBLIC`, so the grant was removed (commit `f4e4c21`).
3. The read check connects through the private hostname. If DSQL rejects a token signed for that hostname, the Lambda signs the token for the public endpoint and connects to the private host, and the plan records this. **Passed without the fallback:** the output was `{"tables_read": 13, "insert_denied": true}`.
4. Connecting from a laptop with admin credentials (the `ledgerlens` profile) is refused. **Passed:** "FATAL: unable to accept connection, access denied". Any principal allowed `dsql:PutClusterPolicy` can still lift this layer (final review, minor 9).
5. Load throughput against the 90-minute estimate. **23.8 minutes** (section 11.4).
6. `transform.json` shows the section 6.1 counts. **Passed on both runs.** `python -m data_load check` reports no drift against the organizer's bucket.

## 14. Out of scope

- The tool Lambdas, and any agent writes (approvals, cases, card blocks, claims, audit, feedback).
- Column-level grants for personal data.
- A daily replay or moving clock, a resume flag, a multi-AZ endpoint.
- R5, and activity before registration (section 6.3).
- `data_backup_20260831/` in the organizer bucket.

## 15. Changes from the 2026-09-29 spec

- **Removed:**
  - the `bank`/`pii`/`app` schemas and the two views;
  - the write tables and roles `ll_write`, `ll_approvals` and `ll_feedback`;
  - `app.load_manifest`, replaced by the S3 run record;
  - the load window and `window_years`;
  - the DuckDB S3 secret;
  - `stage` and `run`.
- **Added:** ingest, the repairs and link checks, the length check, the VPC, the cluster policy, the tools role, the read check and the state machine.
- **Deferred minors from the 2026-10-01 branch review:**
  - #3 (`varchar` length unchecked): fixed by the length check;
  - #10 (organizer keys in the loader's environment): fixed by fetching the secret at runtime;
  - #4 (`stage --source s3://` had no credentials) and #6 (an invalid `app` index skipped forever): obsolete.
