"""scripts/deploy-with-codebuild.py: deploy every stack, or only the ones named."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "deploy-with-codebuild.py"
spec = importlib.util.spec_from_file_location("deploy_with_codebuild", _SCRIPT)
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


def record_commands(monkeypatch, stdout="{}"):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[:3] == ["aws", "codebuild", "batch-get-projects"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"projects": []}))
        return subprocess.CompletedProcess(command, 0, stdout)

    monkeypatch.setattr(deploy, "run_command", run)
    return calls


@pytest.mark.unit
def test_buildspec_deploys_the_named_stacks_or_all(monkeypatch):
    calls = record_commands(monkeypatch)
    deploy.get_or_create_codebuild_project(
        "p", "arn:role", "b", "source.zip", "s", "us-east-1"
    )
    create = next(c for c in calls if c[:3] == ["aws", "codebuild", "create-project"])
    buildspec = json.loads(create[create.index("--cli-input-json") + 1])["source"][
        "buildspec"
    ]
    assert "cdk deploy ${DEPLOY_STACKS:---all} --require-approval never" in buildspec


@pytest.mark.unit
def test_start_build_passes_the_named_stacks(monkeypatch):
    calls = record_commands(monkeypatch, stdout=json.dumps({"build": {"id": "b-1"}}))
    assert deploy.start_codebuild("p", ["ledgerlens-bank-assistant-data"]) == "b-1"
    assert calls[-1][-2:] == [
        "--environment-variables-override",
        "name=DEPLOY_STACKS,value=ledgerlens-bank-assistant-data,type=PLAINTEXT",
    ]
    deploy.start_codebuild("p")
    assert "--environment-variables-override" not in calls[-1]  # all stacks


@pytest.mark.unit
@pytest.mark.parametrize("name", ["x; rm -rf /", "-all", "a b"])
def test_a_bad_stack_name_stops_before_any_aws_call(monkeypatch, name):
    calls = record_commands(monkeypatch)
    assert deploy.main([name]) == 1
    assert calls == []
