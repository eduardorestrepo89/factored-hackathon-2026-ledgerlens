"""Use case: rank the likely reasons the customer is calling."""

import logging
from collections.abc import Callable, Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Final, TypeVar

from classify_call_type_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from classify_call_type_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
)
from classify_call_type_lambda.application.ports.query_provider import QueryProvider
from classify_call_type_lambda.domain.entities.call_classification import (
    CallClassification,
)
from classify_call_type_lambda.domain.entities.candidates import (
    AppEventCandidate,
    CardCandidate,
    CaseCandidate,
    TransactionCandidate,
)
from classify_call_type_lambda.domain.errors import (
    CallReasonLookupError,
    DataSourceUnavailableError,
    InvalidInputError,
)
from classify_call_type_lambda.domain.services.reason_ranking import rank
from classify_call_type_lambda.domain.value_objects.call_reasons import (
    SOURCE_REASONS,
    CallReason,
    Source,
)
from classify_call_type_lambda.domain.value_objects.fraud_bands import REVIEW_ABOVE

logger = logging.getLogger(__name__)

# The candidate query of each source, in the order they run.
QUERY_NAMES: Final[Mapping[Source, str]] = {
    Source.TRANSACTIONS: "call_reason_transactions",
    Source.CARDS: "call_reason_cards",
    Source.CASES: "call_reason_cases",
    Source.APP_EVENTS: "call_reason_app_events",
}

_INVALID_ID: Final = "is required and must be a non-empty string"

_Candidate = TypeVar("_Candidate")


class ClassifyCallTypeUseCase:
    """Rank up to TOP_N call reasons through a database-agnostic repository.

    The four candidate queries run one after another on the repository's single
    connection, each in its own try. A failed query, or a row it returned that
    can't be mapped, makes that source's reasons unavailable; the others are
    still ranked. Only all four failing fails the call.
    """

    TOP_N: Final = 3
    TRANSACTION_CANDIDATE_CAP: Final = 200

    def __init__(
        self,
        database_repository: DatabaseRepository,
        query_provider: QueryProvider,
    ) -> None:
        """Store the ports.

        Args:
            database_repository: Executes the queries; any DatabaseRepository
                adapter.
            query_provider: Supplies the SQL text for the configured dialect.
        """
        self._database_repository: DatabaseRepository = database_repository
        self._query_provider: QueryProvider = query_provider

    def execute(self, customer_id: object, as_of: datetime) -> CallClassification:
        """Clean the input, load the four candidate sources and rank them.

        Args:
            customer_id: The customer id exactly as it came in the tool event.
            as_of: "Now", an aware datetime. Every query and every rule gets it
                as naive UTC, because the ERD's timestamp columns have no time
                zone.

        Raises:
            InvalidInputError: customer_id is missing, not a string or blank.
                Raised before the database is touched.
            ValueError: as_of is naive (a programming error, not user input).
            DataSourceUnavailableError: All four sources failed, at least one
                on the connection.
            CallReasonLookupError: All four sources failed, none on the
                connection.
        """
        clean_customer_id = _clean_customer_id(customer_id)
        as_of_sql = _utc(as_of).replace(tzinfo=None)
        failures: dict[Source, Exception] = {}

        transactions = self._load(
            Source.TRANSACTIONS,
            {
                "customer_id": clean_customer_id,
                "as_of": as_of_sql,
                "review_above": REVIEW_ABOVE,
                "limit": self.TRANSACTION_CANDIDATE_CAP + 1,
            },
            _to_transaction,
            failures,
        )
        if len(transactions) > self.TRANSACTION_CANDIDATE_CAP:
            logger.warning(
                "classify_call_type transactions returned %d rows, above the cap "
                "of %d; the oldest may be missing",
                len(transactions),
                self.TRANSACTION_CANDIDATE_CAP,
            )
        cards = self._load(
            Source.CARDS, {"customer_id": clean_customer_id}, _to_card, failures
        )
        cases = self._load(
            Source.CASES,
            {"customer_id": clean_customer_id, "as_of": as_of_sql},
            _to_case,
            failures,
        )
        app_events = self._load(
            Source.APP_EVENTS,
            {"customer_id": clean_customer_id, "as_of": as_of_sql},
            _to_app_event,
            failures,
        )

        if len(failures) == len(Source):
            _raise_all_failed(failures)

        failed_reasons = {
            reason for source in failures for reason in SOURCE_REASONS[source]
        }
        return CallClassification(
            reasons=rank(
                transactions=transactions,
                cards=cards,
                cases=cases,
                app_events=app_events,
                as_of=as_of_sql,
                limit=self.TOP_N,
            ),
            unavailable=tuple(r for r in CallReason if r in failed_reasons),
            as_of_date=as_of_sql.date(),
        )

    def _load(
        self,
        source: Source,
        params: Mapping[str, object],
        mapper: Callable[[Mapping[str, Any]], _Candidate],
        failures: dict[Source, Exception],
    ) -> tuple[_Candidate, ...]:
        """Run a source's query and map every row.

        On a data-access or mapping failure, record it in ``failures``, log a
        warning and return no candidates.
        """
        try:
            query = self._query_provider.get(QUERY_NAMES[source])
            rows = self._database_repository.execute_query(query, params)
            return tuple(mapper(row) for row in rows)
        # A mapper raises KeyError, TypeError or ValueError on a bad row.
        except (DataAccessError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "classify_call_type source %s unavailable", source.value, exc_info=True
            )
            failures[source] = exc
            return ()


def _raise_all_failed(failures: Mapping[Source, Exception]) -> None:
    """Raise the domain error for four failed sources.

    Raises:
        DataSourceUnavailableError: At least one failure was on the connection.
        CallReasonLookupError: None was.
    """
    for exc in failures.values():
        if isinstance(exc, DataSourceConnectionError):
            raise DataSourceUnavailableError() from exc
    raise CallReasonLookupError() from next(iter(failures.values()))


def _clean_customer_id(raw: object) -> str:
    """Strip and uppercase the raw id; ids look like ``CLI-ITIECUE8PRH9``.

    There is no format check: an unknown id just finds nothing. Whether the
    caller may see this customer is the Gateway's Cedar policy's job.

    Raises:
        InvalidInputError: The id isn't a string or is blank after stripping.
    """
    if not isinstance(raw, str):
        raise InvalidInputError("customer_id", _INVALID_ID)
    customer_id = raw.strip().upper()
    if not customer_id:
        raise InvalidInputError("customer_id", _INVALID_ID)
    return customer_id


def _utc(as_of: datetime) -> datetime:
    """Return as_of converted to aware UTC.

    Raises:
        ValueError: as_of is naive.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be an aware datetime")
    return as_of.astimezone(timezone.utc)


def _to_transaction(row: Mapping[str, Any]) -> TransactionCandidate:
    """Map a call_reason_transactions row.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type, or transaction_id is None.
        ValueError: The amount or the score isn't finite.
    """
    return TransactionCandidate(
        transaction_id=_required_text(row, "transaction_id"),
        transaction_date=_optional_datetime(row, "transaction_date"),
        card_last4=_optional_text(row, "card_last4"),
        card_currency=_optional_text(row, "card_currency"),
        merchant_name=_optional_text(row, "merchant_name"),
        amount=_optional_amount(row, "amount"),
        currency=_optional_text(row, "currency"),
        transaction_status=_optional_text(row, "transaction_status"),
        response_code=_optional_text(row, "response_code"),
        transaction_country=_optional_text(row, "transaction_country"),
        home_country=_optional_text(row, "home_country"),
        fraud_score=_optional_amount(row, "fraud_score"),
    )


def _to_card(row: Mapping[str, Any]) -> CardCandidate:
    """Map a call_reason_cards row.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type, or card_last4 is None.
    """
    return CardCandidate(
        card_last4=_required_text(row, "card_last4"),
        product_status=_optional_text(row, "product_status"),
        expiration_date=_optional_date(row, "expiration_date"),
        days_past_due=_optional_int(row, "days_past_due"),
    )


def _to_case(row: Mapping[str, Any]) -> CaseCandidate:
    """Map a call_reason_cases row.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type, or complaint_id is None.
    """
    return CaseCandidate(
        complaint_id=_required_text(row, "complaint_id"),
        case_type=_optional_text(row, "case_type"),
        category=_optional_text(row, "category"),
        subcategory=_optional_text(row, "subcategory"),
        status=_optional_text(row, "status"),
        sla_breached=_optional_bool(row, "sla_breached"),
        days_open=_optional_int(row, "days_open"),
        creation_date=_optional_datetime(row, "creation_date"),
    )


def _to_app_event(row: Mapping[str, Any]) -> AppEventCandidate:
    """Map a call_reason_app_events row.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type, or event_id is None.
    """
    return AppEventCandidate(
        event_id=_required_text(row, "event_id"),
        event_date=_optional_datetime(row, "event_date"),
        page_title=_optional_text(row, "page_title"),
        action=_optional_text(row, "action"),
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
