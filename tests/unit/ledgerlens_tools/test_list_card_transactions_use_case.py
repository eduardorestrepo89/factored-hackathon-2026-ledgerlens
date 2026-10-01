"""Tests for ListCardTransactionsUseCase: params, mapping, truncation, errors."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from ledgerlens.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
)
from ledgerlens.application.use_cases.list_card_transactions import (
    ListCardTransactionsUseCase,
)
from ledgerlens.domain.entities.card_transaction import (
    CardTransaction,
    CardTransactionsResult,
)
from ledgerlens.domain.errors import (
    DataIntegrityError,
    DataSourceUnavailableError,
    DomainError,
    SearchTooBroadError,
    TransactionLookupError,
)
from ledgerlens.domain.value_objects.transaction_filters import TransactionStatus
from ledgerlens_fakes import (
    FakeDatabaseRepository,
    FakeQueryProvider,
    make_filters,
    make_row,
)

pytestmark = pytest.mark.unit


def run(
    rows: list[dict[str, Any]] | None = None,
    error: Exception | None = None,
    max_rows: int = 25,
) -> tuple[CardTransactionsResult, FakeDatabaseRepository, FakeQueryProvider]:
    """Execute the use case against fakes and return the result and the fakes."""
    database_repository = FakeDatabaseRepository(rows=rows, error=error)
    query_provider = FakeQueryProvider()
    use_case = ListCardTransactionsUseCase(
        database_repository=database_repository,
        query_provider=query_provider,
        max_rows=max_rows,
    )
    return use_case.execute(make_filters()), database_repository, query_provider


def test_maps_a_row_to_a_card_transaction() -> None:
    result, _, _ = run(rows=[make_row()])

    assert result == CardTransactionsResult(
        transactions=(
            CardTransaction(
                transaction_id="TX-1",
                transaction_date=datetime(2026, 9, 20, 14, 30, tzinfo=timezone.utc),
                card_last4="4242",
                amount=Decimal("12.50"),
                currency="COP",
                transaction_status="Approved",
                merchant_name="Óptica Visión",
                merchant_category="Health",
                channel="POS",
                transaction_city="Medellín",
                transaction_country="Colombia",
            ),
        ),
        truncated=False,
    )


def test_loads_the_named_query_and_passes_its_text_to_the_database_repository() -> None:
    _, database_repository, query_provider = run()

    assert query_provider.requested == ["list_card_transactions"]
    assert database_repository.calls[0][0] == "SELECT 'list_card_transactions'"


def test_sends_every_filter_and_limit_as_params() -> None:
    database_repository = FakeDatabaseRepository()
    use_case = ListCardTransactionsUseCase(
        database_repository=database_repository, query_provider=FakeQueryProvider()
    )
    filters = make_filters(
        card_last4="4242",
        merchant="optica",
        min_amount=Decimal("1.00"),
        max_amount=Decimal("99.99"),
        status=TransactionStatus.DECLINED,
    )

    use_case.execute(filters)

    assert database_repository.calls[0][1] == {
        "customer_id": "CUST-1",
        "date_from": date(2026, 8, 30),
        "date_to": date(2026, 9, 29),
        "card_last4": "4242",
        "merchant": "optica",
        "min_amount": Decimal("1.00"),
        "max_amount": Decimal("99.99"),
        "status": "Declined",
        "limit": 26,
    }


def test_absent_filters_are_sent_as_none() -> None:
    _, database_repository, _ = run()

    params = database_repository.calls[0][1]
    for key in ("card_last4", "merchant", "min_amount", "max_amount", "status"):
        assert params[key] is None


def test_limit_is_max_rows_plus_one() -> None:
    _, database_repository, _ = run(max_rows=3)

    assert database_repository.calls[0][1]["limit"] == 4


def test_returns_max_rows_and_flags_truncation_when_more_exist() -> None:
    rows = [make_row(transaction_id=f"TX-{i}") for i in range(26)]

    result, _, _ = run(rows=rows)

    assert len(result.transactions) == 25
    assert result.transactions[-1].transaction_id == "TX-24"
    assert result.truncated is True


def test_exactly_max_rows_is_not_truncated() -> None:
    rows = [make_row(transaction_id=f"TX-{i}") for i in range(25)]

    result, _, _ = run(rows=rows)

    assert len(result.transactions) == 25
    assert result.truncated is False


def test_empty_result_is_not_an_error() -> None:
    result, _, _ = run(rows=[])

    assert result == CardTransactionsResult(transactions=(), truncated=False)


def test_null_optional_columns_are_kept_as_none() -> None:
    nullable = (
        "currency",
        "transaction_status",
        "merchant_name",
        "merchant_category",
        "channel",
        "transaction_city",
        "transaction_country",
    )
    row = make_row(**dict.fromkeys(nullable))

    result, _, _ = run(rows=[row])

    transaction = result.transactions[0]
    for column in nullable:
        assert getattr(transaction, column) is None


def test_numeric_ids_and_float_amounts_are_normalised() -> None:
    result, _, _ = run(rows=[make_row(transaction_id=123, amount=12.5)])

    assert result.transactions[0].transaction_id == "123"
    assert result.transactions[0].amount == Decimal("12.5")


@pytest.mark.parametrize(
    ("port_error", "domain_error"),
    [
        (
            DataSourceConnectionError("conn refused host=db.internal"),
            DataSourceUnavailableError,
        ),
        (
            QueryLimitExceededError("query exceeded the 128 MiB memory limit"),
            SearchTooBroadError,
        ),
        (
            QueryExecutionError('relation "transactions" does not exist'),
            TransactionLookupError,
        ),
        (DataAccessError("unclassified adapter failure"), TransactionLookupError),
    ],
)
def test_port_errors_become_domain_errors_without_leaking_details(
    port_error: Exception, domain_error: type[DomainError]
) -> None:
    with pytest.raises(domain_error) as caught:
        run(error=port_error)

    assert caught.value.__cause__ is port_error
    assert str(port_error) not in caught.value.message


def test_missing_query_becomes_transaction_lookup_error() -> None:
    use_case = ListCardTransactionsUseCase(
        database_repository=FakeDatabaseRepository(),
        query_provider=FakeQueryProvider(queries={}),
    )

    with pytest.raises(TransactionLookupError):
        use_case.execute(make_filters())


@pytest.mark.parametrize(
    "bad_row",
    [
        {k: v for k, v in make_row().items() if k != "amount"},
        make_row(transaction_id=None),
        make_row(card_last4=None),
        make_row(transaction_date="2026-09-20T14:30:00"),
        make_row(transaction_date=None),
        make_row(amount=None),
        make_row(amount="12.50"),
        make_row(amount=True),
        make_row(amount=Decimal("NaN")),
    ],
)
def test_unmappable_rows_raise_data_integrity_error(bad_row: dict[str, Any]) -> None:
    with pytest.raises(DataIntegrityError):
        run(rows=[bad_row])


def test_max_rows_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_rows"):
        ListCardTransactionsUseCase(
            database_repository=FakeDatabaseRepository(),
            query_provider=FakeQueryProvider(),
            max_rows=0,
        )
