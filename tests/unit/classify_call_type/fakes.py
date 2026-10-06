"""Test doubles and builders for the classify_call_type tests."""

import time
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Final

from classify_call_type_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from classify_call_type_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryNotFoundError,
)
from classify_call_type_lambda.application.ports.query_provider import QueryProvider
from classify_call_type_lambda.utils.connectors.base import PsycopgConnector

# Customer P07 of the curated personas and its flagged charge (spec section 1).
CUSTOMER_ID: Final = "CLI-EX6BOAOEFZHQ"
TRANSACTION_ID: Final = "TRX-23BIJAU4GL46ATPW9STY"
CHARGE_DATE: Final = datetime(2026, 5, 31, 6, 9, 15)
# The deployed AS_OF, and what the SQL receives: the same instant as naive UTC.
AS_OF: Final = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
AS_OF_SQL: Final = datetime(2026, 6, 17, 23, 59, 59)

# The four candidate queries, in the order they run (Source order).
QUERY_NAMES: Final = (
    "call_reason_transactions",
    "call_reason_cards",
    "call_reason_cases",
    "call_reason_app_events",
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


class FakeClassifyRepository(DatabaseRepository):
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
    """Build a call_reason_transactions row as psycopg's dict_row returns it.

    P07's charge from the spec's output example: approved, USD on a USD card, in
    the customer's home country. The score is any value above 50 (the fraud band);
    the stored one isn't needed by the tests.
    """
    row: dict[str, Any] = {
        "transaction_id": TRANSACTION_ID,
        "transaction_date": CHARGE_DATE,
        "card_last4": "4497",
        "card_currency": "USD",
        "merchant_name": "Estación de Servicio",
        "amount": Decimal("288.69"),
        "currency": "USD",
        "transaction_status": "Approved",
        "response_code": "00",
        "transaction_country": "México",
        "fraud_score": Decimal("62.00"),
        "home_country": "México",
    }
    row.update(overrides)
    return row


# The copied repository tests build rows with make_row.
make_row = make_transaction_row


def make_card_row(**overrides: Any) -> dict[str, Any]:
    """Build a call_reason_cards row: an active card in good standing, no reason."""
    row: dict[str, Any] = {
        "card_last4": "4497",
        "product_status": "Active",
        "expiration_date": date(2029, 8, 31),
        "days_past_due": 0,
    }
    row.update(overrides)
    return row


def make_case_row(**overrides: Any) -> dict[str, Any]:
    """Build a call_reason_cases row: P08's open claim, sla_breached NULL."""
    row: dict[str, Any] = {
        "complaint_id": "CMP-FHCLR8TGWMBD0YFOCLYS",
        "case_type": "Claim",
        "category": "Cards",
        "subcategory": "Unrecognized charge",
        "status": "In Progress",
        "sla_breached": None,
        "days_open": 12,
        "creation_date": AS_OF_SQL - timedelta(days=12),
    }
    row.update(overrides)
    return row


def make_app_event_row(**overrides: Any) -> dict[str, Any]:
    """Build a call_reason_app_events row: an app error 2 hours before AS_OF."""
    row: dict[str, Any] = {
        "event_id": "EVT-0001",
        "event_date": AS_OF_SQL - timedelta(hours=2),
        "page_title": "Pagar Servicios",
        "action": "submit_payment",
    }
    row.update(overrides)
    return row


def classify_responses(**overrides: Outcome) -> dict[str, Outcome]:
    """Return P07-like responses, keyed by query name.

    One flagged charge and one card in good standing; no case and no app error.
    Overrides replace a query's outcome.
    """
    responses: dict[str, Outcome] = {
        "call_reason_transactions": [make_transaction_row()],
        "call_reason_cards": [make_card_row()],
        "call_reason_cases": [],
        "call_reason_app_events": [],
    }
    responses.update(overrides)
    return responses


def make_any_row() -> dict[str, Any]:
    """Build one row that every query can map.

    FakeConnector serves the same rows to every query, so end-to-end tests over
    real adapters need a row with every query's columns. The transaction and card
    rows share only card_last4, and both builders give it the same value ("4497").
    Ranked, the row gives FRAUD_SUSPECTED 0.77, OPEN_CASE_FOLLOWUP 0.60 and
    FAILED_APP_ACTION 0.58.
    """
    return {
        **make_transaction_row(),
        **make_card_row(),
        **make_case_row(),
        **make_app_event_row(),
    }


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
