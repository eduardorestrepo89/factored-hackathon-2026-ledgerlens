"""Tests for DsqlRepository: rows, error mapping and the single retry."""

import psycopg
import pytest
from ledgerlens.application.ports.errors import (
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
)
from ledgerlens.infrastructure.repositories.dsql_repository import DsqlRepository
from ledgerlens_fakes import FakeConnector, make_row

pytestmark = pytest.mark.unit

QUERY = "SELECT * FROM transactions WHERE customer_id = %(customer_id)s"
PARAMS = {"customer_id": "CUST-1"}


def test_returns_rows_as_dicts_and_passes_query_and_params() -> None:
    connector = FakeConnector([make_row()])

    rows = DsqlRepository(connector).execute_query(QUERY, PARAMS)

    assert rows == [make_row()]
    assert connector.connections[0].cursors[0].executed == [(QUERY, PARAMS)]


@pytest.mark.parametrize(
    "error",
    [
        psycopg.errors.OutOfMemory("query exceeded the 128 MiB limit (53200)"),
        psycopg.errors.ProgramLimitExceeded("transaction age limit of 300s (54000)"),
        psycopg.errors.QueryCanceled("canceling statement (57014)"),
    ],
)
def test_dsql_limit_errors_raise_query_limit_exceeded_without_retry(
    error: psycopg.Error,
) -> None:
    # Each one is an OperationalError subclass: it must not hit the retry branch.
    assert isinstance(error, psycopg.OperationalError)
    connector = FakeConnector(error)

    with pytest.raises(QueryLimitExceededError) as caught:
        DsqlRepository(connector).execute_query(QUERY, PARAMS)

    assert caught.value.__cause__ is error
    assert connector.reset_calls == 0
    assert len(connector.connections) == 1
    assert len(connector.connections[0].cursors) == 1


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
        DsqlRepository(connector).execute_query(QUERY, PARAMS)

    assert caught.value.__cause__ is error
    assert connector.reset_calls == 0


def test_operational_error_resets_and_retries_once_then_succeeds() -> None:
    connector = FakeConnector(
        psycopg.OperationalError("server closed the connection"), [make_row()]
    )

    rows = DsqlRepository(connector).execute_query(QUERY, PARAMS)

    assert rows == [make_row()]
    assert connector.reset_calls == 1
    assert len(connector.connections) == 2


def test_second_operational_error_raises_data_source_connection_error() -> None:
    lost = psycopg.OperationalError("server closed the connection")
    connector = FakeConnector(lost)

    with pytest.raises(DataSourceConnectionError) as caught:
        DsqlRepository(connector).execute_query(QUERY, PARAMS)

    assert caught.value.__cause__ is lost
    assert connector.reset_calls == 2
    assert len(connector.connections) == 2


def test_connector_failure_propagates_as_data_source_connection_error() -> None:
    failure = DataSourceConnectionError("no route to host")
    connector = FakeConnector(failure)

    with pytest.raises(DataSourceConnectionError) as caught:
        DsqlRepository(connector).execute_query(QUERY, PARAMS)

    assert caught.value.__cause__ is failure
    assert connector.reset_calls == 0
