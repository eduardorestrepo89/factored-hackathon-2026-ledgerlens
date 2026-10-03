"""Tests for the hand-off Lambda settings."""

import pytest
from human_agent_hand_off_lambda.delivery.settings import (
    ConfigurationError,
    HandOffSettings,
)

pytestmark = pytest.mark.unit

TOPIC = "arn:aws:sns:us-east-1:111111111111:ledgerlens-human-handoff"


def test_settings_read_the_topic_and_region() -> None:
    env = {"HANDOFF_TOPIC_ARN": f" {TOPIC} ", "AWS_REGION": " us-east-1 "}

    assert HandOffSettings.from_env(env) == HandOffSettings(
        topic_arn=TOPIC, region="us-east-1"
    )


@pytest.mark.parametrize(
    ("env", "name"),
    [
        ({"AWS_REGION": "us-east-1"}, "HANDOFF_TOPIC_ARN"),
        ({"HANDOFF_TOPIC_ARN": " ", "AWS_REGION": "us-east-1"}, "HANDOFF_TOPIC_ARN"),
        (
            {
                "HANDOFF_TOPIC_ARN": "ledgerlens-human-handoff",
                "AWS_REGION": "us-east-1",
            },
            "HANDOFF_TOPIC_ARN",
        ),
        (
            {
                "HANDOFF_TOPIC_ARN": "arn:aws:sqs:us-east-1:1:q",
                "AWS_REGION": "us-east-1",
            },
            "HANDOFF_TOPIC_ARN",
        ),
        ({"HANDOFF_TOPIC_ARN": TOPIC}, "AWS_REGION"),
    ],
)
def test_invalid_settings_are_rejected(env: dict[str, str], name: str) -> None:
    with pytest.raises(ConfigurationError, match=name):
        HandOffSettings.from_env(env)
