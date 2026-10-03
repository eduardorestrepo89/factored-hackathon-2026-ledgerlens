"""Use case: check one charge, or sweep one card, for fraud."""

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Final

from transaction_fraud_detection_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from transaction_fraud_detection_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
)
from transaction_fraud_detection_lambda.application.ports.query_provider import (
    QueryProvider,
)
from transaction_fraud_detection_lambda.domain.entities.fraud_assessment import (
    CardSweep,
    FraudAssessment,
)
from transaction_fraud_detection_lambda.domain.errors import (
    CardNotFoundError,
    DataSourceUnavailableError,
    FraudCheckDataIntegrityError,
    FraudCheckLookupError,
    TransactionNotFoundError,
)
from transaction_fraud_detection_lambda.domain.value_objects.fraud_bands import (
    REVIEW_ABOVE,
    assess,
)
from transaction_fraud_detection_lambda.domain.value_objects.fraud_check_request import (  # noqa: E501
    FraudCheckRequest,
)

TRANSACTION_QUERY_NAME: Final = "fraud_transaction"
CARD_EXISTS_QUERY_NAME: Final = "fraud_card_exists"
SWEEP_QUERY_NAME: Final = "fraud_card_sweep"


class TransactionFraudDetectionUseCase:
    """Band the fraud engine's stored score through a database-agnostic repository.

    One charge runs fraud_transaction. A card sweep runs fraud_card_exists, then
    fraud_card_sweep, on the repository's single connection. Every failure
    becomes one fixed domain error; the score never leaves this class.
    """

    SWEEP_DAYS: Final = 30

    def __init__(
        self,
        database_repository: DatabaseRepository,
        query_provider: QueryProvider,
        max_rows: int = 25,
    ) -> None:
        """Store the ports and the cap on flagged items.

        Args:
            database_repository: Executes the queries; any DatabaseRepository
                adapter.
            query_provider: Supplies the SQL text for the configured dialect.
            max_rows: Maximum flagged items a sweep returns.

        Raises:
            ValueError: If max_rows is less than 1.
        """
        if max_rows < 1:
            raise ValueError("max_rows must be at least 1")
        self._database_repository: DatabaseRepository = database_repository
        self._query_provider: QueryProvider = query_provider
        self._max_rows: int = max_rows

    def execute(
        self, request: FraudCheckRequest, as_of: datetime
    ) -> FraudAssessment | CardSweep:
        """Check the charge, or sweep the card, as the request says.

        Args:
            request: The validated input; exactly one mode is set.
            as_of: "Now", an aware datetime. Every query gets it as naive UTC,
                because the ERD's timestamp columns have no time zone.

        Raises:
            ValueError: as_of is naive (a programming error, not user input).
            TransactionNotFoundError: No credit-card charge of this customer
                has the transaction_id.
            CardNotFoundError: No credit card of this customer ends in
                card_last4. The sweep query then never runs.
            DataSourceUnavailableError: A query couldn't connect.
            FraudCheckLookupError: A query is missing, failed or hit a limit.
            FraudCheckDataIntegrityError: A row couldn't be mapped.
        """
        as_of_sql = _utc(as_of).replace(tzinfo=None)
        try:
            if request.transaction_id is not None:
                return self._one_charge(
                    request.customer_id, request.transaction_id, as_of_sql
                )
            return self._sweep(request.customer_id, str(request.card_last4), as_of_sql)
        except DataSourceConnectionError as exc:
            raise DataSourceUnavailableError() from exc
        except DataAccessError as exc:
            raise FraudCheckLookupError() from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise FraudCheckDataIntegrityError() from exc

    def _one_charge(
        self, customer_id: str, transaction_id: str, as_of_sql: datetime
    ) -> FraudAssessment:
        """Load and band one charge."""
        rows = self._run(
            TRANSACTION_QUERY_NAME,
            {
                "customer_id": customer_id,
                "transaction_id": transaction_id,
                "as_of": as_of_sql,
            },
        )
        if not rows:
            raise TransactionNotFoundError()
        return _to_assessment(rows[0])

    def _sweep(
        self, customer_id: str, card_last4: str, as_of_sql: datetime
    ) -> CardSweep:
        """Check the card exists, then load its flagged charges and the count.

        The sweep query returns a count-only row (NULL transaction columns)
        when nothing is flagged, so ``checked`` is right for a clean card.
        """
        params = {"customer_id": customer_id, "card_last4": card_last4}
        if not self._run(CARD_EXISTS_QUERY_NAME, params):
            raise CardNotFoundError()
        rows = self._run(
            SWEEP_QUERY_NAME,
            {
                **params,
                "as_of": as_of_sql,
                "review_above": REVIEW_ABOVE,
                "limit": self._max_rows + 1,
            },
        )
        checked = _required_int(rows[0], "checked") if rows else 0
        items = [row for row in rows if row["transaction_id"] is not None]
        return CardSweep(
            card_last4=card_last4,
            date_from=as_of_sql - timedelta(days=self.SWEEP_DAYS),
            date_to=as_of_sql,
            checked=checked,
            flagged=tuple(_to_assessment(row) for row in items[: self._max_rows]),
            truncated=len(items) > self._max_rows,
        )

    def _run(self, name: str, params: Mapping[str, object]) -> list[dict[str, Any]]:
        """Load the named SQL and run it.

        Raises:
            DataAccessError: The query is missing or failed.
        """
        query = self._query_provider.get(name)
        return self._database_repository.execute_query(query, params)


def _utc(as_of: datetime) -> datetime:
    """Return as_of converted to aware UTC.

    Raises:
        ValueError: as_of is naive.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be an aware datetime")
    return as_of.astimezone(timezone.utc)


def _to_assessment(row: Mapping[str, Any]) -> FraudAssessment:
    """Band the row's score and map the row; the score itself is dropped."""
    verdict, basis = assess(_optional_score(row, "fraud_score"))
    return FraudAssessment(
        transaction_id=_required_text(row, "transaction_id"),
        transaction_date=_optional_datetime(row, "transaction_date"),
        card_last4=_optional_text(row, "card_last4"),
        merchant_name=_optional_text(row, "merchant_name"),
        amount=_optional_amount(row, "amount"),
        currency=_optional_text(row, "currency"),
        transaction_status=_optional_text(row, "transaction_status"),
        verdict=verdict,
        basis=basis,
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


def _optional_score(row: Mapping[str, Any], column: str) -> Decimal | None:
    """Return the nullable score as a finite Decimal; only Decimal or int pass.

    numeric(5,2) arrives as Decimal. A float, string or bool means the column
    or the driver changed, so the row is rejected instead of guessing a verdict.
    """
    value = row[column]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Decimal | int):
        raise TypeError(f"{column} is {type(value).__name__}, expected a numeric")
    score = value if isinstance(value, Decimal) else Decimal(value)
    if not score.is_finite():
        raise ValueError(f"{column} is not finite")
    return score


def _optional_datetime(row: Mapping[str, Any], column: str) -> datetime | None:
    """Return a nullable timestamp column as it is stored."""
    value = row[column]
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    raise TypeError(f"{column} is {type(value).__name__}, expected a timestamp")


def _required_int(row: Mapping[str, Any], column: str) -> int:
    """Return an integer column that must not be NULL; bool is rejected."""
    value = row[column]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{column} is {type(value).__name__}, expected an integer")
    return value
