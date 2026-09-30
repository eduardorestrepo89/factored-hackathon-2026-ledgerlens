"""Test doubles and builders shared by the LedgerLens tool tests."""

from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from ledgerlens.application.ports.database_repository import DatabaseRepository
from ledgerlens.application.ports.errors import QueryNotFoundError
from ledgerlens.application.ports.query_provider import QueryProvider
from ledgerlens.domain.value_objects.transaction_filters import TransactionFilters


class FakeRepository(DatabaseRepository):
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
        "merchant_name": "Café Aroma",
        "merchant_category": "Restaurants",
        "amount": Decimal("12.50"),
        "currency": "COP",
        "channel": "POS",
        "transaction_city": "Medellín",
        "transaction_country": "CO",
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
