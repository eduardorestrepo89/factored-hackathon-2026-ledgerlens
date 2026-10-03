"""HandOffPublisher adapter for Amazon SNS.

The topic (ledgerlens-human-handoff, data stack) fans each hand-off out to its
subscribers: an email address for the demo, a contact-center queue later
(product design Q5). The Lambda runs outside the VPC, so it reaches SNS
directly.

TODO(ledgerlens): W7 - an email subscriber gets the summary in plain text.
  Demo only.
"""

import json
from typing import Any, Final, Protocol

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from human_agent_hand_off_lambda.application.ports.errors import PublishError
from human_agent_hand_off_lambda.application.ports.hand_off_publisher import (
    HandOffPublisher,
)
from human_agent_hand_off_lambda.domain.entities.hand_off import HandOff

SOURCE: Final = "ledgerlens"


class SnsClient(Protocol):
    """The part of the boto3 SNS client the publisher uses."""

    def publish(self, **kwargs: Any) -> dict[str, Any]:
        """Publish a message; the response carries its MessageId."""
        ...


class SnsHandOffPublisher(HandOffPublisher):
    """Publish each hand-off to one SNS topic as JSON."""

    def __init__(
        self, topic_arn: str, region: str, sns_client: SnsClient | None = None
    ) -> None:
        """Configure the topic; the boto3 client is created on the first publish."""
        self._topic_arn: str = topic_arn
        self._region: str = region
        self._sns_client: SnsClient | None = sns_client

    def publish(self, hand_off: HandOff) -> str:
        """Publish the hand-off and return SNS's MessageId.

        Raises:
            PublishError: The client couldn't be created, SNS refused the
                message, or the response had no MessageId. A failed client
                creation is retried on the next publish.
        """
        try:
            if self._sns_client is None:
                self._sns_client = boto3.client("sns", region_name=self._region)
            response = self._sns_client.publish(
                TopicArn=self._topic_arn,
                Subject=subject(hand_off),
                Message=json.dumps(payload(hand_off), ensure_ascii=False),
                MessageAttributes={
                    "priority": {
                        "DataType": "String",
                        "StringValue": hand_off.priority,
                    },
                    "reason": {"DataType": "String", "StringValue": hand_off.reason},
                },
            )
            return str(response["MessageId"])
        except (BotoCoreError, ClientError, KeyError, TypeError) as exc:
            raise PublishError("SNS publish failed") from exc


def subject(hand_off: HandOff) -> str:
    """ASCII and under 100 characters, as SNS requires: built only from enum values."""
    return f"[{hand_off.priority.upper()}] LedgerLens hand-off: {hand_off.reason}"


def payload(hand_off: HandOff) -> dict[str, Any]:
    """The message body. SNS adds its own timestamp to every delivery."""
    return {
        "source": SOURCE,
        "customer_id": hand_off.customer_id,
        "priority": hand_off.priority,
        "reason": hand_off.reason,
        "summary": hand_off.summary,
        "related_ids": list(hand_off.related_ids),
    }
