"""Tests for the decline-code meanings and the in-person channels."""

import pytest
from explain_transaction_lambda.domain.value_objects.decline_codes import (
    DECLINE_MEANINGS,
    EXPIRED_CARD_CODE,
    IN_PERSON_CHANNELS,
)

pytestmark = pytest.mark.unit


def test_decline_meanings_are_the_four_codes_in_the_data() -> None:
    assert DECLINE_MEANINGS == {
        "05": "declined by the issuer, no specific reason",
        "14": "invalid card number",
        "51": "insufficient available credit",
        "54": "expired card",
    }


def test_expired_card_code_is_54_and_has_a_meaning() -> None:
    assert EXPIRED_CARD_CODE == "54"
    assert DECLINE_MEANINGS[EXPIRED_CARD_CODE] == "expired card"


def test_only_atm_pos_and_branch_are_in_person() -> None:
    assert IN_PERSON_CHANNELS == frozenset({"ATM", "POS", "Branch"})
    assert "App" not in IN_PERSON_CHANNELS
    assert "Web" not in IN_PERSON_CHANNELS
