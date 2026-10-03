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
