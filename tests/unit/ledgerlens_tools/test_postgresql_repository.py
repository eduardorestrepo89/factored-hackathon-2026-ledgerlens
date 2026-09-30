"""Tests for PostgreSQLRepository: rows, error mapping and the single retry."""

import psycopg
import pytest
from ledgerlens.application.ports.errors import (
    DataSourceConnectionError,
    QueryExecutionError,
    QueryTimeoutError,
)
from ledgerlens.infrastructure.repositories.postgresql_repository import (
    PostgreSQLRepository,
)
from ledgerlens_fakes import FakeConnector, make_row

pytestmark = pytest.mark.unit

QUERY = "SELECT * FROM transactions WHERE customer_id = %(customer_id)s"
PARAMS = {"customer_id": "CUST-1"}


def test_returns_rows_as_dicts_and_passes_query_and_params() -> None:
    connector = FakeConnector([make_row()])

    rows = PostgreSQLRepository(connector).execute_query(QUERY, PARAMS)

    assert rows == [make_row()]
    assert connector.connections[0].cursors[0].executed == [(QUERY, PARAMS)]


def test_statement_timeout_raises_query_timeout_without_retry() -> None:
    cancelled = psycopg.errors.QueryCanceled("canceling statement due to timeout")
    connector = FakeConnector(cancelled)

    with pytest.raises(QueryTimeoutError) as caught:
        PostgreSQLRepository(connector).execute_query(QUERY, PARAMS)

    assert caught.value.__cause__ is cancelled
    assert connector.reset_calls == 0
    assert len(connector.connections) == 1


@pytest.mark.parametrize(
    "error",
    [
        psycopg.errors.UndefinedTable('relation "transactions" does not exist'),
        psycopg.ProgrammingError("bad query"),
        psycopg.DataError("invalid input syntax"),
    ],
)
def test_other_psycopg_errors_raise_query_execution_error(
    error: psycopg.Error,
) -> None:
    connector = FakeConnector(error)

    with pytest.raises(QueryExecutionError) as caught:
        PostgreSQLRepository(connector).execute_query(QUERY, PARAMS)

    assert caught.value.__cause__ is error
    assert connector.reset_calls == 0


def test_operational_error_resets_and_retries_once_then_succeeds() -> None:
    connector = FakeConnector(
        psycopg.OperationalError("server closed the connection"), [make_row()]
    )

    rows = PostgreSQLRepository(connector).execute_query(QUERY, PARAMS)

    assert rows == [make_row()]
    assert connector.reset_calls == 1
    assert len(connector.connections) == 2


def test_second_operational_error_raises_data_source_connection_error() -> None:
    lost = psycopg.OperationalError("server closed the connection")
    connector = FakeConnector(lost)

    with pytest.raises(DataSourceConnectionError) as caught:
        PostgreSQLRepository(connector).execute_query(QUERY, PARAMS)

    assert caught.value.__cause__ is lost
    assert connector.reset_calls == 2
    assert len(connector.connections) == 2


def test_connector_failure_propagates_unchanged() -> None:
    failure = DataSourceConnectionError("secret unreadable")
    connector = FakeConnector(failure)

    with pytest.raises(DataSourceConnectionError) as caught:
        PostgreSQLRepository(connector).execute_query(QUERY, PARAMS)

    assert caught.value is failure
