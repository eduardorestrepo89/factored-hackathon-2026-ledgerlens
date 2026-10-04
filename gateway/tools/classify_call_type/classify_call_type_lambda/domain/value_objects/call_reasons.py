"""The call-reason taxonomy: reasons, their pinned rules and the query feeding each.

The weights are hand-set, not learned (DEC-10). They are pinned in tests and in
the spec (section 3.1). CallReason's order is the final ranking tie-break.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class CallReason(StrEnum):
    """A likely reason for the call; the order is the final tie-break."""

    FRAUD_SUSPECTED = "FRAUD_SUSPECTED"
    DECLINED_TRANSACTION = "DECLINED_TRANSACTION"
    UNRECOGNIZED_CHARGE_REVIEW = "UNRECOGNIZED_CHARGE_REVIEW"
    OPEN_CASE_FOLLOWUP = "OPEN_CASE_FOLLOWUP"
    PENDING_TRANSACTION = "PENDING_TRANSACTION"
    REVERSED_TRANSACTION = "REVERSED_TRANSACTION"
    CARD_NOT_ACTIVE = "CARD_NOT_ACTIVE"
    FAILED_APP_ACTION = "FAILED_APP_ACTION"
    FOREIGN_TRANSACTION = "FOREIGN_TRANSACTION"
    PAYMENT_OVERDUE = "PAYMENT_OVERDUE"
    CARD_EXPIRING = "CARD_EXPIRING"


class Decay(StrEnum):
    """How a reason's score falls with the event's age."""

    PER_HOUR = "per_hour"
    PER_DAY = "per_day"
    NONE = "none"


class Source(StrEnum):
    """A candidate query; the use case runs them in this order."""

    TRANSACTIONS = "transactions"
    CARDS = "cards"
    CASES = "cases"
    APP_EVENTS = "app_events"


@dataclass(frozen=True)
class ReasonRule:
    """A reason's base weight, look-back window (None: no window) and decay."""

    weight: Decimal
    window: timedelta | None
    decay: Decay


_HOURS_24: Final = timedelta(hours=24)
_HOURS_72: Final = timedelta(hours=72)
_DAYS_30: Final = timedelta(days=30)

REASON_RULES: Final[Mapping[CallReason, ReasonRule]] = MappingProxyType(
    {
        CallReason.FRAUD_SUSPECTED: ReasonRule(Decimal("95"), _DAYS_30, Decay.PER_DAY),
        CallReason.DECLINED_TRANSACTION: ReasonRule(
            Decimal("85"), _HOURS_72, Decay.PER_HOUR
        ),
        CallReason.UNRECOGNIZED_CHARGE_REVIEW: ReasonRule(
            Decimal("70"), _DAYS_30, Decay.PER_DAY
        ),
        # 60 for an open case; a breached one weighs OPEN_CASE_BREACHED_WEIGHT,
        # a recent one OPEN_CASE_RECENT_WEIGHT.
        CallReason.OPEN_CASE_FOLLOWUP: ReasonRule(Decimal("60"), None, Decay.NONE),
        CallReason.PENDING_TRANSACTION: ReasonRule(
            Decimal("65"), _HOURS_72, Decay.PER_HOUR
        ),
        CallReason.REVERSED_TRANSACTION: ReasonRule(
            Decimal("65"), _HOURS_72, Decay.PER_HOUR
        ),
        CallReason.CARD_NOT_ACTIVE: ReasonRule(Decimal("60"), None, Decay.NONE),
        CallReason.FAILED_APP_ACTION: ReasonRule(
            Decimal("60"), _HOURS_24, Decay.PER_HOUR
        ),
        CallReason.FOREIGN_TRANSACTION: ReasonRule(
            Decimal("55"), _HOURS_72, Decay.PER_HOUR
        ),
        CallReason.PAYMENT_OVERDUE: ReasonRule(Decimal("50"), None, Decay.NONE),
        CallReason.CARD_EXPIRING: ReasonRule(Decimal("35"), None, Decay.NONE),
    }
)

# Weight of an open case whose sla_breached is true; NULL counts as false (60).
OPEN_CASE_BREACHED_WEIGHT: Final = Decimal("75")

# Weight of an unbreached case created within OPEN_CASE_RECENT_WINDOW of as_of
# (inclusive). It sits above CARD_NOT_ACTIVE (60), so a claim the fraud flow just
# opened outranks the card that flow blocked. An undated case isn't recent.
OPEN_CASE_RECENT_WEIGHT: Final = Decimal("70")
OPEN_CASE_RECENT_WINDOW: Final = timedelta(days=7)

# The reasons each query feeds; a failed query makes exactly these unavailable.
SOURCE_REASONS: Final[Mapping[Source, tuple[CallReason, ...]]] = MappingProxyType(
    {
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
)
