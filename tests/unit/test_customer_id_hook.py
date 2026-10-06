"""Unit tests for the hook that sets customer_id on every tool call.

The module lives at ``agent/ledgerlens/tools/customer_id_hook.py``.
``strands`` is an agent-runtime dependency, so ``strands.hooks`` is stubbed in
``sys.modules`` with the few names the module imports. The stub event mirrors
strands-agents 1.32.0's ``BeforeToolCallEvent``: ``selected_tool``, ``tool_use``,
``invocation_state`` and ``cancel_tool``, where the tool executor runs the
``tool_use`` and ``cancel_tool`` the hooks leave on the event.
"""

import importlib
import sys
import types
from pathlib import Path

import pytest

_PATTERN_DIR = Path(__file__).resolve().parents[2] / "agent" / "ledgerlens"

CUSTOMER_ID = "CLI-F2DZJYU0POJ9"
OTHER_CUSTOMER_ID = "CLI-ITIECUE8PRH9"


class StubBeforeToolCallEvent:
    """Stands in for strands.hooks.BeforeToolCallEvent."""

    def __init__(self, selected_tool, tool_use):
        self.selected_tool = selected_tool
        self.tool_use = tool_use
        self.invocation_state = {}
        self.cancel_tool = False


class StubHookRegistry:
    """Records the callbacks a hook provider registers."""

    def __init__(self):
        self.callbacks = []

    def add_callback(self, event_type, callback):
        self.callbacks.append((event_type, callback))


def _install_dependency_stubs() -> None:
    """Register a stub ``strands.hooks`` exposing the names the hook imports."""
    hooks = types.ModuleType("strands.hooks")
    hooks.BeforeToolCallEvent = StubBeforeToolCallEvent
    hooks.HookProvider = object
    hooks.HookRegistry = StubHookRegistry
    sys.modules.setdefault("strands", types.ModuleType("strands"))
    sys.modules["strands.hooks"] = hooks


@pytest.fixture(scope="module")
def hook_module():
    """Import tools/customer_id_hook.py from the strands pattern."""
    _install_dependency_stubs()
    if str(_PATTERN_DIR) not in sys.path:
        sys.path.insert(0, str(_PATTERN_DIR))
    sys.modules.pop("tools.customer_id_hook", None)
    return importlib.import_module("tools.customer_id_hook")


def make_tool(properties):
    """Build a tool whose input schema has the given properties."""
    return types.SimpleNamespace(
        tool_spec={
            "name": "tool",
            "description": "",
            "inputSchema": {"json": {"type": "object", "properties": properties}},
        }
    )


CARD_TOOL = make_tool(
    {"customer_id": {"type": "string"}, "card_id": {"type": "string"}}
)
PYTHON_TOOL = make_tool({"code": {"type": "string"}})


def make_event(selected_tool, tool_input):
    """Build a before-tool-call event for one tool use."""
    tool_use = {"toolUseId": "tool-use-1", "name": "tool", "input": tool_input}
    return StubBeforeToolCallEvent(selected_tool, tool_use)


def run_hook(hook_module, customer_id, event):
    """Register the hook and fire its callback for one event."""
    registry = StubHookRegistry()
    hook_module.CustomerIdHook(customer_id).register_hooks(registry)
    for event_type, callback in registry.callbacks:
        if isinstance(event, event_type):
            callback(event)
    return event


def test_registers_a_before_tool_call_callback(hook_module):
    registry = StubHookRegistry()

    hook_module.CustomerIdHook(CUSTOMER_ID).register_hooks(registry)

    assert [event_type for event_type, _ in registry.callbacks] == [
        StubBeforeToolCallEvent
    ]


def test_overwrites_the_customer_id_the_model_wrote(hook_module):
    event = make_event(CARD_TOOL, {"customer_id": OTHER_CUSTOMER_ID, "card_id": "c-1"})

    run_hook(hook_module, CUSTOMER_ID, event)

    assert event.tool_use["input"] == {"customer_id": CUSTOMER_ID, "card_id": "c-1"}
    assert event.cancel_tool is False


def test_adds_the_customer_id_when_the_model_left_it_out(hook_module):
    event = make_event(CARD_TOOL, {"card_id": "c-1"})

    run_hook(hook_module, CUSTOMER_ID, event)

    assert event.tool_use["input"]["customer_id"] == CUSTOMER_ID


def test_keeps_the_rest_of_the_tool_use(hook_module):
    event = make_event(CARD_TOOL, {"customer_id": OTHER_CUSTOMER_ID})

    run_hook(hook_module, CUSTOMER_ID, event)

    assert event.tool_use["toolUseId"] == "tool-use-1"
    assert event.tool_use["name"] == "tool"


def test_non_object_input_becomes_an_object_with_the_customer_id(hook_module):
    event = make_event(CARD_TOOL, "not an object")

    run_hook(hook_module, CUSTOMER_ID, event)

    assert event.tool_use["input"] == {"customer_id": CUSTOMER_ID}


def test_tools_without_customer_id_are_untouched(hook_module):
    event = make_event(PYTHON_TOOL, {"code": "print(1)"})

    run_hook(hook_module, CUSTOMER_ID, event)

    assert event.tool_use["input"] == {"code": "print(1)"}
    assert event.cancel_tool is False


def test_unknown_tool_is_untouched(hook_module):
    event = make_event(None, {"customer_id": OTHER_CUSTOMER_ID})

    run_hook(hook_module, CUSTOMER_ID, event)

    assert event.tool_use["input"] == {"customer_id": OTHER_CUSTOMER_ID}
    assert event.cancel_tool is False


def test_blank_customer_id_cancels_customer_tools(hook_module):
    event = make_event(CARD_TOOL, {"customer_id": OTHER_CUSTOMER_ID})

    run_hook(hook_module, "", event)

    assert isinstance(event.cancel_tool, str)
    assert "not linked" in event.cancel_tool


def test_blank_customer_id_still_allows_other_tools(hook_module):
    event = make_event(PYTHON_TOOL, {"code": "print(1)"})

    run_hook(hook_module, "", event)

    assert event.cancel_tool is False
