"""Entities returned by the explain_transaction use case.

Every field that comes from a nullable column is ``| None``: the source data has
about 5% nulls, and a row with a null column is still explained. No entity has a
fraud field; judging fraud is transaction_fraud_detection's job.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


@dataclass(frozen=True)
class ExplainedTransaction:
    """The charge itself. ``transaction_id`` is never None: it is the row's key."""

    transaction_id: str
    transaction_date: datetime | None
    card_last4: str | None
    merchant_name: str | None
    merchant_category: str | None
    amount: Decimal | None
    currency: str | None
    channel: str | None
    transaction_city: str | None
    transaction_country: str | None
    transaction_status: str | None


@dataclass(frozen=True)
class FxConversion:
    """What a charge in another currency cost in the card's currency.

    ``rate`` is the bank's sell rate on the charge's date, None when that day has
    no rate. ``amount_in_card_currency`` is amount times rate, rounded half-up to
    2 decimals, None without a rate or an amount.
    """

    card_currency: str
    rate_date: date | None
    rate: Decimal | None
    amount_in_card_currency: Decimal | None


@dataclass(frozen=True)
class DeclineInfo:
    """Why a declined charge was declined.

    ``meaning`` is None for a code the bank doesn't document.
    ``contradicts_card_state`` is True when the code says "expired card" but the
    card was still valid on the charge date (D18), None when that can't be told.
    """

    response_code: str | None
    meaning: str | None
    contradicts_card_state: bool | None


@dataclass(frozen=True)
class UsualAmountRange:
    """The 10th to 90th percentile of the card's approved charges in one currency.

    The values are exact as the database computed them; the presenter rounds.
    """

    low: Decimal
    high: Decimal
    currency: str


@dataclass(frozen=True)
class SpendingHabit:
    """How the charge compares with the card's approved charges of the 90 days before.

    ``times_at_merchant_90d`` is None when the charge has no merchant, and
    ``country_seen_before`` is None when it has no country.
    """

    history_count: int
    times_at_merchant_90d: int | None
    usual_amount_range: UsualAmountRange | None
    country_seen_before: bool | None


@dataclass(frozen=True)
class AppActivity:
    """The customer's app or web event closest to the charge, within 2 hours.

    ``found`` False means there was no such event, which is the usual case.
    ``minutes_from_charge`` is event minus charge, negative when the event came
    first. ``conflict`` is True when the event was in another country during an
    in-person charge, None when a country or the channel is unknown.
    """

    found: bool
    event_date: datetime | None = None
    minutes_from_charge: int | None = None
    ip_country: str | None = None
    ip_city: str | None = None
    conflict: bool | None = None


class Section(StrEnum):
    """The optional sections, in the order their queries run."""

    HABIT = "habit"
    APP_ACTIVITY = "app_activity"


@dataclass(frozen=True)
class TransactionExplanation:
    """Everything known about one charge.

    ``fx`` is None for a charge in the card's currency and ``decline`` is None
    unless the charge was declined. ``habit`` or ``app_activity`` is None only
    when its query failed, and is then named in ``unavailable``.
    """

    transaction: ExplainedTransaction
    fx: FxConversion | None
    decline: DeclineInfo | None
    habit: SpendingHabit | None
    app_activity: AppActivity | None
    unavailable: tuple[Section, ...]
