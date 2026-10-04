"""Unit tests for the session-start step that loads the session context once.

The module lives at ``agent/ledgerlens/tools/session_context.py``.
apply_session_context is driven with a fake agent holding a real ``AgentState``
(saved with the session) and a ``system_prompt``. The fetch runs against a real
Strands Agent whose tools stand in for the Gateway's, by name.
"""

import asyncio
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from strands import Agent, tool
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.agent.state import AgentState
from strands.models import BedrockModel

_PATTERN_DIR = Path(__file__).resolve().parents[2] / "agent" / "ledgerlens"

CUSTOMER_ID = "CLI-70U0WJ1NH1MN"
SESSION_TOOL = "gateway_get-session-context-target___get_session_context"
CLASSIFY_TOOL = "gateway_classify-call-type-target___classify_call_type"

# The Lambdas' bodies, trimmed (their presenters have every key).
CUSTOMER = {"customer": {"first_name": "Ana", "country": "Chile"}, "cards": []}
REASONS = {"reasons": [{"reason": "DECLINED_TRANSACTION", "ref_id": "TX-1"}]}
CONTEXT = {"customer": CUSTOMER, "likely_reasons": REASONS}


@pytest.fixture(scope="module")
def session_context():
    """Import tools/session_context.py from the strands pattern."""
    if str(_PATTERN_DIR) not in sys.path:
        sys.path.insert(0, str(_PATTERN_DIR))
    return importlib.import_module("tools.session_context")


# --- apply_session_context ----------------------------------------------------


class StateAgent:
    """Stands in for strands.Agent after the session manager restored its state."""

    def __init__(self, state=None):
        self.state = AgentState(state or {})
        self.system_prompt = "built by create_strands_agent"


@pytest.fixture
def fetch(session_context, monkeypatch):
    """Replace the fetch: it returns fetch.result and records each customer_id."""
    fake = SimpleNamespace(calls=[], result=CONTEXT)

    async def fake_fetch(agent, customer_id):
        fake.calls.append(customer_id)
        return fake.result

    monkeypatch.setattr(session_context, "_fetch_session_context", fake_fetch)
    return fake


def test_first_turn_fetches_once_saves_the_context_and_renders_it(
    session_context, fetch
):
    agent = StateAgent()

    asyncio.run(session_context.apply_session_context(agent, CUSTOMER_ID))

    assert fetch.calls == [CUSTOMER_ID]
    assert agent.state.get("session_context") == CONTEXT
    assert "<session_context>\n" in agent.system_prompt
    assert '"first_name":"Ana"' in agent.system_prompt


def test_a_saved_context_is_rendered_without_fetching(session_context, fetch):
    saved = {"customer": {"first_name": "Luis"}, "likely_reasons": {"reasons": []}}
    agent = StateAgent(state={"session_context": saved})

    asyncio.run(session_context.apply_session_context(agent, CUSTOMER_ID))

    assert fetch.calls == []
    assert '"first_name":"Luis"' in agent.system_prompt


def test_a_failed_fetch_saves_nothing_so_the_next_turn_retries(session_context, fetch):
    fetch.result = None
    agent = StateAgent()

    asyncio.run(session_context.apply_session_context(agent, CUSTOMER_ID))

    assert agent.state.get("session_context") is None
    assert "</session_context>" not in agent.system_prompt
    assert CUSTOMER_ID in agent.system_prompt


def test_a_user_without_a_customer_gets_no_fetch_and_no_prompt_change(
    session_context, fetch
):
    agent = StateAgent()

    asyncio.run(session_context.apply_session_context(agent, ""))

    assert fetch.calls == []
    assert agent.system_prompt == "built by create_strands_agent"


# --- the fetch, against a real Strands Agent ----------------------------------


class CountingWindow(SlidingWindowConversationManager):
    """Counts apply_management calls; strands runs it after every agent.tool call."""

    def __init__(self):
        super().__init__(window_size=30)
        self.managed = 0

    def apply_management(self, agent, **kwargs):
        self.managed += 1


def real_agent(session=CUSTOMER, classify=REASONS):
    """A Strands Agent with stand-ins for the two Gateway tools.

    Each argument is the payload the tool returns as JSON text, an exception it
    raises (strands turns it into a status "error" result), or None to leave
    the tool off the Gateway.
    """
    received = []

    def stand_in(name, payload):
        @tool(name=name)
        def gateway_tool(customer_id: str) -> str:
            """Stand-in for a Gateway tool."""
            received.append(customer_id)
            if isinstance(payload, Exception):
                raise payload
            return json.dumps(payload)

        return gateway_tool

    tools = [
        stand_in(name, payload)
        for name, payload in ((SESSION_TOOL, session), (CLASSIFY_TOOL, classify))
        if payload is not None
    ]
    agent = Agent(
        model=BedrockModel(model_id="unit-test"),
        tools=tools,
        conversation_manager=CountingWindow(),
        callback_handler=None,
    )
    agent.received = received
    return agent


def test_bootstrap_runs_no_conversation_management_and_records_nothing(
    session_context,
):
    # agent.tool runs apply_management after each call; two concurrent bootstrap
    # calls could each summarize the same messages and double the removed count.
    agent = real_agent()

    context = asyncio.run(session_context._fetch_session_context(agent, CUSTOMER_ID))

    assert context == CONTEXT
    assert agent.received == [CUSTOMER_ID, CUSTOMER_ID]
    assert agent.conversation_manager.managed == 0
    assert agent.messages == []


@pytest.mark.parametrize(
    "tools",
    [
        pytest.param({"classify": None}, id="classify not on the Gateway"),
        pytest.param({"classify": RuntimeError("timeout")}, id="classify fails"),
        pytest.param({"session": RuntimeError("Cedar denied")}, id="context fails"),
    ],
)
def test_fetch_returns_none_unless_both_tools_succeed(session_context, tools):
    agent = real_agent(**tools)

    context = asyncio.run(session_context._fetch_session_context(agent, CUSTOMER_ID))

    assert context is None


@pytest.mark.parametrize(
    "tools",
    [
        pytest.param(
            {"session": {"error": "We couldn't load your data. Offer a hand-off."}},
            id="the Lambda's error envelope",
        ),
        pytest.param({"classify": {"unavailable": []}}, id="ranking without reasons"),
        pytest.param({"session": ["not", "a", "body"]}, id="not an object"),
    ],
)
def test_fetch_saves_no_payload_that_is_not_the_tools_body(session_context, tools):
    # The Lambdas return failures as {"error": ...}, which the Gateway may pass
    # on as a successful call; saved, it would sit in the prompt all session.
    agent = real_agent(**tools)

    context = asyncio.run(session_context._fetch_session_context(agent, CUSTOMER_ID))

    assert context is None


def test_fetch_unwraps_the_lambdas_own_content_envelope(session_context):
    # If the Gateway passes the Lambda's {"content": [{"text": ...}]} through as
    # text, the body is one level down.
    def wrapped(body):
        return {"content": [{"type": "text", "text": json.dumps(body)}]}

    agent = real_agent(session=wrapped(CUSTOMER), classify=wrapped(REASONS))

    context = asyncio.run(session_context._fetch_session_context(agent, CUSTOMER_ID))

    assert context == CONTEXT
