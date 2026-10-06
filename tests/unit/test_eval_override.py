"""Unit tests for the evaluation override gate (agent/ledgerlens/tools/eval_override.py)."""

import importlib
import logging
import re
import sys
from pathlib import Path

import pytest

_PATTERN_DIR = Path(__file__).resolve().parents[2] / "agent" / "ledgerlens"

DEFAULT = "deepseek.v3.2"
GPT = "openai.gpt-oss-120b-1:0"
EVALUATOR = {"sub": "eval-sub", "cognito:groups": ["evaluators"]}
CUSTOMER = {"sub": "demo-sub"}


@pytest.fixture(scope="module")
def mod():
    if str(_PATTERN_DIR) not in sys.path:
        sys.path.insert(0, str(_PATTERN_DIR))
    return importlib.import_module("tools.eval_override")


@pytest.fixture
def allow(mod):
    return mod.parse_allowlist(f"{DEFAULT}, {GPT} ,")


def resolve(mod, allow, request, claims=EVALUATOR):
    return mod.resolve_eval_settings({"prompt": "hola", "eval": request}, claims, DEFAULT, allow)


def test_parse_allowlist_trims_and_drops_blanks(mod):
    assert mod.parse_allowlist(" a, b ,, ") == frozenset({"a", "b"})
    assert mod.parse_allowlist("") == frozenset()


def test_no_eval_field_gives_the_released_defaults(mod, allow):
    settings = mod.resolve_eval_settings({"prompt": "hola"}, EVALUATOR, DEFAULT, allow)

    assert settings == mod.EvalSettings(
        DEFAULT, mod.BASE_SYSTEM_PROMPT, mod.PROMPT_VERSION, False
    )


def test_a_non_evaluator_override_is_ignored_and_logged(mod, allow, caplog):
    request = {"model_id": GPT, "prompt_name": "x", "system_prompt": "P"}
    with caplog.at_level(logging.WARNING):
        settings = resolve(mod, allow, request, claims=CUSTOMER)

    assert (settings.model_id, settings.base_prompt, settings.overridden) == (
        DEFAULT,
        mod.BASE_SYSTEM_PROMPT,
        False,
    )
    assert "not an evaluator" in caplog.text


def test_a_groups_claim_given_as_a_string_still_counts(mod, allow):
    claims = {"sub": "s", "cognito:groups": "evaluators"}

    assert resolve(mod, allow, {"model_id": GPT}, claims=claims).model_id == GPT


def test_an_evaluator_switches_model_and_prompt(mod, allow):
    request = {"model_id": GPT, "prompt_name": "v11", "system_prompt": "NEW POLICY"}

    settings = resolve(mod, allow, request)

    assert (settings.model_id, settings.base_prompt, settings.overridden) == (
        GPT,
        "NEW POLICY",
        True,
    )
    assert re.fullmatch(r"v11-[0-9a-f]{8}", settings.prompt_version)


def test_the_prompt_version_hash_follows_the_text(mod, allow):
    a = resolve(mod, allow, {"prompt_name": "v11", "system_prompt": "A"})
    b = resolve(mod, allow, {"prompt_name": "v11", "system_prompt": "B"})

    assert a.prompt_version != b.prompt_version


def test_an_evaluator_may_switch_only_the_model(mod, allow):
    settings = resolve(mod, allow, {"model_id": GPT})

    assert settings.base_prompt == mod.BASE_SYSTEM_PROMPT
    assert settings.prompt_version == mod.PROMPT_VERSION
    assert settings.overridden


def test_a_prompt_at_the_size_limit_is_accepted(mod, allow):
    text = "x" * mod.MAX_PROMPT_CHARS

    assert resolve(mod, allow, {"prompt_name": "big", "system_prompt": text}).base_prompt == text


@pytest.mark.parametrize(
    "request_, message",
    [
        ("not-a-dict", "must be an object"),
        ({"model_id": "anthropic.claude-x"}, "not in EVAL_MODEL_IDS"),
        ({"system_prompt": "   ", "prompt_name": "v11"}, "system_prompt"),
        ({"system_prompt": "x" * 40_001, "prompt_name": "v11"}, "system_prompt"),
        ({"system_prompt": 7, "prompt_name": "v11"}, "system_prompt"),
        ({"system_prompt": "P"}, "prompt_name"),
        ({"system_prompt": "P", "prompt_name": "V11"}, "prompt_name"),
        ({"system_prompt": "P", "prompt_name": "a" * 33}, "prompt_name"),
    ],
)
def test_an_invalid_evaluator_request_is_rejected(mod, allow, request_, message):
    with pytest.raises(mod.EvalOverrideRejected, match=message):
        resolve(mod, allow, request_)


def test_a_blank_default_model_is_a_configuration_error(mod, allow):
    with pytest.raises(ValueError, match="MODEL_ID"):
        mod.resolve_eval_settings({"prompt": "hola"}, CUSTOMER, "", allow)
