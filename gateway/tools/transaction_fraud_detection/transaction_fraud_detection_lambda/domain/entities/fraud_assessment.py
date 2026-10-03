"""Domain entities returned by the fraud check. Neither carries the score."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from transaction_fraud_detection_lambda.domain.value_objects.fraud_bands import (
    FraudVerdict,
    ScoreBasis,
)


@dataclass(frozen=True)
class FraudAssessment:
    """The verdict on one credit-card charge.

    The use case drops the score after banding it, so it can't reach the agent.
    """

    transaction_id: str
    transaction_date: datetime | None
    card_last4: str | None
    merchant_name: str | None
    amount: Decimal | None
    currency: str | None
    transaction_status: str | None
    verdict: FraudVerdict
    basis: ScoreBasis


@dataclass(frozen=True)
class CardSweep:
    """Every charge on one card in the last 30 days, flagged ones only.

    Attributes:
        card_last4: The card swept.
        date_from: as_of minus 30 days, inclusive, naive UTC.
        date_to: as_of, naive UTC.
        checked: How many charges were in the window, flagged or not.
        flagged: The fraud and review charges, highest score first.
        truncated: More flagged charges exist than were returned.
    """

    card_last4: str
    date_from: datetime
    date_to: datetime
    checked: int
    flagged: tuple[FraudAssessment, ...]
    truncated: bool
