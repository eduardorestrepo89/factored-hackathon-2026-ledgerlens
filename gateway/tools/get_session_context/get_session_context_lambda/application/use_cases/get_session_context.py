"""Use case: load the customer's session-start snapshot."""

import logging
from collections.abc import Callable, Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Final

from get_session_context_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from get_session_context_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
)
from get_session_context_lambda.application.ports.query_provider import QueryProvider
from get_session_context_lambda.domain.entities.session_context import (
    CreditCard,
    Customer,
    DigitalSignal,
    OpenCase,
    RecentTransaction,
    Section,
    SessionContext,
    TransactionFlag,
)
from get_session_context_lambda.domain.errors import (
    CustomerNotFoundError,
    DataSourceUnavailableError,
    InvalidInputError,
    SessionContextDataIntegrityError,
    SessionContextLookupError,
)

logger = logging.getLogger(__name__)

PROFILE_QUERY_NAME: Final = "session_customer_profile"
# The query of each section, in Section order.
SECTION_QUERY_NAMES: Final[Mapping[Section, str]] = {
    Section.CARDS: "session_credit_cards",
    Section.RECENT_TRANSACTIONS: "session_recent_transactions",
    Section.DIGITAL_SIGNALS: "session_digital_signals",
    Section.OPEN_CASES: "session_open_cases",
}
# The sections whose query counts back from as_of.
_TIMED_SECTIONS: Final = frozenset(
    {Section.RECENT_TRANSACTIONS, Section.DIGITAL_SIGNALS, Section.OPEN_CASES}
)


class GetSessionContextUseCase:
    """Load the customer's snapshot through a database-agnostic repository.

    Five queries run one after another on the repository's single connection.
    The customer section is the core: its failure fails the call with a domain
    error. Each other section fails on its own: it becomes None and is listed in
    ``unavailable``, and the next section still runs.
    """

    OPEN_CASES_CAP: Final = 5

    def __init__(
        self,
        database_repository: DatabaseRepository,
        query_provider: QueryProvider,
        max_rows: int = 25,
    ) -> None:
        """Store the ports and the row cap.

        Args:
            database_repository: Executes the queries; any DatabaseRepository
                adapter.
            query_provider: Supplies the SQL text for the configured dialect.
            max_rows: Maximum items per list; open cases are capped at
                min(OPEN_CASES_CAP, max_rows).

        Raises:
            ValueError: If max_rows is less than 1.
        """
        if max_rows < 1:
            raise ValueError("max_rows must be at least 1")
        self._database_repository: DatabaseRepository = database_repository
        self._query_provider: QueryProvider = query_provider
        self._max_rows: int = max_rows

    def execute(self, customer_id: object, as_of: datetime) -> SessionContext:
        """Clean the id, then load the customer and the four other sections.

        Each section's query asks for one row more than its cap, so the result
        can say whether more exist.

        Args:
            customer_id: The customer id exactly as it came in the tool event.
            as_of: "Now", an aware datetime. Every query gets it as naive UTC,
                because the ERD's timestamp columns have no time zone.

        Raises:
            InvalidInputError: customer_id is missing, not a string or blank.
                Raised before the database is touched.
            ValueError: as_of is naive (a programming error, not user input).
            DataSourceUnavailableError: The customer query couldn't connect.
            SessionContextLookupError: The customer query is missing, failed or
                hit a database limit.
            CustomerNotFoundError: No customer row matches customer_id.
            SessionContextDataIntegrityError: The customer row couldn't be mapped.
        """
        clean_id = _clean_customer_id(customer_id)
        as_of_utc = _utc(as_of)
        as_of_sql = as_of_utc.replace(tzinfo=None)
        customer = self._customer(clean_id)

        sections: dict[Section, tuple[Any, ...] | None] = {}
        truncated: list[Section] = []
        unavailable: list[Section] = []
        for section in Section:
            cap = self._cap(section)
            try:
                rows = self._run(
                    SECTION_QUERY_NAMES[section],
                    self._params(section, clean_id, as_of_sql),
                )
                items = tuple(_SECTION_MAPPERS[section](row) for row in rows[:cap])
            except (DataAccessError, KeyError, TypeError, ValueError):
                logger.warning(
                    "get_session_context section %s unavailable",
                    section.value,
                    exc_info=True,
                )
                sections[section] = None
                unavailable.append(section)
                continue
            sections[section] = items
            if len(rows) > cap:
                truncated.append(section)

        return SessionContext(
            as_of=as_of_utc,
            customer=customer,
            cards=sections[Section.CARDS],
            recent_transactions=sections[Section.RECENT_TRANSACTIONS],
            digital_signals=sections[Section.DIGITAL_SIGNALS],
            open_cases=sections[Section.OPEN_CASES],
            truncated=tuple(truncated),
            unavailable=tuple(unavailable),
        )

    def _customer(self, customer_id: str) -> Customer:
        """Load and map the customer row, translating every failure.

        Raises:
            DataSourceUnavailableError: The query couldn't connect.
            SessionContextLookupError: Any other data-access failure.
            CustomerNotFoundError: No row came back.
            SessionContextDataIntegrityError: The row couldn't be mapped.
        """
        try:
            rows = self._run(PROFILE_QUERY_NAME, {"customer_id": customer_id})
        except DataSourceConnectionError as exc:
            raise DataSourceUnavailableError() from exc
        except DataAccessError as exc:
            raise SessionContextLookupError() from exc
        if not rows:
            raise CustomerNotFoundError()
        try:
            return _to_customer(rows[0])
        except (KeyError, TypeError, ValueError) as exc:
            raise SessionContextDataIntegrityError() from exc

    def _run(self, name: str, params: Mapping[str, object]) -> list[dict[str, Any]]:
        """Load the named SQL and run it.

        Raises:
            DataAccessError: The query is missing or failed.
        """
        query = self._query_provider.get(name)
        return self._database_repository.execute_query(query, params)

    def _cap(self, section: Section) -> int:
        """Return the maximum number of items the section returns."""
        if section is Section.OPEN_CASES:
            return min(self.OPEN_CASES_CAP, self._max_rows)
        return self._max_rows

    def _params(
        self, section: Section, customer_id: str, as_of_sql: datetime
    ) -> dict[str, object]:
        """Build a section's query parameters; every key must match a placeholder."""
        params: dict[str, object] = {
            "customer_id": customer_id,
            "limit": self._cap(section) + 1,
        }
        if section in _TIMED_SECTIONS:
            params["as_of"] = as_of_sql
        return params


def _clean_customer_id(raw: object) -> str:
    """Strip and uppercase the raw id; ids look like ``CLI-ITIECUE8PRH9``.

    There is no format check: a malformed or unknown id just finds no customer.
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


def _utc(as_of: datetime) -> datetime:
    """Return as_of converted to aware UTC.

    Raises:
        ValueError: as_of is naive.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be an aware datetime")
    return as_of.astimezone(timezone.utc)


def _to_customer(row: Mapping[str, Any]) -> Customer:
    """Map the profile row to a Customer.

    Raises:
        KeyError: A column is missing.
        TypeError: customer_id is None.
    """
    return Customer(
        customer_id=_required_text(row, "customer_id"),
        first_name=_optional_text(row, "first_name"),
        country=_optional_text(row, "country"),
        city=_optional_text(row, "city"),
        customer_status=_optional_text(row, "customer_status"),
    )


def _to_card(row: Mapping[str, Any]) -> CreditCard:
    """Map one card row to a CreditCard.

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


def _to_transaction(row: Mapping[str, Any]) -> RecentTransaction:
    """Map one transaction row to a RecentTransaction.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type.
        ValueError: The amount isn't finite.
    """
    return RecentTransaction(
        transaction_id=_optional_text(row, "transaction_id"),
        transaction_date=_optional_datetime(row, "transaction_date"),
        card_last4=_optional_text(row, "card_last4"),
        merchant_name=_optional_text(row, "merchant_name"),
        amount=_optional_amount(row, "amount"),
        currency=_optional_text(row, "currency"),
        transaction_status=_optional_text(row, "transaction_status"),
        transaction_country=_optional_text(row, "transaction_country"),
        flags=_flags(row),
    )


def _to_signal(row: Mapping[str, Any]) -> DigitalSignal:
    """Map one signal row to a DigitalSignal.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type, or signal is None.
    """
    return DigitalSignal(
        event_date=_optional_datetime(row, "event_date"),
        signal=_required_text(row, "signal"),
        page_title=_optional_text(row, "page_title"),
        ip_country=_optional_text(row, "ip_country"),
        ip_city=_optional_text(row, "ip_city"),
    )


def _to_case(row: Mapping[str, Any]) -> OpenCase:
    """Map one case row to an OpenCase.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type.
        ValueError: The amount isn't finite.
    """
    return OpenCase(
        complaint_id=_optional_text(row, "complaint_id"),
        case_type=_optional_text(row, "case_type"),
        category=_optional_text(row, "category"),
        subcategory=_optional_text(row, "subcategory"),
        status=_optional_text(row, "status"),
        priority=_optional_text(row, "priority"),
        sla_breached=_optional_bool(row, "sla_breached"),
        claimed_amount=_optional_amount(row, "claimed_amount"),
        currency=_optional_text(row, "currency"),
        days_open=_optional_int(row, "days_open"),
    )


def _flags(row: Mapping[str, Any]) -> tuple[TransactionFlag, ...]:
    """Return the true flags in enum order; NULL means "not flagged".

    Raises:
        KeyError: A flag column is missing.
        TypeError: A flag column is neither a bool nor None.
    """
    return tuple(
        flag for flag in TransactionFlag if _optional_bool(row, f"is_{flag.value}")
    )


def _required_text(row: Mapping[str, Any], column: str) -> str:
    """Return a column that must not be NULL as text."""
    value = row[column]
    if value is None:
        raise TypeError(f"{column} is None, expected text")
    return str(value)


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


def _optional_datetime(row: Mapping[str, Any], column: str) -> datetime | None:
    """Return a nullable timestamp column as it is stored."""
    value = row[column]
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    raise TypeError(f"{column} is {type(value).__name__}, expected a timestamp")


def _optional_int(row: Mapping[str, Any], column: str) -> int | None:
    """Return a nullable integer column; bool is rejected."""
    value = row[column]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{column} is {type(value).__name__}, expected an integer")
    return value


def _optional_bool(row: Mapping[str, Any], column: str) -> bool | None:
    """Return a nullable boolean column; only bool or None is accepted."""
    value = row[column]
    if value is None or isinstance(value, bool):
        return value
    raise TypeError(f"{column} is {type(value).__name__}, expected a boolean")


# The row mapper of each section.
_SECTION_MAPPERS: Final[Mapping[Section, Callable[[Mapping[str, Any]], Any]]] = {
    Section.CARDS: _to_card,
    Section.RECENT_TRANSACTIONS: _to_transaction,
    Section.DIGITAL_SIGNALS: _to_signal,
    Section.OPEN_CASES: _to_case,
}
