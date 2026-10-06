"""Everything that touches Aurora DSQL: tables, the tool roles and their IAM mappings, bulk load, indexes."""

import re
import subprocess
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor

from data_load.ddl import SchemaPlan

LOADER = "aurora-dsql-loader"
POLL_SECONDS = 10
READ_ROLE = "ll_read"  # the read tools, IAM role ledgerlens-tools
WRITE_ROLE = (
    "ll_write"  # block_credit_card and open_claim, IAM role ledgerlens-write-tools
)
ROLE_ARN = re.compile(r"arn:aws:iam::\d{12}:role/[\w+=,.@/-]+")


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
    """Every load recreates the 13 tables: DSQL has no TRUNCATE (spec section 5.4)."""
    return [
        *(f"DROP TABLE IF EXISTS {table}" for table in plan.data_tables),
        *plan.data_tables.values(),
    ]


def apply_schema(conn, plan: SchemaPlan, role_arns: Mapping[str, str]) -> None:
    """Recreate the tables, then apply_access: the roles, their IAM mappings, the grants."""
    _check_role_arns(
        plan, role_arns
    )  # before the drops: a bad ARN must not cost the tables
    with conn.cursor() as cur:
        for stmt in schema_statements(plan):
            cur.execute(stmt)
    apply_access(conn, plan, role_arns)


def apply_access(conn, plan: SchemaPlan, role_arns: Mapping[str, str]) -> None:
    """Create missing roles and IAM mappings, then re-run every grant. Drops nothing.

    ``role_arns`` maps every role in schema.sql to the IAM role it is granted to:
    ll_read -> ledgerlens-tools, ll_write -> ledgerlens-write-tools. The access
    stage calls this alone, to add a role to a loaded cluster.
    """
    _check_role_arns(plan, role_arns)
    with conn.cursor() as cur:
        cur.execute("SELECT rolname FROM pg_roles")
        existing_roles = {row[0] for row in cur.fetchall()}
        for role, stmt in plan.roles.items():
            if role not in existing_roles:
                cur.execute(stmt)
        for role in plan.roles:
            cur.execute(
                "SELECT arn FROM sys.iam_pg_role_mappings WHERE pg_role_name = %s",
                (role,),
            )
            if role_arns[role] not in {row[0] for row in cur.fetchall()}:
                cur.execute(f"AWS IAM GRANT {role} TO '{role_arns[role]}'")
        for stmt in plan.grants:  # recreated tables lose their grants
            cur.execute(stmt)


def _check_role_arns(plan: SchemaPlan, role_arns: Mapping[str, str]) -> None:
    """Every role needs a well-formed IAM role ARN: it is spliced into AWS IAM GRANT."""
    for role in plan.roles:
        arn = role_arns.get(role, "")
        if not ROLE_ARN.fullmatch(arn):
            raise ValueError(f"not an IAM role ARN for {role}: {arn!r}")


def build_indexes(conn, statements: list[str], sleep=time.sleep) -> None:
    """Submit every CREATE INDEX ASYNC, then wait for each job."""
    with conn.cursor() as cur:
        jobs = []
        for stmt in statements:
            cur.execute(stmt)
            jobs.append((cur.fetchone()[0], stmt))
        for job_id, stmt in jobs:
            _wait_for_job(cur, job_id, stmt, sleep)


def _wait_for_job(cur, job_id: str, stmt: str, sleep) -> None:
    """Poll sys.jobs with short statements: a long sys.wait_for_job call could
    outlive DSQL's 5-minute transaction limit on a big index."""
    while True:
        cur.execute("SELECT status, details FROM sys.jobs WHERE job_id = %s", (job_id,))
        rows = cur.fetchall()
        status, details = rows[0] if rows else ("missing", "job not found")
        if status == "completed":
            return
        if status not in ("submitted", "processing"):
            raise RuntimeError(
                f"index build failed (job {job_id}, {status}: {details}): {stmt}"
            )
        sleep(POLL_SECONDS)


def loader_cmd(endpoint: str, uri: str, table: str, dry_run: bool = False) -> list[str]:
    cmd = [LOADER, "load", "--endpoint", endpoint, "--source-uri", uri]
    cmd += ["--schema", "public", "--table", table]
    if (
        dry_run
    ):  # checks the file against the table without loading: seconds, not an hour
        return [*cmd, "--dry-run"]
    return [*cmd, "--on-conflict", "do-nothing", "--verify", "count"]


def load_all(
    endpoint: str,
    uris: dict[str, str],
    run=subprocess.run,
    parallel: int = 4,
    dry_run: bool = False,
) -> None:
    """Load (or dry-run) every Parquet file; once all finish, fail if any table failed."""

    def load_one(table: str) -> str | None:
        try:
            run(loader_cmd(endpoint, uris[table], table, dry_run), check=True)
        except subprocess.CalledProcessError as e:
            return f"{table} (exit {e.returncode})"
        return None

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        failed = [f for f in pool.map(load_one, uris) if f]
    if failed:
        step = "dry run" if dry_run else "load"
        raise RuntimeError(
            f"aurora-dsql-loader {step} failed for: " + ", ".join(failed)
        )
