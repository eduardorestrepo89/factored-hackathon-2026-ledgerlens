"""Tests for detecting, scoring and ranking call reasons (spec section 3)."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from classify_call_type_lambda.domain.entities.candidates import (
    AppEventCandidate,
    CardCandidate,
    CaseCandidate,
    TransactionCandidate,
)
from classify_call_type_lambda.domain.services.reason_ranking import (
    card_reasons,
    rank,
    score,
    to_confidence,
    transaction_reasons,
)
from classify_call_type_lambda.domain.value_objects.call_reasons import (
    CallReason,
    Decay,
)

from .fakes import AS_OF_SQL, CHARGE_DATE, TRANSACTION_ID

pytestmark = pytest.mark.unit

AS = AS_OF_SQL
TODAY = AS.date()
R = CallReason


def _tx(age: timedelta = timedelta(hours=1), **overrides: Any) -> TransactionCandidate:
    """An approved, domestic, unscored charge ``age`` before AS: no reason."""
    fields: dict[str, Any] = {
        "transaction_id": "TRX-A",
        "transaction_date": AS - age,
        "card_last4": "4497",
        "card_currency": "USD",
        "merchant_name": "Tienda",
        "amount": Decimal("10.00"),
        "currency": "USD",
        "transaction_status": "Approved",
        "response_code": "00",
        "transaction_country": "México",
        "home_country": "México",
        "fraud_score": None,
    }
    fields.update(overrides)
    return TransactionCandidate(**fields)


def _card(**overrides: Any) -> CardCandidate:
    """An active card in good standing, far from expiring: no reason."""
    fields: dict[str, Any] = {
        "card_last4": "4497",
        "product_status": "Active",
        "expiration_date": date(2029, 8, 31),
        "days_past_due": 0,
    }
    fields.update(overrides)
    return CardCandidate(**fields)


def _case(**overrides: Any) -> CaseCandidate:
    """An open case whose SLA isn't breached."""
    fields: dict[str, Any] = {
        "complaint_id": "CMP-A",
        "case_type": "Claim",
        "category": "Cards",
        "subcategory": "Unrecognized charge",
        "status": "In Progress",
        "sla_breached": False,
        "days_open": 12,
        "creation_date": AS - timedelta(days=12),
    }
    fields.update(overrides)
    return CaseCandidate(**fields)


def _event(age: timedelta = timedelta(hours=2), **overrides: Any) -> AppEventCandidate:
    """An app error ``age`` before AS."""
    fields: dict[str, Any] = {
        "event_id": "EVT-A",
        "event_date": AS - age,
        "page_title": "Pagar Servicios",
        "action": "submit_payment",
    }
    fields.update(overrides)
    return AppEventCandidate(**fields)


def _rank(
    transactions: tuple[TransactionCandidate, ...] = (),
    cards: tuple[CardCandidate, ...] = (),
    cases: tuple[CaseCandidate, ...] = (),
    app_events: tuple[AppEventCandidate, ...] = (),
    limit: int = 3,
) -> list[tuple[CallReason, Decimal, str]]:
    ranked = rank(
        transactions=transactions,
        cards=cards,
        cases=cases,
        app_events=app_events,
        as_of=AS,
        limit=limit,
    )
    return [(item.reason, item.confidence, item.ref_id) for item in ranked]


# --- score and confidence ---------------------------------------------------


def test_score_decays_one_point_per_hour() -> None:
    event = AS - timedelta(hours=5, minutes=34, seconds=48)  # 5.58 h (P01)

    assert score(Decimal("85"), Decay.PER_HOUR, event, AS) == Decimal("79.42")


def test_score_decays_one_point_per_day() -> None:
    event = AS - timedelta(days=3)

    assert score(Decimal("70"), Decay.PER_DAY, event, AS) == Decimal("67")


def test_p07_age_is_fractional_days() -> None:
    result = score(Decimal("95"), Decay.PER_DAY, CHARGE_DATE, AS)

    assert result.quantize(Decimal("0.0001")) == Decimal("77.2564")
    assert to_confidence(result) == Decimal("0.77")


def test_score_floors_at_40_percent_of_the_weight() -> None:
    event = AS - timedelta(hours=50)

    assert score(Decimal("65"), Decay.PER_HOUR, event, AS) == Decimal("26.0")


def test_a_future_event_counts_as_age_zero() -> None:
    event = AS + timedelta(hours=1)

    assert score(Decimal("85"), Decay.PER_HOUR, event, AS) == Decimal("85")


def test_no_decay_scores_the_weight() -> None:
    assert score(Decimal("60"), Decay.NONE, None, AS) == Decimal("60")


def test_a_decaying_reason_needs_an_event_time() -> None:
    with pytest.raises(ValueError, match="event time"):
        score(Decimal("85"), Decay.PER_HOUR, None, AS)


def test_half_up_rounding_differs_from_half_even() -> None:
    result = score(Decimal("85"), Decay.PER_HOUR, AS - timedelta(hours=8.5), AS)

    assert result == Decimal("76.5")
    assert to_confidence(result) == Decimal("0.77")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("76.5", "0.77"), ("77.2564", "0.77"), ("26", "0.26"), ("60", "0.60")],
)
def test_confidence_is_score_over_100_with_2_decimals(
    value: str, expected: str
) -> None:
    confidence = to_confidence(Decimal(value))

    assert confidence == Decimal(expected)
    assert confidence.as_tuple().exponent == -2


# --- transaction rules ------------------------------------------------------

_H72 = timedelta(hours=72)
_D30 = timedelta(days=30)
_SECOND = timedelta(seconds=1)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param({"fraud_score": Decimal("62")}, (R.FRAUD_SUSPECTED,), id="fraud"),
        pytest.param(
            {"fraud_score": Decimal("50.01")}, (R.FRAUD_SUSPECTED,), id="50.01"
        ),
        pytest.param(
            {"fraud_score": Decimal("50.00")},
            (R.UNRECOGNIZED_CHARGE_REVIEW,),
            id="50.00",
        ),
        pytest.param(
            {"fraud_score": Decimal("30.01")},
            (R.UNRECOGNIZED_CHARGE_REVIEW,),
            id="30.01",
        ),
        pytest.param({"fraud_score": Decimal("30.00")}, (), id="30.00"),
        pytest.param({}, (), id="null-score-domestic"),
        pytest.param(
            {"transaction_country": "Brasil"},
            (R.FOREIGN_TRANSACTION,),
            id="null-score-abroad",
        ),
        pytest.param(
            {"transaction_status": "Declined", "fraud_score": Decimal("62")},
            (R.DECLINED_TRANSACTION,),
            id="declined-scored-62",
        ),
        pytest.param(
            {"transaction_status": "Pending"}, (R.PENDING_TRANSACTION,), id="pending"
        ),
        pytest.param(
            {"transaction_status": "Reversed"}, (R.REVERSED_TRANSACTION,), id="reversed"
        ),
        pytest.param({"transaction_status": None}, (), id="null-status"),
        pytest.param(
            {"transaction_status": "Declined", "age": _H72},
            (R.DECLINED_TRANSACTION,),
            id="declined-72h-in",
        ),
        pytest.param(
            {"transaction_status": "Declined", "age": _H72 + _SECOND},
            (),
            id="declined-72h-out",
        ),
        pytest.param(
            {"fraud_score": Decimal("62"), "age": _D30},
            (R.FRAUD_SUSPECTED,),
            id="fraud-30d-in",
        ),
        pytest.param(
            {"fraud_score": Decimal("62"), "age": _D30 + _SECOND},
            (),
            id="fraud-30d-out",
        ),
        pytest.param(
            {"fraud_score": Decimal("62"), "transaction_country": "Brasil"},
            (R.FRAUD_SUSPECTED, R.FOREIGN_TRANSACTION),
            id="fraud-and-foreign",
        ),
        pytest.param(
            {
                "fraud_score": Decimal("62"),
                "transaction_country": "Brasil",
                "age": _H72 + _SECOND,
            },
            (R.FRAUD_SUSPECTED,),
            id="foreign-window-shorter",
        ),
        pytest.param({"transaction_country": "Mexico"}, (), id="folded-country"),
        pytest.param({"currency": "EUR"}, (R.FOREIGN_TRANSACTION,), id="currency"),
        pytest.param({"transaction_country": None}, (), id="null-country"),
        pytest.param(
            {"transaction_country": "Brasil", "home_country": None},
            (),
            id="null-home",
        ),
        pytest.param({"transaction_country": "  "}, (), id="blank-country"),
        pytest.param({"currency": None}, (), id="null-currency"),
        pytest.param(
            {"transaction_status": "Declined", "transaction_country": "Brasil"},
            (R.DECLINED_TRANSACTION,),
            id="declined-abroad",
        ),
        pytest.param(
            {"fraud_score": Decimal("62"), "transaction_date": None},
            (),
            id="null-date",
        ),
        pytest.param(
            {"transaction_status": "Declined", "age": -_SECOND}, (), id="future"
        ),
    ],
)
def test_transaction_rules(
    overrides: dict[str, Any], expected: tuple[CallReason, ...]
) -> None:
    fields = dict(overrides)  # never mutate the shared parametrize dict
    age = fields.pop("age", timedelta(hours=1))

    assert transaction_reasons(_tx(age, **fields), AS) == expected


# --- card rules -------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param(
            {
                "product_status": "Blocked",
                "days_past_due": 180,
                "expiration_date": TODAY,
            },
            (R.CARD_NOT_ACTIVE,),
            id="blocked-only",
        ),
        pytest.param(
            {"product_status": "Suspended"}, (R.CARD_NOT_ACTIVE,), id="suspended"
        ),
        pytest.param(
            {"product_status": "Closed", "days_past_due": 30, "expiration_date": TODAY},
            (),
            id="closed",
        ),
        pytest.param({}, (), id="good-standing"),
        pytest.param({"days_past_due": 5}, (R.PAYMENT_OVERDUE,), id="overdue"),
        pytest.param({"days_past_due": 0}, (), id="dpd-0"),
        pytest.param({"days_past_due": None}, (), id="dpd-null"),
        pytest.param(
            {"expiration_date": TODAY}, (R.CARD_EXPIRING,), id="expires-today"
        ),
        pytest.param(
            {"expiration_date": TODAY - timedelta(days=1)}, (), id="expired-yesterday"
        ),
        pytest.param(
            {"expiration_date": TODAY + timedelta(days=30)},
            (R.CARD_EXPIRING,),
            id="expires-in-30",
        ),
        pytest.param(
            {"expiration_date": TODAY + timedelta(days=31)}, (), id="expires-in-31"
        ),
        pytest.param({"expiration_date": None}, (), id="null-expiration"),
        pytest.param(
            {"days_past_due": 10, "expiration_date": TODAY + timedelta(days=3)},
            (R.PAYMENT_OVERDUE, R.CARD_EXPIRING),
            id="overdue-and-expiring",
        ),
        pytest.param({"product_status": None}, (), id="null-status"),
    ],
)
def test_card_rules(
    overrides: dict[str, Any], expected: tuple[CallReason, ...]
) -> None:
    assert card_reasons(_card(**overrides), TODAY) == expected


# --- ranking ----------------------------------------------------------------


def test_empty_input_ranks_nothing() -> None:
    assert _rank() == []


def test_p07_charge_ranks_fraud_first_at_0_77() -> None:
    charge = _tx(
        transaction_id=TRANSACTION_ID,
        transaction_date=CHARGE_DATE,
        fraud_score=Decimal("62"),
    )

    ranked = rank(
        transactions=(charge,), cards=(), cases=(), app_events=(), as_of=AS, limit=3
    )

    assert len(ranked) == 1
    assert ranked[0].reason is R.FRAUD_SUSPECTED
    assert ranked[0].confidence == Decimal("0.77")
    assert ranked[0].ref_id == TRANSACTION_ID
    assert ranked[0].candidate is charge


def test_one_charge_can_be_two_reasons() -> None:
    charge = _tx(
        timedelta(hours=2), fraud_score=Decimal("62"), transaction_country="Brasil"
    )

    assert _rank(transactions=(charge,)) == [
        (R.FRAUD_SUSPECTED, Decimal("0.95"), "TRX-A"),
        (R.FOREIGN_TRANSACTION, Decimal("0.53"), "TRX-A"),
    ]


def test_only_the_top_limit_are_kept() -> None:
    brazil = _tx(
        timedelta(hours=2), fraud_score=Decimal("62"), transaction_country="Brasil"
    )
    declined = _tx(transaction_id="TRX-B", transaction_status="Declined")
    breached = _case(sla_breached=True)

    assert _rank(transactions=(brazil, declined), cases=(breached,)) == [
        (R.FRAUD_SUSPECTED, Decimal("0.95"), "TRX-A"),
        (R.DECLINED_TRANSACTION, Decimal("0.84"), "TRX-B"),
        (R.OPEN_CASE_FOLLOWUP, Decimal("0.75"), "CMP-A"),
    ]
    assert _rank(transactions=(brazil, declined), cases=(breached,), limit=1) == [
        (R.FRAUD_SUSPECTED, Decimal("0.95"), "TRX-A"),
    ]


def test_the_best_event_per_reason_has_the_highest_score() -> None:
    older = _tx(
        timedelta(hours=10), transaction_id="TRX-A", transaction_status="Declined"
    )
    newer = _tx(
        timedelta(hours=2), transaction_id="TRX-B", transaction_status="Declined"
    )

    assert _rank(transactions=(older, newer)) == [
        (R.DECLINED_TRANSACTION, Decimal("0.83"), "TRX-B"),
    ]


def test_tied_scores_go_to_the_newest_event() -> None:
    # Both are at the 40 percent floor (34).
    older = _tx(
        timedelta(hours=70), transaction_id="TRX-A", transaction_status="Declined"
    )
    newer = _tx(
        timedelta(hours=60), transaction_id="TRX-B", transaction_status="Declined"
    )

    assert _rank(transactions=(older, newer)) == [
        (R.DECLINED_TRANSACTION, Decimal("0.34"), "TRX-B"),
    ]


def test_tied_scores_and_times_go_to_the_lowest_ref_id() -> None:
    second = _tx(transaction_id="TRX-B", transaction_status="Declined")
    first = _tx(transaction_id="TRX-A", transaction_status="Declined")

    assert _rank(transactions=(second, first)) == [
        (R.DECLINED_TRANSACTION, Decimal("0.84"), "TRX-A"),
    ]


def test_state_reasons_and_cases_tie_on_the_lowest_ref_id() -> None:
    cards = (
        _card(card_last4="9999", product_status="Blocked"),
        _card(card_last4="1234", product_status="Blocked"),
    )
    cases = (_case(complaint_id="CMP-B"), _case(complaint_id="CMP-A"))

    assert _rank(cards=cards, cases=cases) == [
        (R.OPEN_CASE_FOLLOWUP, Decimal("0.60"), "CMP-A"),
        (R.CARD_NOT_ACTIVE, Decimal("0.60"), "1234"),
    ]


def test_a_breached_case_beats_a_lower_id() -> None:
    cases = (
        _case(complaint_id="CMP-A"),
        _case(complaint_id="CMP-B", sla_breached=True),
    )

    assert _rank(cases=cases) == [(R.OPEN_CASE_FOLLOWUP, Decimal("0.75"), "CMP-B")]


def test_tied_cases_go_to_the_newest() -> None:
    # Spec 6.3: breached first, then the newest case.
    older = _case(complaint_id="CMP-A", creation_date=AS - timedelta(days=30))
    newer = _case(complaint_id="CMP-B", creation_date=AS - timedelta(days=10))

    assert _rank(cases=(older, newer)) == [
        (R.OPEN_CASE_FOLLOWUP, Decimal("0.60"), "CMP-B"),
    ]


def test_a_breached_case_beats_a_newer_one() -> None:
    breached = _case(
        complaint_id="CMP-B",
        sla_breached=True,
        creation_date=AS - timedelta(days=30),
    )
    newer = _case(complaint_id="CMP-A", creation_date=AS - timedelta(days=2))

    assert _rank(cases=(newer, breached)) == [
        (R.OPEN_CASE_FOLLOWUP, Decimal("0.75"), "CMP-B"),
    ]


def test_an_undated_case_ranks_but_loses_a_tie_to_a_dated_one() -> None:
    undated = _case(complaint_id="CMP-A", creation_date=None)
    dated = _case(complaint_id="CMP-B")

    assert _rank(cases=(undated,)) == [
        (R.OPEN_CASE_FOLLOWUP, Decimal("0.60"), "CMP-A"),
    ]
    assert _rank(cases=(undated, dated)) == [
        (R.OPEN_CASE_FOLLOWUP, Decimal("0.60"), "CMP-B"),
    ]


def test_null_sla_breached_counts_as_not_breached() -> None:
    assert _rank(cases=(_case(sla_breached=None),)) == [
        (R.OPEN_CASE_FOLLOWUP, Decimal("0.60"), "CMP-A"),
    ]


@pytest.mark.parametrize(
    ("age", "confidence"),
    [
        (timedelta(0), "0.70"),
        (timedelta(days=7), "0.70"),
        (timedelta(days=7, seconds=1), "0.60"),
    ],
)
def test_a_case_opened_in_the_last_7_days_weighs_70(
    age: timedelta, confidence: str
) -> None:
    assert _rank(cases=(_case(creation_date=AS - age),)) == [
        (R.OPEN_CASE_FOLLOWUP, Decimal(confidence), "CMP-A"),
    ]


def test_an_undated_case_is_not_recent() -> None:
    assert _rank(cases=(_case(creation_date=None),)) == [
        (R.OPEN_CASE_FOLLOWUP, Decimal("0.60"), "CMP-A"),
    ]


def test_a_recent_breached_case_still_weighs_75() -> None:
    recent = _case(sla_breached=True, creation_date=AS - timedelta(days=1))

    assert _rank(cases=(recent,)) == [
        (R.OPEN_CASE_FOLLOWUP, Decimal("0.75"), "CMP-A"),
    ]


def test_a_fresh_claim_outranks_the_card_it_got_blocked() -> None:
    # The fraud flow blocks the card and opens a claim the same day; next contact
    # is about the claim, not the block.
    claim = _case(creation_date=AS - timedelta(hours=3))
    blocked = _card(product_status="Blocked")

    assert _rank(cards=(blocked,), cases=(claim,)) == [
        (R.OPEN_CASE_FOLLOWUP, Decimal("0.70"), "CMP-A"),
        (R.CARD_NOT_ACTIVE, Decimal("0.60"), "4497"),
    ]


def test_equal_scores_go_to_the_higher_weight() -> None:
    pending = _tx(timedelta(hours=5), transaction_status="Pending")  # 65 - 5 = 60

    assert _rank(transactions=(pending,), cases=(_case(),)) == [
        (R.PENDING_TRANSACTION, Decimal("0.60"), "TRX-A"),
        (R.OPEN_CASE_FOLLOWUP, Decimal("0.60"), "CMP-A"),
    ]


def test_equal_scores_and_weights_go_to_enum_order() -> None:
    blocked = _card(product_status="Blocked")
    error_now = _event(timedelta(0))

    assert _rank(cards=(blocked,), cases=(_case(),), app_events=(error_now,)) == [
        (R.OPEN_CASE_FOLLOWUP, Decimal("0.60"), "CMP-A"),
        (R.CARD_NOT_ACTIVE, Decimal("0.60"), "4497"),
        (R.FAILED_APP_ACTION, Decimal("0.60"), "EVT-A"),
    ]


def test_ranking_uses_the_unrounded_score() -> None:
    # 65 - 5.0042 = 59.9958: rounds to 0.60 like the card, but ranks below it,
    # even though its weight (65) is higher.
    pending = _tx(timedelta(hours=5, seconds=15), transaction_status="Pending")
    blocked = _card(product_status="Blocked")

    assert _rank(transactions=(pending,), cards=(blocked,)) == [
        (R.CARD_NOT_ACTIVE, Decimal("0.60"), "4497"),
        (R.PENDING_TRANSACTION, Decimal("0.60"), "TRX-A"),
    ]


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        pytest.param(
            _event(timedelta(hours=24)),
            [(R.FAILED_APP_ACTION, Decimal("0.36"), "EVT-A")],
            id="24h-in",
        ),
        pytest.param(_event(timedelta(hours=24, seconds=1)), [], id="24h-out"),
        pytest.param(_event(event_date=None), [], id="null-date"),
        pytest.param(_event(-timedelta(seconds=1)), [], id="future"),
    ],
)
def test_app_event_window(
    event: AppEventCandidate, expected: list[tuple[CallReason, Decimal, str]]
) -> None:
    assert _rank(app_events=(event,)) == expected


def test_p10_card_not_active_then_payment_overdue() -> None:
    cards = (
        _card(card_last4="7718", product_status="Blocked"),
        _card(card_last4="2626", days_past_due=180),
    )

    assert _rank(cards=cards) == [
        (R.CARD_NOT_ACTIVE, Decimal("0.60"), "7718"),
        (R.PAYMENT_OVERDUE, Decimal("0.50"), "2626"),
    ]
