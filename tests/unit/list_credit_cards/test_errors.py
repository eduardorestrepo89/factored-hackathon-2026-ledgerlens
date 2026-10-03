"""Tests for domain and port error definitions."""

import list_credit_cards_lambda.domain.errors as errors_module
import pytest
from list_credit_cards_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
    QueryNotFoundError,
)
from list_credit_cards_lambda.domain.errors import (
    CardDataIntegrityError,
    CardLookupError,
    DataSourceUnavailableError,
    DomainError,
    InvalidInputError,
)

pytestmark = pytest.mark.unit


def test_invalid_input_error_formats_field_and_reason() -> None:
    error = InvalidInputError(
        "customer_id", "is required and must be a non-empty string"
    )

    assert error.field == "customer_id"
    assert error.reason == "is required and must be a non-empty string"
    assert error.message == (
        "Invalid value for 'customer_id': is required and must be a non-empty "
        "string. Ask the customer to confirm and retry."
    )
    assert str(error) == error.message


@pytest.mark.parametrize(
    ("error_type", "expected"),
    [
        (
            DataSourceUnavailableError,
            "Card data is temporarily unavailable. Tell the customer and offer "
            "to retry in a moment or hand off to a human agent.",
        ),
        (
            CardLookupError,
            "The customer's cards can't be retrieved right now due to an internal "
            "error. Don't retry; offer a hand-off to a human agent.",
        ),
        (
            CardDataIntegrityError,
            "Card data came back in an unexpected format. Don't retry; offer a "
            "hand-off to a human agent.",
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
    "name", ["SearchTooBroadError", "TransactionLookupError", "DataIntegrityError"]
)
def test_transaction_worded_errors_are_not_defined(name: str) -> None:
    # The query has no filter the agent could narrow (spec section 4.2).
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
