"""Tests for the fraud assessment presenter (spec section 5)."""

import dataclasses
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest
from transaction_fraud_detection_lambda.delivery.presenters.fraud_assessment import (
    present_assessment,
    present_sweep,
)
from transaction_fraud_detection_lambda.domain.entities.fraud_assessment import (
    CardSweep,
    FraudAssessment,
)
from transaction_fraud_detection_lambda.domain.value_objects.fraud_bands import (
    FraudVerdict,
    ScoreBasis,
)

from .fakes import TRANSACTION_ID

pytestmark = pytest.mark.unit

FRAUD_STEP = "Confirm with the customer, then block the card and open a fraud claim."
REVIEW_STEP = (
    "Ask whether they recognize the charge; if not, offer to open a case for "
    "clarification and dispute."
)
ASSESSMENT = FraudAssessment(
    transaction_id=TRANSACTION_ID,
    transaction_date=datetime(2026, 5, 31, 6, 9, 15),
    card_last4="4497",
    merchant_name="Estación de Servicio",
    amount=Decimal("288.69"),
    currency="USD",
    transaction_status="Approved",
    verdict=FraudVerdict.FRAUD,
    basis=ScoreBasis.SCORED,
)
PRESENTED = {
    "transaction_id": TRANSACTION_ID,
    "transaction_date": "2026-05-31T06:09:15",
    "card_last4": "4497",
    "merchant_name": "Estación de Servicio",
    "amount": "288.69",
    "currency": "USD",
    "transaction_status": "Approved",
    "verdict": "fraud",
    "basis": "scored",
    "next_step": FRAUD_STEP,
}
SWEEP = CardSweep(
    card_last4="4497",
    date_from=datetime(2026, 5, 18, 23, 59, 59),
    date_to=datetime(2026, 6, 17, 23, 59, 59),
    checked=3,
    flagged=(ASSESSMENT,),
    truncated=False,
)


def test_present_assessment_shape() -> None:
    assert present_assessment(ASSESSMENT) == {
        "mode": "transaction",
        "assessment": PRESENTED,
    }


def test_present_assessment_keeps_the_key_order() -> None:
    assert list(present_assessment(ASSESSMENT)["assessment"]) == list(PRESENTED)


def test_present_sweep_shape() -> None:
    assert present_sweep(SWEEP) == {
        "mode": "card",
        "card_last4": "4497",
        "date_from": "2026-05-18T23:59:59",
        "date_to": "2026-06-17T23:59:59",
        "checked": 3,
        "flagged": [PRESENTED],
        "truncated": False,
    }


def test_an_empty_sweep_has_an_empty_list() -> None:
    sweep = dataclasses.replace(SWEEP, flagged=(), checked=3)

    assert present_sweep(sweep)["flagged"] == []


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("288.685"), "288.69"),
        (Decimal("288.684"), "288.68"),
        (Decimal("10"), "10.00"),
        (Decimal("0.005"), "0.01"),
    ],
)
def test_amounts_are_two_decimal_strings_rounded_half_up(
    amount: Decimal, expected: str
) -> None:
    assessment = dataclasses.replace(ASSESSMENT, amount=amount)

    assert present_assessment(assessment)["assessment"]["amount"] == expected


def test_missing_values_stay_null() -> None:
    assessment = dataclasses.replace(
        ASSESSMENT,
        transaction_date=None,
        card_last4=None,
        merchant_name=None,
        amount=None,
        currency=None,
        transaction_status=None,
    )

    presented = present_assessment(assessment)["assessment"]

    for key in (
        "transaction_date",
        "card_last4",
        "merchant_name",
        "amount",
        "currency",
        "transaction_status",
    ):
        assert presented[key] is None, key


@pytest.mark.parametrize(
    ("verdict", "basis", "next_step"),
    [
        (FraudVerdict.FRAUD, ScoreBasis.SCORED, FRAUD_STEP),
        (FraudVerdict.REVIEW, ScoreBasis.SCORED, REVIEW_STEP),
        (FraudVerdict.NO_FRAUD, ScoreBasis.SCORED, None),
        (FraudVerdict.NO_FRAUD, ScoreBasis.NOT_SCORED, None),
    ],
)
def test_next_step_follows_the_verdict(
    verdict: FraudVerdict, basis: ScoreBasis, next_step: str | None
) -> None:
    assessment = dataclasses.replace(ASSESSMENT, verdict=verdict, basis=basis)

    presented = present_assessment(assessment)["assessment"]

    assert (presented["verdict"], presented["basis"]) == (verdict.value, basis.value)
    assert presented["next_step"] == next_step


def keys(value: Any) -> set[str]:
    """Return every dict key anywhere inside ``value``."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys(v)}
    if isinstance(value, list):
        return {k for item in value for k in keys(item)}
    return set()


@pytest.mark.parametrize(
    "presented", [present_assessment(ASSESSMENT), present_sweep(SWEEP)]
)
def test_no_score_key_anywhere(presented: dict[str, Any]) -> None:
    assert keys(presented).isdisjoint({"fraud_score", "score", "is_fraud"})


@pytest.mark.parametrize(
    "presented", [present_assessment(ASSESSMENT), present_sweep(SWEEP)]
)
def test_output_is_plain_json(presented: dict[str, Any]) -> None:
    assert json.loads(json.dumps(presented, ensure_ascii=False)) == presented
