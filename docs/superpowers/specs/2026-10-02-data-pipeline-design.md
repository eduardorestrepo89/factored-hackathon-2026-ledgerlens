# LedgerLens data pipeline: design

- **Date:** 2026-10-02
- **Branch:** `feat/data-pipeline` (from `feat/database` at `7d18c41`)
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
3. `GRANT USAGE ON SCHEMA public TO ll_read;` and `GRANT SELECT ON ALL TABLES IN SCHEMA public TO ll_read;`. The grants run after every load, because recreated tables lose them.
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
| 2. Database role | `ll_read` (SELECT on the 13 tables, USAGE on `public`) is mapped to the tools role with `AWS IAM GRANT` | A tools connection can only read, even with a leaked token |
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

- **VPC:** one AZ, one private isolated subnet, no NAT gateway and no internet gateway. DNS support and DNS hostnames are on.
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

## 11. Cost and duration (list prices, us-east-1)

| Item | Estimate |
|---|---|
| Ingest | About 10 minutes for 7,671 objects (5.3 GB) cross-region |
| Transform | About 10 minutes in CodeBuild, including the download (a laptop staged the 2-year window in about 4 minutes) |
| Load | About 90 minutes. `digital_events` (15.6M rows) at about 3,000 rows/s; to be measured on the first run |
| CodeBuild | `arm1.large`, $0.015/min × about 110 min ≈ **$1.65 per run** |
| DSQL writes | About 1.5 × the 2-year estimate (design doc §16, $1.76) ≈ **$2.60**; to be measured |
| DSQL storage | About 6 GB ≈ $2 per month |
| S3 | `raw/` 5.3 GB + `clean/` Parquet ≈ $0.15 per month |
| DSQL interface endpoint | 1 AZ × $0.01/h ≈ **$7.30 per month**, plus $0.01/GB |
| Step Functions, Lambda, VPC, security groups | Negligible or free |

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

1. The loader authenticates as `admin` from CodeBuild (outside the VPC) with the cluster policy attached, through the `aws:PrincipalArn` exception.
2. `aurora-dsql-loader --dry-run` accepts the typed Parquet against the recreated tables.
3. The read check connects through the private hostname. If DSQL rejects a token signed for that hostname, the Lambda signs the token for the public endpoint and connects to the private host, and the plan records this.
4. Connecting from a laptop with admin credentials (the `ledgerlens` profile) is refused.
5. Load throughput against the 90-minute estimate.
6. `transform.json` shows the section 6.1 counts.

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
