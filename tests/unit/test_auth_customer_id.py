"""Unit tests for reading the customer_id claim from the Gateway machine token.

``patterns/utils/auth.py`` imports ``bedrock_agentcore.runtime`` and
``utils.ssm`` (which needs boto3 at import time). Missing agent-runtime
dependencies are stubbed in ``sys.modules`` before the import, so the tests run
without the agent's container dependencies.
"""

import importlib
import sys
import types
from pathlib import Path

import jwt
import pytest

_PATTERNS_DIR = Path(__file__).resolve().parents[2] / "patterns"

CUSTOMER_ID = "CLI-F2DZJYU0POJ9"


def _install_dependency_stubs() -> None:
    """Register a stub ``bedrock_agentcore.runtime`` exposing RequestContext."""
    if "bedrock_agentcore.runtime" in sys.modules:
        return
    package = types.ModuleType("bedrock_agentcore")
    runtime = types.ModuleType("bedrock_agentcore.runtime")
    runtime.RequestContext = type("RequestContext", (), {})
    package.runtime = runtime
    sys.modules.setdefault("bedrock_agentcore", package)
    sys.modules["bedrock_agentcore.runtime"] = runtime


@pytest.fixture(scope="module")
def auth():
    """Import patterns/utils/auth.py as ``utils.auth``."""
    _install_dependency_stubs()
    if str(_PATTERNS_DIR) not in sys.path:
        sys.path.insert(0, str(_PATTERNS_DIR))
    return importlib.import_module("utils.auth")


def make_token(claims: dict) -> str:
    """Build a signed JWT carrying the given claims (the signature isn't checked)."""
    return jwt.encode(claims, "test-key", algorithm="HS256")


def test_returns_the_customer_id_claim(auth):
    token = make_token({"sub": "machine-client", "customer_id": CUSTOMER_ID})

    assert auth.extract_customer_id_from_token(token) == CUSTOMER_ID


def test_blank_claim_gives_blank(auth):
    token = make_token({"sub": "machine-client", "customer_id": ""})

    assert auth.extract_customer_id_from_token(token) == ""


def test_missing_claim_gives_blank(auth):
    token = make_token({"sub": "machine-client"})

    assert auth.extract_customer_id_from_token(token) == ""


def test_non_string_claim_gives_blank(auth):
    token = make_token({"sub": "machine-client", "customer_id": 123})

    assert auth.extract_customer_id_from_token(token) == ""


def test_whitespace_claim_gives_blank(auth):
    token = make_token({"sub": "machine-client", "customer_id": "   "})

    assert auth.extract_customer_id_from_token(token) == ""


def test_malformed_token_gives_blank(auth):
    assert auth.extract_customer_id_from_token("not-a-jwt") == ""


def test_value_is_returned_exactly_as_in_the_token(auth):
    token = make_token({"customer_id": "cli-f2dzjyu0poj9"})

    assert auth.extract_customer_id_from_token(token) == "cli-f2dzjyu0poj9"
