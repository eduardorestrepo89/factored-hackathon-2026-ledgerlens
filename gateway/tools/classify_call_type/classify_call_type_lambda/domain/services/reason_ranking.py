"""Detect, score and rank call reasons (spec section 3). Pure functions, no I/O.

Every datetime here is naive UTC: the rows' timestamps have no time zone, and
the use case converts as_of the same way before calling rank(). The arithmetic is
Decimal throughout; age is fractional (17.74 days, not 17).
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from classify_call_type_lambda.domain.entities.call_classification import (
    Candidate,
    RankedReason,
)
from classify_call_type_lambda.domain.entities.candidates import (
    AppEventCandidate,
    CardCandidate,
    CaseCandidate,
    TransactionCandidate,
)
from classify_call_type_lambda.domain.value_objects.call_reasons import (
    OPEN_CASE_BREACHED_WEIGHT,
    OPEN_CASE_RECENT_WEIGHT,
    OPEN_CASE_RECENT_WINDOW,
    REASON_RULES,
    CallReason,
    Decay,
)
from classify_call_type_lambda.domain.value_objects.fraud_bands import (
    FRAUD_ABOVE,
    REVIEW_ABOVE,
)
from classify_call_type_lambda.domain.value_objects.text_folding import fold_text

_APPROVED: Final = "Approved"
_ACTIVE: Final = "Active"
# The status reasons of a charge that isn't approved.
_STATUS_REASONS: Final = {
    "Declined": CallReason.DECLINED_TRANSACTION,
    "Pending": CallReason.PENDING_TRANSACTION,
    "Reversed": CallReason.REVERSED_TRANSACTION,
}
# Closed cards are not a reason to call about the card.
_NOT_ACTIVE_STATUSES: Final = frozenset({"Blocked", "Suspended"})
_EXPIRING_WITHIN: Final = timedelta(days=30)
_FLOOR: Final = Decimal("0.4")
_SECONDS_PER_UNIT: Final = {
    Decay.PER_HOUR: Decimal(3600),
    Decay.PER_DAY: Decimal(86400),
}
_HUNDRED: Final = Decimal(100)
_CENTS: Final = Decimal("0.01")
_ENUM_ORDER: Final = {reason: index for index, reason in enumerate(CallReason)}


@dataclass(frozen=True)
class _Scored:
    """A detected reason with its unrounded score, before the ranking."""

    reason: CallReason
    score: Decimal
    weight: Decimal
    event_time: datetime | None
    ref_id: str
    candidate: Candidate


def score(
    weight: Decimal, decay: Decay, event_time: datetime | None, as_of: datetime
) -> Decimal:
    """Return the decayed, unrounded score of an event.

    A future event counts as age 0. The score never falls below 40 percent of
    the weight.

    Raises:
        ValueError: A decaying reason has no event time.
    """
    if decay is Decay.NONE:
        return weight
    if event_time is None:
        raise ValueError("a decaying reason needs an event time")
    age = max(_seconds(as_of - event_time), Decimal(0))
    return max(weight - age / _SECONDS_PER_UNIT[decay], _FLOOR * weight)


def to_confidence(score: Decimal) -> Decimal:
    """Return score / 100 with 2 decimals, rounded half-up."""
    return (score / _HUNDRED).quantize(_CENTS, rounding=ROUND_HALF_UP)


def transaction_reasons(
    candidate: TransactionCandidate, as_of: datetime
) -> tuple[CallReason, ...]:
    """Return the reasons a charge triggers, in enum order.

    A charge without a date triggers nothing: every charge reason is timed.
    """
    when = candidate.transaction_date
    if when is None:
        return ()
    found: set[CallReason] = set()
    status = candidate.transaction_status
    if status == _APPROVED:
        band = _fraud_band(candidate.fraud_score)
        if band is not None:
            found.add(band)
        if _is_foreign(candidate):
            found.add(CallReason.FOREIGN_TRANSACTION)
    elif status in _STATUS_REASONS:
        found.add(_STATUS_REASONS[status])
    return tuple(
        reason
        for reason in CallReason
        if reason in found and _in_window(reason, when, as_of)
    )


def card_reasons(candidate: CardCandidate, as_of_date: date) -> tuple[CallReason, ...]:
    """Return the reasons a card's state triggers, in enum order.

    A Blocked or Suspended card is CARD_NOT_ACTIVE only; the other card
    reasons need an Active card.
    """
    status = candidate.product_status
    if status in _NOT_ACTIVE_STATUSES:
        return (CallReason.CARD_NOT_ACTIVE,)
    if status != _ACTIVE:
        return ()
    found: list[CallReason] = []
    if candidate.days_past_due is not None and candidate.days_past_due > 0:
        found.append(CallReason.PAYMENT_OVERDUE)
    expiration = candidate.expiration_date
    if expiration is not None and as_of_date <= expiration <= (
        as_of_date + _EXPIRING_WITHIN
    ):
        found.append(CallReason.CARD_EXPIRING)
    return tuple(found)


def rank(
    *,
    transactions: Sequence[TransactionCandidate],
    cards: Sequence[CardCandidate],
    cases: Sequence[CaseCandidate],
    app_events: Sequence[AppEventCandidate],
    as_of: datetime,
    limit: int,
) -> tuple[RankedReason, ...]:
    """Detect, score and rank every reason; keep the best ``limit``.

    The best event per reason has the highest score, then the newest event,
    then the lowest ref_id. Across reasons: the unrounded score descending,
    then the weight descending, then enum order.
    """
    scored = [
        *_score_transactions(transactions, as_of),
        *_score_cards(cards, as_of),
        *_score_cases(cases, as_of),
        *_score_app_events(app_events, as_of),
    ]
    ordered = sorted(
        _best_per_reason(scored),
        key=lambda item: (-item.score, -item.weight, _ENUM_ORDER[item.reason]),
    )
    return tuple(
        RankedReason(
            reason=item.reason,
            confidence=to_confidence(item.score),
            ref_id=item.ref_id,
            candidate=item.candidate,
        )
        for item in ordered[:limit]
    )


def _score_transactions(
    candidates: Sequence[TransactionCandidate], as_of: datetime
) -> Iterator[_Scored]:
    for candidate in candidates:
        for reason in transaction_reasons(candidate, as_of):
            yield _scored(
                reason,
                candidate,
                candidate.transaction_id,
                candidate.transaction_date,
                as_of,
            )


def _score_cards(
    candidates: Sequence[CardCandidate], as_of: datetime
) -> Iterator[_Scored]:
    for candidate in candidates:
        for reason in card_reasons(candidate, as_of.date()):
            yield _scored(reason, candidate, candidate.card_last4, None, as_of)


def _score_cases(
    candidates: Sequence[CaseCandidate], as_of: datetime
) -> Iterator[_Scored]:
    reason = CallReason.OPEN_CASE_FOLLOWUP
    for candidate in candidates:
        if candidate.sla_breached is True:
            weight = OPEN_CASE_BREACHED_WEIGHT
        elif (
            candidate.creation_date is not None
            and as_of - candidate.creation_date <= OPEN_CASE_RECENT_WINDOW
        ):
            weight = OPEN_CASE_RECENT_WEIGHT
        else:
            weight = REASON_RULES[reason].weight
        # A case doesn't decay; its creation date sets its weight above and
        # otherwise only makes the newest win a tie.
        yield _scored(
            reason,
            candidate,
            candidate.complaint_id,
            candidate.creation_date,
            as_of,
            weight,
        )


def _score_app_events(
    candidates: Sequence[AppEventCandidate], as_of: datetime
) -> Iterator[_Scored]:
    reason = CallReason.FAILED_APP_ACTION
    for candidate in candidates:
        when = candidate.event_date
        if when is not None and _in_window(reason, when, as_of):
            yield _scored(reason, candidate, candidate.event_id, when, as_of)


def _scored(
    reason: CallReason,
    candidate: Candidate,
    ref_id: str,
    event_time: datetime | None,
    as_of: datetime,
    weight: Decimal | None = None,
) -> _Scored:
    """Score one detection with the reason's rule (or an effective weight)."""
    rule = REASON_RULES[reason]
    effective = rule.weight if weight is None else weight
    return _Scored(
        reason=reason,
        score=score(effective, rule.decay, event_time, as_of),
        weight=effective,
        event_time=event_time,
        ref_id=ref_id,
        candidate=candidate,
    )


def _best_per_reason(scored: list[_Scored]) -> list[_Scored]:
    """Keep each reason's best: highest score, then newest, then lowest ref_id."""
    # Stable sorts: first by ref_id ascending, then by (score, time) descending,
    # so equal score and time keep the lowest ref_id first.
    ordered = sorted(scored, key=lambda item: item.ref_id)
    ordered.sort(
        key=lambda item: (item.score, item.event_time or datetime.min), reverse=True
    )
    best: dict[CallReason, _Scored] = {}
    for item in ordered:
        best.setdefault(item.reason, item)
    return list(best.values())


def _fraud_band(fraud_score: Decimal | None) -> CallReason | None:
    """Return the fraud reason of an approved charge's score, or None."""
    if fraud_score is None:
        return None
    if fraud_score > FRAUD_ABOVE:
        return CallReason.FRAUD_SUSPECTED
    if fraud_score > REVIEW_ABOVE:
        return CallReason.UNRECOGNIZED_CHARGE_REVIEW
    return None


def _is_foreign(candidate: TransactionCandidate) -> bool:
    """Return whether the country (folded) or the currency differs.

    A blank country folds to "" and counts as unknown, like NULL.
    """
    country = fold_text(candidate.transaction_country)
    home = fold_text(candidate.home_country)
    by_country = bool(country) and bool(home) and country != home
    by_currency = (
        candidate.currency is not None
        and candidate.card_currency is not None
        and candidate.currency != candidate.card_currency
    )
    return by_country or by_currency


def _in_window(reason: CallReason, when: datetime, as_of: datetime) -> bool:
    """Return whether ``when`` is in the reason's window, both ends inclusive."""
    window = REASON_RULES[reason].window
    return window is None or as_of - window <= when <= as_of


def _seconds(delta: timedelta) -> Decimal:
    """Return a timedelta in exact Decimal seconds (total_seconds() is a float)."""
    return (
        Decimal(delta.days * 86400 + delta.seconds)
        + Decimal(delta.microseconds) / 1_000_000
    )
