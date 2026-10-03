"""Present a transaction explanation as the JSON returned to the agent."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from explain_transaction_lambda.domain.entities.transaction_explanation import (
    AppActivity,
    DeclineInfo,
    ExplainedTransaction,
    FxConversion,
    SpendingHabit,
    TransactionExplanation,
    UsualAmountRange,
)

_CENTS: Final = Decimal("0.01")


def present_transaction_explanation(
    explanation: TransactionExplanation,
) -> dict[str, Any]:
    """Return the explanation as JSON-safe values (spec section 5).

    Amounts are 2-decimal strings rounded half up; the rate keeps its stored
    decimals. Timestamps are ISO 8601 without a time zone, as stored. Missing
    values stay None. There is no fraud or score field.
    """
    return {
        "transaction": _transaction(explanation.transaction),
        "fx": _fx(explanation.fx),
        "decline": _decline(explanation.decline),
        "habit": _habit(explanation.habit),
        "app_activity": _app_activity(explanation.app_activity),
        "unavailable": [section.value for section in explanation.unavailable],
    }


def _transaction(transaction: ExplainedTransaction) -> dict[str, Any]:
    """Present the charge itself."""
    return {
        "transaction_id": transaction.transaction_id,
        "transaction_date": _iso(transaction.transaction_date),
        "card_last4": transaction.card_last4,
        "merchant_name": transaction.merchant_name,
        "merchant_category": transaction.merchant_category,
        "amount": _amount(transaction.amount),
        "currency": transaction.currency,
        "channel": transaction.channel,
        "transaction_city": transaction.transaction_city,
        "transaction_country": transaction.transaction_country,
        "transaction_status": transaction.transaction_status,
    }


def _fx(fx: FxConversion | None) -> dict[str, Any] | None:
    """Present the conversion; the rate in plain notation, never exponent form."""
    if fx is None:
        return None
    return {
        "card_currency": fx.card_currency,
        "rate_date": _iso(fx.rate_date),
        "rate": None if fx.rate is None else format(fx.rate, "f"),
        "amount_in_card_currency": _amount(fx.amount_in_card_currency),
    }


def _decline(decline: DeclineInfo | None) -> dict[str, Any] | None:
    """Present why the charge was declined."""
    if decline is None:
        return None
    return {
        "response_code": decline.response_code,
        "meaning": decline.meaning,
        "contradicts_card_state": decline.contradicts_card_state,
    }


def _habit(habit: SpendingHabit | None) -> dict[str, Any] | None:
    """Present the habit; None means its query failed."""
    if habit is None:
        return None
    return {
        "history_count": habit.history_count,
        "times_at_merchant_90d": habit.times_at_merchant_90d,
        "usual_amount_range": _usual_range(habit.usual_amount_range),
        "country_seen_before": habit.country_seen_before,
    }


def _usual_range(usual: UsualAmountRange | None) -> dict[str, Any] | None:
    """Present the range rounded to cents: percentile_cont leaves float noise."""
    if usual is None:
        return None
    return {
        "low": _amount(usual.low),
        "high": _amount(usual.high),
        "currency": usual.currency,
    }


def _app_activity(app_activity: AppActivity | None) -> dict[str, Any] | None:
    """Present the closest event; only ``found`` when there was none."""
    if app_activity is None:
        return None
    if not app_activity.found:
        return {"found": False}
    return {
        "found": True,
        "event_date": _iso(app_activity.event_date),
        "minutes_from_charge": app_activity.minutes_from_charge,
        "ip_country": app_activity.ip_country,
        "ip_city": app_activity.ip_city,
        "conflict": app_activity.conflict,
    }


def _iso(value: date | None) -> str | None:
    """Return an ISO 8601 string of a date or timestamp, keeping None."""
    return None if value is None else value.isoformat()


def _amount(value: Decimal | None) -> str | None:
    """Return a 2-decimal string rounded half up, keeping None."""
    if value is None:
        return None
    return str(value.quantize(_CENTS, rounding=ROUND_HALF_UP))
