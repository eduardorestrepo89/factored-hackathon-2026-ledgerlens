"""Lambda handler for the ``block_credit_card`` Gateway tool.

Handler string: ``block_credit_card_lambda/delivery/handler.handler``.

Input: the tool arguments as the event (see
``gateway/tools/block_credit_card/tool_spec.json``); the tool name arrives in
``context.client_context.custom["bedrockAgentCoreToolName"]`` with a
``<target>___`` prefix. Every argument is passed to the use case bare, exactly
as it came; the use case validates and cleans them.

Output: ``{"content": [{"type": "text", "text": <JSON>}]}`` on success, or
``{"error": <agent-facing message>}``. Raw exception text is never returned: it
could leak SQL, hosts or driver details to the model.

The use case and its whole graph are built once, when the module loads, by
dependencies_builder; a warm container reuses them. AS_OF (optional) is read
once into CLOCK, and CLOCK.now() becomes the card's last_updated on every call.
An invalid AS_OF answers every request with DataSourceUnavailableError's message.

TODO(ledgerlens): R1 - deployed by the data stack (ledgerlens-block-credit-card,
  role ledgerlens-write-tools); no Gateway target or Cedar statement 3 yet (write
  tools spec section 10), so the agent can't call it.
TODO(ledgerlens): R5 - customer_id is trusted from the tool input until Cedar
  statement 2 covers this tool (product design sections 5 and 10).
"""

import json
import logging
import os
from collections.abc import Mapping
from typing import Any, Final

from block_credit_card_lambda.delivery.dependencies.dependencies_builder import (
    build_block_credit_card_use_case,
    build_clock,
)
from block_credit_card_lambda.delivery.presenters.card_block import (
    present_card_block,
)
from block_credit_card_lambda.domain.errors import (
    DataSourceUnavailableError,
    DomainError,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TOOL_NAME: Final = "block_credit_card"
_TOOL_NAME_DELIMITER: Final = "___"
UNEXPECTED_ERROR_MESSAGE: Final = (
    "Unexpected internal error blocking the card. "
    "Offer an urgent hand-off to a human agent."
)
_WRONG_TOOL_MESSAGE: Final = (
    f"This function only serves the '{TOOL_NAME}' tool. "
    "Don't retry; offer a hand-off to a human agent."
)


USE_CASE = build_block_credit_card_use_case(os.environ)
CLOCK = build_clock(os.environ)


def handler(event: object, context: object) -> dict[str, Any]:
    """Block one of the customer's credit cards for the agent.

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
        if USE_CASE is None or CLOCK is None:
            raise DataSourceUnavailableError()
        body = present_card_block(
            USE_CASE.execute(
                customer_id=args.get("customer_id"),
                card_last4=args.get("card_last4"),
                reason=args.get("reason"),
                customer_confirmed=args.get("customer_confirmed"),
                now=CLOCK.now(),
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

    logger.info(
        "%s: card %s blocked (already_blocked=%s)",
        TOOL_NAME,
        body["card_last4"],
        body["already_blocked"],
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
