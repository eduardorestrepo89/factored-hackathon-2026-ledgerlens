"""Unit tests for the hook that pauses a claim or hand-off for the customer's Yes/No.

The module lives at ``agent/ledgerlens/tools/confirmation_hook.py``.
``strands.hooks`` is stubbed like in test_customer_id_hook.py. The stub event's
``interrupt`` mirrors strands-agents 1.32.0: it returns the response once one is
set and raises otherwise.
"""

import importlib
import sys
import types
from pathlib import Path

import pytest

_PATTERN_DIR = Path(__file__).resolve().parents[2] / "agent" / "ledgerlens"

BLOCK = "gateway_block-credit-card-target___block_credit_card"
CLAIM = "gateway_open-claim-target___open_claim"
HAND_OFF = "gateway_human-agent-hand-off-target___human_agent_hand_off"


class Paused(Exception):
    """Stands in for strands.interrupt.InterruptException."""


class StubBeforeToolCallEvent:
    def __init__(self, name, tool_input, response=None):
        self.tool_use = {"name": name, "toolUseId": "tool-1", "input": tool_input}
        self.cancel_tool = False
        self.response = response
        self.raised = None

    def interrupt(self, name, reason=None, response=None):
        self.raised = (name, reason)
        if self.response is None:
            raise Paused()
        return self.response


class StubHookRegistry:
    def add_callback(self, event_type, callback):
        pass


@pytest.fixture(scope="module")
def confirm():
    """Import tools/confirmation_hook.py with a stub strands.hooks."""
    hooks = types.ModuleType("strands.hooks")
    hooks.BeforeToolCallEvent = StubBeforeToolCallEvent
    hooks.HookProvider = object
    hooks.HookRegistry = StubHookRegistry
    sys.modules.setdefault("strands", types.ModuleType("strands"))
    sys.modules["strands.hooks"] = hooks
    if str(_PATTERN_DIR) not in sys.path:
        sys.path.insert(0, str(_PATTERN_DIR))
    for name in ("tools.confirmation_hook",):
        sys.modules.pop(name, None)
    return importlib.import_module("tools.confirmation_hook")


CLAIM_INPUT = {"customer_id": "CLI-1", "transaction_ids": ["TRX-1"], "claim_type": "fraud"}


def test_a_claim_pauses_for_the_customer_with_its_details(confirm):
    event = StubBeforeToolCallEvent(CLAIM, CLAIM_INPUT)

    with pytest.raises(Paused):
        confirm.ConfirmationHook().confirm(event)

    name, reason = event.raised
    assert name == "confirm_open_claim"
    assert reason == {
        "tool": "open_claim",
        "toolUseId": "tool-1",
        "details": {"transaction_ids": ["TRX-1"], "claim_type": "fraud"},  # no customer_id
    }


def test_a_card_block_pauses_with_the_card_and_without_the_model_flag(confirm):
    event = StubBeforeToolCallEvent(
        BLOCK, {"customer_id": "CLI-1", "card_last4": "4497", "reason": "lost", "customer_confirmed": True}
    )

    with pytest.raises(Paused):
        confirm.ConfirmationHook().confirm(event)

    assert event.raised[1]["details"] == {"card_last4": "4497", "reason": "lost"}


@pytest.mark.parametrize("model_flag", [False, None])
def test_yes_runs_the_block_with_customer_confirmed_set_by_the_click(confirm, model_flag):
    # Cedar requires customer_confirmed true; after a click it never comes from the model.
    tool_input = {"customer_id": "CLI-1", "card_last4": "4497", "reason": "lost"}
    if model_flag is not None:
        tool_input["customer_confirmed"] = model_flag
    event = StubBeforeToolCallEvent(BLOCK, tool_input, {"approved": True})

    confirm.ConfirmationHook().confirm(event)

    assert event.cancel_tool is False
    assert event.tool_use["input"] == {**tool_input, "customer_confirmed": True}


def test_yes_runs_a_hand_off_without_adding_a_flag_it_doesnt_take(confirm):
    event = StubBeforeToolCallEvent(HAND_OFF, {"reason": "CUSTOMER_REQUEST"}, {"approved": True})

    confirm.ConfirmationHook().confirm(event)

    assert event.cancel_tool is False
    assert event.tool_use["input"] == {"reason": "CUSTOMER_REQUEST"}


def test_no_cancels_the_call(confirm):
    event = StubBeforeToolCallEvent(CLAIM, CLAIM_INPUT, {"approved": False})

    confirm.ConfirmationHook().confirm(event)

    assert event.cancel_tool == confirm.DECLINED_MESSAGE


def test_a_typed_reply_that_isnt_a_yes_reaches_the_model(confirm):
    event = StubBeforeToolCallEvent(CLAIM, CLAIM_INPUT, {"approved": False, "text": 'y el "otro" cargo?'})

    confirm.ConfirmationHook().confirm(event)

    assert "y el 'otro' cargo?" in event.cancel_tool


def test_other_tools_and_cancelled_calls_are_left_alone(confirm):
    other = StubBeforeToolCallEvent("gateway_x___list_credit_cards", {})
    cancelled = StubBeforeToolCallEvent(CLAIM, CLAIM_INPUT)
    cancelled.cancel_tool = "no linked customer"

    confirm.ConfirmationHook().confirm(other)
    confirm.ConfirmationHook().confirm(cancelled)

    assert other.raised is None and cancelled.raised is None


def test_clicks_answer_each_confirmation_and_unanswered_ones_are_no(confirm):
    payload = {"prompt": "Sí", "confirmations": [{"interruptId": "a", "approved": True}]}

    responses = confirm.resume_prompt(["a", "b"], payload)

    assert responses == [
        {"interruptResponse": {"interruptId": "a", "response": {"approved": True}}},
        {"interruptResponse": {"interruptId": "b", "response": {"approved": False}}},
    ]


@pytest.mark.parametrize("typed", ["sí, ábrelo", "mejor no", "¿cuánto tarda?"])
def test_a_typed_reply_never_approves_and_reaches_the_model(confirm, typed):
    # Only a click on Yes runs the tool, so even a typed "sí" is passed on as words.
    [response] = confirm.resume_prompt(["a"], {"prompt": typed})

    assert response["interruptResponse"]["response"] == {"approved": False, "text": typed}


def test_an_interrupted_result_becomes_a_confirmation_event(confirm):
    interrupt = types.SimpleNamespace(id="a", name="confirm_open_claim", reason={"tool": "open_claim"})
    result = types.SimpleNamespace(stop_reason="interrupt", interrupts=[interrupt])

    assert confirm.confirmation_events({"result": result}) == [
        {"confirmation": {"id": "a", "tool": "open_claim"}}
    ]
    assert confirm.confirmation_events({"result": types.SimpleNamespace(stop_reason="end_turn")}) == []
    assert confirm.confirmation_events({"data": "hola"}) == []
