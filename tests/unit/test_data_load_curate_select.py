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
def test_a_persona_cut_from_a_full_cell_fails_the_stage_naming_it():
    con = bank()
    good(con, "PA")
    good(con, "PB")  # same cell as PA: with one place per cell, one persona is cut
    personas = {"P01": {"customer_id": "PA"}, "P02": {"customer_id": "PB"}}
    register_personas(con, personas)
    build_profile(con)
    no_cohort(con)
    with pytest.raises(CurationError, match="personas not selected: P0[12] P[AB]"):
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
