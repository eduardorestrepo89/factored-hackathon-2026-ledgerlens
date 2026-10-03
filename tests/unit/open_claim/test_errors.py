"""Tests for domain and port error definitions."""

import pytest
from open_claim_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    DuplicateKeyError,
    QueryExecutionError,
    QueryLimitExceededError,
    QueryNotFoundError,
    WriteConflictError,
)
from open_claim_lambda.domain.errors import (
    ClaimDataIntegrityError,
    ClaimError,
    DataSourceUnavailableError,
    DomainError,
    InvalidInputError,
    TransactionsNotFoundError,
)

pytestmark = pytest.mark.unit


def test_invalid_input_error_formats_field_and_reason() -> None:
    error = InvalidInputError("claim_type", "must be fraud or dispute")

    assert error.message == (
        "Invalid value for 'claim_type': must be fraud or dispute. "
        "Ask the customer to confirm and retry."
    )


def test_transactions_not_found_names_the_missing_ids() -> None:
    error = TransactionsNotFoundError(["TRX-9", "TRX-10"])

    assert isinstance(error, DomainError)
    assert error.transaction_ids == ("TRX-9", "TRX-10")
    assert error.message == (
        "These transactions weren't found among the customer's credit card "
        "transactions: TRX-9, TRX-10. Check them with list_card_transactions "
        "and retry."
    )


@pytest.mark.parametrize(
    ("error_type", "expected"),
    [
        (
            DataSourceUnavailableError,
            "The claim service is temporarily unavailable. Tell the customer and "
            "offer to retry in a moment or hand off to a human agent.",
        ),
        (
            ClaimError,
            "The claim couldn't be opened due to an internal error. Don't retry; "
            "offer a hand-off to a human agent.",
        ),
        (
            ClaimDataIntegrityError,
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
        DuplicateKeyError,
        WriteConflictError,
    ],
)
def test_port_errors_share_a_base_class(error_type: type[DataAccessError]) -> None:
    assert issubclass(error_type, DataAccessError)
    assert not issubclass(error_type, DomainError)
