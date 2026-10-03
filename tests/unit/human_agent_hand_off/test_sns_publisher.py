"""Tests for SnsHandOffPublisher."""

import json

import human_agent_hand_off_lambda.infrastructure.publishers.sns_publisher as sns_module
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, NoRegionError
from human_agent_hand_off_lambda.application.ports.errors import PublishError
from human_agent_hand_off_lambda.domain.entities.hand_off import HandOff
from human_agent_hand_off_lambda.infrastructure.publishers.sns_publisher import (
    SnsHandOffPublisher,
)

from .fakes import CUSTOMER_ID, FakeSnsClient

pytestmark = pytest.mark.unit

TOPIC = "arn:aws:sns:us-east-1:111111111111:ledgerlens-human-handoff"
HAND_OFF = HandOff(
    customer_id=CUSTOMER_ID,
    priority="high",
    reason="FRAUD_CONFIRMED",
    summary="El cliente no reconoce 2 cargos. Tarjeta 4821 bloqueada.",
    related_ids=("TRX-88", "CMP-4KQ2ZJ7M3XH5TB6RWN2Y"),
)


def test_publishes_json_with_an_ascii_subject_and_filterable_attributes() -> None:
    client = FakeSnsClient()

    reference = SnsHandOffPublisher(TOPIC, "us-east-1", client).publish(HAND_OFF)

    assert reference == "msg-1"
    (call,) = client.calls
    assert call["TopicArn"] == TOPIC
    assert call["Subject"] == "[HIGH] LedgerLens hand-off: FRAUD_CONFIRMED"
    assert call["Subject"].isascii() and len(call["Subject"]) <= 100
    assert call["MessageAttributes"] == {
        "priority": {"DataType": "String", "StringValue": "high"},
        "reason": {"DataType": "String", "StringValue": "FRAUD_CONFIRMED"},
    }
    assert json.loads(call["Message"]) == {
        "source": "ledgerlens",
        "customer_id": CUSTOMER_ID,
        "priority": "high",
        "reason": "FRAUD_CONFIRMED",
        "summary": HAND_OFF.summary,
        "related_ids": ["TRX-88", "CMP-4KQ2ZJ7M3XH5TB6RWN2Y"],
    }
    assert "El cliente" in call["Message"]  # ensure_ascii=False keeps the text readable


@pytest.mark.parametrize(
    "error",
    [
        ClientError(
            {"Error": {"Code": "AuthorizationError", "Message": "no"}}, "Publish"
        ),
        EndpointConnectionError(endpoint_url="https://sns.us-east-1.amazonaws.com"),
    ],
)
def test_sdk_errors_become_publish_error(error: Exception) -> None:
    with pytest.raises(PublishError) as caught:
        SnsHandOffPublisher(TOPIC, "us-east-1", FakeSnsClient(error=error)).publish(
            HAND_OFF
        )

    assert caught.value.__cause__ is error


def test_a_response_without_a_message_id_is_a_publish_error() -> None:
    client = FakeSnsClient(response={"ResponseMetadata": {}})

    with pytest.raises(PublishError):
        SnsHandOffPublisher(TOPIC, "us-east-1", client).publish(HAND_OFF)


def test_the_client_is_created_lazily_for_the_region_and_reused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[tuple[str, str]] = []
    client = FakeSnsClient()

    def fake_client(service: str, region_name: str) -> FakeSnsClient:
        created.append((service, region_name))
        return client

    monkeypatch.setattr(sns_module.boto3, "client", fake_client)
    publisher = SnsHandOffPublisher(TOPIC, "us-east-1")
    assert created == []

    publisher.publish(HAND_OFF)
    publisher.publish(HAND_OFF)

    assert created == [("sns", "us-east-1")]
    assert len(client.calls) == 2


def test_a_failed_client_creation_is_a_publish_error_and_is_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    def failing_client(service: str, region_name: str) -> FakeSnsClient:
        attempts.append(service)
        raise NoRegionError()

    monkeypatch.setattr(sns_module.boto3, "client", failing_client)
    publisher = SnsHandOffPublisher(TOPIC, "us-east-1")

    for _ in range(2):
        with pytest.raises(PublishError):
            publisher.publish(HAND_OFF)

    assert attempts == ["sns", "sns"]
