"""Use case: list a customer's credit cards."""

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

from list_credit_cards_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from list_credit_cards_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
)
from list_credit_cards_lambda.application.ports.query_provider import QueryProvider
from list_credit_cards_lambda.domain.entities.credit_card import (
    CreditCard,
    CreditCardsResult,
)
from list_credit_cards_lambda.domain.errors import (
    CardDataIntegrityError,
    CardLookupError,
    DataSourceUnavailableError,
    InvalidInputError,
)


class ListCreditCardsUseCase:
    """List a customer's credit cards through a database-agnostic repository.

    The use case cleans the customer id, loads the SQL by name through the query
    provider, runs it through the database repository port and maps rows to
    domain entities. Port errors are translated into domain errors whose messages
    tell the agent what to do next.
    """

    QUERY_NAME: Final = "list_credit_cards"

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
            max_rows: Maximum cards returned per call.

        Raises:
            ValueError: If max_rows is less than 1.
        """
        if max_rows < 1:
            raise ValueError("max_rows must be at least 1")
        self._database_repository: DatabaseRepository = database_repository
        self._query_provider: QueryProvider = query_provider
        self._max_rows: int = max_rows

    def execute(self, customer_id: object) -> CreditCardsResult:
        """Clean the id, run the query and return at most max_rows cards.

        One extra row is requested so the result can say whether more exist.
        No rows is an empty result, not an error.

        Args:
            customer_id: The customer id exactly as it came in the tool event.

        Raises:
            InvalidInputError: customer_id is missing, not a string or blank.
                Raised before the database is touched.
            DataSourceUnavailableError: The database can't be reached.
            CardLookupError: The query is missing, failed or hit a database limit.
            CardDataIntegrityError: A returned row couldn't be mapped.
        """
        params = self._params(_clean_customer_id(customer_id))
        try:
            query = self._query_provider.get(self.QUERY_NAME)
            rows = self._database_repository.execute_query(query, params)
        except DataSourceConnectionError as exc:
            raise DataSourceUnavailableError() from exc
        except DataAccessError as exc:
            raise CardLookupError() from exc

        try:
            cards = tuple(_to_card(row) for row in rows[: self._max_rows])
        except (KeyError, TypeError, ValueError) as exc:
            raise CardDataIntegrityError() from exc

        return CreditCardsResult(cards=cards, truncated=len(rows) > self._max_rows)

    def _params(self, customer_id: str) -> dict[str, object]:
        """Build the query parameters; every key must match a SQL placeholder."""
        return {"customer_id": customer_id, "limit": self._max_rows + 1}


def _clean_customer_id(raw: object) -> str:
    """Strip and uppercase the raw id; ids look like ``CLI-ITIECUE8PRH9``.

    There is no format check: a malformed or unknown id just finds no cards.
    Whether the caller may see this customer is the Gateway's Cedar policy's job.

    Raises:
        InvalidInputError: The id isn't a string or is blank after stripping.
    """
    if not isinstance(raw, str):
        raise InvalidInputError(
            "customer_id", "is required and must be a non-empty string"
        )
    customer_id = raw.strip().upper()
    if not customer_id:
        raise InvalidInputError(
            "customer_id", "is required and must be a non-empty string"
        )
    return customer_id


def _to_card(row: Mapping[str, Any]) -> CreditCard:
    """Map one database row to a CreditCard.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type.
        ValueError: An amount isn't finite.
    """
    return CreditCard(
        card_last4=_optional_text(row, "card_last4"),
        product_status=_optional_text(row, "product_status"),
        currency=_optional_text(row, "currency"),
        current_balance=_optional_amount(row, "current_balance"),
        credit_limit=_optional_amount(row, "credit_limit"),
        available_credit=_optional_amount(row, "available_credit"),
        expiration_date=_optional_date(row, "expiration_date"),
        days_past_due=_optional_int(row, "days_past_due"),
    )


def _optional_text(row: Mapping[str, Any], column: str) -> str | None:
    """Return a nullable column as text, keeping None."""
    value = row[column]
    return None if value is None else str(value)


def _optional_amount(row: Mapping[str, Any], column: str) -> Decimal | None:
    """Return a nullable, finite numeric column as an exact Decimal."""
    value = row[column]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Decimal | int | float):
        raise TypeError(f"{column} is {type(value).__name__}, expected a number")
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    if not amount.is_finite():
        raise ValueError(f"{column} is not finite")
    return amount


def _optional_date(row: Mapping[str, Any], column: str) -> date | None:
    """Return a nullable date column; a timestamp keeps only its date."""
    value = row[column]
    if value is None:
        return None
    # datetime is a subclass of date, so it must be checked first.
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"{column} is {type(value).__name__}, expected a date")


def _optional_int(row: Mapping[str, Any], column: str) -> int | None:
    """Return a nullable integer column; bool is rejected."""
    value = row[column]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{column} is {type(value).__name__}, expected an integer")
    return value
