"""Lambda handler for the ``explain_transaction`` Gateway tool.

Handler string: ``explain_transaction_lambda/delivery/handler.handler``.

Input: the tool arguments as the event (see
``gateway/tools/explain_transaction/tool_spec.json``); the tool name arrives in
``context.client_context.custom["bedrockAgentCoreToolName"]`` with a
``<target>___`` prefix, as in ``gateway/tools/sample_tool``. ``customer_id``
and ``transaction_id`` are passed to the use case bare, exactly as they came;
the use case cleans them.

Output: ``{"content": [{"type": "text", "text": <JSON>}]}`` on success, or
``{"error": <agent-facing message>}``. Only a failure of the core query (the
charge) is an error; a failed habit or app-activity section comes back null and
is named in ``unavailable``. Raw exception text is never returned: it could
leak SQL, hosts or driver details to the model.

The use case and its whole graph (settings, connector, connection, adapters) are
built once, when the module loads, by dependencies_builder; a warm container
reuses them. The handler builds nothing itself.

AS_OF (optional) is read once into CLOCK; "now" is CLOCK.now() on every call,
so a warm container never freezes the real clock. An invalid AS_OF answers every
request with DataSourceUnavailableError's message.
"""

import json
import logging
import os
from collections.abc import Mapping
from typing import Any, Final

from explain_transaction_lambda.delivery.dependencies.dependencies_builder import (
    build_clock,
    build_explain_transaction_use_case,
)
from explain_transaction_lambda.delivery.presenters.transaction_explanation import (
    present_transaction_explanation,
)
from explain_transaction_lambda.domain.errors import (
    DataSourceUnavailableError,
    DomainError,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TOOL_NAME: Final = "explain_transaction"
_TOOL_NAME_DELIMITER: Final = "___"
UNEXPECTED_ERROR_MESSAGE: Final = (
    "Unexpected internal error explaining the charge. "
    "Offer a hand-off to a human agent."
)
_WRONG_TOOL_MESSAGE: Final = (
    f"This function only serves the '{TOOL_NAME}' tool. "
    "Don't retry; offer a hand-off to a human agent."
)


USE_CASE = build_explain_transaction_use_case(os.environ)
CLOCK = build_clock(os.environ)


def handler(event: object, context: object) -> dict[str, Any]:
    """Explain one credit-card charge for the agent.

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
        body = present_transaction_explanation(
            USE_CASE.execute(
                _argument(event, "customer_id"),
                _argument(event, "transaction_id"),
                as_of=CLOCK.now(),
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
        "%s returned explanation (unavailable=%s)", TOOL_NAME, body["unavailable"]
    )
    return {"content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]}


def _argument(event: object, name: str) -> object:
    """Return the event's ``name`` argument as it came, or None for a non-object event.

    The use case validates and cleans it, so a bad value becomes that
    argument's InvalidInputError message.
    """
    if not isinstance(event, Mapping):
        return None
    return event.get(name)


def _tool_name(context: object) -> str | None:
    """Return the tool name without its ``<target>___`` prefix, or None if absent."""
    try:
        full_name = context.client_context.custom["bedrockAgentCoreToolName"]  # type: ignore[attr-defined]
    except (AttributeError, KeyError, TypeError):
        return None
    if not isinstance(full_name, str):
        return None
    return full_name.rpartition(_TOOL_NAME_DELIMITER)[2]
