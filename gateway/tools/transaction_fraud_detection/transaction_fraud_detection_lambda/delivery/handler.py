"""Lambda handler for the ``transaction_fraud_detection`` Gateway tool.

Handler string: ``transaction_fraud_detection_lambda/delivery/handler.handler``.

Input: the tool arguments as the event (see
``gateway/tools/transaction_fraud_detection/tool_spec.json``); the tool name
arrives in ``context.client_context.custom["bedrockAgentCoreToolName"]`` with a
``<target>___`` prefix, as in ``gateway/tools/sample_tool``. The event is
validated by FraudCheckRequest.from_raw before any query runs.

Output: ``{"content": [{"type": "text", "text": <JSON>}]}`` on success, or
``{"error": <agent-facing message>}``. Raw exception text is never returned: it
could leak SQL, hosts or driver details to the model. The score is never
returned or logged; the log line carries only the mode and verdict counts.

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
from collections import Counter
from typing import Any, Final

from transaction_fraud_detection_lambda.delivery.dependencies.dependencies_builder import (  # noqa: E501
    build_clock,
    build_transaction_fraud_detection_use_case,
)
from transaction_fraud_detection_lambda.delivery.presenters.fraud_assessment import (
    present_assessment,
    present_sweep,
)
from transaction_fraud_detection_lambda.domain.entities.fraud_assessment import (
    CardSweep,
)
from transaction_fraud_detection_lambda.domain.errors import (
    DataSourceUnavailableError,
    DomainError,
)
from transaction_fraud_detection_lambda.domain.value_objects.fraud_check_request import (  # noqa: E501
    FraudCheckRequest,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TOOL_NAME: Final = "transaction_fraud_detection"
_TOOL_NAME_DELIMITER: Final = "___"
UNEXPECTED_ERROR_MESSAGE: Final = (
    "Unexpected internal error running the fraud check. "
    "Offer a hand-off to a human agent."
)
_WRONG_TOOL_MESSAGE: Final = (
    f"This function only serves the '{TOOL_NAME}' tool. "
    "Don't retry; offer a hand-off to a human agent."
)


USE_CASE = build_transaction_fraud_detection_use_case(os.environ)
CLOCK = build_clock(os.environ)


def handler(event: object, context: object) -> dict[str, Any]:
    """Check one charge, or sweep one card, for fraud.

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
        request = FraudCheckRequest.from_raw(event)
        result = USE_CASE.execute(request, as_of=CLOCK.now())
        body = (
            present_sweep(result)
            if isinstance(result, CardSweep)
            else present_assessment(result)
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
        "%s mode=%s verdict_counts=%s",
        TOOL_NAME,
        body["mode"],
        _verdict_counts(body),
    )
    return {"content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]}


def _verdict_counts(body: dict[str, Any]) -> dict[str, int]:
    """Count the verdicts in a presented body, sorted by verdict."""
    if body["mode"] == "card":
        verdicts = [item["verdict"] for item in body["flagged"]]
    else:
        verdicts = [body["assessment"]["verdict"]]
    return dict(sorted(Counter(verdicts).items()))


def _tool_name(context: object) -> str | None:
    """Return the tool name without its ``<target>___`` prefix, or None if absent."""
    try:
        full_name = context.client_context.custom["bedrockAgentCoreToolName"]  # type: ignore[attr-defined]
    except (AttributeError, KeyError, TypeError):
        return None
    if not isinstance(full_name, str):
        return None
    return full_name.rpartition(_TOOL_NAME_DELIMITER)[2]
