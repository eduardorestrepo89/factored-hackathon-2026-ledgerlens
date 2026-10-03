"""Present the hand-off result as the JSON returned to the agent."""

from typing import Any

from human_agent_hand_off_lambda.domain.entities.hand_off import HandOffResult


def present_hand_off(result: HandOffResult) -> dict[str, Any]:
    """Return ``{"hand_off_id", "status": "queued", "priority"}``.

    "queued" means a person has the case and the summary; nobody has picked it up
    yet, so the agent promises no time.
    """
    return {
        "hand_off_id": result.hand_off_id,
        "status": "queued",
        "priority": result.priority,
    }
