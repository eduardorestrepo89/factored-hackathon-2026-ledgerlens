"""Test doubles and builders shared by the LedgerLens tool tests."""

import time
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from ledgerlens.application.ports.database_repository import DatabaseRepository
from ledgerlens.application.ports.errors import (
    DataSourceConnectionError,
    QueryNotFoundError,
)
from ledgerlens.application.ports.query_provider import QueryProvider
from ledgerlens.domain.value_objects.transaction_filters import TransactionFilters
from ledgerlens.utils.connectors.base import PsycopgConnector


class FakeDatabaseRepository(DatabaseRepository):
    """DatabaseRepository double that records calls and returns canned rows."""

    def __init__(
        self,
        rows: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        """Return ``rows`` from every call, or raise ``error`` if given."""
        self.rows: list[dict[str, Any]] = rows if rows is not None else []
        self.error = error
        self.calls: list[tuple[str, dict[str, object]]] = []

    def execute_query(
        self, query: str, params: Mapping[str, object]
    ) -> list[dict[str, Any]]:
        """Record the call, then raise the configured error or return the rows."""
        self.calls.append((query, dict(params)))
        if self.error is not None:
            raise self.error
        return [dict(row) for row in self.rows]


class FakeQueryProvider(QueryProvider):
    """QueryProvider double backed by an in-memory mapping."""

    def __init__(self, queries: Mapping[str, str] | None = None) -> None:
        """Serve ``queries``; by default only list_card_transactions exists."""
        self.queries: dict[str, str] = dict(
            queries
            if queries is not None
            else {"list_card_transactions": "SELECT 'list_card_transactions'"}
        )
        self.requested: list[str] = []

    def get(self, name: str) -> str:
        """Record the name and return its SQL, or raise QueryNotFoundError."""
        self.requested.append(name)
        if name not in self.queries:
            raise QueryNotFoundError(f"no query named {name!r}")
        return self.queries[name]


def make_row(**overrides: Any) -> dict[str, Any]:
    """Build a database row as psycopg's dict_row returns it."""
    row: dict[str, Any] = {
        "transaction_id": "TX-1",
        "transaction_date": datetime(2026, 9, 20, 14, 30, tzinfo=timezone.utc),
        "card_last4": "4242",
        "merchant_name": "Óptica Visión",
        "merchant_category": "Health",
        "amount": Decimal("12.50"),
        "currency": "COP",
        "channel": "POS",
        "transaction_city": "Medellín",
        "transaction_country": "Colombia",
        "transaction_status": "Approved",
    }
    row.update(overrides)
    return row


def make_filters(**overrides: Any) -> TransactionFilters:
    """Build valid TransactionFilters, overriding any field."""
    values: dict[str, Any] = {
        "customer_id": "CUST-1",
        "date_from": date(2026, 8, 30),
        "date_to": date(2026, 9, 29),
    }
    values.update(overrides)
    return TransactionFilters(**values)


Outcome = list[dict[str, Any]] | Exception


class FakeCursor:
    """psycopg cursor double: records execute() and returns or raises its outcome."""

    def __init__(self, outcome: Outcome) -> None:
        """Serve ``outcome`` from execute()/fetchall()."""
        self._outcome = outcome
        self.executed: list[tuple[str, Mapping[str, object]]] = []

    def __enter__(self) -> "FakeCursor":
        """Support ``with connection.cursor() as cursor``."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Nothing to clean up."""

    def execute(self, query: str, params: Mapping[str, object]) -> None:
        """Record the call; raise the outcome if it is an exception."""
        self.executed.append((query, params))
        if isinstance(self._outcome, Exception):
            raise self._outcome

    def fetchall(self) -> list[dict[str, Any]]:
        """Return the canned rows."""
        assert not isinstance(self._outcome, Exception)
        return self._outcome


class FakeConnection:
    """psycopg connection double exposing cursor(), close() and closed."""

    def __init__(self, outcome: Outcome | None = None) -> None:
        """Every cursor from this connection serves ``outcome``."""
        self._outcome: Outcome = outcome if outcome is not None else []
        self.cursors: list[FakeCursor] = []
        self.closed = False

    def cursor(self) -> FakeCursor:
        """Open a new cursor double."""
        cursor = FakeCursor(self._outcome)
        self.cursors.append(cursor)
        return cursor

    def close(self) -> None:
        """Mark the connection closed."""
        self.closed = True


class FakeConnector(PsycopgConnector):
    """PsycopgConnector double whose _open() serves the next queued outcome.

    The base class caches the connection, so the next outcome is only used after
    a reset, a closed connection or max_age. The last outcome repeats. A
    DataSourceConnectionError outcome is raised by _open() (connection() wraps
    it); any other exception is raised by cursor.execute().
    """

    def __init__(
        self,
        *outcomes: Outcome,
        max_age: timedelta | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Queue the outcomes; with none, every query returns no rows."""
        super().__init__(max_age=max_age, clock=clock)
        self._outcomes: list[Outcome] = list(outcomes) or [[]]
        self.connections: list[FakeConnection] = []
        self.reset_calls = 0

    def reset(self) -> None:
        """Count the reset, then let the base class close the connection."""
        self.reset_calls += 1
        super().reset()

    def _open(self) -> Any:
        """Return a connection double for the next outcome."""
        outcome = (
            self._outcomes.pop(0) if len(self._outcomes) > 1 else self._outcomes[0]
        )
        if isinstance(outcome, DataSourceConnectionError):
            raise outcome
        connection = FakeConnection(outcome)
        self.connections.append(connection)
        return connection


class FakeClock:
    """Monotonic clock double that only moves when told to."""

    def __init__(self, start: float = 1000.0) -> None:
        """Start at ``start`` seconds."""
        self.now = start

    def __call__(self) -> float:
        """Return the current time in seconds."""
        return self.now

    def advance(self, delta: timedelta) -> None:
        """Move the clock forward by ``delta``."""
        self.now += delta.total_seconds()


class FakeDsqlTokenClient:
    """boto3 DSQL client double; returns token-1, token-2, ... and records calls."""

    def __init__(self, error: Exception | None = None) -> None:
        """Raise ``error`` from every token method if given."""
        self.error = error
        self.calls: list[tuple[str, str, str]] = []

    def generate_db_connect_auth_token(
        self,
        Hostname: str,  # noqa: N803
        Region: str,  # noqa: N803
    ) -> str:
        """Return the next token for a custom database role."""
        return self._token("generate_db_connect_auth_token", Hostname, Region)

    def generate_db_connect_admin_auth_token(
        self,
        Hostname: str,  # noqa: N803
        Region: str,  # noqa: N803
    ) -> str:
        """Return the next token for the admin role."""
        return self._token("generate_db_connect_admin_auth_token", Hostname, Region)

    def _token(self, method: str, hostname: str, region: str) -> str:
        """Record the call, then raise the configured error or return a token."""
        self.calls.append((method, hostname, region))
        if self.error is not None:
            raise self.error
        return f"token-{len(self.calls)}"
