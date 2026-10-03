"""Tests for the open_claim presenter."""

from decimal import Decimal

import pytest
from open_claim_lambda.delivery.presenters.claims import present_claims
from open_claim_lambda.domain.entities.claim import (
    Claim,
    ClaimsResult,
    ResolutionEstimate,
)

pytestmark = pytest.mark.unit

CLAIM = Claim(
    claim_id="CMP-4KQ2ZJ7M3XH5TB6RWN2Y",
    card_last4="4821",
    transaction_ids=("TRX-88", "TRX-89"),
    claimed_amount=Decimal("835.005"),
    currency="USD",
    priority="High",
    status="Open",
    already_existed=False,
)


def test_presenter_returns_claims_with_2_decimal_amounts_and_the_estimate() -> None:
    result = ClaimsResult(
        claims=(CLAIM,), resolution_estimate=ResolutionEstimate(5, 12)
    )

    assert present_claims(result) == {
        "claims": [
            {
                "claim_id": "CMP-4KQ2ZJ7M3XH5TB6RWN2Y",
                "card_last4": "4821",
                "transaction_ids": ["TRX-88", "TRX-89"],
                "claimed_amount": "835.01",
                "currency": "USD",
                "priority": "High",
                "status": "Open",
                "already_existed": False,
            }
        ],
        "resolution_estimate": {"median_days": 5, "p90_days": 12},
    }


def test_presenter_returns_a_null_estimate_when_unknown() -> None:
    result = ClaimsResult(claims=(CLAIM,), resolution_estimate=None)

    assert present_claims(result)["resolution_estimate"] is None
