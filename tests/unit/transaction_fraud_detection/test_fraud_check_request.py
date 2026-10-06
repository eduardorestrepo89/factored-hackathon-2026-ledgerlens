"""Tests for FraudCheckRequest.from_raw: validation before any query."""

import pytest
from transaction_fraud_detection_lambda.domain.errors import InvalidInputError
from transaction_fraud_detection_lambda.domain.value_objects.fraud_check_request import (
    FraudCheckRequest,
)

from .fakes import CUSTOMER_ID, TRANSACTION_ID

pytestmark = pytest.mark.unit

CUSTOMER_REASON = "is required and must be a non-empty string"
TRANSACTION_REASON = "must be a non-empty string"
LAST4_REASON = "must be exactly 4 digits"
BOTH_REASON = "give either transaction_id or card_last4, not both"
NEITHER_REASON = (
    "give either transaction_id (one charge) or card_last4 "
    "(sweep of that card's last 30 days)"
)


def rejected(event: object) -> InvalidInputError:
    """Return the InvalidInputError from_raw raises for ``event``."""
    with pytest.raises(InvalidInputError) as caught:
        FraudCheckRequest.from_raw(event)
    return caught.value


def test_transaction_id_is_stripped_and_uppercased() -> None:
    request = FraudCheckRequest.from_raw(
        {
            "customer_id": " cli-ex6boaoefzhq ",
            "transaction_id": " trx-23bijau4gl46atpw9sty ",
        }
    )

    assert request == FraudCheckRequest(
        customer_id=CUSTOMER_ID, transaction_id=TRANSACTION_ID, card_last4=None
    )


def test_card_last4_is_stripped() -> None:
    request = FraudCheckRequest.from_raw(
        {"customer_id": CUSTOMER_ID, "card_last4": " 4497 "}
    )

    assert request == FraudCheckRequest(
        customer_id=CUSTOMER_ID, transaction_id=None, card_last4="4497"
    )


def test_unknown_keys_are_ignored() -> None:
    request = FraudCheckRequest.from_raw(
        {"customer_id": CUSTOMER_ID, "card_last4": "4497", "fraud_score": 99}
    )

    assert request.card_last4 == "4497"


@pytest.mark.parametrize(
    "event",
    [
        None,
        [],
        "customer_id=CLI-EX6BOAOEFZHQ",
        {},
        {"customer_id": None, "card_last4": "4497"},
        {"customer_id": "", "card_last4": "4497"},
        {"customer_id": "   ", "card_last4": "4497"},
        {"customer_id": 42, "card_last4": "4497"},
        {"customer_id": True, "card_last4": "4497"},
    ],
)
def test_bad_customer_id_is_rejected(event: object) -> None:
    error = rejected(event)

    assert (error.field, error.reason) == ("customer_id", CUSTOMER_REASON)


@pytest.mark.parametrize("value", [42, True, ["TRX-1"]])
def test_non_string_transaction_id_is_rejected(value: object) -> None:
    error = rejected({"customer_id": CUSTOMER_ID, "transaction_id": value})

    assert (error.field, error.reason) == ("transaction_id", TRANSACTION_REASON)


@pytest.mark.parametrize("value", ["449", "44971", "44a7", "٤٤٩٧", "4 97", 4497])
def test_bad_card_last4_is_rejected(value: object) -> None:
    error = rejected({"customer_id": CUSTOMER_ID, "card_last4": value})

    assert (error.field, error.reason) == ("card_last4", LAST4_REASON)


def test_both_given_is_rejected() -> None:
    error = rejected(
        {
            "customer_id": CUSTOMER_ID,
            "transaction_id": TRANSACTION_ID,
            "card_last4": "4497",
        }
    )

    assert (error.field, error.reason) == ("transaction_id", BOTH_REASON)


@pytest.mark.parametrize(
    "event",
    [
        {"customer_id": CUSTOMER_ID},
        {"customer_id": CUSTOMER_ID, "transaction_id": None, "card_last4": None},
        {"customer_id": CUSTOMER_ID, "transaction_id": "  ", "card_last4": ""},
    ],
)
def test_neither_given_is_rejected(event: object) -> None:
    error = rejected(event)

    assert (error.field, error.reason) == ("transaction_id", NEITHER_REASON)


def test_a_blank_field_counts_as_missing_next_to_the_other() -> None:
    request = FraudCheckRequest.from_raw(
        {"customer_id": CUSTOMER_ID, "transaction_id": " ", "card_last4": "4497"}
    )

    assert request.transaction_id is None
    assert request.card_last4 == "4497"
