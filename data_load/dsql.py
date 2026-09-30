"""Everything that touches Aurora DSQL: schema, roles, grants, bulk load, indexes, lineage."""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import astuple, dataclass
from datetime import date, datetime

from data_load.ddl import SchemaPlan

LOADER = "aurora-dsql-loader"

INSERT_MANIFEST = (
    "INSERT INTO app.load_manifest (table_name, as_of, window_start, window_end, "
    "source_uri, source_files, source_etag_digest, staged_uri, staged_sha256, "
    "rows_staged, rows_loaded) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)


@dataclass(frozen=True)
class ManifestRow:
    table_name: str
    as_of: datetime
    window_start: date
    window_end: date
    source_uri: str
    source_files: int
    source_etag_digest: str
    staged_uri: str
    staged_sha256: str
    rows_staged: int


def connect(endpoint: str, profile: str | None = None):
    """Connect as admin; autocommit because DSQL allows one DDL per transaction."""
    import aurora_dsql_psycopg as dsql  # lazy: unit tests don't need the driver

    params = {"host": endpoint, "user": "admin"}
    if profile:
        params["profile"] = profile
    conn = dsql.connect(**params)
    conn.autocommit = True
    return conn


def schema_statements(plan: SchemaPlan) -> list[str]:
    """Step 3 DDL in order: bank/pii are recreated, app is created only if missing."""
    return [
        *plan.schemas,
        *(f"DROP VIEW IF EXISTS {view}" for view in plan.views),
        *(f"DROP TABLE IF EXISTS {table}" for table in plan.data_tables),
        *plan.data_tables.values(),
        *plan.views.values(),
        *plan.app_tables,
    ]


def apply_schema(conn, plan: SchemaPlan) -> None:
    with conn.cursor() as cur:
        for stmt in schema_statements(plan):
            cur.execute(stmt)
        cur.execute("SELECT rolname FROM pg_roles")
        existing_roles = {row[0] for row in cur.fetchall()}
        for role, stmt in plan.roles.items():
            if role not in existing_roles:
                cur.execute(stmt)
        for stmt in plan.grants:  # recreated tables lose their grants
            cur.execute(stmt)
        cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'app'")
        existing_indexes = {row[0] for row in cur.fetchall()}
    missing = [
        s for name, s in plan.app_indexes.items() if name not in existing_indexes
    ]
    build_indexes(conn, missing)


def build_indexes(conn, statements: list[str]) -> None:
    """Submit every CREATE INDEX ASYNC, then wait for each job."""
    with conn.cursor() as cur:
        jobs = []
        for stmt in statements:
            cur.execute(stmt)
            jobs.append((cur.fetchone()[0], stmt))
        for job_id, stmt in jobs:
            _wait_for_job(cur, job_id, stmt)


def _wait_for_job(cur, job_id: str, stmt: str) -> None:
    """sys.wait_for_job returns false on failure *or* timeout; sys.jobs tells them apart."""
    while True:
        cur.execute("SELECT sys.wait_for_job(%s)", (job_id,))
        if cur.fetchone()[0]:
            return
        cur.execute("SELECT status, details FROM sys.jobs WHERE job_id = %s", (job_id,))
        rows = cur.fetchall()
        status, details = rows[0] if rows else ("missing", "job not found")
        if status == "completed":
            return
        if status not in ("submitted", "processing"):
            raise RuntimeError(
                f"index build failed (job {job_id}, {status}: {details}): {stmt}"
            )


def loader_cmd(endpoint: str, uri: str, table: str) -> list[str]:
    schema, name = table.split(".")
    return [
        LOADER,
        "load",
        "--endpoint",
        endpoint,
        "--source-uri",
        uri,
        "--schema",
        schema,
        "--table",
        name,
        "--on-conflict",
        "do-nothing",
        "--verify",
        "count",
    ]


def load_all(
    endpoint: str, uris: dict[str, str], run=subprocess.run, parallel: int = 4
) -> None:
    """Load every staged file; once all have finished, fail if any table failed."""

    def load_one(table: str) -> str | None:
        try:
            run(loader_cmd(endpoint, uris[table], table), check=True)
        except subprocess.CalledProcessError as e:
            return f"{table} (exit {e.returncode})"
        return None

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        failed = [f for f in pool.map(load_one, uris) if f]
    if failed:
        raise RuntimeError("aurora-dsql-loader failed for: " + ", ".join(failed))


def record_manifest(conn, rows: list[ManifestRow]) -> None:
    """Check every table's count first; record lineage only if all of them match."""
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(f"SELECT count(*) FROM {row.table_name}")
            loaded = cur.fetchone()[0]
            if loaded != row.rows_staged:
                raise RuntimeError(
                    f"{row.table_name}: {loaded:,} rows in DSQL, {row.rows_staged:,} staged"
                )
        for row in rows:
            with conn.transaction():
                cur.execute(
                    "DELETE FROM app.load_manifest WHERE table_name = %s AND as_of = %s",
                    (row.table_name, row.as_of),
                )
                cur.execute(INSERT_MANIFEST, (*astuple(row), row.rows_staged))


def recorded_digests(conn) -> dict[str, str]:
    """table -> source ETag digest, for the most recent as_of."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name, source_etag_digest FROM app.load_manifest "
            "WHERE as_of = (SELECT max(as_of) FROM app.load_manifest)"
        )
        return dict(cur.fetchall())
