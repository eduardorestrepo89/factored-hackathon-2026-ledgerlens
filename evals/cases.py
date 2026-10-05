"""Load and validate evals/cases.yaml and the prompt files in evals/prompts/."""

import re
from pathlib import Path

import yaml

from evals import config

CASES_PATH = config.EVALS_DIR / "cases.yaml"
PROMPTS_DIR = config.EVALS_DIR / "prompts"
CONFIRM_TOOLS = frozenset({"block_credit_card", "open_claim", "human_agent_hand_off"})
# The laptop can't restore DSQL rows, so a case may approve only the hand-off,
# which stores and sends nothing (spec section 2, "Writes").
YES_ALLOWED = frozenset({"human_agent_hand_off"})
_PROMPT_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}")


class CaseError(ValueError):
    """cases.yaml or a prompt file is invalid."""


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    """Return the validated cases, each with its persona's customer_id added."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise CaseError(f"{path}: expected a non-empty list of cases")
    seen: set[str] = set()
    return [_validate(case, seen) for case in raw]


def _validate(case: object, seen: set[str]) -> dict:
    cid = case.get("id") if isinstance(case, dict) else None
    where = f"case {cid!r}"
    if not isinstance(cid, str) or not re.fullmatch(r"[A-Za-z0-9]+", cid):
        raise CaseError(f"{where}: id must be letters and digits")
    if cid in seen:
        raise CaseError(f"{where}: duplicate id")
    seen.add(cid)

    persona = case.get("persona")
    if persona not in config.PERSONAS:
        raise CaseError(f"{where}: unknown persona {persona!r}")

    turns = case.get("turns")
    if not isinstance(turns, list) or not turns or not all(
        isinstance(t, str) and t.strip() for t in turns
    ):
        raise CaseError(f"{where}: turns must be a non-empty list of messages")

    confirmations = case.get("confirmations") or []
    for item in confirmations:
        tool, answer = item.get("tool"), item.get("answer")
        if tool not in CONFIRM_TOOLS:
            raise CaseError(f"{where}: unknown confirmation tool {tool!r}")
        if isinstance(answer, bool):
            raise CaseError(f"{where}: quote the answer ('yes'/'no'); YAML reads bare yes/no as booleans")
        typed = isinstance(answer, dict) and set(answer) == {"type"} and isinstance(answer["type"], str) and answer["type"].strip()
        if answer not in ("yes", "no") and not typed:
            raise CaseError(f"{where}: answer must be 'yes', 'no' or {{type: <text>}}")
        if answer == "yes" and tool not in YES_ALLOWED:
            raise CaseError(f"{where}: Yes on {tool} would write to the shared database")

    checks = case.get("checks")
    if not isinstance(checks, list) or not checks or not all(
        isinstance(c, dict) and isinstance(c.get("check"), str) for c in checks
    ):
        raise CaseError(f"{where}: checks must be a non-empty list of {{check: name, ...}}")

    expected = case.get("expected_tools") or []
    if not all(isinstance(t, str) and t.startswith("gateway_") and "___" in t for t in expected):
        raise CaseError(f"{where}: expected_tools must be gateway_<target>___<tool> names")

    assertions = case.get("assertions") or []
    if not assertions or not all(isinstance(a, str) and a.strip() for a in assertions):
        raise CaseError(f"{where}: assertions must be a non-empty list of sentences")

    return {
        **case,
        "customer_id": config.PERSONAS[persona],
        "confirmations": confirmations,
        "expected_tools": expected,
        "assertions": assertions,
    }


def load_prompt(name: str, prompts_dir: Path = PROMPTS_DIR) -> str:
    """The prompt text, with LF line endings and no trailing newline (stable hashes)."""
    if not _PROMPT_NAME.fullmatch(name):
        raise CaseError(f"bad prompt name {name!r}: use [a-z0-9][a-z0-9._-]{{0,31}}")
    text = (prompts_dir / f"{name}.md").read_text(encoding="utf-8")
    return text.replace("\r\n", "\n").rstrip("\n")
