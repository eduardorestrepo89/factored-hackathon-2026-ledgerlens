"""Tests for the fraud bands: the stored score mapped to a verdict."""

from decimal import Decimal

import pytest
from transaction_fraud_detection_lambda.domain.value_objects.fraud_bands import (
    FRAUD_ABOVE,
    NEXT_STEPS,
    REVIEW_ABOVE,
    FraudVerdict,
    ScoreBasis,
    assess,
)

pytestmark = pytest.mark.unit


def test_band_limits_are_pinned() -> None:
    # classify_call_type keeps its own copy of these; both tools pin the literals.
    assert Decimal("50") == FRAUD_ABOVE
    assert Decimal("30") == REVIEW_ABOVE


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (None, (FraudVerdict.NO_FRAUD, ScoreBasis.NOT_SCORED)),
        (Decimal("100.00"), (FraudVerdict.FRAUD, ScoreBasis.SCORED)),
        (Decimal("50.01"), (FraudVerdict.FRAUD, ScoreBasis.SCORED)),
        (Decimal("50.00"), (FraudVerdict.REVIEW, ScoreBasis.SCORED)),
        (Decimal("30.01"), (FraudVerdict.REVIEW, ScoreBasis.SCORED)),
        (Decimal("30.00"), (FraudVerdict.NO_FRAUD, ScoreBasis.SCORED)),
        (Decimal("0.00"), (FraudVerdict.NO_FRAUD, ScoreBasis.SCORED)),
        (Decimal("-1"), (FraudVerdict.NO_FRAUD, ScoreBasis.SCORED)),
        (Decimal("150"), (FraudVerdict.FRAUD, ScoreBasis.SCORED)),
    ],
)
def test_assess_bands_each_score(
    score: Decimal | None, expected: tuple[FraudVerdict, ScoreBasis]
) -> None:
    assert assess(score) == expected


def test_enum_values_are_the_output_strings() -> None:
    assert [v.value for v in FraudVerdict] == ["fraud", "review", "no_fraud"]
    assert [b.value for b in ScoreBasis] == ["scored", "not_scored"]


def test_next_steps_per_verdict() -> None:
    assert NEXT_STEPS == {
        FraudVerdict.FRAUD: (
            "Confirm with the customer, then block the card and open a fraud claim."
        ),
        FraudVerdict.REVIEW: (
            "Ask whether they recognize the charge; if not, offer to open a "
            "case for clarification and dispute."
        ),
        FraudVerdict.NO_FRAUD: None,
    }
