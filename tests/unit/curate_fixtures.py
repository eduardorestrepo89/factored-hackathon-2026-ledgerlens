"""A tiny in-memory LATAM Bank for the curate tests: only the columns curate reads.

`good()` builds a customer who passes every gate (G1-G8); tests then break one thing.
"""

from datetime import date, datetime
from pathlib import Path

import duckdb

CREDIT, DEBIT = "Tarjeta Crédito", "Tarjeta Débito"
PERSONAS = {"P01": {"customer_id": "PER"}}  # the persona world() builds
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
