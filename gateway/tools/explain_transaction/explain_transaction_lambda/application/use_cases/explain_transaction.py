"""Use case: explain one credit-card charge."""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final, TypeVar

from explain_transaction_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from explain_transaction_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
)
from explain_transaction_lambda.application.ports.query_provider import QueryProvider
from explain_transaction_lambda.domain.entities.transaction_explanation import (
    AppActivity,
    DeclineInfo,
    ExplainedTransaction,
    FxConversion,
    Section,
    SpendingHabit,
    TransactionExplanation,
    UsualAmountRange,
)
from explain_transaction_lambda.domain.errors import (
    DataSourceUnavailableError,
    ExplainDataIntegrityError,
    ExplainLookupError,
    InvalidInputError,
    TransactionNotFoundError,
)
from explain_transaction_lambda.domain.value_objects.decline_codes import (
    DECLINE_MEANINGS,
    EXPIRED_CARD_CODE,
    IN_PERSON_CHANNELS,
)
from explain_transaction_lambda.domain.value_objects.text_folding import fold_text

logger = logging.getLogger(__name__)

CORE_QUERY_NAME: Final = "explain_transaction"
# The query of each optional section, in Section order.
SECTION_QUERY_NAMES: Final[Mapping[Section, str]] = {
    Section.HABIT: "transaction_habit",
    Section.APP_ACTIVITY: "transaction_app_activity",
}
# One or two charges don't make a range.
MIN_RANGE_CHARGES: Final = 3

_DECLINED: Final = "Declined"
_CENTS: Final = Decimal("0.01")
_INVALID_ID: Final = "is required and must be a non-empty string"

_Value = TypeVar("_Value")


@dataclass(frozen=True)
class _CardFacts:
    """Core-row columns the use case needs but never returns."""

    product_id: str
    card_currency: str | None
    card_expiration_date: date | None
    response_code: str | None
    fx_sell_rate: Decimal | None


class ExplainTransactionUseCase:
    """Explain one charge through a database-agnostic repository.

    Up to three queries run one after another on the repository's single
    connection. The core query (the charge) is required: its failure fails the
    call with a domain error. fx and decline come from the core row. Habit and app
    activity each fail on their own: the section becomes None and is listed in
    ``unavailable``, and the next one still runs.
    """

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

    def execute(
        self, customer_id: object, transaction_id: object, as_of: datetime
    ) -> TransactionExplanation:
        """Clean the inputs, load the charge, then its habit and app activity.

        Args:
            customer_id: The customer id exactly as it came in the tool event.
            transaction_id: The charge's id exactly as it came in the tool event.
            as_of: "Now", an aware datetime. Every query gets it as naive UTC,
                because the ERD's timestamp columns have no time zone.

        Raises:
            InvalidInputError: customer_id or transaction_id is missing, not a
                string or blank, checked in that order. Raised before the
                database is touched.
            ValueError: as_of is naive (a programming error, not user input).
            DataSourceUnavailableError: The core query couldn't connect.
            ExplainLookupError: The core query is missing, failed or hit a
                database limit.
            TransactionNotFoundError: No credit-card charge of this customer has
                the transaction_id.
            ExplainDataIntegrityError: The core row couldn't be mapped.
        """
        clean_customer_id = _clean_customer_id(customer_id)
        clean_transaction_id = _clean_transaction_id(transaction_id)
        as_of_sql = _utc(as_of).replace(tzinfo=None)
        transaction, facts = self._core(
            clean_customer_id, clean_transaction_id, as_of_sql
        )
        fx = _fx(transaction, facts)
        decline = _decline(transaction, facts)

        charge_date = transaction.transaction_date
        if charge_date is None:
            logger.warning(
                "explain_transaction charge has no transaction_date; "
                "habit and app_activity skipped"
            )
            return TransactionExplanation(
                transaction=transaction,
                fx=fx,
                decline=decline,
                habit=None,
                app_activity=None,
                unavailable=(Section.HABIT, Section.APP_ACTIVITY),
            )

        habit = self._section(
            Section.HABIT,
            {
                "customer_id": clean_customer_id,
                "product_id": facts.product_id,
                "transaction_id": transaction.transaction_id,
                "charge_date": charge_date,
                "merchant_name": transaction.merchant_name,
                "currency": transaction.currency,
                "transaction_country": transaction.transaction_country,
            },
            lambda rows: _to_habit(rows, transaction.currency),
        )
        app_activity = self._section(
            Section.APP_ACTIVITY,
            {
                "customer_id": clean_customer_id,
                "charge_date": charge_date,
                "as_of": as_of_sql,
            },
            lambda rows: _to_app_activity(rows, transaction, charge_date),
        )
        return TransactionExplanation(
            transaction=transaction,
            fx=fx,
            decline=decline,
            habit=habit,
            app_activity=app_activity,
            unavailable=tuple(
                section
                for section, value in (
                    (Section.HABIT, habit),
                    (Section.APP_ACTIVITY, app_activity),
                )
                if value is None
            ),
        )

    def _core(
        self, customer_id: str, transaction_id: str, as_of_sql: datetime
    ) -> tuple[ExplainedTransaction, _CardFacts]:
        """Load and map the charge, translating every failure.

        Raises:
            DataSourceUnavailableError: The query couldn't connect.
            ExplainLookupError: Any other data-access failure.
            TransactionNotFoundError: No row came back.
            ExplainDataIntegrityError: The row couldn't be mapped.
        """
        try:
            rows = self._run(
                CORE_QUERY_NAME,
                {
                    "customer_id": customer_id,
                    "transaction_id": transaction_id,
                    "as_of": as_of_sql,
                },
            )
        except DataSourceConnectionError as exc:
            raise DataSourceUnavailableError() from exc
        except DataAccessError as exc:
            raise ExplainLookupError() from exc
        if not rows:
            raise TransactionNotFoundError()
        try:
            return _to_transaction(rows[0]), _to_card_facts(rows[0])
        except (KeyError, TypeError, ValueError) as exc:
            raise ExplainDataIntegrityError() from exc

    def _section(
        self,
        section: Section,
        params: Mapping[str, object],
        mapper: Callable[[list[dict[str, Any]]], _Value],
    ) -> _Value | None:
        """Run a section's query and map its rows; on any failure return None."""
        try:
            return mapper(self._run(SECTION_QUERY_NAMES[section], params))
        except (DataAccessError, KeyError, TypeError, ValueError):
            logger.warning(
                "explain_transaction section %s unavailable",
                section.value,
                exc_info=True,
            )
            return None

    def _run(self, name: str, params: Mapping[str, object]) -> list[dict[str, Any]]:
        """Load the named SQL and run it.

        Raises:
            DataAccessError: The query is missing or failed.
        """
        query = self._query_provider.get(name)
        return self._database_repository.execute_query(query, params)


def _clean_customer_id(raw: object) -> str:
    """Strip and uppercase the raw id; ids look like ``CLI-ITIECUE8PRH9``.

    There is no format check: a malformed or unknown id just finds no charge.
    Whether the caller may see this customer is the Gateway's Cedar policy's job.

    Raises:
        InvalidInputError: The id isn't a string or is blank after stripping.
    """
    if not isinstance(raw, str):
        raise InvalidInputError("customer_id", _INVALID_ID)
    customer_id = raw.strip().upper()
    if not customer_id:
        raise InvalidInputError("customer_id", _INVALID_ID)
    return customer_id


def _clean_transaction_id(raw: object) -> str:
    """Strip and uppercase the raw id; ids look like ``TRX-23BIJAU4GL46ATPW9STY``.

    There is no format check: a malformed or unknown id just finds no charge.

    Raises:
        InvalidInputError: The id isn't a string or is blank after stripping.
    """
    if not isinstance(raw, str):
        raise InvalidInputError("transaction_id", _INVALID_ID)
    transaction_id = raw.strip().upper()
    if not transaction_id:
        raise InvalidInputError("transaction_id", _INVALID_ID)
    return transaction_id


def _utc(as_of: datetime) -> datetime:
    """Return as_of converted to aware UTC.

    Raises:
        ValueError: as_of is naive.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be an aware datetime")
    return as_of.astimezone(timezone.utc)


def _to_transaction(row: Mapping[str, Any]) -> ExplainedTransaction:
    """Map the core row to the charge.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type, or transaction_id is None.
        ValueError: The amount isn't finite.
    """
    return ExplainedTransaction(
        transaction_id=_required_text(row, "transaction_id"),
        transaction_date=_optional_datetime(row, "transaction_date"),
        card_last4=_optional_text(row, "card_last4"),
        merchant_name=_optional_text(row, "merchant_name"),
        merchant_category=_optional_text(row, "merchant_category"),
        amount=_optional_amount(row, "amount"),
        currency=_optional_text(row, "currency"),
        channel=_optional_text(row, "channel"),
        transaction_city=_optional_text(row, "transaction_city"),
        transaction_country=_optional_text(row, "transaction_country"),
        transaction_status=_optional_text(row, "transaction_status"),
    )


def _to_card_facts(row: Mapping[str, Any]) -> _CardFacts:
    """Map the core row's internal columns.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type, or product_id is None.
        ValueError: The rate isn't finite.
    """
    return _CardFacts(
        product_id=_required_text(row, "product_id"),
        card_currency=_optional_text(row, "card_currency"),
        card_expiration_date=_optional_date(row, "card_expiration_date"),
        response_code=_optional_text(row, "response_code"),
        fx_sell_rate=_optional_amount(row, "fx_sell_rate"),
    )


def _fx(transaction: ExplainedTransaction, facts: _CardFacts) -> FxConversion | None:
    """Convert a charge in another currency; None when the currencies match."""
    if (
        transaction.currency is None
        or facts.card_currency is None
        or transaction.currency == facts.card_currency
    ):
        return None
    rate = facts.fx_sell_rate
    converted = (
        None
        if rate is None or transaction.amount is None
        else (transaction.amount * rate).quantize(_CENTS, rounding=ROUND_HALF_UP)
    )
    charge_date = transaction.transaction_date
    return FxConversion(
        card_currency=facts.card_currency,
        rate_date=None if charge_date is None else charge_date.date(),
        rate=rate,
        amount_in_card_currency=converted,
    )


def _decline(
    transaction: ExplainedTransaction, facts: _CardFacts
) -> DeclineInfo | None:
    """Explain a declined charge; None for any other status."""
    if transaction.transaction_status != _DECLINED:
        return None
    code = facts.response_code
    return DeclineInfo(
        response_code=code,
        meaning=None if code is None else DECLINE_MEANINGS.get(code),
        contradicts_card_state=_contradicts_card_state(
            code, facts.card_expiration_date, transaction.transaction_date
        ),
    )


def _contradicts_card_state(
    code: str | None, expiration_date: date | None, charge_date: datetime | None
) -> bool | None:
    """Whether "expired card" was given for a card still valid that day (D18).

    Any code other than 54 contradicts nothing. For 54, a card that expires on
    the charge day or later wasn't expired; without both dates it can't be told.
    """
    if code != EXPIRED_CARD_CODE:
        return False
    if expiration_date is None or charge_date is None:
        return None
    return expiration_date >= charge_date.date()


def _to_habit(rows: list[dict[str, Any]], currency: str | None) -> SpendingHabit:
    """Map the one aggregate row of transaction_habit.

    Raises:
        ValueError: No row came back, or an amount isn't finite.
        KeyError: A column is missing.
        TypeError: A column has the wrong type, or a count is None.
    """
    if not rows:
        raise ValueError("transaction_habit returned no row")
    row = rows[0]
    history_count = _required_int(row, "history_count")
    same_currency_count = _required_int(row, "same_currency_count")
    low = _optional_amount(row, "usual_low")
    high = _optional_amount(row, "usual_high")
    usual_amount_range = (
        None
        if currency is None
        or same_currency_count < MIN_RANGE_CHARGES
        or low is None
        or high is None
        else UsualAmountRange(low=low, high=high, currency=currency)
    )
    return SpendingHabit(
        history_count=history_count,
        times_at_merchant_90d=_optional_int(row, "times_at_merchant"),
        usual_amount_range=usual_amount_range,
        country_seen_before=_optional_bool(row, "country_seen_before"),
    )


def _to_app_activity(
    rows: list[dict[str, Any]],
    transaction: ExplainedTransaction,
    charge_date: datetime,
) -> AppActivity:
    """Map the closest event; no row means found=False, not a failure.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type, or event_date is None.
    """
    if not rows:
        return AppActivity(found=False)
    row = rows[0]
    event_date = _required_datetime(row, "event_date")
    ip_country = _optional_text(row, "ip_country")
    return AppActivity(
        found=True,
        event_date=event_date,
        minutes_from_charge=round((event_date - charge_date).total_seconds() / 60),
        ip_country=ip_country,
        ip_city=_optional_text(row, "ip_city"),
        conflict=_conflict(
            transaction.channel, transaction.transaction_country, ip_country
        ),
    )


def _conflict(
    channel: str | None, country: str | None, ip_country: str | None
) -> bool | None:
    """Whether the app was in another country during an in-person charge.

    App and Web charges never conflict: they can come from anywhere. Countries
    compare without accents, case or spaces ("México" equals " MEXICO ").
    """
    if channel is None or country is None or ip_country is None:
        return None
    return channel in IN_PERSON_CHANNELS and fold_text(ip_country) != fold_text(country)


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


def _required_datetime(row: Mapping[str, Any], column: str) -> datetime:
    """Return a timestamp column that must not be NULL."""
    value = _optional_datetime(row, column)
    if value is None:
        raise TypeError(f"{column} is None, expected a timestamp")
    return value


def _optional_int(row: Mapping[str, Any], column: str) -> int | None:
    """Return a nullable integer column; bool is rejected."""
    value = row[column]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{column} is {type(value).__name__}, expected an integer")
    return value


def _required_int(row: Mapping[str, Any], column: str) -> int:
    """Return an integer column that must not be NULL; bool is rejected."""
    value = _optional_int(row, column)
    if value is None:
        raise TypeError(f"{column} is None, expected an integer")
    return value


def _optional_bool(row: Mapping[str, Any], column: str) -> bool | None:
    """Return a nullable boolean column; only bool or None is accepted."""
    value = row[column]
    if value is None or isinstance(value, bool):
        return value
    raise TypeError(f"{column} is {type(value).__name__}, expected a boolean")
