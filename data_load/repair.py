"""Repairs R1-R6 and the link checks, run in DuckDB before anything reaches DSQL.

Spec: docs/superpowers/specs/2026-10-02-data-pipeline-design.md, section 6. Each rule
writes its fixes to a temp table first, so the counts come from the same rows the
UPDATE applies. A rule runs only when all its tables are loaded (unit tests load a few).
"""

# The ERD's 24 declared links: (child table, column, parent table, parent column)
LINKS = (
    ("customers", "registration_branch_id", "branches", "branch_id"),
    ("products", "opening_branch_id", "branches", "branch_id"),
    ("service_agents", "assigned_branch_id", "branches", "branch_id"),
    ("transactions", "branch_id", "branches", "branch_id"),
    ("complaints", "related_branch_id", "branches", "branch_id"),
    ("products", "customer_id", "customers", "customer_id"),
    ("transactions", "customer_id", "customers", "customer_id"),
    ("call_center_interactions", "customer_id", "customers", "customer_id"),
    ("call_transcripts", "customer_id", "customers", "customer_id"),
    ("satisfaction_surveys", "customer_id", "customers", "customer_id"),
    ("digital_events", "customer_id", "customers", "customer_id"),
    ("complaints", "customer_id", "customers", "customer_id"),
    ("campaign_sends", "customer_id", "customers", "customer_id"),
    ("transactions", "product_id", "products", "product_id"),
    ("digital_events", "product_id", "products", "product_id"),
    ("complaints", "affected_product_id", "products", "product_id"),
    ("call_center_interactions", "agent_id", "service_agents", "agent_id"),
    ("call_transcripts", "agent_id", "service_agents", "agent_id"),
    ("satisfaction_surveys", "agent_id", "service_agents", "agent_id"),
    ("complaints", "assigned_agent_id", "service_agents", "agent_id"),
    ("campaign_sends", "campaign_id", "marketing_campaigns", "campaign_id"),
    (
        "call_transcripts",
        "interaction_id",
        "call_center_interactions",
        "interaction_id",
    ),
    (
        "satisfaction_surveys",
        "interaction_id",
        "call_center_interactions",
        "interaction_id",
    ),
    (
        "complaints",
        "origin_interaction_id",
        "call_center_interactions",
        "interaction_id",
    ),
)
# A product reference must belong to the row's own customer
OWNED = (
    ("transactions", "product_id"),
    ("complaints", "affected_product_id"),
    ("digital_events", "product_id"),
)


class LinkError(RuntimeError):
    """A link, ownership or date check failed after the repairs."""


def _count(con, sql: str) -> int:
    return con.execute(sql).fetchone()[0]


def _tables(con) -> set[str]:
    return {
        r[0]
        for r in con.execute(
            "SELECT table_name FROM duckdb_tables() WHERE NOT temporary"
        ).fetchall()
    }


def _resolved_and_nulled(con, fixes: str, column: str) -> dict[str, int]:
    resolved, total = con.execute(
        f"SELECT count({column}), count(*) FROM {fixes}"
    ).fetchone()
    return {"resolved": resolved, "set_null": total - resolved}


def _one_product_per_type(con) -> None:
    """A customer's only product of each type: the unambiguous relink target for R3/R4."""
    con.execute(
        "CREATE OR REPLACE TEMP TABLE one_per_type AS "
        "SELECT customer_id, product_type, min(product_id) AS product_id "
        "FROM products GROUP BY customer_id, product_type HAVING count(*) = 1"
    )


def r6a(con) -> dict[str, int]:
    """products.opening_date: no earlier than the product's first transaction."""
    con.execute(
        "CREATE OR REPLACE TEMP TABLE fix_r6a AS "
        "SELECT p.product_id, f.first_use FROM products p JOIN ("
        " SELECT product_id, min(transaction_date)::DATE AS first_use"
        " FROM transactions GROUP BY product_id) f USING (product_id) "
        "WHERE f.first_use < p.opening_date"
    )
    con.execute(
        "UPDATE products SET opening_date = f.first_use FROM fix_r6a f "
        "WHERE products.product_id = f.product_id"
    )
    return {"changed": _count(con, "SELECT count(*) FROM fix_r6a")}


def r1(con) -> dict[str, int]:
    """customers.registration_branch_id: broken -> branch of the earliest product, or NULL."""
    con.execute(
        "CREATE OR REPLACE TEMP TABLE fix_r1 AS "
        "SELECT c.customer_id, f.branch_id FROM customers c LEFT JOIN ("
        " SELECT customer_id, arg_min(opening_branch_id, (opening_date, product_id)) AS branch_id"
        " FROM products GROUP BY customer_id) f USING (customer_id) "
        "WHERE c.registration_branch_id NOT IN (SELECT branch_id FROM branches)"
    )
    con.execute(
        "UPDATE customers SET registration_branch_id = f.branch_id FROM fix_r1 f "
        "WHERE customers.customer_id = f.customer_id"
    )
    return _resolved_and_nulled(con, "fix_r1", "branch_id")


def r6b(con) -> dict[str, int]:
    """customers.registration_date: no later than the customer's first product (after R6a)."""
    con.execute(
        "CREATE OR REPLACE TEMP TABLE fix_r6b AS "
        "SELECT c.customer_id, f.first_open::TIMESTAMP AS registered FROM customers c JOIN ("
        " SELECT customer_id, min(opening_date) AS first_open"
        " FROM products GROUP BY customer_id) f USING (customer_id) "
        "WHERE f.first_open < c.registration_date::DATE"
    )
    con.execute(
        "UPDATE customers SET registration_date = f.registered FROM fix_r6b f "
        "WHERE customers.customer_id = f.customer_id"
    )
    return {"changed": _count(con, "SELECT count(*) FROM fix_r6b")}


def r2(con) -> dict[str, int]:
    """service_agents.assigned_branch_id: broken -> NULL (nothing else links agents to branches)."""
    con.execute(
        "CREATE OR REPLACE TEMP TABLE fix_r2 AS SELECT agent_id FROM service_agents "
        "WHERE assigned_branch_id NOT IN (SELECT branch_id FROM branches)"
    )
    con.execute(
        "UPDATE service_agents SET assigned_branch_id = NULL "
        "WHERE agent_id IN (SELECT agent_id FROM fix_r2)"
    )
    return {"set_null": _count(con, "SELECT count(*) FROM fix_r2")}


def r3(con) -> dict[str, int]:
    """complaints.affected_product_id: someone else's -> the complainant's only product of that type."""
    _one_product_per_type(con)
    con.execute(
        "CREATE OR REPLACE TEMP TABLE fix_r3 AS "
        "SELECT x.complaint_id, o.product_id FROM complaints x "
        "JOIN products p ON p.product_id = x.affected_product_id "
        "LEFT JOIN one_per_type o ON o.customer_id = x.customer_id AND o.product_type = p.product_type "
        "WHERE p.customer_id <> x.customer_id"
    )
    con.execute(
        "UPDATE complaints SET affected_product_id = f.product_id FROM fix_r3 f "
        "WHERE complaints.complaint_id = f.complaint_id"
    )
    return _resolved_and_nulled(con, "fix_r3", "product_id")


def r4(con) -> dict[str, int]:
    """digital_events.product_id: as R3; anonymous events can't be checked, so NULL."""
    _one_product_per_type(con)
    con.execute(
        "CREATE OR REPLACE TEMP TABLE fix_r4 AS "
        "SELECT x.event_id, CASE WHEN x.customer_id IS NOT NULL THEN o.product_id END AS product_id "
        "FROM digital_events x JOIN products p ON p.product_id = x.product_id "
        "LEFT JOIN one_per_type o ON o.customer_id = x.customer_id AND o.product_type = p.product_type "
        "WHERE x.customer_id IS NULL OR p.customer_id <> x.customer_id"
    )
    con.execute(
        "UPDATE digital_events SET product_id = f.product_id FROM fix_r4 f "
        "WHERE digital_events.event_id = f.event_id"
    )
    return _resolved_and_nulled(con, "fix_r4", "product_id")


# Order matters: R1 and R6b use the opening dates R6a fixed
RULES = (
    ("R6a", {"products", "transactions"}, r6a),
    ("R1", {"customers", "products", "branches"}, r1),
    ("R6b", {"customers", "products"}, r6b),
    ("R2", {"service_agents", "branches"}, r2),
    ("R3", {"complaints", "products"}, r3),
    ("R4", {"digital_events", "products"}, r4),
)


def repair(con) -> dict[str, dict[str, int]]:
    """Apply every rule whose tables are loaded, in order; return counts per rule."""
    loaded = _tables(con)
    return {rule: fix(con) for rule, needs, fix in RULES if needs <= loaded}


def check_links(con) -> None:
    """Fail, naming every broken check, unless links, ownership and dates all hold."""
    loaded, failures = _tables(con), []
    for child, column, parent, parent_column in LINKS:
        if {child, parent} <= loaded:
            broken = _count(
                con,
                f"SELECT count(*) FROM {child} c WHERE c.{column} IS NOT NULL AND NOT EXISTS "
                f"(SELECT 1 FROM {parent} p WHERE p.{parent_column} = c.{column})",
            )
            if broken:
                failures.append(f"{child}.{column} -> {parent}: {broken:,} broken")
    for child, column in OWNED:
        if {child, "products"} <= loaded:
            foreign = _count(
                con,
                f"SELECT count(*) FROM {child} c JOIN products p ON p.product_id = c.{column} "
                "WHERE p.customer_id IS DISTINCT FROM c.customer_id",
            )
            if foreign:
                failures.append(
                    f"{child}.{column}: {foreign:,} owned by another customer"
                )
    if {"transactions", "products"} <= loaded:
        early = _count(
            con,
            "SELECT count(*) FROM transactions t JOIN products p USING (product_id) "
            "WHERE t.transaction_date::DATE < p.opening_date",
        )
        if early:
            failures.append(
                f"transactions before their product's opening_date: {early:,}"
            )
    if {"products", "customers"} <= loaded:
        early = _count(
            con,
            "SELECT count(*) FROM products p JOIN customers c USING (customer_id) "
            "WHERE p.opening_date < c.registration_date::DATE",
        )
        if early:
            failures.append(
                f"products opened before their customer registered: {early:,}"
            )
    if failures:
        raise LinkError("link checks failed: " + "; ".join(failures))
