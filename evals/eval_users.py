"""Create the evaluation logins, link them to their personas, add them to the group.

  python -m evals.eval_users create                # lists what it would do
  python -m evals.eval_users create --apply        # creates the users, saves passwords to
                                                   # evals/.env, writes their subs into
                                                   # infra-cdk/lib/cognito-construct.ts
  python -m evals.eval_users add-to-group --apply  # after the deploy created the group

The subs go into the committed USER_CUSTOMER_IDS_MAP so later deploys keep them.
"""

import argparse
import json
import re
import secrets
import string
from pathlib import Path

from evals import config

CDK_COGNITO = config.EVALS_DIR.parent / "infra-cdk" / "lib" / "cognito-construct.ts"
GROUP = "evaluators"
_MAP = re.compile(r"USER_CUSTOMER_IDS_MAP: '(\{.*?\})'")
_SYMBOLS = "!@#$%^&*-_=+"


def generate_password(length: int = 20) -> str:
    """A random password meeting the pool policy: upper, lower, digit and symbol."""
    classes = [string.ascii_uppercase, string.ascii_lowercase, string.digits, _SYMBOLS]
    chars = [secrets.choice(c) for c in classes]
    chars += [secrets.choice("".join(classes)) for _ in range(length - len(classes))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def merged_map(existing: dict[str, str], entries: dict[str, str]) -> str:
    """The map as the JSON string the pre-token Lambda reads, sorted by sub."""
    return json.dumps({**existing, **entries}, sort_keys=True, separators=(", ", ": "))


def write_cdk_map(entries: dict[str, str], path: Path = CDK_COGNITO) -> str:
    """Merge entries into the USER_CUSTOMER_IDS_MAP literal in the CDK construct."""
    text = path.read_text(encoding="utf-8")
    match = _MAP.search(text)
    if not match:
        raise ValueError(f"USER_CUSTOMER_IDS_MAP not found in {path}")
    new_map = merged_map(json.loads(match[1]), entries)
    path.write_text(text[: match.start(1)] + new_map + text[match.end(1) :], encoding="utf-8")
    return new_map


def _sub(attributes: list[dict]) -> str:
    return next(a["Value"] for a in attributes if a["Name"] == "sub")


def create(cognito, pool_id: str, env: dict[str, str], apply: bool) -> dict[str, str]:
    """Return {sub: customer_id}; with apply, create missing users and set missing passwords."""
    entries: dict[str, str] = {}
    for persona, customer_id in config.PERSONAS.items():
        name = config.username(persona)
        if not apply:
            print(f"would create {name} -> {persona} {customer_id}")
            continue
        try:
            user = cognito.admin_create_user(
                UserPoolId=pool_id,
                Username=name,
                MessageAction="SUPPRESS",
                UserAttributes=[{"Name": "email", "Value": name},
                                {"Name": "email_verified", "Value": "true"}],
            )["User"]
            attributes = user["Attributes"]
        except cognito.exceptions.UsernameExistsException:
            attributes = cognito.admin_get_user(UserPoolId=pool_id, Username=name)["UserAttributes"]
        key = f"EVAL_PASSWORD_{persona}"
        if key not in env:
            env[key] = generate_password()
            cognito.admin_set_user_password(UserPoolId=pool_id, Username=name,
                                            Password=env[key], Permanent=True)
        entries[_sub(attributes)] = customer_id
        print(f"{name} -> {persona} {customer_id}")
    return entries


def add_to_group(cognito, pool_id: str, apply: bool) -> None:
    for persona in config.PERSONAS:
        name = config.username(persona)
        if apply:
            cognito.admin_add_user_to_group(UserPoolId=pool_id, Username=name, GroupName=GROUP)
        print(f"{'added' if apply else 'would add'} {name} to {GROUP}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Manage the LedgerLens evaluation logins.")
    parser.add_argument("command", choices=["create", "add-to-group"])
    parser.add_argument("--apply", action="store_true", help="make the changes (default: list them)")
    args = parser.parse_args(argv)
    session = config.aws_session()
    cognito = session.client("cognito-idp")
    pool_id = config.stack_outputs(session)["CognitoUserPoolId"]
    if args.command == "add-to-group":
        add_to_group(cognito, pool_id, args.apply)
        return 0
    env = config.read_env()
    entries = create(cognito, pool_id, env, args.apply)
    if args.apply:
        config.write_env(env)
        print("USER_CUSTOMER_IDS_MAP =", write_cdk_map(entries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
