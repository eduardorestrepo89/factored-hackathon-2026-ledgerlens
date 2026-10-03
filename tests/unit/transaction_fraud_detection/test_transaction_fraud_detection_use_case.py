"""Tests for TransactionFraudDetectionUseCase."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from transaction_fraud_detection_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
)
from transaction_fraud_detection_lambda.application.use_cases.transaction_fraud_detection import (  # noqa: E501
    TransactionFraudDetectionUseCase,
)
from transaction_fraud_detection_lambda.domain.entities.fraud_assessment import (
    CardSweep,
    FraudAssessment,
)
from transaction_fraud_detection_lambda.domain.errors import (
    CardNotFoundError,
    DataSourceUnavailableError,
    DomainError,
    FraudCheckDataIntegrityError,
    FraudCheckLookupError,
    TransactionNotFoundError,
)
from transaction_fraud_detection_lambda.domain.value_objects.fraud_bands import (
    REVIEW_ABOVE,
    FraudVerdict,
    ScoreBasis,
)
from transaction_fraud_detection_lambda.domain.value_objects.fraud_check_request import (  # noqa: E501
    FraudCheckRequest,
)

from .fakes import (
    CUSTOMER_ID,
    TRANSACTION_ID,
    FakeFraudRepository,
    FakeQueryProvider,
    Outcome,
    fraud_responses,
    make_count_only_row,
    make_sweep_row,
    make_transaction_row,
)

pytestmark = pytest.mark.unit

AS_OF = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
# What the SQL receives: the same instant as naive UTC.
AS_OF_SQL = datetime(2026, 6, 17, 23, 59, 59)
TX_REQUEST = FraudCheckRequest(
    customer_id=CUSTOMER_ID, transaction_id=TRANSACTION_ID, card_last4=None
)
CARD_REQUEST = FraudCheckRequest(
    customer_id=CUSTOMER_ID, transaction_id=None, card_last4="4497"
)
ASSESSMENT = FraudAssessment(
    transaction_id=TRANSACTION_ID,
    transaction_date=datetime(2026, 5, 31, 6, 9, 15),
    card_last4="4497",
    merchant_name="Estación de Servicio",
    amount=Decimal("288.69"),
    currency="USD",
    transaction_status="Approved",
    verdict=FraudVerdict.FRAUD,
    basis=ScoreBasis.SCORED,
)


def make_use_case(
    responses: dict[str, Outcome] | None = None, max_rows: int = 25
) -> tuple[TransactionFraudDetectionUseCase, FakeFraudRepository]:
    """Build the use case over a fake repository; return both."""
    database_repository = FakeFraudRepository(
        fraud_responses() if responses is None else responses
    )
    use_case = TransactionFraudDetectionUseCase(
        database_repository=database_repository,
        query_provider=FakeQueryProvider(),
        max_rows=max_rows,
    )
    return use_case, database_repository


def sweep_rows(count: int, checked: int = 40) -> list[dict[str, Any]]:
    """Build ``count`` flagged sweep rows with distinct ids."""
    return [
        make_sweep_row(transaction_id=f"TRX-{i:03d}", checked=checked)
        for i in range(count)
    ]


def test_transaction_mode_sends_exactly_its_params() -> None:
    use_case, database_repository = make_use_case()

    use_case.execute(TX_REQUEST, as_of=AS_OF)

    assert database_repository.calls == [
        (
            "fraud_transaction",
            {
                "customer_id": CUSTOMER_ID,
                "transaction_id": TRANSACTION_ID,
                "as_of": AS_OF_SQL,
            },
        )
    ]


def test_transaction_mode_maps_the_row_and_drops_the_score() -> None:
    use_case, _ = make_use_case()

    result = use_case.execute(TX_REQUEST, as_of=AS_OF)

    assert result == ASSESSMENT
    assert not hasattr(result, "fraud_score")


def test_card_mode_checks_the_card_then_sweeps() -> None:
    use_case, database_repository = make_use_case()

    use_case.execute(CARD_REQUEST, as_of=AS_OF)

    assert database_repository.calls == [
        ("fraud_card_exists", {"customer_id": CUSTOMER_ID, "card_last4": "4497"}),
        (
            "fraud_card_sweep",
            {
                "customer_id": CUSTOMER_ID,
                "card_last4": "4497",
                "as_of": AS_OF_SQL,
                "review_above": Decimal("30"),
                "limit": 26,
            },
        ),
    ]
    assert database_repository.calls[1][1]["review_above"] is REVIEW_ABOVE


def test_card_mode_returns_the_sweep() -> None:
    use_case, _ = make_use_case()

    result = use_case.execute(CARD_REQUEST, as_of=AS_OF)

    assert result == CardSweep(
        card_last4="4497",
        date_from=AS_OF_SQL - timedelta(days=30),
        date_to=AS_OF_SQL,
        checked=3,
        flagged=(ASSESSMENT,),
        truncated=False,
    )


def test_an_aware_as_of_in_another_zone_is_sent_as_naive_utc() -> None:
    use_case, database_repository = make_use_case()
    bogota = datetime(2026, 6, 17, 18, 59, 59, tzinfo=timezone(timedelta(hours=-5)))

    result = use_case.execute(CARD_REQUEST, as_of=bogota)

    assert database_repository.calls[1][1]["as_of"] == AS_OF_SQL
    assert isinstance(result, CardSweep)
    assert result.date_to == AS_OF_SQL


def test_no_transaction_row_raises_not_found() -> None:
    use_case, _ = make_use_case(fraud_responses(fraud_transaction=[]))

    with pytest.raises(TransactionNotFoundError):
        use_case.execute(TX_REQUEST, as_of=AS_OF)


def test_no_card_row_raises_card_not_found_without_sweeping() -> None:
    use_case, database_repository = make_use_case(fraud_responses(fraud_card_exists=[]))

    with pytest.raises(CardNotFoundError):
        use_case.execute(CARD_REQUEST, as_of=AS_OF)
    assert database_repository.queries == ["fraud_card_exists"]


def test_a_sweep_with_no_rows_has_checked_zero() -> None:
    use_case, _ = make_use_case(fraud_responses(fraud_card_sweep=[]))

    result = use_case.execute(CARD_REQUEST, as_of=AS_OF)

    assert isinstance(result, CardSweep)
    assert (result.checked, result.flagged, result.truncated) == (0, (), False)


def test_a_count_only_row_gives_checked_and_no_items() -> None:
    use_case, _ = make_use_case(
        fraud_responses(fraud_card_sweep=[make_count_only_row(checked=3)])
    )

    result = use_case.execute(CARD_REQUEST, as_of=AS_OF)

    assert isinstance(result, CardSweep)
    assert (result.checked, result.flagged, result.truncated) == (3, (), False)


def test_checked_comes_from_the_rows() -> None:
    use_case, _ = make_use_case(fraud_responses(fraud_card_sweep=sweep_rows(2, 7)))

    result = use_case.execute(CARD_REQUEST, as_of=AS_OF)

    assert isinstance(result, CardSweep)
    assert result.checked == 7
    assert [a.transaction_id for a in result.flagged] == ["TRX-000", "TRX-001"]


def test_the_sweep_is_capped_and_marked_truncated() -> None:
    use_case, _ = make_use_case(fraud_responses(fraud_card_sweep=sweep_rows(26)))

    result = use_case.execute(CARD_REQUEST, as_of=AS_OF)

    assert isinstance(result, CardSweep)
    assert len(result.flagged) == 25
    assert result.truncated is True
    assert result.flagged[-1].transaction_id == "TRX-024"


def test_exactly_the_cap_is_not_truncated() -> None:
    use_case, _ = make_use_case(fraud_responses(fraud_card_sweep=sweep_rows(25)))

    result = use_case.execute(CARD_REQUEST, as_of=AS_OF)

    assert isinstance(result, CardSweep)
    assert (len(result.flagged), result.truncated) == (25, False)


def test_max_rows_sets_the_cap_and_the_limit() -> None:
    use_case, database_repository = make_use_case(
        fraud_responses(fraud_card_sweep=sweep_rows(4)), max_rows=3
    )

    result = use_case.execute(CARD_REQUEST, as_of=AS_OF)

    assert isinstance(result, CardSweep)
    assert (len(result.flagged), result.truncated) == (3, True)
    assert database_repository.calls[1][1]["limit"] == 4


@pytest.mark.parametrize(
    ("score", "verdict", "basis"),
    [
        (Decimal("62.37"), FraudVerdict.FRAUD, ScoreBasis.SCORED),
        (62, FraudVerdict.FRAUD, ScoreBasis.SCORED),
        (Decimal("50.00"), FraudVerdict.REVIEW, ScoreBasis.SCORED),
        (Decimal("30.01"), FraudVerdict.REVIEW, ScoreBasis.SCORED),
        (Decimal("30.00"), FraudVerdict.NO_FRAUD, ScoreBasis.SCORED),
        (None, FraudVerdict.NO_FRAUD, ScoreBasis.NOT_SCORED),
    ],
)
def test_scores_are_banded(
    score: object, verdict: FraudVerdict, basis: ScoreBasis
) -> None:
    use_case, _ = make_use_case(
        fraud_responses(fraud_transaction=[make_transaction_row(fraud_score=score)])
    )

    result = use_case.execute(TX_REQUEST, as_of=AS_OF)

    assert isinstance(result, FraudAssessment)
    assert (result.verdict, result.basis) == (verdict, basis)


@pytest.mark.parametrize(
    ("request_", "query", "error", "expected"),
    [
        (
            TX_REQUEST,
            "fraud_transaction",
            DataSourceConnectionError("down"),
            DataSourceUnavailableError,
        ),
        (
            TX_REQUEST,
            "fraud_transaction",
            QueryExecutionError("boom"),
            FraudCheckLookupError,
        ),
        (
            CARD_REQUEST,
            "fraud_card_exists",
            DataSourceConnectionError("down"),
            DataSourceUnavailableError,
        ),
        (
            CARD_REQUEST,
            "fraud_card_exists",
            QueryExecutionError("boom"),
            FraudCheckLookupError,
        ),
        (
            CARD_REQUEST,
            "fraud_card_sweep",
            DataSourceConnectionError("down"),
            DataSourceUnavailableError,
        ),
        (
            CARD_REQUEST,
            "fraud_card_sweep",
            QueryLimitExceededError("128 MiB"),
            FraudCheckLookupError,
        ),
    ],
)
def test_each_port_error_becomes_its_domain_error(
    request_: FraudCheckRequest,
    query: str,
    error: Exception,
    expected: type[DomainError],
) -> None:
    use_case, _ = make_use_case(fraud_responses(**{query: error}))

    with pytest.raises(expected):
        use_case.execute(request_, as_of=AS_OF)


@pytest.mark.parametrize("request_", [TX_REQUEST, CARD_REQUEST])
def test_a_missing_query_raises_lookup(request_: FraudCheckRequest) -> None:
    use_case = TransactionFraudDetectionUseCase(
        database_repository=FakeFraudRepository(fraud_responses()),
        query_provider=FakeQueryProvider({}),
    )

    with pytest.raises(FraudCheckLookupError):
        use_case.execute(request_, as_of=AS_OF)


def without(row: dict[str, Any], column: str) -> dict[str, Any]:
    """Return ``row`` without ``column``."""
    return {key: value for key, value in row.items() if key != column}


@pytest.mark.parametrize(
    ("request_", "query", "row"),
    [
        (TX_REQUEST, "fraud_transaction", make_transaction_row(fraud_score="62")),
        (TX_REQUEST, "fraud_transaction", make_transaction_row(fraud_score=62.5)),
        (TX_REQUEST, "fraud_transaction", make_transaction_row(fraud_score=True)),
        (TX_REQUEST, "fraud_transaction", make_transaction_row(transaction_id=None)),
        (TX_REQUEST, "fraud_transaction", make_transaction_row(amount="288.69")),
        (
            TX_REQUEST,
            "fraud_transaction",
            make_transaction_row(transaction_date="2026-05-31"),
        ),
        (TX_REQUEST, "fraud_transaction", without(make_transaction_row(), "currency")),
        (CARD_REQUEST, "fraud_card_sweep", without(make_sweep_row(), "checked")),
        (CARD_REQUEST, "fraud_card_sweep", make_sweep_row(checked="3")),
        (CARD_REQUEST, "fraud_card_sweep", make_sweep_row(checked=True)),
        (CARD_REQUEST, "fraud_card_sweep", make_count_only_row(checked=None)),  # type: ignore[arg-type]
        (CARD_REQUEST, "fraud_card_sweep", make_sweep_row(fraud_score=Decimal("NaN"))),
    ],
)
def test_a_bad_row_raises_data_integrity(
    request_: FraudCheckRequest, query: str, row: dict[str, Any]
) -> None:
    use_case, _ = make_use_case(fraud_responses(**{query: [row]}))

    with pytest.raises(FraudCheckDataIntegrityError):
        use_case.execute(request_, as_of=AS_OF)


def test_max_rows_below_one_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_rows"):
        TransactionFraudDetectionUseCase(
            database_repository=FakeFraudRepository(),
            query_provider=FakeQueryProvider(),
            max_rows=0,
        )


def test_a_naive_as_of_is_rejected_before_any_query() -> None:
    use_case, database_repository = make_use_case()

    with pytest.raises(ValueError, match="aware"):
        use_case.execute(TX_REQUEST, as_of=AS_OF_SQL)
    assert database_repository.calls == []
