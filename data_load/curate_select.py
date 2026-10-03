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
