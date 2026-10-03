"""Session start: put get_session_context's result in the session's history.

On a session's first turn (no messages restored from AgentCore Memory), the
agent code calls get_session_context directly. Strands records a direct tool
call in the agent's messages as a tool call and its result, and the memory
session manager saves them, so later turns still have the context. The model
reads it as tool output, not as text the customer typed.

Nothing here imports strands, so the tests drive it with a fake agent.
"""

import logging

logger = logging.getLogger(__name__)

# Gateway tools are registered as gateway_<target>___<tool>; match on the tool part.
SESSION_CONTEXT_TOOL_SUFFIX = "___get_session_context"


def load_session_context(agent, customer_id: str) -> None:
    """On a session's first turn, call get_session_context so its result is in the history.

    A failure is logged and the turn goes on without the context: the model can
    still call get_session_context itself. Strands returns a failed tool call (a
    Lambda error, a Cedar denial) as a result with status "error" rather than
    raising, so the result's status is checked too.

    Args:
        agent: The Strands agent, built with its memory session manager, so
            agent.messages holds the session's restored history.
        customer_id (str): The customer_id from the Gateway machine token, or ""
            when the user has no linked customer.
    """
    if not customer_id or agent.messages:
        return
    try:
        name = next(
            (n for n in agent.tool_names if n.endswith(SESSION_CONTEXT_TOOL_SUFFIX)),
            None,
        )
        if name is None:
            logger.warning(
                "[SESSION-START] get_session_context is not on the Gateway; skipping"
            )
            return
        result = getattr(agent.tool, name)(customer_id=customer_id)
    except Exception:
        logger.exception(
            "[SESSION-START] get_session_context failed; continuing without it"
        )
        return
    if result.get("status") != "success":
        logger.warning(
            "[SESSION-START] get_session_context returned an error; continuing without it"
        )
        return
    logger.info("[SESSION-START] Loaded the session context with %s", name)
