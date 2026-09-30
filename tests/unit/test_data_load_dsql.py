"""DSQL steps, tested against a fake connection (no cluster needed)."""

import subprocess
from contextlib import contextmanager
from datetime import date, datetime

import pytest

from data_load.ddl import load_plan
from data_load.dsql import (
    ManifestRow,
    apply_schema,
    build_indexes,
    load_all,
    loader_cmd,
    record_manifest,
    schema_statements,
)


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
        self.executed, self.respond, self.transactions = [], respond, 0

    def cursor(self):
        return FakeCursor(self)

    @contextmanager
    def transaction(self):
        self.transactions += 1
        yield

    def sql(self):
        return [s for s, _ in self.executed]


def manifest_row(table="bank.transactions", rows=10):
    return ManifestRow(
        table,
        datetime(2026, 6, 17, 23, 59, 59),
        date(2024, 6, 18),
        date(2026, 6, 17),
        "s3://org/data/transactions/",
        1097,
        "d" * 64,
        "s3://team/staging/t.parquet",
        "s" * 64,
        rows,
    )


@pytest.mark.unit
def test_schema_statements_recreate_organizer_tables_and_keep_app():
    plan = load_plan()
    stmts = schema_statements(plan)
    first = stmts.index
    assert first("DROP VIEW IF EXISTS bank.customer_profile") < first(
        "DROP TABLE IF EXISTS pii.customers"
    )
    assert first("DROP TABLE IF EXISTS pii.customers") < first(
        plan.data_tables["pii.customers"]
    )
    assert first(plan.data_tables["pii.customers"]) < first(
        plan.views["bank.customer_profile"]
    )
    assert not any(s.startswith("DROP TABLE IF EXISTS app.") for s in stmts)
    assert all(s in stmts for s in plan.app_tables)


@pytest.mark.unit
def test_apply_schema_is_rerunnable():
    def respond(sql):
        if sql.startswith("SELECT rolname"):
            return [("ll_read",), ("ll_write",)]
        if sql.startswith("SELECT indexname"):
            return [("idx_cases_customer_date",)]
        if sql.startswith("CREATE INDEX ASYNC"):
            return [("job-1",)]
        if "FROM sys.jobs" in sql:
            return [("completed", None)]
        return []

    plan, conn = load_plan(), FakeConn(respond)
    apply_schema(conn, plan)
    sql = conn.sql()
    assert "CREATE ROLE ll_read WITH LOGIN" not in sql
    assert "CREATE ROLE ll_approvals WITH LOGIN" in sql
    assert all(g in sql for g in plan.grants)
    created = [s for s in sql if s.startswith("CREATE INDEX ASYNC")]
    assert created == [plan.app_indexes["idx_claims_customer_date"]]


@pytest.mark.unit
def test_build_indexes_fails_when_a_job_fails():
    def respond(sql):
        if sql.startswith("CREATE INDEX"):
            return [("job-9",)]
        return [("failed", "Found duplicate key")]  # sys.jobs

    with pytest.raises(RuntimeError, match="job-9, failed: Found duplicate key"):
        build_indexes(
            FakeConn(respond),
            ["CREATE INDEX ASYNC i ON bank.products (customer_id)"],
            sleep=lambda seconds: None,
        )


@pytest.mark.unit
def test_build_indexes_polls_sys_jobs_until_complete():
    statuses = iter([[("processing", None)], [("completed", None)]])

    def respond(sql):
        return [("job-1",)] if sql.startswith("CREATE INDEX") else next(statuses)

    conn, sleeps = FakeConn(respond), []
    build_indexes(
        conn,
        ["CREATE INDEX ASYNC i ON bank.products (customer_id)"],
        sleep=sleeps.append,
    )
    assert sleeps == [10]
    # short polls only: a long sys.wait_for_job could outlive DSQL's 5-min transaction limit
    assert not any("wait_for_job" in s for s in conn.sql())


@pytest.mark.unit
def test_loader_cmd():
    assert loader_cmd(
        "c.dsql.us-east-1.on.aws",
        "s3://t/staging/x/transactions.parquet",
        "bank.transactions",
    ) == [
        "aurora-dsql-loader",
        "load",
        "--endpoint",
        "c.dsql.us-east-1.on.aws",
        "--source-uri",
        "s3://t/staging/x/transactions.parquet",
        "--schema",
        "bank",
        "--table",
        "transactions",
        "--on-conflict",
        "do-nothing",
        "--verify",
        "count",
    ]


@pytest.mark.unit
def test_load_all_fails_after_every_table_was_attempted():
    attempted = []

    def fake_run(cmd, check):
        table = cmd[cmd.index("--table") + 1]
        attempted.append(table)
        if table == "transactions":
            raise subprocess.CalledProcessError(2, cmd)

    uris = {
        "bank.digital_events": "s3://t/a",
        "bank.transactions": "s3://t/b",
        "pii.customers": "s3://t/c",
    }
    with pytest.raises(RuntimeError, match=r"bank\.transactions \(exit 2\)") as err:
        load_all("c.dsql.us-east-1.on.aws", uris, run=fake_run)
    assert sorted(attempted) == ["customers", "digital_events", "transactions"]
    assert "digital_events" not in str(err.value)


@pytest.mark.unit
def test_record_manifest_refuses_a_count_mismatch():
    conn = FakeConn(lambda sql: [(9,)])
    with pytest.raises(RuntimeError, match="9 rows in DSQL, 10 staged"):
        record_manifest(conn, [manifest_row(rows=10)])
    assert not any(s.startswith(("DELETE", "INSERT")) for s in conn.sql())


@pytest.mark.unit
def test_record_manifest_replaces_one_row_per_table():
    conn = FakeConn(lambda sql: [(10,)])
    record_manifest(
        conn, [manifest_row("bank.transactions"), manifest_row("bank.products")]
    )
    writes = [
        (s.split()[0], p)
        for s, p in conn.executed
        if s.startswith(("DELETE", "INSERT"))
    ]
    assert [w[0] for w in writes] == ["DELETE", "INSERT", "DELETE", "INSERT"]
    assert (
        writes[1][1][0] == "bank.transactions" and writes[1][1][-1] == 10
    )  # rows_loaded
    assert conn.transactions == 2


@pytest.mark.unit
def test_loader_dry_run_cmd_validates_without_loading():
    assert loader_cmd(
        "c.dsql.us-east-1.on.aws", "s3://t/x.parquet", "bank.branches", dry_run=True
    ) == [
        "aurora-dsql-loader",
        "load",
        "--endpoint",
        "c.dsql.us-east-1.on.aws",
        "--source-uri",
        "s3://t/x.parquet",
        "--schema",
        "bank",
        "--table",
        "branches",
        "--dry-run",
    ]


@pytest.mark.unit
def test_dsql_driver_imports():
    """requirements.txt must install everything aurora_dsql_psycopg imports."""
    import aurora_dsql_psycopg

    assert callable(aurora_dsql_psycopg.connect)
