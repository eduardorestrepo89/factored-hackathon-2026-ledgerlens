"""Present the hand-off result as the JSON returned to the agent."""

from typing import Any

from human_agent_hand_off_lambda.domain.entities.hand_off import HandOffResult


def present_hand_off(result: HandOffResult) -> dict[str, Any]:
    """Return the full hand-off; the frontend builds the agent desk from it.

    "queued" means a person has the case and the summary; nobody has picked it
    up yet, so the agent promises no time.
    """
    hand_off = result.hand_off
    return {
        "hand_off_id": result.hand_off_id,
        "status": "queued",
        "priority": hand_off.priority,
        "reason": hand_off.reason,
        "customer_id": hand_off.customer_id,
        "summary": hand_off.summary,
        "related_ids": list(hand_off.related_ids),
    }
