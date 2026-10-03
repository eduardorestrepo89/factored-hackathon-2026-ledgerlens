"""The tool's result: up to 3 ranked reasons and the reasons that couldn't be checked."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from classify_call_type_lambda.domain.entities.candidates import (
    AppEventCandidate,
    CardCandidate,
    CaseCandidate,
    TransactionCandidate,
)
from classify_call_type_lambda.domain.value_objects.call_reasons import CallReason

# A plain alias, not a ``type`` statement: ruff.toml targets py311.
Candidate = TransactionCandidate | CardCandidate | CaseCandidate | AppEventCandidate


@dataclass(frozen=True)
class RankedReason:
    """A reason with its 2-decimal confidence and the record it points to."""

    reason: CallReason
    confidence: Decimal
    ref_id: str
    candidate: Candidate


@dataclass(frozen=True)
class CallClassification:
    """The ranking, best first, and the unavailable reasons in enum order.

    as_of_date is as_of's date in naive UTC, the date the card rules used. The
    presenter needs it for CARD_EXPIRING's days_left.
    """

    reasons: tuple[RankedReason, ...]
    unavailable: tuple[CallReason, ...]
    as_of_date: date
