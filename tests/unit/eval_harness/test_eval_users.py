"""Unit tests for evals/eval_users.py (fake Cognito; no AWS)."""

import json
import re

import pytest

from evals import config, eval_users

TS = """      environment: {
        USER_CUSTOMER_IDS_MAP: '{"44b8f4a8-60d1-70bc-daa4-b5edd9e3270b": "CLI-70U0WJ1NH1MN"}',
      },
"""


class UsernameExistsException(Exception):
    pass


class FakeCognito:
    exceptions = type("E", (), {"UsernameExistsException": UsernameExistsException})

    def __init__(self, existing=()):
        self.existing, self.calls = set(existing), []

    def admin_create_user(self, **kw):
        self.calls.append(("create", kw["Username"]))
        if kw["Username"] in self.existing:
            raise UsernameExistsException()
        return {"User": {"Attributes": [{"Name": "sub", "Value": f"sub-{kw['Username']}"}]}}

    def admin_get_user(self, **kw):
        self.calls.append(("get", kw["Username"]))
        return {"UserAttributes": [{"Name": "sub", "Value": f"sub-{kw['Username']}"}]}

    def admin_set_user_password(self, **kw):
        self.calls.append(("password", kw["Username"], kw["Permanent"]))

    def admin_add_user_to_group(self, **kw):
        self.calls.append(("group", kw["Username"], kw["GroupName"]))


def test_passwords_meet_the_pool_policy():
    for _ in range(100):
        pw = eval_users.generate_password()
        assert len(pw) == 20
        assert re.search(r"[A-Z]", pw) and re.search(r"[a-z]", pw)
        assert re.search(r"\d", pw) and re.search(r"[^A-Za-z0-9]", pw)


def test_merged_map_keeps_the_demo_login_and_sorts():
    merged = json.loads(eval_users.merged_map({"z": "CLI-Z"}, {"a": "CLI-A"}))

    assert list(merged) == ["a", "z"]


def test_write_cdk_map_rewrites_only_the_map(tmp_path):
    path = tmp_path / "cognito-construct.ts"
    path.write_text(TS, encoding="utf-8")

    eval_users.write_cdk_map({"sub-1": "CLI-EX6BOAOEFZHQ"}, path)

    text = path.read_text(encoding="utf-8")
    assert '"44b8f4a8-60d1-70bc-daa4-b5edd9e3270b": "CLI-70U0WJ1NH1MN"' in text
    assert '"sub-1": "CLI-EX6BOAOEFZHQ"' in text
    assert text.startswith("      environment: {") and text.endswith("      },\n")


def test_write_cdk_map_fails_loudly_without_the_map(tmp_path):
    path = tmp_path / "x.ts"
    path.write_text("nothing here", encoding="utf-8")

    with pytest.raises(ValueError, match="USER_CUSTOMER_IDS_MAP"):
        eval_users.write_cdk_map({"s": "c"}, path)


def test_judges_get_their_own_logins_and_passwords_and_no_group():
    cognito, env = FakeCognito(), {}

    entries = eval_users.create(cognito, "pool", env, apply=True, judges=True)

    assert sorted(entries.values()) == sorted(config.JUDGES.values())
    assert len(set(config.JUDGES.values())) == len(config.JUDGES)  # one persona per judge
    assert set(env) == {f"JUDGE_PASSWORD_{j}" for j in config.JUDGES}
    assert {call[1] for call in cognito.calls} == {config.judge_username(j) for j in config.JUDGES}
    assert not any(call[0] == "group" for call in cognito.calls)  # judges can't switch model or prompt


def test_a_dry_run_calls_nothing():
    cognito = FakeCognito()

    assert eval_users.create(cognito, "pool", {}, apply=False) == {}
    assert cognito.calls == []


def test_create_makes_users_sets_passwords_and_maps_subs():
    cognito, env = FakeCognito(), {}

    entries = eval_users.create(cognito, "pool", env, apply=True)

    assert len(entries) == len(config.PERSONAS)
    assert entries[f"sub-{config.username('P07')}"] == "CLI-EX6BOAOEFZHQ"
    assert set(env) == {f"EVAL_PASSWORD_{p}" for p in config.PERSONAS}
    assert ("password", config.username("P07"), True) in cognito.calls


def test_an_existing_user_keeps_its_saved_password():
    name = config.username("P07")
    cognito, env = FakeCognito(existing={name}), {"EVAL_PASSWORD_P07": "kept"}

    eval_users.create(cognito, "pool", env, apply=True)

    assert env["EVAL_PASSWORD_P07"] == "kept"
    assert ("get", name) in cognito.calls
    assert ("password", name, True) not in cognito.calls


def test_add_to_group_adds_every_persona_only_with_apply():
    cognito = FakeCognito()

    eval_users.add_to_group(cognito, "pool", apply=False)
    assert cognito.calls == []

    eval_users.add_to_group(cognito, "pool", apply=True)
    assert {c[2] for c in cognito.calls} == {"evaluators"}
    assert len(cognito.calls) == len(config.PERSONAS)
