"""Tests for the human_agent_hand_off Lambda handler."""

import importlib
import json
import logging
import re
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from .fakes import CUSTOMER_ID

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
    """Import the handler module fresh, with an empty environment."""
    for name in ("HANDOFF_TOPIC_ARN", "AWS_REGION"):
        monkeypatch.delenv(name, raising=False)
    import human_agent_hand_off_lambda.delivery.handler as handler_module

    return importlib.reload(handler_module)


def body(response: dict[str, Any]) -> dict[str, Any]:
    """Decode the JSON text of a success response."""
    content = response["content"]
    assert content[0]["type"] == "text"
    return json.loads(content[0]["text"])


def test_the_module_loads_with_an_empty_environment(module: ModuleType) -> None:
    assert module.USE_CASE is not None


def test_success_returns_the_full_hand_off(module: ModuleType) -> None:
    result = body(module.handler(EVENT, make_context()))

    assert re.fullmatch(r"HO-[A-Z2-7]{8}", result["hand_off_id"])
    assert result == {
        "hand_off_id": result["hand_off_id"],
        "status": "queued",
        "priority": "high",
        "reason": "FRAUD_CONFIRMED",
        "customer_id": CUSTOMER_ID,
        "summary": EVENT["summary"],
        "related_ids": ["CMP-4KQ2ZJ7M3XH5TB6RWN2Y"],
    }


def test_the_same_event_gets_the_same_id(module: ModuleType) -> None:
    first = body(module.handler(EVENT, make_context()))["hand_off_id"]

    assert body(module.handler(EVENT, make_context()))["hand_off_id"] == first


def test_related_ids_may_be_left_out(module: ModuleType) -> None:
    event = {k: v for k, v in EVENT.items() if k != "related_ids"}

    assert body(module.handler(event, make_context()))["related_ids"] == []


@pytest.mark.parametrize("event", [None, [], "hand off"])
def test_a_non_object_event_returns_the_customer_id_error(
    module: ModuleType, event: object
) -> None:
    assert "customer_id" in module.handler(event, make_context())["error"]


def test_invalid_input_returns_the_field_error(module: ModuleType) -> None:
    response = module.handler({**EVENT, "priority": "urgent"}, make_context())

    assert response == {
        "error": "Invalid value for 'priority': must be high or normal. "
        "Ask the customer to confirm and retry."
    }


@pytest.mark.parametrize(
    "context", [make_context("open-claim-target___open_claim"), None]
)
def test_wrong_or_missing_tool_name_returns_an_error(
    module: ModuleType, context: object
) -> None:
    response = module.handler(EVENT, context)

    assert set(response) == {"error"}
    assert "human_agent_hand_off" in response["error"]


def test_unexpected_exception_returns_a_generic_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(**_kwargs: object) -> None:
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(module, "USE_CASE", SimpleNamespace(execute=explode))

    response = module.handler(EVENT, make_context())

    assert response == {"error": module.UNEXPECTED_ERROR_MESSAGE}
    assert "secret" not in response["error"]


def test_the_summary_is_never_logged(
    module: ModuleType, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    module.handler(EVENT, make_context())

    assert "queued HO-" in caplog.text
    assert EVENT["summary"] not in caplog.text
