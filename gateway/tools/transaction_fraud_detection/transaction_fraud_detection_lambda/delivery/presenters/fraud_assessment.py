"""Present a fraud assessment or a card sweep as the JSON returned to the agent."""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from transaction_fraud_detection_lambda.domain.entities.fraud_assessment import (
    CardSweep,
    FraudAssessment,
)
from transaction_fraud_detection_lambda.domain.value_objects.fraud_bands import (
    NEXT_STEPS,
)

_CENTS: Final = Decimal("0.01")


def present_assessment(assessment: FraudAssessment) -> dict[str, Any]:
    """Return one charge's assessment as JSON-safe values (spec section 5).

    Amounts are 2-decimal strings rounded half up; timestamps are ISO 8601
    without a time zone, as stored. Missing values stay None. There is no score.
    """
    return {"mode": "transaction", "assessment": _assessment(assessment)}


def present_sweep(sweep: CardSweep) -> dict[str, Any]:
    """Return a card sweep as JSON-safe values: flagged charges plus the count."""
    return {
        "mode": "card",
        "card_last4": sweep.card_last4,
        "date_from": _iso(sweep.date_from),
        "date_to": _iso(sweep.date_to),
        "checked": sweep.checked,
        "flagged": [_assessment(item) for item in sweep.flagged],
        "truncated": sweep.truncated,
    }


def _assessment(assessment: FraudAssessment) -> dict[str, Any]:
    """Present one assessment with the next step its verdict calls for."""
    return {
        "transaction_id": assessment.transaction_id,
        "transaction_date": _iso(assessment.transaction_date),
        "card_last4": assessment.card_last4,
        "merchant_name": assessment.merchant_name,
        "amount": _amount(assessment.amount),
        "currency": assessment.currency,
        "transaction_status": assessment.transaction_status,
        "verdict": assessment.verdict.value,
        "basis": assessment.basis.value,
        "next_step": NEXT_STEPS[assessment.verdict],
    }


def _iso(value: datetime | None) -> str | None:
    """Return an ISO 8601 string, keeping None."""
    return None if value is None else value.isoformat()


def _amount(value: Decimal | None) -> str | None:
    """Return a 2-decimal string rounded half up, keeping None."""
    if value is None:
        return None
    return str(value.quantize(_CENTS, rounding=ROUND_HALF_UP))
