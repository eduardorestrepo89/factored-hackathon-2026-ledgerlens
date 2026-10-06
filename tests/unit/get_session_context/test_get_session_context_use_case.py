"""Tests for the get_session_context use case."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from get_session_context_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
    QueryNotFoundError,
)
from get_session_context_lambda.application.use_cases.get_session_context import (
    PROFILE_QUERY_NAME,
    SECTION_QUERY_NAMES,
    GetSessionContextUseCase,
)
from get_session_context_lambda.domain.entities.session_context import (
    CreditCard,
    Customer,
    DigitalSignal,
    OpenCase,
    RecentTransaction,
    Section,
    SessionContext,
    TransactionFlag,
)
from get_session_context_lambda.domain.errors import (
    CustomerNotFoundError,
    DataSourceUnavailableError,
    DomainError,
    InvalidInputError,
    SessionContextDataIntegrityError,
    SessionContextLookupError,
)

from .fakes import (
    CUSTOMER_ID,
    QUERY_NAMES,
    FakeQueryProvider,
    FakeSessionRepository,
    Outcome,
    make_card_row,
    make_case_row,
    make_profile_row,
    make_signal_row,
    make_transaction_row,
    session_responses,
)

pytestmark = pytest.mark.unit

AS_OF = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
# What the SQL receives: the same instant as naive UTC.
AS_OF_SQL = datetime(2026, 3, 14, 12, 0)
INVALID_CUSTOMER_ID = (
    "Invalid value for 'customer_id': is required and must be a non-empty "
    "string. Ask the customer to confirm and retry."
)
SECTION_ERRORS = [
    DataSourceConnectionError("connection refused"),
    QueryExecutionError("function percentile_cont is not supported"),
    QueryLimitExceededError("statement timeout"),
    QueryNotFoundError("no query named 'session_open_cases'"),
]


def make_use_case(
    responses: dict[str, Outcome] | None = None, max_rows: int = 25
) -> tuple[GetSessionContextUseCase, FakeSessionRepository]:
    """Build the use case over a fake repository; default: one row per query."""
    database_repository = FakeSessionRepository(
        session_responses() if responses is None else responses
    )
    use_case = GetSessionContextUseCase(
        database_repository=database_repository,
        query_provider=FakeQueryProvider(),
        max_rows=max_rows,
    )
    return use_case, database_repository


def section_items(context: SessionContext, section: Section) -> Any:
    """Return the section's tuple, or None when it's unavailable."""
    return getattr(context, section.value)


def warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return the text of every warning the use case logged."""
    return [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]


def test_execute_returns_the_full_snapshot() -> None:
    use_case, _ = make_use_case()

    context = use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert context == SessionContext(
        as_of=AS_OF,
        customer=Customer(
            customer_id=CUSTOMER_ID,
            first_name="Ana",
            country="Colombia",
            city="Bogotá",
            customer_status="Active",
        ),
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
        recent_transactions=(
            RecentTransaction(
                transaction_id="TX-1",
                transaction_date=datetime(2026, 3, 14, 10, 42),
                card_last4="4821",
                merchant_name="EXITO",
                amount=Decimal("350000.00"),
                currency="COP",
                transaction_status="Declined",
                transaction_country="Colombia",
                flags=(TransactionFlag.DECLINED, TransactionFlag.ABOVE_USUAL_AMOUNT),
            ),
        ),
        digital_signals=(
            DigitalSignal(
                event_date=datetime(2026, 3, 14, 10, 48),
                signal="FAILED_ACTION",
                page_title="Tarjeta de Crédito",
                ip_country="Colombia",
                ip_city="Bogotá",
            ),
        ),
        open_cases=(
            OpenCase(
                complaint_id="C-1182",
                case_type="Claim",
                category="Transactions",
                subcategory="Cargo no reconocido",
                status="Open",
                priority="High",
                sla_breached=False,
                claimed_amount=Decimal("350000.00"),
                currency="COP",
                days_open=3,
            ),
        ),
        truncated=(),
        unavailable=(),
    )


def test_query_names_follow_the_sections() -> None:
    assert PROFILE_QUERY_NAME == "session_customer_profile"
    assert (PROFILE_QUERY_NAME, *SECTION_QUERY_NAMES.values()) == QUERY_NAMES
    assert list(SECTION_QUERY_NAMES) == list(Section)


def test_queries_run_one_after_another_in_section_order() -> None:
    use_case, database_repository = make_use_case()

    use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert database_repository.queries == list(QUERY_NAMES)


def test_each_query_gets_exactly_its_params() -> None:
    use_case, database_repository = make_use_case()

    use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert dict(database_repository.calls) == {
        "session_customer_profile": {"customer_id": CUSTOMER_ID},
        "session_credit_cards": {"customer_id": CUSTOMER_ID, "limit": 26},
        "session_recent_transactions": {
            "customer_id": CUSTOMER_ID,
            "as_of": AS_OF_SQL,
            "limit": 26,
        },
        "session_digital_signals": {
            "customer_id": CUSTOMER_ID,
            "as_of": AS_OF_SQL,
            "limit": 26,
        },
        "session_open_cases": {
            "customer_id": CUSTOMER_ID,
            "as_of": AS_OF_SQL,
            "limit": 6,
        },
    }


def test_an_aware_as_of_in_another_zone_is_sent_as_naive_utc() -> None:
    use_case, database_repository = make_use_case()
    bogota = timezone(timedelta(hours=-5))

    context = use_case.execute(
        CUSTOMER_ID, as_of=datetime(2026, 3, 14, 7, 0, tzinfo=bogota)
    )

    sent = [
        params["as_of"] for _q, params in database_repository.calls if "as_of" in params
    ]
    assert len(sent) == 3
    for as_of in sent:
        assert as_of == AS_OF_SQL
        assert as_of.tzinfo is None
    assert context.as_of == AS_OF
    assert context.as_of.tzinfo == timezone.utc


def test_a_naive_as_of_is_rejected_before_any_query() -> None:
    use_case, database_repository = make_use_case()

    with pytest.raises(ValueError, match="aware"):
        use_case.execute(CUSTOMER_ID, as_of=AS_OF_SQL)

    assert database_repository.calls == []


def test_customer_id_is_stripped_and_uppercased() -> None:
    use_case, database_repository = make_use_case()

    use_case.execute("  cli-itiecue8prh9 ", as_of=AS_OF)

    assert {params["customer_id"] for _q, params in database_repository.calls} == {
        CUSTOMER_ID
    }


@pytest.mark.parametrize("customer_id", [None, "", "   ", 42, True, ["CLI-1"]])
def test_invalid_customer_id_is_rejected_before_any_query(customer_id: object) -> None:
    use_case, database_repository = make_use_case()

    with pytest.raises(InvalidInputError) as raised:
        use_case.execute(customer_id, as_of=AS_OF)

    assert raised.value.message == INVALID_CUSTOMER_ID
    assert database_repository.calls == []


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (DataSourceConnectionError("connection refused"), DataSourceUnavailableError),
        (QueryExecutionError("relation does not exist"), SessionContextLookupError),
        (QueryLimitExceededError("statement timeout"), SessionContextLookupError),
        (QueryNotFoundError("no query"), SessionContextLookupError),
    ],
)
def test_a_customer_section_failure_fails_the_call_and_stops(
    error: DataAccessError, expected: type[DomainError]
) -> None:
    use_case, database_repository = make_use_case(
        session_responses(session_customer_profile=error)
    )

    with pytest.raises(expected) as raised:
        use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert raised.value.__cause__ is error
    assert database_repository.queries == ["session_customer_profile"]


def test_a_missing_profile_query_is_a_lookup_error() -> None:
    database_repository = FakeSessionRepository(session_responses())
    use_case = GetSessionContextUseCase(
        database_repository=database_repository,
        query_provider=FakeQueryProvider({"session_credit_cards": "x"}),
    )

    with pytest.raises(SessionContextLookupError):
        use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert database_repository.calls == []


def test_no_customer_row_is_customer_not_found() -> None:
    use_case, database_repository = make_use_case(
        session_responses(session_customer_profile=[])
    )

    with pytest.raises(CustomerNotFoundError):
        use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert database_repository.queries == ["session_customer_profile"]


@pytest.mark.parametrize(
    "row",
    [make_profile_row(customer_id=None), {"customer_id": CUSTOMER_ID}],
    ids=["null-customer-id", "missing-columns"],
)
def test_an_unmappable_customer_row_is_a_data_integrity_error(
    row: dict[str, Any],
) -> None:
    use_case, database_repository = make_use_case(
        session_responses(session_customer_profile=[row])
    )

    with pytest.raises(SessionContextDataIntegrityError):
        use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert database_repository.queries == ["session_customer_profile"]


@pytest.mark.parametrize("error", SECTION_ERRORS, ids=lambda e: type(e).__name__)
@pytest.mark.parametrize("section", list(Section), ids=lambda s: s.value)
def test_a_failed_section_is_none_and_listed_unavailable(
    section: Section, error: DataAccessError, caplog: pytest.LogCaptureFixture
) -> None:
    use_case, database_repository = make_use_case(
        session_responses(**{SECTION_QUERY_NAMES[section]: error})
    )

    context = use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert section_items(context, section) is None
    assert context.unavailable == (section,)
    assert context.truncated == ()
    for other in Section:
        if other is not section:
            assert len(section_items(context, other)) == 1
    assert database_repository.queries == list(QUERY_NAMES)
    assert warnings(caplog) == [
        f"get_session_context section {section.value} unavailable"
    ]


@pytest.mark.parametrize(
    ("section", "bad_row"),
    [
        (Section.CARDS, make_card_row(current_balance="lots")),
        (
            Section.RECENT_TRANSACTIONS,
            make_transaction_row(transaction_date="yesterday"),
        ),
        (Section.DIGITAL_SIGNALS, make_signal_row(signal=None)),
        (Section.OPEN_CASES, make_case_row(days_open=True)),
    ],
    ids=lambda value: value.value if isinstance(value, Section) else "",
)
def test_an_unmappable_row_makes_only_its_section_unavailable(
    section: Section, bad_row: dict[str, Any]
) -> None:
    use_case, _ = make_use_case(
        session_responses(**{SECTION_QUERY_NAMES[section]: [bad_row]})
    )

    context = use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert section_items(context, section) is None
    assert context.unavailable == (section,)
    for other in Section:
        if other is not section:
            assert len(section_items(context, other)) == 1


def test_all_four_sections_failing_are_listed_in_order(
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = QueryExecutionError("boom")
    use_case, _ = make_use_case(
        session_responses(**{name: error for name in SECTION_QUERY_NAMES.values()})
    )

    context = use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert context.customer.customer_id == CUSTOMER_ID
    assert context.unavailable == tuple(Section)
    assert [section_items(context, s) for s in Section] == [None] * 4
    assert warnings(caplog) == [
        f"get_session_context section {s.value} unavailable" for s in Section
    ]


def test_empty_sections_are_empty_tuples_not_unavailable() -> None:
    use_case, _ = make_use_case(
        session_responses(**{name: [] for name in SECTION_QUERY_NAMES.values()})
    )

    context = use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert [section_items(context, s) for s in Section] == [(), (), (), ()]
    assert context.unavailable == ()
    assert context.truncated == ()


def responses_with(
    cards: int, transactions: int, signals: int, cases: int
) -> dict[str, Outcome]:
    """Return session responses with the given number of rows per section."""
    return session_responses(
        session_credit_cards=[make_card_row() for _ in range(cards)],
        session_recent_transactions=[
            make_transaction_row() for _ in range(transactions)
        ],
        session_digital_signals=[make_signal_row() for _ in range(signals)],
        session_open_cases=[make_case_row() for _ in range(cases)],
    )


def test_each_list_is_capped_and_marked_truncated() -> None:
    use_case, _ = make_use_case(responses_with(26, 26, 26, 6))

    context = use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert [len(section_items(context, s)) for s in Section] == [25, 25, 25, 5]
    assert context.truncated == tuple(Section)
    assert context.unavailable == ()


def test_exactly_the_cap_is_not_truncated() -> None:
    use_case, _ = make_use_case(responses_with(25, 25, 25, 5))

    context = use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert [len(section_items(context, s)) for s in Section] == [25, 25, 25, 5]
    assert context.truncated == ()


def test_max_rows_below_five_caps_open_cases() -> None:
    use_case, database_repository = make_use_case(
        responses_with(4, 4, 4, 4), max_rows=3
    )

    context = use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert [len(section_items(context, s)) for s in Section] == [3, 3, 3, 3]
    assert context.truncated == tuple(Section)
    limits = {q: p["limit"] for q, p in database_repository.calls if "limit" in p}
    assert limits == {name: 4 for name in SECTION_QUERY_NAMES.values()}


@pytest.mark.parametrize("max_rows", [0, -1])
def test_max_rows_below_one_is_rejected(max_rows: int) -> None:
    with pytest.raises(ValueError, match="max_rows"):
        GetSessionContextUseCase(
            database_repository=FakeSessionRepository(),
            query_provider=FakeQueryProvider(),
            max_rows=max_rows,
        )


def transaction_with(**flags: object) -> RecentTransaction:
    """Run the use case on one transaction row with the given flag columns."""
    use_case, _ = make_use_case(
        session_responses(session_recent_transactions=[make_transaction_row(**flags)])
    )
    transactions = use_case.execute(CUSTOMER_ID, as_of=AS_OF).recent_transactions
    assert transactions is not None
    return transactions[0]


@pytest.mark.parametrize("flag", list(TransactionFlag), ids=lambda f: f.value)
def test_each_flag_maps_from_its_column(flag: TransactionFlag) -> None:
    columns = {f"is_{f.value}": f is flag for f in TransactionFlag}

    assert transaction_with(**columns).flags == (flag,)


def test_all_flags_come_in_enum_order() -> None:
    columns = {f"is_{f.value}": True for f in TransactionFlag}

    assert transaction_with(**columns).flags == tuple(TransactionFlag)


def test_null_flags_mean_not_flagged() -> None:
    columns = {f"is_{f.value}": None for f in TransactionFlag}

    assert transaction_with(**columns).flags == ()


def test_a_non_bool_flag_makes_only_transactions_unavailable() -> None:
    use_case, _ = make_use_case(
        session_responses(
            session_recent_transactions=[make_transaction_row(is_foreign=1)]
        )
    )

    context = use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert context.recent_transactions is None
    assert context.unavailable == (Section.RECENT_TRANSACTIONS,)
    assert context.cards is not None and len(context.cards) == 1


def test_null_values_stay_none() -> None:
    use_case, _ = make_use_case(
        session_responses(
            session_customer_profile=[make_profile_row(first_name=None, city=None)],
            session_open_cases=[
                make_case_row(sla_breached=None, claimed_amount=None, days_open=None)
            ],
        )
    )

    context = use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert context.customer.first_name is None
    assert context.customer.city is None
    assert context.open_cases is not None
    case = context.open_cases[0]
    assert (case.sla_breached, case.claimed_amount, case.days_open) == (
        None,
        None,
        None,
    )


def test_a_timestamp_expiration_date_keeps_only_the_date() -> None:
    use_case, _ = make_use_case(
        session_responses(
            session_credit_cards=[make_card_row(expiration_date=datetime(2027, 3, 31))]
        )
    )

    cards = use_case.execute(CUSTOMER_ID, as_of=AS_OF).cards

    assert cards is not None
    assert cards[0].expiration_date == date(2027, 3, 31)
