# transaction_fraud_detection Lambda Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- Build the `transaction_fraud_detection` Gateway tool Lambda as a self-contained folder, `gateway/tools/transaction_fraud_detection/transaction_fraud_detection_lambda/`.
- It tells the agent whether a credit-card charge is fraud. It reads the stored `fraud_score` and maps it to `fraud` (above 50), `review` (above 30, up to 50) or `no_fraud`.
- It has two modes. **One charge** (`transaction_id`) returns one assessment. **Card sweep** (`card_last4`) checks the card's last 30 days and returns only the flagged charges plus `checked`.
- Add it to the CDK data stack, deploy it, and run the acceptance checks against P07.

**Architecture:**
- Task 1 copies the shared layers from `gateway/tools/get_session_context/` file by file, changing only the package name.
- The domain is this tool's own:
  - `fraud_bands.py`: the bands, the verdict and basis enums, `NEXT_STEPS`, `assess()`.
  - `fraud_check_request.py`: `FraudCheckRequest.from_raw()`, validated before the database is touched.
  - `fraud_assessment.py`: the `FraudAssessment` and `CardSweep` entities. Neither has a score field.
- The use case runs `fraud_transaction` (one charge), or `fraud_card_exists` then `fraud_card_sweep` (sweep), on the single autocommit connection. Every failure becomes one fixed domain message.
- The sweep SQL always returns at least one row. When nothing is flagged, that row is **count-only**: its transaction columns are NULL and `checked` is the real count.
- The score never leaves the Lambda. The presenter, the handler log line and every error message are free of it, and tests pin this.

**Tech Stack:** Python 3.13 (project `.venv`), pytest, ruff, psycopg 3, boto3, TypeScript CDK with jest, Git Bash on Windows.

**Spec:** `docs/superpowers/specs/2026-10-03-transaction-fraud-detection-lambda-design.md`. Layout rules: `docs/superpowers/specs/2026-10-01-self-contained-tool-folders-design.md`.

## Global Constraints

- Python: `PY=.venv/Scripts/python`. Run every command from the repo root `C:\GITHUB REPOS\ledgerlens-bank-assistant` in Git Bash. Add `</dev/null` to `$PY` commands so nothing waits on stdin. Never use Anaconda.
- **Do not commit during execution.** The user commits once, on their command, at the end. Never run `git commit` or `git add`.
- Never stage `infra-cdk/config.yaml`, `frontend/public/aws-exports.json` or `frontend/.env`.
- No push and no merge.
- **CDK and deploy:**
  - The CDK edit in Task 10 is in scope. The spec (§7) puts it there, and approving the spec approved it.
  - The deploy and the acceptance run (Task 12) touch the real AWS account. **Stop before Task 12 and wait for the user's explicit go-ahead.**
- **Self-contained:**
  - Nothing in `transaction_fraud_detection` imports from another tool.
  - No other tool's files change.
  - Code is copied, never shared.
- **Copy rule:**
  - Copy from `gateway/tools/get_session_context/`.
  - Copied files only get `get_session_context` → `transaction_fraud_detection`. Task 8 also renames `GetSessionContextUseCase` → `TransactionFraudDetectionUseCase`.
  - Never copy `__pycache__`.
- Names (spec §2):
  - asset folder: `gateway/tools/transaction_fraud_detection/`
  - package: `transaction_fraud_detection_lambda`
  - handler string: `transaction_fraud_detection_lambda/delivery/handler.handler`
  - tool name: `transaction_fraud_detection`
  - Lambda: `ledgerlens-transaction-fraud-detection`
  - test package: `tests/unit/transaction_fraud_detection/`
- Query (file) names: `fraud_transaction`, `fraud_card_exists`, `fraud_card_sweep`.
- Keep names specific: `database_repository`, `query_provider`.
- **Exact values from the spec:**
  - `FRAUD_ABOVE = Decimal("50")`, `REVIEW_ABOVE = Decimal("30")`. Comparisons are strict: 50.00 is `review`, 30.00 is `no_fraud`.
  - `SWEEP_DAYS = 30`. `max_rows` defaults to 25, and the sweep sends `limit = max_rows + 1`.
  - Fixed messages (spec §8.2) and validation reasons (spec §3.2): copy them verbatim from Tasks 2 and 4.
  - The handler log line is `"%s mode=%s verdict_counts=%s"`. `verdict_counts` is a `dict` sorted by key, for example `{'fraud': 1}`.
  - The unexpected-error message is `Unexpected internal error running the fraud check. Offer a hand-off to a human agent.`
- **The score never leaves the Lambda.** No output key is named `fraud_score`, `score` or `is_fraud`. No log line or error message contains a score.
- **No SQL file contains the text `is_fraud`, not even in a comment** (DEC-10). A contract test enforces this.
- `card_last4` uses `re.fullmatch(r"[0-9]{4}", value)`. Both `str.isdigit()` and `\d` accept `"٤٤٩٧"`, which must be rejected.
- Keep the `TODO(ledgerlens): Rn` tags exactly as the copied files have them.
- Lint: `$PY -m ruff format --check <paths>` and `$PY -m ruff check <paths>`. Fix formatting with `$PY -m ruff format <paths>`.
- **The suite command.** The ignores and the `-k` stay while `duckdb` and `aurora_dsql_psycopg` are missing from `.venv`:

  ```bash
  $PY -m pytest tests/unit -q -p no:cacheprovider \
    --ignore=tests/unit/test_data_load_cli.py --ignore=tests/unit/test_data_load_curate.py \
    --ignore=tests/unit/test_data_load_curate_rules.py --ignore=tests/unit/test_data_load_curate_select.py \
    --ignore=tests/unit/test_data_load_ddl.py --ignore=tests/unit/test_data_load_repair.py \
    --ignore=tests/unit/test_data_load_transform.py --ignore=tests/unit/test_dsql_read_check.py \
    -k "not test_dsql_driver_imports" </dev/null 2>&1 | tail -1
  ```

  Baseline before Task 1: `876 passed, 1 deselected`.
- **Plan rulings on the spec:**
  - The spec's sweep SQL was fixed before this plan: `totals` plus a `LEFT JOIN flagged ... ON TRUE`. Before the fix, a card with 3 clean charges reported `checked 0`. The spec's §4, §6.3 and §11 describe the count-only row.
  - §4 lists `_optional_int` among the copied helpers. Nothing maps an optional int, so it isn't copied. `checked` gets `_required_int`, because §4 says a `checked` that isn't an int is an integrity error.
  - The handler keeps the copied order: the `USE_CASE is None or CLOCK is None` guard runs first, then `FraudCheckRequest.from_raw(event)`. Both are inside the `try`.

## Review Focus

1. **A card with charges, none flagged.** Expected: `checked` is the real count (for example 3), `flagged` is `[]` and `truncated` is false. It is never `checked 0`. *Pinned by Task 5, `test_a_count_only_row_gives_checked_and_no_items`, and Task 6, `test_sweep_keeps_the_count_when_nothing_is_flagged`.*
2. **Scores on a band edge, or in an odd type from the driver.** Expected: 50.00 is `review`, 50.01 is `fraud`, 30.00 is `no_fraud` (scored), 30.01 is `review`, and an `int` 62 is `fraud`. A string, float or bool score is an integrity error, never a guessed verdict. *Pinned by Task 3, `test_assess_bands_each_score`, and Task 5, `test_scores_are_banded` and `test_a_bad_row_raises_data_integrity`.*
3. **`card_last4` typed loosely.** Expected: `" 4497 "` is accepted, while `"449"`, `"44a7"`, `"٤٤٩٧"` and the number `4497` are rejected with the 4-digits message. A blank value counts as missing. *Pinned by Task 4, `test_card_last4_is_stripped` and `test_bad_card_last4_is_rejected`.*
4. **The score leaking.** Expected: the score appears in no output key or value and no log line. *Pinned by Task 7, `test_no_score_key_anywhere`, and Task 9, `test_success_log_names_the_verdicts_but_no_customer_data_or_score`.*
5. **Another customer's charge, or a debit-card charge.** Expected: "not found", never the other customer's data. *Pinned by Task 6, `test_each_query_checks_the_customer_and_credit_cards`, and Task 5, `test_no_transaction_row_raises_not_found`.*

---

## File map

| Path | Task | Kind |
|---|---|---|
| `gateway/tools/transaction_fraud_detection/requirements.txt` | 1 | copied |
| `transaction_fraud_detection_lambda/**/__init__.py` (14 copied, plus `domain/value_objects/__init__.py`) | 1 | copied or new |
| `transaction_fraud_detection_lambda/application/ports/{database_repository,query_provider,errors}.py` | 1 | copied |
| `transaction_fraud_detection_lambda/infrastructure/queries/file_query_provider.py` | 1 | copied |
| `transaction_fraud_detection_lambda/infrastructure/repositories/dsql_repository.py` | 1 | copied |
| `transaction_fraud_detection_lambda/utils/connectors/{base,dsql}.py` | 1 | copied |
| `transaction_fraud_detection_lambda/delivery/settings.py` | 1 | copied |
| `tests/unit/transaction_fraud_detection/{__init__,conftest,fakes}.py` | 1 | new or adapted |
| `tests/unit/transaction_fraud_detection/test_{settings,file_query_provider,dsql_repository,psycopg_connector,dsql_connector}.py` | 1 | copied |
| `transaction_fraud_detection_lambda/domain/errors.py` + `tests/.../test_errors.py` | 2 | new (base classes copied) |
| `transaction_fraud_detection_lambda/domain/value_objects/fraud_bands.py` + `tests/.../test_fraud_bands.py` | 3 | new |
| `transaction_fraud_detection_lambda/domain/value_objects/fraud_check_request.py` + `tests/.../test_fraud_check_request.py` | 4 | new |
| `transaction_fraud_detection_lambda/domain/entities/fraud_assessment.py` | 5 | new |
| `transaction_fraud_detection_lambda/application/use_cases/transaction_fraud_detection.py` + `tests/.../test_transaction_fraud_detection_use_case.py` | 5 | new |
| `transaction_fraud_detection_lambda/queries/postgresql/fraud_{transaction,card_exists,card_sweep}.sql` | 6 | new |
| `gateway/tools/transaction_fraud_detection/tool_spec.json` + `tests/.../test_query_contracts.py` | 6 | new |
| `transaction_fraud_detection_lambda/delivery/presenters/fraud_assessment.py` + `tests/.../test_fraud_assessment_presenter.py` | 7 | new |
| `transaction_fraud_detection_lambda/delivery/dependencies/dependencies_builder.py` + `tests/.../test_delivery_wiring.py` | 8 | copied, then renamed |
| `transaction_fraud_detection_lambda/delivery/handler.py` + `tests/.../test_transaction_fraud_detection_handler.py` | 9 | new (shape copied) |
| `infra-cdk/lib/data-construct.ts`, `infra-cdk/test/data-construct.test.ts` | 10 | modified |
| `docs/LEDGERLENS_PRODUCT_DESIGN.md` | 11 | modified (§7.6, CRLF) |

All `transaction_fraud_detection_lambda/...` paths are under `gateway/tools/transaction_fraud_detection/`.

---

### Task 1: Copy the shared layers into `transaction_fraud_detection`

**Files:**
- Create (copied): `gateway/tools/transaction_fraud_detection/requirements.txt`
- Create (copied): the 14 `__init__.py` files under `gateway/tools/transaction_fraud_detection/transaction_fraud_detection_lambda/`
- Create: `transaction_fraud_detection_lambda/domain/value_objects/__init__.py`
- Create (copied): `application/ports/{database_repository,query_provider,errors}.py`, `infrastructure/queries/file_query_provider.py`, `infrastructure/repositories/dsql_repository.py`, `utils/connectors/{base,dsql}.py`, `delivery/settings.py`
- Create: `tests/unit/transaction_fraud_detection/__init__.py` (empty), `conftest.py`, `fakes.py`
- Create (copied): `tests/unit/transaction_fraud_detection/test_{settings,file_query_provider,dsql_repository,psycopg_connector,dsql_connector}.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces (all under `transaction_fraud_detection_lambda`):
  - `application.ports.database_repository.DatabaseRepository` with `execute_query(query: str, params: Mapping[str, object]) -> list[dict[str, Any]]`
  - `application.ports.query_provider.QueryProvider` with `get(name: str) -> str`
  - `application.ports.errors`: `DataAccessError`, `DataSourceConnectionError`, `QueryExecutionError`, `QueryLimitExceededError`, `QueryNotFoundError` (each takes one message string)
  - `infrastructure.queries.file_query_provider.FileQueryProvider(directory: Path)`
  - `infrastructure.repositories.dsql_repository.DsqlRepository(connector)`
  - `utils.connectors.base.PsycopgConnector`, `utils.connectors.dsql.DsqlConnector`
  - `delivery.settings`: `ConfigurationError`, `DatabaseEngine`, `DatabaseSettings`, `DsqlSettings`, `ClockSettings` (`.now() -> datetime`)
- Produces in `tests/unit/transaction_fraud_detection/fakes.py`:
  - `CUSTOMER_ID = "CLI-EX6BOAOEFZHQ"`, `TRANSACTION_ID = "TRX-23BIJAU4GL46ATPW9STY"`, `SCORE = Decimal("62.37")`
  - `QUERY_NAMES = ("fraud_transaction", "fraud_card_exists", "fraud_card_sweep")`
  - `Outcome = list[dict[str, Any]] | Exception`
  - `FakeQueryProvider(queries: Mapping[str, str] | None = None)`: by default it serves each query name as its own SQL text. Attributes `.queries`, `.requested`.
  - `FakeFraudRepository(responses: Mapping[str, Outcome] | None = None)`: answers by SQL text (= query name). Attributes `.responses`, `.calls: list[tuple[str, dict[str, object]]]`; property `.queries: list[str]`.
  - Row builders, each taking `**overrides`: `make_transaction_row` (alias `make_row`), `make_sweep_row` (adds `checked: 3`), `make_card_exists_row`. Also `make_count_only_row(checked: int = 3)`.
  - `fraud_responses(**overrides: Outcome) -> dict[str, Outcome]`: one row per query, keyed by query name.
  - `make_any_row() -> dict[str, Any]`: one row every query can map. Use it over `FakeConnector`, which serves the same rows to every query.
  - Copied unchanged: `FakeCursor`, `FakeConnection`, `FakeConnector(*outcomes, max_age=None, clock=time.monotonic)`, `FakeClock`, `FakeDsqlTokenClient`.

- [ ] **Step 1: Copy the production files**

```bash
SRC=gateway/tools/get_session_context
DST=gateway/tools/transaction_fraud_detection
mkdir -p "$DST"
sed 's/get_session_context/transaction_fraud_detection/g' "$SRC/requirements.txt" > "$DST/requirements.txt"
for f in \
  __init__.py application/__init__.py application/ports/__init__.py \
  application/use_cases/__init__.py delivery/__init__.py \
  delivery/dependencies/__init__.py delivery/presenters/__init__.py \
  domain/__init__.py domain/entities/__init__.py infrastructure/__init__.py \
  infrastructure/queries/__init__.py infrastructure/repositories/__init__.py \
  utils/__init__.py utils/connectors/__init__.py \
  application/ports/database_repository.py application/ports/query_provider.py \
  application/ports/errors.py infrastructure/queries/file_query_provider.py \
  infrastructure/repositories/dsql_repository.py utils/connectors/base.py \
  utils/connectors/dsql.py delivery/settings.py
do
  mkdir -p "$DST/transaction_fraud_detection_lambda/$(dirname "$f")"
  sed 's/get_session_context/transaction_fraud_detection/g' \
    "$SRC/get_session_context_lambda/$f" > "$DST/transaction_fraud_detection_lambda/$f"
done
mkdir -p "$DST/transaction_fraud_detection_lambda/domain/value_objects"
mkdir -p "$DST/transaction_fraud_detection_lambda/queries/postgresql"
printf '%s\n' '"""Value objects: the fraud bands and the validated fraud-check request."""' \
  > "$DST/transaction_fraud_detection_lambda/domain/value_objects/__init__.py"
printf '%s\n' '"""Domain layer: value objects, entities and agent-facing errors. No I/O."""' \
  > "$DST/transaction_fraud_detection_lambda/domain/__init__.py"
```

`get_session_context`'s domain has no `value_objects/` folder, so the loop can't copy one. That's why it's written here, and why the domain docstring is rewritten to mention it.

Check the docstrings:

```bash
cat gateway/tools/transaction_fraud_detection/transaction_fraud_detection_lambda/__init__.py gateway/tools/transaction_fraud_detection/transaction_fraud_detection_lambda/application/use_cases/__init__.py
head -1 gateway/tools/transaction_fraud_detection/requirements.txt
```

Expected:
```text
"""The transaction_fraud_detection Gateway tool Lambda, in hexagonal layers."""
"""Use case of the transaction_fraud_detection tool."""
# Runtime dependencies for the transaction_fraud_detection Lambda.
```

- [ ] **Step 2: Create the test package**

`tests/unit/transaction_fraud_detection/__init__.py` is an empty file.

`tests/unit/transaction_fraud_detection/conftest.py`:

```python
"""Pytest setup for transaction_fraud_detection: make its Lambda package importable.

The ``transaction_fraud_detection_lambda`` package lives in the Lambda asset root
``gateway/tools/transaction_fraud_detection``, so that folder is put on
``sys.path`` exactly as the Lambda runtime does.
"""

import sys
from pathlib import Path

_ASSET_ROOT = (
    Path(__file__).resolve().parents[3]
    / "gateway"
    / "tools"
    / "transaction_fraud_detection"
)

if str(_ASSET_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASSET_ROOT))
```

- [ ] **Step 3: Create `fakes.py`**

Copy it with sed first:

```bash
sed 's/get_session_context/transaction_fraud_detection/g' tests/unit/get_session_context/fakes.py > tests/unit/transaction_fraud_detection/fakes.py
```

Then replace everything from the top of the new file down to, but not including, the line `class FakeCursor:` with this block. Keep everything from `class FakeCursor:` to the end of the file exactly as copied.

```python
"""Test doubles and builders for the transaction_fraud_detection tests."""

import time
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from transaction_fraud_detection_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from transaction_fraud_detection_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryNotFoundError,
)
from transaction_fraud_detection_lambda.application.ports.query_provider import (
    QueryProvider,
)
from transaction_fraud_detection_lambda.utils.connectors.base import PsycopgConnector

# Customer P07 of the curated personas and its fraud charge.
CUSTOMER_ID: Final = "CLI-EX6BOAOEFZHQ"
TRANSACTION_ID: Final = "TRX-23BIJAU4GL46ATPW9STY"
# A score with decimals, so a leak can be searched for in logs and output.
SCORE: Final = Decimal("62.37")

# The three queries: fraud_transaction for one charge, the other two for a sweep.
QUERY_NAMES: Final = ("fraud_transaction", "fraud_card_exists", "fraud_card_sweep")

Outcome = list[dict[str, Any]] | Exception


class FakeQueryProvider(QueryProvider):
    """QueryProvider double backed by an in-memory mapping."""

    def __init__(self, queries: Mapping[str, str] | None = None) -> None:
        """Serve ``queries``; by default each query name is its own SQL text."""
        self.queries: dict[str, str] = dict(
            queries if queries is not None else {name: name for name in QUERY_NAMES}
        )
        self.requested: list[str] = []

    def get(self, name: str) -> str:
        """Record the name and return its SQL, or raise QueryNotFoundError."""
        self.requested.append(name)
        if name not in self.queries:
            raise QueryNotFoundError(f"no query named {name!r}")
        return self.queries[name]


class FakeFraudRepository(DatabaseRepository):
    """DatabaseRepository double that answers each query on its own.

    FakeQueryProvider serves each query name as its SQL text, so responses are
    keyed by query name. A missing name returns no rows; an exception is raised.
    """

    def __init__(self, responses: Mapping[str, Outcome] | None = None) -> None:
        """Answer from ``responses``; with none, every query returns no rows."""
        self.responses: dict[str, Outcome] = dict(responses or {})
        self.calls: list[tuple[str, dict[str, object]]] = []

    @property
    def queries(self) -> list[str]:
        """Return the SQL text of every call, in order."""
        return [query for query, _params in self.calls]

    def execute_query(
        self, query: str, params: Mapping[str, object]
    ) -> list[dict[str, Any]]:
        """Record the call, then raise or return the configured outcome."""
        self.calls.append((query, dict(params)))
        outcome = self.responses.get(query, [])
        if isinstance(outcome, Exception):
            raise outcome
        return [dict(row) for row in outcome]


def make_transaction_row(**overrides: Any) -> dict[str, Any]:
    """Build a fraud_transaction row as psycopg's dict_row returns it."""
    row: dict[str, Any] = {
        "transaction_id": TRANSACTION_ID,
        "transaction_date": datetime(2026, 5, 31, 6, 9, 15),
        "card_last4": "4497",
        "merchant_name": "Estación de Servicio",
        "amount": Decimal("288.69"),
        "currency": "USD",
        "transaction_status": "Approved",
        "fraud_score": SCORE,
    }
    row.update(overrides)
    return row


# The copied repository tests build rows with make_row.
make_row = make_transaction_row


def make_sweep_row(**overrides: Any) -> dict[str, Any]:
    """Build a flagged fraud_card_sweep row: a charge plus the window's count."""
    row: dict[str, Any] = {**make_transaction_row(), "checked": 3}
    row.update(overrides)
    return row


def make_count_only_row(checked: int = 3) -> dict[str, Any]:
    """Build the sweep row returned when nothing in the window is flagged."""
    row: dict[str, Any] = {column: None for column in make_transaction_row()}
    row["checked"] = checked
    return row


def make_card_exists_row(**overrides: Any) -> dict[str, Any]:
    """Build a fraud_card_exists row."""
    row: dict[str, Any] = {"card_exists": 1}
    row.update(overrides)
    return row


def fraud_responses(**overrides: Outcome) -> dict[str, Outcome]:
    """Return one row per query, keyed by query name; overrides replace a query."""
    responses: dict[str, Outcome] = {
        "fraud_transaction": [make_transaction_row()],
        "fraud_card_exists": [make_card_exists_row()],
        "fraud_card_sweep": [make_sweep_row()],
    }
    responses.update(overrides)
    return responses


def make_any_row() -> dict[str, Any]:
    """Build one row that every query can map.

    FakeConnector serves the same rows to every query, so end-to-end tests over
    real adapters need a row with every query's columns.
    """
    return {**make_sweep_row(), **make_card_exists_row()}
```

The copied tail decides which imports the header needs. If ruff reports an unused import here, remove only that import. If it reports an undefined name (F821, for example `date`), add that import back exactly as the get_session_context header has it.

- [ ] **Step 4: Copy the adapter tests**

```bash
for t in test_settings test_file_query_provider test_dsql_repository test_psycopg_connector test_dsql_connector; do
  sed 's/get_session_context/transaction_fraud_detection/g' tests/unit/get_session_context/$t.py > tests/unit/transaction_fraud_detection/$t.py
done
```

- [ ] **Step 5: Run the copied tests**

Run: `$PY -m pytest tests/unit/transaction_fraud_detection -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: all pass, 0 failed. These tests cover copied code, so they pass at once. They prove the copy, not new behaviour.

- [ ] **Step 6: Check isolation and lint**

```bash
grep -rn "get_session_context\|list_credit_cards\|list_card_transactions" gateway/tools/transaction_fraud_detection tests/unit/transaction_fraud_detection
$PY -m ruff format --check gateway/tools/transaction_fraud_detection tests/unit/transaction_fraud_detection </dev/null
$PY -m ruff check gateway/tools/transaction_fraud_detection tests/unit/transaction_fraud_detection </dev/null
```

Expected: the grep prints nothing, and both ruff commands are clean.

---

### Task 2: Domain errors

**Files:**
- Create: `gateway/tools/transaction_fraud_detection/transaction_fraud_detection_lambda/domain/errors.py`
- Test: `tests/unit/transaction_fraud_detection/test_errors.py`

**Interfaces:**
- Consumes: `application.ports.errors` from Task 1 (for the port-error test).
- Produces (in `transaction_fraud_detection_lambda.domain.errors`):
  - `DomainError(message: str)` with `.message`
  - `InvalidInputError(field: str, reason: str)` with `.field`, `.reason`
  - Fixed-message errors, each taking no arguments and carrying `MESSAGE: ClassVar[str]`: `DataSourceUnavailableError`, `FraudCheckLookupError`, `TransactionNotFoundError`, `CardNotFoundError`, `FraudCheckDataIntegrityError`

- [ ] **Step 1: Write the failing test**

`tests/unit/transaction_fraud_detection/test_errors.py`:

```python
"""Tests for domain and port error definitions."""

import pytest
import transaction_fraud_detection_lambda.domain.errors as errors_module
from transaction_fraud_detection_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
    QueryNotFoundError,
)
from transaction_fraud_detection_lambda.domain.errors import (
    CardNotFoundError,
    DataSourceUnavailableError,
    DomainError,
    FraudCheckDataIntegrityError,
    FraudCheckLookupError,
    InvalidInputError,
    TransactionNotFoundError,
)

pytestmark = pytest.mark.unit


def test_invalid_input_error_formats_field_and_reason() -> None:
    error = InvalidInputError("card_last4", "must be exactly 4 digits")

    assert error.field == "card_last4"
    assert error.reason == "must be exactly 4 digits"
    assert error.message == (
        "Invalid value for 'card_last4': must be exactly 4 digits. "
        "Ask the customer to confirm and retry."
    )
    assert str(error) == error.message


@pytest.mark.parametrize(
    ("error_type", "expected"),
    [
        (
            TransactionNotFoundError,
            "No credit-card charge with this transaction_id belongs to this "
            "customer. Don't guess; ask the customer to confirm the charge, or "
            "call list_card_transactions to find it.",
        ),
        (
            CardNotFoundError,
            "None of this customer's credit cards ends in these 4 digits. Call "
            "list_credit_cards to see their cards and ask which one they mean.",
        ),
        (
            DataSourceUnavailableError,
            "The fraud check is temporarily unavailable. Offer to retry in a "
            "moment or hand off to a human agent; if the customer reports a "
            "charge they don't recognize, offer the hand-off now.",
        ),
        (
            FraudCheckLookupError,
            "The fraud check can't run right now due to an internal error. "
            "Don't retry; offer a hand-off to a human agent.",
        ),
        (
            FraudCheckDataIntegrityError,
            "The fraud check came back in an unexpected format. Don't retry; "
            "offer a hand-off to a human agent.",
        ),
    ],
)
def test_fixed_domain_errors_carry_agent_facing_messages(
    error_type: type[DomainError], expected: str
) -> None:
    error = error_type()

    assert isinstance(error, DomainError)
    assert error.message == expected
    assert error_type.MESSAGE == expected  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "name",
    ["SessionContextLookupError", "CustomerNotFoundError", "CardLookupError"],
)
def test_other_tools_errors_are_not_defined(name: str) -> None:
    assert not hasattr(errors_module, name)


@pytest.mark.parametrize(
    "error_type",
    [
        DataSourceConnectionError,
        QueryLimitExceededError,
        QueryExecutionError,
        QueryNotFoundError,
    ],
)
def test_port_errors_share_a_base_class(error_type: type[DataAccessError]) -> None:
    assert issubclass(error_type, DataAccessError)
    assert not issubclass(error_type, DomainError)
```

- [ ] **Step 2: Run the test to see it fail**

Run: `$PY -m pytest tests/unit/transaction_fraud_detection/test_errors.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'transaction_fraud_detection_lambda.domain.errors'`.

- [ ] **Step 3: Write `domain/errors.py`**

```python
"""Domain errors: the only failures the agent is allowed to see.

Each message says what went wrong and what the agent should do next. Messages
never contain SQL, hostnames, driver output, scores or other internal details.
"""

from typing import ClassVar


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


class _FixedMessageError(DomainError):
    """Base for domain errors whose message never varies."""

    MESSAGE: ClassVar[str] = ""

    def __init__(self) -> None:
        """Use the class-level MESSAGE as the agent-facing message."""
        super().__init__(self.MESSAGE)


class TransactionNotFoundError(_FixedMessageError):
    """No credit-card charge of this customer has the transaction_id."""

    MESSAGE: ClassVar[str] = (
        "No credit-card charge with this transaction_id belongs to this "
        "customer. Don't guess; ask the customer to confirm the charge, or "
        "call list_card_transactions to find it."
    )


class CardNotFoundError(_FixedMessageError):
    """None of the customer's credit cards ends in the given 4 digits."""

    MESSAGE: ClassVar[str] = (
        "None of this customer's credit cards ends in these 4 digits. Call "
        "list_credit_cards to see their cards and ask which one they mean."
    )


class DataSourceUnavailableError(_FixedMessageError):
    """The database can't be reached right now; retrying later may work."""

    MESSAGE: ClassVar[str] = (
        "The fraud check is temporarily unavailable. Offer to retry in a "
        "moment or hand off to a human agent; if the customer reports a "
        "charge they don't recognize, offer the hand-off now."
    )


class FraudCheckLookupError(_FixedMessageError):
    """A query is missing, failed or hit a database limit; retrying won't help."""

    MESSAGE: ClassVar[str] = (
        "The fraud check can't run right now due to an internal error. "
        "Don't retry; offer a hand-off to a human agent."
    )


class FraudCheckDataIntegrityError(_FixedMessageError):
    """A row couldn't be mapped to a domain entity."""

    MESSAGE: ClassVar[str] = (
        "The fraud check came back in an unexpected format. Don't retry; "
        "offer a hand-off to a human agent."
    )
```

- [ ] **Step 4: Run the test to see it pass**

Run: `$PY -m pytest tests/unit/transaction_fraud_detection/test_errors.py -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: `13 passed`.

- [ ] **Step 5: Lint**

```bash
$PY -m ruff format --check gateway/tools/transaction_fraud_detection tests/unit/transaction_fraud_detection </dev/null
$PY -m ruff check gateway/tools/transaction_fraud_detection tests/unit/transaction_fraud_detection </dev/null
```

Expected: both clean.

---

### Task 3: Fraud bands

**Files:**
- Create: `gateway/tools/transaction_fraud_detection/transaction_fraud_detection_lambda/domain/value_objects/fraud_bands.py`
- Test: `tests/unit/transaction_fraud_detection/test_fraud_bands.py`

**Interfaces:**
- Consumes: nothing.
- Produces (in `transaction_fraud_detection_lambda.domain.value_objects.fraud_bands`):
  - `FRAUD_ABOVE: Decimal = Decimal("50")`, `REVIEW_ABOVE: Decimal = Decimal("30")`
  - `FraudVerdict(StrEnum)`: `FRAUD = "fraud"`, `REVIEW = "review"`, `NO_FRAUD = "no_fraud"`
  - `ScoreBasis(StrEnum)`: `SCORED = "scored"`, `NOT_SCORED = "not_scored"`
  - `NEXT_STEPS: Mapping[FraudVerdict, str | None]`
  - `assess(score: Decimal | None) -> tuple[FraudVerdict, ScoreBasis]`

- [ ] **Step 1: Write the failing test**

`tests/unit/transaction_fraud_detection/test_fraud_bands.py`:

```python
"""Tests for the fraud bands: the stored score mapped to a verdict."""

from decimal import Decimal

import pytest
from transaction_fraud_detection_lambda.domain.value_objects.fraud_bands import (
    FRAUD_ABOVE,
    NEXT_STEPS,
    REVIEW_ABOVE,
    FraudVerdict,
    ScoreBasis,
    assess,
)

pytestmark = pytest.mark.unit


def test_band_limits_are_pinned() -> None:
    # classify_call_type keeps its own copy of these; both tools pin the literals.
    assert Decimal("50") == FRAUD_ABOVE
    assert Decimal("30") == REVIEW_ABOVE


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (None, (FraudVerdict.NO_FRAUD, ScoreBasis.NOT_SCORED)),
        (Decimal("100.00"), (FraudVerdict.FRAUD, ScoreBasis.SCORED)),
        (Decimal("50.01"), (FraudVerdict.FRAUD, ScoreBasis.SCORED)),
        (Decimal("50.00"), (FraudVerdict.REVIEW, ScoreBasis.SCORED)),
        (Decimal("30.01"), (FraudVerdict.REVIEW, ScoreBasis.SCORED)),
        (Decimal("30.00"), (FraudVerdict.NO_FRAUD, ScoreBasis.SCORED)),
        (Decimal("0.00"), (FraudVerdict.NO_FRAUD, ScoreBasis.SCORED)),
        (Decimal("-1"), (FraudVerdict.NO_FRAUD, ScoreBasis.SCORED)),
        (Decimal("150"), (FraudVerdict.FRAUD, ScoreBasis.SCORED)),
    ],
)
def test_assess_bands_each_score(
    score: Decimal | None, expected: tuple[FraudVerdict, ScoreBasis]
) -> None:
    assert assess(score) == expected


def test_enum_values_are_the_output_strings() -> None:
    assert [v.value for v in FraudVerdict] == ["fraud", "review", "no_fraud"]
    assert [b.value for b in ScoreBasis] == ["scored", "not_scored"]


def test_next_steps_per_verdict() -> None:
    assert NEXT_STEPS == {
        FraudVerdict.FRAUD: (
            "Confirm with the customer, then block the card and open a fraud claim."
        ),
        FraudVerdict.REVIEW: (
            "Ask whether they recognize the charge; if not, offer to open a "
            "case for clarification and dispute."
        ),
        FraudVerdict.NO_FRAUD: None,
    }
```

- [ ] **Step 2: Run the test to see it fail**

Run: `$PY -m pytest tests/unit/transaction_fraud_detection/test_fraud_bands.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: FAIL at collection with `ModuleNotFoundError` for `fraud_bands`.

- [ ] **Step 3: Write `fraud_bands.py`**

```python
"""Fraud bands: the fraud engine's stored score mapped to a verdict.

The dataset's transactions.fraud_score (0-100, numeric(5,2)) is treated as the
feed of a bank fraud engine. This tool reads that score and adds no heuristic of
its own. The bands come from the 2026-10-03 profiling (X3, X4 and X15 in
datathon/analysis/profiling_output.txt): no clean charge scores above 30, and
every charge above 50 is fraud. The score is simulated, so the bands fit this
dataset, not a real engine.

classify_call_type keeps its own copy of these bands (tools never share code).
Both tools' tests pin the literals 50 and 30, so changing one copy breaks a test.
"""

from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Final

FRAUD_ABOVE: Final = Decimal("50")
REVIEW_ABOVE: Final = Decimal("30")


class FraudVerdict(StrEnum):
    """What the agent should treat the charge as."""

    FRAUD = "fraud"
    REVIEW = "review"
    NO_FRAUD = "no_fraud"


class ScoreBasis(StrEnum):
    """Whether the fraud engine produced a score for the charge."""

    SCORED = "scored"
    NOT_SCORED = "not_scored"


NEXT_STEPS: Final[Mapping[FraudVerdict, str | None]] = {
    FraudVerdict.FRAUD: (
        "Confirm with the customer, then block the card and open a fraud claim."
    ),
    FraudVerdict.REVIEW: (
        "Ask whether they recognize the charge; if not, offer to open a case "
        "for clarification and dispute."
    ),
    FraudVerdict.NO_FRAUD: None,
}


def assess(score: Decimal | None) -> tuple[FraudVerdict, ScoreBasis]:
    """Band a stored score. The comparisons are strict: 50.00 is review.

    A missing score is no_fraud with basis not_scored: the engine produced
    nothing, which isn't proof the charge is genuine. A score outside 0-100 is
    banded as it is.
    """
    if score is None:
        return FraudVerdict.NO_FRAUD, ScoreBasis.NOT_SCORED
    if score > FRAUD_ABOVE:
        return FraudVerdict.FRAUD, ScoreBasis.SCORED
    if score > REVIEW_ABOVE:
        return FraudVerdict.REVIEW, ScoreBasis.SCORED
    return FraudVerdict.NO_FRAUD, ScoreBasis.SCORED
```

- [ ] **Step 4: Run the test to see it pass**

Run: `$PY -m pytest tests/unit/transaction_fraud_detection/test_fraud_bands.py -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: `12 passed`.

- [ ] **Step 5: Lint**

Same two ruff commands as Task 2 Step 5. Expected: both clean.

---

### Task 4: `FraudCheckRequest`

**Files:**
- Create: `gateway/tools/transaction_fraud_detection/transaction_fraud_detection_lambda/domain/value_objects/fraud_check_request.py`
- Test: `tests/unit/transaction_fraud_detection/test_fraud_check_request.py`

**Interfaces:**
- Consumes: `InvalidInputError(field, reason)` from Task 2.
- Produces: `FraudCheckRequest(customer_id: str, transaction_id: str | None, card_last4: str | None)`, a frozen dataclass, with `FraudCheckRequest.from_raw(event: object) -> FraudCheckRequest`. Exactly one of `transaction_id` and `card_last4` is set on every instance `from_raw` returns.

- [ ] **Step 1: Write the failing test**

`tests/unit/transaction_fraud_detection/test_fraud_check_request.py`:

```python
"""Tests for FraudCheckRequest.from_raw: validation before any query."""

import pytest
from transaction_fraud_detection_lambda.domain.errors import InvalidInputError
from transaction_fraud_detection_lambda.domain.value_objects.fraud_check_request import (  # noqa: E501
    FraudCheckRequest,
)

from .fakes import CUSTOMER_ID, TRANSACTION_ID

pytestmark = pytest.mark.unit

CUSTOMER_REASON = "is required and must be a non-empty string"
TRANSACTION_REASON = "must be a non-empty string"
LAST4_REASON = "must be exactly 4 digits"
BOTH_REASON = "give either transaction_id or card_last4, not both"
NEITHER_REASON = (
    "give either transaction_id (one charge) or card_last4 "
    "(sweep of that card's last 30 days)"
)


def rejected(event: object) -> InvalidInputError:
    """Return the InvalidInputError from_raw raises for ``event``."""
    with pytest.raises(InvalidInputError) as caught:
        FraudCheckRequest.from_raw(event)
    return caught.value


def test_transaction_id_is_stripped_and_uppercased() -> None:
    request = FraudCheckRequest.from_raw(
        {"customer_id": " cli-ex6boaoefzhq ", "transaction_id": " trx-23bijau4gl46atpw9sty "}
    )

    assert request == FraudCheckRequest(
        customer_id=CUSTOMER_ID, transaction_id=TRANSACTION_ID, card_last4=None
    )


def test_card_last4_is_stripped() -> None:
    request = FraudCheckRequest.from_raw(
        {"customer_id": CUSTOMER_ID, "card_last4": " 4497 "}
    )

    assert request == FraudCheckRequest(
        customer_id=CUSTOMER_ID, transaction_id=None, card_last4="4497"
    )


def test_unknown_keys_are_ignored() -> None:
    request = FraudCheckRequest.from_raw(
        {"customer_id": CUSTOMER_ID, "card_last4": "4497", "fraud_score": 99}
    )

    assert request.card_last4 == "4497"


@pytest.mark.parametrize(
    "event",
    [
        None,
        [],
        "customer_id=CLI-EX6BOAOEFZHQ",
        {},
        {"customer_id": None, "card_last4": "4497"},
        {"customer_id": "", "card_last4": "4497"},
        {"customer_id": "   ", "card_last4": "4497"},
        {"customer_id": 42, "card_last4": "4497"},
        {"customer_id": True, "card_last4": "4497"},
    ],
)
def test_bad_customer_id_is_rejected(event: object) -> None:
    error = rejected(event)

    assert (error.field, error.reason) == ("customer_id", CUSTOMER_REASON)


@pytest.mark.parametrize("value", [42, True, ["TRX-1"]])
def test_non_string_transaction_id_is_rejected(value: object) -> None:
    error = rejected({"customer_id": CUSTOMER_ID, "transaction_id": value})

    assert (error.field, error.reason) == ("transaction_id", TRANSACTION_REASON)


@pytest.mark.parametrize("value", ["449", "44971", "44a7", "٤٤٩٧", "4 97", 4497])
def test_bad_card_last4_is_rejected(value: object) -> None:
    error = rejected({"customer_id": CUSTOMER_ID, "card_last4": value})

    assert (error.field, error.reason) == ("card_last4", LAST4_REASON)


def test_both_given_is_rejected() -> None:
    error = rejected(
        {
            "customer_id": CUSTOMER_ID,
            "transaction_id": TRANSACTION_ID,
            "card_last4": "4497",
        }
    )

    assert (error.field, error.reason) == ("transaction_id", BOTH_REASON)


@pytest.mark.parametrize(
    "event",
    [
        {"customer_id": CUSTOMER_ID},
        {"customer_id": CUSTOMER_ID, "transaction_id": None, "card_last4": None},
        {"customer_id": CUSTOMER_ID, "transaction_id": "  ", "card_last4": ""},
    ],
)
def test_neither_given_is_rejected(event: object) -> None:
    error = rejected(event)

    assert (error.field, error.reason) == ("transaction_id", NEITHER_REASON)


def test_a_blank_field_counts_as_missing_next_to_the_other() -> None:
    request = FraudCheckRequest.from_raw(
        {"customer_id": CUSTOMER_ID, "transaction_id": " ", "card_last4": "4497"}
    )

    assert request.transaction_id is None
    assert request.card_last4 == "4497"
```

`ruff format` may rewrap the long dict in `test_transaction_id_is_stripped_and_uppercased`; let it.

- [ ] **Step 2: Run the test to see it fail**

Run: `$PY -m pytest tests/unit/transaction_fraud_detection/test_fraud_check_request.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: FAIL at collection with `ModuleNotFoundError` for `fraud_check_request`.

- [ ] **Step 3: Write `fraud_check_request.py`**

```python
"""The validated input of one fraud check."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from transaction_fraud_detection_lambda.domain.errors import InvalidInputError

# ASCII digits only: str.isdigit() and \d also accept digits of other scripts.
_LAST4: Final = re.compile(r"[0-9]{4}")


@dataclass(frozen=True)
class FraudCheckRequest:
    """One fraud check: one charge, or a sweep of one card's last 30 days.

    Exactly one of transaction_id and card_last4 is set.
    """

    customer_id: str
    transaction_id: str | None
    card_last4: str | None

    @classmethod
    def from_raw(cls, event: object) -> "FraudCheckRequest":
        """Validate the tool arguments. Unknown keys are ignored.

        An event that isn't a JSON object is treated as ``{}``. A blank
        transaction_id or card_last4 counts as missing.

        Raises:
            InvalidInputError: A field is invalid, both modes are given, or
                neither is.
        """
        raw: Mapping[object, object] = event if isinstance(event, Mapping) else {}
        customer_id = _customer_id(raw.get("customer_id"))
        transaction_id = _transaction_id(raw.get("transaction_id"))
        card_last4 = _card_last4(raw.get("card_last4"))
        if transaction_id is not None and card_last4 is not None:
            raise InvalidInputError(
                "transaction_id", "give either transaction_id or card_last4, not both"
            )
        if transaction_id is None and card_last4 is None:
            raise InvalidInputError(
                "transaction_id",
                "give either transaction_id (one charge) or card_last4 "
                "(sweep of that card's last 30 days)",
            )
        return cls(
            customer_id=customer_id,
            transaction_id=transaction_id,
            card_last4=card_last4,
        )


def _customer_id(value: object) -> str:
    """Strip and uppercase the id; ids look like ``CLI-EX6BOAOEFZHQ``."""
    if not isinstance(value, str) or not value.strip():
        raise InvalidInputError(
            "customer_id", "is required and must be a non-empty string"
        )
    return value.strip().upper()


def _transaction_id(value: object) -> str | None:
    """Strip and uppercase the id; None or blank means not given."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidInputError("transaction_id", "must be a non-empty string")
    stripped = value.strip()
    return stripped.upper() if stripped else None


def _card_last4(value: object) -> str | None:
    """Return exactly 4 ASCII digits; None or blank means not given."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidInputError("card_last4", "must be exactly 4 digits")
    stripped = value.strip()
    if not stripped:
        return None
    if _LAST4.fullmatch(stripped) is None:
        raise InvalidInputError("card_last4", "must be exactly 4 digits")
    return stripped
```

- [ ] **Step 4: Run the test to see it pass**

Run: `$PY -m pytest tests/unit/transaction_fraud_detection/test_fraud_check_request.py -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: `26 passed`.

- [ ] **Step 5: Lint**

Same two ruff commands as Task 2 Step 5 (run `ruff format` first if `--check` complains about the test file). Expected: both clean.

---

### Task 5: Entities and use case

**Files:**
- Create: `gateway/tools/transaction_fraud_detection/transaction_fraud_detection_lambda/domain/entities/fraud_assessment.py`
- Create: `gateway/tools/transaction_fraud_detection/transaction_fraud_detection_lambda/application/use_cases/transaction_fraud_detection.py`
- Test: `tests/unit/transaction_fraud_detection/test_transaction_fraud_detection_use_case.py`

**Interfaces:**
- Consumes: Task 1 ports; Task 2 errors; Task 3 `assess`, `REVIEW_ABOVE`, `FraudVerdict`, `ScoreBasis`; Task 4 `FraudCheckRequest`; Task 1 fakes.
- Produces:
  - `domain.entities.fraud_assessment.FraudAssessment(transaction_id: str, transaction_date: datetime | None, card_last4: str | None, merchant_name: str | None, amount: Decimal | None, currency: str | None, transaction_status: str | None, verdict: FraudVerdict, basis: ScoreBasis)`, frozen, no score field.
  - `domain.entities.fraud_assessment.CardSweep(card_last4: str, date_from: datetime, date_to: datetime, checked: int, flagged: tuple[FraudAssessment, ...], truncated: bool)`, frozen. `date_from` and `date_to` are naive UTC.
  - `application.use_cases.transaction_fraud_detection.TransactionFraudDetectionUseCase(database_repository: DatabaseRepository, query_provider: QueryProvider, max_rows: int = 25)` with `SWEEP_DAYS = 30` and `execute(request: FraudCheckRequest, as_of: datetime) -> FraudAssessment | CardSweep`.

- [ ] **Step 1: Write the failing test**

`tests/unit/transaction_fraud_detection/test_transaction_fraud_detection_use_case.py`:

```python
"""Tests for TransactionFraudDetectionUseCase."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from transaction_fraud_detection_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
)
from transaction_fraud_detection_lambda.application.use_cases.transaction_fraud_detection import (  # noqa: E501
    TransactionFraudDetectionUseCase,
)
from transaction_fraud_detection_lambda.domain.entities.fraud_assessment import (
    CardSweep,
    FraudAssessment,
)
from transaction_fraud_detection_lambda.domain.errors import (
    CardNotFoundError,
    DataSourceUnavailableError,
    DomainError,
    FraudCheckDataIntegrityError,
    FraudCheckLookupError,
    TransactionNotFoundError,
)
from transaction_fraud_detection_lambda.domain.value_objects.fraud_bands import (
    REVIEW_ABOVE,
    FraudVerdict,
    ScoreBasis,
)
from transaction_fraud_detection_lambda.domain.value_objects.fraud_check_request import (  # noqa: E501
    FraudCheckRequest,
)

from .fakes import (
    CUSTOMER_ID,
    TRANSACTION_ID,
    FakeFraudRepository,
    FakeQueryProvider,
    Outcome,
    fraud_responses,
    make_count_only_row,
    make_sweep_row,
    make_transaction_row,
)

pytestmark = pytest.mark.unit

AS_OF = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
# What the SQL receives: the same instant as naive UTC.
AS_OF_SQL = datetime(2026, 6, 17, 23, 59, 59)
TX_REQUEST = FraudCheckRequest(
    customer_id=CUSTOMER_ID, transaction_id=TRANSACTION_ID, card_last4=None
)
CARD_REQUEST = FraudCheckRequest(
    customer_id=CUSTOMER_ID, transaction_id=None, card_last4="4497"
)
ASSESSMENT = FraudAssessment(
    transaction_id=TRANSACTION_ID,
    transaction_date=datetime(2026, 5, 31, 6, 9, 15),
    card_last4="4497",
    merchant_name="Estación de Servicio",
    amount=Decimal("288.69"),
    currency="USD",
    transaction_status="Approved",
    verdict=FraudVerdict.FRAUD,
    basis=ScoreBasis.SCORED,
)


def make_use_case(
    responses: dict[str, Outcome] | None = None, max_rows: int = 25
) -> tuple[TransactionFraudDetectionUseCase, FakeFraudRepository]:
    """Build the use case over a fake repository; return both."""
    database_repository = FakeFraudRepository(
        fraud_responses() if responses is None else responses
    )
    use_case = TransactionFraudDetectionUseCase(
        database_repository=database_repository,
        query_provider=FakeQueryProvider(),
        max_rows=max_rows,
    )
    return use_case, database_repository


def sweep_rows(count: int, checked: int = 40) -> list[dict[str, Any]]:
    """Build ``count`` flagged sweep rows with distinct ids."""
    return [
        make_sweep_row(transaction_id=f"TRX-{i:03d}", checked=checked)
        for i in range(count)
    ]


def test_transaction_mode_sends_exactly_its_params() -> None:
    use_case, database_repository = make_use_case()

    use_case.execute(TX_REQUEST, as_of=AS_OF)

    assert database_repository.calls == [
        (
            "fraud_transaction",
            {
                "customer_id": CUSTOMER_ID,
                "transaction_id": TRANSACTION_ID,
                "as_of": AS_OF_SQL,
            },
        )
    ]


def test_transaction_mode_maps_the_row_and_drops_the_score() -> None:
    use_case, _ = make_use_case()

    result = use_case.execute(TX_REQUEST, as_of=AS_OF)

    assert result == ASSESSMENT
    assert not hasattr(result, "fraud_score")


def test_card_mode_checks_the_card_then_sweeps() -> None:
    use_case, database_repository = make_use_case()

    use_case.execute(CARD_REQUEST, as_of=AS_OF)

    assert database_repository.calls == [
        ("fraud_card_exists", {"customer_id": CUSTOMER_ID, "card_last4": "4497"}),
        (
            "fraud_card_sweep",
            {
                "customer_id": CUSTOMER_ID,
                "card_last4": "4497",
                "as_of": AS_OF_SQL,
                "review_above": Decimal("30"),
                "limit": 26,
            },
        ),
    ]
    assert database_repository.calls[1][1]["review_above"] is REVIEW_ABOVE


def test_card_mode_returns_the_sweep() -> None:
    use_case, _ = make_use_case()

    result = use_case.execute(CARD_REQUEST, as_of=AS_OF)

    assert result == CardSweep(
        card_last4="4497",
        date_from=AS_OF_SQL - timedelta(days=30),
        date_to=AS_OF_SQL,
        checked=3,
        flagged=(ASSESSMENT,),
        truncated=False,
    )


def test_an_aware_as_of_in_another_zone_is_sent_as_naive_utc() -> None:
    use_case, database_repository = make_use_case()
    bogota = datetime(2026, 6, 17, 18, 59, 59, tzinfo=timezone(timedelta(hours=-5)))

    result = use_case.execute(CARD_REQUEST, as_of=bogota)

    assert database_repository.calls[1][1]["as_of"] == AS_OF_SQL
    assert isinstance(result, CardSweep)
    assert result.date_to == AS_OF_SQL


def test_no_transaction_row_raises_not_found() -> None:
    use_case, _ = make_use_case(fraud_responses(fraud_transaction=[]))

    with pytest.raises(TransactionNotFoundError):
        use_case.execute(TX_REQUEST, as_of=AS_OF)


def test_no_card_row_raises_card_not_found_without_sweeping() -> None:
    use_case, database_repository = make_use_case(
        fraud_responses(fraud_card_exists=[])
    )

    with pytest.raises(CardNotFoundError):
        use_case.execute(CARD_REQUEST, as_of=AS_OF)
    assert database_repository.queries == ["fraud_card_exists"]


def test_a_sweep_with_no_rows_has_checked_zero() -> None:
    use_case, _ = make_use_case(fraud_responses(fraud_card_sweep=[]))

    result = use_case.execute(CARD_REQUEST, as_of=AS_OF)

    assert isinstance(result, CardSweep)
    assert (result.checked, result.flagged, result.truncated) == (0, (), False)


def test_a_count_only_row_gives_checked_and_no_items() -> None:
    use_case, _ = make_use_case(
        fraud_responses(fraud_card_sweep=[make_count_only_row(checked=3)])
    )

    result = use_case.execute(CARD_REQUEST, as_of=AS_OF)

    assert isinstance(result, CardSweep)
    assert (result.checked, result.flagged, result.truncated) == (3, (), False)


def test_checked_comes_from_the_rows() -> None:
    use_case, _ = make_use_case(fraud_responses(fraud_card_sweep=sweep_rows(2, 7)))

    result = use_case.execute(CARD_REQUEST, as_of=AS_OF)

    assert isinstance(result, CardSweep)
    assert result.checked == 7
    assert [a.transaction_id for a in result.flagged] == ["TRX-000", "TRX-001"]


def test_the_sweep_is_capped_and_marked_truncated() -> None:
    use_case, _ = make_use_case(fraud_responses(fraud_card_sweep=sweep_rows(26)))

    result = use_case.execute(CARD_REQUEST, as_of=AS_OF)

    assert isinstance(result, CardSweep)
    assert len(result.flagged) == 25
    assert result.truncated is True
    assert result.flagged[-1].transaction_id == "TRX-024"


def test_exactly_the_cap_is_not_truncated() -> None:
    use_case, _ = make_use_case(fraud_responses(fraud_card_sweep=sweep_rows(25)))

    result = use_case.execute(CARD_REQUEST, as_of=AS_OF)

    assert isinstance(result, CardSweep)
    assert (len(result.flagged), result.truncated) == (25, False)


def test_max_rows_sets_the_cap_and_the_limit() -> None:
    use_case, database_repository = make_use_case(
        fraud_responses(fraud_card_sweep=sweep_rows(4)), max_rows=3
    )

    result = use_case.execute(CARD_REQUEST, as_of=AS_OF)

    assert isinstance(result, CardSweep)
    assert (len(result.flagged), result.truncated) == (3, True)
    assert database_repository.calls[1][1]["limit"] == 4


@pytest.mark.parametrize(
    ("score", "verdict", "basis"),
    [
        (Decimal("62.37"), FraudVerdict.FRAUD, ScoreBasis.SCORED),
        (62, FraudVerdict.FRAUD, ScoreBasis.SCORED),
        (Decimal("50.00"), FraudVerdict.REVIEW, ScoreBasis.SCORED),
        (Decimal("30.01"), FraudVerdict.REVIEW, ScoreBasis.SCORED),
        (Decimal("30.00"), FraudVerdict.NO_FRAUD, ScoreBasis.SCORED),
        (None, FraudVerdict.NO_FRAUD, ScoreBasis.NOT_SCORED),
    ],
)
def test_scores_are_banded(
    score: object, verdict: FraudVerdict, basis: ScoreBasis
) -> None:
    use_case, _ = make_use_case(
        fraud_responses(fraud_transaction=[make_transaction_row(fraud_score=score)])
    )

    result = use_case.execute(TX_REQUEST, as_of=AS_OF)

    assert isinstance(result, FraudAssessment)
    assert (result.verdict, result.basis) == (verdict, basis)


@pytest.mark.parametrize(
    ("request_", "query", "error", "expected"),
    [
        (TX_REQUEST, "fraud_transaction", DataSourceConnectionError("down"),
         DataSourceUnavailableError),
        (TX_REQUEST, "fraud_transaction", QueryExecutionError("boom"),
         FraudCheckLookupError),
        (CARD_REQUEST, "fraud_card_exists", DataSourceConnectionError("down"),
         DataSourceUnavailableError),
        (CARD_REQUEST, "fraud_card_exists", QueryExecutionError("boom"),
         FraudCheckLookupError),
        (CARD_REQUEST, "fraud_card_sweep", DataSourceConnectionError("down"),
         DataSourceUnavailableError),
        (CARD_REQUEST, "fraud_card_sweep", QueryLimitExceededError("128 MiB"),
         FraudCheckLookupError),
    ],
)
def test_each_port_error_becomes_its_domain_error(
    request_: FraudCheckRequest,
    query: str,
    error: Exception,
    expected: type[DomainError],
) -> None:
    use_case, _ = make_use_case(fraud_responses(**{query: error}))

    with pytest.raises(expected):
        use_case.execute(request_, as_of=AS_OF)


@pytest.mark.parametrize("request_", [TX_REQUEST, CARD_REQUEST])
def test_a_missing_query_raises_lookup(request_: FraudCheckRequest) -> None:
    use_case = TransactionFraudDetectionUseCase(
        database_repository=FakeFraudRepository(fraud_responses()),
        query_provider=FakeQueryProvider({}),
    )

    with pytest.raises(FraudCheckLookupError):
        use_case.execute(request_, as_of=AS_OF)


def without(row: dict[str, Any], column: str) -> dict[str, Any]:
    """Return ``row`` without ``column``."""
    return {key: value for key, value in row.items() if key != column}


@pytest.mark.parametrize(
    ("request_", "query", "row"),
    [
        (TX_REQUEST, "fraud_transaction", make_transaction_row(fraud_score="62")),
        (TX_REQUEST, "fraud_transaction", make_transaction_row(fraud_score=62.5)),
        (TX_REQUEST, "fraud_transaction", make_transaction_row(fraud_score=True)),
        (TX_REQUEST, "fraud_transaction", make_transaction_row(transaction_id=None)),
        (TX_REQUEST, "fraud_transaction", make_transaction_row(amount="288.69")),
        (TX_REQUEST, "fraud_transaction",
         make_transaction_row(transaction_date="2026-05-31")),
        (TX_REQUEST, "fraud_transaction", without(make_transaction_row(), "currency")),
        (CARD_REQUEST, "fraud_card_sweep", without(make_sweep_row(), "checked")),
        (CARD_REQUEST, "fraud_card_sweep", make_sweep_row(checked="3")),
        (CARD_REQUEST, "fraud_card_sweep", make_sweep_row(checked=True)),
        (CARD_REQUEST, "fraud_card_sweep", make_count_only_row(checked=None)),  # type: ignore[arg-type]
        (CARD_REQUEST, "fraud_card_sweep",
         make_sweep_row(fraud_score=Decimal("NaN"))),
    ],
)
def test_a_bad_row_raises_data_integrity(
    request_: FraudCheckRequest, query: str, row: dict[str, Any]
) -> None:
    use_case, _ = make_use_case(fraud_responses(**{query: [row]}))

    with pytest.raises(FraudCheckDataIntegrityError):
        use_case.execute(request_, as_of=AS_OF)


def test_max_rows_below_one_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_rows"):
        TransactionFraudDetectionUseCase(
            database_repository=FakeFraudRepository(),
            query_provider=FakeQueryProvider(),
            max_rows=0,
        )


def test_a_naive_as_of_is_rejected_before_any_query() -> None:
    use_case, database_repository = make_use_case()

    with pytest.raises(ValueError, match="aware"):
        use_case.execute(TX_REQUEST, as_of=AS_OF_SQL)
    assert database_repository.calls == []
```

`ruff format` will rewrap the parametrize lists; let it. If the `# type: ignore` comment on the long `make_count_only_row(checked=None)` line pushes it past 88 characters, drop the comment (ruff ignores mypy comments; nothing type-checks the tests).

- [ ] **Step 2: Run the test to see it fail**

Run: `$PY -m pytest tests/unit/transaction_fraud_detection/test_transaction_fraud_detection_use_case.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: FAIL at collection with `ModuleNotFoundError` for `transaction_fraud_detection_lambda.application.use_cases.transaction_fraud_detection`.

- [ ] **Step 3: Write `domain/entities/fraud_assessment.py`**

```python
"""Domain entities returned by the fraud check. Neither carries the score."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from transaction_fraud_detection_lambda.domain.value_objects.fraud_bands import (
    FraudVerdict,
    ScoreBasis,
)


@dataclass(frozen=True)
class FraudAssessment:
    """The verdict on one credit-card charge.

    The use case drops the score after banding it, so it can't reach the agent.
    """

    transaction_id: str
    transaction_date: datetime | None
    card_last4: str | None
    merchant_name: str | None
    amount: Decimal | None
    currency: str | None
    transaction_status: str | None
    verdict: FraudVerdict
    basis: ScoreBasis


@dataclass(frozen=True)
class CardSweep:
    """Every charge on one card in the last 30 days, flagged ones only.

    Attributes:
        card_last4: The card swept.
        date_from: as_of minus 30 days, inclusive, naive UTC.
        date_to: as_of, naive UTC.
        checked: How many charges were in the window, flagged or not.
        flagged: The fraud and review charges, highest score first.
        truncated: More flagged charges exist than were returned.
    """

    card_last4: str
    date_from: datetime
    date_to: datetime
    checked: int
    flagged: tuple[FraudAssessment, ...]
    truncated: bool
```

- [ ] **Step 4: Write `application/use_cases/transaction_fraud_detection.py`**

```python
"""Use case: check one charge, or sweep one card, for fraud."""

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Final

from transaction_fraud_detection_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from transaction_fraud_detection_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
)
from transaction_fraud_detection_lambda.application.ports.query_provider import (
    QueryProvider,
)
from transaction_fraud_detection_lambda.domain.entities.fraud_assessment import (
    CardSweep,
    FraudAssessment,
)
from transaction_fraud_detection_lambda.domain.errors import (
    CardNotFoundError,
    DataSourceUnavailableError,
    FraudCheckDataIntegrityError,
    FraudCheckLookupError,
    TransactionNotFoundError,
)
from transaction_fraud_detection_lambda.domain.value_objects.fraud_bands import (
    REVIEW_ABOVE,
    assess,
)
from transaction_fraud_detection_lambda.domain.value_objects.fraud_check_request import (  # noqa: E501
    FraudCheckRequest,
)

TRANSACTION_QUERY_NAME: Final = "fraud_transaction"
CARD_EXISTS_QUERY_NAME: Final = "fraud_card_exists"
SWEEP_QUERY_NAME: Final = "fraud_card_sweep"


class TransactionFraudDetectionUseCase:
    """Band the fraud engine's stored score through a database-agnostic repository.

    One charge runs fraud_transaction. A card sweep runs fraud_card_exists, then
    fraud_card_sweep, on the repository's single connection. Every failure
    becomes one fixed domain error; the score never leaves this class.
    """

    SWEEP_DAYS: Final = 30

    def __init__(
        self,
        database_repository: DatabaseRepository,
        query_provider: QueryProvider,
        max_rows: int = 25,
    ) -> None:
        """Store the ports and the cap on flagged items.

        Args:
            database_repository: Executes the queries; any DatabaseRepository
                adapter.
            query_provider: Supplies the SQL text for the configured dialect.
            max_rows: Maximum flagged items a sweep returns.

        Raises:
            ValueError: If max_rows is less than 1.
        """
        if max_rows < 1:
            raise ValueError("max_rows must be at least 1")
        self._database_repository: DatabaseRepository = database_repository
        self._query_provider: QueryProvider = query_provider
        self._max_rows: int = max_rows

    def execute(
        self, request: FraudCheckRequest, as_of: datetime
    ) -> FraudAssessment | CardSweep:
        """Check the charge, or sweep the card, as the request says.

        Args:
            request: The validated input; exactly one mode is set.
            as_of: "Now", an aware datetime. Every query gets it as naive UTC,
                because the ERD's timestamp columns have no time zone.

        Raises:
            ValueError: as_of is naive (a programming error, not user input).
            TransactionNotFoundError: No credit-card charge of this customer
                has the transaction_id.
            CardNotFoundError: No credit card of this customer ends in
                card_last4. The sweep query then never runs.
            DataSourceUnavailableError: A query couldn't connect.
            FraudCheckLookupError: A query is missing, failed or hit a limit.
            FraudCheckDataIntegrityError: A row couldn't be mapped.
        """
        as_of_sql = _utc(as_of).replace(tzinfo=None)
        try:
            if request.transaction_id is not None:
                return self._one_charge(
                    request.customer_id, request.transaction_id, as_of_sql
                )
            return self._sweep(request.customer_id, str(request.card_last4), as_of_sql)
        except DataSourceConnectionError as exc:
            raise DataSourceUnavailableError() from exc
        except DataAccessError as exc:
            raise FraudCheckLookupError() from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise FraudCheckDataIntegrityError() from exc

    def _one_charge(
        self, customer_id: str, transaction_id: str, as_of_sql: datetime
    ) -> FraudAssessment:
        """Load and band one charge."""
        rows = self._run(
            TRANSACTION_QUERY_NAME,
            {
                "customer_id": customer_id,
                "transaction_id": transaction_id,
                "as_of": as_of_sql,
            },
        )
        if not rows:
            raise TransactionNotFoundError()
        return _to_assessment(rows[0])

    def _sweep(self, customer_id: str, card_last4: str, as_of_sql: datetime) -> CardSweep:
        """Check the card exists, then load its flagged charges and the count.

        The sweep query returns a count-only row (NULL transaction columns)
        when nothing is flagged, so ``checked`` is right for a clean card.
        """
        params = {"customer_id": customer_id, "card_last4": card_last4}
        if not self._run(CARD_EXISTS_QUERY_NAME, params):
            raise CardNotFoundError()
        rows = self._run(
            SWEEP_QUERY_NAME,
            {
                **params,
                "as_of": as_of_sql,
                "review_above": REVIEW_ABOVE,
                "limit": self._max_rows + 1,
            },
        )
        checked = _required_int(rows[0], "checked") if rows else 0
        items = [row for row in rows if row["transaction_id"] is not None]
        return CardSweep(
            card_last4=card_last4,
            date_from=as_of_sql - timedelta(days=self.SWEEP_DAYS),
            date_to=as_of_sql,
            checked=checked,
            flagged=tuple(_to_assessment(row) for row in items[: self._max_rows]),
            truncated=len(items) > self._max_rows,
        )

    def _run(self, name: str, params: Mapping[str, object]) -> list[dict[str, Any]]:
        """Load the named SQL and run it.

        Raises:
            DataAccessError: The query is missing or failed.
        """
        query = self._query_provider.get(name)
        return self._database_repository.execute_query(query, params)


def _utc(as_of: datetime) -> datetime:
    """Return as_of converted to aware UTC.

    Raises:
        ValueError: as_of is naive.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be an aware datetime")
    return as_of.astimezone(timezone.utc)


def _to_assessment(row: Mapping[str, Any]) -> FraudAssessment:
    """Band the row's score and map the row; the score itself is dropped."""
    verdict, basis = assess(_optional_score(row, "fraud_score"))
    return FraudAssessment(
        transaction_id=_required_text(row, "transaction_id"),
        transaction_date=_optional_datetime(row, "transaction_date"),
        card_last4=_optional_text(row, "card_last4"),
        merchant_name=_optional_text(row, "merchant_name"),
        amount=_optional_amount(row, "amount"),
        currency=_optional_text(row, "currency"),
        transaction_status=_optional_text(row, "transaction_status"),
        verdict=verdict,
        basis=basis,
    )


def _required_text(row: Mapping[str, Any], column: str) -> str:
    """Return a column that must not be NULL as text."""
    value = row[column]
    if value is None:
        raise TypeError(f"{column} is None, expected text")
    return str(value)


def _optional_text(row: Mapping[str, Any], column: str) -> str | None:
    """Return a nullable column as text, keeping None."""
    value = row[column]
    return None if value is None else str(value)


def _optional_amount(row: Mapping[str, Any], column: str) -> Decimal | None:
    """Return a nullable, finite numeric column as an exact Decimal."""
    value = row[column]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Decimal | int | float):
        raise TypeError(f"{column} is {type(value).__name__}, expected a number")
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    if not amount.is_finite():
        raise ValueError(f"{column} is not finite")
    return amount


def _optional_score(row: Mapping[str, Any], column: str) -> Decimal | None:
    """Return the nullable score as a finite Decimal; only Decimal or int pass.

    numeric(5,2) arrives as Decimal. A float, string or bool means the column
    or the driver changed, so the row is rejected instead of guessing a verdict.
    """
    value = row[column]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Decimal | int):
        raise TypeError(f"{column} is {type(value).__name__}, expected a numeric")
    score = value if isinstance(value, Decimal) else Decimal(value)
    if not score.is_finite():
        raise ValueError(f"{column} is not finite")
    return score


def _optional_datetime(row: Mapping[str, Any], column: str) -> datetime | None:
    """Return a nullable timestamp column as it is stored."""
    value = row[column]
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    raise TypeError(f"{column} is {type(value).__name__}, expected a timestamp")


def _required_int(row: Mapping[str, Any], column: str) -> int:
    """Return an integer column that must not be NULL; bool is rejected."""
    value = row[column]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{column} is {type(value).__name__}, expected an integer")
    return value
```

`ruff format` may rewrap the `_sweep` signature and the `return self._sweep(...)` line; let it.

- [ ] **Step 5: Run the test to see it pass**

Run: `$PY -m pytest tests/unit/transaction_fraud_detection/test_transaction_fraud_detection_use_case.py -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: `41 passed`.

- [ ] **Step 6: Lint**

Same two ruff commands as Task 2 Step 5 (run `ruff format` first on these files if `--check` complains). Expected: both clean.

---

### Task 6: SQL files, `tool_spec.json` and contract tests

**Files:**
- Create: `gateway/tools/transaction_fraud_detection/transaction_fraud_detection_lambda/queries/postgresql/fraud_transaction.sql`
- Create: `.../queries/postgresql/fraud_card_exists.sql`
- Create: `.../queries/postgresql/fraud_card_sweep.sql`
- Create: `gateway/tools/transaction_fraud_detection/tool_spec.json`
- Test: `tests/unit/transaction_fraud_detection/test_query_contracts.py`

**Interfaces:**
- Consumes: Task 5 `TransactionFraudDetectionUseCase` (the params it sends); Task 4 `FraudCheckRequest`; Task 1 `FileQueryProvider` and fakes.
- Produces: the three SQL files Task 8 loads by name, and the `tool_spec.json` Task 10's Lambda serves.

- [ ] **Step 1: Write the failing test**

`tests/unit/transaction_fraud_detection/test_query_contracts.py`:

```python
"""Drift tests: the SQL files and tool_spec.json must match the Python contracts."""

import dataclasses
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from transaction_fraud_detection_lambda.application.use_cases.transaction_fraud_detection import (  # noqa: E501
    TransactionFraudDetectionUseCase,
)
from transaction_fraud_detection_lambda.domain.value_objects.fraud_check_request import (  # noqa: E501
    FraudCheckRequest,
)
from transaction_fraud_detection_lambda.infrastructure.queries.file_query_provider import (  # noqa: E501
    FileQueryProvider,
)

from .fakes import (
    CUSTOMER_ID,
    QUERY_NAMES,
    TRANSACTION_ID,
    FakeFraudRepository,
    FakeQueryProvider,
    fraud_responses,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_ROOT = REPO_ROOT / "gateway/tools/transaction_fraud_detection"
QUERIES_DIR = TOOL_ROOT / "transaction_fraud_detection_lambda/queries/postgresql"
TOOL_SPEC = TOOL_ROOT / "tool_spec.json"
PLACEHOLDER = re.compile(r"%\((\w+)\)s")
SESSION_STATEMENT = re.compile(r"^\s*SET\b", re.IGNORECASE | re.MULTILINE)
# Escaped so this test file's own encoding can't change the expected value.
CREDIT_CARD_FILTER = "p.product_type = 'Tarjeta Cr\u00e9dito'"
AS_OF = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
MAPPED_COLUMNS = (
    "transaction_id",
    "transaction_date",
    "card_last4",
    "merchant_name",
    "amount",
    "currency",
    "transaction_status",
    "fraud_score",
)


def sql(name: str) -> str:
    """Load one of the real queries."""
    return FileQueryProvider(QUERIES_DIR).get(name)


def sent_params() -> dict[str, dict[str, object]]:
    """Return the params the use case actually sends, keyed by query name."""
    database_repository = FakeFraudRepository(fraud_responses())
    use_case = TransactionFraudDetectionUseCase(
        database_repository=database_repository, query_provider=FakeQueryProvider()
    )
    use_case.execute(
        FraudCheckRequest(CUSTOMER_ID, transaction_id=TRANSACTION_ID, card_last4=None),
        AS_OF,
    )
    use_case.execute(
        FraudCheckRequest(CUSTOMER_ID, transaction_id=None, card_last4="4497"), AS_OF
    )
    return dict(database_repository.calls)


def tool_spec() -> dict[str, Any]:
    """Load the single tool definition from tool_spec.json."""
    specs = json.loads(TOOL_SPEC.read_text(encoding="utf-8"))
    assert isinstance(specs, list) and len(specs) == 1
    return specs[0]


def test_every_query_is_sent() -> None:
    assert set(sent_params()) == set(QUERY_NAMES)


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_placeholders_match_the_use_case_params_exactly(name: str) -> None:
    assert set(PLACEHOLDER.findall(sql(name))) == set(sent_params()[name])


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_has_no_stray_percent_signs(name: str) -> None:
    # psycopg treats every '%' as a placeholder marker once params are passed.
    assert "%" not in PLACEHOLDER.sub("", sql(name))


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_sets_no_session_parameters(name: str) -> None:
    # DSQL rejects most session parameters (statement_timeout among them).
    text = sql(name)

    assert SESSION_STATEMENT.search(text) is None
    assert "statement_timeout" not in text.lower()


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_no_query_reads_the_outcome_label(name: str) -> None:
    # DEC-10: the label is only known after an investigation; the verdict
    # comes from the stored score alone. Comments count too.
    assert "is_fraud" not in sql(name).lower()


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_each_query_checks_the_customer_and_credit_cards(name: str) -> None:
    # Another customer's charge or card, or a debit card, must find nothing.
    text = sql(name)

    assert "customer_id = %(customer_id)s" in text
    assert CREDIT_CARD_FILTER in text


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_credit_card_literal_is_nfc_utf8_without_bom(name: str) -> None:
    # A decomposed accent or a BOM would silently match no transactions.
    raw = (QUERIES_DIR / f"{name}.sql").read_bytes()

    assert not raw.startswith(b"\xef\xbb\xbf")
    assert CREDIT_CARD_FILTER.encode("utf-8") in raw
    assert unicodedata.is_normalized("NFC", raw.decode("utf-8"))


@pytest.mark.parametrize("name", ["fraud_transaction", "fraud_card_sweep"])
def test_sql_selects_every_column_the_use_case_maps(name: str) -> None:
    text = sql(name)
    for column in MAPPED_COLUMNS:
        assert column in text, column


@pytest.mark.parametrize("name", ["fraud_transaction", "fraud_card_sweep"])
def test_sql_removes_duplicate_rows(name: str) -> None:
    assert "SELECT DISTINCT ON (t.transaction_id)" in sql(name)


def test_sweep_selects_the_count() -> None:
    assert "checked" in sql("fraud_card_sweep")


def test_sweep_keeps_the_count_when_nothing_is_flagged() -> None:
    # A one-row totals CTE, left-joined to the flagged set, returns a count-only
    # row for a clean card instead of no row at all (checked would read 0).
    text = sql("fraud_card_sweep")

    assert "SELECT COUNT(*) AS checked FROM window_tx" in text
    assert "FROM totals\nLEFT JOIN flagged AS f ON TRUE" in text


def test_sweep_flags_above_review_and_orders_by_score() -> None:
    text = sql("fraud_card_sweep")

    assert "WHERE fraud_score > %(review_above)s::numeric" in text
    assert (
        "ORDER BY fraud_score DESC, transaction_date DESC NULLS LAST, transaction_id"
        in text
    )
    # A join doesn't keep a CTE's order, so the outer select repeats it.
    assert "ORDER BY f.fraud_score DESC NULLS LAST" in text
    # The limit cuts the flagged set, never the count row.
    assert text.index("LIMIT %(limit)s") < text.index("FROM totals")


def test_sweep_window_is_thirty_days_up_to_as_of() -> None:
    text = sql("fraud_card_sweep")

    assert "t.transaction_date >= %(as_of)s - INTERVAL '30 days'" in text
    assert "t.transaction_date <= %(as_of)s" in text


def test_one_charge_is_bounded_by_as_of() -> None:
    assert "t.transaction_date <= %(as_of)s" in sql("fraud_transaction")


def test_tool_spec_name_and_required_fields() -> None:
    spec = tool_spec()

    assert spec["name"] == "transaction_fraud_detection"
    assert spec["inputSchema"]["required"] == ["customer_id"]


def test_tool_spec_properties_match_the_request_fields() -> None:
    properties = set(tool_spec()["inputSchema"]["properties"])

    assert properties == {f.name for f in dataclasses.fields(FraudCheckRequest)}


def test_tool_spec_description_names_the_verdicts_and_the_window() -> None:
    description = tool_spec()["description"]

    for word in ("fraud", "review", "no_fraud", "not_scored", "checked", "30 days"):
        assert word in description, word
```

- [ ] **Step 2: Run the test to see it fail**

Run: `$PY -m pytest tests/unit/transaction_fraud_detection/test_query_contracts.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: many failures, each with `QueryNotFoundError` or `FileNotFoundError` (no SQL files or `tool_spec.json` yet). `test_every_query_is_sent` passes, since it only uses fakes.

- [ ] **Step 3: Write `fraud_transaction.sql`**

Save as UTF-8 with no BOM and LF line endings. The `é` must be a single NFC character (U+00E9).

```sql
-- fraud_transaction (PostgreSQL dialect, runs on Aurora DSQL)
--
-- One credit-card charge of the customer, with the fraud engine's stored score.
-- Used by TransactionFraudDetectionUseCase in transaction mode.
--
-- customer_id in the WHERE is the ownership check: another customer's charge,
-- or a charge on a non-credit product, returns no row ("not found"). Credit
-- cards only, matched exactly on product_type = 'Tarjeta Crédito' (the dataset's
-- Spanish value), the filter every tool uses. transaction_date <= as_of keeps
-- the demo's "now" honest.
--
-- DEC-10: the outcome label column is never read. The verdict comes from
-- fraud_score alone, banded in Python; the score never leaves the Lambda.
--
-- Parameters (psycopg named placeholders):
--   customer_id     text       required
--   transaction_id  text       required
--   as_of           timestamp  required, naive UTC
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster. DISTINCT ON,
--   NULLS LAST and the binds are standard PostgreSQL, but DSQL support is
--   unverified. Column names follow docs/LATAM_Bank_ERD.md; smoke-test against a
--   real cluster.
-- TODO(ledgerlens): R8 - about 2 in 100 rows are duplicated; DISTINCT ON removes
--   them at query time. Drop it once the data load deduplicates.
SELECT DISTINCT ON (t.transaction_id)
       t.transaction_id, t.transaction_date,
       RIGHT(p.product_number, 4) AS card_last4,
       t.merchant_name, t.amount, t.currency, t.transaction_status,
       t.fraud_score
FROM transactions AS t
JOIN products AS p ON p.product_id = t.product_id
WHERE t.transaction_id = %(transaction_id)s
  AND t.customer_id = %(customer_id)s
  AND p.product_type = 'Tarjeta Crédito'
  AND t.transaction_date <= %(as_of)s
ORDER BY t.transaction_id, t.transaction_date DESC NULLS LAST
```

- [ ] **Step 4: Write `fraud_card_exists.sql`**

```sql
-- fraud_card_exists (PostgreSQL dialect, runs on Aurora DSQL)
--
-- Does one of the customer's credit cards end in card_last4? Used by
-- TransactionFraudDetectionUseCase before a sweep, so a mistyped last 4 gives
-- "card not found" instead of looking like a clean card.
--
-- A card in any status counts: a blocked card's charges can still be fraud.
-- Credit cards only, matched exactly on product_type = 'Tarjeta Crédito'.
--
-- Parameters (psycopg named placeholders):
--   customer_id  text  required
--   card_last4   text  required, 4 ASCII digits
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster.
--   Column names follow docs/LATAM_Bank_ERD.md; smoke-test against a real cluster.
SELECT 1 AS card_exists
FROM products AS p
WHERE p.customer_id = %(customer_id)s
  AND p.product_type = 'Tarjeta Crédito'
  AND RIGHT(p.product_number, 4) = %(card_last4)s
LIMIT 1
```

- [ ] **Step 5: Write `fraud_card_sweep.sql`**

```sql
-- fraud_card_sweep (PostgreSQL dialect, runs on Aurora DSQL)
--
-- Every charge on one of the customer's credit cards in the 30 days up to as_of,
-- one row per transaction_id. Returns the flagged ones (score above
-- review_above), highest score first, each with checked = how many charges the
-- window holds, scored or not. Used by TransactionFraudDetectionUseCase in card
-- mode.
--
-- totals always has one row, and the LEFT JOIN keeps it when nothing is
-- flagged: a clean card then returns one count-only row (NULL transaction
-- columns, real checked) instead of no row. The outer ORDER BY repeats the
-- flagged order, because a join doesn't keep a CTE's order. LIMIT cuts only
-- the flagged set.
--
-- The window filters on transaction_date, lower bound inclusive. process_date is
-- there only for partition pruning (product design section 8.1); its extra day
-- covers charges processed a day later. A card with two products ending in the
-- same 4 digits (one replaced, say) is swept across both: the customer sees one
-- last 4. Credit cards only, matched exactly on product_type = 'Tarjeta Crédito'.
--
-- DEC-10: the outcome label column is never read. The verdict comes from
-- fraud_score alone, banded in Python; the score never leaves the Lambda.
--
-- Parameters (psycopg named placeholders):
--   customer_id   text       required
--   card_last4    text       required, 4 ASCII digits
--   as_of         timestamp  required, naive UTC
--   review_above  numeric    required, the domain's REVIEW_ABOVE (30)
--   limit         integer    max flagged rows plus one (the extra row sets truncated)
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster. DISTINCT ON,
--   CTEs, LEFT JOIN ... ON TRUE, NULLS LAST and the binds are standard PostgreSQL,
--   but DSQL support and the plan under the 128 MiB per-query limit are
--   unverified. Column names follow docs/LATAM_Bank_ERD.md; smoke-test against a
--   real cluster.
-- TODO(ledgerlens): R8 - about 2 in 100 rows are duplicated; DISTINCT ON removes
--   them at query time. Drop it once the data load deduplicates.
WITH window_tx AS (
    SELECT DISTINCT ON (t.transaction_id)
           t.transaction_id, t.transaction_date,
           RIGHT(p.product_number, 4) AS card_last4,
           t.merchant_name, t.amount, t.currency, t.transaction_status,
           t.fraud_score
    FROM transactions AS t
    JOIN products AS p ON p.product_id = t.product_id
    WHERE t.customer_id = %(customer_id)s
      AND p.product_type = 'Tarjeta Crédito'
      AND RIGHT(p.product_number, 4) = %(card_last4)s
      AND t.process_date >= (%(as_of)s::date - 31)
      AND t.transaction_date >= %(as_of)s - INTERVAL '30 days'
      AND t.transaction_date <= %(as_of)s
    ORDER BY t.transaction_id, t.transaction_date DESC NULLS LAST
),
totals AS (
    SELECT COUNT(*) AS checked FROM window_tx
),
flagged AS (
    SELECT * FROM window_tx
    WHERE fraud_score > %(review_above)s::numeric
    ORDER BY fraud_score DESC, transaction_date DESC NULLS LAST, transaction_id
    LIMIT %(limit)s
)
SELECT f.transaction_id, f.transaction_date, f.card_last4, f.merchant_name,
       f.amount, f.currency, f.transaction_status, f.fraud_score, totals.checked
FROM totals
LEFT JOIN flagged AS f ON TRUE
ORDER BY f.fraud_score DESC NULLS LAST, f.transaction_date DESC NULLS LAST,
         f.transaction_id
```

The header comments contain no `%` and no line starting with `SET`; the contract tests check both.

- [ ] **Step 6: Write `tool_spec.json`**

`gateway/tools/transaction_fraud_detection/tool_spec.json`, exactly spec §5.1:

```json
[
  {
    "name": "transaction_fraud_detection",
    "description": "Checks whether a credit-card charge is fraud, using the bank's fraud engine. Give exactly one of transaction_id (checks that charge) or card_last4 (checks every charge on that card in the last 30 days and returns only the flagged ones, with 'checked' = how many were looked at). Each assessment has a verdict: 'fraud' (confirm with the customer, then block the card and open a fraud claim), 'review' (ask whether they recognize the charge; if not, offer to open a case for clarification and dispute) or 'no_fraud'. 'next_step' says what to offer. basis 'not_scored' means the engine produced no score for that charge; it isn't proof the charge is genuine. Never tell the customer a score: none is returned. Amounts are strings with 2 decimals in the charge's currency.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "customer_id": { "type": "string", "description": "The authenticated customer's ID from SESSION CONTEXT." },
        "transaction_id": { "type": "string", "description": "One charge to check, e.g. TRX-23BIJAU4GL46ATPW9STY. Leave out when giving card_last4." },
        "card_last4": { "type": "string", "description": "Last 4 digits of one of the customer's credit cards, to sweep its last 30 days. Leave out when giving transaction_id." }
      },
      "required": ["customer_id"]
    }
  }
]
```

- [ ] **Step 7: Run the test to see it pass**

Run: `$PY -m pytest tests/unit/transaction_fraud_detection/test_query_contracts.py -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: `31 passed`.

- [ ] **Step 8: Check the files and lint**

```bash
file gateway/tools/transaction_fraud_detection/transaction_fraud_detection_lambda/queries/postgresql/*.sql
$PY -m json.tool gateway/tools/transaction_fraud_detection/tool_spec.json >/dev/null </dev/null && echo json-ok
$PY -m ruff format --check gateway/tools/transaction_fraud_detection tests/unit/transaction_fraud_detection </dev/null
$PY -m ruff check gateway/tools/transaction_fraud_detection tests/unit/transaction_fraud_detection </dev/null
```

Expected: each SQL file is `Unicode text, UTF-8 text` with no `CRLF` and no `BOM`; `json-ok`; both ruff commands clean.

---

### Task 7: Presenter

**Files:**
- Create: `gateway/tools/transaction_fraud_detection/transaction_fraud_detection_lambda/delivery/presenters/fraud_assessment.py`
- Test: `tests/unit/transaction_fraud_detection/test_fraud_assessment_presenter.py`

**Interfaces:**
- Consumes: Task 5 `FraudAssessment`, `CardSweep`; Task 3 `NEXT_STEPS`, `FraudVerdict`, `ScoreBasis`.
- Produces (in `transaction_fraud_detection_lambda.delivery.presenters.fraud_assessment`):
  - `present_assessment(assessment: FraudAssessment) -> dict[str, Any]`, returning `{"mode": "transaction", "assessment": {...}}`
  - `present_sweep(sweep: CardSweep) -> dict[str, Any]`, returning `{"mode": "card", "card_last4", "date_from", "date_to", "checked", "flagged": [...], "truncated"}`

- [ ] **Step 1: Write the failing test**

`tests/unit/transaction_fraud_detection/test_fraud_assessment_presenter.py`:

```python
"""Tests for the fraud assessment presenter (spec section 5)."""

import dataclasses
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest
from transaction_fraud_detection_lambda.delivery.presenters.fraud_assessment import (
    present_assessment,
    present_sweep,
)
from transaction_fraud_detection_lambda.domain.entities.fraud_assessment import (
    CardSweep,
    FraudAssessment,
)
from transaction_fraud_detection_lambda.domain.value_objects.fraud_bands import (
    FraudVerdict,
    ScoreBasis,
)

from .fakes import TRANSACTION_ID

pytestmark = pytest.mark.unit

FRAUD_STEP = "Confirm with the customer, then block the card and open a fraud claim."
REVIEW_STEP = (
    "Ask whether they recognize the charge; if not, offer to open a case for "
    "clarification and dispute."
)
ASSESSMENT = FraudAssessment(
    transaction_id=TRANSACTION_ID,
    transaction_date=datetime(2026, 5, 31, 6, 9, 15),
    card_last4="4497",
    merchant_name="Estación de Servicio",
    amount=Decimal("288.69"),
    currency="USD",
    transaction_status="Approved",
    verdict=FraudVerdict.FRAUD,
    basis=ScoreBasis.SCORED,
)
PRESENTED = {
    "transaction_id": TRANSACTION_ID,
    "transaction_date": "2026-05-31T06:09:15",
    "card_last4": "4497",
    "merchant_name": "Estación de Servicio",
    "amount": "288.69",
    "currency": "USD",
    "transaction_status": "Approved",
    "verdict": "fraud",
    "basis": "scored",
    "next_step": FRAUD_STEP,
}
SWEEP = CardSweep(
    card_last4="4497",
    date_from=datetime(2026, 5, 18, 23, 59, 59),
    date_to=datetime(2026, 6, 17, 23, 59, 59),
    checked=3,
    flagged=(ASSESSMENT,),
    truncated=False,
)


def test_present_assessment_shape() -> None:
    assert present_assessment(ASSESSMENT) == {
        "mode": "transaction",
        "assessment": PRESENTED,
    }


def test_present_assessment_keeps_the_key_order() -> None:
    assert list(present_assessment(ASSESSMENT)["assessment"]) == list(PRESENTED)


def test_present_sweep_shape() -> None:
    assert present_sweep(SWEEP) == {
        "mode": "card",
        "card_last4": "4497",
        "date_from": "2026-05-18T23:59:59",
        "date_to": "2026-06-17T23:59:59",
        "checked": 3,
        "flagged": [PRESENTED],
        "truncated": False,
    }


def test_an_empty_sweep_has_an_empty_list() -> None:
    sweep = dataclasses.replace(SWEEP, flagged=(), checked=3)

    assert present_sweep(sweep)["flagged"] == []


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("288.685"), "288.69"),
        (Decimal("288.684"), "288.68"),
        (Decimal("10"), "10.00"),
        (Decimal("0.005"), "0.01"),
    ],
)
def test_amounts_are_two_decimal_strings_rounded_half_up(
    amount: Decimal, expected: str
) -> None:
    assessment = dataclasses.replace(ASSESSMENT, amount=amount)

    assert present_assessment(assessment)["assessment"]["amount"] == expected


def test_missing_values_stay_null() -> None:
    assessment = dataclasses.replace(
        ASSESSMENT,
        transaction_date=None,
        card_last4=None,
        merchant_name=None,
        amount=None,
        currency=None,
        transaction_status=None,
    )

    presented = present_assessment(assessment)["assessment"]

    for key in (
        "transaction_date",
        "card_last4",
        "merchant_name",
        "amount",
        "currency",
        "transaction_status",
    ):
        assert presented[key] is None, key


@pytest.mark.parametrize(
    ("verdict", "basis", "next_step"),
    [
        (FraudVerdict.FRAUD, ScoreBasis.SCORED, FRAUD_STEP),
        (FraudVerdict.REVIEW, ScoreBasis.SCORED, REVIEW_STEP),
        (FraudVerdict.NO_FRAUD, ScoreBasis.SCORED, None),
        (FraudVerdict.NO_FRAUD, ScoreBasis.NOT_SCORED, None),
    ],
)
def test_next_step_follows_the_verdict(
    verdict: FraudVerdict, basis: ScoreBasis, next_step: str | None
) -> None:
    assessment = dataclasses.replace(ASSESSMENT, verdict=verdict, basis=basis)

    presented = present_assessment(assessment)["assessment"]

    assert (presented["verdict"], presented["basis"]) == (verdict.value, basis.value)
    assert presented["next_step"] == next_step


def keys(value: Any) -> set[str]:
    """Return every dict key anywhere inside ``value``."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys(v)}
    if isinstance(value, list):
        return {k for item in value for k in keys(item)}
    return set()


@pytest.mark.parametrize(
    "presented", [present_assessment(ASSESSMENT), present_sweep(SWEEP)]
)
def test_no_score_key_anywhere(presented: dict[str, Any]) -> None:
    assert keys(presented).isdisjoint({"fraud_score", "score", "is_fraud"})


@pytest.mark.parametrize(
    "presented", [present_assessment(ASSESSMENT), present_sweep(SWEEP)]
)
def test_output_is_plain_json(presented: dict[str, Any]) -> None:
    assert json.loads(json.dumps(presented, ensure_ascii=False)) == presented
```

- [ ] **Step 2: Run the test to see it fail**

Run: `$PY -m pytest tests/unit/transaction_fraud_detection/test_fraud_assessment_presenter.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: FAIL at collection with `ModuleNotFoundError` for `presenters.fraud_assessment`.

- [ ] **Step 3: Write `delivery/presenters/fraud_assessment.py`**

```python
"""Present a fraud assessment or a card sweep as the JSON returned to the agent."""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from transaction_fraud_detection_lambda.domain.entities.fraud_assessment import (
    CardSweep,
    FraudAssessment,
)
from transaction_fraud_detection_lambda.domain.value_objects.fraud_bands import (
    NEXT_STEPS,
)

_CENTS: Final = Decimal("0.01")


def present_assessment(assessment: FraudAssessment) -> dict[str, Any]:
    """Return one charge's assessment as JSON-safe values (spec section 5).

    Amounts are 2-decimal strings rounded half up; timestamps are ISO 8601
    without a time zone, as stored. Missing values stay None. There is no score.
    """
    return {"mode": "transaction", "assessment": _assessment(assessment)}


def present_sweep(sweep: CardSweep) -> dict[str, Any]:
    """Return a card sweep as JSON-safe values: flagged charges plus the count."""
    return {
        "mode": "card",
        "card_last4": sweep.card_last4,
        "date_from": _iso(sweep.date_from),
        "date_to": _iso(sweep.date_to),
        "checked": sweep.checked,
        "flagged": [_assessment(item) for item in sweep.flagged],
        "truncated": sweep.truncated,
    }


def _assessment(assessment: FraudAssessment) -> dict[str, Any]:
    """Present one assessment with the next step its verdict calls for."""
    return {
        "transaction_id": assessment.transaction_id,
        "transaction_date": _iso(assessment.transaction_date),
        "card_last4": assessment.card_last4,
        "merchant_name": assessment.merchant_name,
        "amount": _amount(assessment.amount),
        "currency": assessment.currency,
        "transaction_status": assessment.transaction_status,
        "verdict": assessment.verdict.value,
        "basis": assessment.basis.value,
        "next_step": NEXT_STEPS[assessment.verdict],
    }


def _iso(value: datetime | None) -> str | None:
    """Return an ISO 8601 string, keeping None."""
    return None if value is None else value.isoformat()


def _amount(value: Decimal | None) -> str | None:
    """Return a 2-decimal string rounded half up, keeping None."""
    if value is None:
        return None
    return str(value.quantize(_CENTS, rounding=ROUND_HALF_UP))
```

- [ ] **Step 4: Run the test to see it pass**

Run: `$PY -m pytest tests/unit/transaction_fraud_detection/test_fraud_assessment_presenter.py -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: `17 passed`.

- [ ] **Step 5: Lint**

Same two ruff commands as Task 2 Step 5. Expected: both clean.

---

### Task 8: Dependency builder

**Files:**
- Create (copied, then renamed): `gateway/tools/transaction_fraud_detection/transaction_fraud_detection_lambda/delivery/dependencies/dependencies_builder.py`
- Test: `tests/unit/transaction_fraud_detection/test_delivery_wiring.py`

**Interfaces:**
- Consumes: Task 1 settings, connectors and adapters; Task 5 `TransactionFraudDetectionUseCase`; Task 6 SQL files; Task 1 fakes (`FakeConnector`, `make_any_row`).
- Produces (in `transaction_fraud_detection_lambda.delivery.dependencies.dependencies_builder`): `QUERIES_ROOT`, `SQL_DIALECTS`, `build_settings`, `build_dsql_settings`, `build_clock(env) -> ClockSettings | None`, `build_connector`, `build_database_repository`, `build_query_provider` (cached) and `build_transaction_fraud_detection_use_case(env) -> TransactionFraudDetectionUseCase | None`.

- [ ] **Step 1: Write the failing test**

`tests/unit/transaction_fraud_detection/test_delivery_wiring.py`:

```python
"""Tests for the dependency wiring of the transaction_fraud_detection tool."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import transaction_fraud_detection_lambda.utils.connectors.dsql as dsql_module
from transaction_fraud_detection_lambda.application.ports.errors import (
    DataSourceConnectionError,
)
from transaction_fraud_detection_lambda.application.use_cases.transaction_fraud_detection import (  # noqa: E501
    TransactionFraudDetectionUseCase,
)
from transaction_fraud_detection_lambda.delivery.dependencies import (
    dependencies_builder,
)
from transaction_fraud_detection_lambda.delivery.dependencies.dependencies_builder import (  # noqa: E501
    QUERIES_ROOT,
    SQL_DIALECTS,
    build_clock,
    build_connector,
    build_database_repository,
    build_dsql_settings,
    build_query_provider,
    build_settings,
    build_transaction_fraud_detection_use_case,
)
from transaction_fraud_detection_lambda.delivery.settings import (
    ClockSettings,
    ConfigurationError,
    DatabaseEngine,
    DatabaseSettings,
    DsqlSettings,
)
from transaction_fraud_detection_lambda.domain.entities.fraud_assessment import (
    CardSweep,
    FraudAssessment,
)
from transaction_fraud_detection_lambda.domain.value_objects.fraud_bands import (
    FraudVerdict,
)
from transaction_fraud_detection_lambda.domain.value_objects.fraud_check_request import (  # noqa: E501
    FraudCheckRequest,
)
from transaction_fraud_detection_lambda.infrastructure.repositories.dsql_repository import (  # noqa: E501
    DsqlRepository,
)
from transaction_fraud_detection_lambda.utils.connectors.dsql import DsqlConnector

from .fakes import (
    CUSTOMER_ID,
    QUERY_NAMES,
    TRANSACTION_ID,
    FakeConnector,
    make_any_row,
)

pytestmark = pytest.mark.unit

ENDPOINT = "abc123.dsql.us-east-1.on.aws"
ENV = {"DSQL_CLUSTER_ENDPOINT": ENDPOINT, "AWS_REGION": "us-east-1"}
SETTINGS = DatabaseSettings(engine=DatabaseEngine.AURORA_DSQL, max_rows=25)
AS_OF = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
# What the SQL receives: the same instant as naive UTC.
AS_OF_SQL = datetime(2026, 6, 17, 23, 59, 59)
TX_REQUEST = FraudCheckRequest(CUSTOMER_ID, transaction_id=TRANSACTION_ID, card_last4=None)
CARD_REQUEST = FraudCheckRequest(CUSTOMER_ID, transaction_id=None, card_last4="4497")


def test_build_settings_reads_the_environment() -> None:
    assert build_settings(ENV) == SETTINGS


def test_build_dsql_settings_reads_the_environment() -> None:
    assert build_dsql_settings(ENV) == DsqlSettings(
        cluster_endpoint=ENDPOINT, region="us-east-1", db_user="ll_read"
    )


def test_build_clock_reads_as_of() -> None:
    assert build_clock({"AS_OF": "2026-06-17T23:59:59"}) == ClockSettings(
        as_of=AS_OF
    )


def test_build_clock_without_as_of_uses_the_real_clock() -> None:
    assert build_clock({}) == ClockSettings(as_of=None)


def test_build_clock_with_a_bad_as_of_returns_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert build_clock({"AS_OF": "yesterday"}) is None
    assert "Invalid AS_OF for transaction_fraud_detection" in caplog.text


def test_build_connector_returns_a_dsql_connector_without_touching_aws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_boto3(*args: object, **kwargs: object) -> object:
        raise AssertionError("boto3 client created while building the connector")

    monkeypatch.setattr(dsql_module.boto3, "client", no_boto3)

    assert isinstance(build_connector(SETTINGS, ENV), DsqlConnector)


def test_build_connector_reads_the_dsql_settings() -> None:
    with pytest.raises(ConfigurationError, match="DSQL_CLUSTER_ENDPOINT"):
        build_connector(SETTINGS, {"AWS_REGION": "us-east-1"})


def test_aurora_dsql_runs_the_postgresql_sql_dialect() -> None:
    assert SQL_DIALECTS == {DatabaseEngine.AURORA_DSQL: "postgresql"}
    provider = build_query_provider(DatabaseEngine.AURORA_DSQL)

    assert provider is build_query_provider(DatabaseEngine.AURORA_DSQL)
    assert "DISTINCT ON" in provider.get("fraud_transaction")


def test_every_engine_has_a_dialect_folder_with_every_query() -> None:
    for engine in DatabaseEngine:
        for name in QUERY_NAMES:
            assert (QUERIES_ROOT / SQL_DIALECTS[engine] / f"{name}.sql").is_file()


def test_queries_root_is_this_tools_own_folder() -> None:
    assert QUERIES_ROOT.parent.name == "transaction_fraud_detection_lambda"


def test_build_query_provider_rejects_an_engine_without_a_dialect() -> None:
    with pytest.raises(ConfigurationError):
        build_query_provider("oracle")  # type: ignore[arg-type]


def test_build_database_repository_wraps_the_connector_for_the_engine() -> None:
    database_repository = build_database_repository(
        DatabaseEngine.AURORA_DSQL, FakeConnector()
    )

    assert isinstance(database_repository, DsqlRepository)


def test_build_database_repository_rejects_an_unknown_engine() -> None:
    with pytest.raises(ConfigurationError):
        build_database_repository("oracle", FakeConnector())  # type: ignore[arg-type]


def use_fake_connector(
    monkeypatch: pytest.MonkeyPatch, connector: FakeConnector
) -> None:
    """Make the builder hand out ``connector`` instead of a real DSQL one."""
    monkeypatch.setattr(
        dependencies_builder, "build_connector", lambda _settings, _env: connector
    )


def executed(connector: FakeConnector) -> list[tuple[str, dict[str, object]]]:
    """Return (sql, params) of every query, in order, on the last connection."""
    return [
        (sql, dict(params))
        for cursor in connector.connections[-1].cursors
        for sql, params in cursor.executed
    ]


def test_one_charge_is_wired_with_real_adapters_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector([make_any_row()])
    use_fake_connector(monkeypatch, connector)

    use_case = build_transaction_fraud_detection_use_case(ENV)
    assert isinstance(use_case, TransactionFraudDetectionUseCase)
    result = use_case.execute(TX_REQUEST, as_of=AS_OF)

    assert isinstance(result, FraudAssessment)
    assert result.verdict is FraudVerdict.FRAUD
    queries = executed(connector)
    assert len(queries) == 1
    assert "FROM transactions AS t" in queries[0][0]
    assert queries[0][1] == {
        "customer_id": CUSTOMER_ID,
        "transaction_id": TRANSACTION_ID,
        "as_of": AS_OF_SQL,
    }


def test_card_sweep_is_wired_with_real_adapters_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector([make_any_row()])
    use_fake_connector(monkeypatch, connector)

    use_case = build_transaction_fraud_detection_use_case(ENV)
    assert use_case is not None
    result = use_case.execute(CARD_REQUEST, as_of=AS_OF)

    assert isinstance(result, CardSweep)
    assert (result.checked, len(result.flagged)) == (3, 1)
    queries = executed(connector)
    assert len(queries) == 2
    assert "SELECT 1 AS card_exists" in queries[0][0]
    assert "WITH window_tx AS" in queries[1][0]
    assert queries[1][1] == {
        "customer_id": CUSTOMER_ID,
        "card_last4": "4497",
        "as_of": AS_OF_SQL,
        "review_above": Decimal("30"),
        "limit": 26,
    }


def test_use_case_uses_max_rows_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector([make_any_row() for _ in range(4)])
    use_fake_connector(monkeypatch, connector)

    use_case = build_transaction_fraud_detection_use_case({**ENV, "MAX_ROWS": "3"})
    assert use_case is not None
    result = use_case.execute(CARD_REQUEST, as_of=AS_OF)

    assert isinstance(result, CardSweep)
    assert (len(result.flagged), result.truncated) == (3, True)
    assert executed(connector)[1][1]["limit"] == 4


def test_use_case_build_opens_the_connection_eagerly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector()
    use_fake_connector(monkeypatch, connector)

    build_transaction_fraud_detection_use_case(ENV)

    assert len(connector.connections) == 1


def test_use_case_build_survives_a_failed_cold_start_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector(
        DataSourceConnectionError("no route to host"), [make_any_row()]
    )
    use_fake_connector(monkeypatch, connector)

    use_case = build_transaction_fraud_detection_use_case(ENV)

    assert use_case is not None
    assert isinstance(use_case.execute(CARD_REQUEST, as_of=AS_OF), CardSweep)


@pytest.mark.parametrize(
    "env",
    [
        {},
        {**ENV, "DB_ENGINE": "oracle"},
        {**ENV, "DB_ENGINE": "postgresql"},
        {"AWS_REGION": "us-east-1"},
        {"DSQL_CLUSTER_ENDPOINT": ENDPOINT},
        {**ENV, "DSQL_CLUSTER_ENDPOINT": f"https://{ENDPOINT}"},
    ],
)
def test_use_case_build_with_bad_configuration_returns_none(
    env: dict[str, str],
) -> None:
    assert build_transaction_fraud_detection_use_case(env) is None
```

- [ ] **Step 2: Run the test to see it fail**

Run: `$PY -m pytest tests/unit/transaction_fraud_detection/test_delivery_wiring.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: FAIL at collection with `ModuleNotFoundError` for `dependencies_builder`.

- [ ] **Step 3: Copy and rename the builder**

```bash
sed -e 's/get_session_context/transaction_fraud_detection/g' \
    -e 's/GetSessionContextUseCase/TransactionFraudDetectionUseCase/g' \
  gateway/tools/get_session_context/get_session_context_lambda/delivery/dependencies/dependencies_builder.py \
  > gateway/tools/transaction_fraud_detection/transaction_fraud_detection_lambda/delivery/dependencies/dependencies_builder.py
grep -n "transaction_fraud_detection\|TransactionFraudDetection" gateway/tools/transaction_fraud_detection/transaction_fraud_detection_lambda/delivery/dependencies/dependencies_builder.py
```

Expected: the grep shows the import `from transaction_fraud_detection_lambda.application.use_cases.transaction_fraud_detection import (`, the class `TransactionFraudDetectionUseCase` (import, return annotation, constructor call), `def build_transaction_fraud_detection_use_case(`, and the two log texts `Invalid AS_OF for transaction_fraud_detection` and `Invalid database configuration for transaction_fraud_detection`. The constructor call keeps `database_repository=`, `query_provider=` and `max_rows=settings.max_rows`, which match Task 5's signature.

The renamed import lines may now pass 88 characters. Run `$PY -m ruff format` on the file; if `ruff check` still reports E501 on an import line, add `  # noqa: E501` to that line, as the other tools do.

- [ ] **Step 4: Run the test to see it pass**

Run: `$PY -m pytest tests/unit/transaction_fraud_detection/test_delivery_wiring.py -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: `24 passed`.

- [ ] **Step 5: Lint**

Same two ruff commands as Task 2 Step 5. Expected: both clean.

---

### Task 9: Handler

**Files:**
- Create: `gateway/tools/transaction_fraud_detection/transaction_fraud_detection_lambda/delivery/handler.py`
- Test: `tests/unit/transaction_fraud_detection/test_transaction_fraud_detection_handler.py`

**Interfaces:**
- Consumes: Task 8 `build_transaction_fraud_detection_use_case`, `build_clock`, `build_database_repository`, `build_query_provider`; Task 7 `present_assessment`, `present_sweep`; Task 5 `CardSweep`, `TransactionFraudDetectionUseCase`; Task 4 `FraudCheckRequest`; Task 2 errors.
- Produces: `handler(event: object, context: object) -> dict[str, Any]`, plus the module globals `TOOL_NAME`, `UNEXPECTED_ERROR_MESSAGE`, `USE_CASE` and `CLOCK`.

- [ ] **Step 1: Write the failing test**

`tests/unit/transaction_fraud_detection/test_transaction_fraud_detection_handler.py`:

```python
"""Tests for the transaction_fraud_detection Lambda handler."""

import importlib
import json
import logging
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from typing import Any

import psycopg
import pytest
from transaction_fraud_detection_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryExecutionError,
)
from transaction_fraud_detection_lambda.application.use_cases.transaction_fraud_detection import (  # noqa: E501
    TransactionFraudDetectionUseCase,
)
from transaction_fraud_detection_lambda.delivery.dependencies.dependencies_builder import (  # noqa: E501
    build_database_repository,
    build_query_provider,
)
from transaction_fraud_detection_lambda.delivery.settings import (
    ClockSettings,
    DatabaseEngine,
)
from transaction_fraud_detection_lambda.domain.errors import (
    CardNotFoundError,
    DataSourceUnavailableError,
    FraudCheckDataIntegrityError,
    FraudCheckLookupError,
    TransactionNotFoundError,
)

from .fakes import (
    CUSTOMER_ID,
    SCORE,
    TRANSACTION_ID,
    FakeConnector,
    FakeFraudRepository,
    FakeQueryProvider,
    Outcome,
    fraud_responses,
    make_any_row,
    make_transaction_row,
)

pytestmark = pytest.mark.unit

TX_EVENT = {"customer_id": CUSTOMER_ID, "transaction_id": TRANSACTION_ID}
CARD_EVENT = {"customer_id": CUSTOMER_ID, "card_last4": "4497"}
AS_OF = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
# What the SQL receives: the same instant as naive UTC.
AS_OF_SQL = datetime(2026, 6, 17, 23, 59, 59)
SUFFIX = " Ask the customer to confirm and retry."


def make_context(
    tool_name: str = "target___transaction_fraud_detection",
) -> SimpleNamespace:
    """Build a Lambda context carrying the Gateway tool name."""
    return SimpleNamespace(
        client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": tool_name})
    )


@pytest.fixture
def module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Import the handler module fresh, with no DB env vars (no AWS calls)."""
    for name in (
        "DB_ENGINE",
        "MAX_ROWS",
        "DSQL_CLUSTER_ENDPOINT",
        "DSQL_DB_USER",
        "AWS_REGION",
        "AS_OF",
    ):
        monkeypatch.delenv(name, raising=False)
    import transaction_fraud_detection_lambda.delivery.handler as handler_module

    return importlib.reload(handler_module)


def wire(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, Outcome] | None = None,
) -> FakeFraudRepository:
    """Point the handler at a use case over a fake repository and a fixed clock."""
    database_repository = FakeFraudRepository(
        fraud_responses() if responses is None else responses
    )
    use_case = TransactionFraudDetectionUseCase(
        database_repository=database_repository, query_provider=FakeQueryProvider()
    )
    monkeypatch.setattr(module, "USE_CASE", use_case)
    monkeypatch.setattr(module, "CLOCK", ClockSettings(as_of=AS_OF))
    return database_repository


def wire_connector(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, connector: Any
) -> None:
    """Point the handler at real adapters over a fake connector and a fixed clock."""
    use_case = TransactionFraudDetectionUseCase(
        database_repository=build_database_repository(
            DatabaseEngine.AURORA_DSQL, connector
        ),
        query_provider=build_query_provider(DatabaseEngine.AURORA_DSQL),
    )
    monkeypatch.setattr(module, "USE_CASE", use_case)
    monkeypatch.setattr(module, "CLOCK", ClockSettings(as_of=AS_OF))


def body(response: dict[str, Any]) -> dict[str, Any]:
    """Decode the JSON text of a success response."""
    content = response["content"]
    assert content[0]["type"] == "text"
    return json.loads(content[0]["text"])


def test_transaction_mode_returns_the_assessment(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch)

    payload = body(module.handler(TX_EVENT, make_context()))

    assert payload["mode"] == "transaction"
    assert payload["assessment"]["transaction_id"] == TRANSACTION_ID
    assert payload["assessment"]["merchant_name"] == "Estación de Servicio"
    assert payload["assessment"]["verdict"] == "fraud"
    assert payload["assessment"]["basis"] == "scored"


def test_card_mode_returns_the_sweep(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch)

    payload = body(module.handler(CARD_EVENT, make_context()))

    assert payload["mode"] == "card"
    assert payload["checked"] == 3
    assert payload["date_to"] == "2026-06-17T23:59:59"
    assert [item["verdict"] for item in payload["flagged"]] == ["fraud"]
    assert payload["truncated"] is False


def test_the_text_keeps_accents_unescaped(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch)

    response = module.handler(TX_EVENT, make_context())

    assert "Estación" in response["content"][0]["text"]


def test_success_over_real_adapters(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire_connector(module, monkeypatch, FakeConnector([make_any_row()]))

    payload = body(module.handler(CARD_EVENT, make_context()))

    assert (payload["checked"], len(payload["flagged"])) == (3, 1)


def test_now_is_read_on_every_call(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_repository = wire(module, monkeypatch)
    times = iter(
        [
            datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc),
            datetime(2026, 6, 18, 8, 30, tzinfo=timezone.utc),
        ]
    )
    monkeypatch.setattr(module, "CLOCK", SimpleNamespace(now=lambda: next(times)))

    module.handler(TX_EVENT, make_context())
    module.handler(TX_EVENT, make_context())

    sent = [params["as_of"] for _name, params in database_repository.calls]
    assert sent == [AS_OF_SQL, datetime(2026, 6, 18, 8, 30)]


@pytest.mark.parametrize(
    ("event", "message"),
    [
        (
            None,
            "Invalid value for 'customer_id': is required and must be a "
            "non-empty string." + SUFFIX,
        ),
        (
            {"customer_id": CUSTOMER_ID},
            "Invalid value for 'transaction_id': give either transaction_id "
            "(one charge) or card_last4 (sweep of that card's last 30 days)."
            + SUFFIX,
        ),
        (
            {**TX_EVENT, "card_last4": "4497"},
            "Invalid value for 'transaction_id': give either transaction_id or "
            "card_last4, not both." + SUFFIX,
        ),
        (
            {"customer_id": CUSTOMER_ID, "card_last4": "449"},
            "Invalid value for 'card_last4': must be exactly 4 digits." + SUFFIX,
        ),
    ],
)
def test_invalid_input_returns_its_message_without_a_query(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    event: object,
    message: str,
) -> None:
    database_repository = wire(module, monkeypatch)

    assert module.handler(event, make_context()) == {"error": message}
    assert database_repository.calls == []


@pytest.mark.parametrize(
    ("event", "responses", "message"),
    [
        (TX_EVENT, fraud_responses(fraud_transaction=[]),
         TransactionNotFoundError.MESSAGE),
        (CARD_EVENT, fraud_responses(fraud_card_exists=[]),
         CardNotFoundError.MESSAGE),
        (TX_EVENT, fraud_responses(fraud_transaction=DataSourceConnectionError("down")),
         DataSourceUnavailableError.MESSAGE),
        (CARD_EVENT, fraud_responses(fraud_card_sweep=QueryExecutionError("boom")),
         FraudCheckLookupError.MESSAGE),
        (TX_EVENT,
         fraud_responses(fraud_transaction=[make_transaction_row(fraud_score="x")]),
         FraudCheckDataIntegrityError.MESSAGE),
    ],
    ids=["tx-not-found", "card-not-found", "unavailable", "lookup", "integrity"],
)
def test_a_domain_error_returns_its_message(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    event: dict[str, Any],
    responses: dict[str, Outcome],
    message: str,
) -> None:
    wire(module, monkeypatch, responses)

    assert module.handler(event, make_context()) == {"error": message}


def test_query_failure_over_real_adapters_returns_the_lookup_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = psycopg.errors.UndefinedTable('relation "transactions" does not exist')
    wire_connector(module, monkeypatch, FakeConnector(error))

    response = module.handler(TX_EVENT, make_context())

    assert response == {"error": FraudCheckLookupError.MESSAGE}


@pytest.mark.parametrize(
    "context",
    [
        make_context("other-target___text_analysis_tool"),
        make_context("target___list_card_transactions"),
        None,
        SimpleNamespace(client_context=None),
        SimpleNamespace(client_context=SimpleNamespace(custom={})),
        SimpleNamespace(client_context=SimpleNamespace(custom=None)),
    ],
)
def test_wrong_or_missing_tool_name_returns_an_error(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, context: object
) -> None:
    database_repository = wire(module, monkeypatch)

    response = module.handler(TX_EVENT, context)

    assert set(response) == {"error"}
    assert "transaction_fraud_detection" in response["error"]
    assert database_repository.calls == []


def test_tool_name_without_a_target_prefix_is_accepted(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch)

    response = module.handler(TX_EVENT, make_context("transaction_fraud_detection"))

    assert "content" in response


def test_unexpected_exception_returns_a_generic_message_without_internals(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("password=hunter2 host=db.internal")

    monkeypatch.setattr(module, "USE_CASE", SimpleNamespace(execute=explode))
    monkeypatch.setattr(module, "CLOCK", ClockSettings(as_of=AS_OF))

    response = module.handler(TX_EVENT, make_context())

    assert response == {"error": module.UNEXPECTED_ERROR_MESSAGE}
    assert module.UNEXPECTED_ERROR_MESSAGE == (
        "Unexpected internal error running the fraud check. "
        "Offer a hand-off to a human agent."
    )
    assert "hunter2" not in response["error"]


def test_missing_configuration_returns_data_source_unavailable(
    module: ModuleType,
) -> None:
    assert module.USE_CASE is None

    response = module.handler(TX_EVENT, make_context())

    assert response == {"error": DataSourceUnavailableError.MESSAGE}


def test_missing_clock_returns_data_source_unavailable(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_repository = wire(module, monkeypatch)
    monkeypatch.setattr(module, "CLOCK", None)

    response = module.handler(TX_EVENT, make_context())

    assert response == {"error": DataSourceUnavailableError.MESSAGE}
    assert database_repository.calls == []


def test_default_environment_uses_the_real_clock(module: ModuleType) -> None:
    assert module.CLOCK == ClockSettings(as_of=None)


def test_a_bad_as_of_env_var_leaves_the_clock_unset(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AS_OF", "yesterday")

    assert importlib.reload(module).CLOCK is None


def test_cold_start_failure_then_failed_retry_returns_unavailable(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire_connector(
        module, monkeypatch, FakeConnector(DataSourceConnectionError("down"))
    )

    response = module.handler(TX_EVENT, make_context())

    assert response == {"error": DataSourceUnavailableError.MESSAGE}


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (TX_EVENT, "transaction_fraud_detection mode=transaction "
                   "verdict_counts={'fraud': 1}"),
        (CARD_EVENT, "transaction_fraud_detection mode=card "
                     "verdict_counts={'fraud': 1}"),
    ],
)
def test_success_log_names_the_verdicts_but_no_customer_data_or_score(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    event: dict[str, Any],
    expected: str,
) -> None:
    wire(module, monkeypatch)
    caplog.set_level(logging.INFO)

    module.handler(event, make_context())

    assert expected in caplog.text
    assert CUSTOMER_ID not in caplog.text
    assert str(SCORE) not in caplog.text
    assert "Estaci" not in caplog.text


def test_a_clean_sweep_logs_empty_counts(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    wire(module, monkeypatch, fraud_responses(fraud_card_sweep=[]))
    caplog.set_level(logging.INFO)

    module.handler(CARD_EVENT, make_context())

    assert "transaction_fraud_detection mode=card verdict_counts={}" in caplog.text
```

`ruff format` will rewrap the parametrize lists; let it.

- [ ] **Step 2: Run the test to see it fail**

Run: `$PY -m pytest tests/unit/transaction_fraud_detection/test_transaction_fraud_detection_handler.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: every test errors in the `module` fixture with `ModuleNotFoundError: No module named 'transaction_fraud_detection_lambda.delivery.handler'`.

- [ ] **Step 3: Write `delivery/handler.py`**

```python
"""Lambda handler for the ``transaction_fraud_detection`` Gateway tool.

Handler string: ``transaction_fraud_detection_lambda/delivery/handler.handler``.

Input: the tool arguments as the event (see
``gateway/tools/transaction_fraud_detection/tool_spec.json``); the tool name
arrives in ``context.client_context.custom["bedrockAgentCoreToolName"]`` with a
``<target>___`` prefix, as in ``gateway/tools/sample_tool``. The event is
validated by FraudCheckRequest.from_raw before any query runs.

Output: ``{"content": [{"type": "text", "text": <JSON>}]}`` on success, or
``{"error": <agent-facing message>}``. Raw exception text is never returned: it
could leak SQL, hosts or driver details to the model. The score is never
returned or logged; the log line carries only the mode and verdict counts.

The use case and its whole graph (settings, connector, connection, adapters) are
built once, when the module loads, by dependencies_builder; a warm container
reuses them. The handler builds nothing itself.

AS_OF (optional) is read once into CLOCK; "now" is CLOCK.now() on every call,
so a warm container never freezes the real clock. An invalid AS_OF answers every
request with DataSourceUnavailableError's message.

TODO(ledgerlens): R1 - deployed alone by infra-cdk/lib/data-construct.ts to test
  it against the database; the Gateway target that lets the agent call it comes
  with the agent stack.
TODO(ledgerlens): R5 - customer_id is trusted from the tool input. Authorization
  depends on a Cedar policy matching it to the token's customer_id claim; neither
  the policy nor the claim exists yet (product design sections 5 and 10).
"""

import json
import logging
import os
from collections import Counter
from typing import Any, Final

from transaction_fraud_detection_lambda.delivery.dependencies.dependencies_builder import (  # noqa: E501
    build_clock,
    build_transaction_fraud_detection_use_case,
)
from transaction_fraud_detection_lambda.delivery.presenters.fraud_assessment import (
    present_assessment,
    present_sweep,
)
from transaction_fraud_detection_lambda.domain.entities.fraud_assessment import (
    CardSweep,
)
from transaction_fraud_detection_lambda.domain.errors import (
    DataSourceUnavailableError,
    DomainError,
)
from transaction_fraud_detection_lambda.domain.value_objects.fraud_check_request import (  # noqa: E501
    FraudCheckRequest,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TOOL_NAME: Final = "transaction_fraud_detection"
_TOOL_NAME_DELIMITER: Final = "___"
UNEXPECTED_ERROR_MESSAGE: Final = (
    "Unexpected internal error running the fraud check. "
    "Offer a hand-off to a human agent."
)
_WRONG_TOOL_MESSAGE: Final = (
    f"This function only serves the '{TOOL_NAME}' tool. "
    "Don't retry; offer a hand-off to a human agent."
)


USE_CASE = build_transaction_fraud_detection_use_case(os.environ)
CLOCK = build_clock(os.environ)


def handler(event: object, context: object) -> dict[str, Any]:
    """Check one charge, or sweep one card, for fraud.

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

    try:
        if USE_CASE is None or CLOCK is None:
            raise DataSourceUnavailableError()
        request = FraudCheckRequest.from_raw(event)
        result = USE_CASE.execute(request, as_of=CLOCK.now())
        body = (
            present_sweep(result)
            if isinstance(result, CardSweep)
            else present_assessment(result)
        )
    except DomainError as err:
        logger.warning(
            "%s returned an error: %s", TOOL_NAME, err.message, exc_info=True
        )
        return {"error": err.message}
    except Exception:
        logger.exception("Unexpected error in %s", TOOL_NAME)
        return {"error": UNEXPECTED_ERROR_MESSAGE}

    logger.info(
        "%s mode=%s verdict_counts=%s",
        TOOL_NAME,
        body["mode"],
        _verdict_counts(body),
    )
    return {"content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]}


def _verdict_counts(body: dict[str, Any]) -> dict[str, int]:
    """Count the verdicts in a presented body, sorted by verdict."""
    if body["mode"] == "card":
        verdicts = [item["verdict"] for item in body["flagged"]]
    else:
        verdicts = [body["assessment"]["verdict"]]
    return dict(sorted(Counter(verdicts).items()))


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

- [ ] **Step 4: Run the test to see it pass**

Run: `$PY -m pytest tests/unit/transaction_fraud_detection/test_transaction_fraud_detection_handler.py -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: `31 passed`.

- [ ] **Step 5: Run the tool's whole test folder, check isolation, lint**

```bash
$PY -m pytest tests/unit/transaction_fraud_detection -q -p no:cacheprovider </dev/null 2>&1 | tail -1
grep -rn "get_session_context\|list_credit_cards_lambda\|list_card_transactions_lambda" gateway/tools/transaction_fraud_detection tests/unit/transaction_fraud_detection
$PY -m ruff format --check gateway/tools/transaction_fraud_detection tests/unit/transaction_fraud_detection </dev/null
$PY -m ruff check gateway/tools/transaction_fraud_detection tests/unit/transaction_fraud_detection </dev/null
```

Expected: all pass, 0 failed; the grep prints nothing (the names `list_card_transactions` and `list_credit_cards` only appear inside error-message text and comments, never as an import of `*_lambda`); both ruff commands clean.

---

### Task 10: CDK

**Files:**
- Modify: `infra-cdk/lib/data-construct.ts` (the `tools` array, near line 216)
- Modify: `infra-cdk/test/data-construct.test.ts` (line 65 and the `test.each` near line 86)

**Interfaces:**
- Consumes: the tool folder from Tasks 1–9 (the `PythonFunction` loop bundles `gateway/tools/<tool>/` and uses the handler `<tool>_lambda.delivery.handler.handler`).
- Produces: the CDK function `ledgerlens-transaction-fraud-detection`, deployed in Task 12.

- [ ] **Step 1: Change the test first**

In `infra-cdk/test/data-construct.test.ts`, change:

```ts
  expect(vpcFns).toHaveLength(4) // the read check and the three tools
```

to:

```ts
  expect(vpcFns).toHaveLength(5) // the read check and the four tools
```

and add a row to the `test.each` table, after the `get_session_context` row:

```ts
  ["transaction_fraud_detection", "ledgerlens-transaction-fraud-detection"],
```

- [ ] **Step 2: Run the CDK test to see it fail**

Run: `cd infra-cdk && npx jest test/data-construct.test.ts 2>&1 | tail -15; cd ..`
Expected: 2 failures: the VPC count test (expected 5, received 4), and the new `transaction_fraud_detection runs in the VPC...` row (no function named `ledgerlens-transaction-fraud-detection`).

- [ ] **Step 3: Add the tool to the stack**

In `infra-cdk/lib/data-construct.ts`, add one entry to the `tools` array, after `get_session_context`:

```ts
      { tool: "transaction_fraud_detection", id: "TransactionFraudDetection" },
```

The loop already sets the function name, VPC, role, `DSQL_CLUSTER_ENDPOINT`, `AS_OF` and the log group.

- [ ] **Step 4: Run the CDK tests to see them pass**

Run: `cd infra-cdk && npx jest 2>&1 | tail -6; cd ..`
Expected: every test suite passes, 0 failed.

- [ ] **Step 5: Show the diff**

Run: `git diff --stat -- infra-cdk`
Expected: exactly `infra-cdk/lib/data-construct.ts` and `infra-cdk/test/data-construct.test.ts` changed. `infra-cdk/config.yaml` must not appear; if it does, it was already modified before this plan and must still never be staged.

---

### Task 11: Product design doc and the full suite

**Files:**
- Modify: `docs/LEDGERLENS_PRODUCT_DESIGN.md` §7.6 (CRLF line endings)

**Interfaces:**
- Consumes: the final output shapes (Task 7), bands (Task 3) and `tool_spec.json` description (Task 6).
- Produces: documentation only.

- [ ] **Step 1: Replace §7.6, keeping CRLF**

Save this script to the scratchpad as `fix_7_6.py` and run it with `$PY fix_7_6.py </dev/null`. It replaces everything from the `### 7.6` heading up to (not including) the existing `` > `transactions.is_fraud` `` note, which stays.

```python
"""Replace product design section 7.6 with the transaction_fraud_detection design."""

import json
from pathlib import Path

DOC = Path("docs/LEDGERLENS_PRODUCT_DESIGN.md")
SPEC = Path("gateway/tools/transaction_fraud_detection/tool_spec.json")

description = json.loads(SPEC.read_text(encoding="utf-8"))[0]["description"]
NEW = [
    "### 7.6 `transaction_fraud_detection` (A2)",
    "",
    "**Spec:** [2026-10-03-transaction-fraud-detection-lambda-design.md]"
    "(superpowers/specs/2026-10-03-transaction-fraud-detection-lambda-design.md)",
    "",
    f'**tool_spec description:** "{description}"',
    "",
    "**Input:** `customer_id`, and exactly one of `transaction_id` (one charge) or "
    "`card_last4` (sweep of that card's last 30 days). The Lambda checks the "
    '"exactly one".',
    "",
    "**Output** (one charge)",
    "```json",
    '{ "mode": "transaction", "assessment": { "transaction_id": '
    '"TRX-23BIJAU4GL46ATPW9STY", "transaction_date": "2026-05-31T06:09:15", '
    '"card_last4": "4497", "merchant_name": "Estación de Servicio", "amount": '
    '"288.69", "currency": "USD", "transaction_status": "Approved", "verdict": '
    '"fraud", "basis": "scored", "next_step": "Confirm with the customer, then '
    'block the card and open a fraud claim." } }',
    "```",
    "",
    "**Output** (card sweep: flagged charges only, plus how many were checked)",
    "```json",
    '{ "mode": "card", "card_last4": "4497", "date_from": "2026-05-18T23:59:59", '
    '"date_to": "2026-06-17T23:59:59", "checked": 3, "flagged": [ "...same shape '
    'as assessment..." ], "truncated": false }',
    "```",
    "",
    "**Logic (in the Lambda, from the stored `fraud_score` only)**",
    "",
    "| `fraud_score` | Verdict | `basis` |",
    "|---|---|---|",
    "| above 50 | fraud | scored |",
    "| above 30, up to 50 | review | scored |",
    "| 30 or below | no_fraud | scored |",
    "| NULL | no_fraud | not_scored |",
    "",
    "> `fraud_score` is 0–100 (`numeric(5,2)`), treated as a simulated "
    "fraud-engine feed; the bands come from the 2026-10-03 profiling. The earlier "
    "0.7 / 0.4 thresholds assumed a 0–1 scale and were wrong. The location and "
    "habit conditions are dropped: the verdict uses the stored score only (user "
    "decision, 2026-10-03). The raw score is never returned.",
    "",
]

raw = DOC.read_bytes().decode("utf-8")
assert raw.count("\n") == raw.count("\r\n"), "expected CRLF only"
lines = raw.split("\r\n")
start = lines.index("### 7.6 `transaction_fraud_detection` (A2)")
end = next(
    i for i in range(start, len(lines)) if lines[i].startswith("> `transactions.is_fraud`")
)
lines[start:end] = NEW
DOC.write_bytes("\r\n".join(lines).encode("utf-8"))
print(f"replaced lines {start + 1}-{end} with {len(NEW)} lines")
```

Expected: one line `replaced lines 578-599 with 36 lines` (the start line is 578; the exact end may differ by a line or two).

- [ ] **Step 2: Check the section and the line endings**

```bash
sed -n '/^### 7.6/,/^### 7.7/p' docs/LEDGERLENS_PRODUCT_DESIGN.md | tr -d '\r'
file docs/LEDGERLENS_PRODUCT_DESIGN.md
git diff --stat -- docs/LEDGERLENS_PRODUCT_DESIGN.md
```

Expected: the section shows the new text followed by the kept `` > `transactions.is_fraud` `` note and `---`; `file` still says `with CRLF line terminators`; the diff touches only this file, with only §7.6's lines changed (not the whole file).

- [ ] **Step 3: Run the whole suite**

Run the suite command from Global Constraints.
Expected: `N passed, 1 deselected`, where N is 876 plus every test in `tests/unit/transaction_fraud_detection/`, and 0 failed.

- [ ] **Step 4: Lint the whole tool**

```bash
$PY -m ruff format --check gateway/tools/transaction_fraud_detection tests/unit/transaction_fraud_detection </dev/null
$PY -m ruff check gateway/tools/transaction_fraud_detection tests/unit/transaction_fraud_detection </dev/null
git status --short
```

Expected: both ruff commands clean. `git status` lists only this plan's files: the new `gateway/tools/transaction_fraud_detection/` and `tests/unit/transaction_fraud_detection/` folders, the two `infra-cdk` files, `docs/LEDGERLENS_PRODUCT_DESIGN.md`, plus the spec and this plan. Nothing is staged.

---

### Task 12: Deploy and acceptance (needs the user's go-ahead)

**Stop here.** Tell the user Tasks 1–11 are done, with the suite and CDK test results, and ask for an explicit go-ahead to deploy. Deploying changes the real AWS account. Don't run any step below without that go-ahead.

**Files:** none changed.

**Interfaces:**
- Consumes: everything above.
- Produces: the deployed `ledgerlens-transaction-fraud-detection` function and the three acceptance results.

- [ ] **Step 1: Deploy the data stack alone**

Run: `cd infra-cdk && npx cdk deploy ledgerlens-bank-assistant-data --exclusively --require-approval never --profile ledgerlens 2>&1 | tail -15; cd ..`
Expected: the stack update finishes with `✅  ledgerlens-bank-assistant-data`. The change set adds the new function, its log group and nothing that replaces an existing function.

- [ ] **Step 2: Run the three acceptance checks**

Use the scratchpad as `S`. The client context is built the same way as the earlier tools' acceptance runs:

```bash
S="<scratchpad>"
CC=$(printf '{"custom":{"bedrockAgentCoreToolName":"target___transaction_fraud_detection"}}' | base64 -w0)
invoke() {
  printf '%s' "$2" > "$S/$1.json"
  aws lambda invoke --function-name ledgerlens-transaction-fraud-detection \
    --client-context "$CC" --cli-binary-format raw-in-base64-out \
    --payload "fileb://$S/$1.json" --profile ledgerlens --region us-east-1 \
    "$S/$1_out.json" >/dev/null && cat "$S/$1_out.json" && echo
}
invoke fraud_tx '{"customer_id":"CLI-EX6BOAOEFZHQ","transaction_id":"TRX-23BIJAU4GL46ATPW9STY"}'
invoke fraud_card '{"customer_id":"CLI-EX6BOAOEFZHQ","card_last4":"4497"}'
invoke clean_tx '{"customer_id":"CLI-EX6BOAOEFZHQ","transaction_id":"TRX-GQLHRNO8BSQEL5CYFBIQ"}'
```

Expected (the spec's §1 acceptance; the deployed `AS_OF` is `2026-06-17T23:59:59`):
- `fraud_tx`: `"mode": "transaction"`, `"verdict": "fraud"`, `"basis": "scored"`.
- `fraud_card`: `"mode": "card"`, `"checked": 3`, `flagged` with exactly one item, `TRX-23BIJAU4GL46ATPW9STY` with `"verdict": "fraud"`.
- `clean_tx`: `"verdict": "no_fraud"`.
- None of the three outputs contains `fraud_score`, `score` or `is_fraud`.

If any result differs, stop and show the user the full output. Don't change the bands or the SQL to make the numbers match.

- [ ] **Step 3: Report**

Show the user the three outputs in full and say which checks passed. Then wait for their command to commit; don't commit or push on your own.
