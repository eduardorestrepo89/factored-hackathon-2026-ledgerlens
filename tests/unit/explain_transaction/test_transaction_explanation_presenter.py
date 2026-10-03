"""Tests for the transaction explanation presenter (spec section 5)."""

import dataclasses
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest
from explain_transaction_lambda.delivery.presenters.transaction_explanation import (
    present_transaction_explanation,
)
from explain_transaction_lambda.domain.entities.transaction_explanation import (
    AppActivity,
    DeclineInfo,
    ExplainedTransaction,
    FxConversion,
    Section,
    SpendingHabit,
    TransactionExplanation,
    UsualAmountRange,
)

from .fakes import CHARGE_DATE, TRANSACTION_ID

pytestmark = pytest.mark.unit

# Spec section 5, verbatim: P07's charge as the agent sees it.
P07_JSON = """
{
  "transaction": {
    "transaction_id": "TRX-23BIJAU4GL46ATPW9STY",
    "transaction_date": "2026-05-31T06:09:15",
    "card_last4": "4497",
    "merchant_name": "Estación de Servicio",
    "merchant_category": "Transport",
    "amount": "288.69",
    "currency": "USD",
    "channel": "Web",
    "transaction_city": "Ciudad de México",
    "transaction_country": "México",
    "transaction_status": "Approved"
  },
  "fx": null,
  "decline": null,
  "habit": {
    "history_count": 1,
    "times_at_merchant_90d": 0,
    "usual_amount_range": null,
    "country_seen_before": true
  },
  "app_activity": { "found": false },
  "unavailable": []
}
"""

P07 = TransactionExplanation(
    transaction=ExplainedTransaction(
        transaction_id=TRANSACTION_ID,
        transaction_date=CHARGE_DATE,
        card_last4="4497",
        merchant_name="Estación de Servicio",
        merchant_category="Transport",
        amount=Decimal("288.69"),
        currency="USD",
        channel="Web",
        transaction_city="Ciudad de México",
        transaction_country="México",
        transaction_status="Approved",
    ),
    fx=None,
    decline=None,
    habit=SpendingHabit(
        history_count=1,
        times_at_merchant_90d=0,
        usual_amount_range=None,
        country_seen_before=True,
    ),
    app_activity=AppActivity(found=False),
    unavailable=(),
)

FOUND = AppActivity(
    found=True,
    event_date=datetime(2026, 5, 31, 5, 39, 15),
    minutes_from_charge=-30,
    ip_country="Colombia",
    ip_city="Bogotá",
    conflict=True,
)


def present(**changes: Any) -> dict[str, Any]:
    """Present P07's explanation with some fields replaced."""
    return present_transaction_explanation(dataclasses.replace(P07, **changes))


def habit_with_range(low: Decimal, high: Decimal) -> SpendingHabit:
    """Return P07's habit with a usual range in USD."""
    return dataclasses.replace(
        P07.habit,  # type: ignore[arg-type]
        usual_amount_range=UsualAmountRange(low=low, high=high, currency="USD"),
    )


def keys(value: object) -> set[str]:
    """Return every dict key at any depth."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys(v)}
    return set()


def test_p07_matches_the_spec_example() -> None:
    assert present_transaction_explanation(P07) == json.loads(P07_JSON)


def test_output_survives_a_json_round_trip() -> None:
    body = present(
        fx=FxConversion("USD", date(2026, 5, 31), Decimal("0.00025"), Decimal("100")),
        decline=DeclineInfo("54", "expired card", True),
        habit=habit_with_range(Decimal("10"), Decimal("90")),
        app_activity=FOUND,
    )

    assert json.loads(json.dumps(body, ensure_ascii=False)) == body


def test_amounts_are_two_decimal_strings() -> None:
    transaction = dataclasses.replace(P07.transaction, amount=Decimal("288.685"))

    assert present(transaction=transaction)["transaction"]["amount"] == "288.69"


def test_missing_transaction_values_stay_null() -> None:
    transaction = dataclasses.replace(
        P07.transaction, transaction_date=None, amount=None, channel=None
    )

    presented = present(transaction=transaction)["transaction"]

    assert presented["transaction_date"] is None
    assert presented["amount"] is None
    assert presented["channel"] is None


def test_fx_is_presented() -> None:
    fx = FxConversion("USD", date(2026, 5, 31), Decimal("0.00025"), Decimal("100.00"))

    assert present(fx=fx)["fx"] == {
        "card_currency": "USD",
        "rate_date": "2026-05-31",
        "rate": "0.00025",
        "amount_in_card_currency": "100.00",
    }


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        (Decimal("0.00025"), "0.00025"),
        (Decimal("0.0002500"), "0.0002500"),
        (Decimal("1E+1"), "10"),
        (Decimal("1E-7"), "0.0000001"),
        (Decimal("4150.75"), "4150.75"),
    ],
)
def test_rate_keeps_its_decimals_in_plain_notation(
    rate: Decimal, expected: str
) -> None:
    fx = FxConversion("USD", date(2026, 5, 31), rate, Decimal("1"))

    assert present(fx=fx)["fx"]["rate"] == expected


def test_fx_without_a_rate_keeps_nulls() -> None:
    fx = FxConversion("USD", None, None, None)

    assert present(fx=fx)["fx"] == {
        "card_currency": "USD",
        "rate_date": None,
        "rate": None,
        "amount_in_card_currency": None,
    }


def test_decline_is_presented() -> None:
    decline = DeclineInfo("14", "invalid card number", False)

    assert present(decline=decline)["decline"] == {
        "response_code": "14",
        "meaning": "invalid card number",
        "contradicts_card_state": False,
    }


def test_decline_with_unknown_values_keeps_nulls() -> None:
    decline = DeclineInfo(None, None, None)

    assert present(decline=decline)["decline"] == {
        "response_code": None,
        "meaning": None,
        "contradicts_card_state": None,
    }


@pytest.mark.parametrize(
    ("low", "high", "expected_low", "expected_high"),
    [
        (Decimal("123.4500000000001"), Decimal("310.2499999999"), "123.45", "310.25"),
        (Decimal("20.5"), Decimal("99.995"), "20.50", "100.00"),
        (Decimal("10"), Decimal("90"), "10.00", "90.00"),
    ],
)
def test_usual_range_is_quantized(
    low: Decimal, high: Decimal, expected_low: str, expected_high: str
) -> None:
    habit = present(habit=habit_with_range(low, high))["habit"]

    assert habit["usual_amount_range"] == {
        "low": expected_low,
        "high": expected_high,
        "currency": "USD",
    }


def test_habit_keeps_its_nulls() -> None:
    habit = SpendingHabit(
        history_count=0,
        times_at_merchant_90d=None,
        usual_amount_range=None,
        country_seen_before=None,
    )

    assert present(habit=habit)["habit"] == {
        "history_count": 0,
        "times_at_merchant_90d": None,
        "usual_amount_range": None,
        "country_seen_before": None,
    }


def test_found_app_activity_is_presented() -> None:
    assert present(app_activity=FOUND)["app_activity"] == {
        "found": True,
        "event_date": "2026-05-31T05:39:15",
        "minutes_from_charge": -30,
        "ip_country": "Colombia",
        "ip_city": "Bogotá",
        "conflict": True,
    }


def test_app_activity_not_found_is_only_found_false() -> None:
    assert present(app_activity=AppActivity(found=False))["app_activity"] == {
        "found": False
    }


def test_failed_sections_are_null_and_named() -> None:
    body = present(
        habit=None,
        app_activity=None,
        unavailable=(Section.HABIT, Section.APP_ACTIVITY),
    )

    assert body["habit"] is None
    assert body["app_activity"] is None
    assert body["unavailable"] == ["habit", "app_activity"]


def test_no_key_mentions_fraud_or_score() -> None:
    body = present(
        fx=FxConversion("USD", date(2026, 5, 31), Decimal("0.00025"), Decimal("100")),
        decline=DeclineInfo("54", "expired card", True),
        habit=habit_with_range(Decimal("10"), Decimal("90")),
        app_activity=FOUND,
    )

    all_keys = keys(body)
    assert "found" in all_keys  # the walk reached the nested sections
    assert not [key for key in all_keys if "fraud" in key or "score" in key]
