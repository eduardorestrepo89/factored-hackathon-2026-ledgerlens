"""Unit tests for evals/cases.py and the shipped cases and prompts."""

import importlib
import sys
from pathlib import Path

import pytest

from evals import cases as cases_mod

_PATTERN_DIR = Path(__file__).resolve().parents[3] / "agent" / "ledgerlens"


def write(tmp_path, text):
    path = tmp_path / "cases.yaml"
    path.write_text(text, encoding="utf-8")
    return path


MINIMAL = """
- id: X1
  evaluation: E9
  title: t
  persona: P06
  turns: ["hola"]
  confirmations: []
  checks: [{check: no_write_proposal}]
  assertions: ["a"]
"""


def test_the_shipped_cases_load():
    loaded = cases_mod.load_cases()

    assert [c["id"] for c in loaded] == [
        "E1a",
        "E1b",
        "E2a",
        "E2b",
        "E3",
        "E4a",
        "E4b",
        "E5a",
        "E5b",
        "E5c",
    ]
    assert all(c["customer_id"].startswith("CLI-") for c in loaded)


def test_the_released_version_file_is_the_released_prompt():
    if str(_PATTERN_DIR) not in sys.path:
        sys.path.insert(0, str(_PATTERN_DIR))
    system_prompt = importlib.import_module("tools.system_prompt")

    assert (
        cases_mod.load_prompt(system_prompt.PROMPT_VERSION)
        == system_prompt.BASE_SYSTEM_PROMPT
    )


def test_prompt_files_are_read_with_lf_and_no_trailing_newline(tmp_path):
    (tmp_path / "v11.md").write_bytes(b"LINE ONE\r\nLINE TWO\r\n")

    assert cases_mod.load_prompt("v11", prompts_dir=tmp_path) == "LINE ONE\nLINE TWO"


def test_a_bad_prompt_name_is_refused(tmp_path):
    with pytest.raises(cases_mod.CaseError, match="prompt name"):
        cases_mod.load_prompt("../secrets", prompts_dir=tmp_path)


def test_a_minimal_case_gets_its_customer_id(tmp_path):
    [case] = cases_mod.load_cases(write(tmp_path, MINIMAL))

    assert case["customer_id"] == "CLI-PV0OIEA8DAAE"
    assert case["expected_tools"] == []


@pytest.mark.parametrize(
    "replace, insert, message",
    [
        ("persona: P06", "persona: P99", "unknown persona"),
        ('turns: ["hola"]', "turns: []", "turns"),
        (
            "confirmations: []",
            'confirmations: [{tool: block_credit_card, answer: "yes"}]',
            "shared database",
        ),
        (
            "confirmations: []",
            "confirmations: [{tool: human_agent_hand_off, answer: yes}]",
            "quote",
        ),
        (
            "confirmations: []",
            'confirmations: [{tool: refund, answer: "no"}]',
            "confirmation tool",
        ),
        (
            "confirmations: []",
            "confirmations: [{tool: open_claim, answer: maybe}]",
            "answer must be",
        ),
        ("checks: [{check: no_write_proposal}]", "checks: []", "checks"),
        ('assertions: ["a"]', "assertions: []", "assertions"),
    ],
)
def test_invalid_cases_are_refused(tmp_path, replace, insert, message):
    with pytest.raises(cases_mod.CaseError, match=message):
        cases_mod.load_cases(write(tmp_path, MINIMAL.replace(replace, insert)))


def test_duplicate_ids_are_refused(tmp_path):
    with pytest.raises(cases_mod.CaseError, match="duplicate"):
        cases_mod.load_cases(write(tmp_path, MINIMAL + MINIMAL))


def test_expected_tools_must_be_model_side_names(tmp_path):
    text = MINIMAL + "  expected_tools: [human_agent_hand_off]\n"
    with pytest.raises(cases_mod.CaseError, match="expected_tools"):
        cases_mod.load_cases(write(tmp_path, text))
