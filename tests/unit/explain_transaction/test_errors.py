"""Tests for domain and port error definitions."""

import explain_transaction_lambda.domain.errors as errors_module
import pytest
from explain_transaction_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
    QueryNotFoundError,
)
from explain_transaction_lambda.domain.errors import (
    DataSourceUnavailableError,
    DomainError,
    ExplainDataIntegrityError,
    ExplainLookupError,
    InvalidInputError,
    TransactionNotFoundError,
)

pytestmark = pytest.mark.unit


def test_invalid_input_error_formats_field_and_reason() -> None:
    error = InvalidInputError(
        "transaction_id", "is required and must be a non-empty string"
    )

    assert error.field == "transaction_id"
    assert error.reason == "is required and must be a non-empty string"
    assert error.message == (
        "Invalid value for 'transaction_id': is required and must be a non-empty "
        "string. Ask the customer to confirm and retry."
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
            DataSourceUnavailableError,
            "Transaction details are temporarily unavailable. Offer to retry in a "
            "moment or hand off to a human agent.",
        ),
        (
            ExplainLookupError,
            "The charge can't be explained right now due to an internal error. "
            "Don't retry; offer a hand-off to a human agent.",
        ),
        (
            ExplainDataIntegrityError,
            "The charge's data came back in an unexpected format. Don't retry; "
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
    ["CardNotFoundError", "FraudCheckLookupError", "SessionContextLookupError"],
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
