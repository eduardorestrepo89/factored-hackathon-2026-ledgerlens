# LedgerLens Curate Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `curate` stage between transform and load that fixes per-customer incoherence (rules C1–C12) and selects 1,500 coherent customers (10 pinned personas among them), plus a defect cohort kept as delivered. Load then puts only that curated set into DSQL `public`.

**Architecture:**
- **Three modules,** following `data_load/repair.py`'s pattern:
  - `curate_rules.py`: the 12 rules, their evidence checks and invariants;
  - `curate_select.py`: gates, score, balanced selection, personas, defect cohort;
  - `curate.py`: the stage, which loads `clean/` Parquet into an on-disk DuckDB, snapshots the cohort, applies the rules, selects, assembles, checks and writes `curated/` Parquet.
- **CLI and records:** a `curate` command and a `runs/<run-id>/curate.json` record. `load` reads that record instead of `transform.json`.
- **Infrastructure:** the Step Functions chain gains one CodeBuild state.

**Tech Stack:**
- Python 3.12 with DuckDB 1.5.5. No new dependency (decision recorded in Global Constraints).
- pytest.
- AWS CDK (TypeScript) with jest.
- Step Functions and CodeBuild.

**Spec:** `docs/superpowers/specs/2026-10-03-curate-stage-design.md`. Read it first: section 5 (rules), section 6 (selection) and section 7 (defect cohort) are the authority. Evidence lives in `datathon/docs/analysis/2026-10-02-agent-data-diagnostic.md`.

**Starting point:** branch `feat/testing-db` at `7f09aff` (the spec commit). Implement on a new branch `feat/curate-stage` cut from it.

**How this plan was checked:**
- **Code:** every file below was written and run in a scratch worktree of the repo.
- **Unit tests:**
  - the 32 new tests and the 7 changed CLI tests fail against the current code (RED) and pass with the code below (GREEN);
  - the whole suite (`tests/unit/test_data_load_*.py`, `test_dsql_read_check.py`, `test_deploy_with_codebuild.py`) passes: 120 tests.
- **Full-data rehearsal:** `python -m data_load curate --source <clean> --out <dir>` ran on the full repaired data, which the local transform produced with the exact R1–R6 counts. It produced the counts pinned in Task 6 in 3 min 27 s.
- **Infrastructure:** the CDK construct type-checks. Its state-machine jest test fails against the current construct and passes against the new one, and all 10 tests pass.

## Global Constraints

- **Names:**

  | Thing | Name |
  |---|---|
  | Stage command | `python -m data_load curate` (CodeBuild `STAGE=curate`) |
  | Step Functions state | `Curate`, between `Transform` and `Load` |
  | Run record | `runs/<run-id>/curate.json` |
  | Data layer | `curated/<run-id>/<table>.parquet` and `.sha256` |
  | Persona file | `data_load/personas.json` (P01–P10) |
  | Reserved ID prefix | `EVL-` (evaluation clones; never in organizer data) |

- **`as_of`:** `2026-06-17 23:59:59`. It is hard-coded in `curate_rules.py` (`AS_OF`, `AS_OF_DATE`) and must equal `infra-cdk/config.yaml` `data.as_of`.
- **Sizes:**
  - `--customers 1500` is 125 per country × segment cell, and must be a positive multiple of 12.
  - `--defect-per-class 20`.
  - The pinned counts in `expected.json` → `curation` are compared only on the full data with these default sizes.
- **No new dependency:**
  - C2 computes `amount_usd` in plain Python (`usd()` = Python `round(amount / rate, 2)`), the generator's own rounding.
  - A DuckDB Python UDF was tried. It needs numpy and ran about 600× slower: 95 s per 200,000 rows, about 15 minutes for the evidence check on the full data. Don't reintroduce it.
- **Python tests:** from the repo root, run `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest <files> -q`.
  - Never use `uv run` without `--no-project`: it writes a stray `uv.lock` at the repo root.
- **CDK tests:** `cd infra-cdk && npx tsc --noEmit && npx jest test/data-construct.test.ts`.
- **Lint:** run `uv run --no-project --quiet --with ruff ruff format <files>` and `uv run --no-project --quiet --with ruff ruff check <files>` on the files the task touches. Each task lists them. Never run ruff over the whole of `tests/unit`, which would reformat unrelated files. The repo's `ruff.toml` applies.
- **Staging files:** stage by path only. Never use `git add -A`, `git add .` or `git commit -a`.
- **Commits:** messages carry no Claude or `Co-Authored-By` signature (the user's standing instruction). Never push.
- **Organizer PDFs:** never open `datathon/*.pdf`. The data dictionary PDF contains AWS keys.
- **AWS:** Task 8 deploys and runs the pipeline in the team account. It needs the human's explicit go-ahead in the session before any `aws` or deploy command.

## Review Focus

These are the inputs and conditions the spec implies that a person is most likely to hit. Each has a pinning test in the task that owns the code.

1. **A persona stops qualifying** after a data or rule change. Expected: the stage fails naming the persona and the gate, rather than silently dropping a demo login. Pinned in Task 2 by `test_a_persona_that_fails_a_gate_fails_the_stage_naming_it`.
2. **A country × segment cell with no eligible customer at all.** Expected: the cell still appears in `curate.json` with `eligible 0, selected 0, short 125`, rather than vanishing. Pinned in Task 2 by the `México|Plus` assertion in `test_selection_takes_personas_first_then_scores_and_reports_short_cells`.
3. **`load` run for a run ID whose curate stage never ran.** Expected: "no curate.json for run …: run curate first", and DSQL is untouched. Other S3 errors such as AccessDenied must still surface as they are. Pinned in Task 4 by `test_load_without_a_curate_record_says_to_run_curate_first`.
4. **A downloaded clean Parquet that differs from `transform.json`** (truncated download or a rerun transform). Expected: the stage fails naming the table before curating anything. Pinned in Task 3 by `test_download_clean_rejects_a_file_that_differs_from_transform_json`.
5. **A clean customer that still breaks a rule after curation**, for example a rule silently skipped. Expected: the stage fails naming the rule and the row count. Pinned in Task 3 by `test_a_clean_customer_breaking_a_rule_fails_the_stage`.

## File map

| Path | Task | Responsibility |
|---|---|---|
| `data_load/curate_rules.py` | 1 | C1–C12, `check_evidence`, `apply_rules`, `check_invariants`, `CurationError`, the `AS_OF` constants |
| `tests/unit/curate_fixtures.py` | 1, 3 | A tiny in-memory bank (`bank`, `add`, `customer`, `card`, `charge`, `good`, `to_parquet`); `world()` and `PERSONAS` added in Task 3 |
| `tests/unit/test_data_load_curate_rules.py` | 1 | One test per rule edge case, plus evidence and invariants |
| `data_load/personas.json` | 2 | The 10 pinned personas and their alternates |
| `data_load/curate_select.py` | 2 | `build_profile` (gates g1–g8, score), `select_clean`, `defect_evidence`, `select_cohort`, `lost_defects` |
| `tests/unit/test_data_load_curate_select.py` | 2 | Gates, allocation, ties, personas, cohort, scenario counts |
| `data_load/curate.py` | 3 | `download_clean`, `curate` (the stage), assembly, checks, the `expected.json` comparison |
| `tests/unit/test_data_load_curate.py` | 3 | End to end on Parquet; size validation; pinned counts; invariant failure; SHA check |
| `data_load/__main__.py`, `data_load/runrecord.py` | 4 | `curate` command; `load` reads `curate.json`; `STAGES` gains `curate` |
| `tests/unit/test_data_load_cli.py` | 4 | CLI coverage for curate and the new load input |
| `infra-cdk/lib/data-construct.ts`, `infra-cdk/test/data-construct.test.ts` | 5 | The `Curate` state |
| `data_load/expected.json` | 6 | The pinned `curation` block |
| `datathon/analysis/curated_customers.py` + docs | 7 | Process and customers documentation |

---

### Task 1: Curation rules C1–C12

**Files:**
- Create: `data_load/curate_rules.py`
- Create: `tests/unit/curate_fixtures.py`
- Test: `tests/unit/test_data_load_curate_rules.py`

**Interfaces:**
- Consumes: `data_load.repair._count(con, sql) -> int` and `data_load.repair._tables(con) -> set[str]` (existing).
- Produces:
  - Constants:
    - `AS_OF: str` (SQL timestamp literal) and `AS_OF_DATE: str`;
    - `CARD_TYPES: str`;
    - `HOME: str` (SQL CASE over alias `c`), `HOME_RATE: str`;
    - `DEADLINES: str` (SQL VALUES with columns `country, days, rule_id`).
  - `class CurationError(RuntimeError)`.
  - `usd(amount: float, currency: str) -> float`.
  - `check_evidence(con) -> None` (raises `CurationError`).
  - `RULES: tuple[tuple[str, set[str], Callable], ...]`.
  - `apply_rules(con) -> dict[str, dict[str, int]]`.
  - `check_invariants(con, scope: str) -> dict[str, int]`, where `scope` is a SQL `SELECT` of `customer_id`.

- [ ] **Step 1: Write the test fixtures**

Create `tests/unit/curate_fixtures.py`:

```python
"""A tiny in-memory LATAM Bank for the curate tests: only the columns curate reads.

`good()` builds a customer who passes every gate (G1-G8); tests then break one thing.
"""

from datetime import date, datetime
from pathlib import Path

import duckdb

CREDIT, DEBIT = "Tarjeta Crédito", "Tarjeta Débito"
COLUMNS = {
    "branches": "branch_id VARCHAR",
    "service_agents": "agent_id VARCHAR, assigned_branch_id VARCHAR",
    "marketing_campaigns": "campaign_id VARCHAR",
    "customers": "customer_id VARCHAR, first_name VARCHAR, gender VARCHAR, "
    "date_of_birth DATE, email VARCHAR, mobile_phone VARCHAR, country VARCHAR, "
    "segment VARCHAR, registration_date TIMESTAMP, registration_branch_id VARCHAR, "
    "customer_status VARCHAR, last_updated TIMESTAMP",
    "products": "product_id VARCHAR, customer_id VARCHAR, product_type VARCHAR, "
    "product_number VARCHAR, currency VARCHAR, current_balance DECIMAL(15,2), "
    "credit_limit DECIMAL(15,2), opening_date DATE, expiration_date DATE, "
    "opening_branch_id VARCHAR, product_status VARCHAR, days_past_due INTEGER, "
    "last_transaction_date TIMESTAMP, last_updated TIMESTAMP",
    "transactions": "transaction_id VARCHAR, transaction_date TIMESTAMP, process_date DATE, "
    "product_id VARCHAR, customer_id VARCHAR, transaction_type VARCHAR, "
    "amount DECIMAL(15,2), currency VARCHAR, amount_usd DECIMAL(15,2), channel VARCHAR, "
    "branch_id VARCHAR, merchant_name VARCHAR, merchant_category VARCHAR, "
    "transaction_country VARCHAR, transaction_status VARCHAR, response_code VARCHAR, "
    "fraud_score DECIMAL(5,2)",
    "call_center_interactions": "interaction_id VARCHAR, customer_id VARCHAR, "
    "agent_id VARCHAR, process_date DATE",
    "call_transcripts": "transcript_id VARCHAR, interaction_id VARCHAR, "
    "customer_id VARCHAR, agent_id VARCHAR",
    "satisfaction_surveys": "survey_id VARCHAR, interaction_id VARCHAR, "
    "customer_id VARCHAR, agent_id VARCHAR",
    "digital_events": "event_id VARCHAR, customer_id VARCHAR, product_id VARCHAR, "
    "event_date TIMESTAMP, process_date DATE",
    "complaints": "complaint_id VARCHAR, creation_date TIMESTAMP, customer_id VARCHAR, "
    "subcategory VARCHAR, affected_product_id VARCHAR, related_branch_id VARCHAR, "
    "origin_interaction_id VARCHAR, claimed_amount DECIMAL(15,2), currency VARCHAR, "
    "status VARCHAR, assigned_agent_id VARCHAR, assignment_date TIMESTAMP, "
    "first_response_date TIMESTAMP, resolution_date TIMESTAMP, closing_date TIMESTAMP, "
    "resolution VARCHAR, resolution_days INTEGER, compensation_granted DECIMAL(15,2), "
    "resolution_satisfaction SMALLINT",
    "campaign_sends": "send_id VARCHAR, campaign_id VARCHAR, customer_id VARCHAR",
}


def bank() -> duckdb.DuckDBPyConnection:
    """An in-memory database with all 12 tables curate reads, empty."""
    con = duckdb.connect()
    for name, columns in COLUMNS.items():
        con.execute(f"CREATE TABLE {name} ({columns})")
    return con


def add(con, table: str, **values) -> None:
    """Insert one row; unspecified columns are NULL."""
    marks = ", ".join("?" * len(values))
    con.execute(
        f"INSERT INTO {table} ({', '.join(values)}) VALUES ({marks})",
        list(values.values()),
    )


def customer(con, cid: str, **over) -> None:
    """A customer who passes G1-G4: Active, adult, contactable, a one-token name."""
    row = {
        "customer_id": cid,
        "first_name": "Ana",
        "gender": "F",
        "date_of_birth": date(1980, 1, 1),
        "email": f"{cid.lower()}@example.com",
        "mobile_phone": "+57 300 000 0000",
        "country": "Colombia",
        "segment": "Basic",
        "registration_date": datetime(2020, 1, 1),
        "customer_status": "Active",
        "last_updated": datetime(2026, 1, 1),
    }
    add(con, "customers", **{**row, **over})


def card(con, pid: str, cid: str, **over) -> None:
    """A usable Active credit card: limit 1,000, balance 100, expiring in 2028."""
    row = {
        "product_id": pid,
        "customer_id": cid,
        "product_type": CREDIT,
        "product_number": "4000000000001234",
        "currency": "COP",
        "current_balance": 100,
        "credit_limit": 1000,
        "opening_date": date(2023, 1, 1),
        "expiration_date": date(2028, 1, 1),
        "product_status": "Active",
        "days_past_due": 0,
        "last_updated": datetime(2026, 1, 1),
    }
    add(con, "products", **{**row, **over})


def charge(con, tid: str, pid: str, cid: str, **over) -> None:
    """An Approved card purchase on 2026-06-15, inside every scoring window."""
    row = {
        "transaction_id": tid,
        "transaction_date": datetime(2026, 6, 15, 12),
        "process_date": date(2026, 6, 15),
        "product_id": pid,
        "customer_id": cid,
        "transaction_type": "Purchase",
        "amount": 40,
        "currency": "COP",
        "amount_usd": 0.01,
        "channel": "POS",
        "merchant_name": "Super Ahorro",
        "merchant_category": "Food",
        "transaction_country": "Colombia",
        "transaction_status": "Approved",
        "response_code": "00",
        "fraud_score": 1,
    }
    add(con, "transactions", **{**row, **over})


def good(con, cid: str, **over) -> None:
    """A customer, a usable credit card and a recent charge: passes every gate."""
    customer(con, cid, **over)
    card(con, f"P-{cid}", cid)
    charge(con, f"T-{cid}", f"P-{cid}", cid)


def to_parquet(con, folder: Path) -> None:
    """Write every table as <folder>/<table>.parquet, the layout transform produces."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in COLUMNS:
        con.execute(
            f"COPY {name} TO '{(folder / name).as_posix()}.parquet' (FORMAT parquet)"
        )
```

- [ ] **Step 2: Write the failing rule tests**

Create `tests/unit/test_data_load_curate_rules.py`:

```python
"""Curation rules C1-C12, their evidence checks and invariants (curate spec section 5)."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from curate_fixtures import add, bank, card, charge, customer

from data_load.curate_rules import (
    CurationError,
    apply_rules,
    check_evidence,
    check_invariants,
)


def value(con, sql: str):
    return con.execute(sql).fetchone()[0]


def by_id(con, table: str, key: str, column: str) -> dict:
    return dict(con.execute(f"SELECT {key}, {column} FROM {table}").fetchall())


@pytest.mark.unit
def test_c1_c3_c4_fix_country_spelling_category_and_approval_code():
    con = bank()
    charge(con, "T1", "P1", "C1", transaction_country="Mexico", response_code=None)
    charge(
        con, "T2", "P1", "C1", merchant_category=None
    )  # Super Ahorro is Food elsewhere
    charge(con, "T3", "P1", "C1", transaction_status="Declined", response_code=None)
    counts = apply_rules(con)
    assert counts["C1"] == {"changed": 1}
    assert counts["C3"] == {"changed": 1}
    assert counts["C4"] == {"changed": 1}  # the Declined row keeps its NULL code
    assert (
        by_id(con, "transactions", "transaction_id", "transaction_country")["T1"]
        == "México"
    )
    assert (
        by_id(con, "transactions", "transaction_id", "merchant_category")["T2"]
        == "Food"
    )
    assert by_id(con, "transactions", "transaction_id", "response_code") == {
        "T1": "00",
        "T2": "00",
        "T3": None,
    }


@pytest.mark.unit
def test_c2_rounds_half_cents_like_the_generator_not_like_duckdb():
    con = bank()
    # 51987.25 / 350 = 148.535: the generator stored 148.53; DuckDB's round() gives 148.54
    charge(
        con,
        "T1",
        "P1",
        "C1",
        amount=Decimal("51987.25"),
        currency="ARS",
        amount_usd=None,
    )
    charge(
        con,
        "T2",
        "P1",
        "C1",
        amount=Decimal("4000.00"),
        currency="COP",
        amount_usd=None,
    )
    charge(
        con, "T3", "P1", "C1", amount=Decimal("10.00"), currency="USD", amount_usd=None
    )
    check_evidence(con)
    assert apply_rules(con)["C2"] == {"changed": 2}  # USD rows keep a NULL amount_usd
    assert by_id(con, "transactions", "transaction_id", "amount_usd") == {
        "T1": Decimal("148.53"),
        "T2": Decimal("1.00"),
        "T3": None,
    }


@pytest.mark.unit
def test_evidence_fails_on_an_off_rate_amount_a_two_category_merchant_and_evl_ids():
    con = bank()
    charge(
        con, "T1", "P1", "C1", amount=Decimal("350.00"), currency="ARS", amount_usd=2
    )
    charge(
        con, "T2", "P1", "C1", merchant_category="Other"
    )  # Super Ahorro is also Food
    charge(con, "T3", "P1", "C1")
    customer(con, "EVL-1")
    with pytest.raises(CurationError) as failed:
        check_evidence(con)
    message = str(failed.value)
    assert "C3: 1 merchants have more than one category" in message
    assert "C2: 1 stored amount_usd values differ from usd()" in message
    assert "1 customer_id values use the reserved EVL- prefix" in message


@pytest.mark.unit
def test_c5_c6_derive_last_transaction_date_and_clamp_future_updates():
    con = bank()
    customer(con, "C1", last_updated=datetime(2027, 6, 15))
    card(con, "P1", "C1", last_transaction_date=datetime(2020, 1, 1))
    card(con, "P2", "C1", last_transaction_date=datetime(2020, 1, 1))  # never used
    charge(con, "T1", "P1", "C1", transaction_date=datetime(2026, 6, 15, 12))
    charge(con, "T2", "P1", "C1", transaction_date=datetime(2026, 6, 1, 9))
    counts = apply_rules(con)
    assert counts["C5"] == {"changed": 2}
    assert counts["C6"] == {"customers": 1, "products": 0}
    assert by_id(con, "products", "product_id", "last_transaction_date") == {
        "P1": datetime(2026, 6, 15, 12),
        "P2": None,
    }
    assert value(con, "SELECT last_updated FROM customers") == datetime(
        2026, 6, 17, 23, 59, 59
    )


@pytest.mark.unit
def test_c7_rolls_cases_with_future_dates_back_to_their_state_at_as_of():
    con = bank()
    customer(con, "C1")
    future, past = datetime(2026, 7, 1), datetime(2026, 6, 10)
    common = {"customer_id": "C1", "creation_date": datetime(2026, 6, 1)}
    add(
        con,
        "complaints",
        complaint_id="K1",
        status="Closed",
        assignment_date=past,
        first_response_date=past,
        resolution_date=past,
        closing_date=future,
        resolution="ok",
        resolution_days=9,
        resolution_satisfaction=4,
        **common,
    )
    add(
        con,
        "complaints",
        complaint_id="K2",
        status="Resolved",
        assignment_date=past,
        first_response_date=past,
        resolution_date=future,
        resolution="ok",
        resolution_days=30,
        compensation_granted=5,
        **common,
    )
    assert apply_rules(con)["C7"] == {"changed": 2}
    rows = {
        r[0]: r[1:]
        for r in con.execute(
            "SELECT complaint_id, status, closing_date, resolution_date, resolution, "
            "resolution_days, compensation_granted, resolution_satisfaction FROM complaints"
        ).fetchall()
    }
    assert rows["K1"] == ("Resolved", None, past, "ok", 9, None, None)
    assert rows["K2"] == ("In Process", None, None, None, None, None, None)


@pytest.mark.unit
def test_c8_reissues_expired_active_cards_unless_a_code_54_decline_proves_expiry():
    con = bank()
    card(
        con, "P1", "C1", opening_date=date(2021, 3, 1), expiration_date=date(2024, 3, 1)
    )
    card(
        con,
        "P2",
        "C1",
        opening_date=date(2020, 1, 10),
        expiration_date=date(2025, 1, 10),
    )
    card(con, "P3", "C1", expiration_date=date(2024, 1, 1), product_status="Blocked")
    charge(
        con,
        "T1",
        "P2",
        "C1",
        transaction_date=datetime(2025, 2, 1, 10),
        transaction_status="Declined",
        response_code="54",
    )
    assert apply_rules(con)["C8"] == {"reissued": 1, "kept_expired": 1}
    assert by_id(con, "products", "product_id", "expiration_date") == {
        "P1": date(2027, 3, 1),  # term 3 years: 2024 -> 2027, the first after as_of
        "P2": date(2025, 1, 10),  # code 54 after expiry: really expired, kept
        "P3": date(2024, 1, 1),  # not Active: untouched
    }


@pytest.mark.unit
def test_c9_c10_settle_old_pending_charges_and_drop_codes_off_declines():
    con = bank()
    charge(
        con,
        "T1",
        "P1",
        "C1",
        transaction_status="Pending",
        response_code="05",
        process_date=date(2026, 6, 10),
    )  # 7 days before as_of: settles
    charge(
        con,
        "T2",
        "P1",
        "C1",
        transaction_status="Pending",
        response_code="51",
        process_date=date(2026, 6, 11),
    )  # 6 days: still pending
    charge(con, "T3", "P1", "C1", transaction_status="Reversed", response_code="14")
    counts = apply_rules(con)
    assert counts["C9"] == {"changed": 1}
    assert counts["C10"] == {"changed": 2}
    rows = con.execute(
        "SELECT transaction_id, transaction_status, response_code FROM transactions "
        "ORDER BY 1"
    ).fetchall()
    assert rows == [
        ("T1", "Approved", "00"),
        ("T2", "Pending", None),
        ("T3", "Reversed", None),
    ]


@pytest.mark.unit
def test_c11_closes_cases_on_each_countrys_legal_deadline():
    con = bank()
    customer(con, "AR", country="Argentina")
    customer(con, "CO", country="Colombia")
    customer(con, "MX", country="México")
    add(
        con,
        "complaints",
        complaint_id="K1",
        customer_id="AR",
        status="Open",
        creation_date=datetime(2026, 6, 3),
    )  # +14 days = 06-17 00:00: due
    add(
        con,
        "complaints",
        complaint_id="K2",
        customer_id="CO",
        status="In Process",
        creation_date=datetime(2026, 6, 3),
    )  # +21 days = 06-24: still inside the deadline
    add(
        con,
        "complaints",
        complaint_id="K3",
        customer_id="MX",
        status="Rejected",
        creation_date=datetime(2026, 1, 1),
    )  # +42 days
    assert apply_rules(con)["C11"] == {"closed": 1, "rejected_dated": 1}
    rows = {
        r[0]: r[1:]
        for r in con.execute(
            "SELECT complaint_id, status, closing_date, resolution_date, resolution_days, "
            "resolution FROM complaints"
        ).fetchall()
    }
    assert rows["K1"][:4] == (
        "Closed",
        datetime(2026, 6, 17),
        datetime(2026, 6, 17),
        14,
    )
    assert "AR-CLAIM" in rows["K1"][4] and "regla sintética C11" in rows["K1"][4]
    assert rows["K2"] == ("In Process", None, None, None, None)
    assert rows["K3"] == ("Rejected", datetime(2026, 2, 12), None, None, None)


@pytest.mark.unit
def test_c12_puts_case_money_in_the_home_currency_at_the_book_rate():
    con = bank()
    customer(con, "AR", country="Argentina")
    customer(con, "MX", country="México")
    customer(con, "CO", country="Colombia")
    add(
        con,
        "complaints",
        complaint_id="K1",
        customer_id="AR",
        claimed_amount=100,
        currency="MXN",
        compensation_granted=10,
        status="Open",
        creation_date=datetime(2026, 6, 16),
    )
    add(
        con,
        "complaints",
        complaint_id="K2",
        customer_id="MX",
        claimed_amount=100,
        currency="USD",
        status="Open",
        creation_date=datetime(2026, 6, 16),
    )
    add(
        con,
        "complaints",
        complaint_id="K3",
        customer_id="CO",
        currency="COP",
        status="Open",
        creation_date=datetime(2026, 6, 16),
    )
    assert apply_rules(con)["C12"] == {"changed": 2}  # K2 is already right
    rows = {
        r[0]: r[1:]
        for r in con.execute(
            "SELECT complaint_id, currency, claimed_amount, compensation_granted FROM complaints"
        ).fetchall()
    }
    assert rows["K1"] == ("ARS", Decimal("35000.00"), Decimal("3500.00"))
    assert rows["K2"] == ("USD", Decimal("100.00"), None)
    assert rows["K3"] == (None, None, None)


@pytest.mark.unit
def test_invariants_count_the_rows_of_scoped_customers_that_still_break_a_rule():
    con = bank()
    customer(con, "C1")
    customer(con, "C2")
    card(con, "P1", "C1")
    charge(con, "T1", "P1", "C1", transaction_country="Mexico")
    charge(con, "T2", "P1", "C2", transaction_country="Mexico")
    apply_rules(con)
    assert set(check_invariants(con, "SELECT 'C1'").values()) == {0}
    con.execute("UPDATE transactions SET transaction_country = 'Mexico'")
    broken = check_invariants(con, "SELECT 'C1'")
    assert broken["C1"] == 1  # only C1's row is in scope
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_curate_rules.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'data_load.curate_rules'`.

- [ ] **Step 4: Write the rules module**

Create `data_load/curate_rules.py`:

```python
"""Curation rules C1-C12, their evidence checks and their invariants.

Spec: docs/superpowers/specs/2026-10-03-curate-stage-design.md, section 5. As in repair.py,
each rule writes its fixes to a temp table first, so the count comes from the same rows the
UPDATE changes, and runs only when all its tables are loaded (unit tests load a few).
C1-C7 derive values from other columns; C8-C12 are synthetic and labelled as such.
"""

from data_load.repair import _count, _tables

# The bank's "today": infra-cdk/config.yaml data.as_of, the tools' AS_OF
AS_OF = "TIMESTAMP '2026-06-17 23:59:59'"
AS_OF_DATE = "DATE '2026-06-17'"
CARD_TYPES = "('Tarjeta Crédito', 'Tarjeta Débito')"
BOOK_RATE = {"ARS": 350, "COP": 4000}  # amount_usd = amount / rate (probes Q3)
# Home currency and book rate by country, for an alias `c` of customers (contract: Mexico = USD)
HOME = "CASE c.country WHEN 'Argentina' THEN 'ARS' WHEN 'Colombia' THEN 'COP' ELSE 'USD' END"
HOME_RATE = (
    "CASE c.country WHEN 'Argentina' THEN 350 WHEN 'Colombia' THEN 4000 ELSE 1 END"
)
# Legal answer deadlines in calendar days (10/15/30 business days x 7/5), design v3 section 9
DEADLINES = (
    "(VALUES ('Argentina', 14, 'AR-CLAIM'), ('Colombia', 21, 'CO-PQR'), "
    "('México', 42, 'MX-UNE')) d(country, days, rule_id)"
)


class CurationError(RuntimeError):
    """An evidence, invariant, gate, persona, cohort, link or count check failed."""


def usd(amount: float, currency: str) -> float:
    """The generator's rounding: Python round() of the float quotient. It reproduces
    every stored amount_usd; DuckDB's round() differs on 1,089 half-cents (spec section 2)."""
    return round(amount / BOOK_RATE[currency], 2)


def _usd_mismatches(con, batch: int = 100_000) -> int:
    """Stored ARS/COP amount_usd values that usd() doesn't reproduce. Plain Python: a
    DuckDB Python UDF needs numpy and ran ~600x slower (95 s per 200,000 rows)."""
    cur = con.execute(
        "SELECT amount::DOUBLE, currency, amount_usd::DOUBLE FROM transactions "
        "WHERE amount_usd IS NOT NULL AND currency IN ('ARS', 'COP')"
    )
    off = 0
    while rows := cur.fetchmany(batch):
        off += sum(1 for amount, code, stored in rows if usd(amount, code) != stored)
    return off


def check_evidence(con) -> None:
    """Fail unless C2 and C3's evidence holds and no ID uses the reserved EVL- prefix."""
    loaded, failures = _tables(con), []
    if "transactions" in loaded:
        merchants = _count(
            con,
            "SELECT count(*) FROM (SELECT merchant_name FROM transactions "
            "WHERE merchant_name IS NOT NULL AND merchant_category IS NOT NULL "
            "GROUP BY 1 HAVING count(DISTINCT merchant_category) > 1)",
        )
        if merchants:
            failures.append(f"C3: {merchants} merchants have more than one category")
        off = _usd_mismatches(con)
        if off:
            failures.append(f"C2: {off:,} stored amount_usd values differ from usd()")
    if "customers" in loaded:
        evl = _count(
            con, "SELECT count(*) FROM customers WHERE customer_id LIKE 'EVL-%'"
        )
        if evl:
            failures.append(f"{evl} customer_id values use the reserved EVL- prefix")
    if failures:
        raise CurationError("evidence checks failed: " + "; ".join(failures))


def _fix(con, name: str, select_sql: str) -> int:
    con.execute(f"CREATE OR REPLACE TEMP TABLE fix_{name} AS {select_sql}")
    return _count(con, f"SELECT count(*) FROM fix_{name}")


def c1(con) -> dict[str, int]:
    """transactions.transaction_country: 'Mexico' -> 'México' (D21)."""
    n = _fix(
        con,
        "c1",
        "SELECT transaction_id FROM transactions WHERE transaction_country = 'Mexico'",
    )
    con.execute(
        "UPDATE transactions SET transaction_country = 'México' FROM fix_c1 f "
        "WHERE transactions.transaction_id = f.transaction_id"
    )
    return {"changed": n}


def c2(con) -> dict[str, int]:
    """transactions.amount_usd: NULL on ARS/COP -> usd(amount, currency) (D24)."""
    rows = con.execute(
        "SELECT transaction_id, amount::DOUBLE, currency FROM transactions "
        "WHERE amount_usd IS NULL AND currency IN ('ARS', 'COP')"
    ).fetchall()
    con.execute(
        "CREATE OR REPLACE TEMP TABLE fix_c2 AS "
        "SELECT unnest($1::VARCHAR[]) AS transaction_id, unnest($2::DOUBLE[]) AS usd",
        [[r[0] for r in rows], [usd(r[1], r[2]) for r in rows]],
    )
    n = len(rows)
    con.execute(
        "UPDATE transactions SET amount_usd = f.usd FROM fix_c2 f "
        "WHERE transactions.transaction_id = f.transaction_id"
    )
    return {"changed": n}


def c3(con) -> dict[str, int]:
    """transactions.merchant_category: NULL with a merchant -> the merchant's only category (D20)."""
    n = _fix(
        con,
        "c3",
        "SELECT t.transaction_id, m.category FROM transactions t JOIN ("
        " SELECT merchant_name, min(merchant_category) AS category FROM transactions"
        " WHERE merchant_name IS NOT NULL AND merchant_category IS NOT NULL GROUP BY 1"
        ") m USING (merchant_name) WHERE t.merchant_category IS NULL",
    )
    con.execute(
        "UPDATE transactions SET merchant_category = f.category FROM fix_c3 f "
        "WHERE transactions.transaction_id = f.transaction_id"
    )
    return {"changed": n}


def c4(con) -> dict[str, int]:
    """transactions.response_code: Approved with NULL -> '00' (D17)."""
    n = _fix(
        con,
        "c4",
        "SELECT transaction_id FROM transactions "
        "WHERE transaction_status = 'Approved' AND response_code IS NULL",
    )
    con.execute(
        "UPDATE transactions SET response_code = '00' FROM fix_c4 f "
        "WHERE transactions.transaction_id = f.transaction_id"
    )
    return {"changed": n}


def c5(con) -> dict[str, int]:
    """products.last_transaction_date := the product's real last transaction (D11)."""
    n = _fix(
        con,
        "c5",
        "SELECT p.product_id, m.last_tx FROM products p LEFT JOIN ("
        " SELECT product_id, max(transaction_date) AS last_tx FROM transactions GROUP BY 1"
        ") m USING (product_id) WHERE p.last_transaction_date IS DISTINCT FROM m.last_tx",
    )
    con.execute(
        "UPDATE products SET last_transaction_date = f.last_tx FROM fix_c5 f "
        "WHERE products.product_id = f.product_id"
    )
    return {"changed": n}


def c6(con) -> dict[str, int]:
    """customers/products.last_updated after as_of -> as_of (D04)."""
    counts = {}
    for table, key in (("customers", "customer_id"), ("products", "product_id")):
        counts[table] = _fix(
            con,
            f"c6_{table}",
            f"SELECT {key} FROM {table} WHERE last_updated > {AS_OF}",
        )
        con.execute(
            f"UPDATE {table} SET last_updated = {AS_OF} FROM fix_c6_{table} f "
            f"WHERE {table}.{key} = f.{key}"
        )
    return counts


def c7(con) -> dict[str, int]:
    """complaints with a lifecycle date after as_of -> their state at as_of (D27).
    Every SET expression reads the row as it was before the UPDATE."""
    n = _fix(
        con,
        "c7",
        "SELECT complaint_id FROM complaints WHERE greatest(assignment_date, "
        f"first_response_date, resolution_date, closing_date) > {AS_OF}",
    )
    con.execute(
        f"""UPDATE complaints SET
          status = CASE WHEN closing_date <= {AS_OF} THEN 'Closed'
                        WHEN resolution_date <= {AS_OF} THEN 'Resolved'
                        WHEN first_response_date <= {AS_OF} OR assignment_date <= {AS_OF}
                          THEN 'In Process'
                        ELSE 'Open' END,
          resolution_satisfaction = CASE WHEN closing_date > {AS_OF} OR resolution_date > {AS_OF}
                                         THEN NULL ELSE resolution_satisfaction END,
          resolution = CASE WHEN resolution_date > {AS_OF} THEN NULL ELSE resolution END,
          resolution_days = CASE WHEN resolution_date > {AS_OF} THEN NULL ELSE resolution_days END,
          compensation_granted = CASE WHEN resolution_date > {AS_OF} THEN NULL
                                      ELSE compensation_granted END,
          closing_date = CASE WHEN closing_date > {AS_OF} THEN NULL ELSE closing_date END,
          resolution_date = CASE WHEN resolution_date > {AS_OF} THEN NULL ELSE resolution_date END,
          first_response_date = CASE WHEN first_response_date > {AS_OF} THEN NULL
                                     ELSE first_response_date END,
          assignment_date = CASE WHEN assignment_date > {AS_OF} THEN NULL ELSE assignment_date END
        FROM fix_c7 f WHERE complaints.complaint_id = f.complaint_id"""
    )
    return {"changed": n}


def c8(con) -> dict[str, int]:
    """Active cards expired at as_of are reissued: expiry moves forward by their own term
    (3-5 years) until after as_of, unless a code-54 decline after the original expiry shows
    the card really was expired (D09; spec decision E5)."""
    expired = (
        f"product_type IN {CARD_TYPES} AND product_status = 'Active' "
        f"AND expiration_date < {AS_OF_DATE}"
    )
    n = _fix(
        con,
        "c8",
        "SELECT product_id, CAST(expiration_date + to_years(CAST("
        f"((year({AS_OF_DATE}) - year(expiration_date)) // term + 1) * term AS INTEGER)) "
        "AS DATE) AS new_expiry FROM ("
        " SELECT p.product_id, p.expiration_date,"
        " least(5, greatest(3, date_diff('year', p.opening_date, p.expiration_date))) AS term"
        f" FROM products p WHERE {expired}"
        " AND NOT EXISTS (SELECT 1 FROM transactions x WHERE x.product_id = p.product_id"
        " AND x.transaction_status = 'Declined' AND x.response_code = '54'"
        " AND x.transaction_date::DATE > p.expiration_date))",
    )
    kept = _count(con, f"SELECT count(*) FROM products WHERE {expired}") - n
    con.execute(
        "UPDATE products SET expiration_date = f.new_expiry FROM fix_c8 f "
        "WHERE products.product_id = f.product_id"
    )
    return {"reissued": n, "kept_expired": kept}


def c9(con) -> dict[str, int]:
    """Pending for 7 days or more at as_of -> Approved '00': the authorization settled (D19)."""
    n = _fix(
        con,
        "c9",
        "SELECT transaction_id FROM transactions "
        f"WHERE transaction_status = 'Pending' AND process_date <= {AS_OF_DATE} - 7",
    )
    con.execute(
        "UPDATE transactions SET transaction_status = 'Approved', response_code = '00' "
        "FROM fix_c9 f WHERE transactions.transaction_id = f.transaction_id"
    )
    return {"changed": n}


def c10(con) -> dict[str, int]:
    """response_code on Pending and Reversed -> NULL: decline codes belong to declines (D17)."""
    n = _fix(
        con,
        "c10",
        "SELECT transaction_id FROM transactions "
        "WHERE transaction_status IN ('Pending', 'Reversed') AND response_code IS NOT NULL",
    )
    con.execute(
        "UPDATE transactions SET response_code = NULL FROM fix_c10 f "
        "WHERE transactions.transaction_id = f.transaction_id"
    )
    return {"changed": n}


def c11(con) -> dict[str, int]:
    """Cases past the legal answer deadline are closed on it; Rejected ones get the date (D26)."""
    n = _fix(
        con,
        "c11",
        "SELECT k.complaint_id, k.status, k.creation_date + to_days(d.days) AS due, "
        f"d.days, d.rule_id FROM complaints k JOIN customers c USING (customer_id) "
        f"JOIN {DEADLINES} USING (country) WHERE k.closing_date IS NULL "
        "AND k.status IN ('Open', 'In Process', 'Escalated', 'Rejected') "
        f"AND k.creation_date + to_days(d.days) <= {AS_OF}",
    )
    rejected = _count(con, "SELECT count(*) FROM fix_c11 WHERE status = 'Rejected'")
    con.execute(
        """UPDATE complaints SET closing_date = f.due,
          status = CASE WHEN f.status = 'Rejected' THEN 'Rejected' ELSE 'Closed' END,
          resolution_date = CASE WHEN f.status = 'Rejected' THEN complaints.resolution_date
                                 ELSE f.due END,
          resolution_days = CASE WHEN f.status = 'Rejected' THEN complaints.resolution_days
                                 ELSE f.days END,
          resolution = CASE WHEN f.status = 'Rejected' THEN complaints.resolution
                            ELSE 'Cerrado al vencer el plazo legal de respuesta ('
                                 || f.rule_id || '); regla sintética C11' END
        FROM fix_c11 f WHERE complaints.complaint_id = f.complaint_id"""
    )
    return {"closed": n - rejected, "rejected_dated": rejected}


def c12(con) -> dict[str, int]:
    """Case money in the customer's home currency; amounts are USD-scale in every currency,
    so they are converted at the book rate (D28; spec decision E6)."""
    money = "(k.claimed_amount IS NOT NULL OR k.compensation_granted IS NOT NULL)"
    n = _fix(
        con,
        "c12",
        f"SELECT k.complaint_id, {money} AS has_money, {HOME} AS home, {HOME_RATE} AS rate "
        "FROM complaints k JOIN customers c USING (customer_id) "
        f"WHERE ({money} AND (k.currency IS DISTINCT FROM {HOME} OR {HOME_RATE} <> 1)) "
        f"OR (NOT {money} AND k.currency IS NOT NULL)",
    )
    con.execute(
        "UPDATE complaints SET currency = CASE WHEN f.has_money THEN f.home END, "
        "claimed_amount = round(claimed_amount * f.rate, 2), "
        "compensation_granted = round(compensation_granted * f.rate, 2) "
        "FROM fix_c12 f WHERE complaints.complaint_id = f.complaint_id"
    )
    return {"changed": n}


# Order matters: C7 settles future dates before C11 closes cases on their deadline
RULES = (
    ("C1", {"transactions"}, c1),
    ("C2", {"transactions"}, c2),
    ("C3", {"transactions"}, c3),
    ("C4", {"transactions"}, c4),
    ("C5", {"products", "transactions"}, c5),
    ("C6", {"customers", "products"}, c6),
    ("C7", {"complaints"}, c7),
    ("C8", {"products", "transactions"}, c8),
    ("C9", {"transactions"}, c9),
    ("C10", {"transactions"}, c10),
    ("C11", {"complaints", "customers"}, c11),
    ("C12", {"complaints", "customers"}, c12),
)


def apply_rules(con) -> dict[str, dict[str, int]]:
    """Apply every rule whose tables are loaded, in order; return counts per rule."""
    loaded = _tables(con)
    return {rule: fix(con) for rule, needs, fix in RULES if needs <= loaded}


def _invariants(scope: str) -> dict[str, str]:
    """Rows of the customers in `scope` (a SELECT of customer_id) that still break a rule."""
    tx = f"SELECT count(*) FROM transactions WHERE customer_id IN ({scope}) AND "
    return {
        "C1": tx + "transaction_country = 'Mexico'",
        "C2": tx + "amount_usd IS NULL AND currency IN ('ARS', 'COP')",
        "C3": tx + "merchant_name IS NOT NULL AND merchant_category IS NULL",
        "C4": tx + "transaction_status = 'Approved' AND response_code IS NULL",
        "C5": "SELECT count(*) FROM products p LEFT JOIN (SELECT product_id, "
        "max(transaction_date) AS last_tx FROM transactions GROUP BY 1) m "
        f"USING (product_id) WHERE p.customer_id IN ({scope}) "
        "AND p.last_transaction_date IS DISTINCT FROM m.last_tx",
        "C6": f"SELECT (SELECT count(*) FROM customers WHERE customer_id IN ({scope}) "
        f"AND last_updated > {AS_OF}) + (SELECT count(*) FROM products "
        f"WHERE customer_id IN ({scope}) AND last_updated > {AS_OF})",
        "C7": f"SELECT count(*) FROM complaints WHERE customer_id IN ({scope}) "
        "AND greatest(assignment_date, first_response_date, resolution_date, "
        f"closing_date) > {AS_OF}",
        "C8": f"SELECT count(*) FROM products WHERE customer_id IN ({scope}) "
        f"AND product_type IN {CARD_TYPES} AND product_status = 'Active' "
        f"AND expiration_date < {AS_OF_DATE}",
        "C9": tx
        + f"transaction_status = 'Pending' AND process_date <= {AS_OF_DATE} - 7",
        "C10": tx + "transaction_status IN ('Pending', 'Reversed') "
        "AND response_code IS NOT NULL",
        "C11": "SELECT count(*) FROM complaints k JOIN customers c USING (customer_id) "
        f"JOIN {DEADLINES} USING (country) WHERE k.customer_id IN ({scope}) "
        "AND k.closing_date IS NULL "
        "AND k.status IN ('Open', 'In Process', 'Escalated', 'Rejected') "
        f"AND k.creation_date + to_days(d.days) <= {AS_OF}",
        "C12": "SELECT count(*) FROM complaints k JOIN customers c USING (customer_id) "
        f"WHERE k.customer_id IN ({scope}) AND ((k.claimed_amount IS NOT NULL "
        f"OR k.compensation_granted IS NOT NULL) AND k.currency IS DISTINCT FROM {HOME} "
        "OR k.claimed_amount IS NULL AND k.compensation_granted IS NULL "
        "AND k.currency IS NOT NULL)",
    }


def check_invariants(con, scope: str) -> dict[str, int]:
    """Count, per rule, the rows of `scope` customers that still break it (0 = holds)."""
    loaded, sql = _tables(con), _invariants(scope)
    return {rule: _count(con, sql[rule]) for rule, needs, _ in RULES if needs <= loaded}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_curate_rules.py -q`
Expected: `10 passed`.

- [ ] **Step 6: Lint and commit**

```bash
uv run --no-project --quiet --with ruff ruff format data_load/curate_rules.py tests/unit/curate_fixtures.py tests/unit/test_data_load_curate_rules.py
uv run --no-project --quiet --with ruff ruff check data_load/curate_rules.py tests/unit/curate_fixtures.py tests/unit/test_data_load_curate_rules.py
git add data_load/curate_rules.py tests/unit/curate_fixtures.py tests/unit/test_data_load_curate_rules.py
git commit -m "feat(curate): rules C1-C12 with evidence checks and invariants"
```

---

### Task 2: Selection: gates, score, personas, defect cohort

**Files:**
- Create: `data_load/personas.json`
- Create: `data_load/curate_select.py`
- Test: `tests/unit/test_data_load_curate_select.py`

**Interfaces:**
- Consumes (Task 1): `AS_OF`, `AS_OF_DATE`, `CARD_TYPES`, `HOME`, `CurationError` from `data_load.curate_rules`.
- Produces:
  - Constants: `PERSONAS: Path`, `GATES: tuple[str, ...]` (`"g1".."g8"`), `ELIGIBLE: str` (SQL), `SCORE: str`, `SCENARIOS: tuple[str, ...]`, `CLASSES: dict[str, str]` (K01–K17).
  - `load_personas(path=PERSONAS) -> dict[str, dict]`.
  - `register_personas(con, personas) -> None`, which creates TEMP `persona_ids`.
  - `build_profile(con) -> None`, which creates TEMP `cards`, `card_tx30` and `profile`. `profile` has `customer_id, cell, g1..g8`, the scenario counts, `calls90, two_usable_cards, score`.
  - `select_clean(con, personas, per_cell: int) -> dict`. It needs TEMP `cohort` and `persona_ids`, creates TEMP `clean(customer_id, cell)`, and returns `{"customers", "funnel", "cells", "personas", "scenarios"}`.
  - `defect_evidence(con) -> None`, which creates TEMP `card_tx` and `defects(class, customer_id, evidence)`.
  - `select_cohort(con, per_class: int) -> dict`. It needs `profile`, `persona_ids` and `defects`, creates TEMP `cohort(customer_id)`, and returns `{"customers_selected", "classes", "customers"}`.
  - `lost_defects(con, customers: dict) -> list[str]`.

- [ ] **Step 1: Write the persona file**

Create `data_load/personas.json`:

```json
{
  "as_of": "2026-06-17T23:59:59",
  "spec": "docs/superpowers/specs/2026-10-03-curate-stage-design.md, section 6.4",
  "personas": {
    "P01": {
      "customer_id": "CLI-1GL7QBDG3QG0",
      "use_case": "Decline explained",
      "expected_outcome": "exit 1: explain the code's meaning from the record; no cause guessed",
      "evidence": ["TRX-SSJAIUCVVU1L4605ZLNM", "PRD-GKI6NTZU2AEX"]
    },
    "P02": {
      "customer_id": "CLI-7EC6UCDZMSKV",
      "use_case": "Pending charge",
      "expected_outcome": "exit 1: explain that the charge is pending",
      "evidence": ["TRX-M8SV89D2QGIE6WRUB79K", "PRD-1CF5T9HNCQ1X"]
    },
    "P03": {
      "customer_id": "CLI-70U0WJ1NH1MN",
      "use_case": "Reversed charge with app context",
      "expected_outcome": "exit 1: explain the reversal; session opens with the app signal",
      "evidence": ["TRX-LJGEBUAOX0G4CL4RQSIU", "PRD-UUY4Z9TDEF96"]
    },
    "P04": {
      "customer_id": "CLI-N4FPJIEGD917",
      "use_case": "Which card?",
      "expected_outcome": "clarify which card before anything else",
      "evidence": ["TRX-19B2TR7A8QXK7243KZV6", "TRX-9TDT782N9PARVY8IMPRE", "PRD-TVC3HHMH0II0", "PRD-VLRZ7201XLV1"]
    },
    "P05": {
      "customer_id": "CLI-50OIF5EIYSWK",
      "use_case": "Portuguese persona, foreign charge",
      "expected_outcome": "answer in Portuguese; explain the charge in Brazil",
      "evidence": ["TRX-MQKFELIPWT098DXTN2WN", "TRX-YLR3CXW0CFHFUNT2IUWZ", "PRD-MTDX0544YHDL"]
    },
    "P06": {
      "customer_id": "CLI-PV0OIEA8DAAE",
      "use_case": "Limit increase (out of scope)",
      "expected_outcome": "abstain and offer a human; read-only servicing facts allowed",
      "evidence": ["PRD-QM9G50SHLSY4"]
    },
    "P07": {
      "customer_id": "CLI-EX6BOAOEFZHQ",
      "use_case": "Suspected fraud",
      "expected_outcome": "exit 2 then 3: confirm, block card 4497, read back, dispute intake",
      "evidence": ["TRX-23BIJAU4GL46ATPW9STY", "PRD-Z3Y8BK8CKUTN"]
    },
    "P08": {
      "customer_id": "CLI-GG3Z1440277M",
      "use_case": "Open unrecognized-charge case",
      "expected_outcome": "exit 3: follow up the open case, no duplicate; hand-off",
      "evidence": ["CMP-FHCLR8TGWMBD0YFOCLYS", "TRX-OW0S5SQC8JI9MJDLTKU1"]
    },
    "P09": {
      "customer_id": "CLI-UBR2NCZWTD4K",
      "use_case": "Records contradict",
      "expected_outcome": "say the records don't match (code 54 on a valid card); offer a hand-off",
      "evidence": ["TRX-RX1ENVJQ5J26GXX7T8F7", "PRD-0Z61E1KSEEMC"]
    },
    "P10": {
      "customer_id": "CLI-Z3V3SBS18YWQ",
      "use_case": "Card not active",
      "expected_outcome": "state the Blocked status only (no reason in the data); offer a human",
      "evidence": ["PRD-AK4W4IPVS8N8"]
    }
  },
  "alternates": {
    "P01": "CLI-S2QIJKEZV442",
    "P07": "CLI-HTX9ITCO0IMR"
  }
}
```

- [ ] **Step 2: Write the failing selection tests**

Create `tests/unit/test_data_load_curate_select.py`:

```python
"""Gates, score, balanced selection, personas and the defect cohort (curate spec 6 and 7)."""

from datetime import date, datetime
from hashlib import md5

import pytest
from curate_fixtures import DEBIT, add, bank, card, charge, customer, good

from data_load.curate_rules import CurationError
from data_load.curate_select import (
    GATES,
    build_profile,
    defect_evidence,
    load_personas,
    lost_defects,
    register_personas,
    select_clean,
    select_cohort,
)


def gates(con, cid: str) -> dict[str, bool]:
    row = con.execute(
        f"SELECT {', '.join(GATES)} FROM profile WHERE customer_id = ?", [cid]
    )
    return dict(zip(GATES, row.fetchone()))


def failing_gates(con, cid: str) -> list[str]:
    return [g for g, ok in gates(con, cid).items() if not ok]


def no_cohort(con) -> None:
    con.execute("CREATE OR REPLACE TEMP TABLE cohort (customer_id VARCHAR)")


@pytest.mark.unit
def test_a_good_customer_passes_every_gate():
    con = bank()
    good(con, "C1")
    build_profile(con)
    assert failing_gates(con, "C1") == []


def break_g1(con):
    good(con, "X", customer_status="Closed")


def break_g2(con):  # 17 at registration
    good(
        con, "X", date_of_birth=date(2003, 6, 2), registration_date=datetime(2020, 6, 1)
    )


def break_g3(con):
    good(con, "X", email=None)


def break_g4(con):  # "Sergio" is a male name and "Carolina" a female one
    customer(con, "M1", first_name="Sergio", gender="M")
    customer(con, "F1", first_name="Carolina", gender="F")
    good(con, "X", first_name="Sergio Carolina", gender="O")


def break_g5(con):  # a usable debit card, but no usable credit card
    customer(con, "X")
    card(con, "PX", "X", product_type=DEBIT, credit_limit=None)
    charge(con, "TX", "PX", "X")


def break_g6(con):  # a second Active credit card with no expiry
    good(con, "X")
    card(con, "PX2", "X", expiration_date=None)


def break_g7(con):  # a second Active card past its expiry
    good(con, "X")
    card(con, "PX2", "X", expiration_date=date(2025, 1, 1))


def break_g8(con):  # the only charge is 47 days old
    customer(con, "X")
    card(con, "PX", "X")
    charge(con, "TX", "PX", "X", process_date=date(2026, 5, 1))


@pytest.mark.unit
@pytest.mark.parametrize(
    "gate, breaker",
    [
        ("g1", break_g1),
        ("g2", break_g2),
        ("g3", break_g3),
        ("g4", break_g4),
        ("g5", break_g5),
        ("g6", break_g6),
        ("g7", break_g7),
        ("g8", break_g8),
    ],
)
def test_each_gate_fails_on_its_own_defect(gate, breaker):
    con = bank()
    breaker(con)
    build_profile(con)
    assert failing_gates(con, "X") == [gate]


@pytest.mark.unit
def test_selection_takes_personas_first_then_scores_and_reports_short_cells():
    con = bank()
    good(con, "LOW")  # the persona: one charge, the lowest score
    for cid in ("HIGH", "MID"):
        good(con, cid)
        charge(con, f"T2-{cid}", f"P-{cid}", cid)  # a second charge: higher score
    charge(
        con,
        "T3-HIGH",
        "P-HIGH",
        "HIGH",
        transaction_status="Declined",
        response_code="51",
    )  # a recent decline: higher still
    good(con, "ARG", country="Argentina")  # alone in its cell
    good(con, "BAD", customer_status="Closed")
    good(con, "MXP", country="México", segment="Plus", email=None)  # no one eligible
    personas = {"P01": {"customer_id": "LOW"}}
    register_personas(con, personas)
    build_profile(con)
    no_cohort(con)
    record = select_clean(con, personas, per_cell=2)
    chosen = dict(con.execute("SELECT customer_id, cell FROM clean").fetchall())
    assert chosen == {
        "LOW": "Colombia|Basic",
        "HIGH": "Colombia|Basic",
        "ARG": "Argentina|Basic",
    }
    assert record["customers"] == 3
    assert record["cells"]["Colombia|Basic"] == {"eligible": 3, "selected": 2}
    assert record["cells"]["Argentina|Basic"] == {
        "eligible": 1,
        "selected": 1,
        "short": 1,
    }
    assert record["cells"]["México|Plus"] == {"eligible": 0, "selected": 0, "short": 2}
    assert record["funnel"]["G1"] == 5 and record["funnel"]["G8"] == 4
    assert record["personas"] == {"P01": "LOW"}


@pytest.mark.unit
def test_equal_scores_break_ties_on_md5_so_the_selection_repeats():
    con = bank()
    for cid in ("A1", "B2", "C3"):
        good(con, cid)
    register_personas(con, {})
    build_profile(con)
    no_cohort(con)
    select_clean(con, {}, per_cell=1)
    first = con.execute("SELECT customer_id FROM clean").fetchall()
    select_clean(con, {}, per_cell=1)
    assert con.execute("SELECT customer_id FROM clean").fetchall() == first
    assert first == [
        (min(("A1", "B2", "C3"), key=lambda c: md5(c.encode()).hexdigest()),)
    ]


@pytest.mark.unit
def test_a_persona_that_fails_a_gate_fails_the_stage_naming_it():
    con = bank()
    good(con, "C1", email=None)
    personas = {"P07": {"customer_id": "C1"}, "P08": {"customer_id": "NOPE"}}
    register_personas(con, personas)
    build_profile(con)
    no_cohort(con)
    with pytest.raises(CurationError, match="P07 C1 fails G3; P08 NOPE fails missing"):
        select_clean(con, personas, per_cell=1)


@pytest.mark.unit
def test_the_shipped_persona_file_pins_ten_customers():
    personas = load_personas()
    assert sorted(personas) == [f"P{n:02d}" for n in range(1, 11)]
    assert all(
        p["customer_id"].startswith("CLI-") and p["evidence"] for p in personas.values()
    )


@pytest.mark.unit
def test_cohort_fills_the_rarest_class_first_and_counts_overlaps():
    con = bank()
    good(con, "X", email=None)  # K17 (missing email) ...
    con.execute(
        "UPDATE transactions SET transaction_country = 'Mexico' WHERE customer_id = 'X'"
    )
    good(con, "Y", mobile_phone=None)  # K17 only
    good(con, "Z", email=None)  # K17 only
    good(con, "P", email=None)  # a persona is never in the cohort
    register_personas(con, {"P01": {"customer_id": "P"}})
    build_profile(con)
    defect_evidence(con)
    record = select_cohort(con, per_class=1)
    assert con.execute("SELECT customer_id FROM cohort").fetchall() == [("X",)]
    assert record["classes"]["K09"] == {
        "candidates": 1,
        "selected": 1,
    }  # rarest: filled first
    assert record["classes"]["K17"] == {
        "candidates": 3,
        "selected": 1,
    }  # X already covers it
    assert record["classes"]["K07"] == {"candidates": 0, "selected": 0, "short": 1}
    assert record["customers"] == {"X": {"K09": ["T-X"], "K17": ["X"]}}


@pytest.mark.unit
def test_lost_defects_names_a_cohort_defect_that_the_tables_no_longer_show():
    con = bank()
    good(con, "X")
    con.execute("UPDATE transactions SET transaction_country = 'Mexico'")
    register_personas(con, {})
    build_profile(con)
    defect_evidence(con)
    record = select_cohort(con, per_class=1)
    assert lost_defects(con, record["customers"]) == []
    con.execute("UPDATE transactions SET transaction_country = 'México'")
    assert lost_defects(con, record["customers"]) == ["X K09"]


@pytest.mark.unit
def test_profile_counts_scenarios_on_usable_cards_and_the_session_windows():
    con = bank()
    good(con, "C1")
    charge(
        con,
        "T2",
        "P-C1",
        "C1",
        transaction_status="Pending",
        process_date=date(2026, 6, 12),
    )
    charge(con, "T3", "P-C1", "C1", transaction_status="Approved", fraud_score=62)
    add(
        con,
        "digital_events",
        event_id="E1",
        customer_id="C1",
        event_date=datetime(2026, 6, 17, 10),
        process_date=date(2026, 6, 17),
    )
    add(
        con,
        "complaints",
        complaint_id="K1",
        customer_id="C1",
        status="In Process",
        subcategory="Cargo no reconocido",
        creation_date=datetime(2026, 6, 8),
    )
    build_profile(con)
    row = con.execute(
        "SELECT tx30, pending7, fraud30, app24, open_unrecognized, score FROM profile"
    ).fetchone()
    # score = 3*3 tx + 2 pending + 3 fraud + 2 open case + 1 app event
    assert row == (3, 1, 1, 1, 1, 17)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_curate_select.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'data_load.curate_select'`.

- [ ] **Step 4: Write the selection module**

Create `data_load/curate_select.py`:

```python
"""Who is served and tested: gates, score, balanced selection, personas, defect cohort.

Spec: docs/superpowers/specs/2026-10-03-curate-stage-design.md, sections 6 and 7. Every
function reads the tables as they are now: before the C-rules for the defect cohort, after
them for the clean selection. Ties break on md5(customer_id), so a run is reproducible.
"""

import json
from pathlib import Path

from data_load.curate_rules import AS_OF, AS_OF_DATE, CARD_TYPES, HOME, CurationError
from data_load.repair import _count

PERSONAS = Path(__file__).with_name("personas.json")
GATES = ("g1", "g2", "g3", "g4", "g5", "g6", "g7", "g8")
ELIGIBLE = " AND ".join(GATES)
# Richness score (spec 6.2): ranks customers within a cell; it decides no eligibility
SCORE = (
    "3 * least(tx30, 5) + 2 * (decline7 > 0)::INT + 2 * (pending7 > 0)::INT "
    "+ 2 * (reversed30 > 0)::INT + 3 * (fraud30 > 0)::INT + 2 * (open_unrecognized > 0)::INT "
    "+ (code54_30 > 0)::INT + (foreign30 > 0)::INT + (app24 > 0)::INT + (calls90 > 0)::INT "
    "+ two_usable_cards + (inactive_credit > 0)::INT + (past_due > 0)::INT"
)
# Informational scenario counts over the selection (profile columns)
SCENARIOS = (
    "decline7",
    "pending7",
    "reversed30",
    "fraud30",
    "code54_30",
    "foreign30",
    "open_unrecognized",
    "app24",
    "two_usable_cards",
    "inactive_credit",
    "past_due",
)


def load_personas(path: Path = PERSONAS) -> dict[str, dict]:
    """P01..P10 -> {customer_id, use_case, expected_outcome, evidence}."""
    return json.loads(path.read_text(encoding="utf-8"))["personas"]


def register_personas(con, personas: dict[str, dict]) -> None:
    ids = [p["customer_id"] for p in personas.values()]
    con.execute(
        "CREATE OR REPLACE TEMP TABLE persona_ids AS "
        "SELECT unnest($1::VARCHAR[]) AS customer_id",
        [ids],
    )


def build_profile(con) -> None:
    """TEMP TABLE profile: one row per customer with gates g1-g8, scenario counts and score."""
    con.execute(
        f"""CREATE OR REPLACE TEMP TABLE cards AS SELECT p.*, coalesce(
          p.product_status = 'Active' AND p.expiration_date >= {AS_OF_DATE}
          AND (p.product_type = 'Tarjeta Débito'
               OR (p.credit_limit IS NOT NULL AND p.current_balance <= p.credit_limit)),
          false) AS usable
        FROM products p WHERE p.product_type IN {CARD_TYPES}"""
    )
    # card transactions of the last 30 days, the score's widest transaction window
    con.execute(
        f"""CREATE OR REPLACE TEMP TABLE card_tx30 AS
        SELECT t.*, c.usable, t.process_date > {AS_OF_DATE} - 7 AS d7
        FROM transactions t JOIN cards c USING (product_id)
        WHERE t.process_date > {AS_OF_DATE} - 30 AND t.process_date <= {AS_OF_DATE}"""
    )
    con.execute(
        f"""CREATE OR REPLACE TEMP TABLE profile AS SELECT *, {SCORE} AS score FROM (
        WITH names AS (  -- first names that only one gender (M/F) uses
          SELECT string_split(first_name, ' ')[1] AS name, min(gender) AS gender
          FROM customers WHERE gender IN ('M', 'F') GROUP BY 1
          HAVING count(DISTINCT gender) = 1),
        cc AS (SELECT customer_id,
          count(*) FILTER (WHERE usable AND product_type = 'Tarjeta Crédito') AS usable_credit,
          count(*) FILTER (WHERE usable) AS usable_cards,
          count(*) FILTER (WHERE product_status = 'Active' AND (expiration_date IS NULL
            OR (product_type = 'Tarjeta Crédito' AND credit_limit IS NULL))) AS incomplete,
          count(*) FILTER (WHERE product_status = 'Active'
            AND expiration_date < {AS_OF_DATE}) AS expired_active,
          count(*) FILTER (WHERE product_type = 'Tarjeta Crédito'
            AND product_status IN ('Blocked', 'Suspended')) AS inactive_credit,
          count(*) FILTER (WHERE usable AND product_type = 'Tarjeta Crédito'
            AND days_past_due > 0) AS past_due
          FROM cards GROUP BY 1),
        tx AS (SELECT t.customer_id,
          count(*) FILTER (WHERE usable) AS tx30,
          count(*) FILTER (WHERE usable AND d7 AND transaction_status = 'Declined'
            AND response_code IN ('05', '14', '51')) AS decline7,
          count(*) FILTER (WHERE usable AND d7 AND transaction_status = 'Pending') AS pending7,
          count(*) FILTER (WHERE usable AND transaction_status = 'Reversed') AS reversed30,
          count(*) FILTER (WHERE usable AND transaction_status = 'Approved'
            AND fraud_score > 30) AS fraud30,
          count(*) FILTER (WHERE usable AND transaction_status = 'Declined'
            AND response_code = '54') AS code54_30,
          count(*) FILTER (WHERE usable AND lower(strip_accents(t.transaction_country))
            <> lower(strip_accents(h.country))) AS foreign30
          FROM card_tx30 t JOIN customers h USING (customer_id) GROUP BY 1),
        k AS (SELECT customer_id, count(*) AS open_unrecognized FROM complaints
          WHERE subcategory = 'Cargo no reconocido' AND creation_date <= {AS_OF}
            AND (closing_date IS NULL OR closing_date > {AS_OF})
            AND status NOT IN ('Resolved', 'Closed', 'Rejected') GROUP BY 1),
        e AS (SELECT customer_id, count(*) AS app24 FROM digital_events
          WHERE customer_id IS NOT NULL AND process_date >= {AS_OF_DATE} - 1
            AND event_date > {AS_OF} - INTERVAL 24 HOUR AND event_date <= {AS_OF}
          GROUP BY 1),
        i AS (SELECT customer_id, count(*) AS calls90 FROM call_center_interactions
          WHERE process_date > {AS_OF_DATE} - 90 AND process_date <= {AS_OF_DATE}
          GROUP BY 1)
        SELECT c.customer_id, c.country || '|' || c.segment AS cell,
          c.customer_status = 'Active' AS g1,
          coalesce(c.date_of_birth + INTERVAL 18 YEAR <= c.registration_date, false) AS g2,
          c.email IS NOT NULL AND c.mobile_phone IS NOT NULL AS g3,
          NOT coalesce(string_split(c.first_name, ' ')[1] = string_split(c.first_name, ' ')[2]
                       OR a.gender <> b.gender, false) AS g4,
          coalesce(cc.usable_credit, 0) >= 1 AS g5,
          coalesce(cc.incomplete, 0) = 0 AS g6,
          coalesce(cc.expired_active, 0) = 0 AS g7,
          coalesce(tx.tx30, 0) >= 1 AS g8,
          coalesce(tx.tx30, 0) AS tx30, coalesce(decline7, 0) AS decline7,
          coalesce(pending7, 0) AS pending7, coalesce(reversed30, 0) AS reversed30,
          coalesce(fraud30, 0) AS fraud30, coalesce(code54_30, 0) AS code54_30,
          coalesce(foreign30, 0) AS foreign30,
          coalesce(open_unrecognized, 0) AS open_unrecognized, coalesce(app24, 0) AS app24,
          coalesce(calls90, 0) AS calls90,
          (coalesce(usable_cards, 0) >= 2)::INT AS two_usable_cards,
          coalesce(inactive_credit, 0) AS inactive_credit, coalesce(past_due, 0) AS past_due
        FROM customers c
        LEFT JOIN names a ON a.name = string_split(c.first_name, ' ')[1]
        LEFT JOIN names b ON b.name = string_split(c.first_name, ' ')[2]
        LEFT JOIN cc USING (customer_id) LEFT JOIN tx USING (customer_id)
        LEFT JOIN k USING (customer_id) LEFT JOIN e USING (customer_id)
        LEFT JOIN i USING (customer_id))"""
    )


def select_clean(con, personas: dict[str, dict], per_cell: int) -> dict:
    """TEMP TABLE clean: personas first, then per_cell customers per country|segment cell
    by score, from those passing every gate and outside the `cohort` table."""
    failures = []
    for pid, persona in sorted(personas.items()):
        row = con.execute(
            f"SELECT {', '.join(GATES)} FROM profile WHERE customer_id = ?",
            [persona["customer_id"]],
        ).fetchone()
        failed = (
            ["missing"]
            if row is None
            else [g.upper() for g, ok in zip(GATES, row) if not ok]
        )
        if failed:
            failures.append(f"{pid} {persona['customer_id']} fails {', '.join(failed)}")
    if failures:
        raise CurationError("personas fail the gates: " + "; ".join(failures))
    con.execute(
        f"""CREATE OR REPLACE TEMP TABLE clean AS SELECT customer_id, cell FROM (
          SELECT customer_id, cell, row_number() OVER (PARTITION BY cell ORDER BY
            customer_id IN (SELECT customer_id FROM persona_ids) DESC,
            score DESC, md5(customer_id)) AS rank
          FROM profile WHERE {ELIGIBLE}
            AND customer_id NOT IN (SELECT customer_id FROM cohort))
        WHERE rank <= {per_cell}"""
    )
    funnel, passed = {}, []
    for gate in GATES:
        passed.append(gate)
        funnel[gate.upper()] = _count(
            con, f"SELECT count(*) FROM profile WHERE {' AND '.join(passed)}"
        )
    cells = {}
    for cell, eligible, selected in con.execute(
        f"""SELECT p.cell, count(*) FILTER (WHERE {ELIGIBLE}
          AND p.customer_id NOT IN (SELECT customer_id FROM cohort)),
          count(c.customer_id)
        FROM profile p LEFT JOIN clean c USING (customer_id) GROUP BY 1 ORDER BY 1"""
    ).fetchall():
        cells[cell] = {"eligible": eligible, "selected": selected}
        if selected < per_cell:
            cells[cell]["short"] = per_cell - selected
    sums = con.execute(
        "SELECT "
        + ", ".join(f"count(*) FILTER (WHERE {s} > 0)" for s in SCENARIOS)
        + " FROM profile WHERE customer_id IN (SELECT customer_id FROM clean)"
    ).fetchone()
    return {
        "customers": _count(con, "SELECT count(*) FROM clean"),
        "funnel": funnel,
        "cells": cells,
        "personas": {pid: p["customer_id"] for pid, p in sorted(personas.items())},
        "scenarios": dict(zip(SCENARIOS, sums)),
    }


# Defect classes (spec 7.1): SQL returning (customer_id, evidence) on the tables as they are now.
# card_tx: every card transaction up to as_of, with its card's status and expiry.
CLASSES = {
    "K01": "SELECT customer_id, customer_id AS evidence FROM customers "
    "WHERE customer_status <> 'Active'",
    "K02": "SELECT customer_id, transaction_id FROM card_tx WHERE d30 "
    "AND product_status = 'Active' AND transaction_status = 'Approved' "
    "AND transaction_date::DATE > expiration_date",
    "K03": "SELECT customer_id, product_id FROM products WHERE product_type = 'Tarjeta Crédito' "
    "AND product_status = 'Active' AND (credit_limit IS NULL OR expiration_date IS NULL)",
    "K04": "SELECT customer_id, product_id FROM products WHERE product_type = 'Tarjeta Crédito' "
    "AND product_status = 'Active' AND current_balance > credit_limit",
    "K05": "SELECT customer_id, transaction_id FROM card_tx WHERE transaction_status = 'Pending' "
    f"AND process_date <= {AS_OF_DATE} - 30",
    "K06": "SELECT customer_id, transaction_id FROM card_tx WHERE d30 "
    "AND transaction_status IN ('Pending', 'Reversed') AND response_code IS NOT NULL",
    "K07": "SELECT customer_id, transaction_id FROM card_tx WHERE d30 "
    "AND transaction_status = 'Declined' AND response_code = '54' "
    "AND expiration_date >= transaction_date::DATE",
    "K08": "SELECT customer_id, transaction_id FROM card_tx WHERE d30 "
    "AND transaction_status IN ('Declined', 'Approved') AND response_code IS NULL",
    "K09": "SELECT customer_id, transaction_id FROM card_tx WHERE d30 "
    "AND transaction_country = 'Mexico'",
    "K10": "SELECT customer_id, transaction_id FROM card_tx WHERE d30 "
    "AND amount_usd IS NULL AND currency IN ('ARS', 'COP')",
    "K11": "SELECT customer_id, transaction_id FROM card_tx WHERE d30 "
    "AND transaction_type = 'Purchase' AND (merchant_name IS NULL OR merchant_category IS NULL)",
    "K12": "SELECT customer_id, complaint_id FROM complaints WHERE closing_date IS NULL "
    "AND status IN ('Open', 'In Process', 'Escalated') "
    f"AND creation_date < {AS_OF} - INTERVAL 60 DAY",
    "K13": "SELECT customer_id, complaint_id FROM complaints "
    "WHERE status = 'Resolved' AND closing_date IS NULL",
    "K14": "SELECT k.customer_id, k.complaint_id FROM complaints k "
    "JOIN customers c USING (customer_id) "
    f"WHERE k.claimed_amount IS NOT NULL AND k.currency IS DISTINCT FROM {HOME}",
    "K15": "SELECT customer_id, complaint_id FROM complaints WHERE greatest(assignment_date, "
    f"first_response_date, resolution_date, closing_date) > {AS_OF} "
    f"UNION ALL SELECT customer_id, customer_id FROM customers WHERE last_updated > {AS_OF}",
    "K16": "SELECT customer_id, customer_id FROM customers "
    "WHERE date_of_birth + INTERVAL 18 YEAR > registration_date",
    "K17": "SELECT customer_id, customer_id FROM customers "
    "WHERE email IS NULL OR mobile_phone IS NULL",
}


def defect_evidence(con) -> None:
    """TEMP TABLE defects(class, customer_id, evidence) for the tables as they are now."""
    con.execute(
        f"""CREATE OR REPLACE TEMP TABLE card_tx AS
        SELECT t.*, p.product_status, p.expiration_date,
               t.process_date > {AS_OF_DATE} - 30 AS d30
        FROM transactions t JOIN products p USING (product_id)
        WHERE p.product_type IN {CARD_TYPES} AND t.process_date <= {AS_OF_DATE}"""
    )
    con.execute(
        "CREATE OR REPLACE TEMP TABLE defects AS "
        + " UNION ALL ".join(
            f"SELECT '{k}' AS class, q.* FROM ({sql}) q(customer_id, evidence)"
            for k, sql in CLASSES.items()
        )
    )


def select_cohort(con, per_class: int) -> dict:
    """TEMP TABLE cohort: per_class customers per defect class, rarest class first, from
    customers with a card transaction in the last 30 days, never personas."""
    con.execute(
        """CREATE OR REPLACE TEMP TABLE defect_candidates AS
        SELECT DISTINCT customer_id FROM card_tx WHERE d30
        EXCEPT SELECT customer_id FROM persona_ids"""
    )
    candidates = dict(
        con.execute(
            "SELECT class, count(DISTINCT customer_id) FROM defects "
            "WHERE customer_id IN (SELECT customer_id FROM defect_candidates) GROUP BY 1"
        ).fetchall()
    )
    con.execute("CREATE OR REPLACE TEMP TABLE cohort (customer_id VARCHAR)")
    for k in sorted(CLASSES, key=lambda k: (candidates.get(k, 0), k)):
        have = _count(
            con,
            f"SELECT count(DISTINCT customer_id) FROM defects WHERE class = '{k}' "
            "AND customer_id IN (SELECT customer_id FROM cohort)",
        )
        if have < per_class:
            con.execute(
                f"""INSERT INTO cohort SELECT customer_id FROM (
                  SELECT DISTINCT d.customer_id, p.score FROM defects d
                  JOIN profile p USING (customer_id)
                  WHERE d.class = '{k}'
                    AND d.customer_id IN (SELECT customer_id FROM defect_candidates)
                    AND d.customer_id NOT IN (SELECT customer_id FROM cohort))
                ORDER BY score DESC, md5(customer_id) LIMIT {per_class - have}"""
            )
    classes = {}
    for k in CLASSES:
        selected = _count(
            con,
            f"SELECT count(DISTINCT customer_id) FROM defects WHERE class = '{k}' "
            "AND customer_id IN (SELECT customer_id FROM cohort)",
        )
        classes[k] = {"candidates": candidates.get(k, 0), "selected": selected}
        if selected < per_class:
            classes[k]["short"] = per_class - selected
    customers: dict[str, dict[str, list[str]]] = {}
    for cid, k, evidence in con.execute(
        """SELECT customer_id, class, list(DISTINCT evidence ORDER BY evidence)
        FROM defects WHERE customer_id IN (SELECT customer_id FROM cohort)
        GROUP BY 1, 2 ORDER BY 1, 2"""
    ).fetchall():
        customers.setdefault(cid, {})[k] = evidence
    return {
        "customers_selected": len(customers),
        "classes": classes,
        "customers": customers,
    }


def lost_defects(con, customers: dict[str, dict[str, list[str]]]) -> list[str]:
    """(customer class) pairs recorded for the cohort that the tables no longer show."""
    defect_evidence(con)
    have = set(
        con.execute(
            "SELECT DISTINCT customer_id, class FROM defects "
            "WHERE customer_id IN (SELECT customer_id FROM cohort)"
        ).fetchall()
    )
    return [
        f"{cid} {k}"
        for cid, ks in customers.items()
        for k in ks
        if (cid, k) not in have
    ]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_curate_select.py tests/unit/test_data_load_curate_rules.py -q`
Expected: `26 passed`.

- [ ] **Step 6: Lint and commit**

```bash
uv run --no-project --quiet --with ruff ruff format data_load/curate_select.py tests/unit/test_data_load_curate_select.py
uv run --no-project --quiet --with ruff ruff check data_load/curate_select.py tests/unit/test_data_load_curate_select.py
git add data_load/personas.json data_load/curate_select.py tests/unit/test_data_load_curate_select.py
git commit -m "feat(curate): gates, score, balanced selection, personas and defect cohort"
```

---

### Task 3: The curate stage

**Files:**
- Create: `data_load/curate.py`
- Modify: `tests/unit/curate_fixtures.py` (add `PERSONAS` and `world()`)
- Test: `tests/unit/test_data_load_curate.py`

**Interfaces:**
- Consumes:
  - Task 1: `curate_rules.check_evidence`, `apply_rules`, `check_invariants`, `RULES`, `CurationError`.
  - Task 2: `curate_select.load_personas`, `register_personas`, `build_profile`, `defect_evidence`, `select_cohort`, `select_clean`, `lost_defects`, `ELIGIBLE`.
  - Existing: `repair.check_links`, `repair.LinkError`; `transform.Table`, `transform._write(con, out_dir, name, rows) -> Table`, `transform.sha256_file`; `ddl.load_plan()`.
- Produces:
  - `download_clean(s3, bucket: str, staged: dict, dest: Path) -> None`. `staged` is `transform.json["tables"]`.
  - `curate(source: str, out_dir: Path, *, customers=1500, per_class=20, personas=None, expected=None) -> tuple[list[Table], dict]`. The record keys are `as_of, rules, selection, defects`; the CLI adds `run_id` and `tables`.

- [ ] **Step 1: Add the shared world to the fixtures**

In `tests/unit/curate_fixtures.py`, add this line directly below `CREDIT, DEBIT = ...`:

```python
PERSONAS = {"P01": {"customer_id": "PER"}}  # the persona world() builds
```

and append at the end of the file:

```python
def world(folder: Path) -> Path:
    """A persona, two clean candidates in the persona's cell and one defect customer."""
    con = bank()
    good(con, "PER")
    charge(con, "T-PER-MX", "P-PER", "PER", transaction_country="Mexico")  # C1 fixes it
    good(con, "OK1")
    good(con, "OK2", country="Argentina")
    good(con, "DEF", email=None)  # K17
    charge(
        con, "T-DEF-MX", "P-DEF", "DEF", transaction_country="Mexico"
    )  # K09, kept raw
    customer(
        con, "GONE", customer_status="Closed"
    )  # no card activity: neither clean nor cohort
    add(
        con,
        "call_center_interactions",
        interaction_id="I1",
        customer_id="PER",
        process_date=date(2026, 6, 1),
    )
    add(
        con,
        "call_center_interactions",
        interaction_id="I2",
        customer_id="GONE",
        process_date=date(2026, 6, 1),
    )
    add(
        con,
        "call_transcripts",
        transcript_id="R1",
        interaction_id="I1",
        customer_id="PER",
    )
    add(
        con,
        "call_transcripts",
        transcript_id="R2",
        interaction_id="I2",
        customer_id="GONE",
    )
    add(
        con,
        "digital_events",
        event_id="E1",
        customer_id="PER",
        event_date=datetime(2026, 6, 17, 9),
        process_date=date(2026, 6, 17),
    )
    add(
        con,
        "digital_events",
        event_id="E2",
        customer_id=None,
        event_date=datetime(2026, 6, 17, 9),
        process_date=date(2026, 6, 17),
    )
    add(con, "branches", branch_id="B1")
    to_parquet(con, folder)
    return folder
```

- [ ] **Step 2: Write the failing stage tests**

Create `tests/unit/test_data_load_curate.py`:

```python
"""The curate stage end to end on tiny Parquet tables (curate spec sections 4 and 8)."""

import duckdb
import pytest
from curate_fixtures import PERSONAS, world
from data_load_s3 import FakeS3

from data_load.curate import curate, download_clean
from data_load.curate_rules import CurationError
from data_load.transform import sha256_file


def read(path, sql):
    return duckdb.sql(sql.replace("{t}", f"'{path.as_posix()}'")).fetchall()


@pytest.mark.unit
def test_curate_writes_clean_customers_fixed_and_the_cohort_as_delivered(tmp_path):
    source = world(tmp_path / "clean")
    written, record = curate(
        source.as_posix(),
        tmp_path / "out",
        customers=12,
        per_class=1,
        personas=PERSONAS,
    )
    files = {t.name: t for t in written}
    assert set(files) == {
        "customers",
        "service_agents",
        "products",
        "branches",
        "marketing_campaigns",
        "transactions",
        "call_center_interactions",
        "call_transcripts",
        "satisfaction_surveys",
        "digital_events",
        "complaints",
        "campaign_sends",
    }
    customers = read(files["customers"].path, "SELECT customer_id FROM {t} ORDER BY 1")
    # one per cell: the persona wins its cell, OK2 is alone in Argentina, DEF is the cohort
    assert customers == [("DEF",), ("OK2",), ("PER",)]
    countries = dict(
        read(
            files["transactions"].path,
            "SELECT transaction_id, transaction_country FROM {t}",
        )
    )
    assert countries["T-PER-MX"] == "México"  # clean: C1 applied
    assert countries["T-DEF-MX"] == "Mexico"  # cohort: kept as transform wrote it
    assert read(files["call_transcripts"].path, "SELECT transcript_id FROM {t}") == [
        ("R1",)
    ]
    assert read(files["digital_events"].path, "SELECT event_id FROM {t}") == [("E1",)]
    assert read(files["branches"].path, "SELECT count(*) FROM {t}") == [(1,)]
    assert record["selection"]["customers"] == 2
    assert record["selection"]["personas"] == {"P01": "PER"}
    assert record["defects"]["customers"]["DEF"] == {
        "K09": ["T-DEF-MX"],
        "K17": ["DEF"],
    }
    assert record["rules"]["C1"] == {"changed": 2}  # rules count every row
    assert files["customers"].sha256 == sha256_file(files["customers"].path)


@pytest.mark.unit
@pytest.mark.parametrize("customers", [0, 100])
def test_customer_counts_must_fill_the_12_cells_evenly(tmp_path, customers):
    with pytest.raises(CurationError, match="positive multiple of 12"):
        curate(str(tmp_path), tmp_path / "out", customers=customers, personas=PERSONAS)


@pytest.mark.unit
def test_full_runs_must_match_the_pinned_curation_counts(tmp_path):
    source = world(tmp_path / "clean")
    rows_in = {
        "branches": 1,
        "service_agents": 0,
        "marketing_campaigns": 0,
        "customers": 5,
        "products": 4,
        "transactions": 6,
        "call_center_interactions": 2,
        "call_transcripts": 2,
        "satisfaction_surveys": 0,
        "digital_events": 2,
        "complaints": 0,
        "campaign_sends": 0,
    }
    expected = {"rows": rows_in, "curation": {"rules": {}, "rows": {}}}
    with pytest.raises(CurationError, match="differs from expected.json curation"):
        curate(
            source.as_posix(), tmp_path / "out", personas=PERSONAS, expected=expected
        )


@pytest.mark.unit
def test_a_clean_customer_breaking_a_rule_fails_the_stage(tmp_path, monkeypatch):
    source = world(tmp_path / "clean")
    from data_load import curate_rules

    def without_c1(con):
        return {rule: fix(con) for rule, _, fix in curate_rules.RULES if rule != "C1"}

    monkeypatch.setattr("data_load.curate_rules.apply_rules", without_c1)
    with pytest.raises(CurationError, match="C1: 1 rows of clean customers break it"):
        curate(
            source.as_posix(),
            tmp_path / "out",
            customers=12,
            per_class=1,
            personas=PERSONAS,
        )


@pytest.mark.unit
def test_download_clean_rejects_a_file_that_differs_from_transform_json(tmp_path):
    s3 = FakeS3({("team", "clean/run-1/branches.parquet"): b"parquet"})
    staged = {
        "branches": {
            "uri": "s3://team/clean/run-1/branches.parquet",
            "sha256": "0" * 64,
        }
    }
    with pytest.raises(CurationError, match="branches: Parquet differs"):
        download_clean(s3, "team", staged, tmp_path)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_curate.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'data_load.curate'`.

- [ ] **Step 4: Write the stage module**

Create `data_load/curate.py`:

```python
"""Stage curate: clean/ Parquet -> curated/ Parquet (curate spec, section 4).

The C-rules fix every row, then the selection keeps ~1,500 coherent customers plus a
defect cohort whose rows are written as transform left them (snapshotted before the rules).
Nothing reaches S3 or DSQL unless every check passes.
"""

from pathlib import Path

import duckdb

from data_load import curate_rules, curate_select, repair
from data_load.curate_rules import CurationError
from data_load.ddl import load_plan
from data_load.repair import _count
from data_load.transform import Table, _write, sha256_file

AS_OF = "2026-06-17T23:59:59"
RULE_TABLES = (
    "customers",
    "products",
    "transactions",
    "complaints",
)  # what C1-C12 change
LINKED = (  # filtered by customer_id; anonymous digital events go too
    "customers",
    "products",
    "transactions",
    "complaints",
    "call_center_interactions",
    "digital_events",
    "campaign_sends",
)
VIA_INTERACTION = ("call_transcripts", "satisfaction_surveys")


def download_clean(s3, bucket: str, staged: dict, dest: Path) -> None:
    """Fetch transform's Parquet files into dest, checking each against its SHA-256."""
    dest.mkdir(parents=True, exist_ok=True)
    for table, meta in staged.items():
        path = dest / f"{table}.parquet"
        s3.download_file(bucket, meta["uri"].split(f"s3://{bucket}/", 1)[1], str(path))
        if sha256_file(path) != meta["sha256"]:
            raise CurationError(
                f"{table}: Parquet differs from transform.json's SHA-256"
            )


def curate(
    source: str,
    out_dir: Path,
    *,
    customers: int = 1500,
    per_class: int = 20,
    personas: dict | None = None,
    expected: dict | None = None,
) -> tuple[list[Table], dict]:
    """Return the curated Parquet files and the record for curate.json (without "tables")."""
    if customers <= 0 or customers % 12:
        raise CurationError(
            f"customers must be a positive multiple of 12, got {customers}"
        )
    personas = curate_select.load_personas() if personas is None else personas
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "curate.duckdb"  # on disk: digital_events has 15.6M rows
    db_path.unlink(missing_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute("SET enable_progress_bar = false")  # keeps CodeBuild logs readable
    try:
        names = [
            t
            for t in load_plan().data_tables
            if (Path(source) / f"{t}.parquet").exists()
        ]
        for name in names:
            path = (Path(source) / f"{name}.parquet").as_posix()
            con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{path}')")
        rows_in = {n: _count(con, f"SELECT count(*) FROM {n}") for n in names}
        curate_rules.check_evidence(con)
        curate_select.register_personas(con, personas)
        curate_select.build_profile(con)  # before the rules: ranks the defect cohort
        curate_select.defect_evidence(con)
        defects = curate_select.select_cohort(con, per_class)
        for t in RULE_TABLES:
            con.execute(
                f"CREATE TEMP TABLE snap_{t} AS SELECT * FROM {t} "
                "WHERE customer_id IN (SELECT customer_id FROM cohort)"
            )
        rules = curate_rules.apply_rules(con)
        print(f"rules {rules}", flush=True)
        curate_select.build_profile(con)  # after the rules: gates and score
        selection = curate_select.select_clean(con, personas, customers // 12)
        _assemble(con)
        _check(con, defects["customers"])
        rows = {n: _count(con, f"SELECT count(*) FROM {n}") for n in names}
        full = expected is not None and rows_in == expected.get("rows")
        if full and "curation" in expected and (customers, per_class) == (1500, 20):
            _compare(expected["curation"], rules, rows)
        record = {
            "as_of": AS_OF,
            "rules": rules,
            "selection": selection,
            "defects": defects,
        }
        return [_write(con, out_dir, n, rows[n]) for n in names], record
    finally:
        con.close()


def _assemble(con) -> None:
    """Keep the clean and cohort customers; the cohort's rule-table rows come from the snapshot."""
    con.execute(
        "CREATE OR REPLACE TEMP TABLE keep AS "
        "SELECT customer_id FROM clean UNION SELECT customer_id FROM cohort"
    )
    for t in RULE_TABLES:
        con.execute(
            f"DELETE FROM {t} WHERE customer_id IN (SELECT customer_id FROM cohort)"
        )
        con.execute(f"INSERT INTO {t} SELECT * FROM snap_{t}")
    for t in LINKED:
        con.execute(
            f"CREATE OR REPLACE TABLE {t} AS SELECT * FROM {t} "
            "WHERE customer_id IN (SELECT customer_id FROM keep)"
        )
    for t in VIA_INTERACTION:
        con.execute(
            f"CREATE OR REPLACE TABLE {t} AS SELECT * FROM {t} "
            "WHERE interaction_id IN (SELECT interaction_id FROM call_center_interactions)"
        )


def _check(con, cohort_customers: dict) -> None:
    """Fail, naming every broken check, unless the curated tables hold together (spec 8)."""
    failures = [
        f"{rule}: {n:,} rows of clean customers break it"
        for rule, n in curate_rules.check_invariants(
            con, "SELECT customer_id FROM clean"
        ).items()
        if n
    ]
    curate_select.build_profile(con)
    ungated = _count(
        con,
        "SELECT count(*) FROM clean JOIN profile USING (customer_id) "
        f"WHERE NOT ({curate_select.ELIGIBLE})",
    )
    if ungated:
        failures.append(f"{ungated} selected customers fail a gate")
    lost = curate_select.lost_defects(con, cohort_customers)
    if lost:
        failures.append(f"cohort lost {len(lost)} defects: {', '.join(lost[:5])}")
    both = _count(
        con,
        "SELECT count(*) FROM clean WHERE customer_id IN (SELECT customer_id FROM cohort)",
    )
    if both:
        failures.append(f"{both} customers are both clean and in the cohort")
    try:
        repair.check_links(con)
    except repair.LinkError as e:
        failures.append(str(e))
    if failures:
        raise CurationError("curation checks failed: " + "; ".join(failures))


def _compare(expected: dict, rules: dict, rows: dict) -> None:
    diffs = []
    if rules != expected["rules"]:
        diffs.append(f"rules {rules}, expected {expected['rules']}")
    if rows != expected["rows"]:
        diffs.append(f"rows {rows}, expected {expected['rows']}")
    if diffs:
        raise CurationError("differs from expected.json curation: " + "; ".join(diffs))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_curate.py tests/unit/test_data_load_curate_select.py tests/unit/test_data_load_curate_rules.py -q`
Expected: `32 passed`.

- [ ] **Step 6: Lint and commit**

```bash
uv run --no-project --quiet --with ruff ruff format data_load/curate.py tests/unit/curate_fixtures.py tests/unit/test_data_load_curate.py
uv run --no-project --quiet --with ruff ruff check data_load/curate.py tests/unit/curate_fixtures.py tests/unit/test_data_load_curate.py
git add data_load/curate.py tests/unit/curate_fixtures.py tests/unit/test_data_load_curate.py
git commit -m "feat(curate): the curate stage: snapshot, rules, selection, assembly and checks"
```

---

### Task 4: CLI command, run record and load input

**Files:**
- Modify: `data_load/__main__.py`
- Modify: `data_load/runrecord.py:6`
- Test: `tests/unit/test_data_load_cli.py`

**Interfaces:**
- Consumes (Task 3): `data_load.curate.curate`, `download_clean`; `transform.load_expected()`.
- Produces:
  - CLI `curate [--source DIR] [--out DIR] [--customers N] [--defect-per-class N]`.
  - A local run writes `<out>/curate.json`; a cloud run writes `runs/<run-id>/curate.json`, whose `tables[<name>]` holds `{rows, uri, sha256}`.
  - `load` consumes `curate.json`.

- [ ] **Step 1: Update the CLI tests**

Make these edits to `tests/unit/test_data_load_cli.py`:

1. Imports: add `import hashlib` above `import json`, and `from curate_fixtures import PERSONAS, world` above `from data_load_fixtures import tx, write_transactions`.
2. In `test_stages_list_missing_environment`'s parametrize list, after the `(["transform"], "RUN_ID, TEAM_BUCKET"),` line add:

   ```python
           (["curate"], "RUN_ID, TEAM_BUCKET"),
   ```

3. Change `@pytest.mark.parametrize("stage", ["ingest", "transform", "load"])` to `@pytest.mark.parametrize("stage", ["ingest", "transform", "curate", "load"])`.
4. In `fake_load_env`:
   - change `"uri": f"s3://team/clean/run-1/{t}.parquet",` to `"uri": f"s3://team/curated/run-1/{t}.parquet",`;
   - change `runrecord.write(s3, "team", "run-1", "transform", record)` to `runrecord.write(s3, "team", "run-1", "curate", record)`.
5. Replace `test_load_refuses_an_incomplete_transform_record` with:

   ```python
   @pytest.mark.unit
   def test_load_refuses_an_incomplete_curate_record(monkeypatch):
       _, calls = fake_load_env(monkeypatch, {"branches": 350})
       with pytest.raises(
           SystemExit, match="curate.json lacks tables: call_center_interactions"
       ):
           main(["load"])
       assert calls == []  # stopped before touching DSQL
   ```

6. Append:

```python
@pytest.mark.unit
def test_load_without_a_curate_record_says_to_run_curate_first(monkeypatch):
    s3, calls = fake_load_env(monkeypatch, {"branches": 350})
    runrecord.clear(s3, "team", "run-1", "curate")
    with pytest.raises(
        SystemExit, match="no curate.json for run run-1: run curate first"
    ):
        main(["load"])
    assert calls == []


@pytest.mark.unit
def test_curate_command_writes_parquet_locally(monkeypatch, tmp_path, capsys):
    source = world(tmp_path / "clean")
    monkeypatch.setattr("data_load.curate_select.load_personas", lambda: PERSONAS)
    code = main(
        [
            "curate",
            "--source",
            source.as_posix(),
            "--out",
            str(tmp_path / "out"),
            "--customers",
            "12",
            "--defect-per-class",
            "1",
        ]
    )
    assert code == 0
    assert (tmp_path / "out" / "customers.parquet").exists()
    record = json.loads((tmp_path / "out" / "curate.json").read_text(encoding="utf-8"))
    assert record["selection"]["personas"] == {"P01": "PER"}
    assert "curated 2 clean + 1 defect-cohort customers" in capsys.readouterr().out


@pytest.mark.unit
def test_cloud_curate_downloads_checks_uploads_and_records(monkeypatch, tmp_path):
    for name, value in {"RUN_ID": "run-1", "TEAM_BUCKET": "team"}.items():
        monkeypatch.setenv(name, value)
    s3 = FakeS3({("team", "clean/run-1/branches.parquet"): b"clean"})
    sha = hashlib.sha256(b"clean").hexdigest()
    staged = {"uri": "s3://team/clean/run-1/branches.parquet", "sha256": sha}
    runrecord.write(s3, "team", "run-1", "transform", {"tables": {"branches": staged}})
    monkeypatch.setattr("boto3.client", lambda *a, **k: s3)
    seen = {}

    def fake_curate(source, out_dir, expected=None, **sizes):
        seen["files"] = sorted(p.name for p in Path(source).iterdir())
        seen["sizes"], seen["expected"] = sizes, expected
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "branches.parquet"
        path.write_bytes(b"curated")
        record = {
            "as_of": "2026-06-17T23:59:59",
            "rules": {"C1": {"changed": 1}},
            "selection": {"customers": 1500},
            "defects": {"customers_selected": 159},
        }
        return [Table("branches", path, 350, "c" * 64)], record

    monkeypatch.setattr("data_load.curate.curate", fake_curate)
    assert main(["curate", "--out", str(tmp_path)]) == 0
    assert seen["files"] == ["branches.parquet"]
    assert seen["sizes"] == {"customers": 1500, "per_class": 20}
    assert seen["expected"] == load_expected()
    assert s3.objects[("team", "curated/run-1/branches.parquet")] == b"curated"
    assert s3.objects[("team", "curated/run-1/branches.parquet.sha256")] == b"c" * 64
    record = runrecord.read(s3, "team", "run-1", "curate")
    assert record["run_id"] == "run-1"
    assert record["rules"] == {"C1": {"changed": 1}}
    assert record["tables"]["branches"] == {
        "rows": 350,
        "uri": "s3://team/curated/run-1/branches.parquet",
        "sha256": "c" * 64,
    }
```

- [ ] **Step 2: Run the CLI tests to verify they fail**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_cli.py -q`
Expected: `7 failed, 12 passed`. The failing tests:
- `test_stages_list_missing_environment[command2-…]`: argparse rejects `curate`;
- `test_a_failed_rerun_removes_the_stages_old_record[curate]`;
- `test_load_dry_runs_every_table_largest_first_then_loads` and `test_load_refuses_an_incomplete_curate_record`: load still reads `transform.json`;
- `test_load_without_a_curate_record_says_to_run_curate_first`;
- `test_curate_command_writes_parquet_locally`;
- `test_cloud_curate_downloads_checks_uploads_and_records`.

- [ ] **Step 3: Add `curate` to the run-record stages**

In `data_load/runrecord.py`, change `STAGES = ("ingest", "transform", "load")` to:

```python
STAGES = ("ingest", "transform", "curate", "load")
```

- [ ] **Step 4: Add the curate command and point load at curate.json**

In `data_load/__main__.py`:

1. Replace the module docstring with:

   ```python
   """python -m data_load {ingest,transform,curate,load,check}: the data pipeline's stages.

   CodeBuild runs `python -m data_load $STAGE` for stages 1-4; Step Functions sets STAGE
   and RUN_ID. Design: docs/superpowers/specs/2026-10-02-data-pipeline-design.md and
   docs/superpowers/specs/2026-10-03-curate-stage-design.md
   """
   ```

2. Add `import json` between `import argparse` and `import os`.
3. Insert above `def cmd_load(args) -> int:`:

   ```python
   def cmd_curate(args) -> int:
       from data_load.curate import curate, download_clean
       from data_load.transform import load_expected

       expected = load_expected()  # compared only on the full data with default sizes
       sizes = {"customers": args.customers, "per_class": args.defect_per_class}
       if args.source:  # local rehearsal: nothing in AWS is read or written
           written, record = curate(
               args.source, Path(args.out), expected=expected, **sizes
           )
           body = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False)
           (Path(args.out) / "curate.json").write_text(body, encoding="utf-8")
           _print_curated(written, record)
           return 0

       run_id, bucket = require_env("RUN_ID", "TEAM_BUCKET")
       import boto3

       from data_load import runrecord

       s3 = boto3.client("s3")
       runrecord.clear(s3, bucket, run_id, "curate")
       staged = runrecord.read(s3, bucket, run_id, "transform")["tables"]
       clean = Path(args.out) / "clean"
       shutil.rmtree(clean, ignore_errors=True)  # a stale file would be read as a table
       download_clean(s3, bucket, staged, clean)
       written, record = curate(
           clean.as_posix(), Path(args.out) / "curated", expected=expected, **sizes
       )
       record = {"run_id": run_id, **record, "tables": {}}
       for table in written:
           key = f"curated/{run_id}/{table.path.name}"
           s3.upload_file(str(table.path), bucket, key)
           s3.put_object(Bucket=bucket, Key=f"{key}.sha256", Body=table.sha256.encode())
           record["tables"][table.name] = {
               "rows": table.rows,
               "uri": f"s3://{bucket}/{key}",
               "sha256": table.sha256,
           }
       uri = runrecord.write(s3, bucket, run_id, "curate", record)
       _print_curated(written, record)
       print(f"curate: record {uri}", flush=True)
       return 0


   def _print_curated(written, record) -> None:
       clean = record["selection"]["customers"]
       cohort = record["defects"]["customers_selected"]
       total = sum(t.rows for t in written)
       print(
           f"curated {clean:,} clean + {cohort:,} defect-cohort customers, {total:,} rows"
       )
       print(f"rules {record['rules']}", flush=True)
   ```

4. In `cmd_load`:
   - add `from botocore.exceptions import ClientError` directly below its `import boto3`;
   - replace `staged = runrecord.read(s3, bucket, run_id, "transform")["tables"]` with:

   ```python
       try:
           staged = runrecord.read(s3, bucket, run_id, "curate")["tables"]
       except (KeyError, ClientError) as e:  # KeyError: the unit tests' fake S3
           if isinstance(e, ClientError) and e.response["Error"]["Code"] != "NoSuchKey":
               raise
           raise SystemExit(f"no curate.json for run {run_id}: run curate first") from None
   ```

   - change the message `f"transform.json lacks tables: {', '.join(missing)}"` to `f"curate.json lacks tables: {', '.join(missing)}"`.
5. In `main`, replace the `load` sub-parser line with:

   ```python
       p = sub.add_parser(
           "curate", help="stage 3: fix, select and write the curated Parquet"
       )
       p.add_argument("--source", help="local directory of clean Parquet (skips S3)")
       p.add_argument("--out", default=str(WORK))
       p.add_argument("--customers", type=int, default=1500, help="clean customers (x12)")
       p.add_argument("--defect-per-class", type=int, default=20)
       p.set_defaults(func=cmd_curate)

       p = sub.add_parser("load", help="stage 4: recreate the tables and bulk-load DSQL")
   ```

- [ ] **Step 5: Run the whole data_load suite**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt --with pytest python -m pytest tests/unit/test_data_load_*.py tests/unit/test_dsql_read_check.py tests/unit/test_deploy_with_codebuild.py -q`
Expected: `120 passed`.

- [ ] **Step 6: Lint and commit**

```bash
uv run --no-project --quiet --with ruff ruff format data_load tests/unit/test_data_load_cli.py
uv run --no-project --quiet --with ruff ruff check data_load tests/unit/test_data_load_cli.py
git add data_load/__main__.py data_load/runrecord.py tests/unit/test_data_load_cli.py
git commit -m "feat(curate): curate command and record; load reads curate.json"
```

---

### Task 5: The Curate state in Step Functions

**Files:**
- Modify: `infra-cdk/lib/data-construct.ts` (CodeBuild description, state chain)
- Test: `infra-cdk/test/data-construct.test.ts` (state-machine test)

**Interfaces:**
- Consumes: the `stage(name)` helper already in `data-construct.ts`. It sets `STAGE` to `name.toLowerCase()` and `RUN_ID` from the execution name.
- Produces: the `Curate` state; CodeBuild runs `python -m data_load curate`.

- [ ] **Step 1: Update the jest test**

In `infra-cdk/test/data-construct.test.ts`, rename the test to `"state machine runs ingest, transform, curate, load, then the read check"`. In its fragment list:
- after `'\\"Next\\":\\"Transform\\"',` add `'\\"Next\\":\\"Curate\\"',`;
- after the `Value\\":\\"transform\\"'` fragment add:

```ts
    '\\"Name\\":\\"STAGE\\",\\"Type\\":\\"PLAINTEXT\\",\\"Value\\":\\"curate\\"',
```

- [ ] **Step 2: Run jest to verify it fails**

Run: `cd infra-cdk && npx jest test/data-construct.test.ts`
Expected: `1 failed, 9 passed`. The state-machine test can't find the `Curate` fragment.

- [ ] **Step 3: Add the state and update the project description**

In `infra-cdk/lib/data-construct.ts`:
- change the CodeBuild `description` to `"Data pipeline stages 1-4: python -m data_load $STAGE (ingest, transform, curate, load)"`;
- in the state-machine chain, insert `.next(stage("Curate"))` between `.next(stage("Transform"))` and `.next(stage("Load"))`.

- [ ] **Step 4: Type-check and run jest**

Run: `cd infra-cdk && npx tsc --noEmit && npx jest test/data-construct.test.ts`
Expected: no tsc output; `10 passed`.

- [ ] **Step 5: Commit**

```bash
git add infra-cdk/lib/data-construct.ts infra-cdk/test/data-construct.test.ts
git commit -m "feat(infra): Curate state between Transform and Load"
```

---

### Task 6: Full rehearsal and pinned counts

**Files:**
- Modify: `data_load/expected.json`

**Interfaces:**
- Consumes: the CLI from Task 4, and the local data `datathon/data` (organizer layout, git-ignored).
- Produces: `expected.json` → `curation`. Every later full run with default sizes must reproduce it.

- [ ] **Step 1: Produce the repaired data locally (skip if a recent `clean/` exists)**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt python -m data_load transform --source datathon/data --out <tmp>/clean`
Expected (about 7 min): `total 23,495,188 rows in 13 tables`, and the R1–R6 counts of `expected.json`.

- [ ] **Step 2: Run curate on it**

Run: `uv run --no-project --quiet --with-requirements data_load/requirements.txt python -m data_load curate --source <tmp>/clean --out <tmp>/curated`
Expected (about 3–4 min):
- `curated 1,500 clean + 159 defect-cohort customers, 270,866 rows`;
- the rule counts below;
- `<tmp>/curated/curate.json` written.

- [ ] **Step 3: Pin the counts**

In `data_load/expected.json`, add a comma after the `"repairs"` object and this `"curation"` key, so the file ends with `"rows"`, `"repairs"`, `"curation"`:

```json
  "curation": {
    "rules": {
      "C1": {"changed": 40515},
      "C2": {"changed": 99477},
      "C3": {"changed": 51952},
      "C4": {"changed": 203369},
      "C5": {"changed": 339965},
      "C6": {"customers": 9316, "products": 25113},
      "C7": {"changed": 283},
      "C8": {"kept_expired": 5171, "reissued": 51493},
      "C9": {"changed": 87740},
      "C10": {"changed": 43006},
      "C11": {"closed": 48943, "rejected_dated": 685},
      "C12": {"changed": 23299}
    },
    "rows": {
      "branches": 350,
      "call_center_interactions": 7685,
      "call_transcripts": 1919,
      "campaign_sends": 19575,
      "complaints": 778,
      "customers": 1659,
      "daily_exchange_rates": 13164,
      "digital_events": 130513,
      "marketing_campaigns": 200,
      "products": 6952,
      "satisfaction_surveys": 2327,
      "service_agents": 1200,
      "transactions": 84544
    }
  }
```

- [ ] **Step 4: Rerun to prove the comparison passes, and that it bites**

1. Rerun Step 2. Expected: the same output and no error.
2. Temporarily change one pinned row count, say `"customers": 1658`, and rerun. Expected: `CurationError: differs from expected.json curation: rows {…}, expected {…}`.
3. Restore the value.

- [ ] **Step 5: Commit**

```bash
git add data_load/expected.json
git commit -m "test(curate): pin the full-data curation counts in expected.json"
```

---

### Task 7: Documentation (process, rules, personas, defect cohort)

**Files:**
- Create: `datathon/analysis/curated_customers.py`
- Create: `datathon/docs/analysis/2026-10-03-curated-customers.md`
- Modify: `datathon/docs/analysis/2026-10-02-agent-data-diagnostic.md` (section 8 resolved; D38, D39)
- Modify: `docs/superpowers/specs/2026-10-03-curate-stage-design.md` (pinned counts)
- Modify: `docs/superpowers/specs/2026-10-02-data-pipeline-design.md` (load reads `curated/`)
- Modify: `README.md` (LedgerLens Database section)

**Interfaces:**
- Consumes: `<tmp>/curated/` from Task 6 (Parquet and `curate.json`) and `data_load/personas.json`.

- [ ] **Step 1: Write the report script**

Create `datathon/analysis/curated_customers.py`:

```python
"""Print the curated customers as Markdown: run summary, the 10 personas, one showcase per
defect class. Feeds datathon/docs/analysis/2026-10-03-curated-customers.md.

Usage: python datathon/analysis/curated_customers.py <curate --out dir> > curated_customers.md
The directory holds curate.json and the 13 curated Parquet files (`python -m data_load curate
--source <clean dir> --out <dir>`).
"""

import json
import sys
from pathlib import Path

import duckdb

sys.stdout.reconfigure(encoding="utf-8")
OUT = Path(sys.argv[1])
RECORD = json.loads((OUT / "curate.json").read_text(encoding="utf-8"))
PERSONAS = json.loads(
    (Path(__file__).parents[2] / "data_load" / "personas.json").read_text(
        encoding="utf-8"
    )
)["personas"]
con = duckdb.connect()
for path in OUT.glob("*.parquet"):
    con.execute(
        f"CREATE VIEW {path.stem} AS SELECT * FROM read_parquet('{path.as_posix()}')"
    )


def fmt(v) -> str:
    return "" if v is None else f"{v:,}" if isinstance(v, int) else str(v)


def table(sql: str, params=None) -> str:
    """One query as a Markdown table ('_none_' when empty)."""
    rel = con.execute(sql, params or [])
    cols, rows = [d[0] for d in rel.description], rel.fetchall()
    if not rows:
        return "_none_\n"
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(fmt(v) for v in row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def customer_block(cid: str) -> str:
    return "\n".join(
        [
            table(
                "SELECT customer_id, first_name, last_name, gender, country, city, segment, "
                "customer_status, date_diff('year', date_of_birth, DATE '2026-06-17') AS age "
                "FROM customers WHERE customer_id = ?",
                [cid],
            ),
            "Cards:\n",
            table(
                "SELECT product_id, right(product_number, 4) AS last4, product_type, "
                "product_status, currency, current_balance, credit_limit, expiration_date, "
                "days_past_due FROM products WHERE customer_id = ? "
                "AND product_type IN ('Tarjeta Crédito', 'Tarjeta Débito') ORDER BY product_id",
                [cid],
            ),
            "Card transactions, last 30 days:\n",
            table(
                "SELECT t.transaction_id, t.transaction_date, right(p.product_number, 4) AS last4, "
                "t.transaction_type, t.merchant_name, t.amount, t.currency, "
                "t.transaction_country, t.channel, t.transaction_status, t.response_code, "
                "t.fraud_score FROM transactions t JOIN products p USING (product_id) "
                "WHERE t.customer_id = ? AND p.product_type IN ('Tarjeta Crédito', "
                "'Tarjeta Débito') AND t.process_date > DATE '2026-06-17' - 30 "
                "ORDER BY t.transaction_date DESC",
                [cid],
            ),
            "Cases, last 120 days:\n",
            table(
                "SELECT complaint_id, creation_date, category, subcategory, status, "
                "claimed_amount, currency, closing_date FROM complaints WHERE customer_id = ? "
                "AND creation_date > TIMESTAMP '2026-06-17 23:59:59' - INTERVAL 120 DAY "
                "ORDER BY creation_date DESC",
                [cid],
            ),
        ]
    )


print("## Run summary\n")
print(f"- Clean customers: {RECORD['selection']['customers']:,}")
print(f"- Defect-cohort customers: {RECORD['defects']['customers_selected']:,}\n")
print("| Rule | Counts |\n|---|---|")
for rule, counts in sorted(RECORD["rules"].items(), key=lambda r: int(r[0][1:])):
    print(f"| {rule} | {', '.join(f'{k} {v:,}' for k, v in counts.items())} |")
print("\n| Gate | Customers passing all gates so far |\n|---|---:|")
for gate, n in RECORD["selection"]["funnel"].items():
    print(f"| {gate} | {n:,} |")
print("\n| Cell | Eligible | Selected |\n|---|---:|---:|")
for cell, c in RECORD["selection"]["cells"].items():
    print(f"| {cell.replace('|', ' × ')} | {c['eligible']:,} | {c['selected']:,} |")
print("\n| Defect class | Candidates | Selected |\n|---|---:|---:|")
for k, c in RECORD["defects"]["classes"].items():
    print(f"| {k} | {c['candidates']:,} | {c['selected']:,} |")

print("\n## Personas\n")
for pid, p in PERSONAS.items():
    print(f"### {pid}: {p['use_case']}\n")
    print(f"Expected: {p['expected_outcome']}. Evidence: {', '.join(p['evidence'])}.\n")
    print(customer_block(p["customer_id"]))

print("## Defect cohort: one showcase per class\n")
cohort, shown = RECORD["defects"]["customers"], set()
for k in RECORD["defects"]["classes"]:
    carriers = sorted(c for c, classes in cohort.items() if k in classes)
    if not carriers:
        continue
    cid = next(
        (c for c in carriers if c not in shown), carriers[0]
    )  # vary the showcases
    shown.add(cid)
    print(f"### {k}: {cid}\n")
    print(
        f"Evidence: {', '.join(cohort[cid][k])}. All classes: {', '.join(cohort[cid])}.\n"
    )
    print(customer_block(cid))
```

- [ ] **Step 2: Generate the customer sections**

Run: `uv run --no-project --quiet --with duckdb==1.5.5 python datathon/analysis/curated_customers.py <tmp>/curated > <tmp>/curated_customers.md`
Expected: Markdown with
- a run summary (rule counts, gate funnel, 12 cells, 17 classes);
- 10 persona sections, each with profile, cards, last-30-day card transactions and cases;
- 17 defect showcases.

- [ ] **Step 3: Write the process document**

Create `datathon/docs/analysis/2026-10-03-curated-customers.md` with exactly this structure. The text in `>` blocks is the content to write. Paste the generated sections where marked.

```markdown
# Curated customers: process, rules, personas and defect cohort

Factored AI & Data Hackathon 2026 · 2026-10-03 · `as_of` 2026-06-17 · spec `docs/superpowers/specs/2026-10-03-curate-stage-design.md`

## 1. Why this exists
> Two or three paragraphs:
> - the problem (diagnostic sections 0 and 3: per-customer incoherence and thin activity);
> - the decision (curate stage: fix by rule, select balanced, keep a defect cohort);
> - what the agent now reads (1,500 clean + the cohort; tools unchanged).

## 2. The process, step by step
> A numbered list of the 7 steps in spec section 4.2, each with what it does and its count from `curate.json`. Name the commands that reproduce it (Task 6 Steps 1–2, and Step 2 of this task).

## 3. Rules applied
> A table: rule, class (derive or synthetic), what changed, rows changed (from `curate.json`), evidence. Then one paragraph on the C8 exception and one on C12's conversion (spec decisions E5, E6). End with the kept-as-delivered list (spec 5.3: D01, D12–D14, D18, D20, D22, D23, D30–D34, D38, D39).

## 4. Selection
> The gates G1–G8 with the funnel, the score formula, the 12 cells table, and why the cells are balanced (spec E7).

## 5. The 10 personas
> A summary table first: P#, use case, customer, country/segment, expected outcome, why picked (spec 6.4, and the reasons from the brainstorming record: evidence inside the tool's window, a credit-card Purchase with a merchant on POS/App/Web, country/segment/gender spread). Then the alternates.
> Paste here the "## Personas" section of `<tmp>/curated_customers.md`.

## 6. The defect cohort
> What it is (spec section 7), the 17 classes with candidates and selected counts, and a draft expected agent behaviour per class as open items for `POLICY.md` (for example K02: never call the card "active and valid" without its expiry; K07: say the records don't match and offer a hand-off; K01: the policy decides whether to serve a Closed customer).
> Paste here the "## Defect cohort" section of `<tmp>/curated_customers.md`.

## 7. Known limits
> - Synthetic rules are labelled (C8–C12).
> - Uniform amounts and hours are unfixable (D22).
> - The score is a draft.
> - C11 uses calendar-day deadlines.
> - The C2 UDF was rejected (Global Constraints).
```

- [ ] **Step 4: Update the existing documents**

1. **Diagnostic:** in `datathon/docs/analysis/2026-10-02-agent-data-diagnostic.md`:
   - set the Status line to "diagnostic; decisions resolved by the curate stage spec (2026-10-03)";
   - add a note under §8 that every row is resolved in `docs/superpowers/specs/2026-10-03-curate-stage-design.md` (decisions E1–E11);
   - add D38 (segment unrelated to age: Students median 52, 5,781 of 7,490 over 35) and D39 (event type vs page title mismatch) to §4.5, class Label.
2. **Curate spec:** in `docs/superpowers/specs/2026-10-03-curate-stage-design.md`, set the Status to "implemented", and replace the prototype counts in sections 5 and 6.1 with the pinned ones from Task 6. In particular:
   - C12 counts only rows whose values change;
   - the funnel ends at the pinned G8 figure;
   - the cohort holds the pinned number of customers.
   - Section 8, the count check: the pinned comparison covers the rule counts and the rows per table. Rows per table change whenever the selection or the cohort changes, so the per-cell and per-class counts aren't pinned separately; they stay in `curate.json`.
3. **Pipeline spec:** in `docs/superpowers/specs/2026-10-02-data-pipeline-design.md` section 4.1, add a line under the stage table: "Amended 2026-10-03: a curate stage runs between transform and load; load reads `runs/<run-id>/curate.json` and `curated/<run-id>/` (`docs/superpowers/specs/2026-10-03-curate-stage-design.md`)."
4. **README:** in the "LedgerLens Database (Aurora DSQL)" section:
   - first paragraph: DSQL holds the curated set (1,500 clean customers + the defect cohort, about 270K rows), while S3 `clean/` keeps all 23,495,188 repaired rows;
   - "Stages" bullet: ingest → transform → curate → load → read check;
   - "Downtime" bullet: about 2 minutes;
   - "Load the data" heading: about 10 minutes in total;
   - add the curate spec to the Design line.

- [ ] **Step 5: Lint and commit**

```bash
uv run --no-project --quiet --with ruff ruff check datathon/analysis/curated_customers.py
git add datathon/analysis/curated_customers.py datathon/docs/analysis/2026-10-03-curated-customers.md datathon/docs/analysis/2026-10-02-agent-data-diagnostic.md docs/superpowers/specs/2026-10-03-curate-stage-design.md docs/superpowers/specs/2026-10-02-data-pipeline-design.md README.md
git commit -m "docs(curate): curated customers process doc, personas and defect cohort; README and specs"
```

---

### Task 8: Deploy and run in AWS (needs the human's go-ahead)

**Files:** none changed. This task deploys and runs.

**Interfaces:**
- Consumes: the data stack `ledgerlens-bank-assistant-data` (deployed), the `ledgerlens` profile, and the state machine `ledgerlens-data-pipeline`.
- Produces: DSQL `public` holding the curated set; `runs/<run-id>/curate.json`.

- [ ] **Step 1: Ask the human before touching AWS**

State what will happen and wait for an explicit yes:
- the data stack redeploys (Step Functions gains `Curate`);
- the pipeline reruns (about 10 minutes);
- the tools see missing tables for about 2 minutes;
- DSQL will hold only the curated set.

- [ ] **Step 2: Deploy the data stack**

Run: `AWS_PROFILE=ledgerlens python scripts/deploy-with-codebuild.py ledgerlens-bank-assistant-data`
Expected: the deploy build succeeds, and the state machine definition shows `Transform → Curate → Load`.

- [ ] **Step 3: Run the pipeline**

```bash
arn=$(aws stepfunctions list-state-machines --profile ledgerlens --query "stateMachines[?name=='ledgerlens-data-pipeline'].stateMachineArn" --output text)
aws stepfunctions start-execution --profile ledgerlens --state-machine-arn "$arn"
```

Expected: the execution succeeds. Follow the stages with `aws logs tail /aws/codebuild/ledgerlens-data-load --follow --profile ledgerlens`. The curate log prints the Task 6 counts. The read check returns `{"tables_read": 13, "insert_denied": true}`.

- [ ] **Step 4: Smoke-test a tool on two personas**

```bash
aws lambda invoke --profile ledgerlens --function-name ledgerlens-get-session-context --cli-binary-format raw-in-base64-out --payload '{"customer_id":"CLI-1GL7QBDG3QG0"}' p01.json
aws lambda invoke --profile ledgerlens --function-name ledgerlens-list-credit-cards --cli-binary-format raw-in-base64-out --payload '{"customer_id":"CLI-Z3V3SBS18YWQ"}' p10.json
```

Expected:
- `p01.json`'s recent transactions include `TRX-SSJAIUCVVU1L4605ZLNM` with status `Declined`;
- `p10.json` lists card 7718 as `Blocked` and card 2626 as `Active`.

Delete both files afterwards.

- [ ] **Step 5: Record the run**

Append to the curate spec's section 13 the run ID, the stage durations and the DSQL row count (`load.json`), as the pipeline spec's section 11.4 does. Commit:

```bash
git add docs/superpowers/specs/2026-10-03-curate-stage-design.md
git commit -m "docs(spec): record the first curated pipeline run"
```
