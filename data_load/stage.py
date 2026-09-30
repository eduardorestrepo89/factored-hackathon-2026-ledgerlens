"""Stage organizer CSVs as typed, validated Parquet with DuckDB.

schema.sql is the contract: every row is read as text and inserted into tables built
from that DDL, so DuckDB casts each column and enforces NOT NULL, CHECK and PRIMARY
KEY before anything reaches AWS. Values are never changed; duplicates are errors.
"""

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

from data_load.ddl import SchemaPlan, load_plan

EVENT_TABLES = frozenset(
    {
        "call_center_interactions",
        "call_transcripts",
        "campaign_sends",
        "complaints",
        "digital_events",
        "satisfaction_surveys",
        "transactions",
    }
)
DATE_FILTERED = {"daily_exchange_rates": "date"}  # reference table cut to the window


class StageError(RuntimeError):
    """A source row broke schema.sql. The message names the table."""


@dataclass(frozen=True)
class Staged:
    table: str  # schema-qualified, e.g. "bank.transactions"
    path: Path
    rows: int
    sha256: str


def load_window(as_of: datetime, window_years: int) -> tuple[date, date]:
    """Event rows kept: process_date in [as_of::date - (365*years - 1), as_of::date]."""
    end = as_of.date()
    return end - timedelta(days=365 * window_years - 1), end


def source_glob(source: str, table: str) -> str:
    base = source.rstrip("/")
    if table in EVENT_TABLES:  # year=/month=/day=/<table>_<yyyymmdd>.csv
        return f"{base}/{table}/*/*/*/*.csv"
    return f"{base}/{table}.csv"


def window_filter(table: str, start: date, end: date) -> str:
    column = "process_date" if table in EVENT_TABLES else DATE_FILTERED.get(table)
    if column is None:
        return ""  # reference tables load in full: entity dates are not causal
    return f"WHERE {column}::DATE BETWEEN DATE '{start}' AND DATE '{end}'"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _create_s3_secret(con: duckdb.DuckDBPyConnection, s3: dict) -> None:
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    try:
        con.execute(
            "CREATE SECRET hackathon (TYPE s3, "
            f"KEY_ID {_sql_literal(s3['aws_access_key_id'])}, "
            f"SECRET {_sql_literal(s3['aws_secret_access_key'])}, "
            f"REGION {_sql_literal(s3['region'])}, "
            f"SCOPE {_sql_literal('s3://' + s3['bucket'])})"
        )
    except duckdb.Error:
        # never chain the original error: its message may quote the statement
        raise StageError(
            "could not create the DuckDB S3 secret from HACKATHON_S3"
        ) from None


def stage(
    source: str,
    out_dir: Path,
    as_of: datetime,
    window_years: int,
    *,
    s3: dict | None = None,
    plan: SchemaPlan | None = None,
    tables: list[str] | None = None,
) -> list[Staged]:
    plan = plan or load_plan()
    start, end = load_window(as_of, window_years)
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "stage.duckdb"  # on disk: digital_events has 10.3M rows
    db_path.unlink(missing_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        if s3:
            _create_s3_secret(con, s3)
        for stmt in plan.schemas:
            con.execute(stmt)
        return [
            _stage_table(con, source, out_dir, qname, ddl, start, end)
            for qname, ddl in plan.data_tables.items()
            if not tables or qname in tables
        ]
    finally:
        con.close()


def _stage_table(con, source, out_dir, qname, ddl, start, end) -> Staged:
    table = qname.split(".")[1]
    con.execute(ddl)
    csv = (
        f"read_csv('{source_glob(source, table)}', header=true, all_varchar=true, "
        "union_by_name=true, hive_partitioning=false)"
    )
    where = window_filter(table, start, end)
    try:
        con.execute(f"INSERT INTO {qname} BY NAME SELECT * FROM {csv} {where}")
    except duckdb.Error as e:
        raise StageError(f"{qname}: {e}") from None
    path = out_dir / f"{table}.parquet"
    con.execute(f"COPY {qname} TO '{path.as_posix()}' (FORMAT parquet)")
    rows = con.execute(f"SELECT count(*) FROM {qname}").fetchone()[0]
    print(f"staged {qname}: {rows:,} rows", flush=True)
    return Staged(qname, path, rows, sha256_file(path))
