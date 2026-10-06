"""Tests for domain and port error definitions."""

import pytest
from block_credit_card_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    DuplicateKeyError,
    QueryExecutionError,
    QueryLimitExceededError,
    QueryNotFoundError,
    WriteConflictError,
)
from block_credit_card_lambda.domain.errors import (
    AmbiguousCardError,
    CardClosedError,
    CardDataIntegrityError,
    CardNotFoundError,
    CardUpdateError,
    DataSourceUnavailableError,
    DomainError,
    InvalidInputError,
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
            DataSourceUnavailableError,
            "The card service is temporarily unavailable. Tell the customer and "
            "offer to retry in a moment or hand off to a human agent.",
        ),
        (
            CardUpdateError,
            "The card couldn't be blocked due to an internal error. Don't retry; "
            "offer an urgent hand-off to a human agent.",
        ),
        (
            CardDataIntegrityError,
            "Card data came back in an unexpected format. Don't retry; offer an "
            "urgent hand-off to a human agent.",
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
    ("error_type", "expected"),
    [
        (
            CardNotFoundError,
            "No credit card ending in 4821 was found for this customer. Check the "
            "card with list_credit_cards and confirm it with the customer.",
        ),
        (
            AmbiguousCardError,
            "More than one of the customer's credit cards ends in 4821, so it "
            "can't be blocked here. Don't retry; offer an urgent hand-off to a "
            "human agent.",
        ),
        (
            CardClosedError,
            "The card ending in 4821 is closed, so it can't be charged and needs "
            "no block. Tell the customer.",
        ),
    ],
)
def test_card_errors_name_the_cards_last_4_digits(
    error_type: type[DomainError], expected: str
) -> None:
    error = error_type("4821")  # type: ignore[call-arg]

    assert isinstance(error, DomainError)
    assert error.card_last4 == "4821"  # type: ignore[attr-defined]
    assert error.message == expected


@pytest.mark.parametrize(
    "error_type",
    [
        DataSourceConnectionError,
        QueryLimitExceededError,
        QueryExecutionError,
        QueryNotFoundError,
        DuplicateKeyError,
        WriteConflictError,
    ],
)
def test_port_errors_share_a_base_class(error_type: type[DataAccessError]) -> None:
    assert issubclass(error_type, DataAccessError)
    assert not issubclass(error_type, DomainError)
