"""Unit tests for the session-start step that loads get_session_context.

The module lives at ``patterns/strands-single-agent/tools/session_start.py`` and
imports nothing from strands. A fake agent stands in for the Strands Agent with
the three attributes the module uses: ``messages`` (the history restored from
AgentCore Memory), ``tool_names`` and ``tool`` (direct tool calls).
"""

import importlib
import logging
import sys
from pathlib import Path

import pytest

_PATTERN_DIR = Path(__file__).resolve().parents[2] / "patterns" / "strands-single-agent"

CUSTOMER_ID = "CLI-70U0WJ1NH1MN"
TOOL_NAME = "gateway_get-session-context-target___get_session_context"
OTHER_TOOL = "gateway_list-credit-cards-target___list_credit_cards"


class FakeToolCaller:
    """Stands in for agent.tool: records each direct call, optionally raising."""

    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def __getattr__(self, name):
        def call(**kwargs):
            self.calls.append((name, kwargs))
            if self.error is not None:
                raise self.error
            return {"status": "success", "content": [{"text": "{}"}]}

        return call


class FakeAgent:
    """Stands in for strands.Agent after the memory session manager restored the history."""

    def __init__(self, messages=(), tool_names=(OTHER_TOOL, TOOL_NAME), error=None):
        self.messages = list(messages)
        self.tool_names = list(tool_names)
        self.tool = FakeToolCaller(error)


@pytest.fixture(scope="module")
def session_start():
    """Import tools/session_start.py from the strands pattern."""
    if str(_PATTERN_DIR) not in sys.path:
        sys.path.insert(0, str(_PATTERN_DIR))
    return importlib.import_module("tools.session_start")


def test_first_turn_calls_get_session_context_with_the_customer_id(session_start):
    agent = FakeAgent()

    session_start.load_session_context(agent, CUSTOMER_ID)

    assert agent.tool.calls == [(TOOL_NAME, {"customer_id": CUSTOMER_ID})]


def test_a_session_with_history_is_not_loaded_again(session_start):
    agent = FakeAgent(messages=[{"role": "user", "content": [{"text": "hola"}]}])

    session_start.load_session_context(agent, CUSTOMER_ID)

    assert agent.tool.calls == []


def test_an_unlinked_user_skips_the_call(session_start):
    agent = FakeAgent()

    session_start.load_session_context(agent, "")

    assert agent.tool.calls == []


def test_a_missing_tool_is_skipped_with_a_warning(session_start, caplog):
    agent = FakeAgent(tool_names=[OTHER_TOOL])

    with caplog.at_level(logging.WARNING):
        session_start.load_session_context(agent, CUSTOMER_ID)

    assert agent.tool.calls == []
    assert "get_session_context is not on the Gateway" in caplog.text


def test_a_failing_call_is_logged_and_the_turn_goes_on(session_start, caplog):
    agent = FakeAgent(error=RuntimeError("DSQL timeout"))

    with caplog.at_level(logging.ERROR):
        session_start.load_session_context(agent, CUSTOMER_ID)

    assert agent.tool.calls == [(TOOL_NAME, {"customer_id": CUSTOMER_ID})]
    assert "get_session_context failed" in caplog.text
