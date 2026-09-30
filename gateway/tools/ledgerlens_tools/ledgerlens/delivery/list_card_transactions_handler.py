"""Lambda handler for the ``list_card_transactions`` Gateway tool.

Handler string: ``ledgerlens/delivery/list_card_transactions_handler.handler``.

Input: the tool arguments as the event (see
``gateway/tools/list_card_transactions/tool_spec.json``); the tool name arrives in
``context.client_context.custom["bedrockAgentCoreToolName"]`` with a
``<target>___`` prefix, as in ``gateway/tools/sample_tool``.

Output: ``{"content": [{"type": "text", "text": <JSON>}]}`` on success, or
``{"error": <agent-facing message>}``. Unlike the sample tool, raw exception text
is never returned: it could leak SQL, hosts or driver details to the model.

The connector (and its connection) is global, created when the module loads so a
warm container reuses it; build_dependencies() is called per invocation.

TODO(ledgerlens): R1 - no CDK yet: no PythonFunction, Gateway target, VPC, security
  group, secret grant or env vars (DB_ENGINE, DB_SECRET_ARN). The tool can't be
  deployed or called by the agent until the CDK spec lands.
TODO(ledgerlens): R5 - customer_id is trusted from the tool input. Authorization
  depends on a Cedar policy matching it to the token's customer_id claim; neither
  the policy nor the claim exists yet (product design sections 5 and 10).
"""

import json
import logging
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Final

from ledgerlens.delivery.database import build_connector
from ledgerlens.delivery.dependencies.list_card_transactions import (
    build_dependencies,
)
from ledgerlens.delivery.presenters.card_transactions import (
    present_card_transactions,
)
from ledgerlens.delivery.settings import ConfigurationError, DatabaseSettings
from ledgerlens.domain.errors import DataSourceUnavailableError, DomainError
from ledgerlens.domain.value_objects.transaction_filters import TransactionFilters
from ledgerlens.utils.connectors.base import PsycopgConnector

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TOOL_NAME: Final = "list_card_transactions"
_TOOL_NAME_DELIMITER: Final = "___"
UNEXPECTED_ERROR_MESSAGE: Final = (
    "Unexpected internal error listing transactions. Offer a hand-off to a human agent."
)
_WRONG_TOOL_MESSAGE: Final = (
    f"This function only serves the '{TOOL_NAME}' tool. "
    "Don't retry; offer a hand-off to a human agent."
)


def _initialise(
    env: Mapping[str, str],
) -> tuple[DatabaseSettings | None, PsycopgConnector | None]:
    """Load settings and open the global connection at cold start. Never raises.

    A failed connection is only logged: the first request retries it lazily, so
    the Lambda init doesn't crash. Bad configuration yields ``(None, None)`` and
    every request then returns DataSourceUnavailableError's message.
    """
    try:
        settings = DatabaseSettings.from_env(env)
        connector = build_connector(settings)
    except ConfigurationError:
        logger.exception("Invalid database configuration for %s", TOOL_NAME)
        return None, None
    try:
        connector.connection()
    except Exception:
        logger.warning(
            "Cold-start database connection failed; the first request will retry",
            exc_info=True,
        )
    return settings, connector


SETTINGS, CONNECTOR = _initialise(os.environ)


def handler(event: object, context: object) -> dict[str, Any]:
    """Search the customer's card transactions for the agent.

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
        if SETTINGS is None or CONNECTOR is None:
            raise DataSourceUnavailableError()
        use_case = build_dependencies(CONNECTOR, SETTINGS)
        filters = TransactionFilters.from_raw(
            event, today=datetime.now(timezone.utc).date()
        )
        body = present_card_transactions(use_case.execute(filters))
    except DomainError as err:
        logger.warning(
            "%s returned an error: %s", TOOL_NAME, err.message, exc_info=True
        )
        return {"error": err.message}
    except Exception:
        logger.exception("Unexpected error in %s", TOOL_NAME)
        return {"error": UNEXPECTED_ERROR_MESSAGE}

    logger.info(
        "%s returned %d transactions (truncated=%s)",
        TOOL_NAME,
        body["count"],
        body["truncated"],
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
