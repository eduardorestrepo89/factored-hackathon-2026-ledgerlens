"""Session start: get_session_context and classify_call_type, fetched once per session.

Replaces tools/session_start.py, which recorded get_session_context into
agent.messages, where the conversation window drops it and summarization
rewords it.

The results are kept in agent.state, which AgentCoreMemorySessionManager saves
with the session, and rendered into the system prompt on every turn. The system
prompt sits outside agent.messages, so the conversation manager never trims or
summarizes it.

Checked against strands-agents 1.32.0 and bedrock-agentcore 1.4.7: agent.state
is restored when the Agent is constructed and saved when its version changes;
the system prompt is not saved with the session. The tools are streamed straight
from the registry, not through agent.tool: agent.tool runs conversation
management after every call (strands/tools/_caller.py), and two concurrent
calls could each summarize the same messages.
"""

import asyncio
import json
import logging

from tools.system_prompt import build_system_prompt

logger = logging.getLogger(__name__)

SESSION_CONTEXT_KEY = "session_context"

# Gateway tools are registered as gateway_<target>___<tool>; match on the tool part.
SESSION_CONTEXT_TOOL_SUFFIX = "___get_session_context"
CLASSIFY_CALL_TYPE_TOOL_SUFFIX = "___classify_call_type"


def _body(name: str, text: str, key: str) -> dict:
    """Parse a tool's JSON body; raise unless it is a dict holding ``key``."""
    body = json.loads(text)
    # The Gateway may pass the Lambda's own {"content": [{"text": ...}]} on as text.
    if (
        isinstance(body, dict)
        and isinstance(body.get("content"), list)
        and body["content"]
    ):
        body = json.loads(body["content"][0]["text"])
    # The Lambdas return failures as {"error": ...}; that must never be saved as
    # context, or it would sit in the system prompt for the whole session.
    if not isinstance(body, dict) or "error" in body or key not in body:
        raise ValueError(f"{name} returned no {key!r}")
    return body


async def _call_tool(agent, suffix: str, key: str, customer_id: str) -> dict:
    registry = agent.tool_registry.registry
    name = next((n for n in registry if n.endswith(suffix)), None)
    if name is None:
        raise LookupError(f"{suffix} is not on the Gateway")
    tool_use = {
        "toolUseId": f"session-start{suffix}",
        "name": name,
        "input": {"customer_id": customer_id},
    }
    result = None
    async for event in registry[name].stream(tool_use, {}):
        result = event.get("tool_result", result)
    # Strands returns a failed call (Lambda error, Cedar denial) as status "error".
    if result is None or result.get("status") != "success":
        raise RuntimeError(f"{name} returned an error")
    return _body(name, result["content"][0]["text"], key)


async def _fetch_session_context(agent, customer_id: str) -> dict | None:
    """Call both tools in parallel on the agent's Gateway client.

    Returns None unless both succeed. Logs carry no context content.
    """
    customer, likely_reasons = await asyncio.gather(
        # Each body's key comes from its Lambda's presenter.
        _call_tool(agent, SESSION_CONTEXT_TOOL_SUFFIX, "customer", customer_id),
        _call_tool(agent, CLASSIFY_CALL_TYPE_TOOL_SUFFIX, "reasons", customer_id),
        return_exceptions=True,
    )
    if isinstance(customer, Exception) or isinstance(likely_reasons, Exception):
        logger.warning("[SESSION-START] Bootstrap failed; will retry next turn")
        return None
    return {"customer": customer, "likely_reasons": likely_reasons}


async def apply_session_context(agent, customer_id: str) -> None:
    """Load the session context once per session and render it into the system prompt.

    Args:
        agent: The Strands agent, built with its memory session manager, so
            agent.state holds whatever an earlier turn saved.
        customer_id (str): The customer_id from the Gateway machine token, or ""
            when the user has no linked customer (then nothing happens).
    """
    if not customer_id:
        return
    session_context = agent.state.get(SESSION_CONTEXT_KEY)
    if session_context is None:
        session_context = await _fetch_session_context(agent, customer_id)
        if session_context is not None:
            agent.state.set(SESSION_CONTEXT_KEY, session_context)
    agent.system_prompt = build_system_prompt(customer_id, session_context)
