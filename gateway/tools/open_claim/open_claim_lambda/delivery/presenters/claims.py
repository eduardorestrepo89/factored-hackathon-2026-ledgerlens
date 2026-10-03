"""Present open_claim results as the JSON returned to the agent."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from open_claim_lambda.domain.entities.claim import Claim, ClaimsResult

_CENTS: Final = Decimal("0.01")


def present_claims(result: ClaimsResult) -> dict[str, Any]:
    """Return ``{"claims": [...], "resolution_estimate": {...} | None}``.

    Amounts are 2-decimal strings in the claim's currency, so no float rounding
    reaches the agent. ``resolution_estimate`` is null when there isn't enough
    history; the agent then gives no time.
    """
    estimate = result.resolution_estimate
    return {
        "claims": [_present(claim) for claim in result.claims],
        "resolution_estimate": (
            None
            if estimate is None
            else {"median_days": estimate.median_days, "p90_days": estimate.p90_days}
        ),
    }


def _present(claim: Claim) -> dict[str, Any]:
    """Convert one claim to JSON-safe values."""
    return {
        "claim_id": claim.claim_id,
        "card_last4": claim.card_last4,
        "transaction_ids": list(claim.transaction_ids),
        "claimed_amount": str(
            claim.claimed_amount.quantize(_CENTS, rounding=ROUND_HALF_UP)
        ),
        "currency": claim.currency,
        "priority": claim.priority,
        "status": claim.status,
        "already_existed": claim.already_existed,
    }
