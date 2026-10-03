"""Port for delivering a hand-off to wherever human agents pick it up."""

from abc import ABC, abstractmethod

from human_agent_hand_off_lambda.domain.entities.hand_off import HandOff


class HandOffPublisher(ABC):
    """Port for publishing a validated hand-off."""

    @abstractmethod
    def publish(self, hand_off: HandOff) -> str:
        """Publish the hand-off and return its reference.

        Raises:
            PublishError: The hand-off couldn't be delivered.
        """
