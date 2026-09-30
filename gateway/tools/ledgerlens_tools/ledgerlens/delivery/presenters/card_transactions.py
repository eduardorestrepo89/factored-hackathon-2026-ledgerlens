"""Present card transaction results as the JSON returned to the agent."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from ledgerlens.domain.entities.card_transaction import (
    CardTransaction,
    CardTransactionsResult,
)

_CENTS: Final = Decimal("0.01")


def present_card_transactions(result: CardTransactionsResult) -> dict[str, Any]:
    """Return ``{"transactions": [...], "count": n, "truncated": bool}``.

    Dates are ISO 8601 strings and amounts are 2-decimal strings, so no float
    rounding reaches the agent. Missing values stay ``None`` (JSON null).
    """
    return {
        "transactions": [_present(t) for t in result.transactions],
        "count": len(result.transactions),
        "truncated": result.truncated,
    }


def _present(transaction: CardTransaction) -> dict[str, Any]:
    """Convert one transaction to JSON-safe values."""
    return {
        "transaction_id": transaction.transaction_id,
        "transaction_date": transaction.transaction_date.isoformat(),
        "card_last4": transaction.card_last4,
        "merchant_name": transaction.merchant_name,
        "merchant_category": transaction.merchant_category,
        "amount": str(transaction.amount.quantize(_CENTS, rounding=ROUND_HALF_UP)),
        "currency": transaction.currency,
        "channel": transaction.channel,
        "transaction_city": transaction.transaction_city,
        "transaction_country": transaction.transaction_country,
        "transaction_status": transaction.transaction_status,
    }
