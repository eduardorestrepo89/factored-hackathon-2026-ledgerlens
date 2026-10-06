"""scripts/deploy-frontend.py: --config-only writes aws-exports.json for the local dev server."""

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "deploy-frontend.py"
spec = importlib.util.spec_from_file_location("deploy_frontend", _SCRIPT)
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)

OUTPUTS = {
    "CognitoClientId": "client-1",
    "CognitoUserPoolId": "us-east-1_abc",
    "AmplifyUrl": "https://main.d1.amplifyapp.com",
    "RuntimeArn": "arn:aws:bedrock-agentcore:us-east-1:111111111111:runtime/r-1",
    "FeedbackApiUrl": "https://api.example/prod/",
}


def read_exports(frontend_dir: Path) -> dict:
    return json.loads((frontend_dir / "public" / "aws-exports.json").read_text())


@pytest.mark.unit
@pytest.mark.parametrize(
    "argv",
    [["--config-only"], ["--config-only", "my-stack"], ["my-stack", "--config-only"]],
)
def test_config_only_is_found_anywhere_and_never_taken_as_the_stack(argv):
    stack, config_only = deploy.parse_args(argv)

    assert config_only is True
    assert stack == ("my-stack" if "my-stack" in argv else None)


@pytest.mark.unit
def test_without_the_flag_the_first_argument_is_the_stack():
    assert deploy.parse_args(["my-stack"]) == ("my-stack", False)
    assert deploy.parse_args([]) == (None, False)


@pytest.mark.unit
def test_a_local_redirect_replaces_the_amplify_url(tmp_path):
    deploy.generate_aws_exports(
        "s",
        OUTPUTS,
        "us-east-1",
        "ledgerlens",
        tmp_path,
        redirect_uri=deploy.LOCAL_DEV_URL,
    )

    exports = read_exports(tmp_path)
    assert exports["redirect_uri"] == "http://localhost:3000"
    assert exports["post_logout_redirect_uri"] == "http://localhost:3000"
    assert exports["agentRuntimeArn"] == OUTPUTS["RuntimeArn"]
    assert exports["feedbackApiUrl"] == OUTPUTS["FeedbackApiUrl"]


@pytest.mark.unit
def test_without_a_redirect_the_amplify_url_is_kept(tmp_path):
    deploy.generate_aws_exports("s", OUTPUTS, "us-east-1", "ledgerlens", tmp_path)

    exports = read_exports(tmp_path)
    assert exports["redirect_uri"] == OUTPUTS["AmplifyUrl"]
    assert exports["post_logout_redirect_uri"] == OUTPUTS["AmplifyUrl"]
