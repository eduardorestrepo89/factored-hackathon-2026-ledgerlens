"""Test doubles and builders for the block_credit_card tests."""

import time
from collections.abc import Callable, Iterable, Mapping
from datetime import timedelta
from typing import Any, Final

from block_credit_card_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from block_credit_card_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryNotFoundError,
)
from block_credit_card_lambda.application.ports.query_provider import QueryProvider
from block_credit_card_lambda.utils.connectors.base import PsycopgConnector

# A customer id in the format the customer system issues.
CUSTOMER_ID: Final = "CLI-ITIECUE8PRH9"
# The queries this tool runs. FakeQueryProvider serves each name as its own SQL text.
QUERY_NAMES: Final = ("find_credit_card", "block_credit_card")

Outcome = list[dict[str, Any]] | Exception
# One outcome, or a tuple of outcomes served call by call (the last one repeats).
Outcomes = Outcome | tuple[Outcome, ...]


def _queue(outcomes: Outcomes) -> list[Outcome]:
    """Turn one outcome, or a tuple of them, into a queue."""
    return list(outcomes) if isinstance(outcomes, tuple) else [outcomes]


def _next(queue: list[Outcome]) -> Outcome:
    """Pop the next outcome, keeping the last one for every later call."""
    return queue.pop(0) if len(queue) > 1 else queue[0]


class FakeDatabaseRepository(DatabaseRepository):
    """DatabaseRepository double keyed by query text.

    FakeQueryProvider serves each query's name as its SQL text, so ``results``
    maps a query name to its outcomes. Unlisted queries return no rows.
    """

    def __init__(self, results: Mapping[str, Outcomes] | None = None) -> None:
        """Serve ``results`` per query name."""
        self._results: dict[str, list[Outcome]] = {
            name: _queue(outcomes) for name, outcomes in (results or {}).items()
        }
        self.calls: list[tuple[str, dict[str, object]]] = []

    def execute_query(
        self, query: str, params: Mapping[str, object]
    ) -> list[dict[str, Any]]:
        """Record the call, then raise or return the query's next outcome."""
        self.calls.append((query, dict(params)))
        outcome = _next(self._results.setdefault(query, [[]]))
        if isinstance(outcome, Exception):
            raise outcome
        return [dict(row) for row in outcome]

    def params_of(self, query: str) -> list[dict[str, object]]:
        """Return the params of every call to ``query``, in order."""
        return [params for name, params in self.calls if name == query]


class FakeQueryProvider(QueryProvider):
    """QueryProvider double that serves each known name as its own SQL text."""

    def __init__(self, names: Iterable[str] = QUERY_NAMES) -> None:
        """Know only ``names``; any other name raises QueryNotFoundError."""
        self.names: frozenset[str] = frozenset(names)
        self.requested: list[str] = []

    def get(self, name: str) -> str:
        """Record the name and return it as the SQL text."""
        self.requested.append(name)
        if name not in self.names:
            raise QueryNotFoundError(f"no query named {name!r}")
        return name


def make_row(**overrides: Any) -> dict[str, Any]:
    """Build a find_credit_card row as psycopg's dict_row returns it."""
    row: dict[str, Any] = {"product_id": "PRD-1", "product_status": "Active"}
    row.update(overrides)
    return row


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

    def __init__(self, outcome: Outcomes | None = None) -> None:
        """Serve ``outcome`` from every cursor, or a tuple's items cursor by cursor."""
        self._outcomes: list[Outcome] = _queue(outcome if outcome is not None else [])
        self.cursors: list[FakeCursor] = []
        self.closed = False

    def cursor(self) -> FakeCursor:
        """Open a new cursor double serving the next outcome."""
        cursor = FakeCursor(_next(self._outcomes))
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
    it); any other exception is raised by cursor.execute(). A tuple outcome is
    served by one connection, cursor by cursor.
    """

    def __init__(
        self,
        *outcomes: Outcomes,
        max_age: timedelta | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Queue the outcomes; with none, every query returns no rows."""
        super().__init__(max_age=max_age, clock=clock)
        self._outcomes: list[Outcomes] = list(outcomes) or [[]]
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
