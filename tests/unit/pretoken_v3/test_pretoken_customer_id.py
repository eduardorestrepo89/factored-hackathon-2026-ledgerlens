"""Tests for the customer_id claim added by the V3 Pre-Token Lambda.

The Lambda's file is ``infra-cdk/lambdas/pretoken-v3/index.py``. The folder name
has a dash and the module is called ``index``, so it is loaded from its path
under a unique module name instead of being imported.
"""

import importlib.util
from pathlib import Path

import pytest

_INDEX_PATH = (
    Path(__file__).resolve().parents[3]
    / "infra-cdk"
    / "lambdas"
    / "pretoken-v3"
    / "index.py"
)

USER_ID = "a1b2c3d4-5678-90ab-cdef-1234567890ab"
OTHER_USER_ID = "ffffffff-0000-1111-2222-333333333333"
CUSTOMER_ID = "CLI-F2DZJYU0POJ9"
MAP_ENV = "USER_CUSTOMER_IDS_MAP"


@pytest.fixture
def pretoken():
    """Load a fresh copy of the Pre-Token Lambda module."""
    spec = importlib.util.spec_from_file_location("pretoken_v3_index", _INDEX_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_m2m_event(user_id=USER_ID):
    """Build a Client Credentials trigger event carrying the verified user id."""
    return {
        "triggerSource": "TokenGeneration_ClientCredentials",
        "request": {"clientMetadata": {"verified_user_id": user_id}},
        "response": {},
    }


def added_claims(event):
    """Return the claims the Lambda added to the access token."""
    return event["response"]["claimsAndScopeOverrideDetails"]["accessTokenGeneration"][
        "claimsToAddOrOverride"
    ]


def test_mapped_user_gets_its_customer_id(pretoken, monkeypatch):
    monkeypatch.setenv(MAP_ENV, f'{{"{USER_ID}": "{CUSTOMER_ID}"}}')

    result = pretoken.lambda_handler(make_m2m_event(), None)

    assert added_claims(result)["customer_id"] == CUSTOMER_ID


def test_unmapped_user_gets_blank_customer_id(pretoken, monkeypatch):
    monkeypatch.setenv(MAP_ENV, f'{{"{OTHER_USER_ID}": "{CUSTOMER_ID}"}}')

    result = pretoken.lambda_handler(make_m2m_event(), None)

    assert added_claims(result)["customer_id"] == ""


def test_missing_variable_gives_blank_customer_id(pretoken, monkeypatch):
    monkeypatch.delenv(MAP_ENV, raising=False)

    result = pretoken.lambda_handler(make_m2m_event(), None)

    assert added_claims(result)["customer_id"] == ""


@pytest.mark.parametrize(
    "raw_map",
    ["", "   ", "not json", '["CLI-1"]', '"CLI-1"', "null"],
    ids=["empty", "blank", "invalid-json", "list", "string", "null"],
)
def test_unusable_variable_gives_blank_customer_id(pretoken, monkeypatch, raw_map):
    monkeypatch.setenv(MAP_ENV, raw_map)

    result = pretoken.lambda_handler(make_m2m_event(), None)

    assert added_claims(result)["customer_id"] == ""


def test_non_string_mapped_value_gives_blank_customer_id(pretoken, monkeypatch):
    monkeypatch.setenv(MAP_ENV, f'{{"{USER_ID}": 123}}')

    result = pretoken.lambda_handler(make_m2m_event(), None)

    assert added_claims(result)["customer_id"] == ""


def test_existing_claims_are_kept(pretoken, monkeypatch):
    monkeypatch.setenv(MAP_ENV, f'{{"{USER_ID}": "{CUSTOMER_ID}"}}')

    claims = added_claims(pretoken.lambda_handler(make_m2m_event(), None))

    assert claims["user_id"] == USER_ID
    assert claims["department"] == "guest"
    assert claims["role"] == "viewer"


def test_user_login_flow_is_untouched(pretoken, monkeypatch):
    monkeypatch.setenv(MAP_ENV, f'{{"{USER_ID}": "{CUSTOMER_ID}"}}')
    event = {"triggerSource": "TokenGeneration_HostedAuth", "response": {}}

    result = pretoken.lambda_handler(event, None)

    assert result["response"] == {}
