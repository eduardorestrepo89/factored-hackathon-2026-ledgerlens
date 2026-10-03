"""Tests for the dependency wiring of the human_agent_hand_off tool."""

import human_agent_hand_off_lambda.infrastructure.publishers.sns_publisher as sns_module
import pytest
from human_agent_hand_off_lambda.application.use_cases.hand_off import HandOffUseCase
from human_agent_hand_off_lambda.delivery.dependencies.dependencies_builder import (
    build_hand_off_use_case,
)

from .fakes import CUSTOMER_ID, FakeSnsClient

pytestmark = pytest.mark.unit

TOPIC = "arn:aws:sns:us-east-1:111111111111:ledgerlens-human-handoff"
ENV = {"HANDOFF_TOPIC_ARN": TOPIC, "AWS_REGION": "us-east-1"}


def test_the_use_case_publishes_to_the_configured_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeSnsClient()
    monkeypatch.setattr(sns_module.boto3, "client", lambda *_a, **_k: client)

    use_case = build_hand_off_use_case(ENV)
    assert isinstance(use_case, HandOffUseCase)
    result = use_case.execute(
        CUSTOMER_ID, "normal", "OUT_OF_SCOPE", "Pide un préstamo.", None
    )

    assert result.hand_off_id == "msg-1"
    assert client.calls[0]["TopicArn"] == TOPIC


def test_building_creates_no_boto3_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_boto3(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("boto3 client created while building")

    monkeypatch.setattr(sns_module.boto3, "client", no_boto3)

    assert build_hand_off_use_case(ENV) is not None


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"AWS_REGION": "us-east-1"},
        {"HANDOFF_TOPIC_ARN": "x", "AWS_REGION": "us-east-1"},
    ],
)
def test_bad_configuration_returns_none(
    env: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    assert build_hand_off_use_case(env) is None
    assert "Invalid configuration for human_agent_hand_off" in caplog.text
