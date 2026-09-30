# LedgerLens data loading: design

- **Date:** 2026-09-29
- **Branch:** `feat/database`
- **Status:** approved in brainstorming; written spec awaiting review
- **Supersedes:** section 8 of `docs/LEDGERLENS_PRODUCT_DESIGN.md` (v3), plus the parts of sections 6, 7.8, 7.10, 8.5 and Appendix A listed in section 6 below. The design doc is updated when this is implemented.

## 1. Goal

Load the organizer's dataset into Aurora DSQL **once**, with these properties:

- **Fixed business date:** everything is frozen at `as_of = 2026-06-17T23:59:59`.
- **Window:** the event tables cover the 2 years ending at `as_of`.
- **Values untouched:** no cleaning, merging or deduplication.
- **Lineage:** every loaded table can be traced to its source files.

The data is static, so there is no daily append, no moving clock and no publish gate (section 2).

## 2. Facts this design rests on (checked 2026-09-29)

| Fact | Evidence | Consequence |
|---|---|---|
| **The source data is static.** The bucket's `data/` prefix holds 7,671 files and 5,349,322,481 bytes, all uploaded in one batch on 2026-09-01 between 02:36 and 02:51 UTC. Nothing has been added or rewritten since | `list-objects-v2` on `factored-datathon-2026-s3-…-us-east-2-an`, read with the `hackathon` profile | Load once. The freshness policy is documented, not built |
| The day folders run from 2023-06-17 to 2026-06-17 (1,097 days) | Same listing | `as_of = 2026-06-17T23:59:59` |
| The local copy `datathon/data/` is byte-identical to the bucket | Same keys and sizes. 7,669 files match on MD5 = ETag; 2 multipart files match on size | Local runs are valid rehearsals |
| `data_backup_20260831/` is an earlier, incomplete version of the dataset: 4,833 files, no transcripts or surveys, transactions for 453 of the 1,097 days, and every shared event, customer and product file differs | Same listing | Not loaded |
| The bucket is in **us-east-2**; the stack is in us-east-1 | Bucket name and region | The DuckDB S3 secret uses `REGION 'us-east-2'` |
| **The DDL works as a contract.** All 13 `bank`/`pii` tables from Appendix A run unchanged in DuckDB 1.5.5 | Prototype run, 2026-09-29 | One DDL file enforces types, `CHECK`, `NOT NULL` and primary keys twice: once in DuckDB before anything reaches AWS, and again in DSQL |
| The prototype (read everything as text, then `INSERT … BY NAME` into those tables) found one DDL bug: `call_transcripts.duration_seconds` is null in 16,135 of the 114,222 rows in the window. With that column nullable, all 13 tables loaded **15,745,982 rows**, exactly the expected window | Prototype run, 2026-09-29 | The column becomes nullable (section 6) |
| `response_code` values keep their leading zeros (`'00'`, `'05'`…) | DuckDB types it `VARCHAR`; the DDL declares `varchar(2)` with a `CHECK` | Reading as text and casting to the DDL types is safe |
| Customer and product dates are not causal: 827,610 transactions happen before their card was opened, and 830,293 before their customer registered | DuckDB query on the local copy | Reference tables load in full and are never cut by date |
| 1,352 transactions in the window have `transaction_date` between 00:00 and 05:59 on 2026-06-18, but `process_date` = 2026-06-17 (the business day ends at 06:00) | DuckDB query on the local copy | Tools filter on `process_date`, not `transaction_date` (section 7) |

## 3. Decisions

| # | Decision | Why | Rejected |
|---|---|---|---|
| D1 | One load at a fixed `as_of`, with the window set in config | The data is static (section 2) | A daily append with a moving clock: more machinery than static data needs |
| D2 | Run the load as a **CodeBuild job defined in CDK** | It runs in AWS next to DSQL and can be reproduced from a clean clone | A local script (depends on a laptop staying on); CloudShell (idle timeout, 1 GB home directory) |
| D3 | Read straight from the **hackathon bucket**, with the organizer's static keys held in Secrets Manager | The organizer's copy is the source of truth, which makes lineage exact | Copying to a team bucket first (a second copy to keep in sync) |
| D4 | **DuckDB + `aurora-dsql-loader`** | DuckDB filters and validates; AWS's loader handles parallelism, retries and IAM tokens | Our own batched inserts (we would own OCC retries and token refresh); AWS Glue (too much infrastructure for 3.6 GB) |
| D5 | **`bank` and `pii` are read-only for the application.** Agent writes go to `app.card_blocks` and `app.claims` | The row counts keep matching the Parquet files; a reload never loses demo actions; no application role can change organizer data | `UPDATE bank.products` / `INSERT bank.complaints` (mixes agent rows with organizer rows) |
| D6 | **Two clocks:** the bank date is `as_of`, the wall clock is `now()` | Real `now()` (October) is months past the data (June) | Using one clock for everything (section 7) |
| D7 | The loader connects as the DSQL `admin` role; the `ll_loader` role is dropped | The job already needs `admin` for DDL, so a second role adds nothing | A separate `ll_loader` role |

## 4. Components

### 4.1 Infrastructure: `infra-cdk/lib/data-construct.ts` (new, wired into `fast-main-stack.ts`)

| Resource | Settings |
|---|---|
| Aurora DSQL cluster | `aws_dsql.CfnCluster` with `deletionProtectionEnabled: true`. `attrEndpoint` is exported for the job now, and for the tool Lambdas later |
| Team bucket | Staging only: `staging/<as_of>/<table>.parquet` and `<table>.parquet.sha256`. S3-managed encryption, public access blocked, SSL enforced |
| Secret `ledgerlens/hackathon-s3` | CDK creates it **with no value**. A teammate sets it once with `aws secretsmanager put-secret-value` to JSON: `{"aws_access_key_id", "aws_secret_access_key", "bucket", "region", "prefix": "data/"}` |
| CodeBuild project `ledgerlens-data-load` | Image `aws/codebuild/amazonlinux2-aarch64-standard:3.0`, compute `BUILD_GENERAL1_LARGE` (ARM, 8 vCPU, 16 GiB), 180-minute timeout. Source: a CDK asset of `data_load/`. Environment variables: `AS_OF`, `WINDOW_YEARS` (from config), `DSQL_ENDPOINT`, `TEAM_BUCKET`, and `HACKATHON_S3` (type `SECRETS_MANAGER`, masked in logs) |
| CodeBuild role | `dsql:DbConnectAdmin` on the cluster; read/write on the team bucket; `secretsmanager:GetSecretValue` on the secret; CloudWatch Logs. It has **no** permission on the organizer's bucket: those reads use the organizer's keys |

**Buildspec (inline in CDK):**
- Install a pinned `duckdb==1.5.5`, `boto3` and `psycopg` with the DSQL connector.
- Install a **pinned** `aurora-dsql-loader` release (aarch64 Linux binary from `github.com/aws-samples/aurora-dsql-loader`).
- Run `python -m data_load run`.

### 4.2 Code

| File | Contents |
|---|---|
| `data_load/__main__.py` | Three commands:<br>• `stage --source <dir or s3 URI> --out <dir>`: validate and write Parquet; no AWS writes; works on the local copy<br>• `run`: stage from the hackathon bucket, upload, load, verify, record lineage (runs in CodeBuild)<br>• `check`: compare the bucket's current ETags with `app.load_manifest`. Run locally before the demo, with the `hackathon` profile for the bucket and the `ledgerlens` profile for DSQL |
| `data_load/schema.sql` | The full DDL: Appendix A plus the changes in section 6. The single source of truth for types and constraints |
| `tests/unit/test_data_load.py` | Section 9 |
| `Makefile` | `load-data` target: `aws codebuild start-build --project-name ledgerlens-data-load`, then `aws logs tail --follow` on its log group |

### 4.3 Config (`infra-cdk/config.yaml`)

```yaml
data:
  as_of: "2026-06-17T23:59:59"   # bank "today" for the load and for every tool
  window_years: 2                # event tables: process_date in [as_of::date - (365 * window_years - 1), as_of::date]
```

The tool Lambdas receive the same `as_of` as `LEDGERLENS_AS_OF`. Changing the date means editing config, running `cdk deploy`, then `make load-data`.

## 5. Load flow (`python -m data_load run`)

**Step 1: Stage (DuckDB; nothing in AWS is written yet)**

1. **Secrets.** Create a DuckDB S3 secret from `HACKATHON_S3` with `SCOPE 's3://<bucket>'` and `REGION 'us-east-2'`.
2. **Tables.** Run the `CREATE TABLE bank.*` and `pii.*` statements from `schema.sql` in a DuckDB database on local disk (not in memory: `digital_events` has 10.3M rows).
3. **Read each table** with `read_csv(..., header=true, all_varchar=true, hive_partitioning=false)`, then `INSERT INTO <schema>.<table> BY NAME`. DuckDB casts every column to its DDL type and enforces `NOT NULL`, `CHECK` and the primary key.
   - **Event tables** (`call_center_interactions`, `call_transcripts`, `campaign_sends`, `complaints`, `digital_events`, `satisfaction_surveys`, `transactions`) read `data/<table>/*/*/*/*.csv` and keep rows where `process_date` is in the window.
   - `daily_exchange_rates` keeps rows where `date` is in the window.
   - **Reference tables** (`customers`, `products`, `branches`, `service_agents`, `marketing_campaigns`) load in full.
4. **Violations stop the run.** Any violation fails the build and names the table and the constraint. Duplicates are **not** removed: a duplicate primary key is a violation (the data has none).
5. **Write Parquet.** `COPY <table> TO '<table>.parquet' (FORMAT parquet)`, then compute the file's SHA-256.
6. **Fingerprint the source.** For each table, list the source objects and record `source_files` and `source_etag_digest` (SHA-256 over the sorted `key etag` lines).

**Step 2: Upload.** Put each Parquet file and its `.sha256` in `s3://<team-bucket>/staging/<as_of>/`.

**Step 3: DDL in DSQL** (connected as `admin`, one statement per transaction as DSQL requires):

1. `CREATE SCHEMA IF NOT EXISTS` for `bank`, `pii` and `app`.
2. Drop the two views, then `DROP TABLE IF EXISTS` each `bank`/`pii` table, then create them from `schema.sql`, then create the views.
3. `CREATE TABLE IF NOT EXISTS` for every `app` table. Its indexes (`app.cases`, `app.claims`) are created only if missing, after checking `pg_indexes`. `app` is created once and never dropped.
4. Create the roles if they are missing (checked against `pg_roles`). **Re-apply every `GRANT`**, because recreated tables lose their grants. Mapping IAM roles to database roles (`AWS IAM GRANT`) happens when the tool Lambdas exist, not in this step.

**Step 4: Load.** Run `aurora-dsql-loader load --source-uri s3://<team-bucket>/staging/<as_of>/<table>.parquet --table <schema>.<table> --on-conflict do-nothing` for all 13 tables in parallel.

**Step 5: Index.** Run `CREATE INDEX ASYNC` on `bank.transactions (customer_id, transaction_date)`, `bank.products (customer_id)` and `bank.complaints (customer_id, creation_date)`. Then `SELECT sys.wait_for_job('<job_id>')` for each; a `false` result fails the build.

**Step 6: Verify and record.**
- For every table, `count(*)` must equal the Parquet row count.
- Per table, in one transaction: delete that table's `app.load_manifest` row for this `as_of`, then insert the new one.
- Any mismatch fails the build.

## 6. Schema changes to Appendix A (design doc v3)

1. **`bank.call_transcripts.duration_seconds`:** drop `NOT NULL`, because 16,135 of the 114,222 rows in the window are null.
2. **`bank.complaints.reception_channel`:** remove `'AI Assistant'` from the `CHECK`. The agent no longer writes complaints; the six observed values remain.
3. **New `app.card_blocks`:** `card_id varchar(30) PRIMARY KEY`, `customer_id varchar(30) NOT NULL`, `approval_id uuid NOT NULL`, `business_date date NOT NULL`, `created_at timestamptz NOT NULL DEFAULT now()`.
   - The primary key on `card_id` makes a second block of the same card a no-op.
   - There is no unblock tool, so a row means the card is blocked.
4. **New `app.claims`:**
   - **Identity:** `claim_id varchar(40) PRIMARY KEY`, `customer_id varchar(30) NOT NULL`, `approval_id uuid NOT NULL`.
   - **Claim details:**
     - `claim_type varchar(10) NOT NULL CHECK (claim_type IN ('fraud','dispute'))`;
     - `transaction_ids jsonb NOT NULL` (a JSON array, because DSQL has no array columns);
     - `claimed_amount numeric(15,2) NOT NULL`, `currency varchar(3) NOT NULL`;
     - `customer_statement varchar(500)`.
   - **Dates and rules:** `business_date date NOT NULL`, `deadline_date date NOT NULL`, `rule_ids jsonb NOT NULL`.
   - **Status:** `status varchar(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open','handed_off','closed'))`, `created_at timestamptz NOT NULL DEFAULT now()`.
   - **Index:** `CREATE INDEX ASYNC` on `(customer_id, business_date)`.
5. **`app.load_manifest`:**
   - **Columns:** `table_name`, `as_of`, `window_start`, `window_end`, `source_uri`, `source_files`, `source_etag_digest`, `staged_uri`, `staged_sha256`, `rows_staged`, `rows_loaded`, `loaded_at`.
   - **Key:** primary key `(table_name, as_of)`.
6. **`app.cases.complaint_id`** becomes `claim_id varchar(40)`, because hand-offs now reference `app.claims` instead of `bank.complaints`.
7. **Roles:**
   - **`ll_loader` is removed** (D7).
   - **`ll_read`** also gets `SELECT` on `app.card_blocks` and `app.claims`.
   - **`ll_write`** loses `UPDATE` on `bank.products` and `INSERT` on `bank.complaints`. It gains `INSERT` on `app.card_blocks` and `app.claims`.
   - **No application role** has write privileges on `bank` or `pii`, or any privilege on `pii` tables.

## 7. Rules for the tools (implemented with the tools, not in this step)

- **Bank date:** `as_of` comes from `LEDGERLENS_AS_OF`.
- **Event reads:** `process_date <= as_of::date`. "Last N days" means `process_date > as_of::date - N`.
- **Card status:** `'Blocked'` if a row exists in `app.card_blocks`, otherwise `bank.products.product_status`.
- **`RECENT_CASE`:** a row in `app.cases` or `app.claims`.
- **Dates that follow the bank clock (`as_of::date`):**
  - `business_date` on `app.card_blocks` and `app.claims`;
  - `deadline_date` and the filing-window check, counted from that date.
- **Dates that follow the wall clock (`now()`):** `app.approvals.expires_at` (now + 10 min), and `created_at`, `approved_at` and `used_at` on every `app` row.
- **Design doc sections to update:**
  - §6: `as_of` becomes 2026-06-17 and the tools filter on `process_date`;
  - §7.8: the block SQL writes `app.card_blocks`;
  - §7.10: `open_claim` writes `app.claims`;
  - §8, §8.5 and Appendix A.

## 8. Failure handling

| Failure | Behavior |
|---|---|
| A constraint is violated, a file is missing, or reading S3 fails during staging | The build fails in step 1 and DSQL is not touched. The log names the table and the constraint |
| The load fails partway | Re-run the build. Steps 3–6 drop and recreate `bank`/`pii`, and `--on-conflict do-nothing` makes loads safe to repeat. There is no resume flag; add one only if a real run needs it |
| An index job fails | The build fails. Re-run it (the failed index is dropped along with its table in step 3) |
| A row count doesn't match | The build fails and nothing is recorded in the manifest |
| Tools are queried during a reload | They see missing or partial tables. Reloads run only outside demo and judging windows (documented in the README) |
| The organizer re-uploads data | `python -m data_load check` reports which tables' ETag digests changed. Re-run the load |

## 9. Testing

- **Unit test** (`tests/unit/test_data_load.py`, no AWS): build a small CSV tree in `tmp_path` and run `stage`. Assert that:
  - an in-window transaction is kept;
  - a transaction before the window is dropped;
  - a transaction at 03:00 on the day after `as_of` with `process_date = as_of::date` is **kept**;
  - `response_code = '99'` raises a `CHECK` violation.
- **Local rehearsal:** `python -m data_load stage --source datathon/data --out <tmp>` must produce 15,745,982 rows across the 13 tables (the prototype produced exactly this on 2026-09-29).
- **After the first cloud run:** the manifest holds 13 rows with `rows_loaded = rows_staged`, and `check` reports no drift.

## 10. Cost and duration (list prices, us-east-1)

| Item | Estimate |
|---|---|
| Stage | About 4 minutes on a laptop from local disk (the prototype, all 13 tables; `digital_events` alone took 124 s). In CodeBuild, reading cross-region, expect about 10 minutes |
| Load | About 60 minutes: fresh DSQL tables accept a few thousand rows per second until their partitions split. To be measured on the first run |
| CodeBuild | `arm1.large` at $0.015/min × about 90 min ≈ **$1.35 per run** |
| DSQL writes | About 219,926 DPU ≈ **$1.76** (design doc §16), partly inside the free tier |
| DSQL storage | About 4.0 GB ≈ $1.33 per month |
| S3 staging | Well under 5 GB of Parquet, a few cents a month |
| Cross-region read | About 5.3 GB us-east-2 → us-east-1, a few cents, billed to the organizer as bucket owner |

## 11. Security

- **The organizer's keys** exist only in Secrets Manager and as CodeBuild environment variables (masked):
  - They are used only for DuckDB's S3 secret, scoped to the datathon bucket.
  - They never appear in the repo, Parquet files, the manifest or logs.
- **The keys are over-permissioned:** they can list every bucket in the organizer's account. We read only `data/` in the datathon bucket, and the team should tell the organizers.
- **`pii`:** no application role can read `pii` tables; tools see only the two views.
- **The team bucket** is private and SSL-only.

## 12. Out of scope

- Daily append, a moving clock, the update fixture (late file, duplicate, renamed column).
- Contract checks beyond the DDL constraints (the ownership invariant, the FX book rate).
- `data_backup_20260831/`.
- The tool Lambdas and their `AWS IAM GRANT` mappings.
- A resume flag.

## 13. To confirm on the first run

1. `aurora-dsql-loader --dry-run` accepts the typed Parquet against the existing tables, including their `CHECK` constraints.
2. The loader authenticates as `admin` with the CodeBuild role's credentials.
3. Design doc Q7: views over `pii` work for roles with no grant on `pii`. If they don't, the job writes a `bank.customer_profile` table instead.
4. Actual load throughput against the 60-minute estimate.
5. DuckDB reads the S3 glob in us-east-2 with the scoped secret.
