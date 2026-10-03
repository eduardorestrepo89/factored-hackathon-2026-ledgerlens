"""Entities of the human_agent_hand_off use case."""

from dataclasses import dataclass


@dataclass(frozen=True)
class HandOff:
    """A validated hand-off to a human agent, as it is published."""

    customer_id: str
    priority: str
    reason: str
    summary: str
    related_ids: tuple[str, ...]


@dataclass(frozen=True)
class HandOffResult:
    """The published hand-off: its reference and priority."""

    hand_off_id: str
    priority: str
