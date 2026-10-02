"""DSQL steps, tested against a fake connection (no cluster needed)."""

import subprocess
from contextlib import contextmanager

import pytest

from data_load.ddl import load_plan
from data_load.dsql import (
    apply_schema,
    build_indexes,
    load_all,
    loader_cmd,
    schema_statements,
)

TOOLS_ROLE = "arn:aws:iam::111111111111:role/ledgerlens-tools"


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.rows = conn, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))
        self.rows = self.conn.respond(sql)

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, respond=lambda sql: []):
        self.executed, self.respond = [], respond

    def cursor(self):
        return FakeCursor(self)

    @contextmanager
    def transaction(self):
        yield

    def sql(self):
        return [s for s, _ in self.executed]


def existing(roles=(), mappings=()):
    def respond(sql):
        if sql.startswith("SELECT rolname"):
            return [(r,) for r in roles]
        if "sys.iam_pg_role_mappings" in sql:
            return [(arn,) for arn in mappings]
        return []

    return respond


@pytest.mark.unit
def test_schema_statements_drop_then_create_every_table():
    plan = load_plan()
    stmts = schema_statements(plan)
    assert len(stmts) == 26
    for table, ddl in plan.data_tables.items():
        assert stmts.index(f"DROP TABLE IF EXISTS {table}") < stmts.index(ddl)


@pytest.mark.unit
def test_first_load_creates_the_role_maps_it_and_grants():
    plan, conn = load_plan(), FakeConn(existing())
    apply_schema(conn, plan, TOOLS_ROLE)
    sql = conn.sql()
    assert "CREATE ROLE ll_read WITH LOGIN" in sql
    assert f"AWS IAM GRANT ll_read TO '{TOOLS_ROLE}'" in sql
    assert sql.index(f"AWS IAM GRANT ll_read TO '{TOOLS_ROLE}'") < sql.index(
        plan.grants[0]
    )
    assert sql[-len(plan.grants) :] == plan.grants  # last: they must see the new tables


@pytest.mark.unit
def test_reload_keeps_the_role_and_mapping_but_regrants():
    plan = load_plan()
    conn = FakeConn(existing(roles=["ll_read"], mappings=[TOOLS_ROLE]))
    apply_schema(conn, plan, TOOLS_ROLE)
    sql = conn.sql()
    assert not any(s.startswith(("CREATE ROLE", "AWS IAM GRANT")) for s in sql)
    assert sql[-len(plan.grants) :] == plan.grants


@pytest.mark.unit
@pytest.mark.parametrize(
    "arn",
    [
        "",
        "ledgerlens-tools",
        "arn:aws:iam::111111111111:role/x'; DROP TABLE customers; --",
    ],
)
def test_a_bad_role_arn_is_refused_before_any_sql(arn):
    conn = FakeConn(existing())
    with pytest.raises(ValueError, match="not an IAM role ARN"):
        apply_schema(conn, load_plan(), arn)
    assert conn.sql() == []


@pytest.mark.unit
def test_build_indexes_fails_when_a_job_fails():
    def respond(sql):
        if sql.startswith("CREATE INDEX"):
            return [("job-9",)]
        return [("failed", "Found duplicate key")]  # sys.jobs

    with pytest.raises(RuntimeError, match="job-9, failed: Found duplicate key"):
        build_indexes(
            FakeConn(respond),
            ["CREATE INDEX ASYNC i ON products (customer_id)"],
            sleep=lambda seconds: None,
        )


@pytest.mark.unit
def test_build_indexes_polls_sys_jobs_until_complete():
    statuses = iter([[("processing", None)], [("completed", None)]])

    def respond(sql):
        return [("job-1",)] if sql.startswith("CREATE INDEX") else next(statuses)

    conn, sleeps = FakeConn(respond), []
    build_indexes(
        conn, ["CREATE INDEX ASYNC i ON products (customer_id)"], sleep=sleeps.append
    )
    assert sleeps == [10]
    # short polls only: a long sys.wait_for_job could outlive DSQL's 5-min transaction limit
    assert not any("wait_for_job" in s for s in conn.sql())


@pytest.mark.unit
def test_loader_cmd_targets_public():
    assert loader_cmd(
        "c.dsql.us-east-1.on.aws", "s3://t/clean/r/transactions.parquet", "transactions"
    ) == [
        "aurora-dsql-loader",
        "load",
        "--endpoint",
        "c.dsql.us-east-1.on.aws",
        "--source-uri",
        "s3://t/clean/r/transactions.parquet",
        "--schema",
        "public",
        "--table",
        "transactions",
        "--on-conflict",
        "do-nothing",
        "--verify",
        "count",
    ]


@pytest.mark.unit
def test_loader_dry_run_cmd_validates_without_loading():
    assert loader_cmd(
        "c.dsql.us-east-1.on.aws", "s3://t/x.parquet", "branches", dry_run=True
    )[-5:] == ["--schema", "public", "--table", "branches", "--dry-run"]


@pytest.mark.unit
def test_load_all_fails_after_every_table_was_attempted():
    attempted = []

    def fake_run(cmd, check):
        table = cmd[cmd.index("--table") + 1]
        attempted.append(table)
        if table == "transactions":
            raise subprocess.CalledProcessError(2, cmd)

    uris = {
        "digital_events": "s3://t/a",
        "transactions": "s3://t/b",
        "customers": "s3://t/c",
    }
    with pytest.raises(RuntimeError, match=r"transactions \(exit 2\)") as err:
        load_all("c.dsql.us-east-1.on.aws", uris, run=fake_run)
    assert sorted(attempted) == ["customers", "digital_events", "transactions"]
    assert "digital_events" not in str(err.value)


@pytest.mark.unit
def test_dsql_driver_imports():
    """requirements.txt must install everything aurora_dsql_psycopg imports."""
    import aurora_dsql_psycopg

    assert callable(aurora_dsql_psycopg.connect)
