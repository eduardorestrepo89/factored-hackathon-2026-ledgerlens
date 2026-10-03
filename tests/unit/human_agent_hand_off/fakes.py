"""Test doubles for the human_agent_hand_off tests."""

from typing import Any, Final

from human_agent_hand_off_lambda.application.ports.hand_off_publisher import (
    HandOffPublisher,
)
from human_agent_hand_off_lambda.domain.entities.hand_off import HandOff

# A customer id in the format the customer system issues.
CUSTOMER_ID: Final = "CLI-ITIECUE8PRH9"


class FakePublisher(HandOffPublisher):
    """HandOffPublisher double that records hand-offs and returns a reference."""

    def __init__(
        self, reference: str = "msg-1", error: Exception | None = None
    ) -> None:
        """Return ``reference`` from every publish, or raise ``error``."""
        self.reference = reference
        self.error = error
        self.published: list[HandOff] = []

    def publish(self, hand_off: HandOff) -> str:
        """Record the hand-off, then raise or return the reference."""
        self.published.append(hand_off)
        if self.error is not None:
            raise self.error
        return self.reference


class FakeSnsClient:
    """boto3 SNS client double: records publish() calls."""

    def __init__(
        self, response: dict[str, Any] | None = None, error: Exception | None = None
    ) -> None:
        """Return ``response`` (default a MessageId) or raise ``error``."""
        self.response = response if response is not None else {"MessageId": "msg-1"}
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def publish(self, **kwargs: Any) -> dict[str, Any]:
        """Record the keyword arguments, then raise or return the response."""
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response
