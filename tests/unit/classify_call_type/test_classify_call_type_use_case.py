"""Tests for ClassifyCallTypeUseCase (spec section 4)."""

import logging
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from classify_call_type_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
)
from classify_call_type_lambda.application.use_cases.classify_call_type import (
    QUERY_NAMES,
    ClassifyCallTypeUseCase,
)
from classify_call_type_lambda.domain.entities.call_classification import (
    CallClassification,
    RankedReason,
)
from classify_call_type_lambda.domain.entities.candidates import (
    AppEventCandidate,
    CardCandidate,
    CaseCandidate,
    TransactionCandidate,
)
from classify_call_type_lambda.domain.errors import (
    CallReasonLookupError,
    DataSourceUnavailableError,
    InvalidInputError,
)
from classify_call_type_lambda.domain.value_objects.call_reasons import (
    CallReason,
    Source,
)
from classify_call_type_lambda.domain.value_objects.fraud_bands import REVIEW_ABOVE

from .fakes import (
    AS_OF,
    AS_OF_SQL,
    CHARGE_DATE,
    CUSTOMER_ID,
    TRANSACTION_ID,
    FakeClassifyRepository,
    FakeQueryProvider,
    Outcome,
    classify_responses,
    make_app_event_row,
    make_card_row,
    make_case_row,
    make_transaction_row,
)

pytestmark = pytest.mark.unit

R = CallReason
TODAY = date(2026, 6, 17)

P07_CANDIDATE = TransactionCandidate(
    transaction_id=TRANSACTION_ID,
    transaction_date=CHARGE_DATE,
    card_last4="4497",
    card_currency="USD",
    merchant_name="Estación de Servicio",
    amount=Decimal("288.69"),
    currency="USD",
    transaction_status="Approved",
    response_code="00",
    transaction_country="México",
    home_country="México",
    fraud_score=Decimal("62.00"),
)
P07_FRAUD = RankedReason(
    reason=R.FRAUD_SUSPECTED,
    confidence=Decimal("0.77"),
    ref_id=TRANSACTION_ID,
    candidate=P07_CANDIDATE,
)

TRANSACTION_REASONS = (
    R.FRAUD_SUSPECTED,
    R.DECLINED_TRANSACTION,
    R.UNRECOGNIZED_CHARGE_REVIEW,
    R.PENDING_TRANSACTION,
    R.REVERSED_TRANSACTION,
    R.FOREIGN_TRANSACTION,
)
CARD_REASONS = (R.CARD_NOT_ACTIVE, R.PAYMENT_OVERDUE, R.CARD_EXPIRING)


def make_use_case(
    responses: dict[str, Outcome] | None = None,
    query_provider: FakeQueryProvider | None = None,
) -> tuple[ClassifyCallTypeUseCase, FakeClassifyRepository]:
    """Wire the use case to fakes; by default they answer P07."""
    repository = FakeClassifyRepository(
        classify_responses() if responses is None else responses
    )
    use_case = ClassifyCallTypeUseCase(
        database_repository=repository,
        query_provider=query_provider or FakeQueryProvider(),
    )
    return use_case, repository


def _summary(result: CallClassification) -> list[tuple[CallReason, Decimal, str]]:
    return [(item.reason, item.confidence, item.ref_id) for item in result.reasons]


def _without(row: dict[str, Any], column: str) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != column}


# --- the happy path and the params ------------------------------------------


def test_constants_are_pinned() -> None:
    assert ClassifyCallTypeUseCase.TOP_N == 3
    assert ClassifyCallTypeUseCase.TRANSACTION_CANDIDATE_CAP == 200
    assert QUERY_NAMES == {
        Source.TRANSACTIONS: "call_reason_transactions",
        Source.CARDS: "call_reason_cards",
        Source.CASES: "call_reason_cases",
        Source.APP_EVENTS: "call_reason_app_events",
    }


def test_p07_ranks_its_flagged_charge() -> None:
    use_case, _ = make_use_case()

    result = use_case.execute(CUSTOMER_ID, AS_OF)

    assert result == CallClassification(
        reasons=(P07_FRAUD,), unavailable=(), as_of_date=TODAY
    )


def test_queries_run_in_order_with_their_params() -> None:
    use_case, repository = make_use_case()

    use_case.execute(CUSTOMER_ID, AS_OF)

    assert repository.calls == [
        (
            "call_reason_transactions",
            {
                "customer_id": CUSTOMER_ID,
                "as_of": AS_OF_SQL,
                "review_above": Decimal("30"),
                "limit": 201,
            },
        ),
        ("call_reason_cards", {"customer_id": CUSTOMER_ID}),
        ("call_reason_cases", {"customer_id": CUSTOMER_ID, "as_of": AS_OF_SQL}),
        ("call_reason_app_events", {"customer_id": CUSTOMER_ID, "as_of": AS_OF_SQL}),
    ]
    assert repository.calls[0][1]["review_above"] is REVIEW_ABOVE


def test_customer_id_is_stripped_and_uppercased() -> None:
    use_case, repository = make_use_case()

    use_case.execute("  cli-ex6boaoefzhq ", AS_OF)

    assert {params["customer_id"] for _, params in repository.calls} == {CUSTOMER_ID}


@pytest.mark.parametrize("bad", [None, 42, "", "   "])
def test_bad_customer_id_is_rejected_before_any_query(bad: object) -> None:
    use_case, repository = make_use_case()

    with pytest.raises(InvalidInputError) as caught:
        use_case.execute(bad, AS_OF)

    assert caught.value.field == "customer_id"
    assert caught.value.reason == "is required and must be a non-empty string"
    assert repository.calls == []


def test_naive_as_of_is_rejected_before_any_query() -> None:
    use_case, repository = make_use_case()

    with pytest.raises(ValueError, match="aware"):
        use_case.execute(CUSTOMER_ID, AS_OF_SQL)

    assert repository.calls == []


def test_non_utc_as_of_is_converted_before_the_window_check() -> None:
    # 21:00 at -05:00 is 02:00 UTC the next day.
    as_of = datetime(2026, 6, 17, 21, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    as_of_utc = datetime(2026, 6, 18, 2, 0, 0)
    declined = make_transaction_row(
        transaction_id="TRX-D",
        transaction_status="Declined",
        transaction_date=as_of_utc - timedelta(hours=72),
        fraud_score=None,
    )
    # Expired the day before as_of's UTC date (the local date is the 17th).
    card = make_card_row(expiration_date=date(2026, 6, 17))
    use_case, repository = make_use_case(
        classify_responses(
            call_reason_transactions=[declined], call_reason_cards=[card]
        )
    )

    result = use_case.execute(CUSTOMER_ID, as_of)

    assert _summary(result) == [(R.DECLINED_TRANSACTION, Decimal("0.34"), "TRX-D")]
    assert result.as_of_date == date(2026, 6, 18)
    assert repository.calls[0][1]["as_of"] == as_of_utc
    assert repository.calls[2][1]["as_of"] == as_of_utc


def test_unknown_customer_gets_no_reasons() -> None:
    use_case, _ = make_use_case({})

    assert use_case.execute("CLI-NOBODY", AS_OF) == CallClassification(
        reasons=(), unavailable=(), as_of_date=TODAY
    )


def test_the_top_three_are_kept() -> None:
    brazil = make_transaction_row(
        transaction_id="TRX-A",
        transaction_date=AS_OF_SQL - timedelta(hours=2),
        transaction_country="Brasil",
    )
    declined = make_transaction_row(
        transaction_id="TRX-B",
        transaction_date=AS_OF_SQL - timedelta(hours=1),
        transaction_status="Declined",
        fraud_score=None,
    )
    use_case, _ = make_use_case(
        classify_responses(
            call_reason_transactions=[declined, brazil],
            call_reason_cases=[make_case_row(sla_breached=True)],
            call_reason_app_events=[make_app_event_row()],
        )
    )

    result = use_case.execute(CUSTOMER_ID, AS_OF)

    # FAILED_APP_ACTION (0.58) and FOREIGN_TRANSACTION (0.53) are cut.
    assert _summary(result) == [
        (R.FRAUD_SUSPECTED, Decimal("0.95"), "TRX-A"),
        (R.DECLINED_TRANSACTION, Decimal("0.84"), "TRX-B"),
        (R.OPEN_CASE_FOLLOWUP, Decimal("0.75"), "CMP-FHCLR8TGWMBD0YFOCLYS"),
    ]


def test_rows_are_mapped_to_candidates() -> None:
    card = make_card_row(card_last4="7718", product_status="Blocked")
    case = make_case_row()
    event = make_app_event_row()
    use_case, _ = make_use_case(
        classify_responses(
            call_reason_transactions=[],
            call_reason_cards=[card],
            call_reason_cases=[case],
            call_reason_app_events=[event],
        )
    )

    result = use_case.execute(CUSTOMER_ID, AS_OF)

    assert [item.candidate for item in result.reasons] == [
        CaseCandidate(
            complaint_id="CMP-FHCLR8TGWMBD0YFOCLYS",
            case_type="Claim",
            category="Cards",
            subcategory="Unrecognized charge",
            status="In Progress",
            sla_breached=None,
            days_open=12,
            creation_date=AS_OF_SQL - timedelta(days=12),
        ),
        CardCandidate(
            card_last4="7718",
            product_status="Blocked",
            expiration_date=date(2029, 8, 31),
            days_past_due=0,
        ),
        AppEventCandidate(
            event_id="EVT-0001",
            event_date=AS_OF_SQL - timedelta(hours=2),
            page_title="Pagar Servicios",
            action="submit_payment",
        ),
    ]


# --- a failing source --------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("call_reason_transactions", TRANSACTION_REASONS),
        ("call_reason_cards", CARD_REASONS),
        ("call_reason_cases", (R.OPEN_CASE_FOLLOWUP,)),
        ("call_reason_app_events", (R.FAILED_APP_ACTION,)),
    ],
)
def test_a_failed_source_lists_its_reasons_in_enum_order(
    query: str, expected: tuple[CallReason, ...]
) -> None:
    use_case, _ = make_use_case(
        classify_responses(**{query: QueryExecutionError("boom")})
    )

    result = use_case.execute(CUSTOMER_ID, AS_OF)

    assert result.unavailable == tuple(r for r in CallReason if r in expected)


@pytest.mark.parametrize(
    "error",
    [
        DataSourceConnectionError("down"),
        QueryExecutionError("boom"),
        QueryLimitExceededError("too big"),
    ],
)
def test_the_other_sources_are_still_ranked(
    error: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    use_case, repository = make_use_case(classify_responses(call_reason_cards=error))

    result = use_case.execute(CUSTOMER_ID, AS_OF)

    assert result.reasons == (P07_FRAUD,)
    assert result.unavailable == CARD_REASONS
    assert repository.queries == list(QUERY_NAMES.values())
    assert "classify_call_type source cards unavailable" in caplog.text


def test_unavailable_merges_sources_in_enum_order() -> None:
    use_case, _ = make_use_case(
        classify_responses(
            call_reason_transactions=QueryExecutionError("boom"),
            call_reason_cards=QueryExecutionError("boom"),
        )
    )

    result = use_case.execute(CUSTOMER_ID, AS_OF)

    assert result.unavailable == (
        R.FRAUD_SUSPECTED,
        R.DECLINED_TRANSACTION,
        R.UNRECOGNIZED_CHARGE_REVIEW,
        R.PENDING_TRANSACTION,
        R.REVERSED_TRANSACTION,
        R.CARD_NOT_ACTIVE,
        R.FOREIGN_TRANSACTION,
        R.PAYMENT_OVERDUE,
        R.CARD_EXPIRING,
    )


def test_a_missing_query_makes_its_source_unavailable() -> None:
    provider = FakeQueryProvider({name: name for name in QUERY_NAMES.values()})
    del provider.queries["call_reason_app_events"]
    use_case, repository = make_use_case(query_provider=provider)

    result = use_case.execute(CUSTOMER_ID, AS_OF)

    assert result.reasons == (P07_FRAUD,)
    assert result.unavailable == (R.FAILED_APP_ACTION,)
    assert "call_reason_app_events" not in repository.queries


@pytest.mark.parametrize(
    ("query", "rows"),
    [
        pytest.param(
            "call_reason_transactions",
            [make_transaction_row(transaction_id=None)],
            id="null-transaction-id",
        ),
        pytest.param(
            "call_reason_transactions",
            [_without(make_transaction_row(), "home_country")],
            id="missing-column",
        ),
        pytest.param(
            "call_reason_transactions",
            [make_transaction_row(amount="288.69")],
            id="amount-text",
        ),
        pytest.param(
            "call_reason_transactions",
            [make_transaction_row(fraud_score=Decimal("NaN"))],
            id="score-nan",
        ),
        pytest.param(
            "call_reason_transactions",
            [make_transaction_row(transaction_date="2026-05-31")],
            id="date-text",
        ),
        pytest.param(
            "call_reason_cards", [make_card_row(card_last4=None)], id="null-last4"
        ),
        pytest.param(
            "call_reason_cards", [make_card_row(days_past_due=True)], id="dpd-bool"
        ),
        pytest.param(
            "call_reason_cases", [make_case_row(complaint_id=None)], id="null-case-id"
        ),
        pytest.param(
            "call_reason_cases", [make_case_row(sla_breached="yes")], id="sla-text"
        ),
        pytest.param(
            "call_reason_cases",
            [make_case_row(creation_date="2026-06-05")],
            id="case-date-text",
        ),
        pytest.param(
            "call_reason_app_events",
            [make_app_event_row(event_id=None)],
            id="null-event-id",
        ),
    ],
)
def test_a_bad_row_makes_its_source_unavailable(
    query: str, rows: list[dict[str, Any]]
) -> None:
    use_case, _ = make_use_case(classify_responses(**{query: rows}))

    result = use_case.execute(CUSTOMER_ID, AS_OF)

    failed = next(source for source, name in QUERY_NAMES.items() if name == query)
    assert result.unavailable == tuple(
        reason for reason in CallReason if reason in _reasons_of(failed)
    )


def test_a_transaction_without_a_card_last4_still_maps() -> None:
    use_case, _ = make_use_case(
        classify_responses(
            call_reason_transactions=[make_transaction_row(card_last4=None)]
        )
    )

    result = use_case.execute(CUSTOMER_ID, AS_OF)

    assert result.unavailable == ()
    assert result.reasons[0].candidate == replace(P07_CANDIDATE, card_last4=None)


def _reasons_of(source: Source) -> tuple[CallReason, ...]:
    return {
        Source.TRANSACTIONS: TRANSACTION_REASONS,
        Source.CARDS: CARD_REASONS,
        Source.CASES: (R.OPEN_CASE_FOLLOWUP,),
        Source.APP_EVENTS: (R.FAILED_APP_ACTION,),
    }[source]


# --- all four failing ---------------------------------------------------------


def test_all_four_failing_with_a_connection_error_is_unavailable() -> None:
    responses: dict[str, Outcome] = {
        "call_reason_transactions": QueryExecutionError("boom"),
        "call_reason_cards": DataSourceConnectionError("down"),
        "call_reason_cases": QueryExecutionError("boom"),
        "call_reason_app_events": QueryLimitExceededError("too big"),
    }
    use_case, repository = make_use_case(responses)

    with pytest.raises(DataSourceUnavailableError) as caught:
        use_case.execute(CUSTOMER_ID, AS_OF)

    assert isinstance(caught.value.__cause__, DataSourceConnectionError)
    assert repository.queries == list(QUERY_NAMES.values())


@pytest.mark.parametrize(
    "responses",
    [
        pytest.param(
            {name: QueryExecutionError("boom") for name in QUERY_NAMES.values()},
            id="query-errors",
        ),
        pytest.param(
            {
                "call_reason_transactions": [make_transaction_row(transaction_id=None)],
                "call_reason_cards": [make_card_row(card_last4=None)],
                "call_reason_cases": [make_case_row(complaint_id=None)],
                "call_reason_app_events": [make_app_event_row(event_id=None)],
            },
            id="bad-rows",
        ),
    ],
)
def test_all_four_failing_without_a_connection_error_is_a_lookup_error(
    responses: dict[str, Outcome],
) -> None:
    use_case, _ = make_use_case(responses)

    with pytest.raises(CallReasonLookupError):
        use_case.execute(CUSTOMER_ID, AS_OF)


# --- the transaction cap ------------------------------------------------------


def _quiet_rows(count: int) -> list[dict[str, Any]]:
    """Approved, domestic, unscored charges, newest first: they trigger nothing."""
    return [
        make_transaction_row(
            transaction_id=f"TRX-{index:04d}",
            transaction_date=AS_OF_SQL - timedelta(minutes=index),
            fraud_score=None,
        )
        for index in range(count)
    ]


def test_more_than_the_cap_logs_and_ranks_every_row(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    oldest = make_transaction_row(
        transaction_id="TRX-OLDEST",
        transaction_date=AS_OF_SQL - timedelta(hours=10),
        transaction_status="Declined",
        fraud_score=None,
    )
    use_case, _ = make_use_case(
        classify_responses(call_reason_transactions=[*_quiet_rows(200), oldest])
    )

    result = use_case.execute(CUSTOMER_ID, AS_OF)

    assert _summary(result) == [
        (R.DECLINED_TRANSACTION, Decimal("0.75"), "TRX-OLDEST"),
    ]
    assert "classify_call_type transactions returned 201 rows" in caplog.text


def test_the_cap_itself_does_not_log(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    use_case, _ = make_use_case(
        classify_responses(call_reason_transactions=_quiet_rows(200))
    )

    use_case.execute(CUSTOMER_ID, AS_OF)

    assert caplog.records == []
