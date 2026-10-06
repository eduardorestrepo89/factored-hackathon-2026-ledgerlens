"""Tests for domain and port error definitions."""

import pytest
import transaction_fraud_detection_lambda.domain.errors as errors_module
from transaction_fraud_detection_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
    QueryNotFoundError,
)
from transaction_fraud_detection_lambda.domain.errors import (
    CardNotFoundError,
    DataSourceUnavailableError,
    DomainError,
    FraudCheckDataIntegrityError,
    FraudCheckLookupError,
    InvalidInputError,
    TransactionNotFoundError,
)

pytestmark = pytest.mark.unit


def test_invalid_input_error_formats_field_and_reason() -> None:
    error = InvalidInputError("card_last4", "must be exactly 4 digits")

    assert error.field == "card_last4"
    assert error.reason == "must be exactly 4 digits"
    assert error.message == (
        "Invalid value for 'card_last4': must be exactly 4 digits. "
        "Ask the customer to confirm and retry."
    )
    assert str(error) == error.message


@pytest.mark.parametrize(
    ("error_type", "expected"),
    [
        (
            TransactionNotFoundError,
            "No credit-card charge with this transaction_id belongs to this "
            "customer. Don't guess; ask the customer to confirm the charge, or "
            "call list_card_transactions to find it.",
        ),
        (
            CardNotFoundError,
            "None of this customer's credit cards ends in these 4 digits. Call "
            "list_credit_cards to see their cards and ask which one they mean.",
        ),
        (
            DataSourceUnavailableError,
            "The fraud check is temporarily unavailable. Offer to retry in a "
            "moment or hand off to a human agent; if the customer reports a "
            "charge they don't recognize, offer the hand-off now.",
        ),
        (
            FraudCheckLookupError,
            "The fraud check can't run right now due to an internal error. "
            "Don't retry; offer a hand-off to a human agent.",
        ),
        (
            FraudCheckDataIntegrityError,
            "The fraud check came back in an unexpected format. Don't retry; "
            "offer a hand-off to a human agent.",
        ),
    ],
)
def test_fixed_domain_errors_carry_agent_facing_messages(
    error_type: type[DomainError], expected: str
) -> None:
    error = error_type()

    assert isinstance(error, DomainError)
    assert error.message == expected
    assert error_type.MESSAGE == expected  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "name",
    ["SessionContextLookupError", "CustomerNotFoundError", "CardLookupError"],
)
def test_other_tools_errors_are_not_defined(name: str) -> None:
    assert not hasattr(errors_module, name)


@pytest.mark.parametrize(
    "error_type",
    [
        DataSourceConnectionError,
        QueryLimitExceededError,
        QueryExecutionError,
        QueryNotFoundError,
    ],
)
def test_port_errors_share_a_base_class(error_type: type[DataAccessError]) -> None:
    assert issubclass(error_type, DataAccessError)
    assert not issubclass(error_type, DomainError)
