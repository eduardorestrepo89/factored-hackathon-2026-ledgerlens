"""Strands hook that pauses block_credit_card, open_claim and human_agent_hand_off until the customer
answers Yes or No.

The model decides when to call these tools; the customer decides whether they run.
After a Yes, the hook sets customer_confirmed to true on the tools that take it, so
the value Cedar checks comes from the click, never from the model.
Before either tool runs, the hook raises a Strands interrupt, so the agent stops
with stop_reason "interrupt" and the call waits. The runtime streams a
"confirmation" event (confirmation_events), the frontend shows Yes/No buttons,
and the click comes back as the next request (resume_prompt). The interrupt and
the waiting tool call are saved with the session, so the click resumes that exact
call: Yes runs it, No cancels it with a message telling the model not to retry.

Only a click on Yes runs the tool. A typed reply instead of a click never does:
it reaches the model as the customer's words, and if they still want the action
the model calls the tool again and the buttons show again.

Checked against strands-agents 1.32.0: BeforeToolCallEvent.interrupt() raises
until a response is set, the event loop saves the tool-use message and resumes
it without calling the model, and RepositorySessionManager persists
_interrupt_state with the session.
"""

import logging
from typing import Any

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

logger = logging.getLogger(__name__)

# Gateway tools are registered as gateway_<target>___<tool>; match on the tool part.
CONFIRM_TOOLS = frozenset({"block_credit_card", "open_claim", "human_agent_hand_off"})
# Tools whose input has customer_confirmed (Cedar requires it to be true)
CONFIRMED_FLAG_TOOLS = frozenset({"block_credit_card", "open_claim"})
INTERRUPT_PREFIX = "confirm_"

DECLINED_MESSAGE = (
    "Not done: the customer chose No. Don't call this tool again unless they ask for it."
)
TYPED_REPLY_MESSAGE = (
    'Not done: the customer wrote instead of tapping Yes or No: "{text}". Answer that. '
    "If they still want this, call the tool again so the buttons show again."
)


class ConfirmationHook(HookProvider):
    """Pause the tools in CONFIRM_TOOLS until the customer answers Yes or No."""

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        """Register the before-tool-call callback."""
        registry.add_callback(BeforeToolCallEvent, self.confirm)

    def confirm(self, event: BeforeToolCallEvent) -> None:
        """Interrupt for a confirmation, then let the call run or cancel it."""
        tool = str(event.tool_use.get("name", "")).rpartition("___")[2]
        if tool not in CONFIRM_TOOLS or event.cancel_tool:
            return  # not ours, or another hook already cancelled it
        tool_input = event.tool_use.get("input")
        if not isinstance(tool_input, dict):
            tool_input = {}
        details = {k: v for k, v in tool_input.items() if k not in ("customer_id", "customer_confirmed")}
        response = event.interrupt(
            INTERRUPT_PREFIX + tool,
            reason={"tool": tool, "toolUseId": event.tool_use.get("toolUseId"), "details": details},
        )
        if isinstance(response, dict) and response.get("approved") is True:
            logger.info("[CONFIRM] Customer approved %s", tool)
            if tool in CONFIRMED_FLAG_TOOLS:
                event.tool_use = {**event.tool_use, "input": {**tool_input, "customer_confirmed": True}}
            return
        logger.info("[CONFIRM] Customer declined %s", tool)
        text = response.get("text") if isinstance(response, dict) else None
        event.cancel_tool = (
            TYPED_REPLY_MESSAGE.format(text=text.replace('"', "'")[:300])
            if text
            else DECLINED_MESSAGE
        )


def resume_prompt(pending_ids: list[str], payload: dict) -> list[dict]:
    """Build the interrupt responses for the request that answers the confirmations.

    Args:
        pending_ids: Ids of the interrupts the agent is waiting on.
        payload: The request body. A button click sends "confirmations":
            [{"interruptId": ..., "approved": true|false}]; a typed reply only "prompt".

    Returns:
        One interruptResponse per pending interrupt. Only a click on Yes approves:
        an unanswered interrupt is a No, and a typed reply is a No carrying the text.
    """
    clicks = payload.get("confirmations")
    if isinstance(clicks, list):
        answers = {
            c.get("interruptId"): c.get("approved") is True for c in clicks if isinstance(c, dict)
        }
        responses: dict[str, dict[str, Any]] = {
            i: {"approved": answers.get(i, False)} for i in pending_ids
        }
    else:
        text = str(payload.get("prompt") or "")
        responses = {i: {"approved": False, "text": text} for i in pending_ids}
    return [
        {"interruptResponse": {"interruptId": i, "response": r}} for i, r in responses.items()
    ]


def confirmation_events(event: dict) -> list[dict]:
    """Return one {"confirmation": ...} stream event per confirmation the agent stopped on."""
    result = event.get("result")
    if getattr(result, "stop_reason", None) != "interrupt":
        return []
    return [
        {"confirmation": {"id": i.id, **(i.reason or {})}}
        for i in (result.interrupts or [])
        if str(i.name).startswith(INTERRUPT_PREFIX)
    ]
