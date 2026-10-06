"""Shared settings for the evaluation harness: AWS target, personas, prices, local secrets."""

import re
from pathlib import Path

REGION = "us-east-1"
AWS_PROFILE = "ledgerlens"
STACK_NAME = "ledgerlens-bank-assistant"
EVALS_DIR = Path(__file__).resolve().parent
ENV_PATH = EVALS_DIR / ".env"
EMAIL_DOMAIN = "ledgerlens.example"

# Persona -> customer id (data_load/personas.json); only the personas the cases use.
PERSONAS = {
    "P01": "CLI-1GL7QBDG3QG0",
    "P03": "CLI-70U0WJ1NH1MN",
    "P04": "CLI-N4FPJIEGD917",
    "P05": "CLI-50OIF5EIYSWK",
    "P06": "CLI-PV0OIEA8DAAE",
    "P07": "CLI-EX6BOAOEFZHQ",
    "P09": "CLI-UBR2NCZWTD4K",
    "P10": "CLI-Z3V3SBS18YWQ",
}

# USD per million tokens (input, output): AWS Price List, us-east-1, published 2026-10-01.
PRICES = {
    "deepseek.v3.2": (0.62, 1.85),
    "openai.gpt-oss-120b-1:0": (0.15, 0.60),
    "global.anthropic.claude-haiku-4-5-20251001-v1:0": (
        1.00,
        5.00,
    ),  # global profile, 2026-09-01
}

# Tokens per session (input, output) for the dry-run estimate (spec section 10).
ESTIMATED_TOKENS = {
    "deepseek.v3.2": (60_000, 1_500),
    "openai.gpt-oss-120b-1:0": (60_000, 5_000),
    "global.anthropic.claude-haiku-4-5-20251001-v1:0": (60_000, 1_500),
}


def username(persona: str) -> str:
    """The evaluation login (a Cognito email username) for a persona."""
    return f"eval-{persona.lower()}@{EMAIL_DOMAIN}"


# Hackathon judges: one persona each, a different use case each (docs/evaluation/judges.md).
# Not in the evaluators group, so they always get the production model and prompt.
JUDGES = {
    "J1": "CLI-EX6BOAOEFZHQ",  # P07 suspected fraud: block the card, open a claim
    "J2": "CLI-UBR2NCZWTD4K",  # P09 records contradict: hand-off to a person
    "J3": "CLI-50OIF5EIYSWK",  # P05 Portuguese, a charge in Brazil
    "J4": "CLI-GG3Z1440277M",  # P08 follow-up of an open claim
    "J5": "CLI-N4FPJIEGD917",  # P04 which card? two charges at one merchant
}


def judge_username(judge: str) -> str:
    """The judge's login, e.g. judge-1@ledgerlens.example for J1."""
    return f"judge-{judge[1:]}@{EMAIL_DOMAIN}"


def model_slug(model_id: str) -> str:
    """A model id with only letters, digits and dashes, for session ids and file names."""
    return re.sub(r"[^a-zA-Z0-9]+", "-", model_id).strip("-")


def session_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """USD for one session's model tokens."""
    price_in, price_out = PRICES[model_id]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def read_env(path: Path = ENV_PATH) -> dict[str, str]:
    """KEY=VALUE lines; blank lines and # comments are skipped; a missing file is empty."""
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def write_env(values: dict[str, str], path: Path = ENV_PATH) -> None:
    """Write KEY=VALUE lines, sorted by key."""
    path.write_text(
        "".join(f"{k}={values[k]}\n" for k in sorted(values)), encoding="utf-8"
    )


def aws_session():
    """A boto3 session on the project profile; never the default profile."""
    import boto3

    return boto3.Session(profile_name=AWS_PROFILE, region_name=REGION)


def stack_outputs(session) -> dict[str, str]:
    """The main stack's outputs (CognitoUserPoolId, CognitoClientId, RuntimeArn, ...)."""
    stack = session.client("cloudformation").describe_stacks(StackName=STACK_NAME)[
        "Stacks"
    ][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}
