"""Tiny organizer-style CSV trees for data_load tests.

Files are written the way the organizer's are: UTF-8 with a BOM and CRLF endings.
"""

from pathlib import Path

TX_HEADER = [
    "transaction_id",
    "transaction_date",
    "process_date",
    "product_id",
    "customer_id",
    "transaction_type",
    "amount",
    "currency",
    "channel",
    "transaction_country",
    "transaction_status",
    "response_code",
    "is_fraud",
]


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(header)] + [",".join(row) for row in rows]
    path.write_bytes(("﻿" + "\r\n".join(lines) + "\r\n").encode("utf-8"))


def tx(
    transaction_id: str, transaction_date: str, process_date: str, code: str = "00"
) -> list[str]:
    return [
        transaction_id,
        transaction_date,
        process_date,
        "PRD-1",
        "CLI-1",
        "Compra",
        "10.50",
        "USD",
        "App",
        "México",
        "Approved",
        code,
        "False",
    ]


def write_transactions(root: Path, rows: list[list[str]]) -> None:
    """One file per process_date partition, like data/transactions/year=/month=/day=/."""
    by_day: dict[str, list[list[str]]] = {}
    for row in rows:
        by_day.setdefault(row[2], []).append(row)
    for day, day_rows in by_day.items():
        y, m, d = day.split("-")
        name = f"transactions_{y}{m}{d}.csv"
        write_csv(
            root / "transactions" / f"year={y}" / f"month={m}" / f"day={d}" / name,
            TX_HEADER,
            day_rows,
        )
