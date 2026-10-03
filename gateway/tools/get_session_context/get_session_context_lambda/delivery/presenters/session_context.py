"""Present the session context as the JSON returned to the agent."""

from collections.abc import Callable
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final, TypeVar

from get_session_context_lambda.domain.entities.session_context import (
    CreditCard,
    Customer,
    DigitalSignal,
    OpenCase,
    RecentTransaction,
    SessionContext,
)

_CENTS: Final = Decimal("0.01")

_Item = TypeVar("_Item")


def present_session_context(context: SessionContext) -> dict[str, Any]:
    """Return the snapshot as JSON-safe values (spec section 4.5).

    An empty section is ``[]``; a section that couldn't be loaded is ``None``
    (JSON null) and is named in ``unavailable``. ``as_of`` is UTC with a ``Z``;
    row timestamps are ISO 8601 without a time zone, as stored. Amounts are
    2-decimal strings, so no float rounding reaches the agent. Missing values
    stay ``None``.
    """
    return {
        "as_of": _as_of(context.as_of),
        "customer": _customer(context.customer),
        "cards": _section(context.cards, _card),
        "recent_transactions": _section(context.recent_transactions, _transaction),
        "digital_signals": _section(context.digital_signals, _signal),
        "open_cases": _section(context.open_cases, _case),
        "truncated": [section.value for section in context.truncated],
        "unavailable": [section.value for section in context.unavailable],
    }


def _section(
    items: tuple[_Item, ...] | None, present: Callable[[_Item], dict[str, Any]]
) -> list[dict[str, Any]] | None:
    """Present every item, keeping None for an unavailable section."""
    if items is None:
        return None
    return [present(item) for item in items]


def _customer(customer: Customer) -> dict[str, Any]:
    """Convert the customer to JSON-safe values."""
    return {
        "customer_id": customer.customer_id,
        "first_name": customer.first_name,
        "country": customer.country,
        "city": customer.city,
        "customer_status": customer.customer_status,
    }


def _card(card: CreditCard) -> dict[str, Any]:
    """Convert one card to JSON-safe values."""
    return {
        "card_last4": card.card_last4,
        "product_status": card.product_status,
        "currency": card.currency,
        "current_balance": _amount(card.current_balance),
        "credit_limit": _amount(card.credit_limit),
        "available_credit": _amount(card.available_credit),
        "expiration_date": _iso(card.expiration_date),
        "days_past_due": card.days_past_due,
    }


def _transaction(transaction: RecentTransaction) -> dict[str, Any]:
    """Convert one transaction to JSON-safe values; flags become their names."""
    return {
        "transaction_id": transaction.transaction_id,
        "transaction_date": _iso(transaction.transaction_date),
        "card_last4": transaction.card_last4,
        "merchant_name": transaction.merchant_name,
        "amount": _amount(transaction.amount),
        "currency": transaction.currency,
        "transaction_status": transaction.transaction_status,
        "transaction_country": transaction.transaction_country,
        "flags": [flag.value for flag in transaction.flags],
    }


def _signal(signal: DigitalSignal) -> dict[str, Any]:
    """Convert one digital signal to JSON-safe values."""
    return {
        "event_date": _iso(signal.event_date),
        "signal": signal.signal,
        "page_title": signal.page_title,
        "ip_country": signal.ip_country,
        "ip_city": signal.ip_city,
    }


def _case(case: OpenCase) -> dict[str, Any]:
    """Convert one open case to JSON-safe values."""
    return {
        "complaint_id": case.complaint_id,
        "case_type": case.case_type,
        "category": case.category,
        "subcategory": case.subcategory,
        "status": case.status,
        "priority": case.priority,
        "sla_breached": case.sla_breached,
        "claimed_amount": _amount(case.claimed_amount),
        "currency": case.currency,
        "days_open": case.days_open,
    }


def _as_of(value: datetime) -> str:
    """Return the aware as_of as ISO 8601 UTC, whole seconds, with a Z."""
    utc = value.astimezone(timezone.utc).isoformat(timespec="seconds")
    return utc.replace("+00:00", "Z")


def _iso(value: date | None) -> str | None:
    """Return a date or a timestamp as ISO 8601, keeping None."""
    return None if value is None else value.isoformat()


def _amount(value: Decimal | None) -> str | None:
    """Round half-up to 2 decimals as a string, keeping None."""
    if value is None:
        return None
    return str(value.quantize(_CENTS, rounding=ROUND_HALF_UP))
