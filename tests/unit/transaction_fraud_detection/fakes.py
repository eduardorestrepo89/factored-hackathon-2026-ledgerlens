"""Test doubles and builders for the transaction_fraud_detection tests."""

import time
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from transaction_fraud_detection_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from transaction_fraud_detection_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryNotFoundError,
)
from transaction_fraud_detection_lambda.application.ports.query_provider import (
    QueryProvider,
)
from transaction_fraud_detection_lambda.utils.connectors.base import PsycopgConnector

# Customer P07 of the curated personas and its fraud charge.
CUSTOMER_ID: Final = "CLI-EX6BOAOEFZHQ"
TRANSACTION_ID: Final = "TRX-23BIJAU4GL46ATPW9STY"
# A score with decimals, so a leak can be searched for in logs and output.
SCORE: Final = Decimal("62.37")

# The three queries: fraud_transaction for one charge, the other two for a sweep.
QUERY_NAMES: Final = ("fraud_transaction", "fraud_card_exists", "fraud_card_sweep")

Outcome = list[dict[str, Any]] | Exception


class FakeQueryProvider(QueryProvider):
    """QueryProvider double backed by an in-memory mapping."""

    def __init__(self, queries: Mapping[str, str] | None = None) -> None:
        """Serve ``queries``; by default each query name is its own SQL text."""
        self.queries: dict[str, str] = dict(
            queries if queries is not None else {name: name for name in QUERY_NAMES}
        )
        self.requested: list[str] = []

    def get(self, name: str) -> str:
        """Record the name and return its SQL, or raise QueryNotFoundError."""
        self.requested.append(name)
        if name not in self.queries:
            raise QueryNotFoundError(f"no query named {name!r}")
        return self.queries[name]


class FakeFraudRepository(DatabaseRepository):
    """DatabaseRepository double that answers each query on its own.

    FakeQueryProvider serves each query name as its SQL text, so responses are
    keyed by query name. A missing name returns no rows; an exception is raised.
    """

    def __init__(self, responses: Mapping[str, Outcome] | None = None) -> None:
        """Answer from ``responses``; with none, every query returns no rows."""
        self.responses: dict[str, Outcome] = dict(responses or {})
        self.calls: list[tuple[str, dict[str, object]]] = []

    @property
    def queries(self) -> list[str]:
        """Return the SQL text of every call, in order."""
        return [query for query, _params in self.calls]

    def execute_query(
        self, query: str, params: Mapping[str, object]
    ) -> list[dict[str, Any]]:
        """Record the call, then raise or return the configured outcome."""
        self.calls.append((query, dict(params)))
        outcome = self.responses.get(query, [])
        if isinstance(outcome, Exception):
            raise outcome
        return [dict(row) for row in outcome]


def make_transaction_row(**overrides: Any) -> dict[str, Any]:
    """Build a fraud_transaction row as psycopg's dict_row returns it."""
    row: dict[str, Any] = {
        "transaction_id": TRANSACTION_ID,
        "transaction_date": datetime(2026, 5, 31, 6, 9, 15),
        "card_last4": "4497",
        "merchant_name": "Estación de Servicio",
        "amount": Decimal("288.69"),
        "currency": "USD",
        "transaction_status": "Approved",
        "fraud_score": SCORE,
    }
    row.update(overrides)
    return row


# The copied repository tests build rows with make_row.
make_row = make_transaction_row


def make_sweep_row(**overrides: Any) -> dict[str, Any]:
    """Build a flagged fraud_card_sweep row: a charge plus the window's count."""
    row: dict[str, Any] = {**make_transaction_row(), "checked": 3}
    row.update(overrides)
    return row


def make_count_only_row(checked: int = 3) -> dict[str, Any]:
    """Build the sweep row returned when nothing in the window is flagged."""
    row: dict[str, Any] = {column: None for column in make_transaction_row()}
    row["checked"] = checked
    return row


def make_card_exists_row(**overrides: Any) -> dict[str, Any]:
    """Build a fraud_card_exists row."""
    row: dict[str, Any] = {"card_exists": 1}
    row.update(overrides)
    return row


def fraud_responses(**overrides: Outcome) -> dict[str, Outcome]:
    """Return one row per query, keyed by query name; overrides replace a query."""
    responses: dict[str, Outcome] = {
        "fraud_transaction": [make_transaction_row()],
        "fraud_card_exists": [make_card_exists_row()],
        "fraud_card_sweep": [make_sweep_row()],
    }
    responses.update(overrides)
    return responses


def make_any_row() -> dict[str, Any]:
    """Build one row that every query can map.

    FakeConnector serves the same rows to every query, so end-to-end tests over
    real adapters need a row with every query's columns.
    """
    return {**make_sweep_row(), **make_card_exists_row()}


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
