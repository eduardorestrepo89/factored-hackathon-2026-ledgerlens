# Human hand-off: SNS-free Lambda and hand-off frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The agent hands a conversation to a person through `human_agent_hand_off`, says goodbye, and the React app animates into a split screen (customer phone + human agent desk) built entirely from the streamed tool result.

**Architecture:** The Lambda drops SNS and becomes a pure validator that returns the full hand-off with a content-derived `HO-` id. CDK, Cedar and a v2 system prompt let the agent call it live. In the frontend, a pure `findHandOff()` reads the completed tool result once the turn has finished streaming; `ChatInterface` then flips one piece of state (`handOff`) inside a View Transition, which swaps the centered chat for a phone frame plus an `AgentDesk`. Laura's messages are local (`role: "human"`) and the bot is muted after the hand-off.

**Tech Stack:** Python 3.13 Lambda (pytest, ruff); AWS CDK TypeScript (jest); Cedar; React 19 + Vite + Tailwind v4 + shadcn/ui + lucide-react (vitest, Testing Library).

**Spec:** [`docs/superpowers/specs/2026-10-03-human-hand-off-frontend-design.md`](../specs/2026-10-03-human-hand-off-frontend-design.md). Visual reference: the three Superdesign beats linked in spec §6 and `.superdesign/design-system.md`.

## Global Constraints

- Branch `feat/frontend`. Commit messages carry **no** `Co-Authored-By` trailer.
- No new pip or npm dependencies.
- Customer- and agent-facing copy is Spanish (es-CO). No wait time is ever promised ("Don't promise a time").
- Tier colors carry meaning: teal = AI (`ai`, `ai-bg`), orange = human (`human`, `human-bg`), brand-dark = customer. Fonts: Geist and Geist Mono only.
- The streamed tool name is `human-agent-hand-off-target___human_agent_hand_off`; always match the bare name `human_agent_hand_off`.
- The Lambda makes no AWS call, reads no environment variable, runs outside the VPC, and never logs the summary.
- The UI switches only on a completed `human_agent_hand_off` result that has a string `hand_off_id`, never on the agent's words.
- Do not deploy while the branch's code review is running.

## Review Focus

1. **"Nueva conversación" clicked during the 600 ms pause** before the split: the new chat must stay a plain chat. Pinned in Task 7 (`starting a new chat during the pause cancels the split`).
2. **The model says goodbye *before* calling the tool** (no text after the tool segment): "Lo que ya se le dijo" must still show the goodbye, not be empty. Pinned in Task 4 (`falls back to the text before the tool`).
3. **The tool returns an error or non-JSON text**: no split, and the plain tool row shows. Pinned in Task 4 (`ignores …`), Task 6 (`falls back to the plain tool row`) and Task 7 (`an error result never opens the desk`).
4. **The customer keeps typing after the hand-off**: AgentCore is never called again and the message shows on both the phone and the desk. Pinned in Task 7.
5. **A Cognito profile with no name**: the case card falls back to `customer_id` and the greeting reads "Hola, soy Laura…", with no blank name. Pinned in Task 4 (`leaves the name out when the profile has none`).

---

## File map

| File | Task | Responsibility |
|---|---|---|
| `gateway/tools/human_agent_hand_off/human_agent_hand_off_lambda/domain/entities/hand_off.py` | 1 | `HandOff`, `HandOffResult(hand_off_id, hand_off)` |
| `…/domain/errors.py` | 1 | `DomainError`, `InvalidInputError` only |
| `…/application/use_cases/hand_off.py` | 1 | validation + `hand_off_id()` |
| `…/delivery/presenters/hand_off.py` | 1 | full JSON result |
| `…/delivery/handler.py` | 1 | dependency-free handler |
| `…/application/ports/`, `…/infrastructure/`, `…/delivery/settings.py`, `…/delivery/dependencies/` | 1 | **deleted** |
| `gateway/tools/human_agent_hand_off/tool_spec.json` | 1 | description with the goodbye rule |
| `tests/unit/human_agent_hand_off/*` | 1 | rewritten; SNS, settings and wiring tests deleted |
| `infra-cdk/lib/data-construct.ts`, `infra-cdk/test/data-construct.test.ts` | 2 | no topic |
| `infra-cdk/lib/backend-construct.ts`, `infra-cdk/test/backend-gateway.test.ts` | 2 | Gateway target |
| `gateway/policies/policy.cedar` | 2 | permit + forbid for the hand-off |
| `patterns/strands-single-agent/tools/system_prompt.py`, `tests/unit/test_system_prompt.py` | 3 | prompt v2 |
| `frontend/src/hooks/useToolRenderer.ts` | 4 | `bareToolName`, prefixed lookup |
| `frontend/src/lib/handoff.ts` | 4 | types, `findHandOff`, `phaseOf`, labels, `suggestedReplies` |
| `frontend/src/components/chat/types.ts` | 4 | `MessageRole` gains `"human"` |
| `frontend/src/test/handoff.test.ts`, `frontend/src/test/tool-renderer.test.ts` | 4 | unit tests |
| `frontend/src/styles/globals.css`, `frontend/index.html`, `frontend/src/test/config.test.ts` | 5 | tokens, font fix, title, view-transition CSS |
| `frontend/src/components/chat/ChatHeader.tsx`, `ChatInput.tsx` | 5 | brand, status track, Spanish copy |
| `frontend/src/components/chat/HandOffTicket.tsx` | 6 | ticket renderer, `PriorityPill`, `IdChips` |
| `frontend/src/components/chat/ChatMessage.tsx`, `ChatMessages.tsx` | 6 | tier bubbles, "Laura se unió" divider |
| `frontend/src/test/handoff-ticket.test.tsx` | 6 | ticket tests |
| `frontend/src/components/chat/AgentDesk.tsx` | 7 | desk pane |
| `frontend/src/components/chat/ChatInterface.tsx` | 7 | trigger, mute, split layout |
| `frontend/src/test/handoff-flow.test.tsx` | 7 | end-to-end flow with a mocked agent |
| `docs/LEDGERLENS_PRODUCT_DESIGN.md`, `docs/superpowers/specs/2026-10-03-write-tools-design.md` | 8 | point at the new spec |

Commands used throughout (run from the repo root unless a `cd` is shown):
- Python tests: `pytest tests/unit/human_agent_hand_off tests/unit/test_system_prompt.py -q`
- Python lint: `ruff format --check gateway tests && ruff check gateway tests`
- CDK tests: `cd infra-cdk && npx jest test/data-construct.test.ts test/policy-cedar.test.ts` (fast), `npx jest test/backend-gateway.test.ts` (about 2 minutes)
- Frontend: `cd frontend && npx vitest --run <file>`, `npm test`, `npm run lint`, `npm run build`

---

### Task 1: SNS-free hand-off Lambda with a content-derived id and a full result

**Files:**
- Delete: `gateway/tools/human_agent_hand_off/human_agent_hand_off_lambda/application/ports/` (whole folder), `…/infrastructure/` (whole folder), `…/delivery/settings.py`, `…/delivery/dependencies/` (whole folder)
- Delete: `tests/unit/human_agent_hand_off/test_sns_publisher.py`, `test_settings.py`, `test_delivery_wiring.py` (the handler test `the module loads with an empty environment` replaces the wiring test)
- Modify: `…/domain/entities/hand_off.py`, `…/domain/errors.py`, `…/application/use_cases/hand_off.py`, `…/delivery/presenters/hand_off.py`, `…/delivery/handler.py`, `gateway/tools/human_agent_hand_off/tool_spec.json`
- Test: `tests/unit/human_agent_hand_off/fakes.py`, `test_errors.py`, `test_hand_off_use_case.py`, `test_hand_off_handler.py`, `test_tool_spec.py`

(`…` = `gateway/tools/human_agent_hand_off/human_agent_hand_off_lambda`.)

**Interfaces:**
- Consumes: nothing.
- Produces: the tool result JSON every later task reads:
  `{"hand_off_id": "HO-XXXXXXXX", "status": "queued", "priority": "high"|"normal", "reason": "FRAUD_CONFIRMED"|"CUSTOMER_REQUEST"|"UNRESOLVED"|"OUT_OF_SCOPE", "customer_id": str, "summary": str, "related_ids": [str]}`; `hand_off_id` matches `^HO-[A-Z2-7]{8}$`. Python: `HandOffUseCase().execute(customer_id, priority, reason, summary, related_ids) -> HandOffResult`, `hand_off_id(hand_off: HandOff) -> str`.

- [ ] **Step 1: Delete the SNS code and its tests**

```bash
L=gateway/tools/human_agent_hand_off/human_agent_hand_off_lambda
git rm -r -q $L/application/ports $L/infrastructure $L/delivery/settings.py $L/delivery/dependencies
git rm -q tests/unit/human_agent_hand_off/test_sns_publisher.py tests/unit/human_agent_hand_off/test_settings.py tests/unit/human_agent_hand_off/test_delivery_wiring.py
```

- [ ] **Step 2: Write the failing tests**

Replace `tests/unit/human_agent_hand_off/fakes.py` with:

```python
"""Shared test values for the human_agent_hand_off tests."""

from typing import Final

# A customer id in the format the customer system issues.
CUSTOMER_ID: Final = "CLI-ITIECUE8PRH9"
```

Replace `tests/unit/human_agent_hand_off/test_errors.py` with:

```python
"""Tests for the hand-off domain errors."""

import pytest
from human_agent_hand_off_lambda.domain.errors import DomainError, InvalidInputError

pytestmark = pytest.mark.unit


def test_invalid_input_error_formats_field_and_reason() -> None:
    error = InvalidInputError("priority", "must be high or normal")

    assert isinstance(error, DomainError)
    assert error.message == (
        "Invalid value for 'priority': must be high or normal. "
        "Ask the customer to confirm and retry."
    )
```

Replace `tests/unit/human_agent_hand_off/test_hand_off_use_case.py` with:

```python
"""Tests for HandOffUseCase and the content-derived hand-off id."""

import re
from typing import Any

import pytest
from human_agent_hand_off_lambda.application.use_cases.hand_off import (
    HandOffUseCase,
    hand_off_id,
)
from human_agent_hand_off_lambda.domain.entities.hand_off import (
    HandOff,
    HandOffResult,
)
from human_agent_hand_off_lambda.domain.errors import InvalidInputError

from .fakes import CUSTOMER_ID

pytestmark = pytest.mark.unit

SUMMARY = (
    "Customer did not recognise 2 charges (USD 740.00 BESTBUY Miami). Card 4821 "
    "blocked. Claim CMP-4KQ2ZJ7M3XH5TB6RWN2Y opened."
)
ARGS: dict[str, Any] = {
    "customer_id": CUSTOMER_ID,
    "priority": "high",
    "reason": "FRAUD_CONFIRMED",
    "summary": SUMMARY,
    "related_ids": ["TRX-88", "CMP-4KQ2ZJ7M3XH5TB6RWN2Y"],
}
# sha256 over "CLI-ITIECUE8PRH9|high|FRAUD_CONFIRMED|<SUMMARY>|CMP-4KQ2ZJ7M3XH5TB6RWN2Y,TRX-88"
EXPECTED_ID = "HO-AYIWT2IJ"
RELATED_IDS_REASON = (
    "must be a list of at most 20 ids made of letters, digits and dashes"
)


def run(**overrides: Any) -> HandOffResult:
    """Run the use case with ARGS, overridden by ``overrides``."""
    return HandOffUseCase().execute(**{**ARGS, **overrides})


def test_a_valid_hand_off_is_returned_with_its_id() -> None:
    assert run() == HandOffResult(
        hand_off_id=EXPECTED_ID,
        hand_off=HandOff(
            customer_id=CUSTOMER_ID,
            priority="high",
            reason="FRAUD_CONFIRMED",
            summary=SUMMARY,
            related_ids=("TRX-88", "CMP-4KQ2ZJ7M3XH5TB6RWN2Y"),
        ),
    )


def test_the_id_is_ho_and_eight_base32_characters() -> None:
    assert re.fullmatch(r"HO-[A-Z2-7]{8}", run().hand_off_id)
    assert hand_off_id(run().hand_off) == run().hand_off_id


def test_inputs_are_cleaned_and_cleaning_keeps_the_id() -> None:
    result = run(
        customer_id=" cli-itiecue8prh9 ",
        priority=" High ",
        reason=" fraud_confirmed ",
        summary=f"  {SUMMARY}\n",
        related_ids=[" cmp-4kq2zj7m3xh5tb6rwn2y ", "trx-88"],
    )

    assert result.hand_off.customer_id == CUSTOMER_ID
    assert result.hand_off.priority == "high"
    assert result.hand_off.reason == "FRAUD_CONFIRMED"
    assert result.hand_off.summary == SUMMARY
    assert result.hand_off.related_ids == ("CMP-4KQ2ZJ7M3XH5TB6RWN2Y", "TRX-88")
    # related ids are sorted inside the hash, so their order doesn't matter
    assert result.hand_off_id == EXPECTED_ID


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("customer_id", "CLI-OTHER0000001"),
        ("priority", "normal"),
        ("reason", "UNRESOLVED"),
        ("summary", "Otro resumen."),
        ("related_ids", ["TRX-99"]),
    ],
)
def test_any_field_change_gives_a_new_id(field: str, value: object) -> None:
    assert run(**{field: value}).hand_off_id != EXPECTED_ID


@pytest.mark.parametrize("related_ids", [None, []])
def test_related_ids_are_optional(related_ids: object) -> None:
    assert run(related_ids=related_ids).hand_off.related_ids == ()


def test_a_summary_of_2000_characters_and_20_related_ids_are_accepted() -> None:
    result = run(summary="á" * 2000, related_ids=[f"TRX-{i}" for i in range(20)])

    assert len(result.hand_off.summary) == 2000
    assert len(result.hand_off.related_ids) == 20


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("customer_id", None, "is required and must be a non-empty string"),
        ("customer_id", "   ", "is required and must be a non-empty string"),
        ("priority", "urgent", "must be high or normal"),
        ("priority", None, "must be high or normal"),
        (
            "reason",
            "ANGRY",
            "must be one of: FRAUD_CONFIRMED, CUSTOMER_REQUEST, UNRESOLVED, "
            "OUT_OF_SCOPE",
        ),
        ("summary", "", "must be a summary of 1 to 2000 characters"),
        ("summary", "   ", "must be a summary of 1 to 2000 characters"),
        ("summary", "x" * 2001, "must be a summary of 1 to 2000 characters"),
        ("summary", 42, "must be a summary of 1 to 2000 characters"),
        ("related_ids", "TRX-88", RELATED_IDS_REASON),
        ("related_ids", ["TRX 88"], RELATED_IDS_REASON),
        ("related_ids", ["TRX-88;DROP"], RELATED_IDS_REASON),
        ("related_ids", ["SEÑOR-1"], RELATED_IDS_REASON),
        ("related_ids", [42], RELATED_IDS_REASON),
        ("related_ids", [""], RELATED_IDS_REASON),
        ("related_ids", ["X" * 41], RELATED_IDS_REASON),
        ("related_ids", [f"TRX-{i}" for i in range(21)], RELATED_IDS_REASON),
    ],
)
def test_invalid_input_is_rejected(field: str, value: object, reason: str) -> None:
    with pytest.raises(InvalidInputError) as caught:
        run(**{field: value})

    assert caught.value.field == field
    assert caught.value.reason == reason
```

Replace `tests/unit/human_agent_hand_off/test_hand_off_handler.py` with:

```python
"""Tests for the human_agent_hand_off Lambda handler."""

import importlib
import json
import logging
import re
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from .fakes import CUSTOMER_ID

pytestmark = pytest.mark.unit

EVENT = {
    "customer_id": CUSTOMER_ID,
    "priority": "high",
    "reason": "FRAUD_CONFIRMED",
    "summary": "Card 4821 blocked; claim CMP-4KQ2ZJ7M3XH5TB6RWN2Y opened.",
    "related_ids": ["CMP-4KQ2ZJ7M3XH5TB6RWN2Y"],
}


def make_context(
    tool_name: str = "human-agent-hand-off-target___human_agent_hand_off",
) -> SimpleNamespace:
    """Build a Lambda context carrying the Gateway tool name."""
    return SimpleNamespace(
        client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": tool_name})
    )


@pytest.fixture
def module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Import the handler module fresh, with an empty environment."""
    for name in ("HANDOFF_TOPIC_ARN", "AWS_REGION"):
        monkeypatch.delenv(name, raising=False)
    import human_agent_hand_off_lambda.delivery.handler as handler_module

    return importlib.reload(handler_module)


def body(response: dict[str, Any]) -> dict[str, Any]:
    """Decode the JSON text of a success response."""
    content = response["content"]
    assert content[0]["type"] == "text"
    return json.loads(content[0]["text"])


def test_the_module_loads_with_an_empty_environment(module: ModuleType) -> None:
    assert module.USE_CASE is not None


def test_success_returns_the_full_hand_off(module: ModuleType) -> None:
    result = body(module.handler(EVENT, make_context()))

    assert re.fullmatch(r"HO-[A-Z2-7]{8}", result["hand_off_id"])
    assert result == {
        "hand_off_id": result["hand_off_id"],
        "status": "queued",
        "priority": "high",
        "reason": "FRAUD_CONFIRMED",
        "customer_id": CUSTOMER_ID,
        "summary": EVENT["summary"],
        "related_ids": ["CMP-4KQ2ZJ7M3XH5TB6RWN2Y"],
    }


def test_the_same_event_gets_the_same_id(module: ModuleType) -> None:
    first = body(module.handler(EVENT, make_context()))["hand_off_id"]

    assert body(module.handler(EVENT, make_context()))["hand_off_id"] == first


def test_related_ids_may_be_left_out(module: ModuleType) -> None:
    event = {k: v for k, v in EVENT.items() if k != "related_ids"}

    assert body(module.handler(event, make_context()))["related_ids"] == []


@pytest.mark.parametrize("event", [None, [], "hand off"])
def test_a_non_object_event_returns_the_customer_id_error(
    module: ModuleType, event: object
) -> None:
    assert "customer_id" in module.handler(event, make_context())["error"]


def test_invalid_input_returns_the_field_error(module: ModuleType) -> None:
    response = module.handler({**EVENT, "priority": "urgent"}, make_context())

    assert response == {
        "error": "Invalid value for 'priority': must be high or normal. "
        "Ask the customer to confirm and retry."
    }


@pytest.mark.parametrize(
    "context", [make_context("open-claim-target___open_claim"), None]
)
def test_wrong_or_missing_tool_name_returns_an_error(
    module: ModuleType, context: object
) -> None:
    response = module.handler(EVENT, context)

    assert set(response) == {"error"}
    assert "human_agent_hand_off" in response["error"]


def test_unexpected_exception_returns_a_generic_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(**_kwargs: object) -> None:
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(module, "USE_CASE", SimpleNamespace(execute=explode))

    response = module.handler(EVENT, make_context())

    assert response == {"error": module.UNEXPECTED_ERROR_MESSAGE}
    assert "secret" not in response["error"]


def test_the_summary_is_never_logged(
    module: ModuleType, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    module.handler(EVENT, make_context())

    assert "queued HO-" in caplog.text
    assert EVENT["summary"] not in caplog.text
```

In `tests/unit/human_agent_hand_off/test_tool_spec.py`, replace the last test with:

```python
def test_description_asks_for_a_summary_a_goodbye_and_no_time() -> None:
    description = tool_spec()["description"]

    assert "without asking the customer anything again" in description
    assert "say goodbye in one or two sentences" in description
    assert "continue in this same chat" in description
    assert "Don't promise a time." in description
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/unit/human_agent_hand_off -q`
Expected: FAIL. Collection errors such as `ImportError: cannot import name 'hand_off_id'` and `ModuleNotFoundError: No module named 'human_agent_hand_off_lambda.delivery.dependencies'`.

- [ ] **Step 4: Write the implementation**

Replace `…/domain/entities/hand_off.py` with:

```python
"""Entities of the human_agent_hand_off use case."""

from dataclasses import dataclass


@dataclass(frozen=True)
class HandOff:
    """A validated hand-off to a human agent."""

    customer_id: str
    priority: str
    reason: str
    summary: str
    related_ids: tuple[str, ...]


@dataclass(frozen=True)
class HandOffResult:
    """The queued hand-off and its content-derived id."""

    hand_off_id: str
    hand_off: HandOff
```

Replace `…/domain/errors.py` with:

```python
"""Domain errors: the only failures the agent is allowed to see.

Each message says what went wrong and what the agent should do next. Messages
are built only from the tool's own input rules, never from internal details.
"""


class DomainError(Exception):
    """Base class for agent-facing errors raised by the use case.

    Attributes:
        message: Agent-facing text describing the failure and the next step.
    """

    def __init__(self, message: str) -> None:
        """Store the agent-facing message."""
        super().__init__(message)
        self.message: str = message


class InvalidInputError(DomainError):
    """A tool argument failed validation.

    Attributes:
        field: Name of the offending tool argument.
        reason: Short human-readable rule that was broken.
    """

    def __init__(self, field: str, reason: str) -> None:
        """Build the message from the field name and the broken rule."""
        self.field: str = field
        self.reason: str = reason
        super().__init__(
            f"Invalid value for '{field}': {reason}. "
            "Ask the customer to confirm and retry."
        )
```

In `…/application/use_cases/hand_off.py`, replace everything from the top of the file down to the end of the `execute` method (the line `return HandOffResult(hand_off_id=reference, priority=hand_off.priority)`) with the code below. Leave the five `_clean_*` functions below it unchanged.

```python
"""Use case: validate a hand-off to a human agent and give it an id."""

import base64
import hashlib
import re
from typing import Final

from human_agent_hand_off_lambda.domain.entities.hand_off import (
    HandOff,
    HandOffResult,
)
from human_agent_hand_off_lambda.domain.errors import InvalidInputError

PRIORITIES: Final = ("high", "normal")
REASONS: Final = ("FRAUD_CONFIRMED", "CUSTOMER_REQUEST", "UNRESOLVED", "OUT_OF_SCOPE")
MAX_SUMMARY_LENGTH: Final = 2000
MAX_RELATED_IDS: Final = 20
HAND_OFF_ID_PREFIX: Final = "HO-"
_HAND_OFF_ID_LENGTH: Final = 8
_RELATED_ID: Final = re.compile(r"[A-Z0-9-]{1,40}")
_RELATED_IDS_REASON: Final = (
    f"must be a list of at most {MAX_RELATED_IDS} ids made of letters, "
    "digits and dashes"
)


class HandOffUseCase:
    """Validate a hand-off and give it an id derived from its content.

    Every field but the summary is a closed set or an id, so only the summary
    carries free text written by the model. Nothing is stored or sent: the
    frontend reads the result from the agent's stream
    (docs/superpowers/specs/2026-10-03-human-hand-off-frontend-design.md, section 2).
    """

    def execute(
        self,
        customer_id: object,
        priority: object,
        reason: object,
        summary: object,
        related_ids: object,
    ) -> HandOffResult:
        """Validate every input, then return the hand-off with its id.

        Args:
            customer_id: The customer id exactly as it came in the tool event.
            priority: high or normal, as it came.
            reason: One of REASONS, as it came.
            summary: The summary for the human agent, as it came.
            related_ids: Optional list of related record ids, as it came.

        Raises:
            InvalidInputError: An input is invalid.
        """
        hand_off = HandOff(
            customer_id=_clean_customer_id(customer_id),
            priority=_clean_priority(priority),
            reason=_clean_reason(reason),
            summary=_clean_summary(summary),
            related_ids=_clean_related_ids(related_ids),
        )
        return HandOffResult(hand_off_id=hand_off_id(hand_off), hand_off=hand_off)


def hand_off_id(hand_off: HandOff) -> str:
    """Return ``HO-`` plus 8 base32 characters of a SHA-256 over the content.

    The same content always gives the same id, so a retried or repeated call
    never makes a second case. Related ids are sorted, so their order doesn't
    matter.
    """
    content = "|".join(
        (
            hand_off.customer_id,
            hand_off.priority,
            hand_off.reason,
            hand_off.summary,
            ",".join(sorted(hand_off.related_ids)),
        )
    )
    digest = hashlib.sha256(content.encode("utf-8")).digest()
    encoded = base64.b32encode(digest).decode("ascii")
    return HAND_OFF_ID_PREFIX + encoded[:_HAND_OFF_ID_LENGTH]
```

Replace `…/delivery/presenters/hand_off.py` with:

```python
"""Present the hand-off result as the JSON returned to the agent."""

from typing import Any

from human_agent_hand_off_lambda.domain.entities.hand_off import HandOffResult


def present_hand_off(result: HandOffResult) -> dict[str, Any]:
    """Return the full hand-off; the frontend builds the agent desk from it.

    "queued" means a person has the case and the summary; nobody has picked it
    up yet, so the agent promises no time.
    """
    hand_off = result.hand_off
    return {
        "hand_off_id": result.hand_off_id,
        "status": "queued",
        "priority": hand_off.priority,
        "reason": hand_off.reason,
        "customer_id": hand_off.customer_id,
        "summary": hand_off.summary,
        "related_ids": list(hand_off.related_ids),
    }
```

Replace `…/delivery/handler.py` with:

```python
"""Lambda handler for the ``human_agent_hand_off`` Gateway tool.

Handler string: ``human_agent_hand_off_lambda/delivery/handler.handler``.

Input: the tool arguments as the event (see
``gateway/tools/human_agent_hand_off/tool_spec.json``); the tool name arrives
in ``context.client_context.custom["bedrockAgentCoreToolName"]`` with a
``<target>___`` prefix. Every argument is passed to the use case bare.

Output: ``{"content": [{"type": "text", "text": <JSON>}]}`` on success, or
``{"error": <agent-facing message>}``. Raw exception text is never returned.

The function makes no AWS call and reads no configuration: the frontend reads
the hand-off from the agent's stream and opens the human agent's desk
(docs/superpowers/specs/2026-10-03-human-hand-off-frontend-design.md).
"""

import json
import logging
from collections.abc import Mapping
from typing import Any, Final

from human_agent_hand_off_lambda.application.use_cases.hand_off import HandOffUseCase
from human_agent_hand_off_lambda.delivery.presenters.hand_off import (
    present_hand_off,
)
from human_agent_hand_off_lambda.domain.errors import DomainError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TOOL_NAME: Final = "human_agent_hand_off"
_TOOL_NAME_DELIMITER: Final = "___"
UNEXPECTED_ERROR_MESSAGE: Final = (
    "Unexpected internal error sending the hand-off. Tell the customer you "
    "couldn't reach a person and that they can contact the bank through its "
    "usual channels."
)
_WRONG_TOOL_MESSAGE: Final = (
    f"This function only serves the '{TOOL_NAME}' tool. Don't retry; tell the "
    "customer they can contact the bank through its usual channels."
)


USE_CASE = HandOffUseCase()


def handler(event: object, context: object) -> dict[str, Any]:
    """Validate a hand-off to a human agent and return it to the agent.

    Args:
        event: Tool arguments passed directly by the AgentCore Gateway.
        context: Lambda context with the tool name in client_context.custom.

    Returns:
        A Gateway ``content`` response, or ``{"error": message}``.
    """
    tool_name = _tool_name(context)
    if tool_name != TOOL_NAME:
        logger.error("Unexpected tool name %r for %s", tool_name, TOOL_NAME)
        return {"error": _WRONG_TOOL_MESSAGE}

    args = event if isinstance(event, Mapping) else {}
    try:
        body = present_hand_off(
            USE_CASE.execute(
                customer_id=args.get("customer_id"),
                priority=args.get("priority"),
                reason=args.get("reason"),
                summary=args.get("summary"),
                related_ids=args.get("related_ids"),
            )
        )
    except DomainError as err:
        logger.warning(
            "%s returned an error: %s", TOOL_NAME, err.message, exc_info=True
        )
        return {"error": err.message}
    except Exception:
        logger.exception("Unexpected error in %s", TOOL_NAME)
        return {"error": UNEXPECTED_ERROR_MESSAGE}

    # The summary is never logged: it holds what the customer said.
    logger.info(
        "%s queued %s (priority=%s)", TOOL_NAME, body["hand_off_id"], body["priority"]
    )
    return {"content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]}


def _tool_name(context: object) -> str | None:
    """Return the tool name without its ``<target>___`` prefix, or None if absent."""
    try:
        full_name = context.client_context.custom["bedrockAgentCoreToolName"]  # type: ignore[attr-defined]
    except (AttributeError, KeyError, TypeError):
        return None
    if not isinstance(full_name, str):
        return None
    return full_name.rpartition(_TOOL_NAME_DELIMITER)[2]
```

In `gateway/tools/human_agent_hand_off/tool_spec.json`, replace the `"description"` value with:

```json
"description": "Sends the conversation to a human agent, who continues in this same chat. Use when the customer asks for a person, after a confirmed fraud case, for anything out of scope, or when you can't resolve the request. The summary must let the agent continue without asking the customer anything again: the card's last 4 digits, the transactions, what was blocked or opened (with ids) and what the customer said. Returns JSON with 'hand_off_id', 'status', 'priority', 'reason', 'customer_id', 'summary' and 'related_ids'. After it succeeds, say goodbye in one or two sentences: a person will continue in this same chat and the customer won't need to repeat anything. Don't promise a time.",
```

- [ ] **Step 5: Run the tests and lint**

Run: `pytest tests/unit/human_agent_hand_off -q && ruff format --check gateway tests && ruff check gateway tests`
Expected: all tests PASS; ruff prints no errors (line length is 88). If `ruff format --check` reports a file, run `ruff format gateway/tools/human_agent_hand_off tests/unit/human_agent_hand_off` and re-run.

Also confirm nothing still references SNS: `grep -rn -i "sns\|publisher\|HandOffUnavailable" gateway/tools/human_agent_hand_off tests/unit/human_agent_hand_off` prints nothing.

- [ ] **Step 6: Commit**

```bash
git add -A gateway/tools/human_agent_hand_off tests/unit/human_agent_hand_off
git commit -m "refactor(human_agent_hand_off): drop SNS; return the full hand-off with a content-derived id"
```

---

### Task 2: Remove the SNS topic and wire the hand-off to the Gateway and Cedar

**Files:**
- Modify: `infra-cdk/lib/data-construct.ts` (imports lines 7, 13, 14; class doc comment; the hand-off block after the tools loop)
- Modify: `infra-cdk/lib/backend-construct.ts` (`toolTargets`, about line 862)
- Modify: `gateway/policies/policy.cedar`
- Test: `infra-cdk/test/data-construct.test.ts`, `infra-cdk/test/backend-gateway.test.ts`, `infra-cdk/test/policy-cedar.test.ts`

**Interfaces:**
- Consumes: the Lambda from Task 1 (function name `ledgerlens-human-agent-hand-off`, handler `human_agent_hand_off_lambda/delivery/handler.handler`).
- Produces: Gateway target `human-agent-hand-off-target`; Cedar action `human-agent-hand-off-target___human_agent_hand_off`. The streamed tool name is therefore `human-agent-hand-off-target___human_agent_hand_off`.

- [ ] **Step 1: Write the failing tests**

In `infra-cdk/test/data-construct.test.ts`, replace the two tests `"the hand-off topic is encrypted; its Lambda runs outside the VPC and may only publish"` and `"the admin email gets the hand-offs only when it is configured"` with:

```ts
test("the hand-off Lambda runs outside the VPC with no environment, no SNS and no DSQL", () => {
  t.resourceCountIs("AWS::SNS::Topic", 0)
  t.resourceCountIs("AWS::SNS::Subscription", 0)
  const fns = Object.values(
    t.findResources("AWS::Lambda::Function", { Properties: { FunctionName: "ledgerlens-human-agent-hand-off" } })
  )
  expect(fns).toHaveLength(1)
  const fn = fns[0]
  expect(fn.Properties.VpcConfig).toBeUndefined()
  expect(fn.Properties.Handler).toBe("human_agent_hand_off_lambda.delivery.handler.handler")
  expect(fn.Properties.Timeout).toBe(10)
  expect(fn.Properties.Environment).toBeUndefined()
  const actions = actionsOf(fn.Properties.Role["Fn::GetAtt"][0])
  expect(actions.filter((a: string) => a.startsWith("sns:") || a.startsWith("dsql:"))).toEqual([])
})

test("an admin email no longer subscribes to anything", () => {
  const withEmail = synth({ ...config, admin_user_email: "ops@example.com" } as unknown as AppConfig)
  withEmail.resourceCountIs("AWS::SNS::Subscription", 0)
})
```

In `infra-cdk/test/backend-gateway.test.ts`, replace:

```ts
// The three read tools live in the data stack; the main stack imports them by name.
const TOOLS = ["list_credit_cards", "list_card_transactions", "get_session_context"]
```

with:

```ts
// The tools the agent can call live in the data stack; the main stack imports them by name.
const TOOLS = ["list_credit_cards", "list_card_transactions", "get_session_context", "human_agent_hand_off"]
```

and rename the test `"the Gateway has one target per read tool, pointing at the data stack's Lambda"` to `"the Gateway has one target per tool, pointing at the data stack's Lambda"`.

Append to `infra-cdk/test/policy-cedar.test.ts`:

```ts
test("the customer_id forbid covers every permitted tool, the hand-off included", () => {
  const actionsIn = (kind: string) =>
    statements
      .filter((s) => s.trim().startsWith(kind))
      .flatMap((s) => [...s.matchAll(/AgentCore::Action::"([^"]+)"/g)].map((m) => m[1]))
  expect(actionsIn("forbid").sort()).toEqual(actionsIn("permit").sort())
  expect(actionsIn("permit")).toContain("human-agent-hand-off-target___human_agent_hand_off")
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd infra-cdk && npx jest test/data-construct.test.ts test/policy-cedar.test.ts`
Expected: FAIL. `the hand-off Lambda runs outside the VPC…` fails on `resourceCountIs("AWS::SNS::Topic", 0)` (found 1); the new Cedar test fails on `toContain("human-agent-hand-off-target___human_agent_hand_off")`.

Run: `cd infra-cdk && npx jest test/backend-gateway.test.ts` (about 2 minutes)
Expected: FAIL. The target names lack `human-agent-hand-off-target`, and the Cedar test's actions lack `human-agent-hand-off-target___human_agent_hand_off`.

- [ ] **Step 3: Remove the topic in `infra-cdk/lib/data-construct.ts`**

Delete these three import lines:

```ts
import * as kms from "aws-cdk-lib/aws-kms"
import * as sns from "aws-cdk-lib/aws-sns"
import * as subscriptions from "aws-cdk-lib/aws-sns-subscriptions"
```

In the class doc comment, replace:

```ts
 * loads it (docs/superpowers/specs/2026-10-02-data-pipeline-design.md), the Gateway tool
 * Lambdas and the hand-off topic (docs/superpowers/specs/2026-10-03-write-tools-design.md).
```

with:

```ts
 * loads it (docs/superpowers/specs/2026-10-02-data-pipeline-design.md) and the Gateway tool
 * Lambdas (docs/superpowers/specs/2026-10-03-write-tools-design.md).
```

Replace the whole block from `// The hand-off tool only publishes to SNS: it runs outside the VPC (which has no route` through `handOffTopic.grantPublish(handOff)` with:

```ts
    // The hand-off tool only validates the hand-off and returns it; the frontend reads it
    // from the agent's stream (docs/superpowers/specs/2026-10-03-human-hand-off-frontend-design.md).
    // It calls no AWS service, so it runs outside the VPC with the default role.
    new PythonFunction(this, "HumanAgentHandOffFn", {
      functionName: "ledgerlens-human-agent-hand-off",
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      entry: path.join(__dirname, "..", "..", "gateway", "tools", "human_agent_hand_off"), // nosemgrep: javascript.lang.security.audit.path-traversal.path-join-resolve-traversal.path-join-resolve-traversal
      index: "human_agent_hand_off_lambda/delivery/handler.py",
      handler: "handler",
      bundling: { assetExcludes: ["**/__pycache__", "**/*.pyc"] },
      timeout: cdk.Duration.seconds(10),
      logGroup: new logs.LogGroup(this, "HumanAgentHandOffLogs", {
        logGroupName: `/aws/lambda/${props.config.stack_name_base}-human-agent-hand-off`,
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    })
```

(The construct ids `HumanAgentHandOffFn` and `HumanAgentHandOffLogs` are unchanged, so the deployed function is updated in place, not replaced.)

- [ ] **Step 4: Add the Gateway target in `infra-cdk/lib/backend-construct.ts`**

Replace:

```ts
    // One Gateway target per LedgerLens read tool. The tool Lambdas live in the data
```

with:

```ts
    // One Gateway target per LedgerLens tool the agent can call. The tool Lambdas live in the data
```

and replace:

```ts
      { tool: "get_session_context", id: "GetSessionContext" },
    ].map(({ tool, id }) => {
```

with:

```ts
      { tool: "get_session_context", id: "GetSessionContext" },
      { tool: "human_agent_hand_off", id: "HumanAgentHandOff" },
    ].map(({ tool, id }) => {
```

- [ ] **Step 5: Add the hand-off to both Cedar statements in `gateway/policies/policy.cedar`**

Replace the RULES header lines:

```
// 1) A token with a linked customer can use the three LedgerLens read tools.
// 2) No call may be about a different customer than the one in the token.
```

with:

```
// 1) A token with a linked customer can use the LedgerLens tools: the three read tools
//    and the hand-off to a human agent.
// 2) No call may be about a different customer than the one in the token.
```

Replace the statement-1 comment line `// 1) A signed-in customer can use the LedgerLens read tools. A blank customer_id` with `// 1) A signed-in customer can use the LedgerLens tools. A blank customer_id`.

In **both** the `permit` and the `forbid` action lists, replace:

```
    AgentCore::Action::"get-session-context-target___get_session_context"
  ],
```

with:

```
    AgentCore::Action::"get-session-context-target___get_session_context",
    AgentCore::Action::"human-agent-hand-off-target___human_agent_hand_off"
  ],
```

(The hand-off's `tool_spec.json` requires `customer_id`, so statement 2 needs no `has` guard, as its comment already says.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd infra-cdk && npx jest test/data-construct.test.ts test/policy-cedar.test.ts test/backend-gateway.test.ts && npx tsc --noEmit`
Expected: all PASS; `tsc` prints nothing.

- [ ] **Step 7: Commit**

```bash
git add infra-cdk/lib/data-construct.ts infra-cdk/lib/backend-construct.ts infra-cdk/test/data-construct.test.ts infra-cdk/test/backend-gateway.test.ts gateway/policies/policy.cedar
git commit -m "feat(cdk): hand-off without SNS, with its Gateway target and Cedar statements"
```

---

### Task 3: System prompt v2 with the hand-off rules and the goodbye

**Files:**
- Modify: `patterns/strands-single-agent/tools/system_prompt.py` (`PROMPT_VERSION`, the FRAUD AND ACTIONS and BOUNDARIES blocks)
- Test: `tests/unit/test_system_prompt.py`

**Interfaces:**
- Consumes: tool name `human_agent_hand_off` and its reasons (Task 1).
- Produces: `PROMPT_VERSION = "v2"`.

Note: fraud hands off at any amount (priority high above USD 500, else normal), because v1 already says a person must handle all fraud and the agent still can't block cards. This matches the spec's priority rule.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_system_prompt.py`:

Replace the `UNAVAILABLE_TOOLS` block with:

```python
# Designed in docs/LEDGERLENS_PRODUCT_DESIGN.md §7 but not deployed yet.
UNAVAILABLE_TOOLS = (
    "classify_call_type",
    "explain_transaction",
    "transaction_fraud_detection",
    "block_credit_card",
    "open_claim",
)
```

Replace `test_blank_customer_id_points_to_a_human_agent` with:

```python
def test_blank_customer_id_points_to_a_human_agent(system_prompt):
    prompt = system_prompt.build_system_prompt("")

    assert "human agent" in prompt
    # No customer_id means Cedar denies every tool, so the unlinked block mustn't
    # promise a hand-off.
    assert "hand-off" not in system_prompt.UNLINKED_SESSION_BLOCK
    assert "hand off" not in system_prompt.UNLINKED_SESSION_BLOCK.lower()
```

Add at the end of the file:

```python
def test_prompt_hands_off_and_says_goodbye(system_prompt):
    prompt = system_prompt.BASE_SYSTEM_PROMPT

    assert "human_agent_hand_off" in prompt
    assert "say goodbye in one or two sentences" in prompt
    assert "this same chat" in prompt
    assert "Promise no time" in prompt
    assert "Never say you have transferred them" not in prompt
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_system_prompt.py -q`
Expected: FAIL in `test_prompt_hands_off_and_says_goodbye` (`human_agent_hand_off` not in prompt).

- [ ] **Step 3: Write the v2 prompt**

In `patterns/strands-single-agent/tools/system_prompt.py`, replace `PROMPT_VERSION = "v1"` with `PROMPT_VERSION = "v2"`.

Replace this text inside `BASE_SYSTEM_PROMPT`:

```
FRAUD AND ACTIONS
You can only read. You can't block cards, open claims or disputes, or change anything. When
the customer doesn't recognise a charge, suspects fraud or asks for an action:
- Show the evidence you have, in plain words.
- Say that a human agent must handle it, and that if they suspect fraud they should ask the
  bank to block the card right away.
- Give a two-line summary they can quote: the card's last 4 digits, the transactions
  involved, and what they told you.
- Never say a charge is or isn't fraud for certain. Never promise a refund or an outcome.
  Never say you have transferred them or that someone will contact them.

BOUNDARIES
- Out of scope: new products, limit increases, credit or investment advice, loans, and
  changes to personal data. Say so in one sentence and say that a human agent can help.
- If the records contradict each other, say they don't match and that a human agent should
  review them.
```

with:

```
FRAUD AND ACTIONS
You can't block cards, open claims or disputes, or change anything. When the customer
doesn't recognise a charge, suspects fraud or asks for an action:
- Show the evidence you have, in plain words.
- Hand off to a person (see HAND OFF). If they suspect fraud, tell them the person can
  block the card.
- Never say a charge is or isn't fraud for certain. Never promise a refund or an outcome.

HAND OFF
Call human_agent_hand_off right away, with no extra questions, when the customer asks for a
person (reason CUSTOMER_REQUEST). Also call it when:
- they don't recognise a charge or suspect fraud: reason FRAUD_CONFIRMED, priority high
  when the charges add up to more than USD 500;
- the request is out of scope and they accept your offer of a person: reason OUT_OF_SCOPE;
- you can't resolve the request within 3 tool calls, or the records contradict each other:
  reason UNRESOLVED.
Use priority normal unless a rule above says high. The summary must let the person continue
without asking anything again: the card's last 4 digits, the transactions (merchant, amount
with currency, date), what you told the customer and what they said. Put transaction and
case ids in related_ids.
When it succeeds, say goodbye in one or two sentences: a person continues in this same chat
and they won't need to repeat anything. Promise no time, and write nothing after it.
If it fails, say you couldn't reach a person and that they can contact the bank through its
usual channels.

BOUNDARIES
- Out of scope: new products, limit increases, credit or investment advice, loans, and
  changes to personal data. Say so in one sentence and offer to pass them to a person.
- If the records contradict each other, say they don't match and hand off.
```

- [ ] **Step 4: Pin the v2 hash**

In `tests/unit/test_system_prompt.py`, keep v1 and add v2 (computed from exactly the text in Step 3):

```python
PINNED_PROMPT_HASHES = {
    "v1": "f17e2e64c42b3a77401584aecfb37120e3d08fdeacf71f1e68711d655321bdc7",
    "v2": "1a5a26533d513a4e2584c171abef12441850fa334dd12f3c17fa0fee18f654a1",
}
```

If `test_prompt_version_names_this_template` fails, the prompt text differs from Step 3 (whitespace included). Print the actual hash with `python -c "import sys, hashlib; sys.path.insert(0, 'patterns/strands-single-agent'); from tools.system_prompt import prompt_template; print(hashlib.sha256(prompt_template().encode()).hexdigest())"`, diff your edit against Step 3, and fix the text rather than the hash.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/unit/test_system_prompt.py -q && ruff format --check tests && ruff check tests`
Expected: all PASS (`patterns/` is excluded from ruff by `ruff.toml`).

- [ ] **Step 6: Commit**

```bash
git add patterns/strands-single-agent/tools/system_prompt.py tests/unit/test_system_prompt.py
git commit -m "feat(agent): prompt v2 hands off to a person and says goodbye"
```

---

### Task 4: Frontend hand-off detection, phases and copy helpers

**Files:**
- Create: `frontend/src/lib/handoff.ts`
- Modify: `frontend/src/hooks/useToolRenderer.ts`, `frontend/src/components/chat/types.ts:2`
- Test: `frontend/src/test/handoff.test.ts`, `frontend/src/test/tool-renderer.test.ts`

**Interfaces:**
- Consumes: the tool result JSON from Task 1; the streamed name from Task 2.
- Produces (used by Tasks 5–7):
  - `useToolRenderer.ts`: `bareToolName(name: string): string`; `getToolRenderer(name)` also resolves prefixed names.
  - `types.ts`: `MessageRole = "user" | "assistant" | "human"`.
  - `handoff.ts`: `HAND_OFF_TOOL = "human_agent_hand_off"`, `HAND_OFF_DELAY_MS = 600`, `type HandOffReason`, `interface HandOffResult`, `interface HandOff extends HandOffResult { goodbye: string; at: string }`, `type Phase = "ai" | "connecting" | "joined"`, `parseHandOffResult(result?: string): HandOffResult | null`, `findHandOff(messages: Message[]): HandOff | null`, `phaseOf(handOff: HandOff | null, messages: Message[]): Phase`, `reasonLabel(reason: string): string`, `queueFor(reason: string): string`, `suggestedReplies(handOff: HandOff, customerName: string): [string, string]`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/test/tool-renderer.test.ts`:

```ts
import { describe, it, expect } from "vitest"
import { bareToolName, getToolRenderer, useDefaultTool, useToolRenderer } from "@/hooks/useToolRenderer"

describe("tool renderer lookup", () => {
  it("finds a named renderer by the Gateway-prefixed name and falls back to the default", () => {
    const named = () => "named"
    const fallback = () => "default"
    useDefaultTool(fallback)
    useToolRenderer("human_agent_hand_off", named)

    expect(getToolRenderer("human-agent-hand-off-target___human_agent_hand_off")).toBe(named)
    expect(getToolRenderer("human_agent_hand_off")).toBe(named)
    expect(getToolRenderer("list-credit-cards-target___list_credit_cards")).toBe(fallback)
  })

  it("strips only the target prefix", () => {
    expect(bareToolName("human-agent-hand-off-target___human_agent_hand_off")).toBe("human_agent_hand_off")
    expect(bareToolName("human_agent_hand_off")).toBe("human_agent_hand_off")
  })
})
```

Create `frontend/src/test/handoff.test.ts`:

```ts
import { describe, it, expect } from "vitest"
import type { Message, MessageSegment, ToolCallStatus } from "@/components/chat/types"
import {
  findHandOff,
  parseHandOffResult,
  phaseOf,
  queueFor,
  reasonLabel,
  suggestedReplies,
  type HandOff,
} from "@/lib/handoff"

const RESULT = {
  hand_off_id: "HO-7Q3KX2MA",
  status: "queued",
  priority: "high" as const,
  reason: "FRAUD_CONFIRMED" as const,
  customer_id: "CLI-F2DZJYU0POJ9",
  summary: "No reconoce 2 cargos en Miami.",
  related_ids: ["TX-88", "TX-89"],
}
const PREFIXED = "human-agent-hand-off-target___human_agent_hand_off"
const AT = "2026-10-03T08:18:00.000Z"

const tool = (result: string | undefined, status: ToolCallStatus = "complete", name = PREFIXED): MessageSegment => ({
  type: "tool",
  toolCall: { toolUseId: "t1", name, input: "{}", result, status },
})
const text = (content: string): MessageSegment => ({ type: "text", content })
const assistant = (...segments: MessageSegment[]): Message => ({ role: "assistant", content: "", timestamp: AT, segments })
const user = (content: string): Message => ({ role: "user", content, timestamp: AT })
const human = (content: string): Message => ({ role: "human", content, timestamp: AT })
const handOff = (over: Partial<HandOff> = {}): HandOff => ({ ...RESULT, goodbye: "", at: AT, ...over })

describe("findHandOff", () => {
  it("returns the result, the goodbye after the tool and the message time", () => {
    const found = findHandOff([
      user("quiero hablar con una persona"),
      assistant(text("Te paso con una persona."), tool(JSON.stringify(RESULT)), text(" Una persona sigue contigo aquí.")),
    ])
    expect(found).toEqual({ ...RESULT, goodbye: "Una persona sigue contigo aquí.", at: AT })
  })

  it("matches the bare tool name too", () => {
    expect(findHandOff([assistant(tool(JSON.stringify(RESULT), "complete", "human_agent_hand_off"))])?.hand_off_id).toBe(
      "HO-7Q3KX2MA"
    )
  })

  it("falls back to the text before the tool when the goodbye came first", () => {
    const found = findHandOff([assistant(text("Una persona sigue contigo aquí."), tool(JSON.stringify(RESULT)))])
    expect(found?.goodbye).toBe("Una persona sigue contigo aquí.")
  })

  it.each([
    ["an error result", JSON.stringify({ error: "The hand-off couldn't be sent." })],
    ["text that isn't JSON", "Unexpected internal error sending the hand-off."],
    ["JSON without an id", JSON.stringify({ status: "queued" })],
    ["no result", undefined],
  ])("ignores %s", (_label, result) => {
    expect(findHandOff([assistant(tool(result), text("Hasta pronto."))])).toBeNull()
  })

  it("ignores a call that hasn't finished", () => {
    expect(findHandOff([assistant(tool(JSON.stringify(RESULT), "executing"))])).toBeNull()
  })

  it("ignores other tools", () => {
    expect(findHandOff([assistant(tool(JSON.stringify(RESULT), "complete", "list-credit-cards-target___list_credit_cards"))])).toBeNull()
  })

  it("looks only at the last message", () => {
    expect(findHandOff([assistant(tool(JSON.stringify(RESULT))), user("hola")])).toBeNull()
  })

  it("takes the first valid call when the tool ran twice", () => {
    const second = { ...RESULT, hand_off_id: "HO-SECOND22" }
    const found = findHandOff([assistant(tool(JSON.stringify(RESULT)), tool(JSON.stringify(second)), text("Chao."))])
    expect(found?.hand_off_id).toBe("HO-7Q3KX2MA")
  })
})

describe("parseHandOffResult", () => {
  it("gives related_ids a default when the result has none", () => {
    const { related_ids: _omit, ...withoutIds } = RESULT
    expect(parseHandOffResult(JSON.stringify(withoutIds))?.related_ids).toEqual([])
  })
})

describe("phaseOf", () => {
  it("moves from ai to connecting to joined", () => {
    expect(phaseOf(null, [user("hola")])).toBe("ai")
    expect(phaseOf(handOff(), [user("hola")])).toBe("connecting")
    expect(phaseOf(handOff(), [user("hola"), human("Hola, soy Laura.")])).toBe("joined")
  })
})

describe("labels", () => {
  it("names the queue and the reason in Spanish, passing unknown reasons through", () => {
    expect(queueFor("FRAUD_CONFIRMED")).toBe("Fraudes")
    expect(queueFor("OUT_OF_SCOPE")).toBe("Servicio general")
    expect(reasonLabel("FRAUD_CONFIRMED")).toBe("Fraude confirmado")
    expect(reasonLabel("SOMETHING_NEW")).toBe("SOMETHING_NEW")
  })
})

describe("suggestedReplies", () => {
  it("greets by first name and names the queue and the case", () => {
    const [hello, next] = suggestedReplies(handOff(), "Carlos Rendón")
    expect(hello).toBe(
      "Hola Carlos, soy Laura, de Fraudes. Ya tengo tu caso HO-7Q3KX2MA y todo lo que hablaste con el asistente, así que no necesitas repetir nada."
    )
    expect(next).toContain("otros intentos")
  })

  it("leaves the name out when the profile has none", () => {
    const [hello] = suggestedReplies(handOff({ reason: "CUSTOMER_REQUEST" }), "  ")
    expect(hello.startsWith("Hola, soy Laura, de Servicio general.")).toBe(true)
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest --run src/test/handoff.test.ts src/test/tool-renderer.test.ts`
Expected: FAIL. `Failed to resolve import "@/lib/handoff"` and `bareToolName` is not exported.

- [ ] **Step 3: Write the implementation**

In `frontend/src/components/chat/types.ts`, replace `export type MessageRole = "user" | "assistant"` with:

```ts
// "human" is the human agent (Laura) after a hand-off; those messages never reach AgentCore
export type MessageRole = "user" | "assistant" | "human"
```

Replace `frontend/src/hooks/useToolRenderer.ts` with:

```ts
import type { ReactNode } from "react"
import type { ToolCallStatus } from "@/components/chat/types"

export interface ToolRenderProps {
  name: string
  args: string
  status: ToolCallStatus
  result?: string
}

export type ToolRenderFn = (props: ToolRenderProps) => ReactNode

const renderers = new Map<string, ToolRenderFn>()

/** The tool name without the Gateway's "<target>___" prefix. */
export const bareToolName = (name: string): string => name.split("___").pop() ?? name

export function useDefaultTool(render: ToolRenderFn) {
  renderers.set("*", render)
}

export function useToolRenderer(name: string, render: ToolRenderFn) {
  renderers.set(name, render)
}

export function getToolRenderer(name: string): ToolRenderFn | null {
  return renderers.get(name) ?? renderers.get(bareToolName(name)) ?? renderers.get("*") ?? null
}
```

Create `frontend/src/lib/handoff.ts`:

```ts
import type { Message, MessageSegment } from "@/components/chat/types"
import { bareToolName } from "@/hooks/useToolRenderer"

export const HAND_OFF_TOOL = "human_agent_hand_off"
/** Pause between the end of the goodbye and the split, so the goodbye can be read. */
export const HAND_OFF_DELAY_MS = 600

export type HandOffReason = "FRAUD_CONFIRMED" | "CUSTOMER_REQUEST" | "UNRESOLVED" | "OUT_OF_SCOPE"

/** What human_agent_hand_off returns (spec §2.2). */
export interface HandOffResult {
  hand_off_id: string
  status: string
  priority: "high" | "normal"
  reason: HandOffReason
  customer_id: string
  summary: string
  related_ids: string[]
}

/** The tool result plus what the desk shows from the stream. */
export interface HandOff extends HandOffResult {
  /** The agent's words to the customer around the hand-off, verbatim. */
  goodbye: string
  /** ISO time of the assistant message that made the hand-off. */
  at: string
}

/** ai: the bot owns the chat; connecting: handed off, Laura hasn't written; joined: she has. */
export type Phase = "ai" | "connecting" | "joined"

/** The hand-off result, or null for an error, text that isn't JSON or a missing id. */
export function parseHandOffResult(result: string | undefined): HandOffResult | null {
  if (!result) return null
  try {
    const value: unknown = JSON.parse(result)
    if (typeof value === "object" && value !== null && typeof (value as HandOffResult).hand_off_id === "string") {
      const found = value as HandOffResult
      return { ...found, related_ids: Array.isArray(found.related_ids) ? found.related_ids : [] }
    }
  } catch {
    // not JSON: an error text from the Gateway or the Lambda
  }
  return null
}

const textOf = (segments: MessageSegment[]) =>
  segments
    .flatMap(s => (s.type === "text" ? [s.content] : []))
    .join("")
    .trim()

/** The first completed, valid hand-off in the last message, if that message is the agent's. */
export function findHandOff(messages: Message[]): HandOff | null {
  const last = messages[messages.length - 1]
  if (last?.role !== "assistant" || !last.segments) return null
  const segments = last.segments
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i]
    if (seg.type !== "tool" || seg.toolCall.status !== "complete") continue
    if (bareToolName(seg.toolCall.name) !== HAND_OFF_TOOL) continue
    const result = parseHandOffResult(seg.toolCall.result)
    if (!result) continue
    // the goodbye normally follows the tool; if the model said it first, use what came before
    const goodbye = textOf(segments.slice(i + 1)) || textOf(segments.slice(0, i))
    return { ...result, goodbye, at: last.timestamp }
  }
  return null
}

export const phaseOf = (handOff: HandOff | null, messages: Message[]): Phase =>
  !handOff ? "ai" : messages.some(m => m.role === "human") ? "joined" : "connecting"

const REASON_LABEL: Record<HandOffReason, string> = {
  FRAUD_CONFIRMED: "Fraude confirmado",
  CUSTOMER_REQUEST: "Pidió hablar con una persona",
  UNRESOLVED: "El asistente no pudo resolverlo",
  OUT_OF_SCOPE: "Fuera del alcance del asistente",
}

export const reasonLabel = (reason: string): string => REASON_LABEL[reason as HandOffReason] ?? reason

export const queueFor = (reason: string): string => (reason === "FRAUD_CONFIRMED" ? "Fraudes" : "Servicio general")

const NEXT_STEP: Record<HandOffReason, string> = {
  FRAUD_CONFIRMED: "Voy a revisar si hubo otros intentos con tus tarjetas y te cuento por aquí mismo.",
  CUSTOMER_REQUEST: "Cuéntame en qué te puedo ayudar y lo revisamos juntos.",
  UNRESOLVED: "Voy a revisar tu caso con más detalle y te confirmo por aquí mismo.",
  OUT_OF_SCOPE: "Esa solicitud la reviso yo. Dame un momento para validar tus datos.",
}

/** Two replies Laura can send as they are: a greeting that shows she has the case, then a next step. */
export function suggestedReplies(handOff: HandOff, customerName: string): [string, string] {
  const firstName = customerName.trim().split(/\s+/)[0]
  const queue = queueFor(handOff.reason)
  const hello = firstName ? `Hola ${firstName}, soy Laura, de ${queue}.` : `Hola, soy Laura, de ${queue}.`
  return [
    `${hello} Ya tengo tu caso ${handOff.hand_off_id} y todo lo que hablaste con el asistente, así que no necesitas repetir nada.`,
    NEXT_STEP[handOff.reason] ?? NEXT_STEP.CUSTOMER_REQUEST,
  ]
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest --run src/test/handoff.test.ts src/test/tool-renderer.test.ts && npx tsc --noEmit && npm run lint`
Expected: all PASS; no type errors; lint prints no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/handoff.ts frontend/src/hooks/useToolRenderer.ts frontend/src/components/chat/types.ts frontend/src/test/handoff.test.ts frontend/src/test/tool-renderer.test.ts
git commit -m "feat(frontend): detect the hand-off in the streamed tool result"
```

---

### Task 5: Theme tokens, Geist fix, LedgerLens header with the status track, Spanish composer

**Files:**
- Modify: `frontend/src/styles/globals.css`, `frontend/index.html`, `frontend/src/components/chat/ChatHeader.tsx`, `frontend/src/components/chat/ChatInput.tsx`
- Test: `frontend/src/test/config.test.ts:173`

**Interfaces:**
- Consumes: `type Phase` from Task 4.
- Produces: Tailwind classes `bg-ai`, `text-ai`, `border-ai`, `bg-ai-bg`, `bg-human`, `text-human`, `border-human`, `bg-human-bg`, `bg-page`; `ChatHeader` prop `phase?: Phase` (default `"ai"`); `ChatInput` prop `placeholder?: string` (default `"Escribe un mensaje…"`); the view-transition name `handoff-ticket` gets a 320 ms animation.

- [ ] **Step 1: Write the failing test**

In `frontend/src/test/config.test.ts`, replace:

```ts
      expect(indexHtml).toContain("<title>Fullstack AgentCore Solution Template</title>")
```

with:

```ts
      expect(indexHtml).toContain("<title>LedgerLens</title>")
      // Google Fonts names the family "Geist"; "Geist Sans" doesn't exist there
      expect(indexHtml).toContain("family=Geist:wght@")
      expect(indexHtml).not.toContain("Geist+Sans")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest --run src/test/config.test.ts`
Expected: FAIL (`expected … to contain "<title>LedgerLens</title>"`).

- [ ] **Step 3: Write the implementation**

In `frontend/index.html`, replace:

```html
    <meta name="description" content="A solution template for building GenAI applications with AgentCore" />
    <title>Fullstack AgentCore Solution Template</title>
    <!-- Google Fonts for Geist Sans and Geist Mono -->
```

with:

```html
    <meta name="description" content="LedgerLens · asistente de tarjetas de crédito de LATAM Bank" />
    <title>LedgerLens</title>
    <!-- Google Fonts for Geist and Geist Mono -->
```

and replace `family=Geist+Sans:wght@100..900` with `family=Geist:wght@100..900` in the stylesheet link.

In `frontend/src/styles/globals.css`:

After the line `  --color-brand-orange: hsl(12, 76%, 61%);` (inside `@theme inline`), add:

```css
  /* Tier colors (.superdesign/design-system.md): teal = AI assistant, orange = human agent */
  --color-ai: hsl(173 62% 26%);
  --color-ai-bg: hsl(173 42% 90%);
  --color-human: hsl(12 68% 42%);
  --color-human-bg: hsl(12 80% 94%);
  --color-page: hsl(195 22% 95%);
```

Replace:

```css
  --font-geist-sans:
    "Geist Sans", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
```

with:

```css
  --font-geist-sans: "Geist", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
```

Append at the end of the file:

```css
/* Hand-off split (spec §6): the ticket morphs into the desk's case card */
::view-transition-group(*) {
  animation-duration: 320ms;
  animation-timing-function: ease-out;
}

@media (prefers-reduced-motion: reduce) {
  /* cross-fade only: the ticket doesn't travel */
  ::view-transition-group(handoff-ticket) {
    animation: none;
  }
}
```

Replace `frontend/src/components/chat/ChatHeader.tsx` with:

```tsx
import { Button } from "@/components/ui/button"
import { Check, Plus, ShieldCheck } from "lucide-react"
import { useAuth } from "@/hooks/useAuth"
import type { Phase } from "@/lib/handoff"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"

type ChatHeaderProps = {
  title?: string | undefined
  onNewChat: () => void
  canStartNewChat: boolean
  phase?: Phase
}

const STEP = "flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[.08em]"

/** Who owns the conversation: the AI assistant, then the person it handed off to. */
function StatusTrack({ phase }: { phase: Phase }) {
  const human = phase !== "ai"
  return (
    <div className="hidden items-center gap-3 md:flex" aria-live="polite">
      <span className={`${STEP} text-ai`}>
        {human ? <Check className="h-3.5 w-3.5" /> : <span className="h-2 w-2 rounded-full bg-ai" />}
        Asistente IA
      </span>
      <span className="h-px w-8 bg-border" />
      <span className={`${STEP} ${human ? "text-human" : "text-muted-foreground/60"}`}>
        <span
          className={`h-2 w-2 rounded-full ${human ? "bg-human" : "bg-muted-foreground/30"} ${
            phase === "connecting" ? "animate-pulse" : ""
          }`}
        />
        {human ? "Persona · Laura" : "Persona"}
        {phase === "connecting" && <span className="font-normal normal-case tracking-normal">conectando</span>}
      </span>
    </div>
  )
}

export function ChatHeader({ title, onNewChat, canStartNewChat, phase = "ai" }: ChatHeaderProps) {
  const { isAuthenticated, signOut } = useAuth()

  return (
    <header className="flex h-14 w-full items-center justify-between gap-4 border-b bg-white px-4">
      <div className="flex items-center gap-2">
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand-dark text-white">
          <ShieldCheck className="h-4 w-4" />
        </span>
        <div className="leading-tight">
          <h1 className="text-base font-bold">{title || "LedgerLens"}</h1>
          <p className="text-xs text-muted-foreground">LATAM Bank</p>
        </div>
      </div>
      <StatusTrack phase={phase} />
      <div className="flex items-center gap-2">
        <Button onClick={onNewChat} variant="outline" className="gap-2" disabled={!canStartNewChat}>
          <Plus className="h-4 w-4" />
          Nueva conversación
        </Button>
        {isAuthenticated && (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="outline">Logout</Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Confirm Logout</AlertDialogTitle>
                <AlertDialogDescription>
                  Are you sure you want to log out? You will need to sign in again to access your
                  account.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction onClick={() => signOut()}>Confirm</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
      </div>
    </header>
  )
}
```

In `frontend/src/components/chat/ChatInput.tsx`:
- In `interface ChatInputProps`, after `className?: string`, add `placeholder?: string`.
- In the destructuring, after `className = "",` add `placeholder = "Escribe un mensaje…",`.
- Replace `placeholder="Type your message... (Ctrl+Enter for new line)"` with `placeholder={placeholder}`.
- Replace `Thinking...` with `Pensando…` and the `Send` label text (the line `              Send` after `<Send className="h-4 w-4 mr-2" />`) with `              Enviar`.

- [ ] **Step 4: Run the checks**

Run: `cd frontend && npm test && npx tsc --noEmit && npm run lint && npm run build`
Expected: all tests PASS (including `config.test.ts`); build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html frontend/src/styles/globals.css frontend/src/components/chat/ChatHeader.tsx frontend/src/components/chat/ChatInput.tsx frontend/src/test/config.test.ts
git commit -m "feat(frontend): LedgerLens header with the hand-off status track, tier tokens and the Geist fix"
```

---

### Task 6: Hand-off ticket and tier-colored messages

**Files:**
- Create: `frontend/src/components/chat/HandOffTicket.tsx`
- Modify: `frontend/src/components/chat/ChatMessage.tsx` (whole file), `frontend/src/components/chat/ChatMessages.tsx` (whole file)
- Test: `frontend/src/test/handoff-ticket.test.tsx`

**Interfaces:**
- Consumes: `parseHandOffResult`, `reasonLabel` (Task 4); `ToolRenderProps` (Task 4); tokens (Task 5).
- Produces: `HandOffTicket(props: ToolRenderProps & { tagged: boolean })`, `PriorityPill({ priority })`, `IdChips({ ids })`, `HAND_OFF_TRANSITION: CSSProperties` (all from `HandOffTicket.tsx`); `ChatMessages` gains optional `hideFeedback?: boolean` and `messagesEndRef` becomes optional; `ChatMessage` gains `hideFeedback?: boolean`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/handoff-ticket.test.tsx`:

```tsx
import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { HandOffTicket } from "@/components/chat/HandOffTicket"

const NAME = "human-agent-hand-off-target___human_agent_hand_off"
const RESULT = JSON.stringify({
  hand_off_id: "HO-7Q3KX2MA",
  status: "queued",
  priority: "high",
  reason: "FRAUD_CONFIRMED",
  customer_id: "CLI-F2DZJYU0POJ9",
  summary: "No reconoce 2 cargos.",
  related_ids: ["TX-88", "TX-89"],
})

describe("HandOffTicket", () => {
  it("shows the case, its priority, reason and ids for a valid result", () => {
    render(<HandOffTicket name={NAME} args="{}" status="complete" result={RESULT} tagged />)

    expect(screen.getByText("Caso HO-7Q3KX2MA")).toBeInTheDocument()
    expect(screen.getByText("ALTA")).toBeInTheDocument()
    expect(screen.getByText("Fraude confirmado")).toBeInTheDocument()
    expect(screen.getByText("TX-89")).toBeInTheDocument()
    expect(screen.getByText("Enviado a una persona")).toBeInTheDocument()
  })

  it("shows that it is sending while the call runs", () => {
    render(<HandOffTicket name={NAME} args="{}" status="executing" tagged={false} />)

    expect(screen.getByText("Enviando a una persona…")).toBeInTheDocument()
  })

  it("falls back to the plain tool row for an error result", () => {
    render(<HandOffTicket name={NAME} args="{}" status="complete" result='{"error":"down"}' tagged={false} />)

    expect(screen.queryByText(/Caso/)).toBeNull()
    expect(screen.getByText(NAME)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest --run src/test/handoff-ticket.test.tsx`
Expected: FAIL (`Failed to resolve import "@/components/chat/HandOffTicket"`).

- [ ] **Step 3: Write the implementation**

Create `frontend/src/components/chat/HandOffTicket.tsx`:

```tsx
import type { CSSProperties } from "react"
import { Loader2, Ticket } from "lucide-react"
import type { ToolRenderProps } from "@/hooks/useToolRenderer"
import { parseHandOffResult, reasonLabel } from "@/lib/handoff"
import { ToolCallDisplay } from "./ToolCallDisplay"

/** The split's shared element: the ticket in the chat, then the case card on the desk. */
export const HAND_OFF_TRANSITION = { viewTransitionName: "handoff-ticket" } as CSSProperties

export function PriorityPill({ priority }: { priority: string }) {
  return priority === "high" ? (
    <span className="rounded-full border border-red-700 px-2 py-0.5 text-[11px] font-semibold text-red-700">ALTA</span>
  ) : (
    <span className="rounded-full border bg-muted px-2 py-0.5 text-[11px] font-semibold text-muted-foreground">
      Normal
    </span>
  )
}

export function IdChips({ ids }: { ids: string[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {ids.map(id => (
        <span key={id} className="rounded-full border bg-white px-2 py-0.5 font-mono text-[11px]">
          {id}
        </span>
      ))}
    </div>
  )
}

/** Renders human_agent_hand_off: a spinner while it runs, then the case ticket. */
export function HandOffTicket({ tagged, ...props }: ToolRenderProps & { tagged: boolean }) {
  if (props.status !== "complete") {
    return (
      <div className="flex items-center gap-2 text-sm text-human">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Enviando a una persona…
      </div>
    )
  }
  const result = parseHandOffResult(props.result)
  if (!result) return <ToolCallDisplay {...props} />
  return (
    <div
      style={tagged ? HAND_OFF_TRANSITION : undefined}
      className="flex w-full max-w-md flex-col gap-2 rounded-xl border border-human bg-human-bg p-3 animate-in fade-in slide-in-from-bottom-1 duration-200"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 font-mono text-sm font-semibold text-human">
          <Ticket className="h-4 w-4" />
          Caso {result.hand_off_id}
        </span>
        <PriorityPill priority={result.priority} />
      </div>
      <span className="text-sm">{reasonLabel(result.reason)}</span>
      {result.related_ids.length > 0 && <IdChips ids={result.related_ids} />}
      <span className="text-xs text-human">Enviado a una persona</span>
    </div>
  )
}
```

Replace `frontend/src/components/chat/ChatMessage.tsx` with:

```tsx
"use client"

import { useState } from "react"
import { Sparkles, ThumbsDown, ThumbsUp, User } from "lucide-react"
import { Message } from "./types"
import { FeedbackDialog } from "./FeedbackDialog"
import { getToolRenderer } from "@/hooks/useToolRenderer"
import { MarkdownRenderer } from "./MarkdownRenderer"

interface ChatMessageProps {
  message: Message
  sessionId: string
  onFeedbackSubmit: (feedbackType: "positive" | "negative", comment: string) => Promise<void>
  hideFeedback?: boolean
}

const TAG = "flex items-center gap-1 text-[11px] font-semibold uppercase tracking-[.06em]"
const BUBBLE = "rounded-2xl rounded-tl-sm px-3 py-2"

export function ChatMessage({
  message,
  sessionId: _sessionId,
  onFeedbackSubmit,
  hideFeedback = false,
}: ChatMessageProps) {
  const [isDialogOpen, setIsDialogOpen] = useState(false)
  const [selectedFeedbackType, setSelectedFeedbackType] = useState<"positive" | "negative">(
    "positive"
  )
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false)

  const formatTime = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    })
  }

  const handleFeedbackClick = (type: "positive" | "negative") => {
    setSelectedFeedbackType(type)
    setIsDialogOpen(true)
  }

  const handleFeedbackSubmit = async (comment: string) => {
    await onFeedbackSubmit(selectedFeedbackType, comment)
    setFeedbackSubmitted(true)
  }

  const renderAssistantContent = () => {
    // If segments exist, render them in order (interleaved text bubbles + tools)
    if (message.segments && message.segments.length > 0) {
      return message.segments.map((seg, i) => {
        if (seg.type === "text") {
          return (
            <div key={i} className={`${BUBBLE} bg-ai-bg`}>
              <MarkdownRenderer content={seg.content} />
            </div>
          )
        }
        const render = getToolRenderer(seg.toolCall.name)
        if (!render) return null
        return (
          <div key={seg.toolCall.toolUseId} className="my-1">
            {render({
              name: seg.toolCall.name,
              args: seg.toolCall.input,
              status: seg.toolCall.status,
              result: seg.toolCall.result,
            })}
          </div>
        )
      })
    }
    // Fallback: just render content as markdown
    return message.content ? (
      <div className={`${BUBBLE} bg-ai-bg`}>
        <MarkdownRenderer content={message.content} />
      </div>
    ) : null
  }

  const bubbleClass =
    message.role === "user"
      ? "rounded-2xl rounded-br-sm bg-brand-dark p-3 text-white whitespace-pre-wrap"
      : message.role === "human"
        ? `${BUBBLE} bg-human-bg whitespace-pre-wrap`
        : "flex flex-col gap-2 text-gray-800"

  return (
    <div className={`flex flex-col gap-1 ${message.role === "user" ? "items-end" : "items-start"}`}>
      {message.role === "assistant" && (
        <span className={`${TAG} text-ai`}>
          <Sparkles className="h-3 w-3" />
          Asistente IA
        </span>
      )}
      {message.role === "human" && (
        <span className={`${TAG} text-human`}>
          <User className="h-3 w-3" />
          Laura · Persona
        </span>
      )}
      <div className={`max-w-[85%] break-words ${bubbleClass}`}>
        {message.role === "assistant" ? renderAssistantContent() : message.content}
      </div>

      {/* Timestamp and Feedback buttons for assistant messages */}
      <div className="flex items-center gap-2 px-1">
        <div className="text-xs text-gray-500">{formatTime(message.timestamp)}</div>

        {/* Show feedback buttons only for assistant messages with content */}
        {!hideFeedback && message.role === "assistant" && message.content && (
          <div className="flex items-center gap-1 ml-2">
            <button
              onClick={() => handleFeedbackClick("positive")}
              disabled={feedbackSubmitted}
              className="p-1 text-gray-400 hover:text-green-600 hover:bg-green-50 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              aria-label="Positive feedback"
              title="Good response"
            >
              <ThumbsUp size={14} />
            </button>
            <button
              onClick={() => handleFeedbackClick("negative")}
              disabled={feedbackSubmitted}
              className="p-1 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              aria-label="Negative feedback"
              title="Bad response"
            >
              <ThumbsDown size={14} />
            </button>
            {feedbackSubmitted && (
              <span className="text-xs text-gray-500 ml-1">Thanks for your feedback!</span>
            )}
          </div>
        )}
      </div>

      {/* Feedback Dialog */}
      <FeedbackDialog
        isOpen={isDialogOpen}
        onClose={() => setIsDialogOpen(false)}
        onSubmit={handleFeedbackSubmit}
        feedbackType={selectedFeedbackType}
      />
    </div>
  )
}
```

Replace `frontend/src/components/chat/ChatMessages.tsx` with:

```tsx
import { Fragment, RefObject } from "react"
import { Message } from "./types"
import { ChatMessage } from "./ChatMessage"

interface ChatMessagesProps {
  messages: Message[]
  messagesEndRef?: RefObject<HTMLDivElement | null>
  sessionId: string
  onFeedbackSubmit: (
    messageContent: string,
    feedbackType: "positive" | "negative",
    comment: string
  ) => Promise<void>
  hideFeedback?: boolean
}

const time = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })

export function ChatMessages({
  messages,
  messagesEndRef,
  sessionId,
  onFeedbackSubmit,
  hideFeedback = false,
}: ChatMessagesProps) {
  // Laura's first message is the moment she joins the conversation
  const firstHuman = messages.findIndex(m => m.role === "human")

  return (
    <div
      className={`h-full p-4 space-y-4 w-full ${
        messages.length > 0 ? "overflow-y-auto" : "overflow-hidden"
      }`}
    >
      {messages.length === 0 ? (
        <div className="flex items-center justify-center h-full text-gray-400">
          Empieza una conversación
        </div>
      ) : (
        messages.map((message, index) => (
          <Fragment key={index}>
            {index === firstHuman && (
              <p className="text-center text-[11px] font-semibold uppercase tracking-[.06em] text-muted-foreground">
                Laura se unió a la conversación · {time(message.timestamp)}
              </p>
            )}
            <ChatMessage
              message={message}
              sessionId={sessionId}
              hideFeedback={hideFeedback}
              onFeedbackSubmit={async (feedbackType, comment) => {
                await onFeedbackSubmit(message.content, feedbackType, comment)
              }}
            />
          </Fragment>
        ))
      )}
      <div ref={messagesEndRef} />
    </div>
  )
}
```

- [ ] **Step 4: Run the checks**

Run: `cd frontend && npx vitest --run src/test/handoff-ticket.test.tsx && npm test && npx tsc --noEmit && npm run lint`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/chat/HandOffTicket.tsx frontend/src/components/chat/ChatMessage.tsx frontend/src/components/chat/ChatMessages.tsx frontend/src/test/handoff-ticket.test.tsx
git commit -m "feat(frontend): hand-off ticket and tier-colored messages"
```

---

### Task 7: Agent desk and the split in ChatInterface

**Files:**
- Create: `frontend/src/components/chat/AgentDesk.tsx`
- Modify: `frontend/src/components/chat/ChatInterface.tsx` (imports, state, renderer registration, `sendMessage`, `finally`, everything from `startNewChat` to the end)
- Test: `frontend/src/test/handoff-flow.test.tsx`

**Interfaces:**
- Consumes: everything from Tasks 4–6.
- Produces: `AgentDesk(props: { handOff: HandOff; phase: Phase; messages: Message[]; customerName: string; sessionId: string; onSend: (text: string) => void })`, rendered as `<section aria-label="Escritorio del agente">`. Laura's textarea has `aria-label="Mensaje de Laura"`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/handoff-flow.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import ChatInterface from "@/components/chat/ChatInterface"
import { GlobalContextProvider } from "@/app/context/GlobalContext"

const { invoke, created } = vi.hoisted(() => ({ invoke: vi.fn(), created: vi.fn() }))

vi.mock("@/lib/agentcore-client", () => ({
  AgentCoreClient: class {
    invoke = invoke
    constructor(config: unknown) {
      created(config)
    }
  },
}))
vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: "token", id_token: "id", profile: { name: "Carlos Rendón" } } }),
}))
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ isAuthenticated: false, signOut: vi.fn() }) }))

const HAND_OFF = {
  hand_off_id: "HO-7Q3KX2MA",
  status: "queued",
  priority: "high",
  reason: "FRAUD_CONFIRMED",
  customer_id: "CLI-F2DZJYU0POJ9",
  summary: "No reconoce 2 cargos en Miami.",
  related_ids: ["TX-88", "TX-89"],
}
const GOODBYE = "Carlos, una persona del equipo de fraudes sigue contigo desde aquí."
const DESK = { name: "Escritorio del agente" }

type OnEvent = (event: Record<string, unknown>) => void

/** The agent's next turn: a line, the hand-off tool returning `result`, then the goodbye. */
function agentTurn(result: string) {
  invoke.mockImplementationOnce(async (_message: string, _session: string, _token: string, onEvent: OnEvent) => {
    onEvent({ type: "text", content: "Te paso con una persona." })
    onEvent({ type: "tool_use_start", toolUseId: "t1", name: "human-agent-hand-off-target___human_agent_hand_off" })
    onEvent({ type: "tool_result", toolUseId: "t1", result })
    onEvent({ type: "text", content: GOODBYE })
  })
}

async function startChat() {
  render(
    <GlobalContextProvider>
      <ChatInterface />
    </GlobalContextProvider>
  )
  await waitFor(() => expect(created).toHaveBeenCalled())
}

/** Waits until the turn has finished streaming (the send button stops saying "Pensando…"). */
const turnFinished = () => waitFor(() => expect(screen.queryByText("Pensando…")).toBeNull())
const pause = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

beforeEach(() => {
  invoke.mockReset()
  created.mockReset()
  Element.prototype.scrollIntoView = vi.fn()
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => ({ agentRuntimeArn: "arn:aws:bedrock-agentcore:us-east-1:1:runtime/x" }) }))
  )
})

describe("hand-off flow", () => {
  it("opens the desk after the goodbye, mutes the bot and lets Laura join", async () => {
    const user = userEvent.setup()
    agentTurn(JSON.stringify(HAND_OFF))
    await startChat()

    await user.type(screen.getByPlaceholderText("Escribe un mensaje…"), "quiero hablar con una persona{Enter}")

    const desk = await screen.findByRole("region", DESK, { timeout: 2000 })
    expect(within(desk).getByText("Carlos Rendón")).toBeInTheDocument()
    expect(within(desk).getByText(HAND_OFF.summary)).toBeInTheDocument()
    expect(within(desk).getByText(GOODBYE, { selector: "blockquote" })).toBeInTheDocument()
    expect(within(desk).getByText("Conectando…")).toBeInTheDocument()

    // the customer keeps typing: the message reaches the desk, never the bot
    await user.type(screen.getByPlaceholderText("Escribe un mensaje…"), "¿sigues ahí?{Enter}")
    expect(invoke).toHaveBeenCalledTimes(1)
    expect(screen.getAllByText("¿sigues ahí?")).toHaveLength(2)

    // Laura answers: both views show that she joined
    await user.type(within(desk).getByLabelText("Mensaje de Laura"), "Hola Carlos, soy Laura.")
    await user.click(within(desk).getByRole("button", { name: /Enviar/ }))
    expect(screen.getAllByText(/Laura se unió a la conversación/)).toHaveLength(2)
    expect(within(desk).getByText("En conversación")).toBeInTheDocument()
  })

  it("an error result never opens the desk", async () => {
    const user = userEvent.setup()
    agentTurn(JSON.stringify({ error: "The hand-off couldn't be sent." }))
    await startChat()

    await user.type(screen.getByPlaceholderText("Escribe un mensaje…"), "quiero hablar con una persona{Enter}")
    await turnFinished()
    await pause(900)

    expect(screen.queryByRole("region", DESK)).toBeNull()
  })

  it("starting a new chat during the pause cancels the split", async () => {
    const user = userEvent.setup()
    agentTurn(JSON.stringify(HAND_OFF))
    await startChat()

    await user.type(screen.getByPlaceholderText("Escribe un mensaje…"), "quiero hablar con una persona{Enter}")
    await turnFinished()
    await user.click(screen.getByRole("button", { name: /Nueva conversación/ }))
    await pause(900)

    expect(screen.queryByRole("region", DESK)).toBeNull()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest --run src/test/handoff-flow.test.tsx`
Expected: FAIL. The first test times out on `findByRole("region", { name: "Escritorio del agente" })`; the other two pass for now.

- [ ] **Step 3: Create `frontend/src/components/chat/AgentDesk.tsx`**

```tsx
import { useState, type FormEvent } from "react"
import { Check, Send, Ticket, User } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { type HandOff, type Phase, queueFor, reasonLabel, suggestedReplies } from "@/lib/handoff"
import { ChatMessages } from "./ChatMessages"
import { HAND_OFF_TRANSITION, IdChips, PriorityPill } from "./HandOffTicket"
import type { Message } from "./types"

interface AgentDeskProps {
  handOff: HandOff
  phase: Phase
  messages: Message[]
  customerName: string
  sessionId: string
  onSend: (text: string) => void
}

const LABEL = "text-[11px] font-semibold uppercase tracking-[.08em] text-muted-foreground"
const time = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })

/** The human agent's side of the split: the case, the customer's live thread and a composer. */
export function AgentDesk({ handOff, phase, messages, customerName, sessionId, onSend }: AgentDeskProps) {
  const [draft, setDraft] = useState("")
  const joined = phase === "joined"
  const sent = new Set(messages.filter(m => m.role === "human").map(m => m.content))

  const send = (e: FormEvent) => {
    e.preventDefault()
    if (!draft.trim()) return
    onSend(draft.trim())
    setDraft("")
  }

  return (
    <section aria-label="Escritorio del agente" className="flex min-h-0 flex-col gap-2">
      <h2 className={LABEL}>Escritorio del agente · Laura</h2>
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border bg-white">
        <header className="flex items-center justify-between gap-3 border-b bg-page px-4 py-3">
          <div className="flex items-center gap-3">
            <span className="grid h-9 w-9 place-items-center rounded-full bg-human text-white">
              <User className="h-4 w-4" />
            </span>
            <div className="leading-tight">
              <p className="font-semibold">Laura Restrepo</p>
              <p className="text-xs text-muted-foreground">Fraudes y servicio · Mesa de personas</p>
            </div>
          </div>
          <span
            className={`rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[.06em] ${
              joined ? "border-ai text-ai" : "border-human text-human"
            }`}
          >
            {joined ? "En conversación" : "Conectando…"}
          </span>
        </header>

        <div className="grid min-h-0 flex-1 gap-4 overflow-y-auto p-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
          <article
            style={HAND_OFF_TRANSITION}
            className="flex flex-col gap-3 self-start rounded-xl border border-human bg-human-bg/40 p-4"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2 font-mono text-sm font-semibold text-human">
                <Ticket className="h-4 w-4" />
                {handOff.hand_off_id}
                {!joined && (
                  <span className="rounded bg-human px-1.5 py-0.5 font-sans text-[10px] font-bold uppercase text-white">
                    Nuevo
                  </span>
                )}
              </span>
              <PriorityPill priority={handOff.priority} />
            </div>
            <div>
              <h3 className="text-xl font-semibold">{customerName || handOff.customer_id}</h3>
              <p className="text-sm text-muted-foreground">
                Cola: {queueFor(handOff.reason)} · {reasonLabel(handOff.reason)}
              </p>
            </div>
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <dt className={LABEL}>Cliente</dt>
                <dd className="font-mono">{handOff.customer_id}</dd>
              </div>
              <div>
                <dt className={LABEL}>En cola desde</dt>
                <dd className="font-mono">{time(handOff.at)}</dd>
              </div>
            </dl>
            <div>
              <h4 className={LABEL}>Resumen del asistente</h4>
              <p className="mt-1 text-[15px] leading-relaxed">{handOff.summary}</p>
            </div>
            {handOff.related_ids.length > 0 && (
              <div className="flex flex-col gap-1.5">
                <h4 className={LABEL}>IDs relacionados</h4>
                <IdChips ids={handOff.related_ids} />
              </div>
            )}
            <div>
              <h4 className={LABEL}>Lo que ya se le dijo</h4>
              <blockquote className="mt-1 border-l-2 border-human pl-3 text-sm text-muted-foreground">
                {handOff.goodbye}
              </blockquote>
            </div>
          </article>

          <div className="flex min-h-0 flex-col gap-3">
            <div className="flex items-center justify-between">
              <h4 className={LABEL}>Conversación del cliente</h4>
              <span className="text-xs text-muted-foreground">Reflejada en vivo</span>
            </div>
            <div className="min-h-[240px] flex-1 overflow-hidden rounded-xl border bg-page/60">
              <ChatMessages messages={messages} sessionId={sessionId} onFeedbackSubmit={async () => {}} hideFeedback />
            </div>

            <h4 className={LABEL}>Respuestas sugeridas</h4>
            {suggestedReplies(handOff, customerName).map(reply =>
              sent.has(reply) ? (
                <p key={reply} className="flex items-start gap-2 rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
                  <Check className="mt-0.5 h-4 w-4 flex-none text-ai" />
                  {reply}
                </p>
              ) : (
                <div key={reply} className="flex items-start justify-between gap-3 rounded-lg border border-dashed border-human/60 p-3 text-sm">
                  <span>{reply}</span>
                  <Button type="button" size="sm" variant="outline" className="border-human text-human" onClick={() => setDraft(reply)}>
                    Usar
                  </Button>
                </div>
              )
            )}

            <form onSubmit={send} className="flex flex-col gap-1">
              <div className="flex items-end gap-2 rounded-xl border border-human/70 bg-white p-2 focus-within:ring-2 focus-within:ring-human/40">
                <Textarea
                  value={draft}
                  onChange={e => setDraft(e.target.value)}
                  placeholder="Escribe como Laura…"
                  aria-label="Mensaje de Laura"
                  rows={2}
                  className="min-h-[44px] resize-none border-0 shadow-none focus-visible:ring-0"
                  autoFocus
                />
                <Button type="submit" disabled={!draft.trim()} className="bg-human hover:bg-human/90">
                  <Send className="mr-1 h-4 w-4" />
                  Enviar
                </Button>
              </div>
              {!joined && <p className="text-xs text-muted-foreground">Tu primer mensaje le avisa al cliente que te uniste.</p>}
            </form>
          </div>
        </div>
      </div>
    </section>
  )
}
```

- [ ] **Step 4: Edit `frontend/src/components/chat/ChatInterface.tsx`**

4a. Imports. Replace:

```tsx
import { useEffect, useRef, useState } from "react"
import { ChatHeader } from "./ChatHeader"
```

with:

```tsx
import { useEffect, useRef, useState } from "react"
import { flushSync } from "react-dom"
import { AgentDesk } from "./AgentDesk"
import { ChatHeader } from "./ChatHeader"
```

and replace:

```tsx
import { useDefaultTool } from "@/hooks/useToolRenderer"
import { ToolCallDisplay } from "./ToolCallDisplay"
```

with:

```tsx
import { useDefaultTool, useToolRenderer } from "@/hooks/useToolRenderer"
import { findHandOff, HAND_OFF_DELAY_MS, HAND_OFF_TOOL, phaseOf, queueFor, type HandOff } from "@/lib/handoff"
import { HandOffTicket } from "./HandOffTicket"
import { ToolCallDisplay } from "./ToolCallDisplay"
```

4b. State. Replace:

```tsx
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID())
```

with:

```tsx
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID())
  const [handOff, setHandOff] = useState<HandOff | null>(null)
  // the pending split, cancelled by "Nueva conversación"
  const handOffTimer = useRef<number | undefined>(undefined)
  const phase = phaseOf(handOff, messages)
```

4c. Renderer. Directly after the closing `))` of the existing `useDefaultTool(({ name, args, status, result }) => ( … ))` call, add:

```tsx

  // The hand-off renders as a ticket. It carries the shared view-transition name until the
  // split; then the desk's case card takes the name over and the ticket morphs into it.
  useToolRenderer(HAND_OFF_TOOL, props => <HandOffTicket {...props} tagged={phase === "ai"} />)
```

4d. Mute the bot after the hand-off. In `sendMessage`, replace:

```tsx
    setInput("")
    setIsLoading(true)
```

with:

```tsx
    setInput("")
    // ponytail: after the hand-off a person owns the chat, so the bot is never called again
    if (handOff) return
    setIsLoading(true)
```

4e. Move the stream buffers out of the `try`. Replace:

```tsx
    try {
      // Get auth token from react-oidc-context
      const accessToken = auth.user?.access_token

      if (!accessToken) {
        throw new Error("Authentication required. Please log in again.")
      }

      const segments: MessageSegment[] = []
      const toolCallMap = new Map<string, ToolCall>()
```

with:

```tsx
    // Outside the try so the finally block can look for a hand-off in what streamed
    const segments: MessageSegment[] = []
    const toolCallMap = new Map<string, ToolCall>()

    try {
      // Get auth token from react-oidc-context
      const accessToken = auth.user?.access_token

      if (!accessToken) {
        throw new Error("Authentication required. Please log in again.")
      }
```

4f. Trigger. Replace:

```tsx
    } finally {
      setIsLoading(false)
    }
  }
```

with:

```tsx
    } finally {
      // The turn has finished streaming, so the goodbye is on screen: split after a pause
      const found = findHandOff([{ ...assistantResponse, segments }])
      if (found) {
        handOffTimer.current = window.setTimeout(() => openHandOff(found), HAND_OFF_DELAY_MS)
      }
      setIsLoading(false)
    }
  }

  // Animate into the split with the View Transitions API where the browser has it
  const openHandOff = (found: HandOff) => {
    const apply = () => flushSync(() => setHandOff(current => current ?? found))
    if ("startViewTransition" in document) document.startViewTransition(apply)
    else apply()
  }
```

4g. Layout. Replace everything from the line `  const startNewChat = () => {` to the end of the file with:

```tsx
  const startNewChat = () => {
    clearTimeout(handOffTimer.current)
    setHandOff(null)
    setMessages([])
    setInput("")
    setError(null)
    setSessionId(crypto.randomUUID())
  }

  // Laura's messages stay in the browser: they never reach AgentCore
  const sendAsAgent = (content: string) =>
    setMessages(prev => [...prev, { role: "human", content, timestamp: new Date().toISOString() }])

  // Check if this is the initial state (no messages)
  const isInitialState = messages.length === 0

  // Check if there are any assistant messages
  const hasAssistantMessages = messages.some(message => message.role === "assistant")

  // Beat 1: the hand-off is done and the split is about to happen
  const handOffPending = !handOff && findHandOff(messages) !== null

  const profile = auth.user?.profile
  const customerName = String(profile?.name ?? profile?.given_name ?? "")

  return (
    <div className="flex h-screen w-full flex-col bg-page">
      {/* Fixed header */}
      <div className="flex-none">
        <ChatHeader onNewChat={startNewChat} canStartNewChat={hasAssistantMessages} phase={phase} />
        {error && (
          <div className="bg-red-50 border-l-4 border-red-500 p-4 mx-4 mt-2">
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}
      </div>

      {handOff ? (
        // Hand-off split: the customer's phone and the human agent's desk
        <div className="grid min-h-0 flex-1 gap-4 overflow-y-auto p-4 min-[1100px]:grid-cols-[400px_minmax(0,1fr)] min-[1100px]:overflow-hidden">
          <section aria-label="Cliente" className="flex min-h-0 flex-col gap-2">
            <h2 className="text-[11px] font-semibold uppercase tracking-[.08em] text-muted-foreground">
              Cliente · App
            </h2>
            <div className="flex min-h-[560px] flex-1 flex-col overflow-hidden rounded-[28px] border bg-white shadow-[0_18px_40px_-28px_hsl(200_40%_10%/.45)]">
              <div className="flex items-center justify-between gap-2 border-b px-4 py-3">
                <b>LATAM Bank</b>
                <span className="rounded-full bg-human-bg px-2.5 py-0.5 text-xs font-medium text-human">
                  {phase === "joined" ? "Laura · Persona" : `En cola · ${queueFor(handOff.reason)}`}
                </span>
              </div>
              <div className="min-h-0 flex-1">
                <ChatMessages
                  messages={messages}
                  messagesEndRef={messagesEndRef}
                  sessionId={sessionId}
                  onFeedbackSubmit={handleFeedbackSubmit}
                />
              </div>
              <ChatInput input={input} setInput={setInput} handleSubmit={handleSubmit} isLoading={isLoading} />
            </div>
          </section>
          <AgentDesk
            handOff={handOff}
            phase={phase}
            messages={messages}
            customerName={customerName}
            sessionId={sessionId}
            onSend={sendAsAgent}
          />
        </div>
      ) : isInitialState ? (
        // Initial state - input in the middle
        <>
          <div className="grow" />

          <div className="text-center mb-6">
            <h2 className="text-2xl font-bold text-gray-800">Hola, soy LedgerLens</h2>
            <p className="text-gray-600 mt-2">
              Pregúntame por tus tarjetas, tus compras o un cargo que no reconozcas.
            </p>
          </div>

          <div className="px-4 mb-16 max-w-4xl mx-auto w-full">
            <ChatInput
              input={input}
              setInput={setInput}
              handleSubmit={handleSubmit}
              isLoading={isLoading}
            />
          </div>

          <div className="grow" />
        </>
      ) : (
        // Chat in progress - normal layout
        <>
          <div className="grow overflow-hidden">
            <div className="max-w-4xl mx-auto w-full h-full">
              <ChatMessages
                messages={messages}
                messagesEndRef={messagesEndRef}
                sessionId={sessionId}
                onFeedbackSubmit={handleFeedbackSubmit}
              />
            </div>
          </div>

          <div className="flex-none">
            <div className="max-w-4xl mx-auto w-full">
              <ChatInput
                input={input}
                setInput={setInput}
                handleSubmit={handleSubmit}
                isLoading={isLoading}
                placeholder={handOffPending ? "Conectando con una persona…" : undefined}
              />
            </div>
          </div>
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npx vitest --run src/test/handoff-flow.test.tsx`
Expected: 3 PASS.

Then run everything: `cd frontend && npm test && npx tsc --noEmit && npm run lint && npm run build`
Expected: all PASS; build succeeds.

- [ ] **Step 6: Check it in a browser (no backend needed)**

Run `cd frontend && npm run dev`. Without a deployed agent you can't stream a real hand-off, so check only the layout. Temporarily add `useEffect(() => { setHandOff({ hand_off_id: "HO-7Q3KX2MA", status: "queued", priority: "high", reason: "FRAUD_CONFIRMED", customer_id: "CLI-F2DZJYU0POJ9", summary: "No reconoce 2 cargos en Miami.", related_ids: ["TX-88", "TX-89"], goodbye: "Una persona sigue contigo aquí.", at: new Date().toISOString() }) }, [])` inside `ChatInterface`. Compare the page at 1600×960 with Beat 2 of spec §6, send a message as Laura and compare it with Beat 3, then **remove the temporary `useEffect`** and confirm `git diff` doesn't contain it.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/chat/AgentDesk.tsx frontend/src/components/chat/ChatInterface.tsx frontend/src/test/handoff-flow.test.tsx
git commit -m "feat(frontend): split into the customer phone and the human agent desk after the hand-off"
```

---

### Task 8: Point the docs at the new design, verify everything, demo check

**Files:**
- Modify: `docs/LEDGERLENS_PRODUCT_DESIGN.md`, `docs/superpowers/specs/2026-10-03-write-tools-design.md`

**Interfaces:**
- Consumes: everything above.
- Produces: docs that no longer describe an SNS hand-off.

- [ ] **Step 1: Update `docs/LEDGERLENS_PRODUCT_DESIGN.md`**

Make these nine replacements. Each "find" text occurs exactly once in the file.

1. Find `└─ human_agent_hand_off ──> SNS (human agent queue / alert)`
   Replace with `└─ human_agent_hand_off ──> agent desk in the frontend (no AWS service)`
2. Find:
   ```
   | SNS | Human hand-off alerts | **To build** |
   ```
   Replace with:
   ```
   | Frontend agent desk | Human hand-off (split screen) | **Built** (hand-off spec) |
   ```
3. Find `SNS, call_center_interactions` (row 9 of the tools table)
   Replace with `— (the frontend opens the agent desk)`
4. Find:
   ```
   Spec: [2026-10-03-write-tools-design.md](superpowers/specs/2026-10-03-write-tools-design.md) §5. SNS only; the Lambda runs outside the VPC.
   ```
   Replace with:
   ```
   Spec: [2026-10-03-human-hand-off-frontend-design.md](superpowers/specs/2026-10-03-human-hand-off-frontend-design.md), which replaces the SNS design of the write-tools spec §5. The Lambda validates the hand-off and returns it; it runs outside the VPC and calls no AWS service.
   ```
5. Find:
   ```
   - Publishes the payload to the SNS topic `ledgerlens-human-handoff`. Subscribers can be email or SMS for the demo, or a contact-center queue later.
   ```
   Replace with:
   ```
   - Returns the validated hand-off with a content-derived `HO-` id. The frontend detects the result, waits for the goodbye and opens the human agent's desk.
   ```
6. Find:
   ```
   - [x] Create the SNS topic `ledgerlens-human-handoff` (data stack).
   ```
   Replace with:
   ```
   - [x] ~~Create the SNS topic `ledgerlens-human-handoff`~~ Removed: the frontend opens the agent desk (hand-off spec).
   ```
7. Find `only the hand-off role may publish to SNS.`
   Replace with `the hand-off Lambda has only its log permissions.`
8. Find:
   ```
   `human_agent_hand_off` + SNS
   ```
   Replace with:
   ```
   `human_agent_hand_off` + agent desk
   ```
9. Find:
   ```
   | Q5 | Who receives the SNS hand-off: email for the demo, or a contact-center queue? | P3 |
   ```
   Replace with:
   ```
   | Q5 | ~~Who receives the SNS hand-off?~~ Answered: the frontend's agent desk (hand-off spec). | P3 |
   ```

Then `grep -n "SNS" docs/LEDGERLENS_PRODUCT_DESIGN.md` must print only the three lines written by replacements 4, 6 and 9.

- [ ] **Step 2: Update `docs/superpowers/specs/2026-10-03-write-tools-design.md`**

Directly under the heading `## 5. \`human_agent_hand_off\``, add:

```markdown
> **Superseded:** the SNS publisher, topic and settings in this section were removed by [2026-10-03-human-hand-off-frontend-design.md](2026-10-03-human-hand-off-frontend-design.md). The input schema and validation still hold.
```

- [ ] **Step 3: Run the full verification**

```bash
pytest tests/unit -q
ruff format --check && ruff check
cd infra-cdk && npx jest && npx tsc --noEmit && cd ..
cd frontend && npm test && npm run lint && npm run build && cd ..
grep -rn -i "HANDOFF_TOPIC\|ledgerlens-human-handoff\|aws-sns" infra-cdk/lib gateway frontend/src
```

Expected: every suite PASSES, the build succeeds, and the final `grep` prints nothing.

- [ ] **Step 4: Commit**

```bash
git add docs/LEDGERLENS_PRODUCT_DESIGN.md docs/superpowers/specs/2026-10-03-write-tools-design.md
git commit -m "docs: the hand-off opens the agent desk instead of publishing to SNS"
```

- [ ] **Step 5: Demo check (only after the branch's code review has finished)**

Deploy the data stack, then the main stack (`cd infra-cdk && npx cdk deploy --all`). Open the deployed frontend, sign in as a linked demo customer (chosen from `personas.json`), and type **"quiero hablar con una persona"**. Expected: the ticket appears, the goodbye streams, and after about 0.6 s the split opens (Beat 2). Send a suggested reply as Laura (Beat 3). Record it with the Chrome GIF recorder as `handoff_demo.gif` for the judges' deck.
