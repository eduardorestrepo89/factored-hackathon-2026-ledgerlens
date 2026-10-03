"""Tests for domain and port error definitions."""

import get_session_context_lambda.domain.errors as errors_module
import pytest
from get_session_context_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
    QueryNotFoundError,
)
from get_session_context_lambda.domain.errors import (
    CustomerNotFoundError,
    DataSourceUnavailableError,
    DomainError,
    InvalidInputError,
    SessionContextDataIntegrityError,
    SessionContextLookupError,
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
            "Customer data is temporarily unavailable. Greet the customer, ask how "
            "you can help, and offer to retry in a moment or hand off to a human "
            "agent.",
        ),
        (
            SessionContextLookupError,
            "The customer's context can't be retrieved right now due to an "
            "internal error. Don't retry; ask the customer how you can help and "
            "offer a hand-off to a human agent if needed.",
        ),
        (
            CustomerNotFoundError,
            "No customer record matches this customer_id. Don't guess or retry; "
            "offer a hand-off to a human agent.",
        ),
        (
            SessionContextDataIntegrityError,
            "Customer data came back in an unexpected format. Don't retry; offer "
            "a hand-off to a human agent.",
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


@pytest.mark.parametrize("name", ["CardLookupError", "CardDataIntegrityError"])
def test_card_worded_errors_are_not_defined(name: str) -> None:
    # This tool's failures are about the whole context (spec section 6.2).
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
