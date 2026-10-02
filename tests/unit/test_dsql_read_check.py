"""Stage 4 read check: ll_read reads every table and is refused an INSERT."""

import importlib.util
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest

_LAMBDA = (
    Path(__file__).resolve().parents[2]
    / "infra-cdk"
    / "lambdas"
    / "dsql-read-check"
    / "index.py"
)
spec = importlib.util.spec_from_file_location("dsql_read_check", _LAMBDA)
read_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(read_check)


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.rows = conn, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append(sql)
        if sql.startswith("INSERT") and not self.conn.insert_allowed:
            raise psycopg.errors.InsufficientPrivilege(
                "permission denied for table branches"
            )
        table = sql.split()[3] if sql.startswith("SELECT 1 FROM") else None
        self.rows = [] if table in self.conn.empty else [(1,)]

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, insert_allowed=False, empty=()):
        self.executed, self.insert_allowed, self.empty = [], insert_allowed, set(empty)
        self.transactions = 0

    def cursor(self):
        return FakeCursor(self)

    @contextmanager
    def transaction(self):
        self.transactions += 1
        yield

    def close(self):
        pass


@pytest.mark.unit
def test_reads_every_table_and_is_refused_an_insert():
    conn = FakeConn()
    assert read_check.check(conn) == {"tables_read": 13, "insert_denied": True}
    reads = [s for s in conn.executed if s.startswith("SELECT")]
    assert len(reads) == 13
    assert conn.transactions == 1  # the INSERT attempt runs inside a transaction


@pytest.mark.unit
def test_an_allowed_insert_fails_the_check():
    with pytest.raises(RuntimeError, match="could INSERT"):
        read_check.check(FakeConn(insert_allowed=True))


@pytest.mark.unit
def test_an_empty_table_fails_the_check():
    with pytest.raises(RuntimeError, match="complaints is empty"):
        read_check.check(FakeConn(empty={"complaints"}))


@pytest.mark.unit
def test_handler_logs_in_as_ll_read_at_the_private_host(monkeypatch):
    seen = {}

    def connect(**kwargs):
        seen.update(kwargs)
        return FakeConn()

    monkeypatch.setattr(read_check.dsql, "connect", connect)
    monkeypatch.setenv("DSQL_HOST", "abc.dsql-fnh4.us-east-1.on.aws")
    assert read_check.handler({}, None)["insert_denied"] is True
    assert seen == {
        "host": "abc.dsql-fnh4.us-east-1.on.aws",
        "user": "ll_read",
        "autocommit": True,
    }
