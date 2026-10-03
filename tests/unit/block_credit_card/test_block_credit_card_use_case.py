"""Tests for BlockCreditCardUseCase."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from block_credit_card_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    DuplicateKeyError,
    QueryExecutionError,
    QueryLimitExceededError,
    WriteConflictError,
)
from block_credit_card_lambda.application.use_cases.block_credit_card import (
    BlockCreditCardUseCase,
)
from block_credit_card_lambda.domain.entities.card_block import CardBlock
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

from .fakes import (
    CUSTOMER_ID,
    FakeDatabaseRepository,
    FakeQueryProvider,
    Outcomes,
    make_row,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
NAIVE_NOW = datetime(2026, 6, 17, 23, 59, 59)
FIND = "find_credit_card"
BLOCK = "block_credit_card"
BLOCKED_ROW = [{"product_id": "PRD-1"}]
ARGS: dict[str, Any] = {
    "customer_id": CUSTOMER_ID,
    "card_last4": "4821",
    "reason": "suspected_fraud",
    "customer_confirmed": True,
}


def make_use_case(
    results: dict[str, Outcomes] | None = None,
    query_provider: FakeQueryProvider | None = None,
) -> tuple[BlockCreditCardUseCase, FakeDatabaseRepository]:
    """Build the use case over fakes; return it with its repository."""
    repository = FakeDatabaseRepository(results)
    use_case = BlockCreditCardUseCase(
        database_repository=repository,
        query_provider=query_provider or FakeQueryProvider(),
    )
    return use_case, repository


def block(use_case: BlockCreditCardUseCase, **overrides: Any) -> CardBlock:
    """Run the use case with ARGS, overridden by ``overrides``."""
    return use_case.execute(**{**ARGS, **overrides, "now": overrides.get("now", NOW)})


def test_an_active_card_is_blocked() -> None:
    use_case, repository = make_use_case({FIND: [make_row()], BLOCK: BLOCKED_ROW})

    assert block(use_case) == CardBlock(
        card_last4="4821", status="Blocked", already_blocked=False
    )
    assert repository.calls == [
        (FIND, {"customer_id": CUSTOMER_ID, "card_last4": "4821"}),
        (
            BLOCK,
            {
                "customer_id": CUSTOMER_ID,
                "product_id": "PRD-1",
                "last_updated": NAIVE_NOW,
            },
        ),
    ]


def test_a_suspended_card_is_blocked_too() -> None:
    use_case, _ = make_use_case(
        {FIND: [make_row(product_status="Suspended")], BLOCK: BLOCKED_ROW}
    )

    assert block(use_case).already_blocked is False


def test_an_already_blocked_card_is_a_success_without_a_write() -> None:
    use_case, repository = make_use_case({FIND: [make_row(product_status="Blocked")]})

    assert block(use_case) == CardBlock(
        card_last4="4821", status="Blocked", already_blocked=True
    )
    assert [name for name, _ in repository.calls] == [FIND]


def test_a_closed_card_is_refused_without_a_write() -> None:
    use_case, repository = make_use_case({FIND: [make_row(product_status="Closed")]})

    with pytest.raises(CardClosedError) as caught:
        block(use_case)

    assert caught.value.card_last4 == "4821"
    assert [name for name, _ in repository.calls] == [FIND]


def test_no_matching_card_raises_card_not_found() -> None:
    use_case, _ = make_use_case({FIND: []})

    with pytest.raises(CardNotFoundError) as caught:
        block(use_case)

    assert "No credit card ending in 4821" in caught.value.message


def test_two_matching_cards_raise_ambiguous_card() -> None:
    use_case, repository = make_use_case(
        {FIND: [make_row(), make_row(product_id="PRD-2")]}
    )

    with pytest.raises(AmbiguousCardError):
        block(use_case)

    assert [name for name, _ in repository.calls] == [FIND]


def test_an_update_that_changes_nothing_rereads_the_card() -> None:
    # A retry after a lost reply, or a block that landed between the statements.
    use_case, repository = make_use_case(
        {FIND: ([make_row()], [make_row(product_status="Blocked")]), BLOCK: []}
    )

    assert block(use_case).already_blocked is True
    assert [name for name, _ in repository.calls] == [FIND, BLOCK, FIND]


def test_a_card_closed_between_the_statements_raises_card_closed() -> None:
    use_case, _ = make_use_case(
        {FIND: ([make_row()], [make_row(product_status="Closed")]), BLOCK: []}
    )

    with pytest.raises(CardClosedError):
        block(use_case)


def test_an_update_that_changes_nothing_on_a_still_active_card_fails() -> None:
    use_case, _ = make_use_case({FIND: [make_row()], BLOCK: []})

    with pytest.raises(CardUpdateError):
        block(use_case)


def test_now_is_written_as_naive_utc() -> None:
    use_case, repository = make_use_case({FIND: [make_row()], BLOCK: BLOCKED_ROW})
    bogota = timezone(timedelta(hours=-5))

    block(use_case, now=datetime(2026, 6, 17, 18, 59, 59, tzinfo=bogota))

    assert repository.params_of(BLOCK)[0]["last_updated"] == NAIVE_NOW


def test_the_inputs_are_cleaned_before_the_query() -> None:
    use_case, repository = make_use_case({FIND: [make_row()], BLOCK: BLOCKED_ROW})

    block(
        use_case, customer_id=" cli-itiecue8prh9 ", card_last4=" 4821 ", reason=" Lost "
    )

    assert repository.params_of(FIND) == [
        {"customer_id": CUSTOMER_ID, "card_last4": "4821"}
    ]


def assert_rejected(field: str, **overrides: Any) -> InvalidInputError:
    """Run with ``overrides``; it must fail on ``field`` before any query."""
    use_case, repository = make_use_case({FIND: [make_row()], BLOCK: BLOCKED_ROW})
    with pytest.raises(InvalidInputError) as caught:
        block(use_case, **overrides)
    assert caught.value.field == field
    assert repository.calls == []
    return caught.value


@pytest.mark.parametrize("customer_id", [None, "", "   ", 42, True])
def test_a_bad_customer_id_is_rejected(customer_id: object) -> None:
    error = assert_rejected("customer_id", customer_id=customer_id)

    assert error.reason == "is required and must be a non-empty string"


@pytest.mark.parametrize(
    "card_last4",
    [
        None,
        4821,
        "",
        "482",
        "48210",
        "04821",
        "48 21",
        "\uff14\uff18\uff12\uff11",
        "abcd",
    ],
)
def test_card_last4_must_be_exactly_4_ascii_digits(card_last4: object) -> None:
    error = assert_rejected("card_last4", card_last4=card_last4)

    assert error.reason == "must be exactly 4 digits"


@pytest.mark.parametrize("reason", [None, "", "fraud", "theft", 1])
def test_reason_must_be_one_of_the_four(reason: object) -> None:
    error = assert_rejected("reason", reason=reason)

    assert error.reason == (
        "must be one of: customer_request, lost, stolen, suspected_fraud"
    )


@pytest.mark.parametrize("confirmed", [False, None, "true", "yes", 1])
def test_only_the_boolean_true_confirms_the_block(confirmed: object) -> None:
    error = assert_rejected("customer_confirmed", customer_confirmed=confirmed)

    assert error.message == (
        "Invalid value for 'customer_confirmed': must be true, after the customer "
        "explicitly confirmed the block. Ask the customer to confirm and retry."
    )


@pytest.mark.parametrize(
    ("port_error", "domain_error"),
    [
        (DataSourceConnectionError("down"), DataSourceUnavailableError),
        (WriteConflictError("40001"), DataSourceUnavailableError),
        (QueryExecutionError("boom"), CardUpdateError),
        (QueryLimitExceededError("limit"), CardUpdateError),
        (DuplicateKeyError("23505"), CardUpdateError),
    ],
)
@pytest.mark.parametrize("failing_query", [FIND, BLOCK])
def test_port_errors_become_domain_errors(
    port_error: DataAccessError,
    domain_error: type[DomainError],
    failing_query: str,
) -> None:
    results: dict[str, Outcomes] = {FIND: [make_row()], BLOCK: BLOCKED_ROW}
    results[failing_query] = port_error
    use_case, _ = make_use_case(results)

    with pytest.raises(domain_error) as caught:
        block(use_case)

    assert caught.value.__cause__ is port_error


def test_a_missing_sql_file_raises_card_update_error() -> None:
    use_case, _ = make_use_case(query_provider=FakeQueryProvider(names=()))

    with pytest.raises(CardUpdateError):
        block(use_case)


@pytest.mark.parametrize(
    "row",
    [
        {"product_status": "Active"},
        make_row(product_id=None),
        make_row(product_id=""),
        make_row(product_status=5),
    ],
)
def test_an_unreadable_card_row_raises_card_data_integrity_error(
    row: dict[str, Any],
) -> None:
    use_case, _ = make_use_case({FIND: [row]})

    with pytest.raises(CardDataIntegrityError):
        block(use_case)


def test_every_block_writes_an_audit_line(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    use_case, _ = make_use_case({FIND: [make_row()], BLOCK: BLOCKED_ROW})

    block(use_case)

    assert (
        f"block_credit_card audit: customer_id={CUSTOMER_ID} card_last4=4821 "
        "reason=suspected_fraud already_blocked=False"
    ) in caplog.text
