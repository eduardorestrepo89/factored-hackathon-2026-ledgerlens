"""Present credit card results as the JSON returned to the agent."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from list_credit_cards_lambda.domain.entities.credit_card import (
    CreditCard,
    CreditCardsResult,
)

_CENTS: Final = Decimal("0.01")


def present_credit_cards(result: CreditCardsResult) -> dict[str, Any]:
    """Return ``{"cards": [...] | None, "count": n, "truncated": bool}``.

    ``cards`` is ``None`` (JSON null) when the customer has no credit cards; the
    agent then tells the customer they have none. Dates are ISO 8601 strings and
    amounts are 2-decimal strings, so no float rounding reaches the agent.
    Missing values stay ``None``.
    """
    return {
        "cards": [_present(card) for card in result.cards] if result.cards else None,
        "count": len(result.cards),
        "truncated": result.truncated,
    }


def _present(card: CreditCard) -> dict[str, Any]:
    """Convert one card to JSON-safe values."""
    return {
        "card_last4": card.card_last4,
        "product_status": card.product_status,
        "currency": card.currency,
        "current_balance": _amount(card.current_balance),
        "credit_limit": _amount(card.credit_limit),
        "available_credit": _amount(card.available_credit),
        "expiration_date": (
            None if card.expiration_date is None else card.expiration_date.isoformat()
        ),
        "days_past_due": card.days_past_due,
    }


def _amount(value: Decimal | None) -> str | None:
    """Round half-up to 2 decimals as a string, keeping None."""
    if value is None:
        return None
    return str(value.quantize(_CENTS, rounding=ROUND_HALF_UP))
