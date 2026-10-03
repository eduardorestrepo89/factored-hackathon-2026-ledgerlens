"""Present a call classification as the JSON returned to the agent."""

from collections.abc import Mapping
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from classify_call_type_lambda.domain.entities.call_classification import (
    CallClassification,
    RankedReason,
)
from classify_call_type_lambda.domain.entities.candidates import (
    AppEventCandidate,
    CardCandidate,
    CaseCandidate,
    TransactionCandidate,
)
from classify_call_type_lambda.domain.value_objects.call_reasons import CallReason

_CENTS: Final = Decimal("0.01")

# The evidence a transaction reason adds to the common charge keys (spec section 5).
_TRANSACTION_EXTRA_KEYS: Final[Mapping[CallReason, tuple[str, ...]]] = {
    CallReason.DECLINED_TRANSACTION: ("response_code",),
    CallReason.FOREIGN_TRANSACTION: (
        "transaction_country",
        "home_country",
        "card_currency",
    ),
}


def present_call_classification(classification: CallClassification) -> dict[str, Any]:
    """Return the classification as JSON-safe values (spec section 5).

    confidence is a JSON number (a float of the 2-decimal Decimal). Amounts are
    2-decimal strings rounded half up. Timestamps are ISO 8601 without a time
    zone, as stored. Missing values stay None. No key holds a fraud score.
    """
    return {
        "reasons": [
            _reason(ranked, classification.as_of_date)
            for ranked in classification.reasons
        ],
        "unavailable": [reason.value for reason in classification.unavailable],
    }


def _reason(ranked: RankedReason, as_of_date: date) -> dict[str, Any]:
    """Present one ranked reason with its evidence."""
    return {
        "reason": ranked.reason.value,
        "confidence": float(ranked.confidence),
        "ref_id": ranked.ref_id,
        "evidence": _evidence(ranked, as_of_date),
    }


def _evidence(ranked: RankedReason, as_of_date: date) -> dict[str, Any]:
    """Pick the evidence builder for the candidate's type."""
    candidate = ranked.candidate
    if isinstance(candidate, TransactionCandidate):
        return _transaction_evidence(ranked.reason, candidate)
    if isinstance(candidate, CardCandidate):
        return _card_evidence(ranked.reason, candidate, as_of_date)
    if isinstance(candidate, CaseCandidate):
        return _case_evidence(candidate)
    return _app_event_evidence(candidate)


def _transaction_evidence(
    reason: CallReason, charge: TransactionCandidate
) -> dict[str, Any]:
    """The charge keys, plus the extra keys of DECLINED and FOREIGN."""
    values: dict[str, Any] = {
        "transaction_date": _iso(charge.transaction_date),
        "card_last4": charge.card_last4,
        "merchant_name": charge.merchant_name,
        "amount": _amount(charge.amount),
        "currency": charge.currency,
        "transaction_status": charge.transaction_status,
    }
    extras = {
        "response_code": charge.response_code,
        "transaction_country": charge.transaction_country,
        "home_country": charge.home_country,
        "card_currency": charge.card_currency,
    }
    for key in _TRANSACTION_EXTRA_KEYS.get(reason, ()):
        values[key] = extras[key]
    return values


def _card_evidence(
    reason: CallReason, card: CardCandidate, as_of_date: date
) -> dict[str, Any]:
    """The card's last 4 digits and the one fact behind its reason.

    Raises:
        ValueError: The reason isn't a card reason (a ranking bug).
    """
    if reason is CallReason.CARD_NOT_ACTIVE:
        return {"card_last4": card.card_last4, "product_status": card.product_status}
    if reason is CallReason.PAYMENT_OVERDUE:
        return {"card_last4": card.card_last4, "days_past_due": card.days_past_due}
    if reason is CallReason.CARD_EXPIRING:
        return {
            "card_last4": card.card_last4,
            "expiration_date": _iso(card.expiration_date),
            "days_left": (
                None
                if card.expiration_date is None
                else (card.expiration_date - as_of_date).days
            ),
        }
    raise ValueError(f"{reason.value} is not a card reason")


def _case_evidence(case: CaseCandidate) -> dict[str, Any]:
    """The open case, without its complaint_id (that is the ref_id)."""
    return {
        "case_type": case.case_type,
        "category": case.category,
        "subcategory": case.subcategory,
        "status": case.status,
        "sla_breached": case.sla_breached,
        "days_open": case.days_open,
    }


def _app_event_evidence(event: AppEventCandidate) -> dict[str, Any]:
    """The failed app action, without its event_id (that is the ref_id)."""
    return {
        "event_date": _iso(event.event_date),
        "page_title": event.page_title,
        "action": event.action,
    }


def _iso(value: date | None) -> str | None:
    """Return an ISO 8601 string of a date or timestamp, keeping None."""
    return None if value is None else value.isoformat()


def _amount(value: Decimal | None) -> str | None:
    """Return a 2-decimal string rounded half up, keeping None."""
    if value is None:
        return None
    return str(value.quantize(_CENTS, rounding=ROUND_HALF_UP))
