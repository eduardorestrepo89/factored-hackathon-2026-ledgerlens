"""Lambda handler for the ``classify_call_type`` Gateway tool.

Handler string: ``classify_call_type_lambda/delivery/handler.handler``.

Input: the tool arguments as the event (see
``gateway/tools/classify_call_type/tool_spec.json``); the tool name arrives in
``context.client_context.custom["bedrockAgentCoreToolName"]`` with a
``<target>___`` prefix, as in ``gateway/tools/sample_tool``. ``customer_id`` is
passed to the use case bare, exactly as it came; the use case cleans it.

Output: ``{"content": [{"type": "text", "text": <JSON>}]}`` on success, or
``{"error": <agent-facing message>}``. Only a failure of all four candidate
queries is an error; a failed query makes its reasons ``unavailable`` and the
others are still ranked. Raw exception text is never returned: it could leak
SQL, hosts or driver details to the model. The log names the reasons and
``unavailable`` only, never evidence, confidences or scores.

The use case and its whole graph (settings, connector, connection, adapters) are
built once, when the module loads, by dependencies_builder; a warm container
reuses them. The handler builds nothing itself.

AS_OF (optional) is read once into CLOCK; "now" is CLOCK.now() on every call,
so a warm container never freezes the real clock. An invalid AS_OF answers every
request with DataSourceUnavailableError's message.

TODO(ledgerlens): R5 - customer_id is trusted from the tool input. Authorization
  depends on a Cedar policy matching it to the token's customer_id claim; neither
  the policy nor the claim exists yet (product design sections 5 and 10).
"""

import json
import logging
import os
from collections.abc import Mapping
from typing import Any, Final

from classify_call_type_lambda.delivery.dependencies.dependencies_builder import (
    build_classify_call_type_use_case,
    build_clock,
)
from classify_call_type_lambda.delivery.presenters.call_classification import (
    present_call_classification,
)
from classify_call_type_lambda.domain.errors import (
    DataSourceUnavailableError,
    DomainError,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TOOL_NAME: Final = "classify_call_type"
_TOOL_NAME_DELIMITER: Final = "___"
UNEXPECTED_ERROR_MESSAGE: Final = (
    "Unexpected internal error ranking call reasons. "
    "Greet the customer and ask how you can help."
)
_WRONG_TOOL_MESSAGE: Final = (
    f"This function only serves the '{TOOL_NAME}' tool. "
    "Don't retry; offer a hand-off to a human agent."
)


USE_CASE = build_classify_call_type_use_case(os.environ)
CLOCK = build_clock(os.environ)


def handler(event: object, context: object) -> dict[str, Any]:
    """Rank the likely reasons the customer is calling, for the agent.

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

    try:
        if USE_CASE is None or CLOCK is None:
            raise DataSourceUnavailableError()
        body = present_call_classification(
            USE_CASE.execute(_customer_id(event), as_of=CLOCK.now())
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
        "%s returned reasons=%s (unavailable=%s)",
        TOOL_NAME,
        [item["reason"] for item in body["reasons"]],
        body["unavailable"],
    )
    return {"content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]}


def _customer_id(event: object) -> object:
    """Return the event's customer_id as it came, or None for a non-object event.

    The use case validates and cleans it, so a bad value becomes the
    customer_id InvalidInputError message.
    """
    if not isinstance(event, Mapping):
        return None
    return event.get("customer_id")


def _tool_name(context: object) -> str | None:
    """Return the tool name without its ``<target>___`` prefix, or None if absent."""
    try:
        full_name = context.client_context.custom["bedrockAgentCoreToolName"]  # type: ignore[attr-defined]
    except (AttributeError, KeyError, TypeError):
        return None
    if not isinstance(full_name, str):
        return None
    return full_name.rpartition(_TOOL_NAME_DELIMITER)[2]
