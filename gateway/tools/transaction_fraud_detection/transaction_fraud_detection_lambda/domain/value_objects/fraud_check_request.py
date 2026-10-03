"""The validated input of one fraud check."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from transaction_fraud_detection_lambda.domain.errors import InvalidInputError

# ASCII digits only: str.isdigit() and \d also accept digits of other scripts.
_LAST4: Final = re.compile(r"[0-9]{4}")


@dataclass(frozen=True)
class FraudCheckRequest:
    """One fraud check: one charge, or a sweep of one card's last 30 days.

    Exactly one of transaction_id and card_last4 is set.
    """

    customer_id: str
    transaction_id: str | None
    card_last4: str | None

    @classmethod
    def from_raw(cls, event: object) -> "FraudCheckRequest":
        """Validate the tool arguments. Unknown keys are ignored.

        An event that isn't a JSON object is treated as ``{}``. A blank
        transaction_id or card_last4 counts as missing.

        Raises:
            InvalidInputError: A field is invalid, both modes are given, or
                neither is.
        """
        raw: Mapping[object, object] = event if isinstance(event, Mapping) else {}
        customer_id = _customer_id(raw.get("customer_id"))
        transaction_id = _transaction_id(raw.get("transaction_id"))
        card_last4 = _card_last4(raw.get("card_last4"))
        if transaction_id is not None and card_last4 is not None:
            raise InvalidInputError(
                "transaction_id", "give either transaction_id or card_last4, not both"
            )
        if transaction_id is None and card_last4 is None:
            raise InvalidInputError(
                "transaction_id",
                "give either transaction_id (one charge) or card_last4 "
                "(sweep of that card's last 30 days)",
            )
        return cls(
            customer_id=customer_id,
            transaction_id=transaction_id,
            card_last4=card_last4,
        )


def _customer_id(value: object) -> str:
    """Strip and uppercase the id; ids look like ``CLI-EX6BOAOEFZHQ``."""
    if not isinstance(value, str) or not value.strip():
        raise InvalidInputError(
            "customer_id", "is required and must be a non-empty string"
        )
    return value.strip().upper()


def _transaction_id(value: object) -> str | None:
    """Strip and uppercase the id; None or blank means not given."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidInputError("transaction_id", "must be a non-empty string")
    stripped = value.strip()
    return stripped.upper() if stripped else None


def _card_last4(value: object) -> str | None:
    """Return exactly 4 ASCII digits; None or blank means not given."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidInputError("card_last4", "must be exactly 4 digits")
    stripped = value.strip()
    if not stripped:
        return None
    if _LAST4.fullmatch(stripped) is None:
        raise InvalidInputError("card_last4", "must be exactly 4 digits")
    return stripped
