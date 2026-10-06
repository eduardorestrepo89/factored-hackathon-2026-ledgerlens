"""Tests for the Cedar policy custom resource creating one policy per statement.

The Lambda's file is ``infra-cdk/lambdas/cedar-policy/index.py``. It builds a
``bedrock-agentcore-control`` client at import time, so ``boto3.client`` is
patched with a mock before the module is loaded from its path. CreatePolicy
takes one Cedar statement per policy, so a document with several statements
becomes several policies.
"""

import importlib.util
from pathlib import Path
from unittest import mock

import pytest

_INDEX_PATH = (
    Path(__file__).resolve().parents[3]
    / "infra-cdk"
    / "lambdas"
    / "cedar-policy"
    / "index.py"
)

# The real engine name: f"{stack_name_base.replace('-', '_')}_policy_engine".
ENGINE_NAME = "ledgerlens_bank_assistant_policy_engine"
ENGINE_ID = "ledgerlens_bank_assistant_policy_engine-abcdefghij"
GATEWAY_ID = "gateway-1"

PERMIT = (
    "permit (\n"
    "  principal is AgentCore::OAuthUser,\n"
    '  action == AgentCore::Action::"sample-tool-target___text_analysis_tool",\n'
    '  resource == AgentCore::Gateway::"arn:aws:gateway/g-1"\n'
    ");"
)
FORBID = (
    "forbid (\n"
    "  principal is AgentCore::OAuthUser,\n"
    "  action,\n"
    '  resource == AgentCore::Gateway::"arn:aws:gateway/g-1"\n'
    ")\n"
    'when { principal.getTag("department") == "guest" };'
)


@pytest.fixture
def cedar_policy():
    """Load a fresh copy of the custom resource with a mock AgentCore client."""
    with mock.patch("boto3.client") as client_factory:
        client_factory.return_value = mock.MagicMock()
        spec = importlib.util.spec_from_file_location("cedar_policy_index", _INDEX_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    module.client.create_policy.side_effect = [
        {"policyId": f"policy-{n}"} for n in range(1, 10)
    ]
    module.client.list_policies.return_value = {"policies": []}
    module.client.get_gateway.return_value = {
        "status": "READY",
        "policyEngineConfiguration": {"arn": "arn:engine"},
    }
    module.client.create_policy_engine.return_value = {"policyEngineId": ENGINE_ID}
    module.client.get_policy_engine.return_value = {"policyEngineArn": "arn:engine"}
    return module


def props(document):
    """Build the custom resource properties for a policy document."""
    return {
        "GatewayIdentifier": GATEWAY_ID,
        "PolicyDocument": document,
        "PolicyEngineName": ENGINE_NAME,
        "Description": "LedgerLens policy",
    }


def created_statements(cedar_policy):
    """Return the Cedar statement of every create_policy call, in order."""
    return [
        call.kwargs["definition"]["cedar"]["statement"]
        for call in cedar_policy.client.create_policy.call_args_list
    ]


def created_names(cedar_policy):
    """Return the name of every create_policy call, in order."""
    return [
        call.kwargs["name"] for call in cedar_policy.client.create_policy.call_args_list
    ]


def test_one_statement_is_one_statement(cedar_policy):
    assert cedar_policy.split_cedar_statements(PERMIT) == [PERMIT]


def test_two_statements_are_split(cedar_policy):
    document = f"{PERMIT}\n\n{FORBID}\n"

    assert cedar_policy.split_cedar_statements(document) == [PERMIT, FORBID]


def test_semicolon_in_a_string_does_not_split(cedar_policy):
    statement = (
        'forbid (principal, action, resource)\nwhen { context.input.note == "a;b" };'
    )

    assert cedar_policy.split_cedar_statements(statement) == [statement]


def test_escaped_quote_in_a_string_does_not_end_it(cedar_policy):
    statement = (
        "forbid (principal, action, resource)\n"
        'when { context.input.note == "say \\"hi;\\"" };'
    )

    assert cedar_policy.split_cedar_statements(statement) == [statement]


def test_comments_are_dropped(cedar_policy):
    document = (
        "// rule 1\n"
        "permit (principal, action, resource) // trailing; comment\n"
        "when { true };\n"
    )

    assert cedar_policy.split_cedar_statements(document) == [
        "permit (principal, action, resource)\nwhen { true };"
    ]


def test_double_slash_in_a_string_is_not_a_comment(cedar_policy):
    statement = (
        "permit (principal, action, resource)\n"
        'when { context.input.url == "https://example.com" };'
    )

    assert cedar_policy.split_cedar_statements(statement) == [statement]


def test_text_without_a_closing_semicolon_is_rejected(cedar_policy):
    with pytest.raises(ValueError, match="semicolon"):
        cedar_policy.split_cedar_statements(
            f"{PERMIT}\npermit (principal, action, resource)"
        )


def test_document_without_statements_is_rejected(cedar_policy):
    with pytest.raises(ValueError, match="no Cedar statements"):
        cedar_policy.split_cedar_statements("// only a comment\n")


def test_policy_names_fit_the_api_limit(cedar_policy):
    names = [cedar_policy.policy_name(ENGINE_NAME, n) for n in range(1, 21)]

    assert all(len(name) <= 48 for name in names)


def test_policy_names_match_the_api_pattern(cedar_policy):
    name = cedar_policy.policy_name(ENGINE_NAME, 1)

    assert name[0].isalpha()
    assert all(c.isalnum() or c == "_" for c in name)


def test_policy_names_in_one_deploy_are_unique(cedar_policy):
    names = [cedar_policy.policy_name(ENGINE_NAME, n) for n in range(1, 21)]

    assert len(set(names)) == len(names)


def test_create_makes_one_policy_per_statement(cedar_policy):
    result = cedar_policy.handle_create(props(f"{PERMIT}\n{FORBID}"))

    assert created_statements(cedar_policy) == [PERMIT, FORBID]
    assert result["PhysicalResourceId"] == f"{ENGINE_ID}|policy-1"
    assert result["Data"]["PolicyId"] == "policy-1"


def test_create_waits_for_every_policy(cedar_policy):
    cedar_policy.handle_create(props(f"{PERMIT}\n{FORBID}"))

    waited = [
        call.kwargs.get("policyId")
        for call in cedar_policy.client.get_waiter.return_value.wait.call_args_list
    ]
    assert "policy-1" in waited
    assert "policy-2" in waited


def test_update_replaces_the_policies_with_one_per_statement(cedar_policy):
    event = {"PhysicalResourceId": f"{ENGINE_ID}|old-policy"}

    result = cedar_policy.handle_update(event, props(f"{PERMIT}\n{FORBID}"))

    assert created_statements(cedar_policy) == [PERMIT, FORBID]
    assert result["PhysicalResourceId"] == f"{ENGINE_ID}|old-policy"
    assert result["Data"]["PolicyId"] == "policy-1"


def test_update_deletes_the_new_and_the_old_managed_names(cedar_policy):
    new_name = cedar_policy.policy_name(ENGINE_NAME, 1)
    old_name = f"{ENGINE_NAME}_cp_1700000000"
    cedar_policy.client.list_policies.return_value = {
        "policies": [
            {"policyId": "p-new", "name": new_name},
            {"policyId": "p-old", "name": old_name},
            {"policyId": "p-other", "name": "someone_elses_policy"},
        ]
    }

    cedar_policy.handle_update(
        {"PhysicalResourceId": f"{ENGINE_ID}|old-policy"}, props(PERMIT)
    )

    deleted = [
        call.kwargs["policyId"]
        for call in cedar_policy.client.delete_policy.call_args_list
    ]
    assert "p-new" in deleted
    assert "p-old" in deleted
    assert "p-other" not in deleted


def test_bad_document_fails_before_any_policy_is_created(cedar_policy):
    with pytest.raises(ValueError):
        cedar_policy.handle_update(
            {"PhysicalResourceId": f"{ENGINE_ID}|old-policy"},
            props("permit (principal, action, resource)"),
        )

    cedar_policy.client.delete_policy.assert_not_called()
    cedar_policy.client.create_policy.assert_not_called()
