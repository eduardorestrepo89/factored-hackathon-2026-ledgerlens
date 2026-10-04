"""Entities of the human_agent_hand_off use case."""

from dataclasses import dataclass


@dataclass(frozen=True)
class HandOff:
    """A validated hand-off to a human agent."""

    customer_id: str
    priority: str
    reason: str
    summary: str
    related_ids: tuple[str, ...]


@dataclass(frozen=True)
class HandOffResult:
    """The queued hand-off and its content-derived id."""

    hand_off_id: str
    hand_off: HandOff
