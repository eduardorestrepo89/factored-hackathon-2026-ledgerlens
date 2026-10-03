"""Unit tests for the Strands agent's system prompt builder.

The module lives at ``patterns/strands-single-agent/tools/system_prompt.py``
and has no runtime dependencies, so it is imported directly.
"""

import hashlib
import importlib
import sys
from pathlib import Path

import pytest

_PATTERN_DIR = Path(__file__).resolve().parents[2] / "patterns" / "strands-single-agent"

CUSTOMER_ID = "CLI-F2DZJYU0POJ9"

# One entry per released prompt version: PROMPT_VERSION -> sha256 of prompt_template().
# Changed the prompt? Bump PROMPT_VERSION in system_prompt.py and add its hash here.
PINNED_PROMPT_HASHES = {
    "v1": "f17e2e64c42b3a77401584aecfb37120e3d08fdeacf71f1e68711d655321bdc7",
}

# Designed in docs/LEDGERLENS_PRODUCT_DESIGN.md §7 but not deployed in v1.
UNAVAILABLE_TOOLS = (
    "classify_call_type",
    "explain_transaction",
    "transaction_fraud_detection",
    "block_credit_card",
    "open_claim",
    "human_agent_hand_off",
)


@pytest.fixture(scope="module")
def system_prompt():
    """Import tools/system_prompt.py from the strands pattern."""
    if str(_PATTERN_DIR) not in sys.path:
        sys.path.insert(0, str(_PATTERN_DIR))
    return importlib.import_module("tools.system_prompt")


def test_linked_customer_id_is_in_the_prompt(system_prompt):
    prompt = system_prompt.build_system_prompt(CUSTOMER_ID)

    assert CUSTOMER_ID in prompt


def test_linked_prompt_says_to_pass_it_on_every_tool_call(system_prompt):
    prompt = system_prompt.build_system_prompt(CUSTOMER_ID)

    assert "customer_id" in prompt
    assert "every tool call" in prompt


def test_linked_prompt_forbids_ids_from_the_user(system_prompt):
    prompt = system_prompt.build_system_prompt(CUSTOMER_ID)

    assert "never use a customer id the user gives" in prompt.lower()


def test_blank_customer_id_says_the_account_is_not_linked(system_prompt):
    prompt = system_prompt.build_system_prompt("")

    assert "not linked" in prompt


def test_blank_customer_id_never_asks_the_user_for_one(system_prompt):
    prompt = system_prompt.build_system_prompt("")

    assert "do not ask the user for a customer id" in prompt.lower()
    assert "every tool call" not in prompt


def test_blank_customer_id_points_to_a_human_agent(system_prompt):
    prompt = system_prompt.build_system_prompt("")

    assert "human agent" in prompt
    # No hand-off tool exists in v1, so the prompt mustn't promise one.
    assert "hand-off" not in prompt


def test_base_prompt_is_always_included(system_prompt):
    for customer_id in (CUSTOMER_ID, ""):
        prompt = system_prompt.build_system_prompt(customer_id)

        assert prompt.startswith(system_prompt.BASE_SYSTEM_PROMPT)


def test_prompt_never_names_a_tool_that_is_not_deployed(system_prompt):
    template = system_prompt.prompt_template()

    for tool in UNAVAILABLE_TOOLS:
        assert tool not in template, f"the prompt names {tool}, which v1 doesn't deploy"


def test_prompt_tells_the_model_to_recover_missing_context(system_prompt):
    # The session-start call can fail, or the sliding window can drop its result.
    prompt = system_prompt.BASE_SYSTEM_PROMPT

    assert "If there is no get_session_context result in this conversation" in prompt
    assert "greet without a name" in prompt


def test_prompt_version_names_this_template(system_prompt):
    digest = hashlib.sha256(system_prompt.prompt_template().encode()).hexdigest()

    assert PINNED_PROMPT_HASHES.get(system_prompt.PROMPT_VERSION) == digest, (
        "The prompt changed: bump PROMPT_VERSION and pin the new hash"
    )
