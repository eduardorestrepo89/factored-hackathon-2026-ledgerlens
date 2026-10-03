"""Use case: search a customer's card transactions."""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from list_card_transactions_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from list_card_transactions_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    QueryLimitExceededError,
)
from list_card_transactions_lambda.application.ports.query_provider import QueryProvider
from list_card_transactions_lambda.domain.entities.card_transaction import (
    CardTransaction,
    CardTransactionsResult,
)
from list_card_transactions_lambda.domain.errors import (
    DataIntegrityError,
    DataSourceUnavailableError,
    SearchTooBroadError,
    TransactionLookupError,
)
from list_card_transactions_lambda.domain.value_objects.transaction_filters import (
    TransactionFilters,
)


class ListCardTransactionsUseCase:
    """Search a customer's card transactions through a database-agnostic repository.

    The use case loads the SQL by name through the query provider, runs it
    through the database repository port and maps rows to domain entities. Port
    errors are translated into domain errors whose messages tell the agent what
    to do next.
    """

    QUERY_NAME: Final = "list_card_transactions"

    def __init__(
        self,
        database_repository: DatabaseRepository,
        query_provider: QueryProvider,
        max_rows: int = 25,
    ) -> None:
        """Store the ports and the row cap.

        Args:
            database_repository: Executes the query; any DatabaseRepository
                adapter.
            query_provider: Supplies the SQL text for the configured dialect.
            max_rows: Maximum transactions returned per call.

        Raises:
            ValueError: If max_rows is less than 1.
        """
        if max_rows < 1:
            raise ValueError("max_rows must be at least 1")
        self._database_repository: DatabaseRepository = database_repository
        self._query_provider: QueryProvider = query_provider
        self._max_rows: int = max_rows

    def execute(self, filters: TransactionFilters) -> CardTransactionsResult:
        """Load the query, run it with the filters and return at most max_rows rows.

        One extra row is requested so the result can say whether more exist.

        Raises:
            DataSourceUnavailableError: The database can't be reached.
            SearchTooBroadError: The query exceeded a database time or resource
                limit.
            TransactionLookupError: The query is missing or failed to run.
            DataIntegrityError: A returned row couldn't be mapped.
        """
        try:
            query = self._query_provider.get(self.QUERY_NAME)
            rows = self._database_repository.execute_query(query, self._params(filters))
        except DataSourceConnectionError as exc:
            raise DataSourceUnavailableError() from exc
        except QueryLimitExceededError as exc:
            raise SearchTooBroadError() from exc
        except DataAccessError as exc:
            raise TransactionLookupError() from exc

        try:
            transactions = tuple(_to_transaction(row) for row in rows[: self._max_rows])
        except (KeyError, TypeError, ValueError) as exc:
            raise DataIntegrityError() from exc

        return CardTransactionsResult(
            transactions=transactions, truncated=len(rows) > self._max_rows
        )

    def _params(self, filters: TransactionFilters) -> dict[str, object]:
        """Build the query parameters; every key must match a SQL placeholder."""
        return {
            "customer_id": filters.customer_id,
            "date_from": filters.date_from,
            "date_to": filters.date_to,
            "card_last4": filters.card_last4,
            "merchant": filters.merchant,
            "min_amount": filters.min_amount,
            "max_amount": filters.max_amount,
            "status": filters.status.value if filters.status is not None else None,
            "limit": self._max_rows + 1,
        }


def _to_transaction(row: Mapping[str, Any]) -> CardTransaction:
    """Map one database row to a CardTransaction.

    Raises:
        KeyError: A column is missing.
        TypeError: A required column has the wrong type.
        ValueError: A required column is null or the amount isn't finite.
    """
    return CardTransaction(
        transaction_id=_required_text(row, "transaction_id"),
        transaction_date=_required_datetime(row, "transaction_date"),
        card_last4=_required_text(row, "card_last4"),
        amount=_required_amount(row, "amount"),
        currency=_optional_text(row, "currency"),
        transaction_status=_optional_text(row, "transaction_status"),
        merchant_name=_optional_text(row, "merchant_name"),
        merchant_category=_optional_text(row, "merchant_category"),
        channel=_optional_text(row, "channel"),
        transaction_city=_optional_text(row, "transaction_city"),
        transaction_country=_optional_text(row, "transaction_country"),
    )


def _required_text(row: Mapping[str, Any], column: str) -> str:
    """Return a non-null column as text (numeric ids become strings)."""
    value = row[column]
    if value is None:
        raise ValueError(f"{column} is null")
    return str(value)


def _optional_text(row: Mapping[str, Any], column: str) -> str | None:
    """Return a nullable column as text, keeping None."""
    value = row[column]
    return None if value is None else str(value)


def _required_datetime(row: Mapping[str, Any], column: str) -> datetime:
    """Return a non-null timestamp column."""
    value = row[column]
    if value is None:
        raise ValueError(f"{column} is null")
    if not isinstance(value, datetime):
        raise TypeError(f"{column} is {type(value).__name__}, expected datetime")
    return value


def _required_amount(row: Mapping[str, Any], column: str) -> Decimal:
    """Return a non-null, finite numeric column as an exact Decimal."""
    value = row[column]
    if value is None:
        raise ValueError(f"{column} is null")
    if isinstance(value, bool) or not isinstance(value, Decimal | int | float):
        raise TypeError(f"{column} is {type(value).__name__}, expected a number")
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    if not amount.is_finite():
        raise ValueError(f"{column} is not finite")
    return amount
