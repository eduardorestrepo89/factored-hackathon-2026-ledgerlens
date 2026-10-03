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
