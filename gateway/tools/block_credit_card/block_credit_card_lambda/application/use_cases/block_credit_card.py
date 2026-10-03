"""Use case: block one of a customer's credit cards."""

import logging
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Final

from block_credit_card_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from block_credit_card_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    WriteConflictError,
)
from block_credit_card_lambda.application.ports.query_provider import QueryProvider
from block_credit_card_lambda.domain.entities.card_block import CardBlock
from block_credit_card_lambda.domain.errors import (
    AmbiguousCardError,
    CardClosedError,
    CardDataIntegrityError,
    CardNotFoundError,
    CardUpdateError,
    DataSourceUnavailableError,
    InvalidInputError,
)

logger = logging.getLogger(__name__)

BLOCKED: Final = "Blocked"
CLOSED: Final = "Closed"
REASONS: Final = ("customer_request", "lost", "stolen", "suspected_fraud")
_LAST4: Final = re.compile(r"[0-9]{4}")


class BlockCreditCardUseCase:
    """Block one of the customer's credit cards through a database-agnostic repository.

    The card is found by its last 4 digits, then blocked with a guarded UPDATE
    that only changes a card that is neither blocked nor closed. Both statements
    are safe to run twice. Port errors become domain errors whose messages tell
    the agent what to do next.
    """

    FIND_QUERY: Final = "find_credit_card"
    BLOCK_QUERY: Final = "block_credit_card"

    def __init__(
        self,
        database_repository: DatabaseRepository,
        query_provider: QueryProvider,
    ) -> None:
        """Store the ports."""
        self._database_repository: DatabaseRepository = database_repository
        self._query_provider: QueryProvider = query_provider

    def execute(
        self,
        customer_id: object,
        card_last4: object,
        reason: object,
        customer_confirmed: object,
        now: datetime,
    ) -> CardBlock:
        """Validate every input, then block the card unless it already is.

        Args:
            customer_id: The customer id exactly as it came in the tool event.
            card_last4: The card's last 4 digits, as they came.
            reason: suspected_fraud, lost, stolen or customer_request, as it came.
            customer_confirmed: Must be the boolean True.
            now: The tool's "now" (AS_OF in demos), written as last_updated.

        Raises:
            InvalidInputError: An input is invalid, or customer_confirmed isn't
                true. Raised before the database is touched.
            CardNotFoundError: No credit card of the customer ends in the digits.
            AmbiguousCardError: More than one does.
            CardClosedError: The card is closed.
            DataSourceUnavailableError: The database can't be reached, or kept
                reporting write conflicts.
            CardUpdateError: A query failed, or the card couldn't be blocked.
            CardDataIntegrityError: A returned row couldn't be read.
        """
        customer = _clean_customer_id(customer_id)
        last4 = _clean_card_last4(card_last4)
        clean_reason = _clean_reason(reason)
        _require_confirmation(customer_confirmed)
        try:
            already_blocked = self._block(customer, last4, _naive_utc(now))
        except (DataSourceConnectionError, WriteConflictError) as exc:
            raise DataSourceUnavailableError() from exc
        except DataAccessError as exc:
            raise CardUpdateError() from exc
        # products has no column for the reason: this line is its only record.
        logger.info(
            "block_credit_card audit: customer_id=%s card_last4=%s reason=%s "
            "already_blocked=%s",
            customer,
            last4,
            clean_reason,
            already_blocked,
        )
        return CardBlock(
            card_last4=last4, status=BLOCKED, already_blocked=already_blocked
        )

    def _block(self, customer_id: str, card_last4: str, last_updated: datetime) -> bool:
        """Block the card; return True when it was already blocked."""
        product_id = self._card_to_block(customer_id, card_last4)
        if product_id is None:
            return True
        updated = self._run(
            self.BLOCK_QUERY,
            {
                "customer_id": customer_id,
                "product_id": product_id,
                "last_updated": last_updated,
            },
        )
        if updated:
            return False
        # The card changed between the two statements, or a retry after a lost
        # reply found its own committed UPDATE: decide from the card as it is now.
        if self._card_to_block(customer_id, card_last4) is None:
            return True
        raise CardUpdateError()

    def _card_to_block(self, customer_id: str, card_last4: str) -> str | None:
        """Return the product_id to block, or None when the card is already blocked.

        Raises:
            CardNotFoundError, AmbiguousCardError, CardClosedError: The card
                can't be blocked here.
            CardDataIntegrityError: The row couldn't be read.
        """
        rows = self._run(
            self.FIND_QUERY, {"customer_id": customer_id, "card_last4": card_last4}
        )
        if not rows:
            raise CardNotFoundError(card_last4)
        if len(rows) > 1:
            raise AmbiguousCardError(card_last4)
        try:
            product_id = _text(rows[0], "product_id")
            status = _text(rows[0], "product_status")
        except (KeyError, TypeError) as exc:
            raise CardDataIntegrityError() from exc
        if status == BLOCKED:
            return None
        if status == CLOSED:
            raise CardClosedError(card_last4)
        return product_id

    def _run(self, name: str, params: Mapping[str, object]) -> list[dict[str, Any]]:
        """Load the named SQL and run it."""
        query = self._query_provider.get(name)
        return self._database_repository.execute_query(query, params)


def _clean_customer_id(raw: object) -> str:
    """Strip and uppercase the raw id; ids look like ``CLI-ITIECUE8PRH9``.

    Raises:
        InvalidInputError: The id isn't a string or is blank after stripping.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidInputError(
            "customer_id", "is required and must be a non-empty string"
        )
    return raw.strip().upper()


def _clean_card_last4(raw: object) -> str:
    """Strip the digits; they must be exactly 4 ASCII digits.

    Raises:
        InvalidInputError: Not a string, or not 4 ASCII digits after stripping.
    """
    if isinstance(raw, str) and _LAST4.fullmatch(raw.strip()):
        return raw.strip()
    raise InvalidInputError("card_last4", "must be exactly 4 digits")


def _clean_reason(raw: object) -> str:
    """Strip and lowercase the reason; it must be one of REASONS.

    Raises:
        InvalidInputError: Not one of REASONS.
    """
    if isinstance(raw, str) and raw.strip().lower() in REASONS:
        return raw.strip().lower()
    raise InvalidInputError("reason", f"must be one of: {', '.join(REASONS)}")


def _require_confirmation(raw: object) -> None:
    """Only the boolean True confirms; "true", 1 or a missing value don't.

    The Gateway's Cedar statement 3 will check it too (spec section 10).

    Raises:
        InvalidInputError: The value isn't True.
    """
    if raw is not True:
        raise InvalidInputError(
            "customer_confirmed",
            "must be true, after the customer explicitly confirmed the block",
        )


def _naive_utc(now: datetime) -> datetime:
    """Return ``now`` as naive UTC: products.last_updated has no time zone."""
    if now.tzinfo is None:
        return now
    return now.astimezone(timezone.utc).replace(tzinfo=None)


def _text(row: Mapping[str, Any], column: str) -> str:
    """Return a non-empty text column.

    Raises:
        KeyError: The column is missing.
        TypeError: The value isn't a non-empty string.
    """
    value = row[column]
    if not isinstance(value, str) or not value:
        raise TypeError(f"{column} is {type(value).__name__}, expected text")
    return value
