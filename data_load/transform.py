"""Stage 2: raw CSVs -> typed, checked, repaired Parquet (spec sections 4.1 and 6).

schema.sql is the contract: every row is read as text and inserted into tables built
from that DDL, so DuckDB casts each column and enforces NOT NULL, CHECK and PRIMARY
KEY. DuckDB ignores varchar(n), so lengths are checked separately. Then the repairs
run, then the link checks; nothing reaches S3 or DSQL unless all of them pass.
"""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import duckdb

from data_load import repair
from data_load.ddl import SchemaPlan, load_plan, varchar_limits
from data_load.source import EVENT_TABLES

EXPECTED = Path(__file__).with_name("expected.json")


class TransformError(RuntimeError):
    """A row broke schema.sql, a check failed, or counts differ from expected.json."""


@dataclass(frozen=True)
class Table:
    name: str
    path: Path
    rows: int
    sha256: str


def load_expected(path: Path = EXPECTED) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def source_glob(source: str, table: str) -> str:
    base = source.rstrip("/")
    if table in EVENT_TABLES:  # year=/month=/day=/<table>_<yyyymmdd>.csv
        return f"{base}/{table}/*/*/*/*.csv"
    return f"{base}/{table}.csv"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_raw(s3, bucket: str, run_id: str, dest: Path, workers: int = 16) -> int:
    """Mirror raw/<run-id>/ to dest, keeping the organizer's folder layout."""
    prefix = f"raw/{run_id}/"
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=prefix
    ):
        keys += [o["Key"] for o in page.get("Contents", [])]
    if not keys:
        raise TransformError(f"nothing under s3://{bucket}/{prefix}: run ingest first")

    def get(key: str) -> None:
        target = dest / key[len(prefix) :]
        target.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(bucket, key, str(target))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(get, keys))
    return len(keys)


def transform(
    source: str,
    out_dir: Path,
    *,
    plan: SchemaPlan | None = None,
    tables: list[str] | None = None,
    expected: dict | None = None,
) -> tuple[list[Table], dict]:
    """Return the Parquet files and the per-rule repair counts."""
    plan = plan or load_plan()
    names = [t for t in plan.data_tables if not tables or t in tables]
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "transform.duckdb"  # on disk: digital_events has 15.6M rows
    db_path.unlink(missing_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute("SET enable_progress_bar = false")  # keeps CodeBuild logs readable
    try:
        for name in names:
            _read_table(con, source, name, plan.data_tables[name])
        try:
            counts = repair.repair(con)
            repair.check_links(con)
        except (duckdb.Error, repair.LinkError) as e:
            raise TransformError(str(e)) from None
        rows = {
            n: con.execute(f"SELECT count(*) FROM {n}").fetchone()[0] for n in names
        }
        if expected is not None:
            _compare(expected, rows, counts)
        return [_write(con, out_dir, n, rows[n]) for n in names], counts
    finally:
        con.close()


def _read_table(con, source: str, name: str, ddl: str) -> None:
    con.execute(ddl)
    csv = (
        f"read_csv('{source_glob(source, name)}', header=true, all_varchar=true, "
        "union_by_name=true, hive_partitioning=false)"
    )
    try:
        con.execute(f"INSERT INTO {name} BY NAME SELECT * FROM {csv}")
    except duckdb.Error as e:
        raise TransformError(f"{name}: {e}") from None
    _check_lengths(con, name, ddl)
    rows = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
    print(f"read {name}: {rows:,} rows", flush=True)


def _check_lengths(con, name: str, ddl: str) -> None:
    limits = varchar_limits(ddl)
    if not limits:
        return
    over = con.execute(
        "SELECT "
        + ", ".join(
            f"count(*) FILTER (WHERE length({c}) > {n})" for c, n in limits.items()
        )
        + f" FROM {name}"
    ).fetchone()
    bad = [
        f"{c} longer than {n} in {k:,} rows"
        for (c, n), k in zip(limits.items(), over)
        if k
    ]
    if bad:
        raise TransformError(f"{name}: " + "; ".join(bad))


def _compare(expected: dict, rows: dict[str, int], counts: dict) -> None:
    diffs = [
        f"{name}: {n:,} rows, expected {expected['rows'].get(name)}"
        for name, n in rows.items()
        if expected["rows"].get(name) != n
    ]
    if counts != expected["repairs"]:
        diffs.append(f"repairs {counts}, expected {expected['repairs']}")
    if diffs:
        raise TransformError("differs from expected.json: " + "; ".join(diffs))


def _write(con, out_dir: Path, name: str, rows: int) -> Table:
    path = out_dir / f"{name}.parquet"
    con.execute(f"COPY {name} TO '{path.as_posix()}' (FORMAT parquet)")
    print(f"wrote {path.name}: {rows:,} rows", flush=True)
    return Table(name, path, rows, sha256_file(path))
