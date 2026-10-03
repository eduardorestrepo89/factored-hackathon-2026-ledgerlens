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
