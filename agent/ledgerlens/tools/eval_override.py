"""Per-session model and base-prompt override for evaluation logins.

The evaluation harness (evals/) compares models and prompt versions against the
deployed agent. A request may carry "eval": {"model_id", "prompt_name",
"system_prompt"}. Only a caller whose runtime JWT lists the Cognito group
"evaluators" gets it, and only for a model in EVAL_MODEL_IDS. Anyone else's
"eval" field is ignored. The text replaces only BASE_SYSTEM_PROMPT: the session
blocks, the customer_id and confirmation hooks, the guardrail and Cedar apply
exactly as for a customer.
Spec: docs/superpowers/specs/2026-10-04-eval-harness-design.md section 4.1.
"""

import hashlib
import logging
import re
from dataclasses import dataclass

from tools.system_prompt import BASE_SYSTEM_PROMPT, PROMPT_VERSION

logger = logging.getLogger(__name__)

EVALUATORS_GROUP = "evaluators"
MAX_PROMPT_CHARS = 40_000
_PROMPT_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}")


class EvalOverrideRejected(ValueError):
    """An evaluator's override is invalid; the request must not run on defaults."""


@dataclass(frozen=True)
class EvalSettings:
    """The model and base prompt one request runs with."""

    model_id: str
    base_prompt: str
    prompt_version: str
    overridden: bool


def parse_allowlist(value: str) -> frozenset[str]:
    """Split EVAL_MODEL_IDS ("a,b") into model ids, dropping blanks."""
    return frozenset(item.strip() for item in value.split(",") if item.strip())


def _groups(claims: dict) -> set[str]:
    groups = claims.get("cognito:groups") or []
    if isinstance(groups, str):
        groups = [groups]
    return {group for group in groups if isinstance(group, str)}


def resolve_eval_settings(
    payload: dict, claims: dict, default_model_id: str, allowlist: frozenset[str]
) -> EvalSettings:
    """Return the settings for one request.

    Args:
        payload: The request body; its optional "eval" object asks for an override.
        claims: The runtime JWT's claims (utils.auth.extract_claims_from_context).
        default_model_id: MODEL_ID, the model customers always get.
        allowlist: parse_allowlist(EVAL_MODEL_IDS).

    Returns:
        EvalSettings: the defaults, or an evaluator's override.

    Raises:
        ValueError: default_model_id is blank (a deployment error).
        EvalOverrideRejected: an evaluator sent an invalid override.
    """
    if not default_model_id:
        raise ValueError("MODEL_ID environment variable is required")
    defaults = EvalSettings(default_model_id, BASE_SYSTEM_PROMPT, PROMPT_VERSION, False)
    request = payload.get("eval")
    if request is None:
        return defaults
    if EVALUATORS_GROUP not in _groups(claims):
        logger.warning("[EVAL] override ignored: not an evaluator sub=%s", claims.get("sub"))
        return defaults
    if not isinstance(request, dict):
        raise EvalOverrideRejected("eval must be an object")

    model_id = request.get("model_id", default_model_id)
    if model_id not in allowlist:
        raise EvalOverrideRejected(f"model_id {model_id!r} is not in EVAL_MODEL_IDS")

    text = request.get("system_prompt")
    if text is None:
        settings = EvalSettings(model_id, BASE_SYSTEM_PROMPT, PROMPT_VERSION, True)
    else:
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_PROMPT_CHARS:
            raise EvalOverrideRejected(
                f"system_prompt must be 1 to {MAX_PROMPT_CHARS} characters of text"
            )
        name = request.get("prompt_name")
        if not isinstance(name, str) or not _PROMPT_NAME.fullmatch(name):
            raise EvalOverrideRejected("prompt_name must match [a-z0-9][a-z0-9._-]{0,31}")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
        settings = EvalSettings(model_id, text, f"{name}-{digest}", True)

    logger.info(
        "[EVAL] override sub=%s model=%s prompt=%s",
        claims.get("sub"),
        settings.model_id,
        settings.prompt_version,
    )
    return settings
