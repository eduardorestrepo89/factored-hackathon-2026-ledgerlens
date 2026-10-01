"""Tests for domain and port error definitions."""

import pytest
from list_card_transactions_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
    QueryNotFoundError,
)
from list_card_transactions_lambda.domain.errors import (
    DataIntegrityError,
    DataSourceUnavailableError,
    DomainError,
    InvalidInputError,
    SearchTooBroadError,
    TransactionLookupError,
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
            "Transaction data is temporarily unavailable. Tell the customer and "
            "offer to retry in a moment or hand off to a human agent.",
        ),
        (
            SearchTooBroadError,
            "The transaction search was too broad for the database. Retry with a "
            "narrower date range or add a card or merchant filter.",
        ),
        (
            TransactionLookupError,
            "Transactions can't be retrieved right now due to an internal error. "
            "Don't retry; offer a hand-off to a human agent.",
        ),
        (
            DataIntegrityError,
            "Transaction data came back in an unexpected format. Don't retry; "
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
