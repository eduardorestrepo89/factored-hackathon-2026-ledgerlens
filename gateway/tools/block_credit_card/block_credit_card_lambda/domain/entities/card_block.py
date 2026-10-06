"""Result entity of the block_credit_card use case."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CardBlock:
    """The card the customer asked to block, after the call.

    ``already_blocked`` is True when the card was blocked before this call (by an
    earlier call or a retry), so nothing was written. It is a success, not an
    error. The internal ``product_id`` is never exposed.
    """

    card_last4: str
    status: str
    already_blocked: bool
