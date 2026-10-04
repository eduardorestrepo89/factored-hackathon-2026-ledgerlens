"""Bedrock Guardrail settings for the Strands agent's model.

The guardrail itself is defined in infra-cdk/lib/utils/agent-guardrail.ts: it
blocks prompt attacks, harmful content and topics unrelated to banking (code,
general knowledge, entertainment, politics and similar). It masks nothing:
card digits, amounts and merchants reach the customer unchanged. The CDK
backend passes its id and version as GUARDRAIL_ID and GUARDRAIL_VERSION.

Banking requests the agent can't serve (loans, new products) aren't blocked
here: the system prompt declines them and offers a person.
"""

import os


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} environment variable is required")
    return value


def guardrail_settings() -> dict:
    """Return the BedrockModel keyword arguments that attach the agent's guardrail.

    Returns:
        dict: guardrail_* settings for strands.models.BedrockModel.

    Raises:
        ValueError: GUARDRAIL_ID or GUARDRAIL_VERSION is missing or blank. The
            agent never runs without its guardrail.
    """
    return {
        "guardrail_id": _required_env("GUARDRAIL_ID"),
        "guardrail_version": _required_env("GUARDRAIL_VERSION"),
        "guardrail_trace": "enabled",
        # Hold each reply chunk until it's checked, so a blocked reply is never half shown.
        "guardrail_stream_processing_mode": "sync",
        # Check only the customer's newest message, not the history or tool results.
        "guardrail_latest_message": True,
        # Replace a blocked customer message in memory, so the next turn doesn't resend it.
        "guardrail_redact_input": True,
        # Off: Bedrock already replies with the guardrail's blocked message, and
        # redaction would overwrite it with "[Assistant output redacted.]".
        "guardrail_redact_output": False,
    }
