"""Validated search criteria for listing a customer's card transactions."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Final

from list_card_transactions_lambda.domain.errors import InvalidInputError

DEFAULT_WINDOW_DAYS: Final = 30
MAX_WINDOW_DAYS: Final = 180
MAX_MERCHANT_LENGTH: Final = 100

# Strict patterns: Python 3.11+ date.fromisoformat also accepts "20260901", so the
# format is checked first to behave the same on 3.10 (local) and 3.13 (Lambda).
_ISO_DATE: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_CARD_LAST4: Final = re.compile(r"[0-9]{4}")


class TransactionStatus(str, Enum):
    """Transaction statuses the agent can filter by.

    These are every ``transactions.transaction_status`` value in the dataset.
    Update this enum and tool_spec.json together.
    """

    APPROVED = "Approved"
    DECLINED = "Declined"
    PENDING = "Pending"
    REVERSED = "Reversed"


@dataclass(frozen=True)
class TransactionFilters:
    """Validated search criteria for a customer's card transactions.

    Attributes:
        customer_id: Customer whose transactions are searched.
        date_from: First processing date included (inclusive).
        date_to: Last processing date included (inclusive).
        card_last4: Last four digits of one card, or None for every card.
        merchant: Substring of the merchant name, matched ignoring case and
            accents, or None.
        min_amount: Smallest amount included, or None.
        max_amount: Largest amount included, or None.
        status: Transaction status to match, or None for any status.
    """

    customer_id: str
    date_from: date
    date_to: date
    card_last4: str | None = None
    merchant: str | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    status: TransactionStatus | None = None

    @classmethod
    def from_raw(cls, raw: object, today: date) -> "TransactionFilters":
        """Parse untyped tool input, apply the defaults and validate it.

        Empty strings and nulls in optional fields mean "no filter".

        Args:
            raw: The tool arguments exactly as received from the Gateway.
            today: Current UTC date, passed in so tests are deterministic.

        Returns:
            The validated filters.

        Raises:
            InvalidInputError: If any argument breaks a validation rule.
        """
        if not isinstance(raw, Mapping):
            raise InvalidInputError("input", "must be a JSON object")

        customer_id = raw.get("customer_id")
        if not isinstance(customer_id, str) or not customer_id.strip():
            raise InvalidInputError(
                "customer_id", "is required and must be a non-empty string"
            )

        parsed_to = _parse_date(raw, "date_to")
        date_to = parsed_to if parsed_to is not None else today
        parsed_from = _parse_date(raw, "date_from")
        date_from = (
            parsed_from
            if parsed_from is not None
            else date_to - timedelta(days=DEFAULT_WINDOW_DAYS)
        )
        if date_from > date_to:
            raise InvalidInputError("date_from", "must be on or before date_to")
        if (date_to - date_from).days > MAX_WINDOW_DAYS:
            raise InvalidInputError(
                "date_from", f"the date range can't exceed {MAX_WINDOW_DAYS} days"
            )

        min_amount = _parse_amount(raw, "min_amount")
        max_amount = _parse_amount(raw, "max_amount")
        if (
            min_amount is not None
            and max_amount is not None
            and min_amount > max_amount
        ):
            raise InvalidInputError(
                "min_amount", "must be less than or equal to max_amount"
            )

        return cls(
            customer_id=customer_id.strip(),
            date_from=date_from,
            date_to=date_to,
            card_last4=_parse_card_last4(raw),
            merchant=_parse_merchant(raw),
            min_amount=min_amount,
            max_amount=max_amount,
            status=_parse_status(raw),
        )


def _optional_text(raw: Mapping[str, Any], field: str) -> str | None:
    """Return the trimmed string value of ``field``, or None if null or blank.

    Raises:
        InvalidInputError: If the value is present but not a string.
    """
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidInputError(field, "must be a string")
    return value.strip() or None


def _parse_date(raw: Mapping[str, Any], field: str) -> date | None:
    """Parse an optional YYYY-MM-DD date.

    Raises:
        InvalidInputError: If the value has another format or isn't a real date.
    """
    text = _optional_text(raw, field)
    if text is None:
        return None
    if not _ISO_DATE.fullmatch(text):
        raise InvalidInputError(field, "must be a date in YYYY-MM-DD format")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise InvalidInputError(field, "is not a real calendar date") from exc


def _parse_card_last4(raw: Mapping[str, Any]) -> str | None:
    """Parse the optional last four card digits.

    Raises:
        InvalidInputError: If the value isn't exactly four ASCII digits.
    """
    value = raw.get("card_last4")
    if value is not None and not isinstance(value, str):
        raise InvalidInputError("card_last4", "must be exactly 4 digits as a string")
    text = _optional_text(raw, "card_last4")
    if text is not None and not _CARD_LAST4.fullmatch(text):
        raise InvalidInputError("card_last4", "must be exactly 4 digits")
    return text


def _parse_merchant(raw: Mapping[str, Any]) -> str | None:
    """Parse the optional merchant search text.

    Raises:
        InvalidInputError: If the text is longer than MAX_MERCHANT_LENGTH.
    """
    text = _optional_text(raw, "merchant")
    if text is not None and len(text) > MAX_MERCHANT_LENGTH:
        raise InvalidInputError(
            "merchant", f"must be at most {MAX_MERCHANT_LENGTH} characters"
        )
    return text


def _parse_amount(raw: Mapping[str, Any], field: str) -> Decimal | None:
    """Parse an optional non-negative amount into an exact Decimal.

    Floats are converted through ``str`` so 10.5 becomes Decimal("10.5"), not its
    binary approximation.

    Raises:
        InvalidInputError: If the value is a boolean, not numeric, not finite or
            negative.
    """
    value = raw.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str | Decimal):
        raise InvalidInputError(field, "must be a number")
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise InvalidInputError(field, "must be a number") from exc
    if not amount.is_finite():
        raise InvalidInputError(field, "must be a finite number")
    if amount < 0:
        raise InvalidInputError(field, "must be zero or greater")
    return amount


def _parse_status(raw: Mapping[str, Any]) -> TransactionStatus | None:
    """Parse the optional status, matching the enum values case-insensitively.

    Raises:
        InvalidInputError: If the value isn't one of TransactionStatus.
    """
    text = _optional_text(raw, "status")
    if text is None:
        return None
    for status in TransactionStatus:
        if status.value.casefold() == text.casefold():
            return status
    allowed = ", ".join(status.value for status in TransactionStatus)
    raise InvalidInputError("status", f"must be one of {allowed}")
