"""Unit tests for the Strands agent's Bedrock Guardrail settings.

The module lives at ``patterns/strands-single-agent/tools/guardrail.py`` and is
configured from GUARDRAIL_ID and GUARDRAIL_VERSION, which the CDK backend sets.
"""

import importlib
import json
import sys
from pathlib import Path

import boto3
import pytest
from strands.models import BedrockModel

_PATTERN_DIR = Path(__file__).resolve().parents[2] / "patterns" / "strands-single-agent"

GUARDRAIL_ID = "abc123xyz"
GUARDRAIL_VERSION = "3"


@pytest.fixture(scope="module")
def guardrail():
    """Import tools/guardrail.py from the strands pattern."""
    if str(_PATTERN_DIR) not in sys.path:
        sys.path.insert(0, str(_PATTERN_DIR))
    return importlib.import_module("tools.guardrail")


@pytest.fixture(autouse=True)
def guardrail_env(monkeypatch):
    monkeypatch.setenv("GUARDRAIL_ID", GUARDRAIL_ID)
    monkeypatch.setenv("GUARDRAIL_VERSION", GUARDRAIL_VERSION)


def test_settings_name_the_deployed_guardrail(guardrail):
    settings = guardrail.guardrail_settings()

    assert settings["guardrail_id"] == GUARDRAIL_ID
    assert settings["guardrail_version"] == GUARDRAIL_VERSION


def test_settings_check_only_the_customers_latest_message(guardrail):
    # Re-checking the history and tool results every turn would block replies
    # about the customer's own transactions.
    assert guardrail.guardrail_settings()["guardrail_latest_message"] is True


def test_settings_check_replies_before_they_stream(guardrail):
    # "sync" holds each chunk until the guardrail has checked it, so a blocked
    # reply is never half shown.
    assert guardrail.guardrail_settings()["guardrail_stream_processing_mode"] == "sync"


def test_settings_trace_what_the_guardrail_did(guardrail):
    assert guardrail.guardrail_settings()["guardrail_trace"] == "enabled"


def test_settings_drop_a_blocked_customer_message_from_memory(guardrail):
    # Redaction replaces only a message the guardrail blocked; it masks nothing in
    # messages that pass, so card digits, amounts and merchants stay visible.
    assert guardrail.guardrail_settings()["guardrail_redact_input"] is True


def test_settings_keep_the_guardrails_blocked_message_as_the_reply(guardrail):
    # Output redaction would overwrite the guardrail's trilingual blocked message
    # with Strands' "[Assistant output redacted.]".
    assert guardrail.guardrail_settings()["guardrail_redact_output"] is False


@pytest.fixture
def model(guardrail):
    # Dummy credentials keep the test offline and away from the local AWS login.
    session = boto3.Session(
        aws_access_key_id="test", aws_secret_access_key="test", region_name="us-east-1"
    )
    return BedrockModel(
        model_id="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        boto_session=session,
        **guardrail.guardrail_settings(),
    )


def test_settings_are_accepted_by_the_bedrock_model(model):
    config = model.get_config()

    assert config["guardrail_id"] == GUARDRAIL_ID
    assert config["guardrail_latest_message"] is True


def test_tool_results_are_never_sent_to_the_guardrail(model):
    # After a tool call the last message is the tool result. Bedrock checks every
    # message when none is wrapped in guardContent, so the customer's question must
    # stay wrapped, or the guardrail would scan transaction data.
    messages = [
        {"role": "user", "content": [{"text": "¿Qué es este cargo de Netflix?"}]},
        {
            "role": "assistant",
            "content": [{"toolUse": {"toolUseId": "t1", "name": "list", "input": {}}}],
        },
        {
            "role": "user",
            "content": [
                {
                    "toolResult": {
                        "toolUseId": "t1",
                        "status": "success",
                        "content": [{"text": "NETFLIX USD 15.99 fraud flag"}],
                    }
                }
            ],
        },
    ]

    request = model._format_request(messages)

    assert request["messages"][0]["content"] == [
        {"guardContent": {"text": {"text": "¿Qué es este cargo de Netflix?"}}}
    ]
    assert "guardContent" not in json.dumps(request["messages"][2])


@pytest.mark.parametrize("name", ["GUARDRAIL_ID", "GUARDRAIL_VERSION"])
def test_missing_env_var_fails_loudly(guardrail, monkeypatch, name):
    # The agent must never run without its guardrail.
    monkeypatch.delenv(name)

    with pytest.raises(ValueError, match=name):
        guardrail.guardrail_settings()


@pytest.mark.parametrize("name", ["GUARDRAIL_ID", "GUARDRAIL_VERSION"])
def test_blank_env_var_fails_loudly(guardrail, monkeypatch, name):
    monkeypatch.setenv(name, "  ")

    with pytest.raises(ValueError, match=name):
        guardrail.guardrail_settings()
