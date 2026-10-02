"""Repairs R1-R6 and link checks (spec section 6), on tiny hand-built tables."""

from datetime import date, datetime

import duckdb
import pytest

from data_load.repair import LinkError, check_links, repair

# Only the columns the repairs and link checks touch
COLUMNS = {
    "branches": "branch_id VARCHAR PRIMARY KEY",
    "customers": "customer_id VARCHAR PRIMARY KEY, registration_branch_id VARCHAR, registration_date TIMESTAMP",
    "products": "product_id VARCHAR PRIMARY KEY, customer_id VARCHAR, product_type VARCHAR, "
    "opening_branch_id VARCHAR, opening_date DATE",
    "transactions": "transaction_id VARCHAR PRIMARY KEY, product_id VARCHAR, customer_id VARCHAR, "
    "branch_id VARCHAR, transaction_date TIMESTAMP",
    "service_agents": "agent_id VARCHAR PRIMARY KEY, assigned_branch_id VARCHAR",
    "complaints": "complaint_id VARCHAR PRIMARY KEY, customer_id VARCHAR, affected_product_id VARCHAR, "
    "related_branch_id VARCHAR, assigned_agent_id VARCHAR, origin_interaction_id VARCHAR",
    "digital_events": "event_id VARCHAR PRIMARY KEY, customer_id VARCHAR, product_id VARCHAR",
}
CARD, SAVINGS = "Tarjeta Crédito", "Cuenta Ahorro"
OLD = datetime(2020, 1, 1)


def db(**tables: list[tuple]) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    for name, rows in tables.items():
        con.execute(f"CREATE TABLE {name} ({COLUMNS[name]})")
        if rows:
            marks = ", ".join("?" * len(rows[0]))
            con.executemany(f"INSERT INTO {name} VALUES ({marks})", rows)
    return con


def column(con, table: str, key: str, col: str) -> dict:
    return dict(con.execute(f"SELECT {key}, {col} FROM {table}").fetchall())


@pytest.mark.unit
def test_r6a_moves_opening_date_back_to_the_first_transaction():
    con = db(
        products=[
            ("P1", "C1", CARD, "B1", date(2025, 1, 10)),
            ("P2", "C1", SAVINGS, "B1", date(2024, 1, 1)),
        ],
        transactions=[
            ("T1", "P1", "C1", None, datetime(2024, 12, 31, 23, 0)),
            ("T2", "P1", "C1", None, datetime(2025, 2, 1)),
            ("T3", "P2", "C1", None, datetime(2024, 5, 1)),
        ],
    )
    assert repair(con) == {"R6a": {"changed": 1}}
    assert column(con, "products", "product_id", "opening_date") == {
        "P1": date(2024, 12, 31),
        "P2": date(2024, 1, 1),
    }
    check_links(con)


@pytest.mark.unit
def test_r1_takes_the_branch_of_the_earliest_product_or_null():
    con = db(
        branches=[("B1",), ("B2",)],
        customers=[("C1", "SUC-X", OLD), ("C2", "B2", OLD), ("C3", "SUC-Y", OLD)],
        products=[
            ("P1", "C1", CARD, "B2", date(2024, 2, 1)),
            ("P2", "C1", SAVINGS, "B1", date(2024, 1, 1)),
            ("P3", "C2", CARD, "B1", date(2024, 1, 1)),
        ],
    )
    counts = repair(con)
    assert counts["R1"] == {"resolved": 1, "set_null": 1}
    assert column(con, "customers", "customer_id", "registration_branch_id") == {
        "C1": "B1",  # earliest product P2
        "C2": "B2",  # valid: kept
        "C3": None,  # no products
    }
    check_links(con)


@pytest.mark.unit
def test_r1_breaks_ties_on_product_id():
    con = db(
        branches=[("B1",), ("B2",)],
        customers=[("C1", "SUC-X", OLD)],
        products=[
            ("P2", "C1", CARD, "B2", date(2024, 1, 1)),
            ("P1", "C1", SAVINGS, "B1", date(2024, 1, 1)),
        ],
    )
    repair(con)
    assert column(con, "customers", "customer_id", "registration_branch_id") == {
        "C1": "B1"
    }


@pytest.mark.unit
def test_r6b_uses_the_opening_dates_r6a_fixed():
    con = db(
        branches=[("B1",)],
        customers=[
            ("C1", "B1", datetime(2024, 3, 5, 10, 0)),
            ("C2", "B1", datetime(2024, 1, 1, 8, 0)),
        ],
        products=[
            ("P1", "C1", CARD, "B1", date(2024, 3, 1)),
            ("P2", "C2", CARD, "B1", date(2024, 1, 1)),  # same day: not before
        ],
        transactions=[("T1", "P1", "C1", None, datetime(2024, 2, 15, 9, 30))],
    )
    counts = repair(con)
    assert counts["R6a"] == {"changed": 1} and counts["R6b"] == {"changed": 1}
    assert column(con, "customers", "customer_id", "registration_date") == {
        "C1": datetime(2024, 2, 15),  # R6a moved P1 to 2024-02-15 first
        "C2": datetime(2024, 1, 1, 8, 0),
    }
    check_links(con)


@pytest.mark.unit
def test_r2_nulls_broken_agent_branches():
    con = db(
        branches=[("B1",)],
        service_agents=[("A1", "B1"), ("A2", "SUC-X"), ("A3", None)],
    )
    assert repair(con) == {"R2": {"set_null": 1}}
    assert column(con, "service_agents", "agent_id", "assigned_branch_id") == {
        "A1": "B1",
        "A2": None,
        "A3": None,
    }


@pytest.mark.unit
def test_r3_relinks_to_the_complainants_only_product_of_that_type():
    con = db(
        products=[
            ("P1", "C1", CARD, "B1", date(2024, 1, 1)),
            ("P2", "C2", CARD, "B1", date(2024, 1, 1)),
            ("P3", "C3", CARD, "B1", date(2024, 1, 1)),
            ("P4", "C3", CARD, "B1", date(2024, 1, 1)),
            ("P5", "C4", SAVINGS, "B1", date(2024, 1, 1)),
        ],
        complaints=[
            ("K1", "C2", "P1", None, None, None),  # C2 has one card: P2
            ("K2", "C3", "P1", None, None, None),  # C3 has two cards: ambiguous
            ("K3", "C4", "P1", None, None, None),  # C4 has no card
            ("K4", "C1", "P1", None, None, None),  # already the complainant's
            ("K5", "C1", None, None, None, None),  # no product: untouched
        ],
    )
    assert repair(con) == {"R3": {"resolved": 1, "set_null": 2}}
    assert column(con, "complaints", "complaint_id", "affected_product_id") == {
        "K1": "P2",
        "K2": None,
        "K3": None,
        "K4": "P1",
        "K5": None,
    }
    check_links(con)


@pytest.mark.unit
def test_r4_nulls_anonymous_events_and_relinks_the_rest():
    con = db(
        products=[
            ("P1", "C1", CARD, "B1", date(2024, 1, 1)),
            ("P2", "C2", CARD, "B1", date(2024, 1, 1)),
        ],
        digital_events=[
            ("E1", "C2", "P1"),  # someone else's card: C2's only card is P2
            ("E2", None, "P1"),  # anonymous: ownership can't be checked
            ("E3", "C1", "P1"),  # own card: kept
            ("E4", "C2", None),  # no product: untouched
        ],
    )
    assert repair(con) == {"R4": {"resolved": 1, "set_null": 1}}
    assert column(con, "digital_events", "event_id", "product_id") == {
        "E1": "P2",
        "E2": None,
        "E3": "P1",
        "E4": None,
    }
    check_links(con)


@pytest.mark.unit
def test_rules_run_only_when_their_tables_are_loaded():
    assert repair(db(branches=[("B1",)])) == {}


@pytest.mark.unit
def test_check_links_names_every_broken_check():
    con = db(
        products=[("P1", "C1", CARD, "B1", date(2025, 1, 1))],
        transactions=[
            ("T1", "P9", "C1", None, datetime(2025, 2, 1)),  # no such product
            ("T2", "P1", "C9", None, datetime(2025, 2, 1)),  # another customer's card
            ("T3", "P1", "C1", None, datetime(2024, 6, 1)),  # before the card opened
        ],
    )
    with pytest.raises(LinkError) as err:
        check_links(con)
    message = str(err.value)
    assert "transactions.product_id -> products: 1 broken" in message
    assert "transactions.product_id: 1 owned by another customer" in message
    assert "transactions before their product's opening_date: 1" in message
