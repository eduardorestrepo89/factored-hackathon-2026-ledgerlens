# LedgerLens Data Loading Implementation Plan

> **Superseded** by [2026-10-02-data-pipeline.md](2026-10-02-data-pipeline.md) on 2026-10-02. Its `bank`/`pii` schemas and `app.load_manifest` were never built: every table is in `public`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load the organizer's static snapshot into Aurora DSQL once, at a fixed `as_of`, through a CDK-defined CodeBuild job, with lineage for every table.

**Architecture:** A small Python package, `data_load/`, reads the raw CSVs with DuckDB into tables built from one DDL file (`data_load/schema.sql`). DuckDB therefore enforces the contract before anything reaches AWS. The package then writes checksummed Parquet to a team bucket, recreates the `bank`/`pii` schemas in DSQL, bulk-loads them with AWS's `aurora-dsql-loader`, builds indexes, and records `app.load_manifest`. A CDK construct creates the DSQL cluster, the staging bucket, the secret holding the organizer's keys, and the CodeBuild project that runs `python -m data_load run`.

**Tech Stack:** Python 3.12, DuckDB 1.5.5, psycopg 3 with `aurora-dsql-python-connector`, boto3, `aurora-dsql-loader` v3.3.0, AWS CDK 2.260 (TypeScript), pytest, jest.

**Spec:** `docs/superpowers/specs/2026-09-29-data-loading-design.md`

## Global Constraints

- **Branch `feat/database`. Commit only the hunks you wrote.**
  - Several files still carry uncommitted `feat/design` edits: `infra-cdk/config.yaml` (the `admin_user_email` line), `infra-cdk/lib/backend-construct.ts`, `infra-cdk/lambdas/cedar-policy/index.py`, `docs/LEDGERLENS_PRODUCT_DESIGN.md` and `docs/LATAM_Bank_ERD.md`.
  - Never run `git add -A`, `git add .` or `git commit -a`. Use `git add -p` for files that already had edits.
- **Always run `uv run --no-project …`.** The repo root has a `pyproject.toml`, and without the flag `uv` creates `uv.lock` and installs the project.
- **Python dependencies are pinned in `data_load/requirements.txt`:** `duckdb==1.5.5` (the version the prototype was validated with), `boto3==1.43.105`, `psycopg[binary]==3.3.6`, `aurora-dsql-python-connector==0.2.7`, `PyYAML>=6.0.1`.
- **Loader:** `aurora-dsql-loader` release **v3.3.0**, asset `aurora-dsql-loader-aarch64-unknown-linux-musl.tar.gz`, SHA-256 `eb7a559f13aa3603704aae0e3e27b4f5e2bd3904ae9e656161df60170ce3dff5` (GitHub's published digest; the archive contains a single binary, `aurora-dsql-loader`).
- **Dates:** `as_of = "2026-06-17T23:59:59"` and `window_years = 2`, which gives an event window of **2024-06-18 → 2026-06-17** by `process_date`. Reference tables load in full. `daily_exchange_rates` is cut by `date`.
- **Expected staged rows, 15,745,982 in total:**

  | Table | Rows |
  |---|---:|
  | `bank.digital_events` | 10,303,685 |
  | `bank.transactions` | 2,946,214 |
  | `bank.campaign_sends` | 1,177,694 |
  | `bank.call_center_interactions` | 457,173 |
  | `bank.products` | 400,000 |
  | `pii.customers` | 150,000 |
  | `bank.satisfaction_surveys` | 141,726 |
  | `bank.call_transcripts` | 114,222 |
  | `bank.complaints` | 44,758 |
  | `bank.daily_exchange_rates` | 8,760 |
  | `pii.service_agents` | 1,200 |
  | `bank.branches` | 350 |
  | `bank.marketing_campaigns` | 200 |
- **Values stay untouched.** Nothing is cleaned or deduplicated. A duplicate primary key or a constraint violation fails the run.
- **DSQL rules:**
  - Connect as `admin` with `autocommit` on, because DSQL allows one DDL statement per transaction.
  - Build secondary indexes with `CREATE INDEX ASYNC` and wait with `SELECT sys.wait_for_job(job_id)`.
  - A connection lives at most 60 minutes, so reconnect after the bulk load.
- **Organizer data is read-only for the app.** No application role gets `INSERT`, `UPDATE` or `DELETE` on `bank`/`pii`, or any privilege on `pii` tables. Agent writes go to `app.card_blocks` and `app.claims`.
- **Secrets:**
  - Never open the organizer PDFs.
  - Never print, log or commit the organizer keys.
  - Only the human sets the value of the `ledgerlens/hackathon-s3` secret.
- **Regions:** the stack is in **us-east-1**; the hackathon bucket is in **us-east-2**.
- **Test command:** `uv run --no-project --with-requirements data_load/requirements.txt --with pytest python -m pytest <files> -v`, run from the repo root.
- **Lint:**
  - `uv run --no-project --with ruff ruff check --fix <files>`
  - `uv run --no-project --with ruff ruff format <files>` (ruff.toml: line length 88, rules E4/E7/E9/F/I).

## Review Focus

1. **Real CSVs start with a UTF-8 BOM and use CRLF line endings.** The first header must still match its DDL column. Accented enum values (`'Tarjeta Crédito'`) must pass their `CHECK`. The Task 2 fixtures write BOM + CRLF, and `test_reference_tables_load_in_full` pins both behaviors.
2. **Empty CSV fields must load as NULL, not `''`.** 221,033 real transactions have no `response_code`, and `''` would fail the `CHECK`. Pinned by `test_empty_field_loads_as_null` (Task 2).
3. **Re-running the job after a partial failure must work.** Roles and `app` indexes already exist, so the second run must skip them, not crash. Pinned by `test_apply_schema_is_rerunnable` (Task 4).
4. **One table's loader failure must fail the whole build,** after every table has been attempted, and name only the failed table. Pinned by `test_load_all_fails_after_every_table_was_attempted` (Task 4).
5. **A malformed or unusable `HACKATHON_S3` secret must fail with a message that never contains a key value.** Pinned by `test_secret_errors_name_keys_never_values` (Task 5) and `test_s3_secret_failure_does_not_echo_keys` (Task 2).

---

### Task 1: Schema file and statement classifier

**Files:**
- Create: `data_load/__init__.py`
- Create: `data_load/requirements.txt`
- Create: `data_load/schema.sql`
- Create: `data_load/ddl.py`
- Test: `tests/unit/test_data_load_ddl.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `data_load.ddl.SCHEMA_SQL: Path`
  - `data_load.ddl.split_statements(sql: str) -> list[str]`
  - `data_load.ddl.load_plan(sql: str | None = None) -> SchemaPlan`
  - `SchemaPlan` fields:
    - `schemas: list[str]`
    - `data_tables: dict[str, str]` (key `"bank.transactions"` → DDL)
    - `views: dict[str, str]`
    - `app_tables: list[str]`
    - `roles: dict[str, str]`
    - `grants: list[str]`
    - `data_indexes: list[str]`
    - `app_indexes: dict[str, str]` (index name → DDL)

- [ ] **Step 1: Create the package files**

`data_load/__init__.py`:

```python
"""LedgerLens data load: organizer CSVs -> validated Parquet -> Aurora DSQL.

Design: docs/superpowers/specs/2026-09-29-data-loading-design.md
"""
```

`data_load/requirements.txt`:

```text
duckdb==1.5.5
boto3==1.43.105
psycopg[binary]==3.3.6
aurora-dsql-python-connector==0.2.7
PyYAML>=6.0.1
```

- [ ] **Step 2: Write the failing tests**

`tests/unit/test_data_load_ddl.py`:

```python
"""schema.sql is the single contract for DuckDB (validation) and Aurora DSQL."""

import re

import duckdb
import pytest

from data_load.ddl import load_plan

BANK_PII = {
    "pii.customers", "pii.service_agents", "bank.products", "bank.branches",
    "bank.marketing_campaigns", "bank.daily_exchange_rates", "bank.transactions",
    "bank.call_center_interactions", "bank.call_transcripts",
    "bank.satisfaction_surveys", "bank.digital_events", "bank.complaints",
    "bank.campaign_sends",
}


@pytest.mark.unit
def test_plan_groups_every_statement():
    plan = load_plan()
    assert set(plan.data_tables) == BANK_PII
    assert set(plan.views) == {"bank.customer_profile", "bank.agent_roster"}
    assert len(plan.app_tables) == 7
    assert set(plan.roles) == {"ll_read", "ll_write", "ll_approvals", "ll_feedback"}
    assert len(plan.data_indexes) == 3
    assert set(plan.app_indexes) == {"idx_cases_customer_date", "idx_claims_customer_date"}


@pytest.mark.unit
def test_unknown_statement_is_rejected():
    with pytest.raises(ValueError, match="unclassified"):
        load_plan("DROP TABLE bank.transactions;")


@pytest.mark.unit
def test_duckdb_builds_every_data_table():
    plan = load_plan()
    con = duckdb.connect()
    for stmt in plan.schemas + list(plan.data_tables.values()):
        con.execute(stmt)
    count = con.sql(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema IN ('bank', 'pii')"
    ).fetchone()[0]
    assert count == 13


@pytest.mark.unit
def test_schema_fixes_from_the_spec():
    plan = load_plan()
    transcripts = plan.data_tables["bank.call_transcripts"]
    assert "duration_seconds integer NOT NULL" not in transcripts
    assert "AI Assistant" not in plan.data_tables["bank.complaints"]
    cases = next(s for s in plan.app_tables if "app.cases" in s)
    assert "claim_id varchar(40)" in cases and "complaint_id" not in cases


@pytest.mark.unit
def test_app_roles_cannot_write_or_see_organizer_data():
    for grant in load_plan().grants:
        m = re.fullmatch(r"GRANT (.+) ON (.+) TO \w+", grant)
        assert m, grant
        privileges = m[1]
        objects = [o.strip() for o in m[2].replace("SCHEMA ", "").split(",")]
        assert not any(o.startswith("pii") for o in objects), grant
        if privileges not in ("SELECT", "USAGE"):
            assert not any(o.startswith("bank") for o in objects), grant
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --no-project --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_ddl.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'data_load.ddl'`

- [ ] **Step 4: Write `data_load/schema.sql`**

This is Appendix A of the design doc v3 with the spec's section 6 changes:
- `call_transcripts.duration_seconds` is nullable;
- `'AI Assistant'` is gone from the complaints `CHECK`;
- `app.*` uses `IF NOT EXISTS`;
- `app.cases.claim_id` replaces `complaint_id`;
- the new `app.load_manifest` columns, `app.card_blocks` and `app.claims`;
- roles, grants and indexes.

```sql
-- LedgerLens Aurora DSQL schema: the single source of truth for types and constraints.
-- data_load runs the bank/pii CREATE TABLE statements in DuckDB (validation) and in DSQL.
-- File rules: statements end with a semicolon; no semicolon or double dash inside string literals.

CREATE SCHEMA IF NOT EXISTS bank;
CREATE SCHEMA IF NOT EXISTS pii;
CREATE SCHEMA IF NOT EXISTS app;

-- pii and bank: organizer data. Dropped and recreated by every load; read-only for the app.
CREATE TABLE pii.customers (
  customer_id varchar(30) PRIMARY KEY, document_number varchar(30) NOT NULL, document_type varchar(12) NOT NULL,
  first_name varchar(100) NOT NULL, last_name varchar(100) NOT NULL, date_of_birth date NOT NULL, gender varchar(1),
  email varchar(100), mobile_phone varchar(20), landline_phone varchar(20), address varchar(200), city varchar(100) NOT NULL,
  state varchar(100) NOT NULL, country varchar(50) NOT NULL, postal_code varchar(10), detected_accent varchar(50),
  segment varchar(50) NOT NULL, credit_score integer, estimated_monthly_income numeric(15,2), occupation varchar(100),
  marital_status varchar(20), education_level varchar(50), registration_date timestamp NOT NULL,
  registration_branch_id varchar(30), customer_status varchar(20) NOT NULL, last_updated timestamp NOT NULL,
  accepts_marketing boolean NOT NULL
);
CREATE TABLE pii.service_agents (
  agent_id varchar(30) PRIMARY KEY, employee_code varchar(15) NOT NULL, first_name varchar(100) NOT NULL,
  last_name varchar(100) NOT NULL, email varchar(100), phone varchar(20), native_accent varchar(50) NOT NULL,
  country_of_origin varchar(50) NOT NULL, assigned_branch_id varchar(30), agent_type varchar(30) NOT NULL,
  experience_level varchar(20) NOT NULL, languages varchar(100) NOT NULL, specialty varchar(100), hire_date date NOT NULL,
  avg_csat numeric(3,2), total_monthly_interactions integer, agent_status varchar(20) NOT NULL, work_shift varchar(20) NOT NULL
);
CREATE TABLE bank.products (
  product_id varchar(30) PRIMARY KEY, customer_id varchar(30) NOT NULL,
  product_type varchar(50) NOT NULL CHECK (product_type IN ('Cuenta Ahorro','Tarjeta Crédito','Cuenta Corriente','Tarjeta Débito','Préstamo Personal','Préstamo Hipotecario','Inversión','Seguro')),
  product_number varchar(30) NOT NULL, currency varchar(3) NOT NULL, current_balance numeric(15,2) NOT NULL,
  credit_limit numeric(15,2), interest_rate numeric(5,2), opening_date date NOT NULL, expiration_date date,
  opening_branch_id varchar(30), product_status varchar(20) NOT NULL CHECK (product_status IN ('Active','Blocked','Closed','Suspended')),
  opening_channel varchar(30) NOT NULL, has_linked_app boolean NOT NULL, days_past_due integer,
  last_transaction_date timestamp, last_updated timestamp NOT NULL
);
CREATE TABLE bank.branches (
  branch_id varchar(30) PRIMARY KEY, branch_code varchar(10) NOT NULL, branch_name varchar(100) NOT NULL,
  branch_type varchar(30) NOT NULL, address varchar(200) NOT NULL, city varchar(100) NOT NULL, state varchar(100) NOT NULL,
  country varchar(50) NOT NULL, postal_code varchar(10), geographic_zone varchar(50) NOT NULL, phone varchar(20) NOT NULL,
  email varchar(100), opening_time time NOT NULL, closing_time time NOT NULL, has_atms boolean NOT NULL, atm_count integer,
  has_teller_windows boolean NOT NULL, teller_window_count integer, latitude numeric(10,7), longitude numeric(10,7),
  branch_opening_date date NOT NULL, branch_status varchar(20) NOT NULL
);
CREATE TABLE bank.marketing_campaigns (
  campaign_id varchar(30) PRIMARY KEY, campaign_name varchar(150) NOT NULL, description text, campaign_type varchar(50) NOT NULL,
  campaign_objective varchar(100) NOT NULL, promoted_product varchar(50), target_segment varchar(50), target_country varchar(50),
  start_date date NOT NULL, end_date date NOT NULL, budget numeric(12,2), campaign_status varchar(20) NOT NULL,
  expected_conversion_rate numeric(5,2)
);
CREATE TABLE bank.daily_exchange_rates (
  date date NOT NULL, source_currency varchar(3) NOT NULL, target_currency varchar(3) NOT NULL,
  exchange_rate numeric(12,6) NOT NULL, buy_rate numeric(12,6), sell_rate numeric(12,6), source varchar(50),
  PRIMARY KEY (date, source_currency, target_currency)
);
CREATE TABLE bank.transactions (
  transaction_id varchar(30) PRIMARY KEY, transaction_date timestamp NOT NULL, process_date date NOT NULL,
  product_id varchar(30) NOT NULL, customer_id varchar(30) NOT NULL, transaction_type varchar(50) NOT NULL,
  transaction_category varchar(50), amount numeric(15,2) NOT NULL, currency varchar(3) NOT NULL, amount_usd numeric(15,2),
  channel varchar(30) NOT NULL, branch_id varchar(30), merchant_name varchar(150), merchant_category varchar(50),
  transaction_country varchar(50) NOT NULL, transaction_city varchar(100),
  transaction_status varchar(20) NOT NULL CHECK (transaction_status IN ('Approved','Declined','Pending','Reversed')),
  response_code varchar(10) CHECK (response_code IN ('00','05','14','51','54')),
  is_fraud boolean NOT NULL, fraud_score numeric(5,2), latitude numeric(10,7), longitude numeric(10,7)
);
CREATE TABLE bank.call_center_interactions (
  interaction_id varchar(30) PRIMARY KEY, interaction_date timestamp NOT NULL, process_date date NOT NULL,
  customer_id varchar(30) NOT NULL, agent_id varchar(30), interaction_type varchar(30) NOT NULL, channel varchar(30) NOT NULL,
  contact_reason varchar(100) NOT NULL, reason_category varchar(50) NOT NULL, duration_seconds integer, wait_time_seconds integer,
  was_resolved boolean, requires_followup boolean NOT NULL, detected_sentiment varchar(20), sentiment_score numeric(3,2),
  customer_detected_accent varchar(50), agent_used_accent varchar(50), was_escalated boolean NOT NULL,
  mentioned_products varchar(200), has_transcript boolean NOT NULL, has_recording boolean NOT NULL
);
CREATE TABLE bank.call_transcripts (
  transcript_id varchar(30) PRIMARY KEY, interaction_id varchar(30) NOT NULL, process_date date NOT NULL,
  customer_id varchar(30) NOT NULL, agent_id varchar(30) NOT NULL, full_text text NOT NULL, customer_text text, agent_text text,
  detected_language varchar(10) NOT NULL, detected_accent varchar(50), accent_confidence numeric(3,2),
  detected_keywords varchar(500), mentioned_entities text, detected_intents varchar(300), main_topics varchar(300),
  transcription_model varchar(50) NOT NULL, audio_quality varchar(20), duration_seconds integer
);
CREATE TABLE bank.satisfaction_surveys (
  survey_id varchar(30) PRIMARY KEY, survey_date timestamp NOT NULL, process_date date NOT NULL,
  interaction_id varchar(30) NOT NULL, customer_id varchar(30), agent_id varchar(30), survey_type varchar(20) NOT NULL,
  send_channel varchar(30), main_score smallint, nps_category varchar(20), question_1_text text, question_1_response smallint,
  question_2_text text, question_2_response smallint, question_3_text text, question_3_response smallint, open_comments text,
  comment_sentiment varchar(20), response_time_hours numeric(8,2), campaign_response_rate numeric(5,2)
);
CREATE TABLE bank.digital_events (
  event_id varchar(30) PRIMARY KEY, event_date timestamp NOT NULL, process_date date NOT NULL, customer_id varchar(30),
  session_id varchar(50) NOT NULL, event_type varchar(50) NOT NULL, event_category varchar(50) NOT NULL, channel varchar(30) NOT NULL,
  platform varchar(30), browser varchar(50), app_version varchar(20), page_url varchar(300), page_title varchar(200),
  action varchar(100), element_id varchar(100), product_id varchar(30), event_value numeric(15,2), duration_seconds integer,
  ip_address varchar(45), ip_country varchar(50), ip_city varchar(100), is_mobile boolean NOT NULL, referrer varchar(300),
  utm_source varchar(100), utm_medium varchar(100), utm_campaign varchar(100)
);
CREATE TABLE bank.complaints (
  complaint_id varchar(30) PRIMARY KEY, creation_date timestamp NOT NULL, process_date date NOT NULL,
  customer_id varchar(30) NOT NULL, case_type varchar(30) NOT NULL,
  category varchar(100) NOT NULL CHECK (category IN ('Branch','Fees','Service','Technical','Transactions')),
  subcategory varchar(100),
  reception_channel varchar(30) NOT NULL CHECK (reception_channel IN ('Call Center','Email','Web','App','Branch','Regulator')),
  affected_product_id varchar(30), related_branch_id varchar(30), origin_interaction_id varchar(30), description text NOT NULL,
  claimed_amount numeric(15,2), currency varchar(3), priority varchar(20) NOT NULL, status varchar(30) NOT NULL,
  assigned_agent_id varchar(30), assignment_date timestamp, first_response_date timestamp, resolution_date timestamp,
  closing_date timestamp, sla_breached boolean NOT NULL, resolution_days integer, resolution text,
  compensation_granted numeric(15,2), resolution_satisfaction smallint, is_repeat_complainer boolean NOT NULL
);
CREATE TABLE bank.campaign_sends (
  send_id varchar(30) PRIMARY KEY, send_date timestamp NOT NULL, process_date date NOT NULL, campaign_id varchar(30) NOT NULL,
  customer_id varchar(30) NOT NULL, send_channel varchar(30) NOT NULL, template_used varchar(100), subject varchar(200),
  send_status varchar(20) NOT NULL, was_delivered boolean NOT NULL, was_opened boolean, open_date timestamp, was_clicked boolean,
  click_date timestamp, click_count integer, had_conversion boolean NOT NULL, conversion_date timestamp,
  conversion_value numeric(15,2), open_device varchar(30), open_country varchar(50), failure_reason varchar(200),
  send_cost numeric(10,4)
);

CREATE VIEW bank.customer_profile AS
  SELECT customer_id, first_name, country, customer_status FROM pii.customers;
CREATE VIEW bank.agent_roster AS
  SELECT agent_id, languages, specialty, work_shift, agent_status FROM pii.service_agents;

-- app: written by LedgerLens. Created once, never dropped by a load.
CREATE TABLE IF NOT EXISTS app.approvals (
  approval_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), session_id varchar(100) NOT NULL, customer_id varchar(30) NOT NULL,
  action varchar(20) NOT NULL CHECK (action IN ('block_card','open_claim')), target_ids text NOT NULL, readback text NOT NULL,
  status varchar(10) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','used')),
  created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL, approved_at timestamptz, used_at timestamptz
);
CREATE TABLE IF NOT EXISTS app.cases (
  case_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), customer_id varchar(30) NOT NULL, claim_id varchar(40),
  queue varchar(50) NOT NULL, priority varchar(10) NOT NULL, reason varchar(30) NOT NULL, customer_language varchar(5) NOT NULL,
  payload jsonb NOT NULL, status varchar(20) NOT NULL DEFAULT 'open', created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS app.audit_log (
  audit_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), created_at timestamptz NOT NULL DEFAULT now(), actor_sub varchar(64) NOT NULL,
  customer_id varchar(30), session_id varchar(100), tool varchar(60) NOT NULL, approval_id uuid, input jsonb, result jsonb,
  outcome varchar(20) NOT NULL
);
CREATE TABLE IF NOT EXISTS app.feedback (
  feedback_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_sub varchar(64) NOT NULL, session_id varchar(100) NOT NULL,
  message text NOT NULL, feedback_type varchar(10) NOT NULL CHECK (feedback_type IN ('positive','negative')), comment text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS app.load_manifest (
  table_name varchar(60) NOT NULL, as_of timestamp NOT NULL, window_start date NOT NULL, window_end date NOT NULL,
  source_uri text NOT NULL, source_files integer NOT NULL, source_etag_digest varchar(64) NOT NULL,
  staged_uri text NOT NULL, staged_sha256 varchar(64) NOT NULL, rows_staged bigint NOT NULL, rows_loaded bigint NOT NULL,
  loaded_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (table_name, as_of)
);
CREATE TABLE IF NOT EXISTS app.card_blocks (
  card_id varchar(30) PRIMARY KEY, customer_id varchar(30) NOT NULL, approval_id uuid NOT NULL,
  business_date date NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS app.claims (
  claim_id varchar(40) PRIMARY KEY, customer_id varchar(30) NOT NULL, approval_id uuid NOT NULL,
  claim_type varchar(10) NOT NULL CHECK (claim_type IN ('fraud','dispute')), transaction_ids jsonb NOT NULL,
  claimed_amount numeric(15,2) NOT NULL, currency varchar(3) NOT NULL, customer_statement varchar(500),
  business_date date NOT NULL, deadline_date date NOT NULL, rule_ids jsonb NOT NULL,
  status varchar(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open','handed_off','closed')),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Roles: created only if missing. Grants: re-applied after every load (recreated tables lose them).
CREATE ROLE ll_read WITH LOGIN;
CREATE ROLE ll_write WITH LOGIN;
CREATE ROLE ll_approvals WITH LOGIN;
CREATE ROLE ll_feedback WITH LOGIN;
GRANT USAGE ON SCHEMA bank TO ll_read;
GRANT USAGE ON SCHEMA app TO ll_read;
GRANT SELECT ON bank.products, bank.transactions, bank.complaints, bank.customer_profile, bank.agent_roster TO ll_read;
GRANT SELECT ON app.approvals, app.cases, app.card_blocks, app.claims TO ll_read;
GRANT USAGE ON SCHEMA bank TO ll_write;
GRANT USAGE ON SCHEMA app TO ll_write;
GRANT SELECT ON bank.products, bank.transactions, bank.complaints, bank.customer_profile, bank.agent_roster TO ll_write;
GRANT SELECT ON app.approvals, app.cases, app.card_blocks, app.claims TO ll_write;
GRANT INSERT, UPDATE ON app.approvals, app.claims TO ll_write;
GRANT INSERT ON app.card_blocks, app.cases, app.audit_log TO ll_write;
GRANT USAGE ON SCHEMA app TO ll_approvals;
GRANT SELECT, UPDATE ON app.approvals TO ll_approvals;
GRANT USAGE ON SCHEMA app TO ll_feedback;
GRANT INSERT ON app.feedback TO ll_feedback;

-- Secondary indexes, only for queries the tools run. bank: rebuilt after every load. app: created once.
CREATE INDEX ASYNC idx_transactions_customer_date ON bank.transactions (customer_id, transaction_date);
CREATE INDEX ASYNC idx_products_customer ON bank.products (customer_id);
CREATE INDEX ASYNC idx_complaints_customer_date ON bank.complaints (customer_id, creation_date);
CREATE INDEX ASYNC idx_cases_customer_date ON app.cases (customer_id, created_at);
CREATE INDEX ASYNC idx_claims_customer_date ON app.claims (customer_id, business_date);
```

- [ ] **Step 5: Write `data_load/ddl.py`**

```python
"""Split schema.sql into the groups the load runs at different moments."""

import re
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_SQL = Path(__file__).with_name("schema.sql")


@dataclass
class SchemaPlan:
    schemas: list[str] = field(default_factory=list)
    data_tables: dict[str, str] = field(default_factory=dict)  # "bank.x" -> DDL
    views: dict[str, str] = field(default_factory=dict)  # "bank.v" -> DDL
    app_tables: list[str] = field(default_factory=list)
    roles: dict[str, str] = field(default_factory=dict)  # "ll_read" -> CREATE ROLE
    grants: list[str] = field(default_factory=list)
    data_indexes: list[str] = field(default_factory=list)  # rebuilt every load
    app_indexes: dict[str, str] = field(default_factory=dict)  # name -> DDL, once


def split_statements(sql: str) -> list[str]:
    """Drop '--' comments, split on ';', collapse whitespace."""
    without_comments = re.sub(r"--[^\n]*", "", sql)
    return [" ".join(s.split()) for s in without_comments.split(";") if s.strip()]


def load_plan(sql: str | None = None) -> SchemaPlan:
    if sql is None:
        sql = SCHEMA_SQL.read_text(encoding="utf-8")
    plan = SchemaPlan()
    for stmt in split_statements(sql):
        if re.fullmatch(r"CREATE SCHEMA IF NOT EXISTS \w+", stmt):
            plan.schemas.append(stmt)
        elif m := re.match(r"CREATE TABLE ((?:bank|pii)\.\w+) \(", stmt):
            plan.data_tables[m[1]] = stmt
        elif m := re.match(r"CREATE VIEW (\w+\.\w+) AS ", stmt):
            plan.views[m[1]] = stmt
        elif re.match(r"CREATE TABLE IF NOT EXISTS app\.\w+ \(", stmt):
            plan.app_tables.append(stmt)
        elif m := re.fullmatch(r"CREATE ROLE (\w+) WITH LOGIN", stmt):
            plan.roles[m[1]] = stmt
        elif stmt.startswith("GRANT "):
            plan.grants.append(stmt)
        elif m := re.match(r"CREATE INDEX ASYNC (\w+) ON (bank|pii|app)\.", stmt):
            if m[2] == "app":
                plan.app_indexes[m[1]] = stmt
            else:
                plan.data_indexes.append(stmt)
        else:
            raise ValueError(f"schema.sql: unclassified statement: {stmt[:80]}")
    return plan
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run --no-project --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_ddl.py -v`
Expected: 5 passed.

- [ ] **Step 7 (optional, if the `aurora-dsql` MCP is available): lint the DDL**

Pass the contents of `data_load/schema.sql` to `dsql_lint` (without `fix`). Expected: 0 errors. Warnings about `CREATE ROLE` or `GRANT` are fine. Fix any error in `schema.sql`, then re-run Step 6.

- [ ] **Step 8: Lint and commit**

```bash
uv run --no-project --with ruff ruff check --fix data_load tests/unit/test_data_load_ddl.py
uv run --no-project --with ruff ruff format data_load tests/unit/test_data_load_ddl.py
git add data_load/__init__.py data_load/requirements.txt data_load/schema.sql data_load/ddl.py tests/unit/test_data_load_ddl.py
git commit -m "feat(data-load): add DSQL schema as single contract and statement classifier"
```

---

### Task 2: Stage CSVs into validated Parquet with DuckDB

**Files:**
- Create: `data_load/stage.py`
- Create: `tests/unit/data_load_fixtures.py`
- Test: `tests/unit/test_data_load_stage.py`

**Interfaces:**
- Consumes: `data_load.ddl.load_plan`, `SchemaPlan.schemas`, `SchemaPlan.data_tables`.
- Produces:
  - `EVENT_TABLES: frozenset[str]` (bare table names)
  - `StageError(RuntimeError)`
  - `Staged(table: str, path: Path, rows: int, sha256: str)`
  - `load_window(as_of: datetime, window_years: int) -> tuple[date, date]`
  - `sha256_file(path: Path) -> str`
  - `stage(source: str, out_dir: Path, as_of: datetime, window_years: int, *, s3: dict | None = None, plan: SchemaPlan | None = None, tables: list[str] | None = None) -> list[Staged]`
- **Behavior contract:**
  - `source` is a local directory or an `s3://bucket/prefix` using the organizer layout: event tables in `<table>/year=/month=/day=/*.csv`, other tables in `<table>.csv`.
  - `s3` is the parsed secret dict with keys `aws_access_key_id`, `aws_secret_access_key`, `bucket` and `region`.
  - Parquet is written to `out_dir/<table>.parquet`.

- [ ] **Step 1: Write the fixture helpers**

`tests/unit/data_load_fixtures.py`:

```python
"""Tiny organizer-style CSV trees for data_load tests.

Files are written the way the organizer's are: UTF-8 with a BOM and CRLF endings.
"""

from datetime import datetime
from pathlib import Path

AS_OF = datetime(2026, 6, 17, 23, 59, 59)

TX_HEADER = [
    "transaction_id", "transaction_date", "process_date", "product_id", "customer_id",
    "transaction_type", "amount", "currency", "channel", "transaction_country",
    "transaction_status", "response_code", "is_fraud",
]


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(header)] + [",".join(row) for row in rows]
    path.write_bytes(("﻿" + "\r\n".join(lines) + "\r\n").encode("utf-8"))


def tx(transaction_id: str, transaction_date: str, process_date: str, code: str = "00") -> list[str]:
    return [
        transaction_id, transaction_date, process_date, "PRD-1", "CLI-1", "Compra",
        "10.50", "USD", "App", "México", "Approved", code, "False",
    ]


def write_transactions(root: Path, rows: list[list[str]]) -> None:
    """One file per process_date partition, like data/transactions/year=/month=/day=/."""
    by_day: dict[str, list[list[str]]] = {}
    for row in rows:
        by_day.setdefault(row[2], []).append(row)
    for day, day_rows in by_day.items():
        y, m, d = day.split("-")
        name = f"transactions_{y}{m}{d}.csv"
        write_csv(root / "transactions" / f"year={y}" / f"month={m}" / f"day={d}" / name, TX_HEADER, day_rows)
```

- [ ] **Step 2: Write the failing tests**

`tests/unit/test_data_load_stage.py`:

```python
"""stage(): window by business date, DDL-enforced types and constraints, Parquet out."""

import hashlib
from datetime import date

import duckdb
import pytest
from data_load_fixtures import AS_OF, tx, write_csv, write_transactions

from data_load.stage import StageError, _create_s3_secret, load_window, stage

TX = ["bank.transactions"]


def read(path, columns):
    return duckdb.sql(f"SELECT {columns} FROM '{path.as_posix()}' ORDER BY 1").fetchall()


@pytest.mark.unit
def test_load_window_is_two_years_ending_at_as_of():
    assert load_window(AS_OF, 2) == (date(2024, 6, 18), date(2026, 6, 17))


@pytest.mark.unit
def test_window_keeps_business_day_rows(tmp_path):
    write_transactions(tmp_path / "src", [
        tx("T1", "2026-06-17 10:00:00", "2026-06-17"),
        tx("T2", "2024-06-17 10:00:00", "2024-06-17"),  # one day before the window
        tx("T3", "2026-06-18 03:00:00", "2026-06-17"),  # after midnight, same business day
        tx("T4", "2024-06-18 00:00:01", "2024-06-18"),  # first day of the window
    ])
    [staged] = stage((tmp_path / "src").as_posix(), tmp_path / "out", AS_OF, 2, tables=TX)
    assert staged.rows == 3
    assert read(staged.path, "transaction_id") == [("T1",), ("T3",), ("T4",)]


@pytest.mark.unit
def test_empty_field_loads_as_null(tmp_path):
    write_transactions(tmp_path / "src", [tx("T1", "2026-06-17 10:00:00", "2026-06-17", code="")])
    [staged] = stage((tmp_path / "src").as_posix(), tmp_path / "out", AS_OF, 2, tables=TX)
    assert read(staged.path, "transaction_id, response_code") == [("T1", None)]


@pytest.mark.unit
def test_check_violation_names_the_table(tmp_path):
    write_transactions(tmp_path / "src", [tx("T1", "2026-06-17 10:00:00", "2026-06-17", code="99")])
    with pytest.raises(StageError, match=r"^bank\.transactions: .*CHECK"):
        stage((tmp_path / "src").as_posix(), tmp_path / "out", AS_OF, 2, tables=TX)


@pytest.mark.unit
def test_duplicate_primary_key_is_an_error(tmp_path):
    row = tx("T1", "2026-06-17 10:00:00", "2026-06-17")
    write_transactions(tmp_path / "src", [row, row])
    with pytest.raises(StageError, match=r"^bank\.transactions: "):
        stage((tmp_path / "src").as_posix(), tmp_path / "out", AS_OF, 2, tables=TX)


@pytest.mark.unit
def test_reference_tables_load_in_full(tmp_path):
    header = [
        "product_id", "customer_id", "product_type", "product_number", "currency",
        "current_balance", "opening_date", "product_status", "opening_channel",
        "has_linked_app", "last_updated",
    ]
    write_csv(tmp_path / "src" / "products.csv", header, [
        ["PRD-1", "CLI-1", "Tarjeta Crédito", "4111", "USD", "100.00", "2026-06-17",
         "Active", "App", "True", "2027-06-15 19:35:27"],
        ["PRD-2", "CLI-1", "Cuenta Ahorro", "5222", "USD", "5.00", "2018-06-18",
         "Active", "Branch", "False", "2018-06-20 05:21:54"],
    ])
    [staged] = stage((tmp_path / "src").as_posix(), tmp_path / "out", AS_OF, 2, tables=["bank.products"])
    assert read(staged.path, "product_id, product_type") == [
        ("PRD-1", "Tarjeta Crédito"), ("PRD-2", "Cuenta Ahorro"),
    ]


@pytest.mark.unit
def test_exchange_rates_are_cut_by_date(tmp_path):
    header = ["date", "source_currency", "target_currency", "exchange_rate"]
    write_csv(tmp_path / "src" / "daily_exchange_rates.csv", header, [
        ["2024-06-17", "USD", "COP", "4000.000000"],
        ["2024-06-18", "USD", "COP", "4000.000000"],
        ["2026-06-17", "USD", "COP", "4000.000000"],
    ])
    [staged] = stage((tmp_path / "src").as_posix(), tmp_path / "out", AS_OF, 2,
                     tables=["bank.daily_exchange_rates"])
    assert staged.rows == 2


@pytest.mark.unit
def test_parquet_checksum_and_count(tmp_path):
    write_transactions(tmp_path / "src", [tx("T1", "2026-06-17 10:00:00", "2026-06-17")])
    [staged] = stage((tmp_path / "src").as_posix(), tmp_path / "out", AS_OF, 2, tables=TX)
    assert staged.table == "bank.transactions"
    assert staged.path == tmp_path / "out" / "transactions.parquet"
    assert staged.sha256 == hashlib.sha256(staged.path.read_bytes()).hexdigest()
    assert duckdb.sql(f"SELECT count(*) FROM '{staged.path.as_posix()}'").fetchone()[0] == 1


@pytest.mark.unit
def test_s3_secret_failure_does_not_echo_keys():
    con = duckdb.connect()
    try:
        con.execute("INSTALL httpfs")
    except duckdb.Error:
        pytest.skip("httpfs extension not downloadable (offline)")
    secret = {"aws_access_key_id": "fake-key-id", "aws_secret_access_key": "fake-secret-value",
              "region": "us-east-2", "bucket": "b"}
    _create_s3_secret(con, secret)
    with pytest.raises(StageError) as err:  # second CREATE SECRET with the same name fails
        _create_s3_secret(con, secret)
    assert "fake-key-id" not in str(err.value) and "fake-secret-value" not in str(err.value)
    assert err.value.__cause__ is None and err.value.__suppress_context__
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --no-project --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_stage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'data_load.stage'`

- [ ] **Step 4: Write `data_load/stage.py`**

```python
"""Stage organizer CSVs as typed, validated Parquet with DuckDB.

schema.sql is the contract: every row is read as text and inserted into tables built
from that DDL, so DuckDB casts each column and enforces NOT NULL, CHECK and PRIMARY
KEY before anything reaches AWS. Values are never changed; duplicates are errors.
"""

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

from data_load.ddl import SchemaPlan, load_plan

EVENT_TABLES = frozenset(
    {
        "call_center_interactions",
        "call_transcripts",
        "campaign_sends",
        "complaints",
        "digital_events",
        "satisfaction_surveys",
        "transactions",
    }
)
DATE_FILTERED = {"daily_exchange_rates": "date"}  # reference table cut to the window


class StageError(RuntimeError):
    """A source row broke schema.sql. The message names the table."""


@dataclass(frozen=True)
class Staged:
    table: str  # schema-qualified, e.g. "bank.transactions"
    path: Path
    rows: int
    sha256: str


def load_window(as_of: datetime, window_years: int) -> tuple[date, date]:
    """Event rows kept: process_date in [as_of::date - (365*years - 1), as_of::date]."""
    end = as_of.date()
    return end - timedelta(days=365 * window_years - 1), end


def source_glob(source: str, table: str) -> str:
    base = source.rstrip("/")
    if table in EVENT_TABLES:  # year=/month=/day=/<table>_<yyyymmdd>.csv
        return f"{base}/{table}/*/*/*/*.csv"
    return f"{base}/{table}.csv"


def window_filter(table: str, start: date, end: date) -> str:
    column = "process_date" if table in EVENT_TABLES else DATE_FILTERED.get(table)
    if column is None:
        return ""  # reference tables load in full: entity dates are not causal
    return f"WHERE {column}::DATE BETWEEN DATE '{start}' AND DATE '{end}'"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _create_s3_secret(con: duckdb.DuckDBPyConnection, s3: dict) -> None:
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    try:
        con.execute(
            "CREATE SECRET hackathon (TYPE s3, "
            f"KEY_ID {_sql_literal(s3['aws_access_key_id'])}, "
            f"SECRET {_sql_literal(s3['aws_secret_access_key'])}, "
            f"REGION {_sql_literal(s3['region'])}, "
            f"SCOPE {_sql_literal('s3://' + s3['bucket'])})"
        )
    except duckdb.Error:
        # never chain the original error: its message may quote the statement
        raise StageError("could not create the DuckDB S3 secret from HACKATHON_S3") from None


def stage(
    source: str,
    out_dir: Path,
    as_of: datetime,
    window_years: int,
    *,
    s3: dict | None = None,
    plan: SchemaPlan | None = None,
    tables: list[str] | None = None,
) -> list[Staged]:
    plan = plan or load_plan()
    start, end = load_window(as_of, window_years)
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "stage.duckdb"  # on disk: digital_events has 10.3M rows
    db_path.unlink(missing_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        if s3:
            _create_s3_secret(con, s3)
        for stmt in plan.schemas:
            con.execute(stmt)
        return [
            _stage_table(con, source, out_dir, qname, ddl, start, end)
            for qname, ddl in plan.data_tables.items()
            if not tables or qname in tables
        ]
    finally:
        con.close()


def _stage_table(con, source, out_dir, qname, ddl, start, end) -> Staged:
    table = qname.split(".")[1]
    con.execute(ddl)
    csv = (
        f"read_csv('{source_glob(source, table)}', header=true, all_varchar=true, "
        "union_by_name=true, hive_partitioning=false)"
    )
    where = window_filter(table, start, end)
    try:
        con.execute(f"INSERT INTO {qname} BY NAME SELECT * FROM {csv} {where}")
    except duckdb.Error as e:
        raise StageError(f"{qname}: {e}") from None
    path = out_dir / f"{table}.parquet"
    con.execute(f"COPY {qname} TO '{path.as_posix()}' (FORMAT parquet)")
    rows = con.execute(f"SELECT count(*) FROM {qname}").fetchone()[0]
    print(f"staged {qname}: {rows:,} rows", flush=True)
    return Staged(qname, path, rows, sha256_file(path))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --no-project --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_stage.py -v`
Expected: 9 passed, or 8 passed and 1 skipped if the httpfs extension can't be downloaded.

- [ ] **Step 6: Lint and commit**

```bash
uv run --no-project --with ruff ruff check --fix data_load tests/unit/test_data_load_stage.py tests/unit/data_load_fixtures.py
uv run --no-project --with ruff ruff format data_load tests/unit/test_data_load_stage.py tests/unit/data_load_fixtures.py
git add data_load/stage.py tests/unit/data_load_fixtures.py tests/unit/test_data_load_stage.py
git commit -m "feat(data-load): stage organizer CSVs into DDL-validated Parquet with DuckDB"
```

---

### Task 3: Source fingerprints (lineage and drift check)

**Files:**
- Create: `data_load/source.py`
- Test: `tests/unit/test_data_load_source.py`

**Interfaces:**
- Consumes: `data_load.stage.EVENT_TABLES`.
- Produces:
  - `source_prefix(prefix: str, table: str) -> str` (`table` may be schema-qualified)
  - `list_objects(s3, bucket: str, key_prefix: str) -> list[tuple[str, str]]`
  - `etag_digest(objects: list[tuple[str, str]]) -> str`
  - `fingerprint(s3, bucket: str, prefix: str, tables: list[str]) -> dict[str, tuple[int, str]]` (table → (file count, digest))
  - `drift(recorded: dict[str, str], current: dict[str, str]) -> list[str]`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_data_load_source.py`:

```python
"""Source fingerprints: detect a re-upload of the organizer's files."""

from unittest import mock

import pytest

from data_load.source import (
    drift,
    etag_digest,
    fingerprint,
    list_objects,
    source_prefix,
)


def fake_s3(objects_by_prefix):
    s3 = mock.MagicMock()

    def paginate(Bucket, Prefix):
        return [{"Contents": [{"Key": k, "ETag": f'"{e}"'} for k, e in objects_by_prefix.get(Prefix, [])]}, {}]

    s3.get_paginator.return_value.paginate.side_effect = paginate
    return s3


@pytest.mark.unit
def test_source_prefix_for_event_and_reference_tables():
    assert source_prefix("data/", "bank.transactions") == "data/transactions/"
    assert source_prefix("data/", "pii.customers") == "data/customers.csv"


@pytest.mark.unit
def test_list_objects_reads_every_page_and_strips_quotes():
    s3 = fake_s3({"data/transactions/": [("data/transactions/a.csv", "e1")]})
    assert list_objects(s3, "b", "data/transactions/") == [("data/transactions/a.csv", "e1")]


@pytest.mark.unit
def test_digest_ignores_order_and_catches_rewrites():
    a, b = ("k1", "e1"), ("k2", "e2")
    assert etag_digest([a, b]) == etag_digest([b, a])
    assert etag_digest([a, b]) != etag_digest([a, ("k2", "e3")])
    assert etag_digest([a, b]) != etag_digest([a])


@pytest.mark.unit
def test_fingerprint_counts_files_per_table():
    s3 = fake_s3({
        "data/transactions/": [("data/transactions/1.csv", "e1"), ("data/transactions/2.csv", "e2")],
        "data/customers.csv": [("data/customers.csv", "e3")],
    })
    prints = fingerprint(s3, "b", "data/", ["bank.transactions", "pii.customers"])
    assert prints["bank.transactions"][0] == 2
    assert prints["pii.customers"] == (1, etag_digest([("data/customers.csv", "e3")]))


@pytest.mark.unit
def test_drift_lists_changed_and_one_sided_tables():
    assert drift({"a": "1", "b": "2"}, {"a": "1", "b": "2"}) == []
    assert drift({"a": "1", "b": "2"}, {"a": "1", "b": "X", "c": "3"}) == ["b", "c"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-project --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_source.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'data_load.source'`

- [ ] **Step 3: Write `data_load/source.py`**

```python
"""Fingerprint the organizer's source files so a later re-upload is detectable."""

import hashlib

from data_load.stage import EVENT_TABLES


def source_prefix(prefix: str, table: str) -> str:
    """S3 key prefix of one table's source files; `table` may be schema-qualified."""
    name = table.split(".")[-1]
    return f"{prefix}{name}/" if name in EVENT_TABLES else f"{prefix}{name}.csv"


def list_objects(s3, bucket: str, key_prefix: str) -> list[tuple[str, str]]:
    objects = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=key_prefix):
        objects += [(o["Key"], o["ETag"].strip('"')) for o in page.get("Contents", [])]
    return objects


def etag_digest(objects: list[tuple[str, str]]) -> str:
    """SHA-256 over sorted 'key etag' lines: any added, removed or rewritten file changes it."""
    lines = "\n".join(f"{key} {etag}" for key, etag in sorted(objects))
    return hashlib.sha256(lines.encode()).hexdigest()


def fingerprint(s3, bucket: str, prefix: str, tables: list[str]) -> dict[str, tuple[int, str]]:
    """table -> (number of source files, ETag digest)."""
    result = {}
    for table in tables:
        objects = list_objects(s3, bucket, source_prefix(prefix, table))
        result[table] = (len(objects), etag_digest(objects))
    return result


def drift(recorded: dict[str, str], current: dict[str, str]) -> list[str]:
    """Tables whose digest differs, or that exist on only one side."""
    tables = recorded.keys() | current.keys()
    return sorted(t for t in tables if recorded.get(t) != current.get(t))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --no-project --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_source.py -v`
Expected: 5 passed.

- [ ] **Step 5: Lint and commit**

```bash
uv run --no-project --with ruff ruff check --fix data_load tests/unit/test_data_load_source.py
uv run --no-project --with ruff ruff format data_load tests/unit/test_data_load_source.py
git add data_load/source.py tests/unit/test_data_load_source.py
git commit -m "feat(data-load): fingerprint source files by ETag for lineage and drift checks"
```

---

### Task 4: Aurora DSQL side: schema, roles, loader, indexes, manifest

**Files:**
- Create: `data_load/dsql.py`
- Test: `tests/unit/test_data_load_dsql.py`

**Interfaces:**
- Consumes: `data_load.ddl.SchemaPlan` and `load_plan`.
- Produces:
  - `ManifestRow(table_name: str, as_of: datetime, window_start: date, window_end: date, source_uri: str, source_files: int, source_etag_digest: str, staged_uri: str, staged_sha256: str, rows_staged: int)`
  - `connect(endpoint: str, profile: str | None = None)` (a psycopg connection with `autocommit`)
  - `schema_statements(plan) -> list[str]`
  - `apply_schema(conn, plan) -> None`
  - `build_indexes(conn, statements: list[str]) -> None`
  - `loader_cmd(endpoint: str, uri: str, table: str) -> list[str]`
  - `load_all(endpoint: str, uris: dict[str, str], run=subprocess.run, parallel: int = 4) -> None`
  - `record_manifest(conn, rows: list[ManifestRow]) -> None`
  - `recorded_digests(conn) -> dict[str, str]`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_data_load_dsql.py`:

```python
"""DSQL steps, tested against a fake connection (no cluster needed)."""

import subprocess
from contextlib import contextmanager
from datetime import date, datetime

import pytest

from data_load.ddl import load_plan
from data_load.dsql import (
    ManifestRow,
    apply_schema,
    build_indexes,
    load_all,
    loader_cmd,
    record_manifest,
    schema_statements,
)


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.rows = conn, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))
        self.rows = self.conn.respond(sql)

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, respond=lambda sql: []):
        self.executed, self.respond, self.transactions = [], respond, 0

    def cursor(self):
        return FakeCursor(self)

    @contextmanager
    def transaction(self):
        self.transactions += 1
        yield

    def sql(self):
        return [s for s, _ in self.executed]


def manifest_row(table="bank.transactions", rows=10):
    return ManifestRow(
        table, datetime(2026, 6, 17, 23, 59, 59), date(2024, 6, 18), date(2026, 6, 17),
        "s3://org/data/transactions/", 1097, "d" * 64, "s3://team/staging/t.parquet", "s" * 64, rows,
    )


@pytest.mark.unit
def test_schema_statements_recreate_organizer_tables_and_keep_app():
    plan = load_plan()
    stmts = schema_statements(plan)
    first = stmts.index
    assert first("DROP VIEW IF EXISTS bank.customer_profile") < first("DROP TABLE IF EXISTS pii.customers")
    assert first("DROP TABLE IF EXISTS pii.customers") < first(plan.data_tables["pii.customers"])
    assert first(plan.data_tables["pii.customers"]) < first(plan.views["bank.customer_profile"])
    assert not any(s.startswith("DROP TABLE IF EXISTS app.") for s in stmts)
    assert all(s in stmts for s in plan.app_tables)


@pytest.mark.unit
def test_apply_schema_is_rerunnable():
    def respond(sql):
        if sql.startswith("SELECT rolname"):
            return [("ll_read",), ("ll_write",)]
        if sql.startswith("SELECT indexname"):
            return [("idx_cases_customer_date",)]
        if sql.startswith("CREATE INDEX ASYNC"):
            return [("job-1",)]
        if sql.startswith("SELECT sys.wait_for_job"):
            return [(True,)]
        return []

    plan, conn = load_plan(), FakeConn(respond)
    apply_schema(conn, plan)
    sql = conn.sql()
    assert "CREATE ROLE ll_read WITH LOGIN" not in sql
    assert "CREATE ROLE ll_approvals WITH LOGIN" in sql
    assert all(g in sql for g in plan.grants)
    created = [s for s in sql if s.startswith("CREATE INDEX ASYNC")]
    assert created == [plan.app_indexes["idx_claims_customer_date"]]


@pytest.mark.unit
def test_build_indexes_fails_when_a_job_fails():
    def respond(sql):
        if sql.startswith("CREATE INDEX"):
            return [("job-9",)]
        if sql.startswith("SELECT sys.wait_for_job"):
            return [(False,)]
        return [("failed", "Found duplicate key")]  # sys.jobs

    with pytest.raises(RuntimeError, match="job-9, failed: Found duplicate key"):
        build_indexes(FakeConn(respond), ["CREATE INDEX ASYNC i ON bank.products (customer_id)"])


@pytest.mark.unit
def test_build_indexes_keeps_waiting_while_the_job_runs():
    waits = iter([[(False,)], [(True,)]])  # first wait times out, second completes

    def respond(sql):
        if sql.startswith("CREATE INDEX"):
            return [("job-1",)]
        if sql.startswith("SELECT sys.wait_for_job"):
            return next(waits)
        return [("processing", None)]  # sys.jobs

    conn = FakeConn(respond)
    build_indexes(conn, ["CREATE INDEX ASYNC i ON bank.products (customer_id)"])
    assert sum(s.startswith("SELECT sys.wait_for_job") for s in conn.sql()) == 2


@pytest.mark.unit
def test_loader_cmd():
    assert loader_cmd("c.dsql.us-east-1.on.aws", "s3://t/staging/x/transactions.parquet",
                      "bank.transactions") == [
        "aurora-dsql-loader", "load", "--endpoint", "c.dsql.us-east-1.on.aws",
        "--source-uri", "s3://t/staging/x/transactions.parquet",
        "--schema", "bank", "--table", "transactions",
        "--on-conflict", "do-nothing", "--verify", "count",
    ]


@pytest.mark.unit
def test_load_all_fails_after_every_table_was_attempted():
    attempted = []

    def fake_run(cmd, check):
        table = cmd[cmd.index("--table") + 1]
        attempted.append(table)
        if table == "transactions":
            raise subprocess.CalledProcessError(2, cmd)

    uris = {"bank.digital_events": "s3://t/a", "bank.transactions": "s3://t/b", "pii.customers": "s3://t/c"}
    with pytest.raises(RuntimeError, match=r"bank\.transactions \(exit 2\)") as err:
        load_all("c.dsql.us-east-1.on.aws", uris, run=fake_run)
    assert sorted(attempted) == ["customers", "digital_events", "transactions"]
    assert "digital_events" not in str(err.value)


@pytest.mark.unit
def test_record_manifest_refuses_a_count_mismatch():
    conn = FakeConn(lambda sql: [(9,)])
    with pytest.raises(RuntimeError, match="9 rows in DSQL, 10 staged"):
        record_manifest(conn, [manifest_row(rows=10)])
    assert not any(s.startswith(("DELETE", "INSERT")) for s in conn.sql())


@pytest.mark.unit
def test_record_manifest_replaces_one_row_per_table():
    conn = FakeConn(lambda sql: [(10,)])
    record_manifest(conn, [manifest_row("bank.transactions"), manifest_row("bank.products")])
    writes = [(s.split()[0], p) for s, p in conn.executed if s.startswith(("DELETE", "INSERT"))]
    assert [w[0] for w in writes] == ["DELETE", "INSERT", "DELETE", "INSERT"]
    assert writes[1][1][0] == "bank.transactions" and writes[1][1][-1] == 10  # rows_loaded
    assert conn.transactions == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-project --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_dsql.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'data_load.dsql'`

- [ ] **Step 3: Write `data_load/dsql.py`**

```python
"""Everything that touches Aurora DSQL: schema, roles, grants, bulk load, indexes, lineage."""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import astuple, dataclass
from datetime import date, datetime

from data_load.ddl import SchemaPlan

LOADER = "aurora-dsql-loader"

INSERT_MANIFEST = (
    "INSERT INTO app.load_manifest (table_name, as_of, window_start, window_end, "
    "source_uri, source_files, source_etag_digest, staged_uri, staged_sha256, "
    "rows_staged, rows_loaded) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)


@dataclass(frozen=True)
class ManifestRow:
    table_name: str
    as_of: datetime
    window_start: date
    window_end: date
    source_uri: str
    source_files: int
    source_etag_digest: str
    staged_uri: str
    staged_sha256: str
    rows_staged: int


def connect(endpoint: str, profile: str | None = None):
    """Connect as admin; autocommit because DSQL allows one DDL per transaction."""
    import aurora_dsql_psycopg as dsql  # lazy: unit tests don't need the driver

    params = {"host": endpoint, "user": "admin"}
    if profile:
        params["profile"] = profile
    conn = dsql.connect(**params)
    conn.autocommit = True
    return conn


def schema_statements(plan: SchemaPlan) -> list[str]:
    """Step 3 DDL in order: bank/pii are recreated, app is created only if missing."""
    return [
        *plan.schemas,
        *(f"DROP VIEW IF EXISTS {view}" for view in plan.views),
        *(f"DROP TABLE IF EXISTS {table}" for table in plan.data_tables),
        *plan.data_tables.values(),
        *plan.views.values(),
        *plan.app_tables,
    ]


def apply_schema(conn, plan: SchemaPlan) -> None:
    with conn.cursor() as cur:
        for stmt in schema_statements(plan):
            cur.execute(stmt)
        cur.execute("SELECT rolname FROM pg_roles")
        existing_roles = {row[0] for row in cur.fetchall()}
        for role, stmt in plan.roles.items():
            if role not in existing_roles:
                cur.execute(stmt)
        for stmt in plan.grants:  # recreated tables lose their grants
            cur.execute(stmt)
        cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'app'")
        existing_indexes = {row[0] for row in cur.fetchall()}
    missing = [s for name, s in plan.app_indexes.items() if name not in existing_indexes]
    build_indexes(conn, missing)


def build_indexes(conn, statements: list[str]) -> None:
    """Submit every CREATE INDEX ASYNC, then wait for each job."""
    with conn.cursor() as cur:
        jobs = []
        for stmt in statements:
            cur.execute(stmt)
            jobs.append((cur.fetchone()[0], stmt))
        for job_id, stmt in jobs:
            _wait_for_job(cur, job_id, stmt)


def _wait_for_job(cur, job_id: str, stmt: str) -> None:
    """sys.wait_for_job returns false on failure *or* timeout; sys.jobs tells them apart."""
    while True:
        cur.execute("SELECT sys.wait_for_job(%s)", (job_id,))
        if cur.fetchone()[0]:
            return
        cur.execute("SELECT status, details FROM sys.jobs WHERE job_id = %s", (job_id,))
        rows = cur.fetchall()
        status, details = rows[0] if rows else ("missing", "job not found")
        if status == "completed":
            return
        if status not in ("submitted", "processing"):
            raise RuntimeError(f"index build failed (job {job_id}, {status}: {details}): {stmt}")


def loader_cmd(endpoint: str, uri: str, table: str) -> list[str]:
    schema, name = table.split(".")
    return [
        LOADER, "load", "--endpoint", endpoint, "--source-uri", uri,
        "--schema", schema, "--table", name,
        "--on-conflict", "do-nothing", "--verify", "count",
    ]


def load_all(endpoint: str, uris: dict[str, str], run=subprocess.run, parallel: int = 4) -> None:
    """Load every staged file; once all have finished, fail if any table failed."""

    def load_one(table: str) -> str | None:
        try:
            run(loader_cmd(endpoint, uris[table], table), check=True)
        except subprocess.CalledProcessError as e:
            return f"{table} (exit {e.returncode})"
        return None

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        failed = [f for f in pool.map(load_one, uris) if f]
    if failed:
        raise RuntimeError("aurora-dsql-loader failed for: " + ", ".join(failed))


def record_manifest(conn, rows: list[ManifestRow]) -> None:
    """Check every table's count first; record lineage only if all of them match."""
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(f"SELECT count(*) FROM {row.table_name}")
            loaded = cur.fetchone()[0]
            if loaded != row.rows_staged:
                raise RuntimeError(
                    f"{row.table_name}: {loaded:,} rows in DSQL, {row.rows_staged:,} staged"
                )
        for row in rows:
            with conn.transaction():
                cur.execute(
                    "DELETE FROM app.load_manifest WHERE table_name = %s AND as_of = %s",
                    (row.table_name, row.as_of),
                )
                cur.execute(INSERT_MANIFEST, (*astuple(row), row.rows_staged))


def recorded_digests(conn) -> dict[str, str]:
    """table -> source ETag digest, for the most recent as_of."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name, source_etag_digest FROM app.load_manifest "
            "WHERE as_of = (SELECT max(as_of) FROM app.load_manifest)"
        )
        return dict(cur.fetchall())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --no-project --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_dsql.py -v`
Expected: 8 passed.

- [ ] **Step 5: Lint and commit**

```bash
uv run --no-project --with ruff ruff check --fix data_load tests/unit/test_data_load_dsql.py
uv run --no-project --with ruff ruff format data_load tests/unit/test_data_load_dsql.py
git add data_load/dsql.py tests/unit/test_data_load_dsql.py
git commit -m "feat(data-load): DSQL schema, grants, parallel loader, async indexes and manifest"
```

---

### Task 5: Command line (`stage`, `run`, `check`) and the local rehearsal

**Files:**
- Create: `data_load/__main__.py`
- Test: `tests/unit/test_data_load_cli.py`

**Interfaces:**
- Consumes:
  - `data_load.stage.stage`, `load_window`
  - `data_load.ddl.load_plan`
  - `data_load.source.fingerprint`, `source_prefix`, `drift`
  - `data_load.dsql.connect`, `apply_schema`, `load_all`, `build_indexes`, `record_manifest`, `recorded_digests`, `ManifestRow`
- Produces:
  - `main(argv: list[str] | None = None) -> int`
  - `parse_hackathon_secret(raw: str) -> dict`
  - `RUN_ENV = ("AS_OF", "WINDOW_YEARS", "DSQL_ENDPOINT", "TEAM_BUCKET", "HACKATHON_S3")` (the environment CodeBuild provides in Task 6)
  - Log line `data_load: done, <N> rows in <M> tables` on success

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_data_load_cli.py`:

```python
"""python -m data_load: argument handling and secret hygiene."""

import json

import pytest
from data_load_fixtures import tx, write_transactions

from data_load.__main__ import RUN_ENV, main, parse_hackathon_secret


@pytest.mark.unit
def test_stage_command_writes_parquet(tmp_path, capsys):
    write_transactions(tmp_path / "src", [
        tx("T1", "2026-06-17 10:00:00", "2026-06-17"),
        tx("T2", "2026-06-18 03:00:00", "2026-06-17"),
    ])
    code = main([
        "stage", "--source", (tmp_path / "src").as_posix(), "--out", str(tmp_path / "out"),
        "--as-of", "2026-06-17T23:59:59", "--window-years", "2", "--tables", "bank.transactions",
    ])
    assert code == 0
    assert (tmp_path / "out" / "transactions.parquet").exists()
    assert "total 2 rows in 1 tables" in capsys.readouterr().out


@pytest.mark.unit
def test_run_lists_missing_environment(monkeypatch):
    for name in RUN_ENV:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit, match="AS_OF, WINDOW_YEARS, DSQL_ENDPOINT, TEAM_BUCKET, HACKATHON_S3"):
        main(["run"])


@pytest.mark.unit
def test_secret_errors_name_keys_never_values():
    partial = json.dumps({
        "aws_access_key_id": "fake-key-id", "aws_secret_access_key": "fake-secret-value",
        "region": "us-east-2", "prefix": "data/",
    })
    with pytest.raises(SystemExit) as err:
        parse_hackathon_secret(partial)
    assert str(err.value) == "HACKATHON_S3 is missing: bucket"
    with pytest.raises(SystemExit) as err:
        parse_hackathon_secret('{"aws_secret_access_key": "fake-secret-value"')  # truncated JSON
    assert "fake-secret-value" not in str(err.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --no-project --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'data_load.__main__'`

- [ ] **Step 3: Write `data_load/__main__.py`**

```python
"""python -m data_load {stage,run,check}.

Design: docs/superpowers/specs/2026-09-29-data-loading-design.md
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

from data_load.ddl import load_plan
from data_load.stage import load_window, stage

CONFIG = Path(__file__).resolve().parents[1] / "infra-cdk" / "config.yaml"
SECRET_KEYS = ("aws_access_key_id", "aws_secret_access_key", "bucket", "region", "prefix")
RUN_ENV = ("AS_OF", "WINDOW_YEARS", "DSQL_ENDPOINT", "TEAM_BUCKET", "HACKATHON_S3")


def config_defaults() -> dict:
    """The `data:` block of infra-cdk/config.yaml, when running from a repo checkout."""
    if not CONFIG.exists():
        return {}
    return (yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}).get("data") or {}


def parse_hackathon_secret(raw: str) -> dict:
    """Parse HACKATHON_S3. Errors name missing keys and never echo values."""
    try:
        secret = json.loads(raw)
    except json.JSONDecodeError:
        raise SystemExit("HACKATHON_S3 is not valid JSON") from None
    if not isinstance(secret, dict):
        raise SystemExit("HACKATHON_S3 must be a JSON object")
    missing = [key for key in SECRET_KEYS if not secret.get(key)]
    if missing:
        raise SystemExit(f"HACKATHON_S3 is missing: {', '.join(missing)}")
    return secret


def cmd_stage(args) -> int:
    if args.as_of is None or args.window_years is None:
        raise SystemExit("--as-of and --window-years are required (no data block in config.yaml)")
    tables = args.tables.split(",") if args.tables else None
    staged = stage(args.source, Path(args.out), args.as_of, args.window_years, tables=tables)
    print(f"total {sum(s.rows for s in staged):,} rows in {len(staged)} tables")
    return 0


def cmd_run(args) -> int:
    missing = [name for name in RUN_ENV if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"missing environment variables: {', '.join(missing)}")
    import boto3

    from data_load import dsql, source

    secret = parse_hackathon_secret(os.environ["HACKATHON_S3"])
    as_of = datetime.fromisoformat(os.environ["AS_OF"])
    years = int(os.environ["WINDOW_YEARS"])
    endpoint, team_bucket = os.environ["DSQL_ENDPOINT"], os.environ["TEAM_BUCKET"]
    plan = load_plan()

    # 1. Stage from the hackathon bucket; nothing in AWS is written yet
    origin = f"s3://{secret['bucket']}/{secret['prefix']}"
    staged = stage(origin, Path(args.out), as_of, years, s3=secret, plan=plan)
    org_s3 = boto3.client(
        "s3",
        region_name=secret["region"],
        aws_access_key_id=secret["aws_access_key_id"],
        aws_secret_access_key=secret["aws_secret_access_key"],
    )
    prints = source.fingerprint(org_s3, secret["bucket"], secret["prefix"], [s.table for s in staged])

    # 2. Upload, largest first so the longest load starts first
    team_s3 = boto3.client("s3")
    key_base = f"staging/{as_of:%Y%m%dT%H%M%S}"
    uris = {}
    for s in sorted(staged, key=lambda s: s.rows, reverse=True):
        key = f"{key_base}/{s.path.name}"
        team_s3.upload_file(str(s.path), team_bucket, key)
        team_s3.put_object(Bucket=team_bucket, Key=f"{key}.sha256", Body=s.sha256.encode())
        uris[s.table] = f"s3://{team_bucket}/{key}"

    # 3. Schema, roles, grants. A DSQL connection lives at most 60 min: reconnect after the load.
    conn = dsql.connect(endpoint)
    try:
        dsql.apply_schema(conn, plan)
    finally:
        conn.close()

    # 4. Bulk load
    dsql.load_all(endpoint, uris)

    # 5-6. Indexes, then verify counts and record lineage
    start, end = load_window(as_of, years)
    rows = [
        dsql.ManifestRow(
            table_name=s.table,
            as_of=as_of,
            window_start=start,
            window_end=end,
            source_uri=f"s3://{secret['bucket']}/{source.source_prefix(secret['prefix'], s.table)}",
            source_files=prints[s.table][0],
            source_etag_digest=prints[s.table][1],
            staged_uri=uris[s.table],
            staged_sha256=s.sha256,
            rows_staged=s.rows,
        )
        for s in staged
    ]
    conn = dsql.connect(endpoint)
    try:
        dsql.build_indexes(conn, plan.data_indexes)
        dsql.record_manifest(conn, rows)
    finally:
        conn.close()
    print(f"data_load: done, {sum(s.rows for s in staged):,} rows in {len(staged)} tables", flush=True)
    return 0


def cmd_check(args) -> int:
    import boto3

    from data_load import dsql, source

    conn = dsql.connect(args.endpoint, profile=args.dsql_profile)
    try:
        recorded = dsql.recorded_digests(conn)
    finally:
        conn.close()
    if not recorded:
        print("no load recorded in app.load_manifest")
        return 1
    org_s3 = boto3.Session(profile_name=args.bucket_profile).client("s3", region_name=args.region)
    prints = source.fingerprint(org_s3, args.bucket, args.prefix, list(recorded))
    changed = source.drift(recorded, {t: digest for t, (_, digest) in prints.items()})
    if changed:
        print("changed since the last load: " + ", ".join(changed))
        return 1
    print("no drift: the bucket matches the last load")
    return 0


def main(argv: list[str] | None = None) -> int:
    defaults = config_defaults()
    parser = argparse.ArgumentParser(prog="python -m data_load")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("stage", help="validate CSVs and write Parquet locally (no AWS writes)")
    p.add_argument("--source", required=True, help="directory or s3:// URI in the organizer data/ layout")
    p.add_argument("--out", required=True)
    p.add_argument("--as-of", type=datetime.fromisoformat, default=defaults.get("as_of"))
    p.add_argument("--window-years", type=int, default=defaults.get("window_years"))
    p.add_argument("--tables", help="comma-separated subset, e.g. bank.transactions")
    p.set_defaults(func=cmd_stage)

    p = sub.add_parser("run", help="stage from the hackathon bucket and load Aurora DSQL (CodeBuild)")
    p.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "ledgerlens-stage"))
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("check", help="compare the bucket's ETags with app.load_manifest")
    p.add_argument("--bucket", required=True)
    p.add_argument("--endpoint", required=True, help="stack output DsqlEndpoint")
    p.add_argument("--prefix", default="data/")
    p.add_argument("--region", default="us-east-2")
    p.add_argument("--bucket-profile", default="hackathon")
    p.add_argument("--dsql-profile", default="ledgerlens")
    p.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run all data_load tests**

Run: `uv run --no-project --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_ddl.py tests/unit/test_data_load_stage.py tests/unit/test_data_load_source.py tests/unit/test_data_load_dsql.py tests/unit/test_data_load_cli.py -v`
Expected: 30 passed (1 may be skipped offline).

- [ ] **Step 5: Local rehearsal on the full local copy (about 5 minutes, no AWS)**

Run:

```bash
uv run --no-project --with-requirements data_load/requirements.txt python -m data_load stage \
  --source datathon/data --out "$TEMP/ledgerlens-stage" --as-of 2026-06-17T23:59:59 --window-years 2
```

Expected:
- 13 `staged …` lines whose counts equal the Global Constraints table;
- the last line is `total 15,745,982 rows in 13 tables`.

If a table fails, the error names it and its constraint. Fix `schema.sql` only if the data contradicts the DDL, as `duration_seconds` did, and never by changing values. Then delete `"$TEMP/ledgerlens-stage"`.

- [ ] **Step 6: Lint and commit**

```bash
uv run --no-project --with ruff ruff check --fix data_load tests/unit/test_data_load_cli.py
uv run --no-project --with ruff ruff format data_load tests/unit/test_data_load_cli.py
git add data_load/__main__.py tests/unit/test_data_load_cli.py
git commit -m "feat(data-load): add stage/run/check commands; full local rehearsal stages 15,745,982 rows"
```

---

### Task 6: CDK: DSQL cluster, staging bucket, secret, CodeBuild job, config and Makefile

**Files:**
- Create: `infra-cdk/lib/data-construct.ts`
- Modify: `infra-cdk/lib/utils/config-manager.ts` (the `AppConfig` interface, the validation in `_loadConfig`, and the returned object)
- Modify: `infra-cdk/lib/fast-main-stack.ts` (construct and outputs)
- Modify: `infra-cdk/config.yaml` (append a `data:` block)
- Modify: `Makefile` (a `load-data` target)
- Test: `infra-cdk/test/data-construct.test.ts`

**Interfaces:**
- Consumes: `data_load/` (packaged as a CodeBuild source asset) and `RUN_ENV` from Task 5.
- Produces:
  - `DataConstruct` with public `clusterEndpoint: string`, `clusterArn: string` and `loadProjectName: string`
  - `AppConfig.data: { as_of: string; window_years: number }`
  - Stack outputs `DsqlEndpoint` and `DataLoadProject`
  - CodeBuild project `ledgerlens-data-load`, log group `/aws/codebuild/ledgerlens-data-load`
  - Secret `ledgerlens/hackathon-s3`

- [ ] **Step 1: Write the failing jest test**

`infra-cdk/test/data-construct.test.ts`:

```ts
import * as cdk from "aws-cdk-lib"
import { Match, Template } from "aws-cdk-lib/assertions"
import { DataConstruct } from "../lib/data-construct"
import { AppConfig } from "../lib/utils/config-manager"

const config = {
  stack_name_base: "ledgerlens-test",
  data: { as_of: "2026-06-17T23:59:59", window_years: 2 },
} as unknown as AppConfig

test("DSQL cluster, secret and data-load job", () => {
  const app = new cdk.App()
  const stack = new cdk.Stack(app, "T", { env: { account: "111111111111", region: "us-east-1" } })
  new DataConstruct(stack, "Data", { config })
  const t = Template.fromStack(stack)

  t.hasResourceProperties("AWS::DSQL::Cluster", { DeletionProtectionEnabled: true })
  t.hasResourceProperties("AWS::SecretsManager::Secret", { Name: "ledgerlens/hackathon-s3" })
  t.hasResourceProperties("AWS::CodeBuild::Project", {
    Name: "ledgerlens-data-load",
    TimeoutInMinutes: 180,
    Environment: Match.objectLike({
      Type: "ARM_CONTAINER",
      ComputeType: "BUILD_GENERAL1_LARGE",
      // arrayWith is order-sensitive: same order as environmentVariables in data-construct.ts
      EnvironmentVariables: Match.arrayWith([
        { Name: "AS_OF", Type: "PLAINTEXT", Value: "2026-06-17T23:59:59" },
        { Name: "WINDOW_YEARS", Type: "PLAINTEXT", Value: "2" },
        Match.objectLike({ Name: "DSQL_ENDPOINT" }),
        Match.objectLike({ Name: "TEAM_BUCKET" }),
        Match.objectLike({ Name: "HACKATHON_S3", Type: "SECRETS_MANAGER" }),
      ]),
    }),
  })
  t.hasResourceProperties("AWS::IAM::Policy", {
    PolicyDocument: {
      Statement: Match.arrayWith([Match.objectLike({ Action: "dsql:DbConnectAdmin" })]),
    },
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd infra-cdk && npx jest test/data-construct.test.ts`
Expected: FAIL with `Cannot find module '../lib/data-construct'`

- [ ] **Step 3: Add the `data` config**

In `infra-cdk/lib/utils/config-manager.ts`:

(a) Add this interface after `McpRegistryConfig`:

```ts
/** Organizer snapshot load (docs/superpowers/specs/2026-09-29-data-loading-design.md). */
export interface DataConfig {
  /** Bank "today" for the load and every tool: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS, no time zone. */
  as_of: string
  /** Event tables keep process_date in [as_of::date - (365 * window_years - 1), as_of::date]. */
  window_years: number
}
```

(b) Add `data: DataConfig` as the last field of `AppConfig`, after the closing brace of `backend: {…}`.

(c) In `_loadConfig`, just before `return {`, add:

```ts
      // Validate the data-load snapshot settings
      const asOf = String(parsedConfig.data?.as_of ?? "2026-06-17T23:59:59")
      if (!/^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})?$/.test(asOf)) {
        throw new Error(
          `data.as_of '${asOf}' in ${configPath} must be YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.`
        )
      }
      const windowYears = parsedConfig.data?.window_years ?? 2
      if (!Number.isInteger(windowYears) || windowYears < 1) {
        throw new Error(`data.window_years in ${configPath} must be a positive integer.`)
      }
```

(d) In the returned object, add after the `backend: {…},` entry:

```ts
        data: { as_of: asOf, window_years: windowYears },
```

Append to `infra-cdk/config.yaml`:

```yaml

# Organizer snapshot load (docs/superpowers/specs/2026-09-29-data-loading-design.md).
# Change, then deploy and run `make load-data`. Reloads recreate bank/pii: never during a demo.
data:
  as_of: "2026-06-17T23:59:59"   # bank "today" for the load and for every tool
  window_years: 2                # event tables: process_date in [as_of::date - (365 * window_years - 1), as_of::date]
```

- [ ] **Step 4: Write `infra-cdk/lib/data-construct.ts`**

```ts
import * as path from "path"
import * as cdk from "aws-cdk-lib"
import * as codebuild from "aws-cdk-lib/aws-codebuild"
import * as dsql from "aws-cdk-lib/aws-dsql"
import * as iam from "aws-cdk-lib/aws-iam"
import * as s3 from "aws-cdk-lib/aws-s3"
import * as s3assets from "aws-cdk-lib/aws-s3-assets"
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager"
import { Construct } from "constructs"
import { AppConfig } from "./utils/config-manager"

// Pinned aurora-dsql-loader release; the hash is GitHub's published asset digest
const LOADER_URL =
  "https://github.com/aws-samples/aurora-dsql-loader/releases/download/v3.3.0/aurora-dsql-loader-aarch64-unknown-linux-musl.tar.gz"
const LOADER_SHA256 = "eb7a559f13aa3603704aae0e3e27b4f5e2bd3904ae9e656161df60170ce3dff5"

export interface DataConstructProps {
  config: AppConfig
}

/**
 * Aurora DSQL plus the CodeBuild job that loads the organizer snapshot into it
 * (docs/superpowers/specs/2026-09-29-data-loading-design.md).
 */
export class DataConstruct extends Construct {
  public readonly clusterEndpoint: string
  public readonly clusterArn: string
  public readonly loadProjectName: string

  constructor(scope: Construct, id: string, props: DataConstructProps) {
    super(scope, id)

    const cluster = new dsql.CfnCluster(this, "Cluster", {
      deletionProtectionEnabled: true,
      tags: [{ key: "Name", value: `${props.config.stack_name_base}-dsql` }],
    })
    cluster.applyRemovalPolicy(cdk.RemovalPolicy.RETAIN)
    this.clusterEndpoint = cluster.attrEndpoint
    this.clusterArn = cluster.attrResourceArn

    const stagingBucket = new s3.Bucket(this, "StagingBucket", {
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    })

    // Created with a generated placeholder; a teammate sets the real JSON once (spec section 4.1)
    const hackathonSecret = new secretsmanager.Secret(this, "HackathonS3", {
      secretName: "ledgerlens/hackathon-s3",
      description: "Organizer S3 read keys for the datathon bucket (JSON). Set manually; never commit.",
    })

    const source = new s3assets.Asset(this, "DataLoadSource", {
      path: path.join(__dirname, "..", "..", "data_load"),
      exclude: ["__pycache__", "*.pyc"],
    })

    const project = new codebuild.Project(this, "DataLoad", {
      projectName: "ledgerlens-data-load",
      description: "Loads the organizer snapshot into Aurora DSQL (python -m data_load run)",
      source: codebuild.Source.s3({ bucket: source.bucket, path: source.s3ObjectKey }),
      environment: {
        buildImage: codebuild.LinuxArmBuildImage.AMAZON_LINUX_2_STANDARD_3_0,
        computeType: codebuild.ComputeType.LARGE,
      },
      timeout: cdk.Duration.minutes(180),
      environmentVariables: {
        AS_OF: { value: props.config.data.as_of },
        WINDOW_YEARS: { value: String(props.config.data.window_years) },
        DSQL_ENDPOINT: { value: cluster.attrEndpoint },
        TEAM_BUCKET: { value: stagingBucket.bucketName },
        HACKATHON_S3: {
          type: codebuild.BuildEnvironmentVariableType.SECRETS_MANAGER,
          value: hackathonSecret.secretArn,
        },
      },
      buildSpec: codebuild.BuildSpec.fromObject({
        version: "0.2",
        phases: {
          install: {
            "runtime-versions": { python: "3.12" },
            commands: [
              "pip install --quiet -r requirements.txt",
              `curl --proto '=https' --tlsv1.2 -sSfL -o /tmp/loader.tar.gz ${LOADER_URL}`,
              `echo "${LOADER_SHA256}  /tmp/loader.tar.gz" | sha256sum -c -`,
              "tar -xzf /tmp/loader.tar.gz -C /usr/local/bin aurora-dsql-loader",
              "aurora-dsql-loader load --help",
            ],
          },
          build: {
            commands: [
              // The asset unpacks data_load's contents at the source root; python -m needs the package dir
              "mkdir -p /tmp/src/data_load && cp -r . /tmp/src/data_load/ && cd /tmp/src && python -m data_load run",
            ],
          },
        },
      }),
    })

    stagingBucket.grantReadWrite(project)
    hackathonSecret.grantRead(project)
    project.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["dsql:DbConnectAdmin"],
        resources: [cluster.attrResourceArn],
      })
    )
    this.loadProjectName = project.projectName
  }
}
```

- [ ] **Step 5: Wire it into the main stack**

In `infra-cdk/lib/fast-main-stack.ts`:
- add `import { DataConstruct } from "./data-construct"` after the `CognitoConstruct` import;
- add `public readonly data: DataConstruct` after `public readonly cognito: CognitoConstruct`;
- after the `this.backend = new BackendConstruct(…)` block, add:

```ts
    // Step 3: Aurora DSQL and the job that loads the organizer snapshot into it
    this.data = new DataConstruct(this, `${id}-data`, { config: props.config })
```

Then add these after the `FeedbackApiUrl` output:

```ts
    new cdk.CfnOutput(this, "DsqlEndpoint", {
      value: this.data.clusterEndpoint,
      description: "Aurora DSQL cluster endpoint",
      exportName: `${props.config.stack_name_base}-DsqlEndpoint`,
    })

    new cdk.CfnOutput(this, "DataLoadProject", {
      value: this.data.loadProjectName,
      description: "CodeBuild project that loads the organizer snapshot (make load-data)",
    })
```

- [ ] **Step 6: Add the Makefile target**

Append to `Makefile`. Recipe lines must start with a TAB:

```make

# Load the organizer snapshot into Aurora DSQL with the CodeBuild job from
# infra-cdk/lib/data-construct.ts. Run as: AWS_PROFILE=ledgerlens make load-data
# The log tail keeps following; press Ctrl-C after "data_load: done".
load-data:
	aws codebuild start-build --project-name ledgerlens-data-load --query build.id --output text
	aws logs tail /aws/codebuild/ledgerlens-data-load --follow --since 1m
```

- [ ] **Step 7: Compile and run the test**

Run: `cd infra-cdk && npx tsc --noEmit && npx jest test/data-construct.test.ts`
Expected: no TypeScript errors; 1 passed.

- [ ] **Step 8: Commit only your hunks**

`infra-cdk/config.yaml` already has an uncommitted `admin_user_email` change from `feat/design`, so stage it interactively and accept only the `data:` block:

```bash
git add infra-cdk/lib/data-construct.ts infra-cdk/test/data-construct.test.ts infra-cdk/lib/utils/config-manager.ts infra-cdk/lib/fast-main-stack.ts Makefile
git add -p infra-cdk/config.yaml
git diff --cached --stat
git commit -m "feat(infra): add Aurora DSQL cluster and CodeBuild data-load job"
```

Expected `--stat`: the 5 files above plus `infra-cdk/config.yaml`, with only the `data:` hunk staged.

---

### Task 7: First cloud run and first-run checks (needs the human for the secret)

**Files:**
- Modify: `docs/superpowers/specs/2026-09-29-data-loading-design.md` (§10 measured numbers, §13 outcomes)

**Interfaces:**
- Consumes: everything above; the stack outputs `DsqlEndpoint` and `DataLoadProject`.
- Produces: a loaded cluster; `app.load_manifest` with 13 rows; the measured duration and cost.

- [ ] **Step 1: Confirm what will be deployed**

Run: `git status --short`. `scripts/deploy-with-codebuild.py` packages git-tracked files from the working tree, and the working tree still holds uncommitted `feat/design` edits (`backend-construct.ts`, the cedar Lambda, `config.yaml`). **Ask the user whether to deploy with those edits** before continuing.

- [ ] **Step 2: Deploy**

Run: `AWS_PROFILE=ledgerlens python scripts/deploy-with-codebuild.py`
Expected: the stack deploys and prints its outputs, including `DsqlEndpoint` (`<id>.dsql.us-east-1.on.aws`) and `DataLoadProject = ledgerlens-data-load`.

- [ ] **Step 3 (HUMAN ONLY): Set the organizer secret**

An agent must not do this step, read the organizer PDF, or see the keys. The human creates a local file `hackathon-s3.json` outside the repo:

```json
{"aws_access_key_id": "<from organizer>", "aws_secret_access_key": "<from organizer>",
 "bucket": "<datathon bucket name>", "region": "us-east-2", "prefix": "data/"}
```

Then:

```bash
aws secretsmanager put-secret-value --secret-id ledgerlens/hackathon-s3 --secret-string file://hackathon-s3.json --profile ledgerlens
rm hackathon-s3.json
```

- [ ] **Step 4: Run the load**

Run: `AWS_PROFILE=ledgerlens make load-data`

Expected in the log, in order:
- the `aurora-dsql-loader load --help` output, which must list `--schema`, `--on-conflict` and `--verify` (spec §13.1 and §13.2);
- 13 `staged …` lines with the Global Constraints counts;
- the loader's progress and a `Match` verdict per table;
- `data_load: done, 15,745,982 rows in 13 tables`.

Note the build's total minutes from the CodeBuild console. If a step fails, fix the cause and re-run `make load-data`. The job is safe to repeat.

Known risk: `record_manifest` runs `SELECT count(*)` on `bank.digital_events` (10.3M rows). If that hits DSQL's 5-minute transaction limit, record it in spec §13. Then make `record_manifest` take `rows_loaded` from the loader's `--verify count` verdict for that table, with a unit test.

- [ ] **Step 5: Verify the manifest and the PII views (spec §13.3)**

Run, with `<DsqlEndpoint>` from Step 2:

```bash
uv run --no-project --with-requirements data_load/requirements.txt python - <<'EOF'
import aurora_dsql_psycopg as dsql
conn = dsql.connect(host="<DsqlEndpoint>", user="admin", profile="ledgerlens")
conn.autocommit = True
cur = conn.cursor()
cur.execute("SELECT table_name, rows_staged, rows_loaded FROM app.load_manifest ORDER BY 1")
rows = cur.fetchall()
for r in rows:
    print(r)
print("tables", len(rows), "total", sum(r[2] for r in rows))
for sql in ("SET ROLE ll_read", "SELECT count(*) FROM bank.customer_profile",
            "SELECT count(*) FROM pii.customers", "RESET ROLE"):
    try:
        cur.execute(sql)
        print(sql, "->", cur.fetchone() if cur.description else "ok")
    except Exception as e:
        print(sql, "->", type(e).__name__, str(e).splitlines()[0])
EOF
```

Expected:
- 13 manifest rows with `rows_staged == rows_loaded`, and `total 15745982`;
- `bank.customer_profile` → `(150000,)`;
- `pii.customers` → a permission-denied error.

If `SET ROLE` is unsupported, record "Q7 deferred to the tools step". If the view is denied for `ll_read`, record that the Q7 fallback (a `bank.customer_profile` table filled by the job) is needed.

- [ ] **Step 6: Check for drift**

Run: `uv run --no-project --with-requirements data_load/requirements.txt python -m data_load check --bucket <datathon bucket name> --endpoint <DsqlEndpoint>`
Expected: `no drift: the bucket matches the last load`, exit code 0.

- [ ] **Step 7: Record the outcomes in the spec and commit**

In `docs/superpowers/specs/2026-09-29-data-loading-design.md`:
- **§10:** replace the Stage, Load and CodeBuild estimates with the measured minutes and cost.
- **§13:** add the outcome to each item, e.g. `→ confirmed 2026-10-01` or `→ fallback needed: …`.

```bash
git add docs/superpowers/specs/2026-09-29-data-loading-design.md
git commit -m "docs(spec): record first data-load run measurements and first-run checks"
```

---

### Task 8: Bring the design doc, ERD and README in line with the spec

**Files:**
- Modify: `docs/LEDGERLENS_PRODUCT_DESIGN.md` (§6.2, §7.8, §7.10, §8.1, §8.2, §8.4, §8.5, §19 Q7/Q8, Appendix A)
- Modify: `docs/LATAM_Bank_ERD.md` (the app schema)
- Modify: `README.md` (a data-load section)

**Interfaces:**
- Consumes: the Task 7 outcomes (Q7/Q8).
- Produces: documentation only.

- [ ] **Step 1: Guard against committing someone else's work**

Run: `git diff --stat -- docs/LEDGERLENS_PRODUCT_DESIGN.md docs/LATAM_Bank_ERD.md`

If either file shows changes you did not make (the design v3 edits from `feat/design` are uncommitted), **stop and ask the user** where those edits should be committed first. Continue only once `git diff` on these two files is empty.

- [ ] **Step 2: Design doc §6.2.** Replace the bullet that begins "`as_of` comes from `infra-cdk/config.yaml`" with:

```markdown
- `as_of` comes from `infra-cdk/config.yaml` (`data.as_of`, default `2026-06-17T23:59:59`, the dataset's last business day). It is passed to every tool Lambda as `LEDGERLENS_AS_OF` and is the same value the load used (section 8). Event reads filter `process_date <= as_of::date`: the business day ends at 06:00, so filtering `transaction_date` would hide 1,352 loaded transactions. "Last N days" means `process_date > as_of::date - N`. Dates that follow the bank clock (`business_date`, dispute deadlines) use `as_of`; approval expiry and every `created_at` use `now()`.
```

- [ ] **Step 3: Design doc §7.8.** Replace the SQL block with:

```sql
BEGIN;
-- 1) Use up the approval: exactly 1 row, or ROLLBACK and return DENIED
UPDATE app.approvals SET status = 'used', used_at = now()
WHERE approval_id = %(approval_id)s AND customer_id = %(customer_id)s AND action = 'block_card'
  AND target_ids = %(card_id)s AND status = 'approved' AND expires_at > now();
-- 2) Block the card: it must be this customer's active card; a repeat block is a no-op (card_id is the key)
INSERT INTO app.card_blocks (card_id, customer_id, approval_id, business_date)
SELECT product_id, customer_id, %(approval_id)s, %(as_of)s::date FROM bank.products
WHERE product_id = %(card_id)s AND customer_id = %(customer_id)s
  AND product_type IN ('Tarjeta Crédito', 'Tarjeta Débito') AND product_status = 'Active'
ON CONFLICT (card_id) DO NOTHING;
-- 3) Audit row in the same transaction
INSERT INTO app.audit_log (actor_sub, customer_id, session_id, tool, approval_id, input, result, outcome)
VALUES (%(sub)s, %(customer_id)s, %(session_id)s, 'block_card', %(approval_id)s, %(input)s, %(result)s, 'blocked');
COMMIT;
-- Read-back, after the commit: organizer status overridden by an active block
SELECT CASE WHEN b.card_id IS NOT NULL THEN 'Blocked' ELSE p.product_status END AS product_status
FROM bank.products p LEFT JOIN app.card_blocks b ON b.card_id = p.product_id
WHERE p.product_id = %(card_id)s AND p.customer_id = %(customer_id)s;
```

In the bullets below it, change "the card is blocked" to "the block row exists". Change "The v2 split (approval in DynamoDB, card in Aurora)" to "The v2 split (approval in DynamoDB, card in Aurora); `bank` stays read-only (organizer data)".

- [ ] **Step 4: Design doc §7.10.** Replace the SQL block with:

```sql
WITH t AS (
  SELECT t.* FROM bank.transactions t
  JOIN bank.products p ON p.product_id = t.product_id AND p.customer_id = %(customer_id)s
  WHERE t.customer_id = %(customer_id)s
    AND t.transaction_id = ANY (%(transaction_ids)s)
    AND t.process_date <= %(as_of)s::date
)
INSERT INTO app.claims (claim_id, customer_id, approval_id, claim_type, transaction_ids, claimed_amount,
                        currency, customer_statement, business_date, deadline_date, rule_ids)
SELECT %(new_claim_id)s, %(customer_id)s, %(approval_id)s, %(claim_type)s, %(transaction_ids_json)s::jsonb,
       SUM(t.amount), MIN(t.currency), %(customer_statement)s, %(as_of)s::date, %(deadline_date)s,
       %(rule_ids_json)s::jsonb
FROM t
HAVING COUNT(*) = cardinality(%(transaction_ids)s)   -- every ID belongs to this customer
   AND COUNT(DISTINCT t.currency) = 1
RETURNING claim_id, claimed_amount, currency;
```

Replace the "Contracts" bullet with:

```markdown
- **Contracts:** claims live in `app.claims`; `bank.complaints` stays organizer-only. `deadline_date` comes from `get_dispute_policy` counted from `as_of::date`. `RECENT_CASE` reads `app.claims` and `app.cases`.
```

- [ ] **Step 5: Design doc §8.1 and §8.2.**
- In the §8.1 YAML block, set `as_of: "2026-06-17T23:59:59"`. Keep the comments.
- Replace everything from the `### 8.2 Pipeline` heading up to, but not including, `### 8.3` with:

```markdown
### 8.2 Load job

One CodeBuild job (`make load-data`) loads the snapshot once, at the fixed `as_of`. The organizer bucket was verified static (one upload on 2026-09-01), so there is no append and no moving clock. Full design, facts and failure handling: [`docs/superpowers/specs/2026-09-29-data-loading-design.md`](superpowers/specs/2026-09-29-data-loading-design.md). In short:

1. DuckDB reads the raw CSVs from the hackathon bucket into tables built from `data_load/schema.sql`, so types, `NOT NULL`, `CHECK` and primary keys are enforced before anything reaches AWS. Values are never changed; a duplicate key fails the run.
2. Checksummed Parquet goes to the team staging bucket.
3. `bank`/`pii` are dropped and recreated; `app` is created once and never dropped. Roles are created if missing; grants are re-applied.
4. `aurora-dsql-loader` loads every table (`--verify count`), then 3 indexes are built with `CREATE INDEX ASYNC`.
5. Every table's count must equal its Parquet rows; `app.load_manifest` records the source ETag digest, the Parquet SHA-256 and the counts. `python -m data_load check` reports whether the bucket changed since.
```

- [ ] **Step 6: Design doc §8.4 and §8.5.**
- In §8.4, change "**Four secondary indexes,**" to "**Five secondary indexes,**" and add `  - \`app.claims (customer_id, business_date)\`` after the `app.cases` line.
- Replace the §8.5 table with:

```markdown
| Database role | Used by | Grants |
|---|---|---|
| `admin` | The load job only (IAM `dsql:DbConnectAdmin`): DDL and bulk load | All |
| `ll_read` | Read tools (1–6, 8, 10) | `SELECT` on `bank.products`, `bank.transactions`, `bank.complaints`, `bank.customer_profile`, `bank.agent_roster`, `app.approvals`, `app.cases`, `app.card_blocks`, `app.claims` |
| `ll_write` | Write tools (7, 9, 11, 12) | The same `SELECT`s, plus `INSERT, UPDATE` on `app.approvals`, `app.claims`; `INSERT` on `app.card_blocks`, `app.cases`, `app.audit_log`. Nothing on `bank`/`pii` beyond `SELECT` |
| `ll_approvals` | Approvals API | `SELECT, UPDATE` on `app.approvals` |
| `ll_feedback` | Feedback API | `INSERT` on `app.feedback` |
```

- [ ] **Step 7: Design doc §19 and Appendix A.**
- Append the Task 7 outcome to the Q7 and Q8 rows, e.g. "→ confirmed 2026-10-01: …".
- Replace everything from `## Appendix A.` to the end of the file with:

```markdown
## Appendix A. Aurora DSQL schema

The schema lives in [`data_load/schema.sql`](../data_load/schema.sql). It is the single source of truth: every load runs its `bank`/`pii` table definitions in DuckDB to validate the data, then in DSQL. Grants and roles are in the same file.
```

- [ ] **Step 8: ERD (`docs/LATAM_Bank_ERD.md`).**
- **Header bullet:** list `app` as `APPROVALS`, `CASES`, `AUDIT_LOG`, `FEEDBACK`, `LOAD_MANIFEST`, `CARD_BLOCKS`, `CLAIMS`.
- **DDL link:** point it to `../data_load/schema.sql`.
- **Relationships:** replace `COMPLAINTS |o--o{ CASES : "claim (complaint_id)"` with:

```text
    CUSTOMERS ||--o{ CARD_BLOCKS : "blocks (agent)"
    PRODUCTS ||--o| CARD_BLOCKS : "blocked card"
    CUSTOMERS ||--o{ CLAIMS : "files (agent)"
    CLAIMS |o--o{ CASES : "handed off (claim_id)"
```

- **`CASES` entity:** change `varchar complaint_id FK` to `varchar claim_id FK`.
- **`LOAD_MANIFEST` entity:** replace its body with the columns of `app.load_manifest` in `schema.sql`.
- **New entities**, after `LOAD_MANIFEST`:

```text
    CARD_BLOCKS {
        varchar card_id PK "= products.product_id"
        varchar customer_id FK
        uuid approval_id FK
        date business_date "as_of::date"
        timestamptz created_at
    }

    CLAIMS {
        varchar claim_id PK
        varchar customer_id FK
        uuid approval_id FK
        varchar claim_type "fraud, dispute"
        jsonb transaction_ids
        decimal claimed_amount
        varchar currency
        varchar customer_statement
        date business_date "as_of::date"
        date deadline_date
        jsonb rule_ids
        varchar status "open, handed_off, closed"
        timestamptz created_at
    }
```

- [ ] **Step 9: README.** Append:

```markdown

## Data load (LedgerLens)

The organizer snapshot is loaded once into Aurora DSQL at a fixed business date (`data.as_of` in `infra-cdk/config.yaml`, default `2026-06-17T23:59:59`, 2-year window). Freshness policy: the organizer bucket is a static snapshot, so the data is refreshed only by changing `as_of` and re-running the job. A reload drops and recreates the `bank`/`pii` tables, so **never reload during a demo or the judging window**.

- Load: `AWS_PROFILE=ledgerlens make load-data`
- Rehearse locally (no AWS): `uv run --no-project --with-requirements data_load/requirements.txt python -m data_load stage --source datathon/data --out <dir>`
- Check the bucket for re-uploads: `python -m data_load check --bucket <bucket> --endpoint <DsqlEndpoint>`

Design: `docs/superpowers/specs/2026-09-29-data-loading-design.md`.
```

- [ ] **Step 10: Commit**

```bash
git add docs/LEDGERLENS_PRODUCT_DESIGN.md docs/LATAM_Bank_ERD.md README.md
git diff --cached --stat
git commit -m "docs: align design doc, ERD and README with the data-loading spec"
```
