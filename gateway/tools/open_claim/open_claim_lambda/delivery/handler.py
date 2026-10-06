"""Lambda handler for the ``open_claim`` Gateway tool.

Handler string: ``open_claim_lambda/delivery/handler.handler``.

Input: the tool arguments as the event (see
``gateway/tools/open_claim/tool_spec.json``); the tool name arrives in
``context.client_context.custom["bedrockAgentCoreToolName"]`` with a
``<target>___`` prefix. Every argument is passed to the use case bare, exactly
as it came; the use case validates and cleans them.

Output: ``{"content": [{"type": "text", "text": <JSON>}]}`` on success, or
``{"error": <agent-facing message>}``. Raw exception text is never returned: it
could leak SQL, hosts or driver details to the model.

The use case and its whole graph are built once, when the module loads, by
dependencies_builder; a warm container reuses them. AS_OF (optional) is read
once into CLOCK, and CLOCK.now() is the claims' creation date on every call. An
invalid AS_OF answers every request with DataSourceUnavailableError's message.
"""

import json
import logging
import os
from collections.abc import Mapping
from typing import Any, Final

from open_claim_lambda.delivery.dependencies.dependencies_builder import (
    build_clock,
    build_open_claim_use_case,
)
from open_claim_lambda.delivery.presenters.claims import present_claims
from open_claim_lambda.domain.errors import DataSourceUnavailableError, DomainError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TOOL_NAME: Final = "open_claim"
_TOOL_NAME_DELIMITER: Final = "___"
UNEXPECTED_ERROR_MESSAGE: Final = (
    "Unexpected internal error opening the claim. Offer a hand-off to a human agent."
)
_WRONG_TOOL_MESSAGE: Final = (
    f"This function only serves the '{TOOL_NAME}' tool. "
    "Don't retry; offer a hand-off to a human agent."
)


USE_CASE = build_open_claim_use_case(os.environ)
CLOCK = build_clock(os.environ)


def handler(event: object, context: object) -> dict[str, Any]:
    """Open fraud or dispute claims for the agent.

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
        body = present_claims(
            USE_CASE.execute(
                customer_id=args.get("customer_id"),
                transaction_ids=args.get("transaction_ids"),
                claim_type=args.get("claim_type"),
                customer_statement=args.get("customer_statement"),
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
        "%s: %d claims (%d already existed): %s",
        TOOL_NAME,
        len(body["claims"]),
        sum(claim["already_existed"] for claim in body["claims"]),
        ", ".join(claim["claim_id"] for claim in body["claims"]),
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
