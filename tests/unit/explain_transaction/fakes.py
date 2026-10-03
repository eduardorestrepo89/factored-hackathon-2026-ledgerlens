"""Test doubles and builders for the explain_transaction tests."""

import time
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from explain_transaction_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from explain_transaction_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryNotFoundError,
)
from explain_transaction_lambda.application.ports.query_provider import QueryProvider
from explain_transaction_lambda.utils.connectors.base import PsycopgConnector

# Customer P07 of the curated personas and the charge the spec's example explains.
CUSTOMER_ID: Final = "CLI-EX6BOAOEFZHQ"
TRANSACTION_ID: Final = "TRX-23BIJAU4GL46ATPW9STY"
# Any id: the use case only passes it from the core row to the habit query.
PRODUCT_ID: Final = "PRD-P07-CC-4497"
CHARGE_DATE: Final = datetime(2026, 5, 31, 6, 9, 15)

# The core query, then the two optional sections, in the order they run.
QUERY_NAMES: Final = (
    "explain_transaction",
    "transaction_habit",
    "transaction_app_activity",
)

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


class FakeExplainRepository(DatabaseRepository):
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


def make_core_row(**overrides: Any) -> dict[str, Any]:
    """Build an explain_transaction row as psycopg's dict_row returns it.

    The values are P07's charge from the spec's output example: USD on a USD
    card, approved, so fx and decline are both None.
    """
    row: dict[str, Any] = {
        "transaction_id": TRANSACTION_ID,
        "transaction_date": CHARGE_DATE,
        "product_id": PRODUCT_ID,
        "card_last4": "4497",
        "card_currency": "USD",
        "card_expiration_date": date(2029, 8, 31),
        "merchant_name": "Estación de Servicio",
        "merchant_category": "Transport",
        "amount": Decimal("288.69"),
        "currency": "USD",
        "channel": "Web",
        "transaction_city": "Ciudad de México",
        "transaction_country": "México",
        "transaction_status": "Approved",
        "response_code": "00",
        "fx_sell_rate": None,
    }
    row.update(overrides)
    return row


# The copied repository tests build rows with make_row.
make_row = make_core_row


def make_habit_row(**overrides: Any) -> dict[str, Any]:
    """Build the one aggregate row transaction_habit returns (P07's values)."""
    row: dict[str, Any] = {
        "history_count": 1,
        "times_at_merchant": 0,
        "same_currency_count": 1,
        "usual_low": None,
        "usual_high": None,
        "country_seen_before": True,
    }
    row.update(overrides)
    return row


def make_app_activity_row(**overrides: Any) -> dict[str, Any]:
    """Build a transaction_app_activity row: an event 12 minutes after the charge."""
    row: dict[str, Any] = {
        "event_id": "EVT-0001",
        "event_date": CHARGE_DATE + timedelta(minutes=12),
        "ip_country": "México",
        "ip_city": "Ciudad de México",
    }
    row.update(overrides)
    return row


def explain_responses(**overrides: Outcome) -> dict[str, Outcome]:
    """Return the responses of P07's charge, keyed by query name.

    App activity is empty by default, as it is for most charges. Overrides
    replace a query's outcome.
    """
    responses: dict[str, Outcome] = {
        "explain_transaction": [make_core_row()],
        "transaction_habit": [make_habit_row()],
        "transaction_app_activity": [],
    }
    responses.update(overrides)
    return responses


def make_any_row() -> dict[str, Any]:
    """Build one row that every query can map.

    FakeConnector serves the same rows to every query, so end-to-end tests over
    real adapters need a row with every query's columns. The three rows share no
    column name, so nothing is overwritten.
    """
    return {**make_core_row(), **make_habit_row(), **make_app_activity_row()}


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
