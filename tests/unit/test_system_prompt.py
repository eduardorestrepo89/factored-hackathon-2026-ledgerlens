"""Unit tests for the Strands agent's system prompt builder.

The module lives at ``patterns/strands-single-agent/tools/system_prompt.py``
and has no runtime dependencies, so it is imported directly.
"""

import importlib
import sys
from pathlib import Path

import pytest

_PATTERN_DIR = Path(__file__).resolve().parents[2] / "patterns" / "strands-single-agent"

CUSTOMER_ID = "CLI-F2DZJYU0POJ9"


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


def test_blank_customer_id_offers_a_hand_off(system_prompt):
    prompt = system_prompt.build_system_prompt("")

    assert "hand-off" in prompt


def test_base_prompt_is_always_included(system_prompt):
    for customer_id in (CUSTOMER_ID, ""):
        prompt = system_prompt.build_system_prompt(customer_id)

        assert prompt.startswith(system_prompt.BASE_SYSTEM_PROMPT)
