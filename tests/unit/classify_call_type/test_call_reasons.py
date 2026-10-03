"""Tests for the call-reason taxonomy, its pinned rules and the fraud bands."""

from datetime import timedelta
from decimal import Decimal
from types import MappingProxyType

import pytest
from classify_call_type_lambda.domain.value_objects.call_reasons import (
    OPEN_CASE_BREACHED_WEIGHT,
    REASON_RULES,
    SOURCE_REASONS,
    CallReason,
    Decay,
    ReasonRule,
    Source,
)
from classify_call_type_lambda.domain.value_objects.fraud_bands import (
    FRAUD_ABOVE,
    REVIEW_ABOVE,
)

pytestmark = pytest.mark.unit

_HOURS_72 = timedelta(hours=72)
_DAYS_30 = timedelta(days=30)


def test_enum_order_is_the_final_tie_break() -> None:
    assert [reason.value for reason in CallReason] == [
        "FRAUD_SUSPECTED",
        "DECLINED_TRANSACTION",
        "UNRECOGNIZED_CHARGE_REVIEW",
        "OPEN_CASE_FOLLOWUP",
        "PENDING_TRANSACTION",
        "REVERSED_TRANSACTION",
        "CARD_NOT_ACTIVE",
        "FAILED_APP_ACTION",
        "FOREIGN_TRANSACTION",
        "PAYMENT_OVERDUE",
        "CARD_EXPIRING",
    ]


@pytest.mark.parametrize(
    ("reason", "weight", "window", "decay"),
    [
        (CallReason.FRAUD_SUSPECTED, "95", _DAYS_30, Decay.PER_DAY),
        (CallReason.DECLINED_TRANSACTION, "85", _HOURS_72, Decay.PER_HOUR),
        (CallReason.UNRECOGNIZED_CHARGE_REVIEW, "70", _DAYS_30, Decay.PER_DAY),
        (CallReason.OPEN_CASE_FOLLOWUP, "60", None, Decay.NONE),
        (CallReason.PENDING_TRANSACTION, "65", _HOURS_72, Decay.PER_HOUR),
        (CallReason.REVERSED_TRANSACTION, "65", _HOURS_72, Decay.PER_HOUR),
        (CallReason.CARD_NOT_ACTIVE, "60", None, Decay.NONE),
        (CallReason.FAILED_APP_ACTION, "60", timedelta(hours=24), Decay.PER_HOUR),
        (CallReason.FOREIGN_TRANSACTION, "55", _HOURS_72, Decay.PER_HOUR),
        (CallReason.PAYMENT_OVERDUE, "50", None, Decay.NONE),
        (CallReason.CARD_EXPIRING, "35", None, Decay.NONE),
    ],
)
def test_each_reason_rule_is_pinned(
    reason: CallReason, weight: str, window: timedelta | None, decay: Decay
) -> None:
    assert REASON_RULES[reason] == ReasonRule(
        weight=Decimal(weight), window=window, decay=decay
    )


def test_every_reason_has_a_rule() -> None:
    assert set(REASON_RULES) == set(CallReason)


def test_a_breached_case_weighs_75() -> None:
    assert OPEN_CASE_BREACHED_WEIGHT == Decimal("75")


def test_sources_run_in_this_order() -> None:
    assert [source.value for source in Source] == [
        "transactions",
        "cards",
        "cases",
        "app_events",
    ]


def test_source_reasons_are_pinned() -> None:
    assert dict(SOURCE_REASONS) == {
        Source.TRANSACTIONS: (
            CallReason.FRAUD_SUSPECTED,
            CallReason.DECLINED_TRANSACTION,
            CallReason.UNRECOGNIZED_CHARGE_REVIEW,
            CallReason.PENDING_TRANSACTION,
            CallReason.REVERSED_TRANSACTION,
            CallReason.FOREIGN_TRANSACTION,
        ),
        Source.CARDS: (
            CallReason.CARD_NOT_ACTIVE,
            CallReason.PAYMENT_OVERDUE,
            CallReason.CARD_EXPIRING,
        ),
        Source.CASES: (CallReason.OPEN_CASE_FOLLOWUP,),
        Source.APP_EVENTS: (CallReason.FAILED_APP_ACTION,),
    }


def test_every_reason_comes_from_exactly_one_source() -> None:
    fed = [reason for reasons in SOURCE_REASONS.values() for reason in reasons]

    assert sorted(fed) == sorted(CallReason)
    assert len(fed) == len(set(fed))


def test_tables_are_read_only() -> None:
    assert isinstance(REASON_RULES, MappingProxyType)
    assert isinstance(SOURCE_REASONS, MappingProxyType)
    with pytest.raises(TypeError):
        REASON_RULES[CallReason.FRAUD_SUSPECTED] = ReasonRule(  # type: ignore[index]
            weight=Decimal("1"), window=None, decay=Decay.NONE
        )


def test_fraud_bands_match_transaction_fraud_detection() -> None:
    assert FRAUD_ABOVE == Decimal("50")
    assert REVIEW_ABOVE == Decimal("30")
