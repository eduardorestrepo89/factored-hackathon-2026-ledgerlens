"""Tests for ListCreditCardsUseCase: customer_id cleaning, params, mapping, errors."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from list_credit_cards_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
)
from list_credit_cards_lambda.application.use_cases.list_credit_cards import (
    ListCreditCardsUseCase,
)
from list_credit_cards_lambda.domain.entities.credit_card import (
    CreditCard,
    CreditCardsResult,
)
from list_credit_cards_lambda.domain.errors import (
    CardDataIntegrityError,
    CardLookupError,
    DataSourceUnavailableError,
    DomainError,
    InvalidInputError,
)

from .fakes import CUSTOMER_ID, FakeDatabaseRepository, FakeQueryProvider, make_row

pytestmark = pytest.mark.unit

INVALID_CUSTOMER_ID = (
    "Invalid value for 'customer_id': is required and must be a non-empty "
    "string. Ask the customer to confirm and retry."
)


def run(
    rows: list[dict[str, Any]] | None = None,
    error: Exception | None = None,
    max_rows: int = 25,
    customer_id: object = CUSTOMER_ID,
) -> tuple[CreditCardsResult, FakeDatabaseRepository, FakeQueryProvider]:
    """Execute the use case against fakes and return the result and the fakes."""
    database_repository = FakeDatabaseRepository(rows=rows, error=error)
    query_provider = FakeQueryProvider()
    use_case = ListCreditCardsUseCase(
        database_repository=database_repository,
        query_provider=query_provider,
        max_rows=max_rows,
    )
    return use_case.execute(customer_id), database_repository, query_provider


def test_maps_a_row_to_a_credit_card() -> None:
    result, _, _ = run(rows=[make_row()])

    assert result == CreditCardsResult(
        cards=(
            CreditCard(
                card_last4="4821",
                product_status="Active",
                currency="COP",
                current_balance=Decimal("1250000.00"),
                credit_limit=Decimal("3000000.00"),
                available_credit=Decimal("1750000.00"),
                expiration_date=date(2027, 3, 31),
                days_past_due=0,
            ),
        ),
        truncated=False,
    )


def test_loads_the_named_query_and_passes_its_text_to_the_database_repository() -> None:
    _, database_repository, query_provider = run()

    assert query_provider.requested == ["list_credit_cards"]
    assert database_repository.calls[0][0] == "SELECT 'list_credit_cards'"


def test_sends_exactly_the_customer_id_and_limit() -> None:
    _, database_repository, _ = run()

    assert database_repository.calls[0][1] == {"customer_id": CUSTOMER_ID, "limit": 26}


@pytest.mark.parametrize(
    "raw",
    [
        "CLI-ITIECUE8PRH9",
        "  CLI-ITIECUE8PRH9  ",
        "cli-itiecue8prh9",
        "\tCli-ItieCue8prh9\n",
    ],
)
def test_customer_id_is_stripped_and_uppercased(raw: str) -> None:
    _, database_repository, _ = run(customer_id=raw)

    assert database_repository.calls[0][1]["customer_id"] == "CLI-ITIECUE8PRH9"


def test_customer_id_is_otherwise_sent_unchanged_as_a_bind() -> None:
    # No format check: the id is a bind parameter, so odd characters are harmless.
    _, database_repository, _ = run(customer_id="cli-1'; drop table products;--")

    assert database_repository.calls[0][1]["customer_id"] == (
        "CLI-1'; DROP TABLE PRODUCTS;--"
    )


@pytest.mark.parametrize(
    "raw", [None, "", "   ", "\t\n", 123, 12.5, True, ["CLI-1"], {"id": "CLI-1"}]
)
def test_invalid_customer_id_is_rejected_before_the_database_is_called(
    raw: object,
) -> None:
    database_repository = FakeDatabaseRepository(rows=[make_row()])
    query_provider = FakeQueryProvider()
    use_case = ListCreditCardsUseCase(
        database_repository=database_repository, query_provider=query_provider
    )

    with pytest.raises(InvalidInputError) as caught:
        use_case.execute(raw)

    assert caught.value.field == "customer_id"
    assert caught.value.message == INVALID_CUSTOMER_ID
    assert database_repository.calls == []
    assert query_provider.requested == []


def test_limit_is_max_rows_plus_one() -> None:
    _, database_repository, _ = run(max_rows=3)

    assert database_repository.calls[0][1]["limit"] == 4


def test_returns_max_rows_and_flags_truncation_when_more_exist() -> None:
    rows = [make_row(product_id=f"PRD-{i}", card_last4=f"{i:04d}") for i in range(26)]

    result, _, _ = run(rows=rows)

    assert len(result.cards) == 25
    assert result.cards[-1].card_last4 == "0024"
    assert result.truncated is True


def test_exactly_max_rows_is_not_truncated() -> None:
    rows = [make_row(product_id=f"PRD-{i}") for i in range(25)]

    result, _, _ = run(rows=rows)

    assert len(result.cards) == 25
    assert result.truncated is False


def test_no_cards_is_an_empty_result_not_an_error() -> None:
    result, _, _ = run(rows=[])

    assert result == CreditCardsResult(cards=(), truncated=False)


def test_every_column_may_be_null() -> None:
    null_row = {column: None for column in make_row()}

    result, _, _ = run(rows=[null_row, make_row()])

    assert result.cards[0] == CreditCard(
        card_last4=None,
        product_status=None,
        currency=None,
        current_balance=None,
        credit_limit=None,
        available_credit=None,
        expiration_date=None,
        days_past_due=None,
    )
    assert result.cards[1].card_last4 == "4821"


def test_a_timestamp_expiration_date_becomes_a_date() -> None:
    row = make_row(expiration_date=datetime(2027, 3, 31, 23, 59, tzinfo=timezone.utc))

    result, _, _ = run(rows=[row])

    assert result.cards[0].expiration_date == date(2027, 3, 31)
    assert type(result.cards[0].expiration_date) is date


def test_numbers_are_normalised_and_negative_credit_is_kept() -> None:
    row = make_row(
        card_last4=4821,
        current_balance=100,
        credit_limit=250.5,
        available_credit=Decimal("-50.25"),
        days_past_due=45,
    )

    card = run(rows=[row])[0].cards[0]

    assert card.card_last4 == "4821"
    assert card.current_balance == Decimal("100")
    assert card.credit_limit == Decimal("250.5")
    assert card.available_credit == Decimal("-50.25")
    assert card.days_past_due == 45


@pytest.mark.parametrize(
    ("port_error", "domain_error"),
    [
        (
            DataSourceConnectionError("conn refused host=db.internal"),
            DataSourceUnavailableError,
        ),
        (
            QueryLimitExceededError("query exceeded the 128 MiB memory limit"),
            CardLookupError,
        ),
        (
            QueryExecutionError('relation "products" does not exist'),
            CardLookupError,
        ),
        (DataAccessError("unclassified adapter failure"), CardLookupError),
    ],
)
def test_port_errors_become_domain_errors_without_leaking_details(
    port_error: Exception, domain_error: type[DomainError]
) -> None:
    with pytest.raises(domain_error) as caught:
        run(error=port_error)

    assert caught.value.__cause__ is port_error
    assert str(port_error) not in caught.value.message


def test_missing_query_becomes_card_lookup_error() -> None:
    use_case = ListCreditCardsUseCase(
        database_repository=FakeDatabaseRepository(),
        query_provider=FakeQueryProvider(queries={}),
    )

    with pytest.raises(CardLookupError):
        use_case.execute(CUSTOMER_ID)


@pytest.mark.parametrize(
    "bad_row",
    [
        {k: v for k, v in make_row().items() if k != "credit_limit"},
        make_row(current_balance="1250000.00"),
        make_row(current_balance=True),
        make_row(credit_limit=Decimal("NaN")),
        make_row(available_credit=float("inf")),
        make_row(expiration_date="2027-03-31"),
        make_row(days_past_due="0"),
        make_row(days_past_due=True),
        make_row(days_past_due=Decimal("3")),
    ],
)
def test_unmappable_rows_raise_card_data_integrity_error(
    bad_row: dict[str, Any],
) -> None:
    with pytest.raises(CardDataIntegrityError):
        run(rows=[bad_row])


def test_max_rows_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_rows"):
        ListCreditCardsUseCase(
            database_repository=FakeDatabaseRepository(),
            query_provider=FakeQueryProvider(),
            max_rows=0,
        )
