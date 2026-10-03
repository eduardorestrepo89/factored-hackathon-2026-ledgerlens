"""Tests for ExplainTransactionUseCase (spec sections 3.4 and 4)."""

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from explain_transaction_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
    QueryNotFoundError,
)
from explain_transaction_lambda.application.use_cases.explain_transaction import (
    ExplainTransactionUseCase,
)
from explain_transaction_lambda.domain.entities.transaction_explanation import (
    AppActivity,
    DeclineInfo,
    ExplainedTransaction,
    FxConversion,
    Section,
    SpendingHabit,
    TransactionExplanation,
    UsualAmountRange,
)
from explain_transaction_lambda.domain.errors import (
    DataSourceUnavailableError,
    DomainError,
    ExplainDataIntegrityError,
    ExplainLookupError,
    InvalidInputError,
    TransactionNotFoundError,
)

from .fakes import (
    CHARGE_DATE,
    CUSTOMER_ID,
    PRODUCT_ID,
    TRANSACTION_ID,
    FakeExplainRepository,
    FakeQueryProvider,
    Outcome,
    explain_responses,
    make_app_activity_row,
    make_core_row,
    make_habit_row,
)

pytestmark = pytest.mark.unit

AS_OF = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
AS_OF_SQL = datetime(2026, 6, 17, 23, 59, 59)

P07_TRANSACTION = ExplainedTransaction(
    transaction_id=TRANSACTION_ID,
    transaction_date=CHARGE_DATE,
    card_last4="4497",
    merchant_name="Estación de Servicio",
    merchant_category="Transport",
    amount=Decimal("288.69"),
    currency="USD",
    channel="Web",
    transaction_city="Ciudad de México",
    transaction_country="México",
    transaction_status="Approved",
)
P07_HABIT = SpendingHabit(
    history_count=1,
    times_at_merchant_90d=0,
    usual_amount_range=None,
    country_seen_before=True,
)


def make_use_case(
    responses: dict[str, Outcome] | None = None,
) -> tuple[ExplainTransactionUseCase, FakeExplainRepository]:
    """Wire the use case to fakes; by default they answer P07's charge."""
    database_repository = FakeExplainRepository(
        explain_responses() if responses is None else responses
    )
    use_case = ExplainTransactionUseCase(
        database_repository=database_repository,
        query_provider=FakeQueryProvider(),
    )
    return use_case, database_repository


def explain(**overrides: Outcome) -> TransactionExplanation:
    """Explain P07's charge with some query outcomes replaced."""
    use_case, _ = make_use_case(explain_responses(**overrides))
    return use_case.execute(CUSTOMER_ID, TRANSACTION_ID, as_of=AS_OF)


def core(**overrides: Any) -> dict[str, list[dict[str, Any]]]:
    """Return a core-query override with some columns replaced."""
    return {"explain_transaction": [make_core_row(**overrides)]}


# --- the whole call -------------------------------------------------------------


def test_p07_charge_is_explained() -> None:
    assert explain() == TransactionExplanation(
        transaction=P07_TRANSACTION,
        fx=None,
        decline=None,
        habit=P07_HABIT,
        app_activity=AppActivity(found=False),
        unavailable=(),
    )


def test_queries_run_in_order_with_their_params() -> None:
    use_case, database_repository = make_use_case()

    use_case.execute(CUSTOMER_ID, TRANSACTION_ID, as_of=AS_OF)

    assert database_repository.calls == [
        (
            "explain_transaction",
            {
                "customer_id": CUSTOMER_ID,
                "transaction_id": TRANSACTION_ID,
                "as_of": AS_OF_SQL,
            },
        ),
        (
            "transaction_habit",
            {
                "customer_id": CUSTOMER_ID,
                "product_id": PRODUCT_ID,
                "transaction_id": TRANSACTION_ID,
                "charge_date": CHARGE_DATE,
                "merchant_name": "Estación de Servicio",
                "currency": "USD",
                "transaction_country": "México",
            },
        ),
        (
            "transaction_app_activity",
            {
                "customer_id": CUSTOMER_ID,
                "charge_date": CHARGE_DATE,
                "as_of": AS_OF_SQL,
            },
        ),
    ]


def test_ids_are_stripped_and_uppercased() -> None:
    use_case, database_repository = make_use_case()

    use_case.execute(" cli-ex6boaoefzhq ", " trx-23bijau4gl46atpw9sty ", as_of=AS_OF)

    _query, params = database_repository.calls[0]
    assert params["customer_id"] == CUSTOMER_ID
    assert params["transaction_id"] == TRANSACTION_ID


def test_as_of_is_sent_as_naive_utc() -> None:
    use_case, database_repository = make_use_case()
    bogota = timezone(timedelta(hours=-5))

    use_case.execute(
        CUSTOMER_ID,
        TRANSACTION_ID,
        as_of=datetime(2026, 6, 17, 18, 59, 59, tzinfo=bogota),
    )

    assert database_repository.calls[0][1]["as_of"] == AS_OF_SQL
    assert database_repository.calls[2][1]["as_of"] == AS_OF_SQL


def test_naive_as_of_is_rejected_before_any_query() -> None:
    use_case, database_repository = make_use_case()

    with pytest.raises(ValueError, match="aware"):
        use_case.execute(CUSTOMER_ID, TRANSACTION_ID, as_of=AS_OF_SQL)
    assert database_repository.calls == []


# --- input validation -------------------------------------------------------------


@pytest.mark.parametrize("bad", [None, "", "   ", 42, True, ["CLI-1"]])
def test_bad_customer_id_is_rejected_before_any_query(bad: object) -> None:
    use_case, database_repository = make_use_case()

    with pytest.raises(InvalidInputError) as caught:
        use_case.execute(bad, TRANSACTION_ID, as_of=AS_OF)

    assert caught.value.field == "customer_id"
    assert database_repository.calls == []


@pytest.mark.parametrize("bad", [None, "", "   ", 42, True, ["TRX-1"]])
def test_bad_transaction_id_is_rejected_before_any_query(bad: object) -> None:
    use_case, database_repository = make_use_case()

    with pytest.raises(InvalidInputError) as caught:
        use_case.execute(CUSTOMER_ID, bad, as_of=AS_OF)

    assert caught.value.field == "transaction_id"
    assert caught.value.reason == "is required and must be a non-empty string"
    assert database_repository.calls == []


def test_customer_id_is_checked_before_transaction_id() -> None:
    use_case, _ = make_use_case()

    with pytest.raises(InvalidInputError) as caught:
        use_case.execute(None, None, as_of=AS_OF)

    assert caught.value.field == "customer_id"


# --- core failures --------------------------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (DataSourceConnectionError("down"), DataSourceUnavailableError),
        (QueryExecutionError("syntax"), ExplainLookupError),
        (QueryLimitExceededError("too big"), ExplainLookupError),
        (QueryNotFoundError("missing"), ExplainLookupError),
        ([], TransactionNotFoundError),
        ([make_core_row(transaction_id=None)], ExplainDataIntegrityError),
        ([make_core_row(product_id=None)], ExplainDataIntegrityError),
        ([make_core_row(amount="288.69")], ExplainDataIntegrityError),
        ([make_core_row(transaction_date="2026-05-31")], ExplainDataIntegrityError),
        ([{"transaction_id": TRANSACTION_ID}], ExplainDataIntegrityError),
    ],
    ids=[
        "unavailable",
        "execution",
        "limit",
        "missing-query",
        "not-found",
        "null-id",
        "null-product",
        "text-amount",
        "text-date",
        "missing-columns",
    ],
)
def test_core_failure_fails_the_call_and_skips_the_sections(
    outcome: Outcome, expected: type[DomainError]
) -> None:
    use_case, database_repository = make_use_case(
        explain_responses(explain_transaction=outcome)
    )

    with pytest.raises(expected):
        use_case.execute(CUSTOMER_ID, TRANSACTION_ID, as_of=AS_OF)
    assert database_repository.queries == ["explain_transaction"]


def test_missing_core_sql_is_a_lookup_error() -> None:
    use_case = ExplainTransactionUseCase(
        database_repository=FakeExplainRepository(explain_responses()),
        query_provider=FakeQueryProvider({}),
    )

    with pytest.raises(ExplainLookupError):
        use_case.execute(CUSTOMER_ID, TRANSACTION_ID, as_of=AS_OF)


# --- fx ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("columns", "expected"),
    [
        ({}, None),
        ({"currency": None}, None),
        ({"card_currency": None}, None),
        (
            {
                "currency": "COP",
                "amount": Decimal("400000.00"),
                "fx_sell_rate": Decimal("0.00025"),
            },
            FxConversion(
                "USD", date(2026, 5, 31), Decimal("0.00025"), Decimal("100.00")
            ),
        ),
        (
            {"currency": "COP", "fx_sell_rate": None},
            FxConversion("USD", date(2026, 5, 31), None, None),
        ),
        (
            {"currency": "COP", "amount": None, "fx_sell_rate": Decimal("0.00025")},
            FxConversion("USD", date(2026, 5, 31), Decimal("0.00025"), None),
        ),
        (
            {
                "currency": "COP",
                "amount": Decimal("10.00"),
                "fx_sell_rate": Decimal("0.0005"),
            },
            FxConversion("USD", date(2026, 5, 31), Decimal("0.0005"), Decimal("0.01")),
        ),
    ],
    ids=[
        "same-currency",
        "no-charge-currency",
        "no-card-currency",
        "converted",
        "no-rate",
        "no-amount",
        "half-up",
    ],
)
def test_fx_rules(columns: dict[str, Any], expected: FxConversion | None) -> None:
    assert explain(**core(**columns)).fx == expected


# --- decline ---------------------------------------------------------------------


@pytest.mark.parametrize("status", ["Approved", "Pending", "Reversed", None])
def test_decline_is_only_for_declined_charges(status: str | None) -> None:
    result = explain(**core(transaction_status=status, response_code="54"))

    assert result.decline is None


@pytest.mark.parametrize(
    ("code", "meaning"),
    [
        ("05", "declined by the issuer, no specific reason"),
        ("14", "invalid card number"),
        ("51", "insufficient available credit"),
        ("99", None),
        (None, None),
    ],
)
def test_decline_meaning_per_code(code: str | None, meaning: str | None) -> None:
    result = explain(**core(transaction_status="Declined", response_code=code))

    assert result.decline == DeclineInfo(
        response_code=code, meaning=meaning, contradicts_card_state=False
    )


@pytest.mark.parametrize(
    ("expiration", "expected"),
    [
        (date(2029, 1, 31), True),
        (date(2026, 5, 31), True),
        (date(2026, 5, 30), False),
        (None, None),
    ],
    ids=["valid-for-years", "expires-that-day", "already-expired", "no-expiration"],
)
def test_code_54_contradiction(expiration: date | None, expected: bool | None) -> None:
    result = explain(
        **core(
            transaction_status="Declined",
            response_code="54",
            card_expiration_date=expiration,
        )
    )

    assert result.decline == DeclineInfo(
        response_code="54", meaning="expired card", contradicts_card_state=expected
    )


def test_code_54_without_a_charge_date_is_unknown() -> None:
    result = explain(
        **core(transaction_status="Declined", response_code="54", transaction_date=None)
    )

    assert result.decline is not None
    assert result.decline.contradicts_card_state is None


# --- a charge without a date ------------------------------------------------------


def test_null_charge_date_skips_both_sections() -> None:
    use_case, database_repository = make_use_case(
        explain_responses(**core(transaction_date=None))
    )

    result = use_case.execute(CUSTOMER_ID, TRANSACTION_ID, as_of=AS_OF)

    assert result.transaction.transaction_date is None
    assert result.habit is None
    assert result.app_activity is None
    assert result.unavailable == (Section.HABIT, Section.APP_ACTIVITY)
    assert database_repository.queries == ["explain_transaction"]


# --- habit ------------------------------------------------------------------------


def test_habit_with_a_usual_range() -> None:
    habit_row = make_habit_row(
        history_count=12,
        times_at_merchant=3,
        same_currency_count=10,
        usual_low=Decimal("20.5"),
        usual_high=Decimal("310.25"),
        country_seen_before=False,
    )

    assert explain(transaction_habit=[habit_row]).habit == SpendingHabit(
        history_count=12,
        times_at_merchant_90d=3,
        usual_amount_range=UsualAmountRange(
            low=Decimal("20.5"), high=Decimal("310.25"), currency="USD"
        ),
        country_seen_before=False,
    )


@pytest.mark.parametrize(
    ("same_currency_count", "has_range"), [(0, False), (2, False), (3, True)]
)
def test_usual_range_needs_three_charges(
    same_currency_count: int, has_range: bool
) -> None:
    habit_row = make_habit_row(
        history_count=5,
        same_currency_count=same_currency_count,
        usual_low=Decimal("10"),
        usual_high=Decimal("90"),
    )

    habit = explain(transaction_habit=[habit_row]).habit

    assert habit is not None
    assert (habit.usual_amount_range is not None) is has_range


@pytest.mark.parametrize(
    "columns",
    [{"usual_low": None}, {"usual_high": None}],
    ids=["no-low", "no-high"],
)
def test_usual_range_needs_both_percentiles(columns: dict[str, Any]) -> None:
    habit_row = make_habit_row(
        same_currency_count=5,
        usual_low=Decimal("10"),
        usual_high=Decimal("90"),
    )
    habit_row.update(columns)

    habit = explain(transaction_habit=[habit_row]).habit

    assert habit is not None
    assert habit.usual_amount_range is None


def test_usual_range_needs_the_charge_currency() -> None:
    habit_row = make_habit_row(
        same_currency_count=5, usual_low=Decimal("10"), usual_high=Decimal("90")
    )

    result = explain(**core(currency=None), transaction_habit=[habit_row])

    assert result.habit is not None
    assert result.habit.usual_amount_range is None


def test_habit_keeps_its_nullable_fields() -> None:
    habit_row = make_habit_row(times_at_merchant=None, country_seen_before=None)

    assert explain(transaction_habit=[habit_row]).habit == SpendingHabit(
        history_count=1,
        times_at_merchant_90d=None,
        usual_amount_range=None,
        country_seen_before=None,
    )


@pytest.mark.parametrize(
    "outcome",
    [
        QueryExecutionError("translate() unsupported"),
        [],
        [make_habit_row(history_count=None)],
        [make_habit_row(history_count=True)],
        [make_habit_row(same_currency_count="3")],
        [make_habit_row(usual_low="cheap")],
        [{"history_count": 1}],
    ],
    ids=[
        "query-failed",
        "no-row",
        "null-count",
        "bool-count",
        "text-count",
        "text-low",
        "missing-columns",
    ],
)
def test_habit_failure_keeps_app_activity(
    outcome: Outcome, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    use_case, database_repository = make_use_case(
        explain_responses(
            transaction_habit=outcome,
            transaction_app_activity=[make_app_activity_row()],
        )
    )

    result = use_case.execute(CUSTOMER_ID, TRANSACTION_ID, as_of=AS_OF)

    assert result.habit is None
    assert result.app_activity is not None
    assert result.app_activity.found is True
    assert result.unavailable == (Section.HABIT,)
    assert database_repository.queries == [
        "explain_transaction",
        "transaction_habit",
        "transaction_app_activity",
    ]
    assert "explain_transaction section habit unavailable" in caplog.text


# --- app activity -----------------------------------------------------------------


def test_app_event_is_mapped() -> None:
    result = explain(transaction_app_activity=[make_app_activity_row()])

    assert result.app_activity == AppActivity(
        found=True,
        event_date=CHARGE_DATE + timedelta(minutes=12),
        minutes_from_charge=12,
        ip_country="México",
        ip_city="Ciudad de México",
        conflict=False,
    )
    assert result.unavailable == ()


@pytest.mark.parametrize("minutes", [-30, 0, 45, -120, 120])
def test_minutes_from_charge_is_negative_before_the_charge(minutes: int) -> None:
    event = make_app_activity_row(event_date=CHARGE_DATE + timedelta(minutes=minutes))

    app_activity = explain(transaction_app_activity=[event]).app_activity

    assert app_activity is not None
    assert app_activity.minutes_from_charge == minutes


@pytest.mark.parametrize(
    ("channel", "country", "ip_country", "expected"),
    [
        ("POS", "México", "Colombia", True),
        ("ATM", "México", "Colombia", True),
        ("Branch", "México", "Colombia", True),
        ("POS", "México", " MEXICO ", False),
        ("POS", "Perú", "PERU", False),
        ("App", "México", "Colombia", False),
        ("Web", "México", "Colombia", False),
        (None, "México", "Colombia", None),
        ("POS", None, "Colombia", None),
        ("POS", "México", None, None),
    ],
)
def test_conflict_rules(
    channel: str | None,
    country: str | None,
    ip_country: str | None,
    expected: bool | None,
) -> None:
    result = explain(
        **core(channel=channel, transaction_country=country),
        transaction_app_activity=[make_app_activity_row(ip_country=ip_country)],
    )

    assert result.app_activity is not None
    assert result.app_activity.conflict is expected


@pytest.mark.parametrize(
    "outcome",
    [
        QueryExecutionError("boom"),
        [make_app_activity_row(event_date=None)],
        [make_app_activity_row(event_date="2026-05-31T06:21:15")],
        [{"event_id": "EVT-1"}],
    ],
    ids=["query-failed", "null-date", "text-date", "missing-columns"],
)
def test_app_activity_failure_is_unavailable(outcome: Outcome) -> None:
    result = explain(transaction_app_activity=outcome)

    assert result.app_activity is None
    assert result.habit == P07_HABIT
    assert result.unavailable == (Section.APP_ACTIVITY,)


def test_both_sections_failing_are_listed_in_order() -> None:
    result = explain(
        transaction_habit=QueryExecutionError("a"),
        transaction_app_activity=QueryExecutionError("b"),
    )

    assert result.habit is None
    assert result.app_activity is None
    assert result.unavailable == (Section.HABIT, Section.APP_ACTIVITY)
