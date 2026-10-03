"""Lambda handler for the ``human_agent_hand_off`` Gateway tool.

Handler string: ``human_agent_hand_off_lambda/delivery/handler.handler``.

Input: the tool arguments as the event (see
``gateway/tools/human_agent_hand_off/tool_spec.json``); the tool name arrives
in ``context.client_context.custom["bedrockAgentCoreToolName"]`` with a
``<target>___`` prefix. Every argument is passed to the use case bare.

Output: ``{"content": [{"type": "text", "text": <JSON>}]}`` on success, or
``{"error": <agent-facing message>}``. Raw exception text is never returned.

The use case and its publisher are built once, when the module loads; a warm
container reuses them. The function runs outside the VPC and never touches DSQL.
"""

import json
import logging
import os
from collections.abc import Mapping
from typing import Any, Final

from human_agent_hand_off_lambda.delivery.dependencies.dependencies_builder import (
    build_hand_off_use_case,
)
from human_agent_hand_off_lambda.delivery.presenters.hand_off import (
    present_hand_off,
)
from human_agent_hand_off_lambda.domain.errors import (
    DomainError,
    HandOffUnavailableError,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TOOL_NAME: Final = "human_agent_hand_off"
_TOOL_NAME_DELIMITER: Final = "___"
UNEXPECTED_ERROR_MESSAGE: Final = (
    "Unexpected internal error sending the hand-off. Tell the customer you "
    "couldn't reach a person and that they can contact the bank through its "
    "usual channels."
)
_WRONG_TOOL_MESSAGE: Final = (
    f"This function only serves the '{TOOL_NAME}' tool. Don't retry; tell the "
    "customer they can contact the bank through its usual channels."
)


USE_CASE = build_hand_off_use_case(os.environ)


def handler(event: object, context: object) -> dict[str, Any]:
    """Send the conversation to a human agent for the agent.

    Args:
        event: Tool arguments passed directly by the AgentCore Gateway.
        context: Lambda context with the tool name in client_context.custom.

    Returns:
        A Gateway ``content`` response, or ``{"error": message}``.
    """
    tool_name = _tool_name(context)
    if tool_name != TOOL_NAME:
        logger.error("Unexpected tool name %r for %s", tool_name, TOOL_NAME)
        return {"error": _WRONG_TOOL_MESSAGE}

    args = event if isinstance(event, Mapping) else {}
    try:
        if USE_CASE is None:
            raise HandOffUnavailableError()
        body = present_hand_off(
            USE_CASE.execute(
                customer_id=args.get("customer_id"),
                priority=args.get("priority"),
                reason=args.get("reason"),
                summary=args.get("summary"),
                related_ids=args.get("related_ids"),
            )
        )
    except DomainError as err:
        logger.warning(
            "%s returned an error: %s", TOOL_NAME, err.message, exc_info=True
        )
        return {"error": err.message}
    except Exception:
        logger.exception("Unexpected error in %s", TOOL_NAME)
        return {"error": UNEXPECTED_ERROR_MESSAGE}

    # The summary is never logged: it holds what the customer said.
    logger.info(
        "%s queued %s (priority=%s)", TOOL_NAME, body["hand_off_id"], body["priority"]
    )
    return {"content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]}


def _tool_name(context: object) -> str | None:
    """Return the tool name without its ``<target>___`` prefix, or None if absent."""
    try:
        full_name = context.client_context.custom["bedrockAgentCoreToolName"]  # type: ignore[attr-defined]
    except (AttributeError, KeyError, TypeError):
        return None
    if not isinstance(full_name, str):
        return None
    return full_name.rpartition(_TOOL_NAME_DELIMITER)[2]
