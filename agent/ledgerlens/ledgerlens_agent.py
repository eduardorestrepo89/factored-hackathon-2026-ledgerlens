"""Strands agent with Gateway MCP tools and Memory."""

import json
import logging
import os

from bedrock_agentcore.memory.integrations.strands.config import (
    AgentCoreMemoryConfig,
    RetrievalConfig,
)
from bedrock_agentcore.memory.integrations.strands.session_manager import (
    AgentCoreMemorySessionManager,
)
from bedrock_agentcore.runtime import BedrockAgentCoreApp, RequestContext
from strands import Agent
from strands.models import BedrockModel
from tools.confirmation_hook import ConfirmationHook, confirmation_events, resume_prompt
from tools.conversation_memory import create_conversation_manager
from tools.customer_id_hook import CustomerIdHook
from tools.eval_override import (
    EvalOverrideRejected,
    EvalSettings,
    parse_allowlist,
    resolve_eval_settings,
)
from tools.gateway import create_gateway_mcp_client
from tools.guardrail import guardrail_settings
from tools.leaked_markup import LeakedMarkupFilter
from tools.mcp_registry import build_registry_mcp_clients, is_discovery_enabled
from tools.session_context import apply_session_context
from tools.system_prompt import build_system_prompt
from utils.auth import (
    extract_claims_from_context,
    extract_customer_id_from_token,
    extract_user_id_from_context,
    get_gateway_access_token,
)

logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()


def _create_session_manager(
    user_id: str, session_id: str
) -> AgentCoreMemorySessionManager:
    """Create an AgentCore memory session manager, optionally with long-term semantic retrieval.

    When the USE_LONG_TERM_MEMORY environment variable is "true", configures retrieval
    from the /facts/{actorId} namespace so the agent recalls facts across sessions.
    When false (default), only short-term memory (conversation history) is active,
    avoiding the additional storage and retrieval costs of long-term memory.

    Args:
        user_id: Unique identifier for the user (actor), extracted from the JWT sub claim.
        session_id: Unique identifier for the current conversation session.

    Returns:
        An AgentCoreMemorySessionManager bound to the user and session.
    """
    memory_id = os.environ.get("MEMORY_ID")
    if not memory_id:
        raise ValueError("MEMORY_ID environment variable is required")

    use_ltm = os.environ.get("USE_LONG_TERM_MEMORY", "false").lower() == "true"

    top_k = int(os.environ.get("LTM_TOP_K", "10"))
    relevance_score = float(os.environ.get("LTM_RELEVANCE_SCORE", "0.3"))

    # Only pass retrieval_config when LTM is explicitly enabled.
    # Omitting it means the session manager uses short-term memory only,
    # which avoids the $0.50/1,000 retrieval and $0.75/1,000 storage costs.
    retrieval_config = (
        {
            "/facts/{actorId}": RetrievalConfig(
                top_k=top_k,
                relevance_score=relevance_score,
            )
        }
        if use_ltm
        else None
    )

    config = AgentCoreMemoryConfig(
        memory_id=memory_id,
        session_id=session_id,
        actor_id=user_id,
        retrieval_config=retrieval_config,
    )
    return AgentCoreMemorySessionManager(
        agentcore_memory_config=config,
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    )


# Per-model BedrockModel settings on top of the defaults in create_strands_agent.
# gpt-oss reasons before it answers, so it needs room for those tokens.
# ponytail: fixed table; tune from the eval pilot's stop reasons (a change needs a deploy).
MODEL_SETTINGS: dict[str, dict] = {
    "openai.gpt-oss-120b-1:0": {"max_tokens": 8192},
}


def create_strands_agent(
    user_id: str,
    session_id: str,
    access_token: str,
    customer_id: str,
    settings: EvalSettings,
) -> Agent:
    """Create a Strands agent with Gateway tools and memory.

    Args:
        user_id: The authenticated user's ID (JWT sub claim).
        session_id: The current conversation session ID.
        access_token: The Gateway access token for this request.
        customer_id: The customer_id claim from access_token, or "" when the
            user has no linked customer.
        settings: The model and base prompt for this request: MODEL_ID and
            BASE_SYSTEM_PROMPT unless an evaluation login overrides them
            (tools/eval_override.py).
    """
    # The guardrail blocks prompt attacks and topics unrelated to banking; it masks nothing.
    bedrock_model = BedrockModel(
        model_id=settings.model_id,
        temperature=0.1,
        **MODEL_SETTINGS.get(settings.model_id, {}),
        **guardrail_settings(),
    )

    session_manager = _create_session_manager(user_id, session_id)

    gateway_client = create_gateway_mcp_client(access_token)

    # Base tools: the Gateway MCP client only. Code Interpreter isn't used: it
    # isn't needed for card questions and is extra risk in a banking context.
    tools: list = [gateway_client]

    # Auto-connect MCP servers discovered from the AWS Agent Registry (opt-in via
    # MCP_REGISTRY_DISCOVERY_ENABLED). Each discovered public streamable-HTTP
    # server becomes a live MCPClient tool provider on the agent. Fail-soft: any
    # discovery/config error yields zero extra clients and the agent still runs
    # on its built-in and gateway tools. (Misconfiguration is caught loudly at
    # deploy time by the CDK config-manager validation, so
    # this runtime guard is defense-in-depth, not the primary check.)
    if is_discovery_enabled():
        try:
            tools.extend(build_registry_mcp_clients())
        except Exception:
            logger.exception(
                "[MCP-REGISTRY] Registry discovery failed; continuing without registry tools"
            )

    return Agent(
        name="strands_agent",
        system_prompt=build_system_prompt(customer_id, base=settings.base_prompt),
        tools=tools,
        model=bedrock_model,
        session_manager=session_manager,
        # Short-term memory window and optional summarization, from STM_* env vars.
        conversation_manager=create_conversation_manager(),
        # In order: overwrite customer_id with the token's value, then pause a card
        # block, claim or hand-off until the customer taps Yes or No.
        hooks=[CustomerIdHook(customer_id), ConfirmationHook()],
        trace_attributes={
            "user.id": user_id,
            "session.id": session_id,
            # Let evaluation and observability tell models and prompt versions apart.
            "model.id": settings.model_id,
            "prompt.version": settings.prompt_version,
        },
    )


@app.entrypoint
async def invocations(payload, context: RequestContext):
    """Main entrypoint — called by AgentCore Runtime on each request.

    Extracts user ID from the validated JWT token (not the payload body)
    to prevent impersonation via prompt injection.
    """
    user_query = payload.get("prompt")
    session_id = payload.get("runtimeSessionId")

    if not all([user_query, session_id]):
        yield {
            "status": "error",
            "error": "Missing required fields: prompt or runtimeSessionId",
        }
        return

    try:
        claims = extract_claims_from_context(context)
        user_id = extract_user_id_from_context(context)
        try:
            settings = resolve_eval_settings(
                payload,
                claims,
                os.environ.get("MODEL_ID", ""),
                parse_allowlist(os.environ.get("EVAL_MODEL_IDS", "")),
            )
        except EvalOverrideRejected as e:
            yield {"status": "error", "error": f"eval override rejected: {e}"}
            return
        # One token per request: the agent reads customer_id from the same token
        # the Gateway checks with Cedar.
        access_token = get_gateway_access_token(user_id)
        customer_id = extract_customer_id_from_token(access_token)
        agent = create_strands_agent(
            user_id, session_id, access_token, customer_id, settings
        )
        logger.info(
            "[PROMPT] version=%s model=%s session=%s",
            settings.prompt_version,
            settings.model_id,
            session_id,
        )
        # Session context: fetched once per session into agent.state, then rendered
        # into the system prompt every turn, out of reach of the conversation window.
        await apply_session_context(agent, customer_id, settings.base_prompt)

        # A paused claim or hand-off resumes with the customer's answer instead of a prompt.
        # ponytail: _interrupt_state is Strands-internal (1.32.0); it's the only way to
        # tell, before streaming, that the agent waits on an answer.
        prompt = user_query
        if agent._interrupt_state.activated:
            prompt = resume_prompt(list(agent._interrupt_state.interrupts), payload)

        markup = LeakedMarkupFilter()
        async for event in agent.stream_async(prompt):
            for confirmation in confirmation_events(event):
                yield confirmation
            for clean in markup.clean(json.loads(json.dumps(dict(event), default=str))):
                yield clean

    except Exception as e:
        logger.exception("Agent run failed")
        yield {"status": "error", "error": str(e)}


if __name__ == "__main__":
    app.run()
