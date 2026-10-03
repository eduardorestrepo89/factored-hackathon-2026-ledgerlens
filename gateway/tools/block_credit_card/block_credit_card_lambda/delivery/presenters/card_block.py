"""Present the block_credit_card result as the JSON returned to the agent."""

from typing import Any

from block_credit_card_lambda.domain.entities.card_block import CardBlock


def present_card_block(block: CardBlock) -> dict[str, Any]:
    """Return ``{"card_last4", "status", "already_blocked"}``.

    ``already_blocked`` true means the card was blocked before this call; the
    agent tells the customer the card is blocked, not that anything failed.
    """
    return {
        "card_last4": block.card_last4,
        "status": block.status,
        "already_blocked": block.already_blocked,
    }
