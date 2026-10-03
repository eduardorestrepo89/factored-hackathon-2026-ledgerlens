"""Tests for domain and port error definitions."""

import classify_call_type_lambda.domain.errors as errors_module
import pytest
from classify_call_type_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
    QueryNotFoundError,
)
from classify_call_type_lambda.domain.errors import (
    CallReasonLookupError,
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
            "Call reasons are temporarily unavailable. Greet the customer and ask "
            "how you can help.",
        ),
        (
            CallReasonLookupError,
            "Call reasons can't be computed right now due to an internal error. "
            "Don't retry; greet the customer and ask how you can help.",
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
    [
        "ExplainLookupError",
        "TransactionNotFoundError",
        "FraudCheckLookupError",
        "SessionContextLookupError",
        "CardNotFoundError",
    ],
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
