"""Tests for the credit cards presenter: the JSON the agent reads."""

import json
from datetime import date
from decimal import Decimal

import pytest
from list_credit_cards_lambda.delivery.presenters.credit_cards import (
    present_credit_cards,
)
from list_credit_cards_lambda.domain.entities.credit_card import (
    CreditCard,
    CreditCardsResult,
)

pytestmark = pytest.mark.unit

AMOUNT_FIELDS = ("current_balance", "credit_limit", "available_credit")


def make_card(**overrides: object) -> CreditCard:
    """Build a CreditCard for presenter tests."""
    values: dict[str, object] = {
        "card_last4": "4821",
        "product_status": "Active",
        "currency": "COP",
        "current_balance": Decimal("1250000"),
        "credit_limit": Decimal("3000000.00"),
        "available_credit": Decimal("1750000.00"),
        "expiration_date": date(2027, 3, 31),
        "days_past_due": 0,
    }
    values.update(overrides)
    return CreditCard(**values)  # type: ignore[arg-type]


def test_presenter_shapes_the_agent_json() -> None:
    result = CreditCardsResult(cards=(make_card(),), truncated=True)

    assert present_credit_cards(result) == {
        "cards": [
            {
                "card_last4": "4821",
                "product_status": "Active",
                "currency": "COP",
                "current_balance": "1250000.00",
                "credit_limit": "3000000.00",
                "available_credit": "1750000.00",
                "expiration_date": "2027-03-31",
                "days_past_due": 0,
            }
        ],
        "count": 1,
        "truncated": True,
    }


@pytest.mark.parametrize("field", AMOUNT_FIELDS)
@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("7"), "7.00"),
        (Decimal("10.005"), "10.01"),
        (Decimal("0.004"), "0.00"),
        (Decimal("-50.255"), "-50.26"),
    ],
)
def test_presenter_formats_amounts_as_two_decimal_strings(
    field: str, amount: Decimal, expected: str
) -> None:
    result = CreditCardsResult((make_card(**{field: amount}),), False)

    assert present_credit_cards(result)["cards"][0][field] == expected


def test_presenter_keeps_nulls_and_output_is_json_serialisable() -> None:
    card = CreditCard(None, None, None, None, None, None, None, None)

    body = present_credit_cards(CreditCardsResult((card,), False))

    assert set(body["cards"][0].values()) == {None}
    json.dumps(body)


def test_days_past_due_stays_an_integer() -> None:
    body = present_credit_cards(
        CreditCardsResult((make_card(days_past_due=45),), False)
    )

    assert body["cards"][0]["days_past_due"] == 45


def test_presenter_returns_null_cards_when_the_customer_has_none() -> None:
    assert present_credit_cards(CreditCardsResult((), False)) == {
        "cards": None,
        "count": 0,
        "truncated": False,
    }
