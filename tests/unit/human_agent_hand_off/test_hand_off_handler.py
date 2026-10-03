"""Tests for the human_agent_hand_off Lambda handler."""

import importlib
import json
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from human_agent_hand_off_lambda.application.ports.errors import PublishError
from human_agent_hand_off_lambda.application.use_cases.hand_off import HandOffUseCase
from human_agent_hand_off_lambda.domain.errors import HandOffUnavailableError

from .fakes import CUSTOMER_ID, FakePublisher

pytestmark = pytest.mark.unit

EVENT = {
    "customer_id": CUSTOMER_ID,
    "priority": "high",
    "reason": "FRAUD_CONFIRMED",
    "summary": "Card 4821 blocked; claim CMP-4KQ2ZJ7M3XH5TB6RWN2Y opened.",
    "related_ids": ["CMP-4KQ2ZJ7M3XH5TB6RWN2Y"],
}


def make_context(
    tool_name: str = "human-agent-hand-off-target___human_agent_hand_off",
) -> SimpleNamespace:
    """Build a Lambda context carrying the Gateway tool name."""
    return SimpleNamespace(
        client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": tool_name})
    )


@pytest.fixture
def module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Import the handler module fresh, with no topic configured (no AWS calls)."""
    for name in ("HANDOFF_TOPIC_ARN", "AWS_REGION"):
        monkeypatch.delenv(name, raising=False)
    import human_agent_hand_off_lambda.delivery.handler as handler_module

    return importlib.reload(handler_module)


def wire(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, publisher: FakePublisher
) -> None:
    """Point the handler at a use case over ``publisher``."""
    monkeypatch.setattr(module, "USE_CASE", HandOffUseCase(publisher=publisher))


def body(response: dict[str, Any]) -> dict[str, Any]:
    """Decode the JSON text of a success response."""
    content = response["content"]
    assert content[0]["type"] == "text"
    return json.loads(content[0]["text"])


def test_success_queues_the_hand_off(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher = FakePublisher(reference="msg-42")
    wire(module, monkeypatch, publisher)

    assert body(module.handler(EVENT, make_context())) == {
        "hand_off_id": "msg-42",
        "status": "queued",
        "priority": "high",
    }
    assert publisher.published[0].reason == "FRAUD_CONFIRMED"


def test_related_ids_may_be_left_out(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher = FakePublisher()
    wire(module, monkeypatch, publisher)
    event = {k: v for k, v in EVENT.items() if k != "related_ids"}

    assert "content" in module.handler(event, make_context())
    assert publisher.published[0].related_ids == ()


@pytest.mark.parametrize("event", [None, [], "hand off"])
def test_a_non_object_event_returns_the_customer_id_error(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, event: object
) -> None:
    publisher = FakePublisher()
    wire(module, monkeypatch, publisher)

    response = module.handler(event, make_context())

    assert "customer_id" in response["error"]
    assert publisher.published == []


def test_a_failed_publish_returns_the_unavailable_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakePublisher(error=PublishError("down")))

    assert module.handler(EVENT, make_context()) == {
        "error": HandOffUnavailableError.MESSAGE
    }


def test_missing_configuration_returns_the_unavailable_message(
    module: ModuleType,
) -> None:
    assert module.USE_CASE is None

    assert module.handler(EVENT, make_context()) == {
        "error": HandOffUnavailableError.MESSAGE
    }


@pytest.mark.parametrize(
    "context", [make_context("open-claim-target___open_claim"), None]
)
def test_wrong_or_missing_tool_name_returns_an_error(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, context: object
) -> None:
    publisher = FakePublisher()
    wire(module, monkeypatch, publisher)

    response = module.handler(EVENT, context)

    assert set(response) == {"error"}
    assert "human_agent_hand_off" in response["error"]
    assert publisher.published == []


def test_unexpected_exception_returns_a_generic_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(**_kwargs: object) -> None:
        raise RuntimeError("arn:aws:sns:secret")

    monkeypatch.setattr(module, "USE_CASE", SimpleNamespace(execute=explode))

    response = module.handler(EVENT, make_context())

    assert response == {"error": module.UNEXPECTED_ERROR_MESSAGE}
    assert "arn:aws" not in response["error"]
