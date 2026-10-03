"""Tests for OpenClaimUseCase."""

import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from open_claim_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    DuplicateKeyError,
    QueryExecutionError,
    WriteConflictError,
)
from open_claim_lambda.application.use_cases.open_claim import (
    OpenClaimUseCase,
    claim_id_for,
)
from open_claim_lambda.domain.entities.claim import (
    Claim,
    ClaimsResult,
    ResolutionEstimate,
)
from open_claim_lambda.domain.errors import (
    ClaimDataIntegrityError,
    ClaimError,
    DataSourceUnavailableError,
    DomainError,
    InvalidInputError,
    TransactionsNotFoundError,
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
TXS = "claim_transactions"
INSERT = "insert_claim"
ESTIMATE = "resolution_estimate"
STATEMENT = "No reconozco este cargo"
INSERTED = [{"complaint_id": "CMP-X"}]
ESTIMATE_ROW = [{"median_days": 4.2, "p90_days": Decimal("11.5")}]
ARGS: dict[str, Any] = {
    "customer_id": CUSTOMER_ID,
    "transaction_ids": ["TRX-1"],
    "claim_type": "fraud",
    "customer_statement": STATEMENT,
    "customer_confirmed": True,
}


def make_use_case(
    results: dict[str, Outcomes] | None = None,
    query_provider: FakeQueryProvider | None = None,
) -> tuple[OpenClaimUseCase, FakeDatabaseRepository]:
    """Build the use case over fakes; return it with its repository."""
    repository = FakeDatabaseRepository(results)
    use_case = OpenClaimUseCase(
        database_repository=repository,
        query_provider=query_provider or FakeQueryProvider(),
    )
    return use_case, repository


def open_claim(use_case: OpenClaimUseCase, **overrides: Any) -> ClaimsResult:
    """Run the use case with ARGS, overridden by ``overrides``."""
    return use_case.execute(**{**ARGS, **overrides}, now=NOW)


def default_results(rows: list[dict[str, Any]] | None = None) -> dict[str, Outcomes]:
    """One fraud transaction, a successful insert and an estimate."""
    return {TXS: rows or [make_row()], INSERT: INSERTED, ESTIMATE: ESTIMATE_ROW}


def test_a_fraud_claim_is_opened_with_the_estimate() -> None:
    use_case, repository = make_use_case(default_results())

    result = open_claim(use_case)

    claim_id = claim_id_for(CUSTOMER_ID, "fraud", "PRD-1", "USD", ["TRX-1"])
    assert result == ClaimsResult(
        claims=(
            Claim(
                claim_id=claim_id,
                card_last4="4821",
                transaction_ids=("TRX-1",),
                claimed_amount=Decimal("740.00"),
                currency="USD",
                priority="High",
                status="Open",
                already_existed=False,
            ),
        ),
        resolution_estimate=ResolutionEstimate(median_days=5, p90_days=12),
    )
    assert repository.params_of(TXS) == [
        {"customer_id": CUSTOMER_ID, "transaction_ids": ["TRX-1"]}
    ]
    assert repository.params_of(INSERT) == [
        {
            "complaint_id": claim_id,
            "creation_date": NAIVE_NOW,
            "process_date": NAIVE_NOW.date(),
            "customer_id": CUSTOMER_ID,
            "subcategory": "Cargo no reconocido",
            "product_id": "PRD-1",
            "description": f"{STATEMENT} | tx: TRX-1",
            "claimed_amount": Decimal("740.00"),
            "currency": "USD",
            "priority": "High",
        }
    ]
    assert repository.params_of(ESTIMATE) == [
        {
            "subcategory": "Cargo no reconocido",
            "since": datetime(2025, 6, 17, 23, 59, 59),
        }
    ]


def test_a_dispute_uses_its_own_subcategory() -> None:
    use_case, repository = make_use_case(default_results())

    open_claim(use_case, claim_type=" Dispute ")

    assert repository.params_of(INSERT)[0]["subcategory"] == "Cobro indebido"
    assert repository.params_of(ESTIMATE)[0]["subcategory"] == "Cobro indebido"


@pytest.mark.parametrize(
    ("amounts_usd", "priority"),
    [
        ([Decimal("95.00")], "Medium"),
        ([Decimal("500.00")], "Medium"),
        ([Decimal("500.01")], "High"),
        ([Decimal("300.00"), Decimal("200.01")], "High"),
        ([None], "High"),
        ([Decimal("10.00"), None], "High"),
    ],
)
def test_priority_is_high_above_500_usd_or_when_unknown(
    amounts_usd: list[Decimal | None], priority: str
) -> None:
    rows = [
        make_row(transaction_id=f"TRX-{i}", amount_usd=usd)
        for i, usd in enumerate(amounts_usd, start=1)
    ]
    ids = [row["transaction_id"] for row in rows]
    use_case, _ = make_use_case(default_results(rows))

    result = open_claim(use_case, transaction_ids=ids)

    assert result.claims[0].priority == priority


def test_transaction_ids_are_cleaned_and_deduplicated_in_order() -> None:
    rows = [make_row(transaction_id="TRX-2"), make_row(transaction_id="TRX-1")]
    use_case, repository = make_use_case(default_results(rows))

    result = open_claim(use_case, transaction_ids=[" trx-2", "TRX-1", "trx-2 "])

    assert repository.params_of(TXS)[0]["transaction_ids"] == ["TRX-2", "TRX-1"]
    assert result.claims[0].transaction_ids == ("TRX-2", "TRX-1")
    assert result.claims[0].claimed_amount == Decimal("1480.00")
    assert repository.params_of(INSERT)[0]["description"] == (
        f"{STATEMENT} | tx: TRX-2,TRX-1"
    )


def test_one_claim_per_card_and_currency_ordered_by_card_then_currency() -> None:
    rows = [
        make_row(transaction_id="TRX-1", product_id="PRD-B", card_last4="9999"),
        make_row(transaction_id="TRX-2", product_id="PRD-A", card_last4="1111"),
        make_row(
            transaction_id="TRX-3",
            product_id="PRD-A",
            card_last4="1111",
            currency="COP",
            amount=Decimal("350000.00"),
            amount_usd=Decimal("87.50"),
        ),
        make_row(transaction_id="TRX-4", product_id="PRD-A", card_last4="1111"),
    ]
    use_case, repository = make_use_case(default_results(rows))

    result = open_claim(use_case, transaction_ids=["TRX-1", "TRX-2", "TRX-3", "TRX-4"])

    assert [(c.card_last4, c.currency, c.transaction_ids) for c in result.claims] == [
        ("1111", "COP", ("TRX-3",)),
        ("1111", "USD", ("TRX-2", "TRX-4")),
        ("9999", "USD", ("TRX-1",)),
    ]
    assert [c.claimed_amount for c in result.claims] == [
        Decimal("350000.00"),
        Decimal("1480.00"),
        Decimal("740.00"),
    ]
    assert len({c.claim_id for c in result.claims}) == 3
    assert len(repository.params_of(INSERT)) == 3


def test_the_same_transactions_in_another_order_give_the_same_claim_id() -> None:
    rows = [make_row(transaction_id="TRX-1"), make_row(transaction_id="TRX-2")]
    first, _ = make_use_case(default_results(rows))
    second, _ = make_use_case(default_results(rows))

    a = open_claim(first, transaction_ids=["TRX-1", "TRX-2"]).claims[0].claim_id
    b = open_claim(second, transaction_ids=["trx-2", "TRX-1"]).claims[0].claim_id

    assert a == b
    assert re.fullmatch(r"CMP-[A-Z2-7]{20}", a)


def test_the_claim_id_depends_on_every_part_of_the_claim() -> None:
    base = ("CLI-1", "fraud", "PRD-1", "USD", ["TRX-1"])
    variants = [
        ("CLI-2", "fraud", "PRD-1", "USD", ["TRX-1"]),
        ("CLI-1", "dispute", "PRD-1", "USD", ["TRX-1"]),
        ("CLI-1", "fraud", "PRD-2", "USD", ["TRX-1"]),
        ("CLI-1", "fraud", "PRD-1", "COP", ["TRX-1"]),
        ("CLI-1", "fraud", "PRD-1", "USD", ["TRX-1", "TRX-2"]),
    ]

    assert len({claim_id_for(*v) for v in [base, *variants]}) == 6


def test_an_existing_claim_is_returned_as_already_existed() -> None:
    results = default_results()
    results[INSERT] = DuplicateKeyError("23505")
    use_case, repository = make_use_case(results)

    result = open_claim(use_case)

    assert result.claims[0].already_existed is True
    assert result.claims[0].status == "Open"
    assert result.resolution_estimate == ResolutionEstimate(median_days=5, p90_days=12)
    assert len(repository.params_of(INSERT)) == 1


def test_missing_transactions_raise_not_found_before_any_insert() -> None:
    use_case, repository = make_use_case(default_results([make_row()]))

    with pytest.raises(TransactionsNotFoundError) as caught:
        open_claim(use_case, transaction_ids=["TRX-1", "TRX-9", "TRX-8"])

    assert caught.value.transaction_ids == ("TRX-9", "TRX-8")
    assert repository.params_of(INSERT) == []


def test_no_estimate_when_history_is_too_short() -> None:
    results = default_results()
    results[ESTIMATE] = []
    use_case, _ = make_use_case(results)

    assert open_claim(use_case).resolution_estimate is None


@pytest.mark.parametrize(
    "estimate",
    [
        QueryExecutionError("function percentile_cont does not exist"),
        DataSourceConnectionError("down"),
        [{"median_days": None, "p90_days": 3}],
        [{"median_days": float("nan"), "p90_days": 3}],
        [{"p90_days": 3}],
    ],
)
def test_a_failed_estimate_never_fails_the_written_claims(
    estimate: Outcomes, caplog: pytest.LogCaptureFixture
) -> None:
    results = default_results()
    results[ESTIMATE] = estimate
    use_case, _ = make_use_case(results)
    caplog.set_level(logging.WARNING)

    result = open_claim(use_case)

    assert result.resolution_estimate is None
    assert len(result.claims) == 1
    assert "Resolution estimate failed" in caplog.text


def test_a_missing_estimate_sql_file_gives_no_estimate() -> None:
    provider = FakeQueryProvider(names=(TXS, INSERT))
    use_case, _ = make_use_case(default_results(), query_provider=provider)

    assert open_claim(use_case).resolution_estimate is None


def assert_rejected(field: str, **overrides: Any) -> InvalidInputError:
    """Run with ``overrides``; it must fail on ``field`` before any query."""
    use_case, repository = make_use_case(default_results())
    with pytest.raises(InvalidInputError) as caught:
        open_claim(use_case, **overrides)
    assert caught.value.field == field
    assert repository.calls == []
    return caught.value


@pytest.mark.parametrize(
    "transaction_ids",
    [
        None,
        "TRX-1",
        [],
        [""],
        ["   "],
        [1],
        ["X" * 31],
        [f"TRX-{i}" for i in range(11)],
    ],
)
def test_transaction_ids_must_be_1_to_10_ids(transaction_ids: object) -> None:
    error = assert_rejected("transaction_ids", transaction_ids=transaction_ids)

    assert error.reason == (
        "must be a list of 1 to 10 transaction ids from list_card_transactions"
    )


def test_ten_distinct_ids_with_repeats_are_accepted() -> None:
    ids = [f"TRX-{i}" for i in range(10)] * 2
    rows = [make_row(transaction_id=f"TRX-{i}") for i in range(10)]
    use_case, repository = make_use_case(default_results(rows))

    open_claim(use_case, transaction_ids=ids)

    assert len(repository.params_of(TXS)[0]["transaction_ids"]) == 10


@pytest.mark.parametrize("claim_type", [None, "", "chargeback", 1])
def test_claim_type_must_be_fraud_or_dispute(claim_type: object) -> None:
    error = assert_rejected("claim_type", claim_type=claim_type)

    assert error.reason == "must be fraud or dispute"


@pytest.mark.parametrize("statement", [None, "", "   ", "x" * 501, 42])
def test_the_statement_must_be_1_to_500_characters(statement: object) -> None:
    error = assert_rejected("customer_statement", customer_statement=statement)

    assert error.reason == "must be the customer's own words, 1 to 500 characters"


def test_a_statement_of_500_characters_is_accepted() -> None:
    use_case, repository = make_use_case(default_results())

    open_claim(use_case, customer_statement="x" * 500)

    assert repository.params_of(INSERT)[0]["description"].startswith("x" * 500)


@pytest.mark.parametrize("confirmed", [False, None, "true", 1])
def test_only_the_boolean_true_confirms_the_claim(confirmed: object) -> None:
    error = assert_rejected("customer_confirmed", customer_confirmed=confirmed)

    assert error.reason == (
        "must be true, after the customer explicitly confirmed these transactions"
    )


@pytest.mark.parametrize("customer_id", [None, "", "   ", 42])
def test_a_bad_customer_id_is_rejected(customer_id: object) -> None:
    assert_rejected("customer_id", customer_id=customer_id)


@pytest.mark.parametrize(
    ("failing_query", "port_error", "domain_error"),
    [
        (TXS, DataSourceConnectionError("down"), DataSourceUnavailableError),
        (TXS, QueryExecutionError("boom"), ClaimError),
        (INSERT, WriteConflictError("40001"), DataSourceUnavailableError),
        (INSERT, QueryExecutionError("boom"), ClaimError),
    ],
)
def test_port_errors_become_domain_errors(
    failing_query: str,
    port_error: DataAccessError,
    domain_error: type[DomainError],
) -> None:
    results = default_results()
    results[failing_query] = port_error
    use_case, _ = make_use_case(results)

    with pytest.raises(domain_error) as caught:
        open_claim(use_case)

    assert caught.value.__cause__ is port_error


def test_a_missing_transactions_sql_file_raises_claim_error() -> None:
    use_case, _ = make_use_case(query_provider=FakeQueryProvider(names=()))

    with pytest.raises(ClaimError):
        open_claim(use_case)


def test_a_later_group_failing_leaves_the_earlier_claim_written() -> None:
    rows = [
        make_row(transaction_id="TRX-1"),
        make_row(transaction_id="TRX-2", currency="COP"),
    ]
    results = default_results(rows)
    results[INSERT] = (INSERTED, QueryExecutionError("boom"))
    use_case, repository = make_use_case(results)

    with pytest.raises(ClaimError):
        open_claim(use_case, transaction_ids=["TRX-1", "TRX-2"])

    assert len(repository.params_of(INSERT)) == 2


@pytest.mark.parametrize(
    "row",
    [
        make_row(amount=None),
        make_row(amount=True),
        make_row(amount=Decimal("NaN")),
        make_row(currency=3),
        make_row(amount_usd="740"),
        {k: v for k, v in make_row().items() if k != "card_last4"},
    ],
)
def test_an_unreadable_transaction_row_raises_claim_data_integrity_error(
    row: dict[str, Any],
) -> None:
    use_case, repository = make_use_case(default_results([row]))

    with pytest.raises(ClaimDataIntegrityError):
        open_claim(use_case)

    assert repository.params_of(INSERT) == []
