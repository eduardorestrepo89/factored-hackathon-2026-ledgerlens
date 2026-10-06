"""Tests for the PsycopgConnector base: caching, recycling, reset, failures."""

from datetime import timedelta
from typing import Any

import psycopg
import pytest
from classify_call_type_lambda.application.ports.errors import (
    DataSourceConnectionError,
)
from classify_call_type_lambda.utils.connectors.base import PsycopgConnector

from .fakes import FakeClock, FakeConnector

pytestmark = pytest.mark.unit

MAX_AGE = timedelta(minutes=55)


class FailingConnector(PsycopgConnector):
    """Connector whose _open() always raises ``failure``."""

    def __init__(self, failure: Exception) -> None:
        """Raise ``failure`` on every open."""
        super().__init__()
        self.failure = failure

    def _open(self) -> Any:
        """Fail to open."""
        raise self.failure


def test_base_class_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        PsycopgConnector()  # type: ignore[abstract]


def test_opens_lazily_and_reuses_the_open_connection() -> None:
    connector = FakeConnector()
    assert connector.connections == []

    first = connector.connection()

    assert connector.connection() is first
    assert connector.connections == [first]


def test_reopens_when_the_connection_is_closed() -> None:
    connector = FakeConnector()
    first = connector.connection()
    first.closed = True

    second = connector.connection()

    assert second is not first
    assert len(connector.connections) == 2


def test_recycles_a_connection_once_it_reaches_max_age() -> None:
    clock = FakeClock()
    connector = FakeConnector(max_age=MAX_AGE, clock=clock)
    first = connector.connection()

    clock.advance(MAX_AGE - timedelta(seconds=1))
    assert connector.connection() is first

    clock.advance(timedelta(seconds=1))
    second = connector.connection()

    assert second is not first
    assert first.closed is True
    assert connector.reset_calls == 1


def test_age_counts_from_the_latest_open() -> None:
    clock = FakeClock()
    connector = FakeConnector(max_age=MAX_AGE, clock=clock)
    connector.connection()
    clock.advance(MAX_AGE)
    second = connector.connection()

    clock.advance(MAX_AGE - timedelta(seconds=1))

    assert connector.connection() is second


def test_no_age_check_without_max_age() -> None:
    clock = FakeClock()
    connector = FakeConnector(clock=clock)
    first = connector.connection()

    clock.advance(timedelta(days=1))

    assert connector.connection() is first


def test_reset_closes_and_drops_the_connection() -> None:
    connector = FakeConnector()
    first = connector.connection()

    connector.reset()

    assert first.closed is True
    assert connector.connection() is not first


def test_reset_without_a_connection_is_a_no_op() -> None:
    connector = FakeConnector()

    connector.reset()

    assert connector.connections == []


def test_reset_ignores_errors_while_closing() -> None:
    connector = FakeConnector()
    connection = connector.connection()

    def broken_close() -> None:
        raise psycopg.OperationalError("already gone")

    connection.close = broken_close  # type: ignore[method-assign]

    connector.reset()

    assert connector.connection() is not connection


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("host=abc123.dsql.us-east-1.on.aws password=token-1"),
        psycopg.OperationalError("connection to abc123.dsql.us-east-1.on.aws failed"),
        DataSourceConnectionError("raw failure from a subclass"),
    ],
)
def test_open_failure_becomes_data_source_connection_error_without_details(
    failure: Exception,
) -> None:
    with pytest.raises(DataSourceConnectionError) as caught:
        FailingConnector(failure).connection()

    assert caught.value.__cause__ is failure
    assert "dsql" not in str(caught.value)
    assert "token" not in str(caught.value)


def test_a_failed_open_is_retried_on_the_next_call() -> None:
    connector = FakeConnector(DataSourceConnectionError("no route to host"), [])

    with pytest.raises(DataSourceConnectionError):
        connector.connection()

    assert connector.connection() is connector.connections[0]
