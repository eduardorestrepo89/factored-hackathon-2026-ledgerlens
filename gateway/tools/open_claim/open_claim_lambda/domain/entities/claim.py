"""Entities returned by the open_claim use case."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Claim:
    """One opened claim: one card and one currency.

    ``already_existed`` is True when the same claim was opened before (a retry,
    or the agent calling again), so nothing was written. It is a success, not an
    error. ``status`` is "Open" as written; a later change isn't re-read.
    """

    claim_id: str
    card_last4: str
    transaction_ids: tuple[str, ...]
    claimed_amount: Decimal
    currency: str
    priority: str
    status: str
    already_existed: bool


@dataclass(frozen=True)
class ResolutionEstimate:
    """Median and 90th-percentile resolution time of similar past claims, in days."""

    median_days: int
    p90_days: int


@dataclass(frozen=True)
class ClaimsResult:
    """The claims of one call; the estimate is None when it isn't known."""

    claims: tuple[Claim, ...]
    resolution_estimate: ResolutionEstimate | None
