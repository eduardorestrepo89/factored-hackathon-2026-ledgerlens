"""Stage curate: clean/ Parquet -> curated/ Parquet (curate spec, section 4).

The C-rules fix every row, then the selection keeps ~1,500 coherent customers plus a
defect cohort whose rows are written as transform left them (snapshotted before the rules).
Nothing reaches S3 or DSQL unless every check passes.
"""

from pathlib import Path

import duckdb

from data_load import curate_rules, curate_select, repair
from data_load.curate_rules import CurationError
from data_load.ddl import load_plan
from data_load.repair import _count
from data_load.transform import Table, _write, sha256_file

AS_OF = "2026-06-17T23:59:59"
RULE_TABLES = (
    "customers",
    "products",
    "transactions",
    "complaints",
)  # what C1-C12 change
LINKED = (  # filtered by customer_id; anonymous digital events go too
    "customers",
    "products",
    "transactions",
    "complaints",
    "call_center_interactions",
    "digital_events",
    "campaign_sends",
)
VIA_INTERACTION = ("call_transcripts", "satisfaction_surveys")


def download_clean(s3, bucket: str, staged: dict, dest: Path) -> None:
    """Fetch transform's Parquet files into dest, checking each against its SHA-256."""
    dest.mkdir(parents=True, exist_ok=True)
    for table, meta in staged.items():
        path = dest / f"{table}.parquet"
        s3.download_file(bucket, meta["uri"].split(f"s3://{bucket}/", 1)[1], str(path))
        if sha256_file(path) != meta["sha256"]:
            raise CurationError(
                f"{table}: Parquet differs from transform.json's SHA-256"
            )


def curate(
    source: str,
    out_dir: Path,
    *,
    customers: int = 1500,
    per_class: int = 20,
    personas: dict | None = None,
    expected: dict | None = None,
) -> tuple[list[Table], dict]:
    """Return the curated Parquet files and the record for curate.json (without "tables")."""
    if customers <= 0 or customers % 12:
        raise CurationError(
            f"customers must be a positive multiple of 12, got {customers}"
        )
    personas = curate_select.load_personas() if personas is None else personas
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "curate.duckdb"  # on disk: digital_events has 15.6M rows
    db_path.unlink(missing_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute("SET enable_progress_bar = false")  # keeps CodeBuild logs readable
    try:
        names = [
            t
            for t in load_plan().data_tables
            if (Path(source) / f"{t}.parquet").exists()
        ]
        for name in names:
            path = (Path(source) / f"{name}.parquet").as_posix()
            con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{path}')")
        rows_in = {n: _count(con, f"SELECT count(*) FROM {n}") for n in names}
        curate_rules.check_evidence(con)
        curate_select.register_personas(con, personas)
        curate_select.build_profile(con)  # before the rules: ranks the defect cohort
        curate_select.defect_evidence(con)
        defects = curate_select.select_cohort(con, per_class)
        for t in RULE_TABLES:
            con.execute(
                f"CREATE TEMP TABLE snap_{t} AS SELECT * FROM {t} "
                "WHERE customer_id IN (SELECT customer_id FROM cohort)"
            )
        rules = curate_rules.apply_rules(con)
        print(f"rules {rules}", flush=True)
        curate_select.build_profile(con)  # after the rules: gates and score
        selection = curate_select.select_clean(con, personas, customers // 12)
        _assemble(con)
        _check(con, defects["customers"])
        rows = {n: _count(con, f"SELECT count(*) FROM {n}") for n in names}
        full = expected is not None and rows_in == expected.get("rows")
        if full and "curation" in expected and (customers, per_class) == (1500, 20):
            _compare(expected["curation"], rules, rows)
        record = {
            "as_of": AS_OF,
            "rules": rules,
            "selection": selection,
            "defects": defects,
        }
        return [_write(con, out_dir, n, rows[n]) for n in names], record
    finally:
        con.close()


def _assemble(con) -> None:
    """Keep the clean and cohort customers; the cohort's rule-table rows come from the snapshot."""
    con.execute(
        "CREATE OR REPLACE TEMP TABLE keep AS "
        "SELECT customer_id FROM clean UNION SELECT customer_id FROM cohort"
    )
    for t in RULE_TABLES:
        con.execute(
            f"DELETE FROM {t} WHERE customer_id IN (SELECT customer_id FROM cohort)"
        )
        con.execute(f"INSERT INTO {t} SELECT * FROM snap_{t}")
    for t in LINKED:
        con.execute(
            f"CREATE OR REPLACE TABLE {t} AS SELECT * FROM {t} "
            "WHERE customer_id IN (SELECT customer_id FROM keep)"
        )
    for t in VIA_INTERACTION:
        con.execute(
            f"CREATE OR REPLACE TABLE {t} AS SELECT * FROM {t} "
            "WHERE interaction_id IN (SELECT interaction_id FROM call_center_interactions)"
        )


def _check(con, cohort_customers: dict) -> None:
    """Fail, naming every broken check, unless the curated tables hold together (spec 8)."""
    failures = [
        f"{rule}: {n:,} rows of clean customers break it"
        for rule, n in curate_rules.check_invariants(
            con, "SELECT customer_id FROM clean"
        ).items()
        if n
    ]
    curate_select.build_profile(con)
    ungated = _count(
        con,
        "SELECT count(*) FROM clean JOIN profile USING (customer_id) "
        f"WHERE NOT ({curate_select.ELIGIBLE})",
    )
    if ungated:
        failures.append(f"{ungated} selected customers fail a gate")
    lost = curate_select.lost_defects(con, cohort_customers)
    if lost:
        failures.append(f"cohort lost {len(lost)} defects: {', '.join(lost[:5])}")
    both = _count(
        con,
        "SELECT count(*) FROM clean WHERE customer_id IN (SELECT customer_id FROM cohort)",
    )
    if both:
        failures.append(f"{both} customers are both clean and in the cohort")
    try:
        repair.check_links(con)
    except repair.LinkError as e:
        failures.append(str(e))
    if failures:
        raise CurationError("curation checks failed: " + "; ".join(failures))


def _compare(expected: dict, rules: dict, rows: dict) -> None:
    diffs = []
    if rules != expected["rules"]:
        diffs.append(f"rules {rules}, expected {expected['rules']}")
    if rows != expected["rows"]:
        diffs.append(f"rows {rows}, expected {expected['rows']}")
    if diffs:
        raise CurationError("differs from expected.json curation: " + "; ".join(diffs))
