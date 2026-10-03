"""Drift tests: tool_spec.json must match the use case's rules."""

import json
from pathlib import Path

import pytest
from human_agent_hand_off_lambda.application.use_cases.hand_off import (
    MAX_RELATED_IDS,
    PRIORITIES,
    REASONS,
)

pytestmark = pytest.mark.unit

TOOL_SPEC = (
    Path(__file__).resolve().parents[3]
    / "gateway/tools/human_agent_hand_off/tool_spec.json"
)


def tool_spec() -> dict:
    """Load the single tool definition from tool_spec.json."""
    specs = json.loads(TOOL_SPEC.read_text(encoding="utf-8"))
    assert isinstance(specs, list) and len(specs) == 1
    return specs[0]


def test_tool_spec_matches_the_use_case() -> None:
    spec = tool_spec()
    properties = spec["inputSchema"]["properties"]

    assert spec["name"] == "human_agent_hand_off"
    assert spec["inputSchema"]["required"] == [
        "customer_id",
        "priority",
        "reason",
        "summary",
    ]
    assert tuple(properties["priority"]["enum"]) == PRIORITIES
    assert tuple(properties["reason"]["enum"]) == REASONS
    assert properties["related_ids"]["maxItems"] == MAX_RELATED_IDS


def test_tool_spec_description_asks_for_a_complete_summary_and_no_time() -> None:
    description = tool_spec()["description"]

    assert "without asking the customer anything again" in description
    assert "Don't promise a time." in description
