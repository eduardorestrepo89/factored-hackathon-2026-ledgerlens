"""Fraud bands: the fraud engine's stored score mapped to a verdict.

The dataset's transactions.fraud_score (0-100, numeric(5,2)) is treated as the
feed of a bank fraud engine. This tool reads that score and adds no heuristic of
its own. The bands come from the 2026-10-03 profiling (X3, X4 and X15 in
datathon/analysis/profiling_output.txt): no clean charge scores above 30, and
every charge above 50 is fraud. The score is simulated, so the bands fit this
dataset, not a real engine.

classify_call_type keeps its own copy of these bands (tools never share code).
Both tools' tests pin the literals 50 and 30, so changing one copy breaks a test.
"""

from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Final

FRAUD_ABOVE: Final = Decimal("50")
REVIEW_ABOVE: Final = Decimal("30")


class FraudVerdict(StrEnum):
    """What the agent should treat the charge as."""

    FRAUD = "fraud"
    REVIEW = "review"
    NO_FRAUD = "no_fraud"


class ScoreBasis(StrEnum):
    """Whether the fraud engine produced a score for the charge."""

    SCORED = "scored"
    NOT_SCORED = "not_scored"


NEXT_STEPS: Final[Mapping[FraudVerdict, str | None]] = {
    FraudVerdict.FRAUD: (
        "Confirm with the customer, then block the card and open a fraud claim."
    ),
    FraudVerdict.REVIEW: (
        "Ask whether they recognize the charge; if not, offer to open a case "
        "for clarification and dispute."
    ),
    FraudVerdict.NO_FRAUD: None,
}


def assess(score: Decimal | None) -> tuple[FraudVerdict, ScoreBasis]:
    """Band a stored score. The comparisons are strict: 50.00 is review.

    A missing score is no_fraud with basis not_scored: the engine produced
    nothing, which isn't proof the charge is genuine. A score outside 0-100 is
    banded as it is.
    """
    if score is None:
        return FraudVerdict.NO_FRAUD, ScoreBasis.NOT_SCORED
    if score > FRAUD_ABOVE:
        return FraudVerdict.FRAUD, ScoreBasis.SCORED
    if score > REVIEW_ABOVE:
        return FraudVerdict.REVIEW, ScoreBasis.SCORED
    return FraudVerdict.NO_FRAUD, ScoreBasis.SCORED
