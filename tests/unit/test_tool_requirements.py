"""Tool Lambdas bundle only what the Python runtime lacks.

The Lambda Python runtime ships boto3 and botocore, so bundling them only bloats
the asset with boto3, botocore, s3transfer, jmespath, dateutil, urllib3 and six.
"""

from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[2] / "gateway" / "tools"
RUNTIME_PACKAGES = ("boto3", "botocore")


def _requirements(tool: str) -> list[str]:
    lines = (TOOLS_DIR / tool / "requirements.txt").read_text(encoding="utf-8").splitlines()
    return [line.strip().lower() for line in lines if line.strip() and not line.lstrip().startswith("#")]


@pytest.mark.parametrize("tool", ["list_credit_cards", "list_card_transactions", "get_session_context"])
def test_tool_does_not_bundle_the_runtime_sdk(tool: str) -> None:
    requirements = _requirements(tool)

    assert not [r for r in requirements if r.startswith(RUNTIME_PACKAGES)]
    assert any(r.startswith("psycopg[binary]") for r in requirements)
