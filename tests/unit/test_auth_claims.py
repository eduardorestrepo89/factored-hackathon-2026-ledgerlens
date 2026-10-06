"""Unit tests for reading the runtime JWT's claims (agent/utils/auth.py)."""

import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest

_AGENT_DIR = Path(__file__).resolve().parents[2] / "agent"
KEY = "test-signing-key-of-32-bytes-ok!"  # PyJWT warns on HMAC keys under 32 bytes


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
    _install_dependency_stubs()
    if str(_AGENT_DIR) not in sys.path:
        sys.path.insert(0, str(_AGENT_DIR))
    return importlib.import_module("utils.auth")


def context(headers):
    return SimpleNamespace(request_headers=headers)


def bearer(claims: dict) -> dict:
    return {"Authorization": "Bearer " + jwt.encode(claims, KEY, algorithm="HS256")}


def test_claims_include_the_cognito_groups(auth):
    claims = auth.extract_claims_from_context(
        context(bearer({"sub": "u1", "cognito:groups": ["evaluators"]}))
    )

    assert claims["cognito:groups"] == ["evaluators"]


def test_a_token_without_the_bearer_prefix_is_read(auth):
    token = jwt.encode({"sub": "u1"}, KEY, algorithm="HS256")

    assert (
        auth.extract_claims_from_context(context({"Authorization": token}))["sub"]
        == "u1"
    )


def test_missing_headers_raise(auth):
    with pytest.raises(ValueError, match="request headers"):
        auth.extract_claims_from_context(context(None))


def test_missing_authorization_header_raises(auth):
    with pytest.raises(ValueError, match="Authorization"):
        auth.extract_claims_from_context(context({"X-Other": "1"}))


def test_user_id_still_comes_from_sub(auth):
    assert auth.extract_user_id_from_context(context(bearer({"sub": "u1"}))) == "u1"


def test_user_id_without_sub_raises(auth):
    with pytest.raises(ValueError, match="sub"):
        auth.extract_user_id_from_context(context(bearer({"name": "x"})))
