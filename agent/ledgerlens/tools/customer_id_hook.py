"""Strands hook that sets customer_id on every tool call from the machine token.

The system prompt tells the model which customer_id to pass, but the model is
never the source of the value. Before each tool call, this hook finds tools
whose input schema has a customer_id property and overwrites it with the
customer_id from the Gateway machine token, whatever the model wrote. When the
user has no linked customer, those calls are cancelled instead. Cedar checks
the same value against the token at the Gateway.

Checked against strands-agents 1.32.0: the tool executor runs the tool_use and
cancel_tool the BeforeToolCallEvent hooks leave on the event.
"""

import logging

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

logger = logging.getLogger(__name__)

NOT_LINKED_MESSAGE = (
    "This user's account is not linked to a customer, so customer data "
    "can't be looked up."
)


def _takes_customer_id(selected_tool) -> bool:
    """Return True when the tool's input schema has a customer_id property."""
    if selected_tool is None:
        return False
    input_schema = selected_tool.tool_spec.get("inputSchema", {}).get("json", {})
    return "customer_id" in input_schema.get("properties", {})


class CustomerIdHook(HookProvider):
    """Overwrite customer_id on every tool call that takes one."""

    def __init__(self, customer_id: str):
        """
        Args:
            customer_id (str): The customer_id from the Gateway machine token,
                or "" when the user has no linked customer.
        """
        self.customer_id = customer_id

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        """Register the before-tool-call callback."""
        registry.add_callback(BeforeToolCallEvent, self.set_customer_id)

    def set_customer_id(self, event: BeforeToolCallEvent) -> None:
        """Set customer_id on the tool input, or cancel the call when there is none."""
        if not _takes_customer_id(event.selected_tool):
            return

        tool_name = event.tool_use.get("name")
        if not self.customer_id:
            logger.info("[CUSTOMER-ID] No linked customer - cancelling %s", tool_name)
            event.cancel_tool = NOT_LINKED_MESSAGE
            return

        tool_input = event.tool_use.get("input")
        if not isinstance(tool_input, dict):
            tool_input = {}
        if tool_input.get("customer_id") != self.customer_id:
            # The value itself isn't logged (privacy); only that it was replaced.
            logger.info(
                "[CUSTOMER-ID] Replaced the model's customer_id on %s", tool_name
            )

        event.tool_use = {
            **event.tool_use,
            "input": {**tool_input, "customer_id": self.customer_id},
        }
