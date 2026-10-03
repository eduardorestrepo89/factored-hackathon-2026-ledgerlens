# explain_transaction Lambda Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `explain_transaction` Gateway tool Lambda as a self-contained folder, `gateway/tools/explain_transaction/explain_transaction_lambda/`. It explains one credit-card charge in five parts: the charge itself, FX, the decline, habit, and app activity. It gives no fraud verdict.

**Architecture:** The shared layers are copied from `gateway/tools/get_session_context/` with sed. The domain holds `decline_codes.py`, `text_folding.py` and the entities. The use case runs the core query first. It then builds fx and decline from the core row. Habit and app activity each run in their own `try`; a failure there sets that section to `null` and lists it in `unavailable`.

**Tech Stack:** Python 3.13 (`.venv`), pytest, ruff, psycopg 3, TypeScript CDK with jest, and Git Bash on Windows.

**Spec:** `docs/superpowers/specs/2026-10-03-explain-transaction-lambda-design.md`

## Global Constraints

- **Python and shell**
  - `PY=.venv/Scripts/python`.
  - Run from the repo root in Git Bash, and add `</dev/null` to every `$PY` command.
  - Use `"$BASH"`, not plain `bash`.
- **Git**
  - Never run `git commit` or `git add`.
  - Never stage `infra-cdk/config.yaml`, `frontend/public/aws-exports.json` or `frontend/.env`.
  - No push and no merge.
  - The working tree already holds the uncommitted `transaction_fraud_detection` work: its tool and test folders, its plan and spec, and its hunks in `docs/LEDGERLENS_PRODUCT_DESIGN.md` and both `infra-cdk` files. Leave all of it as it is.
- **Names**
  - Asset folder: `gateway/tools/explain_transaction/`
  - Package: `explain_transaction_lambda`
  - Handler string: `explain_transaction_lambda/delivery/handler.handler`
  - Lambda: `ledgerlens-explain-transaction`
  - Tests: `tests/unit/explain_transaction/`
  - Queries: `explain_transaction`, `transaction_habit`, `transaction_app_activity`
  - Keep the specific names `database_repository` and `query_provider`. Never use a generic `repository` or `queries`.
- **Copy rule**
  - Copied files only change `get_session_context` → `explain_transaction`.
  - The builder also changes `GetSessionContextUseCase` → `ExplainTransactionUseCase` and drops `max_rows=` (ruling 1).
  - Never copy `__pycache__`. Never import from another tool's folder.
- **Isolation grep:** `grep -rnE "(get_session_context|list_credit_cards|list_card_transactions|transaction_fraud_detection)_lambda" gateway/tools/explain_transaction tests/unit/explain_transaction` must print nothing. Bare tool names may appear in message text and paths.
- **SQL**
  - No SQL file contains `fraud_score` or `is_fraud`, not even in a comment.
  - No `%` appears except in placeholders, comments included: write "10th to 90th percentile", not "10%".
  - No `SET` statement.
  - UTF-8, NFC, no BOM. Write the files with the Write tool, never with PowerShell.
  - Every SQL file gets the header written in Task 5. Never copy the fraud header, because it mentions the score.
- **Exact values:** the messages, `DECLINE_MEANINGS`, `tool_spec.json` and SQL are given in full in the tasks below, copied from spec §3.1, §5.1, §6 and §8.2. Use them verbatim.
  - Unexpected-error message: `Unexpected internal error explaining the charge. Offer a hand-off to a human agent.`
  - Handler success log line: `"%s returned explanation (unavailable=%s)"`.
- **Deploy is deferred.** It runs in one joint deploy with `transaction_fraud_detection` and `classify_call_type`, after all three are built. Don't run Task 11 during this plan.
- **Suite command** (the ignores keep duckdb-only data-load tests out):

  ```bash
  .venv/Scripts/python -m pytest tests/unit -q -p no:cacheprovider --ignore=tests/unit/test_data_load_cli.py --ignore=tests/unit/test_data_load_curate.py --ignore=tests/unit/test_data_load_curate_rules.py --ignore=tests/unit/test_data_load_curate_select.py --ignore=tests/unit/test_data_load_ddl.py --ignore=tests/unit/test_data_load_repair.py --ignore=tests/unit/test_data_load_transform.py --ignore=tests/unit/test_dsql_read_check.py -k "not test_dsql_driver_imports" </dev/null
  ```

  The baseline before this plan is `1166 passed, 1 deselected`.

### Plan rulings on the spec
1. **Builder:** after the sed copy, remove `max_rows=settings.max_rows` from the constructor call. Leaving it in raises `TypeError` at import, so every cold start would crash. The settings still parse `MAX_ROWS`.
2. **`usual_amount_range`** is presented as `{"low", "high", "currency"}`, with 2-decimal strings quantized half-up, because `percentile_cont` leaves float noise. It is `None` when `same_currency_count < 3`, either percentile is NULL, or the charge has no currency. A NULL percentile shouldn't make the whole habit unavailable.
3. **Missing habit row:** if `transaction_habit` returns no row, raise `ValueError`, so the section is unavailable rather than an uncaught `IndexError`.
4. **`rate`** is presented with `format(rate, "f")`, so it keeps its stored decimals and `Decimal("1E+1")` comes out as `"10"`.
5. **NULL `transaction_date`:** the core SQL's `transaction_date <= as_of` already drops NULL dates. The NULL-date branch in spec §4 is kept as defensive code and is unit-tested.
6. **Validation order:** `customer_id` is checked before `transaction_id`, so `{}` returns the customer_id error.
7. **Code-54 comparison:** `expiration_date >= transaction_date.date()`. A card expiring on the charge day gives `True`.
8. **Product doc §7.5:** the merchant-descriptor paragraph (`merchant_hint`) is dropped, because the spec has no `merchant_hint`.
9. **Translate-mapping test:** the test finds `list_card_transactions.sql` with `rglob` under `gateway/tools/list_card_transactions`, so no `*_lambda` path string appears.
10. **`minutes_from_charge`** uses Python's `round()`, which rounds halves to even. Test fixtures use whole minutes only, so the rounding mode never shows.

## Review Focus
1. **A card expiring on the same day as the charge, with code 54.** `contradicts_card_state` must be `true`. Code `"05"` must stay a string. *Pinned by Task 4, `test_code_54_contradiction` and `test_decline_meaning_per_code`.*
2. **Float noise from `percentile_cont`.** `Decimal("123.4500000000001")` must be presented as `"123.45"`. 2 vs 3 same-currency charges must also be covered. *Pinned by Task 6, `test_usual_range_is_quantized`, and Task 4, `test_usual_range_needs_three_charges`.*
3. **A foreign-currency charge with a NULL amount or a NULL rate.** `fx` must still be present with `amount_in_card_currency: null`, and nothing may crash. Half-up rounding gives 10.00 × 0.0005 = `0.01`. *Pinned by Task 4, `test_fx_rules`.*
4. **The habit query rejected by DSQL (R3).** The result must be `habit: null` and `unavailable: ["habit"]`, and app activity must still run. *Pinned by Task 4, `test_habit_failure_keeps_app_activity`.*
5. **An in-person charge whose country folds equal to the IP country** ("México" vs " MEXICO "). The result must be `conflict: false`, and App or Web never conflicts. *Pinned by Task 4, `test_conflict_rules`.*

## File map
| Path | Task |
|---|---|
| copied layers, `requirements.txt`, `__init__`s, `conftest.py`, `fakes.py`, 5 copied adapter tests | 1 |
| `domain/errors.py` + `test_errors.py` | 2 |
| `domain/value_objects/{decline_codes,text_folding}.py` + tests | 3 |
| `domain/entities/transaction_explanation.py`, `application/use_cases/explain_transaction.py` + `test_explain_transaction_use_case.py` | 4 |
| `queries/postgresql/*.sql` (3 files), `tool_spec.json` + `test_query_contracts.py` | 5 |
| `delivery/presenters/transaction_explanation.py` + `test_transaction_explanation_presenter.py` | 6 |
| `delivery/dependencies/dependencies_builder.py` + `test_delivery_wiring.py` | 7 |
| `delivery/handler.py` + `test_explain_transaction_handler.py` | 8 |
| `infra-cdk/lib/data-construct.ts`, `infra-cdk/test/data-construct.test.ts` | 9 |
| `docs/LEDGERLENS_PRODUCT_DESIGN.md` §7.5 (CRLF) + full suite | 10 |
| joint deploy + acceptance (deferred) | 11 |

All production paths below are relative to `gateway/tools/explain_transaction/explain_transaction_lambda/` unless they start with `gateway/`, `tests/`, `infra-cdk/` or `docs/`.

---

### Task 1: Copy the shared layers into `explain_transaction`

**Files:**
- Create (copied): `gateway/tools/explain_transaction/requirements.txt`
- Create (copied): the 14 `__init__.py` files under `gateway/tools/explain_transaction/explain_transaction_lambda/`
- Create: `domain/value_objects/__init__.py`, and the folder `queries/postgresql/`
- Create (copied): `application/ports/{database_repository,query_provider,errors}.py`, `infrastructure/queries/file_query_provider.py`, `infrastructure/repositories/dsql_repository.py`, `utils/connectors/{base,dsql}.py`, `delivery/settings.py`
- Create: `tests/unit/explain_transaction/__init__.py` (empty), `conftest.py`, `fakes.py`
- Create (copied): `tests/unit/explain_transaction/test_{settings,file_query_provider,dsql_repository,psycopg_connector,dsql_connector}.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces (all under `explain_transaction_lambda`):
  - `application.ports.database_repository.DatabaseRepository` with `execute_query(query: str, params: Mapping[str, object]) -> list[dict[str, Any]]`
  - `application.ports.query_provider.QueryProvider` with `get(name: str) -> str`
  - `application.ports.errors`: `DataAccessError`, `DataSourceConnectionError`, `QueryExecutionError`, `QueryLimitExceededError`, `QueryNotFoundError` (each takes one message string)
  - `infrastructure.queries.file_query_provider.FileQueryProvider(directory: Path)`
  - `infrastructure.repositories.dsql_repository.DsqlRepository(connector)`
  - `utils.connectors.base.PsycopgConnector`, `utils.connectors.dsql.DsqlConnector`
  - `delivery.settings`: `ConfigurationError`, `DatabaseEngine`, `DatabaseSettings`, `DsqlSettings`, `ClockSettings` (`.now() -> datetime`)
- Produces in `tests/unit/explain_transaction/fakes.py`:
  - `CUSTOMER_ID = "CLI-EX6BOAOEFZHQ"`, `TRANSACTION_ID = "TRX-23BIJAU4GL46ATPW9STY"`, `PRODUCT_ID = "PRD-P07-CC-4497"`, `CHARGE_DATE = datetime(2026, 5, 31, 6, 9, 15)`
  - `QUERY_NAMES = ("explain_transaction", "transaction_habit", "transaction_app_activity")`
  - `Outcome = list[dict[str, Any]] | Exception`
  - `FakeQueryProvider(queries: Mapping[str, str] | None = None)`: by default it serves each query name as its own SQL text. Attributes `.queries`, `.requested`.
  - `FakeExplainRepository(responses: Mapping[str, Outcome] | None = None)`: answers by SQL text (= query name). Attributes `.responses`, `.calls: list[tuple[str, dict[str, object]]]`; property `.queries: list[str]`.
  - Row builders, each taking `**overrides`: `make_core_row` (alias `make_row`), `make_habit_row`, `make_app_activity_row`.
  - `explain_responses(**overrides: Outcome) -> dict[str, Outcome]`: core and habit rows, and `[]` for app activity.
  - `make_any_row() -> dict[str, Any]`: the three rows merged. Use it over `FakeConnector`, which serves the same rows to every query.
  - Copied unchanged: `FakeCursor`, `FakeConnection`, `FakeConnector(*outcomes, max_age=None, clock=time.monotonic)`, `FakeClock`, `FakeDsqlTokenClient`.

- [ ] **Step 1: Copy the production files**

```bash
SRC=gateway/tools/get_session_context
DST=gateway/tools/explain_transaction
mkdir -p "$DST"
sed 's/get_session_context/explain_transaction/g' "$SRC/requirements.txt" > "$DST/requirements.txt"
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
  mkdir -p "$DST/explain_transaction_lambda/$(dirname "$f")"
  sed 's/get_session_context/explain_transaction/g' \
    "$SRC/get_session_context_lambda/$f" > "$DST/explain_transaction_lambda/$f"
done
mkdir -p "$DST/explain_transaction_lambda/domain/value_objects"
mkdir -p "$DST/explain_transaction_lambda/queries/postgresql"
printf '%s\n' '"""Value objects: decline-code meanings and text folding."""' \
  > "$DST/explain_transaction_lambda/domain/value_objects/__init__.py"
printf '%s\n' '"""Domain layer: value objects, entities and agent-facing errors. No I/O."""' \
  > "$DST/explain_transaction_lambda/domain/__init__.py"
```

`get_session_context`'s domain has no `value_objects/` folder, so the loop can't copy one. That's why it's written here, and why the domain docstring is rewritten to mention it.

Check the docstrings:

```bash
cat gateway/tools/explain_transaction/explain_transaction_lambda/__init__.py gateway/tools/explain_transaction/explain_transaction_lambda/application/use_cases/__init__.py
head -1 gateway/tools/explain_transaction/requirements.txt
find gateway/tools/explain_transaction -name __pycache__
```

Expected:
```text
"""The explain_transaction Gateway tool Lambda, in hexagonal layers."""
"""Use case of the explain_transaction tool."""
# Runtime dependencies for the explain_transaction Lambda.
```
and `find` prints nothing.

- [ ] **Step 2: Create the test package**

`tests/unit/explain_transaction/__init__.py` is an empty file.

`tests/unit/explain_transaction/conftest.py`:

```python
"""Pytest setup for explain_transaction: make its Lambda package importable.

The ``explain_transaction_lambda`` package lives in the Lambda asset root
``gateway/tools/explain_transaction``, so that folder is put on ``sys.path``
exactly as the Lambda runtime does.
"""

import sys
from pathlib import Path

_ASSET_ROOT = (
    Path(__file__).resolve().parents[3] / "gateway" / "tools" / "explain_transaction"
)

if str(_ASSET_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASSET_ROOT))
```

- [ ] **Step 3: Create `fakes.py`**

Copy it with sed first:

```bash
sed 's/get_session_context/explain_transaction/g' tests/unit/get_session_context/fakes.py > tests/unit/explain_transaction/fakes.py
```

Then replace everything from the top of the new file down to, but not including, the line `class FakeCursor:` with this block. Keep everything from `class FakeCursor:` to the end of the file exactly as copied.

```python
"""Test doubles and builders for the explain_transaction tests."""

import time
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from explain_transaction_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from explain_transaction_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryNotFoundError,
)
from explain_transaction_lambda.application.ports.query_provider import QueryProvider
from explain_transaction_lambda.utils.connectors.base import PsycopgConnector

# Customer P07 of the curated personas and the charge the spec's example explains.
CUSTOMER_ID: Final = "CLI-EX6BOAOEFZHQ"
TRANSACTION_ID: Final = "TRX-23BIJAU4GL46ATPW9STY"
# Any id: the use case only passes it from the core row to the habit query.
PRODUCT_ID: Final = "PRD-P07-CC-4497"
CHARGE_DATE: Final = datetime(2026, 5, 31, 6, 9, 15)

# The core query, then the two optional sections, in the order they run.
QUERY_NAMES: Final = (
    "explain_transaction",
    "transaction_habit",
    "transaction_app_activity",
)

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


class FakeExplainRepository(DatabaseRepository):
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


def make_core_row(**overrides: Any) -> dict[str, Any]:
    """Build an explain_transaction row as psycopg's dict_row returns it.

    The values are P07's charge from the spec's output example: USD on a USD
    card, approved, so fx and decline are both None.
    """
    row: dict[str, Any] = {
        "transaction_id": TRANSACTION_ID,
        "transaction_date": CHARGE_DATE,
        "product_id": PRODUCT_ID,
        "card_last4": "4497",
        "card_currency": "USD",
        "card_expiration_date": date(2029, 8, 31),
        "merchant_name": "Estación de Servicio",
        "merchant_category": "Transport",
        "amount": Decimal("288.69"),
        "currency": "USD",
        "channel": "Web",
        "transaction_city": "Ciudad de México",
        "transaction_country": "México",
        "transaction_status": "Approved",
        "response_code": "00",
        "fx_sell_rate": None,
    }
    row.update(overrides)
    return row


# The copied repository tests build rows with make_row.
make_row = make_core_row


def make_habit_row(**overrides: Any) -> dict[str, Any]:
    """Build the one aggregate row transaction_habit returns (P07's values)."""
    row: dict[str, Any] = {
        "history_count": 1,
        "times_at_merchant": 0,
        "same_currency_count": 1,
        "usual_low": None,
        "usual_high": None,
        "country_seen_before": True,
    }
    row.update(overrides)
    return row


def make_app_activity_row(**overrides: Any) -> dict[str, Any]:
    """Build a transaction_app_activity row: an event 12 minutes after the charge."""
    row: dict[str, Any] = {
        "event_id": "EVT-0001",
        "event_date": CHARGE_DATE + timedelta(minutes=12),
        "ip_country": "México",
        "ip_city": "Ciudad de México",
    }
    row.update(overrides)
    return row


def explain_responses(**overrides: Outcome) -> dict[str, Outcome]:
    """Return the responses of P07's charge, keyed by query name.

    App activity is empty by default, as it is for most charges. Overrides
    replace a query's outcome.
    """
    responses: dict[str, Outcome] = {
        "explain_transaction": [make_core_row()],
        "transaction_habit": [make_habit_row()],
        "transaction_app_activity": [],
    }
    responses.update(overrides)
    return responses


def make_any_row() -> dict[str, Any]:
    """Build one row that every query can map.

    FakeConnector serves the same rows to every query, so end-to-end tests over
    real adapters need a row with every query's columns. The three rows share no
    column name, so nothing is overwritten.
    """
    return {**make_core_row(), **make_habit_row(), **make_app_activity_row()}
```

The copied tail decides which imports the header needs. If ruff reports an unused import here, remove only that import. If it reports an undefined name (F821), add that import back exactly as the get_session_context header has it.

- [ ] **Step 4: Copy the adapter tests**

```bash
for t in test_settings test_file_query_provider test_dsql_repository test_psycopg_connector test_dsql_connector; do
  sed 's/get_session_context/explain_transaction/g' tests/unit/get_session_context/$t.py > tests/unit/explain_transaction/$t.py
done
```

- [ ] **Step 5: Run the copied tests**

Run: `$PY -m pytest tests/unit/explain_transaction -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: all pass, 0 failed. These tests cover copied code, so they pass at once. They prove the copy, not new behaviour.

- [ ] **Step 6: Check isolation and lint**

```bash
grep -rnE "(get_session_context|list_credit_cards|list_card_transactions|transaction_fraud_detection)_lambda" gateway/tools/explain_transaction tests/unit/explain_transaction
grep -rn "get_session_context" gateway/tools/explain_transaction tests/unit/explain_transaction
$PY -m ruff format --check gateway/tools/explain_transaction tests/unit/explain_transaction </dev/null
$PY -m ruff check gateway/tools/explain_transaction tests/unit/explain_transaction </dev/null
```

Expected: both greps print nothing, and both ruff commands are clean. If `ruff format --check` only reports reflowed lines in the copied files (the new package name is longer), run `$PY -m ruff format gateway/tools/explain_transaction tests/unit/explain_transaction </dev/null` once and re-check.

---

### Task 2: Domain errors

**Files:**
- Create: `domain/errors.py`
- Test: `tests/unit/explain_transaction/test_errors.py`

**Interfaces:**
- Consumes: `application.ports.errors` (Task 1).
- Produces in `explain_transaction_lambda.domain.errors`:
  - `DomainError(message: str)` with `.message`
  - `InvalidInputError(field: str, reason: str)` with `.field`, `.reason`
  - Fixed-message errors, each built with no arguments and carrying a class-level `MESSAGE`: `TransactionNotFoundError`, `DataSourceUnavailableError`, `ExplainLookupError`, `ExplainDataIntegrityError`

- [ ] **Step 1: Write the failing test**

`tests/unit/explain_transaction/test_errors.py`:

```python
"""Tests for domain and port error definitions."""

import explain_transaction_lambda.domain.errors as errors_module
import pytest
from explain_transaction_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
    QueryNotFoundError,
)
from explain_transaction_lambda.domain.errors import (
    DataSourceUnavailableError,
    DomainError,
    ExplainDataIntegrityError,
    ExplainLookupError,
    InvalidInputError,
    TransactionNotFoundError,
)

pytestmark = pytest.mark.unit


def test_invalid_input_error_formats_field_and_reason() -> None:
    error = InvalidInputError(
        "transaction_id", "is required and must be a non-empty string"
    )

    assert error.field == "transaction_id"
    assert error.reason == "is required and must be a non-empty string"
    assert error.message == (
        "Invalid value for 'transaction_id': is required and must be a non-empty "
        "string. Ask the customer to confirm and retry."
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
            DataSourceUnavailableError,
            "Transaction details are temporarily unavailable. Offer to retry in a "
            "moment or hand off to a human agent.",
        ),
        (
            ExplainLookupError,
            "The charge can't be explained right now due to an internal error. "
            "Don't retry; offer a hand-off to a human agent.",
        ),
        (
            ExplainDataIntegrityError,
            "The charge's data came back in an unexpected format. Don't retry; "
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
    ["CardNotFoundError", "FraudCheckLookupError", "SessionContextLookupError"],
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

If `ruff check` sorts the first two imports differently, accept ruff's order (`ruff check --fix` for I001 only).

- [ ] **Step 2: Run it to verify it fails**

Run: `$PY -m pytest tests/unit/explain_transaction/test_errors.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: an error during collection, `ModuleNotFoundError: No module named 'explain_transaction_lambda.domain.errors'`.

- [ ] **Step 3: Write `domain/errors.py`**

```python
"""Domain errors: the only failures the agent is allowed to see.

Each message says what went wrong and what the agent should do next. Messages
never contain SQL, hostnames, driver output, scores or other internal details.
"""

from typing import ClassVar


class DomainError(Exception):
    """Base class for errors whose message is safe to show the agent.

    Attributes:
        message: The agent-facing text.
    """

    def __init__(self, message: str) -> None:
        """Store the agent-facing message."""
        super().__init__(message)
        self.message: str = message


class InvalidInputError(DomainError):
    """A tool argument is missing or malformed.

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


class DataSourceUnavailableError(_FixedMessageError):
    """The database can't be reached right now; retrying later may work."""

    MESSAGE: ClassVar[str] = (
        "Transaction details are temporarily unavailable. Offer to retry in a "
        "moment or hand off to a human agent."
    )


class ExplainLookupError(_FixedMessageError):
    """The core query is missing, failed or hit a database limit."""

    MESSAGE: ClassVar[str] = (
        "The charge can't be explained right now due to an internal error. "
        "Don't retry; offer a hand-off to a human agent."
    )


class ExplainDataIntegrityError(_FixedMessageError):
    """The core row couldn't be mapped to a domain entity."""

    MESSAGE: ClassVar[str] = (
        "The charge's data came back in an unexpected format. Don't retry; "
        "offer a hand-off to a human agent."
    )
```

- [ ] **Step 4: Run it to verify it passes**

Run: `$PY -m pytest tests/unit/explain_transaction/test_errors.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: `12 passed`.

- [ ] **Step 5: Lint**

Run: `$PY -m ruff format --check gateway/tools/explain_transaction tests/unit/explain_transaction </dev/null && $PY -m ruff check gateway/tools/explain_transaction tests/unit/explain_transaction </dev/null`
Expected: clean.

---

### Task 3: Decline codes and text folding

**Files:**
- Create: `domain/value_objects/decline_codes.py`, `domain/value_objects/text_folding.py`
- Test: `tests/unit/explain_transaction/test_decline_codes.py`, `tests/unit/explain_transaction/test_text_folding.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `explain_transaction_lambda.domain.value_objects.decline_codes`: `DECLINE_MEANINGS: Final[Mapping[str, str]]`, `EXPIRED_CARD_CODE: Final = "54"`, `IN_PERSON_CHANNELS: Final = frozenset({"ATM", "POS", "Branch"})`
  - `explain_transaction_lambda.domain.value_objects.text_folding.fold_text(value: str | None) -> str | None`

- [ ] **Step 1: Write the failing tests**

`tests/unit/explain_transaction/test_decline_codes.py`:

```python
"""Tests for the decline-code meanings and the in-person channels."""

import pytest
from explain_transaction_lambda.domain.value_objects.decline_codes import (
    DECLINE_MEANINGS,
    EXPIRED_CARD_CODE,
    IN_PERSON_CHANNELS,
)

pytestmark = pytest.mark.unit


def test_decline_meanings_are_the_four_codes_in_the_data() -> None:
    assert DECLINE_MEANINGS == {
        "05": "declined by the issuer, no specific reason",
        "14": "invalid card number",
        "51": "insufficient available credit",
        "54": "expired card",
    }


def test_expired_card_code_is_54_and_has_a_meaning() -> None:
    assert EXPIRED_CARD_CODE == "54"
    assert DECLINE_MEANINGS[EXPIRED_CARD_CODE] == "expired card"


def test_only_atm_pos_and_branch_are_in_person() -> None:
    assert IN_PERSON_CHANNELS == frozenset({"ATM", "POS", "Branch"})
    assert "App" not in IN_PERSON_CHANNELS
    assert "Web" not in IN_PERSON_CHANNELS
```

`tests/unit/explain_transaction/test_text_folding.py`:

```python
"""Tests for fold_text, which compares country names loosely."""

import pytest
from explain_transaction_lambda.domain.value_objects.text_folding import fold_text

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("México", " MEXICO "),
        ("Colombia", "colombia"),
        ("Perú", "PERU"),
    ],
)
def test_accents_case_and_spaces_fold_equal(left: str, right: str) -> None:
    assert fold_text(left) == fold_text(right)


def test_fold_text_returns_plain_lower_case() -> None:
    assert fold_text("México") == "mexico"
    assert fold_text("São Paulo") == "sao paulo"


def test_different_countries_stay_different() -> None:
    assert fold_text("Brasil") != fold_text("México")


def test_none_stays_none() -> None:
    assert fold_text(None) is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/unit/explain_transaction/test_decline_codes.py tests/unit/explain_transaction/test_text_folding.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: errors during collection, `ModuleNotFoundError: No module named 'explain_transaction_lambda.domain.value_objects.decline_codes'` (and `...text_folding`).

- [ ] **Step 3: Write the two modules**

`domain/value_objects/decline_codes.py`:

```python
"""What each decline response code means, and which channels are in person.

The response codes in the data are 00, 05, 14, 51, 54 and NULL; declined rows
carry only the last four, or NULL. An unknown code has no meaning here, and the
agent is shown the code with a null meaning.
"""

from collections.abc import Mapping
from typing import Final

DECLINE_MEANINGS: Final[Mapping[str, str]] = {
    "05": "declined by the issuer, no specific reason",
    "14": "invalid card number",
    "51": "insufficient available credit",
    "54": "expired card",
}

# The code whose meaning can contradict the card's own expiration date (D18).
EXPIRED_CARD_CODE: Final = "54"

# The transaction channels where the card is physically present. App and Web
# charges can come from anywhere, so they never conflict with app activity.
IN_PERSON_CHANNELS: Final = frozenset({"ATM", "POS", "Branch"})
```

`domain/value_objects/text_folding.py`:

```python
"""Fold text so country names compare equal regardless of accents, case or spaces."""

import unicodedata


def fold_text(value: str | None) -> str | None:
    """Return ``value`` without accents, case-folded and stripped; None stays None.

    "México" and " MEXICO " both fold to "mexico" (D21). The habit SQL does the
    same comparison with translate() and the list_card_transactions mapping.
    """
    if value is None:
        return None
    decomposed = unicodedata.normalize("NFKD", value)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return plain.casefold().strip()
```

- [ ] **Step 4: Run them to verify they pass**

Run: `$PY -m pytest tests/unit/explain_transaction/test_decline_codes.py tests/unit/explain_transaction/test_text_folding.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: `9 passed`.

- [ ] **Step 5: Lint**

Run: `$PY -m ruff format --check gateway/tools/explain_transaction tests/unit/explain_transaction </dev/null && $PY -m ruff check gateway/tools/explain_transaction tests/unit/explain_transaction </dev/null`
Expected: clean.

---

### Task 4: Entities and the use case

**Files:**
- Create: `domain/entities/transaction_explanation.py`
- Create: `application/use_cases/explain_transaction.py`
- Test: `tests/unit/explain_transaction/test_explain_transaction_use_case.py`

**Interfaces:**
- Consumes:
  - Task 1: the ports, port errors and fakes (`FakeExplainRepository`, `FakeQueryProvider`, `explain_responses`, row builders, `CUSTOMER_ID`, `TRANSACTION_ID`, `PRODUCT_ID`, `CHARGE_DATE`).
  - Task 2: `InvalidInputError`, `TransactionNotFoundError`, `DataSourceUnavailableError`, `ExplainLookupError`, `ExplainDataIntegrityError`.
  - Task 3: `DECLINE_MEANINGS`, `EXPIRED_CARD_CODE`, `IN_PERSON_CHANNELS`, `fold_text`.
- Produces in `explain_transaction_lambda.domain.entities.transaction_explanation`. All dataclasses are frozen, with fields in this order:
  - `ExplainedTransaction(transaction_id: str, transaction_date: datetime | None, card_last4: str | None, merchant_name: str | None, merchant_category: str | None, amount: Decimal | None, currency: str | None, channel: str | None, transaction_city: str | None, transaction_country: str | None, transaction_status: str | None)`
  - `FxConversion(card_currency: str, rate_date: date | None, rate: Decimal | None, amount_in_card_currency: Decimal | None)`
  - `DeclineInfo(response_code: str | None, meaning: str | None, contradicts_card_state: bool | None)`
  - `UsualAmountRange(low: Decimal, high: Decimal, currency: str)`. Values are unrounded; the presenter quantizes them.
  - `SpendingHabit(history_count: int, times_at_merchant_90d: int | None, usual_amount_range: UsualAmountRange | None, country_seen_before: bool | None)`
  - `AppActivity(found: bool, event_date: datetime | None = None, minutes_from_charge: int | None = None, ip_country: str | None = None, ip_city: str | None = None, conflict: bool | None = None)`
  - `Section(StrEnum)`: `HABIT = "habit"`, `APP_ACTIVITY = "app_activity"`
  - `TransactionExplanation(transaction: ExplainedTransaction, fx: FxConversion | None, decline: DeclineInfo | None, habit: SpendingHabit | None, app_activity: AppActivity | None, unavailable: tuple[Section, ...])`
- Produces in `explain_transaction_lambda.application.use_cases.explain_transaction`:
  - `ExplainTransactionUseCase(database_repository: DatabaseRepository, query_provider: QueryProvider)`
  - `.execute(customer_id: object, transaction_id: object, as_of: datetime) -> TransactionExplanation`
  - `CORE_QUERY_NAME = "explain_transaction"`, `SECTION_QUERY_NAMES = {Section.HABIT: "transaction_habit", Section.APP_ACTIVITY: "transaction_app_activity"}`, `MIN_RANGE_CHARGES = 3`
- **SQL column → entity field mapping** (Tasks 5 and 6 depend on these names):
  - Core columns:
    - `fx_sell_rate` → `FxConversion.rate`
    - `card_currency` → `FxConversion.card_currency`
    - `response_code` → `DeclineInfo.response_code`
    - `card_expiration_date` and `product_id` are internal and never put on an entity.
  - Habit columns:
    - `times_at_merchant` → `SpendingHabit.times_at_merchant_90d`
    - `usual_low` and `usual_high` → `UsualAmountRange.low` and `UsualAmountRange.high`
    - `same_currency_count` is internal.
  - App columns: `event_id` is ordering only and is never mapped.

- [ ] **Step 1: Write the failing tests**

`tests/unit/explain_transaction/test_explain_transaction_use_case.py`:

```python
"""Tests for ExplainTransactionUseCase (spec sections 3.4 and 4)."""

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from explain_transaction_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
    QueryNotFoundError,
)
from explain_transaction_lambda.application.use_cases.explain_transaction import (
    ExplainTransactionUseCase,
)
from explain_transaction_lambda.domain.entities.transaction_explanation import (
    AppActivity,
    DeclineInfo,
    ExplainedTransaction,
    FxConversion,
    Section,
    SpendingHabit,
    TransactionExplanation,
    UsualAmountRange,
)
from explain_transaction_lambda.domain.errors import (
    DataSourceUnavailableError,
    DomainError,
    ExplainDataIntegrityError,
    ExplainLookupError,
    InvalidInputError,
    TransactionNotFoundError,
)

from .fakes import (
    CHARGE_DATE,
    CUSTOMER_ID,
    PRODUCT_ID,
    TRANSACTION_ID,
    FakeExplainRepository,
    FakeQueryProvider,
    Outcome,
    explain_responses,
    make_app_activity_row,
    make_core_row,
    make_habit_row,
)

pytestmark = pytest.mark.unit

AS_OF = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
AS_OF_SQL = datetime(2026, 6, 17, 23, 59, 59)

P07_TRANSACTION = ExplainedTransaction(
    transaction_id=TRANSACTION_ID,
    transaction_date=CHARGE_DATE,
    card_last4="4497",
    merchant_name="Estación de Servicio",
    merchant_category="Transport",
    amount=Decimal("288.69"),
    currency="USD",
    channel="Web",
    transaction_city="Ciudad de México",
    transaction_country="México",
    transaction_status="Approved",
)
P07_HABIT = SpendingHabit(
    history_count=1,
    times_at_merchant_90d=0,
    usual_amount_range=None,
    country_seen_before=True,
)


def make_use_case(
    responses: dict[str, Outcome] | None = None,
) -> tuple[ExplainTransactionUseCase, FakeExplainRepository]:
    """Wire the use case to fakes; by default they answer P07's charge."""
    database_repository = FakeExplainRepository(
        explain_responses() if responses is None else responses
    )
    use_case = ExplainTransactionUseCase(
        database_repository=database_repository,
        query_provider=FakeQueryProvider(),
    )
    return use_case, database_repository


def explain(**overrides: Outcome) -> TransactionExplanation:
    """Explain P07's charge with some query outcomes replaced."""
    use_case, _ = make_use_case(explain_responses(**overrides))
    return use_case.execute(CUSTOMER_ID, TRANSACTION_ID, as_of=AS_OF)


def core(**overrides: Any) -> dict[str, list[dict[str, Any]]]:
    """Return a core-query override with some columns replaced."""
    return {"explain_transaction": [make_core_row(**overrides)]}


# --- the whole call -------------------------------------------------------------


def test_p07_charge_is_explained() -> None:
    assert explain() == TransactionExplanation(
        transaction=P07_TRANSACTION,
        fx=None,
        decline=None,
        habit=P07_HABIT,
        app_activity=AppActivity(found=False),
        unavailable=(),
    )


def test_queries_run_in_order_with_their_params() -> None:
    use_case, database_repository = make_use_case()

    use_case.execute(CUSTOMER_ID, TRANSACTION_ID, as_of=AS_OF)

    assert database_repository.calls == [
        (
            "explain_transaction",
            {
                "customer_id": CUSTOMER_ID,
                "transaction_id": TRANSACTION_ID,
                "as_of": AS_OF_SQL,
            },
        ),
        (
            "transaction_habit",
            {
                "customer_id": CUSTOMER_ID,
                "product_id": PRODUCT_ID,
                "transaction_id": TRANSACTION_ID,
                "charge_date": CHARGE_DATE,
                "merchant_name": "Estación de Servicio",
                "currency": "USD",
                "transaction_country": "México",
            },
        ),
        (
            "transaction_app_activity",
            {
                "customer_id": CUSTOMER_ID,
                "charge_date": CHARGE_DATE,
                "as_of": AS_OF_SQL,
            },
        ),
    ]


def test_ids_are_stripped_and_uppercased() -> None:
    use_case, database_repository = make_use_case()

    use_case.execute(" cli-ex6boaoefzhq ", " trx-23bijau4gl46atpw9sty ", as_of=AS_OF)

    _query, params = database_repository.calls[0]
    assert params["customer_id"] == CUSTOMER_ID
    assert params["transaction_id"] == TRANSACTION_ID


def test_as_of_is_sent_as_naive_utc() -> None:
    use_case, database_repository = make_use_case()
    bogota = timezone(timedelta(hours=-5))

    use_case.execute(
        CUSTOMER_ID, TRANSACTION_ID, as_of=datetime(2026, 6, 17, 18, 59, 59, tzinfo=bogota)
    )

    assert database_repository.calls[0][1]["as_of"] == AS_OF_SQL
    assert database_repository.calls[2][1]["as_of"] == AS_OF_SQL


def test_naive_as_of_is_rejected_before_any_query() -> None:
    use_case, database_repository = make_use_case()

    with pytest.raises(ValueError, match="aware"):
        use_case.execute(CUSTOMER_ID, TRANSACTION_ID, as_of=AS_OF_SQL)
    assert database_repository.calls == []


# --- input validation -------------------------------------------------------------


@pytest.mark.parametrize("bad", [None, "", "   ", 42, True, ["CLI-1"]])
def test_bad_customer_id_is_rejected_before_any_query(bad: object) -> None:
    use_case, database_repository = make_use_case()

    with pytest.raises(InvalidInputError) as caught:
        use_case.execute(bad, TRANSACTION_ID, as_of=AS_OF)

    assert caught.value.field == "customer_id"
    assert database_repository.calls == []


@pytest.mark.parametrize("bad", [None, "", "   ", 42, True, ["TRX-1"]])
def test_bad_transaction_id_is_rejected_before_any_query(bad: object) -> None:
    use_case, database_repository = make_use_case()

    with pytest.raises(InvalidInputError) as caught:
        use_case.execute(CUSTOMER_ID, bad, as_of=AS_OF)

    assert caught.value.field == "transaction_id"
    assert caught.value.reason == "is required and must be a non-empty string"
    assert database_repository.calls == []


def test_customer_id_is_checked_before_transaction_id() -> None:
    use_case, _ = make_use_case()

    with pytest.raises(InvalidInputError) as caught:
        use_case.execute(None, None, as_of=AS_OF)

    assert caught.value.field == "customer_id"


# --- core failures --------------------------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (DataSourceConnectionError("down"), DataSourceUnavailableError),
        (QueryExecutionError("syntax"), ExplainLookupError),
        (QueryLimitExceededError("too big"), ExplainLookupError),
        (QueryNotFoundError("missing"), ExplainLookupError),
        ([], TransactionNotFoundError),
        ([make_core_row(transaction_id=None)], ExplainDataIntegrityError),
        ([make_core_row(product_id=None)], ExplainDataIntegrityError),
        ([make_core_row(amount="288.69")], ExplainDataIntegrityError),
        ([make_core_row(transaction_date="2026-05-31")], ExplainDataIntegrityError),
        ([{"transaction_id": TRANSACTION_ID}], ExplainDataIntegrityError),
    ],
    ids=[
        "unavailable",
        "execution",
        "limit",
        "missing-query",
        "not-found",
        "null-id",
        "null-product",
        "text-amount",
        "text-date",
        "missing-columns",
    ],
)
def test_core_failure_fails_the_call_and_skips_the_sections(
    outcome: Outcome, expected: type[DomainError]
) -> None:
    use_case, database_repository = make_use_case(
        explain_responses(explain_transaction=outcome)
    )

    with pytest.raises(expected):
        use_case.execute(CUSTOMER_ID, TRANSACTION_ID, as_of=AS_OF)
    assert database_repository.queries == ["explain_transaction"]


def test_missing_core_sql_is_a_lookup_error() -> None:
    use_case = ExplainTransactionUseCase(
        database_repository=FakeExplainRepository(explain_responses()),
        query_provider=FakeQueryProvider({}),
    )

    with pytest.raises(ExplainLookupError):
        use_case.execute(CUSTOMER_ID, TRANSACTION_ID, as_of=AS_OF)


# --- fx ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("columns", "expected"),
    [
        ({}, None),
        ({"currency": None}, None),
        ({"card_currency": None}, None),
        (
            {
                "currency": "COP",
                "amount": Decimal("400000.00"),
                "fx_sell_rate": Decimal("0.00025"),
            },
            FxConversion("USD", date(2026, 5, 31), Decimal("0.00025"), Decimal("100.00")),
        ),
        (
            {"currency": "COP", "fx_sell_rate": None},
            FxConversion("USD", date(2026, 5, 31), None, None),
        ),
        (
            {"currency": "COP", "amount": None, "fx_sell_rate": Decimal("0.00025")},
            FxConversion("USD", date(2026, 5, 31), Decimal("0.00025"), None),
        ),
        (
            {
                "currency": "COP",
                "amount": Decimal("10.00"),
                "fx_sell_rate": Decimal("0.0005"),
            },
            FxConversion("USD", date(2026, 5, 31), Decimal("0.0005"), Decimal("0.01")),
        ),
    ],
    ids=[
        "same-currency",
        "no-charge-currency",
        "no-card-currency",
        "converted",
        "no-rate",
        "no-amount",
        "half-up",
    ],
)
def test_fx_rules(columns: dict[str, Any], expected: FxConversion | None) -> None:
    assert explain(**core(**columns)).fx == expected


# --- decline ---------------------------------------------------------------------


@pytest.mark.parametrize("status", ["Approved", "Pending", "Reversed", None])
def test_decline_is_only_for_declined_charges(status: str | None) -> None:
    result = explain(**core(transaction_status=status, response_code="54"))

    assert result.decline is None


@pytest.mark.parametrize(
    ("code", "meaning"),
    [
        ("05", "declined by the issuer, no specific reason"),
        ("14", "invalid card number"),
        ("51", "insufficient available credit"),
        ("99", None),
        (None, None),
    ],
)
def test_decline_meaning_per_code(code: str | None, meaning: str | None) -> None:
    result = explain(**core(transaction_status="Declined", response_code=code))

    assert result.decline == DeclineInfo(
        response_code=code, meaning=meaning, contradicts_card_state=False
    )


@pytest.mark.parametrize(
    ("expiration", "expected"),
    [
        (date(2029, 1, 31), True),
        (date(2026, 5, 31), True),
        (date(2026, 5, 30), False),
        (None, None),
    ],
    ids=["valid-for-years", "expires-that-day", "already-expired", "no-expiration"],
)
def test_code_54_contradiction(expiration: date | None, expected: bool | None) -> None:
    result = explain(
        **core(
            transaction_status="Declined",
            response_code="54",
            card_expiration_date=expiration,
        )
    )

    assert result.decline == DeclineInfo(
        response_code="54", meaning="expired card", contradicts_card_state=expected
    )


def test_code_54_without_a_charge_date_is_unknown() -> None:
    result = explain(
        **core(transaction_status="Declined", response_code="54", transaction_date=None)
    )

    assert result.decline is not None
    assert result.decline.contradicts_card_state is None


# --- a charge without a date ------------------------------------------------------


def test_null_charge_date_skips_both_sections() -> None:
    use_case, database_repository = make_use_case(
        explain_responses(**core(transaction_date=None))
    )

    result = use_case.execute(CUSTOMER_ID, TRANSACTION_ID, as_of=AS_OF)

    assert result.transaction.transaction_date is None
    assert result.habit is None
    assert result.app_activity is None
    assert result.unavailable == (Section.HABIT, Section.APP_ACTIVITY)
    assert database_repository.queries == ["explain_transaction"]


# --- habit ------------------------------------------------------------------------


def test_habit_with_a_usual_range() -> None:
    habit_row = make_habit_row(
        history_count=12,
        times_at_merchant=3,
        same_currency_count=10,
        usual_low=Decimal("20.5"),
        usual_high=Decimal("310.25"),
        country_seen_before=False,
    )

    assert explain(transaction_habit=[habit_row]).habit == SpendingHabit(
        history_count=12,
        times_at_merchant_90d=3,
        usual_amount_range=UsualAmountRange(
            low=Decimal("20.5"), high=Decimal("310.25"), currency="USD"
        ),
        country_seen_before=False,
    )


@pytest.mark.parametrize(
    ("same_currency_count", "has_range"), [(0, False), (2, False), (3, True)]
)
def test_usual_range_needs_three_charges(
    same_currency_count: int, has_range: bool
) -> None:
    habit_row = make_habit_row(
        history_count=5,
        same_currency_count=same_currency_count,
        usual_low=Decimal("10"),
        usual_high=Decimal("90"),
    )

    habit = explain(transaction_habit=[habit_row]).habit

    assert habit is not None
    assert (habit.usual_amount_range is not None) is has_range


@pytest.mark.parametrize(
    "columns",
    [{"usual_low": None}, {"usual_high": None}],
    ids=["no-low", "no-high"],
)
def test_usual_range_needs_both_percentiles(columns: dict[str, Any]) -> None:
    habit_row = make_habit_row(
        same_currency_count=5,
        usual_low=Decimal("10"),
        usual_high=Decimal("90"),
    )
    habit_row.update(columns)

    habit = explain(transaction_habit=[habit_row]).habit

    assert habit is not None
    assert habit.usual_amount_range is None


def test_usual_range_needs_the_charge_currency() -> None:
    habit_row = make_habit_row(
        same_currency_count=5, usual_low=Decimal("10"), usual_high=Decimal("90")
    )

    result = explain(**core(currency=None), transaction_habit=[habit_row])

    assert result.habit is not None
    assert result.habit.usual_amount_range is None


def test_habit_keeps_its_nullable_fields() -> None:
    habit_row = make_habit_row(times_at_merchant=None, country_seen_before=None)

    assert explain(transaction_habit=[habit_row]).habit == SpendingHabit(
        history_count=1,
        times_at_merchant_90d=None,
        usual_amount_range=None,
        country_seen_before=None,
    )


@pytest.mark.parametrize(
    "outcome",
    [
        QueryExecutionError("translate() unsupported"),
        [],
        [make_habit_row(history_count=None)],
        [make_habit_row(history_count=True)],
        [make_habit_row(same_currency_count="3")],
        [make_habit_row(usual_low="cheap")],
        [{"history_count": 1}],
    ],
    ids=[
        "query-failed",
        "no-row",
        "null-count",
        "bool-count",
        "text-count",
        "text-low",
        "missing-columns",
    ],
)
def test_habit_failure_keeps_app_activity(
    outcome: Outcome, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    use_case, database_repository = make_use_case(
        explain_responses(
            transaction_habit=outcome,
            transaction_app_activity=[make_app_activity_row()],
        )
    )

    result = use_case.execute(CUSTOMER_ID, TRANSACTION_ID, as_of=AS_OF)

    assert result.habit is None
    assert result.app_activity is not None
    assert result.app_activity.found is True
    assert result.unavailable == (Section.HABIT,)
    assert database_repository.queries == [
        "explain_transaction",
        "transaction_habit",
        "transaction_app_activity",
    ]
    assert "explain_transaction section habit unavailable" in caplog.text


# --- app activity -----------------------------------------------------------------


def test_app_event_is_mapped() -> None:
    result = explain(transaction_app_activity=[make_app_activity_row()])

    assert result.app_activity == AppActivity(
        found=True,
        event_date=CHARGE_DATE + timedelta(minutes=12),
        minutes_from_charge=12,
        ip_country="México",
        ip_city="Ciudad de México",
        conflict=False,
    )
    assert result.unavailable == ()


@pytest.mark.parametrize("minutes", [-30, 0, 45, -120, 120])
def test_minutes_from_charge_is_negative_before_the_charge(minutes: int) -> None:
    event = make_app_activity_row(event_date=CHARGE_DATE + timedelta(minutes=minutes))

    app_activity = explain(transaction_app_activity=[event]).app_activity

    assert app_activity is not None
    assert app_activity.minutes_from_charge == minutes


@pytest.mark.parametrize(
    ("channel", "country", "ip_country", "expected"),
    [
        ("POS", "México", "Colombia", True),
        ("ATM", "México", "Colombia", True),
        ("Branch", "México", "Colombia", True),
        ("POS", "México", " MEXICO ", False),
        ("POS", "Perú", "PERU", False),
        ("App", "México", "Colombia", False),
        ("Web", "México", "Colombia", False),
        (None, "México", "Colombia", None),
        ("POS", None, "Colombia", None),
        ("POS", "México", None, None),
    ],
)
def test_conflict_rules(
    channel: str | None,
    country: str | None,
    ip_country: str | None,
    expected: bool | None,
) -> None:
    result = explain(
        **core(channel=channel, transaction_country=country),
        transaction_app_activity=[make_app_activity_row(ip_country=ip_country)],
    )

    assert result.app_activity is not None
    assert result.app_activity.conflict is expected


@pytest.mark.parametrize(
    "outcome",
    [
        QueryExecutionError("boom"),
        [make_app_activity_row(event_date=None)],
        [make_app_activity_row(event_date="2026-05-31T06:21:15")],
        [{"event_id": "EVT-1"}],
    ],
    ids=["query-failed", "null-date", "text-date", "missing-columns"],
)
def test_app_activity_failure_is_unavailable(outcome: Outcome) -> None:
    result = explain(transaction_app_activity=outcome)

    assert result.app_activity is None
    assert result.habit == P07_HABIT
    assert result.unavailable == (Section.APP_ACTIVITY,)


def test_both_sections_failing_are_listed_in_order() -> None:
    result = explain(
        transaction_habit=QueryExecutionError("a"),
        transaction_app_activity=QueryExecutionError("b"),
    )

    assert result.habit is None
    assert result.app_activity is None
    assert result.unavailable == (Section.HABIT, Section.APP_ACTIVITY)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/unit/explain_transaction/test_explain_transaction_use_case.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: an error during collection, `ModuleNotFoundError: No module named 'explain_transaction_lambda.application.use_cases.explain_transaction'`.

- [ ] **Step 3: Write the entities**

`domain/entities/transaction_explanation.py`:

```python
"""Entities returned by the explain_transaction use case.

Every field that comes from a nullable column is ``| None``: the source data has
about 5% nulls, and a row with a null column is still explained. No entity has a
fraud field; judging fraud is transaction_fraud_detection's job.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


@dataclass(frozen=True)
class ExplainedTransaction:
    """The charge itself. ``transaction_id`` is never None: it is the row's key."""

    transaction_id: str
    transaction_date: datetime | None
    card_last4: str | None
    merchant_name: str | None
    merchant_category: str | None
    amount: Decimal | None
    currency: str | None
    channel: str | None
    transaction_city: str | None
    transaction_country: str | None
    transaction_status: str | None


@dataclass(frozen=True)
class FxConversion:
    """What a charge in another currency cost in the card's currency.

    ``rate`` is the bank's sell rate on the charge's date, None when that day has
    no rate. ``amount_in_card_currency`` is amount times rate, rounded half-up to
    2 decimals, None without a rate or an amount.
    """

    card_currency: str
    rate_date: date | None
    rate: Decimal | None
    amount_in_card_currency: Decimal | None


@dataclass(frozen=True)
class DeclineInfo:
    """Why a declined charge was declined.

    ``meaning`` is None for a code the bank doesn't document.
    ``contradicts_card_state`` is True when the code says "expired card" but the
    card was still valid on the charge date (D18), None when that can't be told.
    """

    response_code: str | None
    meaning: str | None
    contradicts_card_state: bool | None


@dataclass(frozen=True)
class UsualAmountRange:
    """The 10th to 90th percentile of the card's approved charges in one currency.

    The values are exact as the database computed them; the presenter rounds.
    """

    low: Decimal
    high: Decimal
    currency: str


@dataclass(frozen=True)
class SpendingHabit:
    """How the charge compares with the card's approved charges of the 90 days before.

    ``times_at_merchant_90d`` is None when the charge has no merchant, and
    ``country_seen_before`` is None when it has no country.
    """

    history_count: int
    times_at_merchant_90d: int | None
    usual_amount_range: UsualAmountRange | None
    country_seen_before: bool | None


@dataclass(frozen=True)
class AppActivity:
    """The customer's app or web event closest to the charge, within 2 hours.

    ``found`` False means there was no such event, which is the usual case.
    ``minutes_from_charge`` is event minus charge, negative when the event came
    first. ``conflict`` is True when the event was in another country during an
    in-person charge, None when a country or the channel is unknown.
    """

    found: bool
    event_date: datetime | None = None
    minutes_from_charge: int | None = None
    ip_country: str | None = None
    ip_city: str | None = None
    conflict: bool | None = None


class Section(StrEnum):
    """The optional sections, in the order their queries run."""

    HABIT = "habit"
    APP_ACTIVITY = "app_activity"


@dataclass(frozen=True)
class TransactionExplanation:
    """Everything known about one charge.

    ``fx`` is None for a charge in the card's currency and ``decline`` is None
    unless the charge was declined. ``habit`` or ``app_activity`` is None only
    when its query failed, and is then named in ``unavailable``.
    """

    transaction: ExplainedTransaction
    fx: FxConversion | None
    decline: DeclineInfo | None
    habit: SpendingHabit | None
    app_activity: AppActivity | None
    unavailable: tuple[Section, ...]
```

- [ ] **Step 4: Write the use case**

`application/use_cases/explain_transaction.py`:

```python
"""Use case: explain one credit-card charge."""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final, TypeVar

from explain_transaction_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from explain_transaction_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
)
from explain_transaction_lambda.application.ports.query_provider import QueryProvider
from explain_transaction_lambda.domain.entities.transaction_explanation import (
    AppActivity,
    DeclineInfo,
    ExplainedTransaction,
    FxConversion,
    Section,
    SpendingHabit,
    TransactionExplanation,
    UsualAmountRange,
)
from explain_transaction_lambda.domain.errors import (
    DataSourceUnavailableError,
    ExplainDataIntegrityError,
    ExplainLookupError,
    InvalidInputError,
    TransactionNotFoundError,
)
from explain_transaction_lambda.domain.value_objects.decline_codes import (
    DECLINE_MEANINGS,
    EXPIRED_CARD_CODE,
    IN_PERSON_CHANNELS,
)
from explain_transaction_lambda.domain.value_objects.text_folding import fold_text

logger = logging.getLogger(__name__)

CORE_QUERY_NAME: Final = "explain_transaction"
# The query of each optional section, in Section order.
SECTION_QUERY_NAMES: Final[Mapping[Section, str]] = {
    Section.HABIT: "transaction_habit",
    Section.APP_ACTIVITY: "transaction_app_activity",
}
# One or two charges don't make a range.
MIN_RANGE_CHARGES: Final = 3

_DECLINED: Final = "Declined"
_CENTS: Final = Decimal("0.01")
_INVALID_ID: Final = "is required and must be a non-empty string"

_Value = TypeVar("_Value")


@dataclass(frozen=True)
class _CardFacts:
    """Core-row columns the use case needs but never returns."""

    product_id: str
    card_currency: str | None
    card_expiration_date: date | None
    response_code: str | None
    fx_sell_rate: Decimal | None


class ExplainTransactionUseCase:
    """Explain one charge through a database-agnostic repository.

    Up to three queries run one after another on the repository's single
    connection. The core query (the charge) is required: its failure fails the
    call with a domain error. fx and decline come from the core row. Habit and app
    activity each fail on their own: the section becomes None and is listed in
    ``unavailable``, and the next one still runs.
    """

    def __init__(
        self,
        database_repository: DatabaseRepository,
        query_provider: QueryProvider,
    ) -> None:
        """Store the ports.

        Args:
            database_repository: Executes the queries; any DatabaseRepository
                adapter.
            query_provider: Supplies the SQL text for the configured dialect.
        """
        self._database_repository: DatabaseRepository = database_repository
        self._query_provider: QueryProvider = query_provider

    def execute(
        self, customer_id: object, transaction_id: object, as_of: datetime
    ) -> TransactionExplanation:
        """Clean the inputs, load the charge, then its habit and app activity.

        Args:
            customer_id: The customer id exactly as it came in the tool event.
            transaction_id: The charge's id exactly as it came in the tool event.
            as_of: "Now", an aware datetime. Every query gets it as naive UTC,
                because the ERD's timestamp columns have no time zone.

        Raises:
            InvalidInputError: customer_id or transaction_id is missing, not a
                string or blank, checked in that order. Raised before the
                database is touched.
            ValueError: as_of is naive (a programming error, not user input).
            DataSourceUnavailableError: The core query couldn't connect.
            ExplainLookupError: The core query is missing, failed or hit a
                database limit.
            TransactionNotFoundError: No credit-card charge of this customer has
                the transaction_id.
            ExplainDataIntegrityError: The core row couldn't be mapped.
        """
        clean_customer_id = _clean_customer_id(customer_id)
        clean_transaction_id = _clean_transaction_id(transaction_id)
        as_of_sql = _utc(as_of).replace(tzinfo=None)
        transaction, facts = self._core(
            clean_customer_id, clean_transaction_id, as_of_sql
        )
        fx = _fx(transaction, facts)
        decline = _decline(transaction, facts)

        charge_date = transaction.transaction_date
        if charge_date is None:
            logger.warning(
                "explain_transaction charge has no transaction_date; "
                "habit and app_activity skipped"
            )
            return TransactionExplanation(
                transaction=transaction,
                fx=fx,
                decline=decline,
                habit=None,
                app_activity=None,
                unavailable=(Section.HABIT, Section.APP_ACTIVITY),
            )

        habit = self._section(
            Section.HABIT,
            {
                "customer_id": clean_customer_id,
                "product_id": facts.product_id,
                "transaction_id": transaction.transaction_id,
                "charge_date": charge_date,
                "merchant_name": transaction.merchant_name,
                "currency": transaction.currency,
                "transaction_country": transaction.transaction_country,
            },
            lambda rows: _to_habit(rows, transaction.currency),
        )
        app_activity = self._section(
            Section.APP_ACTIVITY,
            {
                "customer_id": clean_customer_id,
                "charge_date": charge_date,
                "as_of": as_of_sql,
            },
            lambda rows: _to_app_activity(rows, transaction, charge_date),
        )
        return TransactionExplanation(
            transaction=transaction,
            fx=fx,
            decline=decline,
            habit=habit,
            app_activity=app_activity,
            unavailable=tuple(
                section
                for section, value in (
                    (Section.HABIT, habit),
                    (Section.APP_ACTIVITY, app_activity),
                )
                if value is None
            ),
        )

    def _core(
        self, customer_id: str, transaction_id: str, as_of_sql: datetime
    ) -> tuple[ExplainedTransaction, _CardFacts]:
        """Load and map the charge, translating every failure.

        Raises:
            DataSourceUnavailableError: The query couldn't connect.
            ExplainLookupError: Any other data-access failure.
            TransactionNotFoundError: No row came back.
            ExplainDataIntegrityError: The row couldn't be mapped.
        """
        try:
            rows = self._run(
                CORE_QUERY_NAME,
                {
                    "customer_id": customer_id,
                    "transaction_id": transaction_id,
                    "as_of": as_of_sql,
                },
            )
        except DataSourceConnectionError as exc:
            raise DataSourceUnavailableError() from exc
        except DataAccessError as exc:
            raise ExplainLookupError() from exc
        if not rows:
            raise TransactionNotFoundError()
        try:
            return _to_transaction(rows[0]), _to_card_facts(rows[0])
        except (KeyError, TypeError, ValueError) as exc:
            raise ExplainDataIntegrityError() from exc

    def _section(
        self,
        section: Section,
        params: Mapping[str, object],
        mapper: Callable[[list[dict[str, Any]]], _Value],
    ) -> _Value | None:
        """Run a section's query and map its rows; on any failure return None."""
        try:
            return mapper(self._run(SECTION_QUERY_NAMES[section], params))
        except (DataAccessError, KeyError, TypeError, ValueError):
            logger.warning(
                "explain_transaction section %s unavailable",
                section.value,
                exc_info=True,
            )
            return None

    def _run(self, name: str, params: Mapping[str, object]) -> list[dict[str, Any]]:
        """Load the named SQL and run it.

        Raises:
            DataAccessError: The query is missing or failed.
        """
        query = self._query_provider.get(name)
        return self._database_repository.execute_query(query, params)


def _clean_customer_id(raw: object) -> str:
    """Strip and uppercase the raw id; ids look like ``CLI-ITIECUE8PRH9``.

    There is no format check: a malformed or unknown id just finds no charge.
    Whether the caller may see this customer is the Gateway's Cedar policy's job.

    Raises:
        InvalidInputError: The id isn't a string or is blank after stripping.
    """
    if not isinstance(raw, str):
        raise InvalidInputError("customer_id", _INVALID_ID)
    customer_id = raw.strip().upper()
    if not customer_id:
        raise InvalidInputError("customer_id", _INVALID_ID)
    return customer_id


def _clean_transaction_id(raw: object) -> str:
    """Strip and uppercase the raw id; ids look like ``TRX-23BIJAU4GL46ATPW9STY``.

    There is no format check: a malformed or unknown id just finds no charge.

    Raises:
        InvalidInputError: The id isn't a string or is blank after stripping.
    """
    if not isinstance(raw, str):
        raise InvalidInputError("transaction_id", _INVALID_ID)
    transaction_id = raw.strip().upper()
    if not transaction_id:
        raise InvalidInputError("transaction_id", _INVALID_ID)
    return transaction_id


def _utc(as_of: datetime) -> datetime:
    """Return as_of converted to aware UTC.

    Raises:
        ValueError: as_of is naive.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be an aware datetime")
    return as_of.astimezone(timezone.utc)


def _to_transaction(row: Mapping[str, Any]) -> ExplainedTransaction:
    """Map the core row to the charge.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type, or transaction_id is None.
        ValueError: The amount isn't finite.
    """
    return ExplainedTransaction(
        transaction_id=_required_text(row, "transaction_id"),
        transaction_date=_optional_datetime(row, "transaction_date"),
        card_last4=_optional_text(row, "card_last4"),
        merchant_name=_optional_text(row, "merchant_name"),
        merchant_category=_optional_text(row, "merchant_category"),
        amount=_optional_amount(row, "amount"),
        currency=_optional_text(row, "currency"),
        channel=_optional_text(row, "channel"),
        transaction_city=_optional_text(row, "transaction_city"),
        transaction_country=_optional_text(row, "transaction_country"),
        transaction_status=_optional_text(row, "transaction_status"),
    )


def _to_card_facts(row: Mapping[str, Any]) -> _CardFacts:
    """Map the core row's internal columns.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type, or product_id is None.
        ValueError: The rate isn't finite.
    """
    return _CardFacts(
        product_id=_required_text(row, "product_id"),
        card_currency=_optional_text(row, "card_currency"),
        card_expiration_date=_optional_date(row, "card_expiration_date"),
        response_code=_optional_text(row, "response_code"),
        fx_sell_rate=_optional_amount(row, "fx_sell_rate"),
    )


def _fx(transaction: ExplainedTransaction, facts: _CardFacts) -> FxConversion | None:
    """Convert a charge in another currency; None when the currencies match."""
    if (
        transaction.currency is None
        or facts.card_currency is None
        or transaction.currency == facts.card_currency
    ):
        return None
    rate = facts.fx_sell_rate
    converted = (
        None
        if rate is None or transaction.amount is None
        else (transaction.amount * rate).quantize(_CENTS, rounding=ROUND_HALF_UP)
    )
    charge_date = transaction.transaction_date
    return FxConversion(
        card_currency=facts.card_currency,
        rate_date=None if charge_date is None else charge_date.date(),
        rate=rate,
        amount_in_card_currency=converted,
    )


def _decline(transaction: ExplainedTransaction, facts: _CardFacts) -> DeclineInfo | None:
    """Explain a declined charge; None for any other status."""
    if transaction.transaction_status != _DECLINED:
        return None
    code = facts.response_code
    return DeclineInfo(
        response_code=code,
        meaning=None if code is None else DECLINE_MEANINGS.get(code),
        contradicts_card_state=_contradicts_card_state(
            code, facts.card_expiration_date, transaction.transaction_date
        ),
    )


def _contradicts_card_state(
    code: str | None, expiration_date: date | None, charge_date: datetime | None
) -> bool | None:
    """Whether "expired card" was given for a card still valid that day (D18).

    Any code other than 54 contradicts nothing. For 54, a card that expires on
    the charge day or later wasn't expired; without both dates it can't be told.
    """
    if code != EXPIRED_CARD_CODE:
        return False
    if expiration_date is None or charge_date is None:
        return None
    return expiration_date >= charge_date.date()


def _to_habit(rows: list[dict[str, Any]], currency: str | None) -> SpendingHabit:
    """Map the one aggregate row of transaction_habit.

    Raises:
        ValueError: No row came back, or an amount isn't finite.
        KeyError: A column is missing.
        TypeError: A column has the wrong type, or a count is None.
    """
    if not rows:
        raise ValueError("transaction_habit returned no row")
    row = rows[0]
    history_count = _required_int(row, "history_count")
    same_currency_count = _required_int(row, "same_currency_count")
    low = _optional_amount(row, "usual_low")
    high = _optional_amount(row, "usual_high")
    usual_amount_range = (
        None
        if currency is None
        or same_currency_count < MIN_RANGE_CHARGES
        or low is None
        or high is None
        else UsualAmountRange(low=low, high=high, currency=currency)
    )
    return SpendingHabit(
        history_count=history_count,
        times_at_merchant_90d=_optional_int(row, "times_at_merchant"),
        usual_amount_range=usual_amount_range,
        country_seen_before=_optional_bool(row, "country_seen_before"),
    )


def _to_app_activity(
    rows: list[dict[str, Any]],
    transaction: ExplainedTransaction,
    charge_date: datetime,
) -> AppActivity:
    """Map the closest event; no row means found=False, not a failure.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type, or event_date is None.
    """
    if not rows:
        return AppActivity(found=False)
    row = rows[0]
    event_date = _required_datetime(row, "event_date")
    ip_country = _optional_text(row, "ip_country")
    return AppActivity(
        found=True,
        event_date=event_date,
        minutes_from_charge=round((event_date - charge_date).total_seconds() / 60),
        ip_country=ip_country,
        ip_city=_optional_text(row, "ip_city"),
        conflict=_conflict(
            transaction.channel, transaction.transaction_country, ip_country
        ),
    )


def _conflict(
    channel: str | None, country: str | None, ip_country: str | None
) -> bool | None:
    """Whether the app was in another country during an in-person charge.

    App and Web charges never conflict: they can come from anywhere. Countries
    compare without accents, case or spaces ("México" equals " MEXICO ").
    """
    if channel is None or country is None or ip_country is None:
        return None
    return channel in IN_PERSON_CHANNELS and fold_text(ip_country) != fold_text(
        country
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


def _optional_date(row: Mapping[str, Any], column: str) -> date | None:
    """Return a nullable date column; a timestamp keeps only its date."""
    value = row[column]
    if value is None:
        return None
    # datetime is a subclass of date, so it must be checked first.
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"{column} is {type(value).__name__}, expected a date")


def _optional_datetime(row: Mapping[str, Any], column: str) -> datetime | None:
    """Return a nullable timestamp column as it is stored."""
    value = row[column]
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    raise TypeError(f"{column} is {type(value).__name__}, expected a timestamp")


def _required_datetime(row: Mapping[str, Any], column: str) -> datetime:
    """Return a timestamp column that must not be NULL."""
    value = _optional_datetime(row, column)
    if value is None:
        raise TypeError(f"{column} is None, expected a timestamp")
    return value


def _optional_int(row: Mapping[str, Any], column: str) -> int | None:
    """Return a nullable integer column; bool is rejected."""
    value = row[column]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{column} is {type(value).__name__}, expected an integer")
    return value


def _required_int(row: Mapping[str, Any], column: str) -> int:
    """Return an integer column that must not be NULL; bool is rejected."""
    value = _optional_int(row, column)
    if value is None:
        raise TypeError(f"{column} is None, expected an integer")
    return value


def _optional_bool(row: Mapping[str, Any], column: str) -> bool | None:
    """Return a nullable boolean column; only bool or None is accepted."""
    value = row[column]
    if value is None or isinstance(value, bool):
        return value
    raise TypeError(f"{column} is {type(value).__name__}, expected a boolean")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `$PY -m pytest tests/unit/explain_transaction/test_explain_transaction_use_case.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: all pass, 0 failed (about 85 tests).

- [ ] **Step 6: Lint**

Run: `$PY -m ruff format --check gateway/tools/explain_transaction tests/unit/explain_transaction </dev/null && $PY -m ruff check gateway/tools/explain_transaction tests/unit/explain_transaction </dev/null`
Expected: clean. If `ruff format --check` only reports reflowed lines, run `ruff format` on the two new files and re-check. Don't change any logic.

---

### Task 5: The SQL files, `tool_spec.json` and the contract tests

**Files:**
- Create: `queries/postgresql/explain_transaction.sql`, `queries/postgresql/transaction_habit.sql`, `queries/postgresql/transaction_app_activity.sql`
- Create: `gateway/tools/explain_transaction/tool_spec.json`
- Test: `tests/unit/explain_transaction/test_query_contracts.py`

**Interfaces:**
- Consumes:
  - Task 1: `FileQueryProvider`, and the fakes (`QUERY_NAMES`, `FakeExplainRepository`, `FakeQueryProvider`, `explain_responses`, `CUSTOMER_ID`, `TRANSACTION_ID`).
  - Task 4: `ExplainTransactionUseCase` and the column names in its mapping block. The SQL must select exactly those columns.
- Produces: the three query files, loaded by name through `FileQueryProvider(QUERIES_DIR).get(name)`, and the tool definition the Gateway target will register.

Write every SQL file with the Write tool, UTF-8 without a BOM. They contain accented literals (`'Tarjeta Crédito'` and the translate() strings), and the contract test reads the raw bytes.

- [ ] **Step 1: Write the failing contract tests**

`tests/unit/explain_transaction/test_query_contracts.py`:

```python
"""Drift tests: the SQL files and tool_spec.json must match the Python contracts."""

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from explain_transaction_lambda.application.use_cases.explain_transaction import (
    ExplainTransactionUseCase,
)
from explain_transaction_lambda.infrastructure.queries.file_query_provider import (
    FileQueryProvider,
)

from .fakes import (
    CUSTOMER_ID,
    QUERY_NAMES,
    TRANSACTION_ID,
    FakeExplainRepository,
    FakeQueryProvider,
    explain_responses,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_ROOT = REPO_ROOT / "gateway/tools/explain_transaction"
QUERIES_DIR = TOOL_ROOT / "explain_transaction_lambda/queries/postgresql"
TOOL_SPEC = TOOL_ROOT / "tool_spec.json"
PLACEHOLDER = re.compile(r"%\((\w+)\)s")
TRANSLATE = re.compile(r"translate\(([^,]+), '([^']*)', '([^']*)'\)")
SESSION_STATEMENT = re.compile(r"^\s*SET\b", re.IGNORECASE | re.MULTILINE)
# Escaped so this test file's own encoding can't change the expected value.
CREDIT_CARD_FILTER = "p.product_type = 'Tarjeta Crédito'"
AS_OF = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)

# The columns each query must select: the ones the use case maps (Task 4).
SELECTED_COLUMNS = {
    "explain_transaction": (
        "transaction_id",
        "transaction_date",
        "product_id",
        "card_last4",
        "card_currency",
        "card_expiration_date",
        "merchant_name",
        "merchant_category",
        "amount",
        "currency",
        "channel",
        "transaction_city",
        "transaction_country",
        "transaction_status",
        "response_code",
        "fx_sell_rate",
    ),
    "transaction_habit": (
        "history_count",
        "times_at_merchant",
        "same_currency_count",
        "usual_low",
        "usual_high",
        "country_seen_before",
    ),
    "transaction_app_activity": ("event_id", "event_date", "ip_country", "ip_city"),
}


def sql(name: str) -> str:
    """Load one of the real queries."""
    return FileQueryProvider(QUERIES_DIR).get(name)


def sent_params() -> dict[str, dict[str, object]]:
    """Return the params the use case actually sends, keyed by query name."""
    database_repository = FakeExplainRepository(explain_responses())
    use_case = ExplainTransactionUseCase(
        database_repository=database_repository, query_provider=FakeQueryProvider()
    )
    use_case.execute(CUSTOMER_ID, TRANSACTION_ID, as_of=AS_OF)
    return dict(database_repository.calls)


def tool_spec() -> dict[str, Any]:
    """Load the single tool definition from tool_spec.json."""
    specs = json.loads(TOOL_SPEC.read_text(encoding="utf-8"))
    assert isinstance(specs, list) and len(specs) == 1
    return specs[0]


def strip_accents(text: str) -> str:
    """Drop combining marks: 'Ó' -> 'O', 'ñ' -> 'n'."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def country_folds() -> list[tuple[str, str, str]]:
    """Return (argument, from_chars, to_chars) of each translate() in the habit SQL."""
    return [
        (arg.strip(), src, dst)
        for arg, src, dst in TRANSLATE.findall(sql("transaction_habit"))
    ]


# --- every query -----------------------------------------------------------------


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
def test_no_query_reads_the_fraud_columns(name: str) -> None:
    # This tool explains; judging fraud is transaction_fraud_detection's job.
    # Comments count too.
    text = sql(name).lower()

    assert "fraud_score" not in text
    assert "is_fraud" not in text


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_each_query_checks_the_customer(name: str) -> None:
    assert "customer_id = %(customer_id)s" in sql(name)


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_is_nfc_utf8_without_bom(name: str) -> None:
    # A decomposed accent or a BOM would silently match nothing.
    raw = (QUERIES_DIR / f"{name}.sql").read_bytes()

    assert not raw.startswith(b"\xef\xbb\xbf")
    assert unicodedata.is_normalized("NFC", raw.decode("utf-8"))


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_selects_every_column_the_use_case_maps(name: str) -> None:
    text = sql(name)
    for column in SELECTED_COLUMNS[name]:
        assert column in text, column


# --- the core query ----------------------------------------------------------------


def test_core_is_credit_cards_only() -> None:
    raw = (QUERIES_DIR / "explain_transaction.sql").read_bytes()

    assert CREDIT_CARD_FILTER.encode("utf-8") in raw


def test_core_finds_one_charge_of_the_customer_up_to_as_of() -> None:
    text = sql("explain_transaction")

    assert "SELECT DISTINCT ON (t.transaction_id)" in text
    assert "t.transaction_id = %(transaction_id)s" in text
    assert "t.customer_id = %(customer_id)s" in text
    assert "t.transaction_date <= %(as_of)s" in text


def test_core_joins_the_rate_only_across_currencies() -> None:
    text = sql("explain_transaction")

    assert "LEFT JOIN daily_exchange_rates AS fx" in text
    assert "fx.date = t.transaction_date::date" in text
    assert "fx.source_currency = t.currency" in text
    assert "fx.target_currency = p.currency" in text
    assert "t.currency <> p.currency" in text
    assert "fx.sell_rate" in text


# --- the habit query ---------------------------------------------------------------


def test_habit_window_is_the_cards_approved_90_days_before_the_charge() -> None:
    text = sql("transaction_habit")

    assert "SELECT DISTINCT ON (t.transaction_id)" in text
    assert "t.product_id = %(product_id)s" in text
    assert "t.transaction_status = 'Approved'" in text
    assert "t.transaction_id <> %(transaction_id)s" in text
    assert "t.transaction_date >= %(charge_date)s - INTERVAL '90 days'" in text
    assert "t.transaction_date <  %(charge_date)s" in text


def test_habit_range_is_the_10th_to_90th_percentile_in_the_charge_currency() -> None:
    text = sql("transaction_habit")

    assert "percentile_cont(0.1) WITHIN GROUP (ORDER BY amount)" in text
    assert "percentile_cont(0.9) WITHIN GROUP (ORDER BY amount)" in text
    assert text.count("FILTER (WHERE currency = %(currency)s::text)") == 3


def test_habit_folds_the_country_on_both_sides_identically() -> None:
    folds = country_folds()

    assert [arg for arg, _, _ in folds] == [
        "btrim(transaction_country)",
        "btrim(%(transaction_country)s::text)",
    ]
    assert folds[0][1:] == folds[1][1:]


def test_habit_accent_mapping_strips_each_accent() -> None:
    _, src, dst = country_folds()[0]

    assert len(src) == len(dst)
    for accented, plain in zip(src, dst, strict=True):
        assert strip_accents(accented) == plain


def test_habit_accent_mapping_matches_list_card_transactions() -> None:
    # The same strings fold merchants there; one mapping keeps both tools alike.
    other = next(
        (REPO_ROOT / "gateway/tools/list_card_transactions").rglob(
            "list_card_transactions.sql"
        )
    )
    other_folds = TRANSLATE.findall(other.read_text(encoding="utf-8"))

    assert country_folds()[0][1:] == other_folds[0][1:]


# --- the app activity query ---------------------------------------------------------


def test_app_activity_is_the_closest_event_within_two_hours() -> None:
    text = sql("transaction_app_activity")

    assert "e.ip_country IS NOT NULL" in text
    assert (
        "e.event_date BETWEEN %(charge_date)s - INTERVAL '2 hours' "
        "AND %(charge_date)s + INTERVAL '2 hours'"
    ) in text
    assert "e.event_date <= %(as_of)s" in text
    assert "ORDER BY ABS(EXTRACT(EPOCH FROM (e.event_date - %(charge_date)s)))" in text
    assert text.rstrip().endswith("LIMIT 1")


# --- tool_spec.json ---------------------------------------------------------------


def test_tool_spec_name_and_required_fields() -> None:
    spec = tool_spec()

    assert spec["name"] == "explain_transaction"
    assert spec["inputSchema"]["required"] == ["customer_id", "transaction_id"]


def test_tool_spec_properties_are_the_two_ids() -> None:
    properties = tool_spec()["inputSchema"]["properties"]

    assert set(properties) == {"customer_id", "transaction_id"}
    assert all(prop["type"] == "string" for prop in properties.values())


def test_tool_spec_description_names_the_sections() -> None:
    description = tool_spec()["description"]

    for word in (
        "fx",
        "decline",
        "habit",
        "app_activity",
        "unavailable",
        "transaction_fraud_detection",
        "2 decimals",
    ):
        assert word in description, word
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/unit/explain_transaction/test_query_contracts.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: FAIL. Most tests fail with `QueryNotFoundError` or `FileNotFoundError`, because the SQL files and `tool_spec.json` don't exist yet. `test_every_query_is_sent` already passes, since it uses the fakes only.

- [ ] **Step 3: Write `queries/postgresql/explain_transaction.sql`**

```sql
-- explain_transaction (PostgreSQL dialect, runs on Aurora DSQL)
--
-- One credit-card charge of the customer, with its card and, for a charge in
-- another currency, the bank's sell rate on the charge's date.
-- Used by ExplainTransactionUseCase as the core query.
--
-- customer_id in the WHERE is the ownership check: another customer's charge,
-- or a charge on a non-credit product, returns no row ("not found"). Credit
-- cards only, matched exactly on product_type = 'Tarjeta Crédito' (the dataset's
-- Spanish value), the filter every tool uses. transaction_date <= as_of keeps
-- the demo's "now" honest. The rate join only matches when the currencies
-- differ, so fx_sell_rate is NULL for a charge in the card's currency or a day
-- with no rate. product_id and card_expiration_date are used internally and
-- never returned to the agent.
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
       t.product_id,
       RIGHT(p.product_number, 4) AS card_last4,
       p.currency                 AS card_currency,
       p.expiration_date          AS card_expiration_date,
       t.merchant_name, t.merchant_category, t.amount, t.currency, t.channel,
       t.transaction_city, t.transaction_country, t.transaction_status, t.response_code,
       fx.sell_rate               AS fx_sell_rate
FROM transactions AS t
JOIN products AS p ON p.product_id = t.product_id
LEFT JOIN daily_exchange_rates AS fx
       ON fx.date = t.transaction_date::date
      AND fx.source_currency = t.currency
      AND fx.target_currency = p.currency
      AND t.currency <> p.currency
WHERE t.transaction_id = %(transaction_id)s
  AND t.customer_id = %(customer_id)s
  AND p.product_type = 'Tarjeta Crédito'
  AND t.transaction_date <= %(as_of)s
ORDER BY t.transaction_id, t.transaction_date DESC NULLS LAST, p.last_updated DESC NULLS LAST
```

- [ ] **Step 4: Write `queries/postgresql/transaction_habit.sql`**

```sql
-- transaction_habit (PostgreSQL dialect, runs on Aurora DSQL)
--
-- How a charge compares with its card's approved charges of the 90 days before
-- it: how many there were, how many at the same merchant, the usual amount range
-- in the charge's currency, and whether the charge's country was seen before.
-- Used by ExplainTransactionUseCase for the habit section.
--
-- customer_id and product_id come from the core query, which already checked
-- ownership and the credit-card filter. The charge itself is excluded. The
-- range is the 10th to 90th percentile of amounts in the same currency; Python
-- drops it when fewer than 3 such charges exist. Countries compare without
-- accents, case or spaces: translate() uses the same mapping list_card_transactions
-- uses for merchants, and lower() handles ASCII. A NULL merchant or country makes
-- its column NULL instead of a misleading 0 or FALSE. The aggregate always
-- returns exactly one row. process_date bounds the scan to the window's days.
--
-- Parameters (psycopg named placeholders):
--   customer_id          text       required
--   product_id           text       required
--   transaction_id       text       required, the charge being explained
--   charge_date          timestamp  required, the charge's transaction_date
--   merchant_name        text       nullable
--   currency             text       nullable
--   transaction_country  text       nullable
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster.
--   DISTINCT ON, NULLS LAST, FILTER, percentile_cont, bool_or, translate() and the
--   binds are standard PostgreSQL, but DSQL support is unverified. Column names
--   follow docs/LATAM_Bank_ERD.md; smoke-test against a real cluster.
-- TODO(ledgerlens): R8 - about 2 in 100 rows are duplicated; DISTINCT ON removes
--   them at query time. Drop it once the data load deduplicates.
WITH hist AS (
    SELECT DISTINCT ON (t.transaction_id)
           t.transaction_id, t.merchant_name, t.amount, t.currency, t.transaction_country
    FROM transactions AS t
    WHERE t.customer_id = %(customer_id)s
      AND t.product_id = %(product_id)s
      AND t.transaction_status = 'Approved'
      AND t.transaction_id <> %(transaction_id)s
      AND t.process_date >= (%(charge_date)s::date - 91)
      AND t.transaction_date >= %(charge_date)s - INTERVAL '90 days'
      AND t.transaction_date <  %(charge_date)s
    ORDER BY t.transaction_id, t.transaction_date DESC NULLS LAST
)
SELECT COUNT(*) AS history_count,
       CASE WHEN %(merchant_name)s::text IS NULL THEN NULL
            ELSE COUNT(*) FILTER (WHERE merchant_name = %(merchant_name)s::text) END AS times_at_merchant,
       COUNT(*) FILTER (WHERE currency = %(currency)s::text) AS same_currency_count,
       (percentile_cont(0.1) WITHIN GROUP (ORDER BY amount)
            FILTER (WHERE currency = %(currency)s::text))::numeric AS usual_low,
       (percentile_cont(0.9) WITHIN GROUP (ORDER BY amount)
            FILTER (WHERE currency = %(currency)s::text))::numeric AS usual_high,
       CASE WHEN %(transaction_country)s::text IS NULL THEN NULL
            ELSE COALESCE(bool_or(
                lower(translate(btrim(transaction_country), 'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÑÇáàâãäéèêëíìîïóòôõöúùûüñç', 'AAAAAEEEEIIIIOOOOOUUUUNCaaaaaeeeeiiiiooooouuuunc'))
                = lower(translate(btrim(%(transaction_country)s::text), 'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÑÇáàâãäéèêëíìîïóòôõöúùûüñç', 'AAAAAEEEEIIIIOOOOOUUUUNCaaaaaeeeeiiiiooooouuuunc'))), FALSE)
       END AS country_seen_before
FROM hist
```

The habit header doesn't contain the literal `customer_id = %(customer_id)s`; only the WHERE clause does, and that's where the contract test finds it. Don't add a `%` anywhere else in the header.

- [ ] **Step 5: Write `queries/postgresql/transaction_app_activity.sql`**

```sql
-- transaction_app_activity (PostgreSQL dialect, runs on Aurora DSQL)
--
-- The customer's app or web event closest to a charge, within 2 hours either
-- side. Used by ExplainTransactionUseCase for the app_activity section.
--
-- customer_id comes from the core query, which already checked ownership. Only
-- events with an IP country count, because the event is only useful to compare
-- countries. No row is the usual case (D36): few customers have app activity on
-- any given day, and Python reports it as found = false. Python decides whether
-- the countries conflict, and only for in-person channels. process_date bounds
-- the scan to the days around the charge; event_date <= as_of keeps the demo's
-- "now" honest. Ties on distance go to the lower event_id, so the answer is stable.
--
-- Parameters (psycopg named placeholders):
--   customer_id  text       required
--   charge_date  timestamp  required, the charge's transaction_date
--   as_of        timestamp  required, naive UTC
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster.
--   EXTRACT(EPOCH ...), interval arithmetic and the binds are standard PostgreSQL,
--   but DSQL support is unverified. Column names follow docs/LATAM_Bank_ERD.md;
--   smoke-test against a real cluster.
SELECT e.event_id, e.event_date, e.ip_country, e.ip_city
FROM digital_events AS e
WHERE e.customer_id = %(customer_id)s
  AND e.ip_country IS NOT NULL
  AND e.process_date BETWEEN (%(charge_date)s::date - 1) AND (%(charge_date)s::date + 1)
  AND e.event_date BETWEEN %(charge_date)s - INTERVAL '2 hours' AND %(charge_date)s + INTERVAL '2 hours'
  AND e.event_date <= %(as_of)s
ORDER BY ABS(EXTRACT(EPOCH FROM (e.event_date - %(charge_date)s))), e.event_id
LIMIT 1
```

This query has no R8 tag because it has no `DISTINCT ON`: `LIMIT 1` already returns a single row even when an event is duplicated.

- [ ] **Step 6: Write `gateway/tools/explain_transaction/tool_spec.json`**

```json
[
  {
    "name": "explain_transaction",
    "description": "Explains one credit-card charge so you can tell the customer what it is: the charge (merchant, amount, channel, place, status); 'fx' when it was in another currency (sell rate on that day and the amount in the card's currency, rate null if the bank has no rate for that day); 'decline' for declined charges (response code, its meaning, and contradicts_card_state = true when the code says expired but the card wasn't); 'habit' over the card's 90 days before the charge (how many approved charges, visits to this merchant, usual amount range, whether the country was seen before); 'app_activity': the customer's app or web session closest to the charge within 2 hours, with conflict = true when it was in another country during an in-person charge. App activity is usually not found; that's normal, not a sign of anything. This tool doesn't judge fraud: use transaction_fraud_detection for that. A null section couldn't be loaded and is named in 'unavailable'. Amounts are strings with 2 decimals.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "customer_id": { "type": "string", "description": "The authenticated customer's ID from SESSION CONTEXT." },
        "transaction_id": { "type": "string", "description": "The charge to explain, e.g. TRX-23BIJAU4GL46ATPW9STY." }
      },
      "required": ["customer_id", "transaction_id"]
    }
  }
]
```

- [ ] **Step 7: Run the contract tests to verify they pass**

Run: `$PY -m pytest tests/unit/explain_transaction/test_query_contracts.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: all pass, 0 failed (about 40 tests).

Also check the encoding directly:

```bash
for f in gateway/tools/explain_transaction/explain_transaction_lambda/queries/postgresql/*.sql; do head -c3 "$f" | od -An -tx1; done
```

Expected: no line reads `ef bb bf`.

- [ ] **Step 8: Lint**

Run: `$PY -m ruff format --check gateway/tools/explain_transaction tests/unit/explain_transaction </dev/null && $PY -m ruff check gateway/tools/explain_transaction tests/unit/explain_transaction </dev/null`
Expected: clean.

---

### Task 6: The presenter

**Files:**
- Create: `delivery/presenters/transaction_explanation.py`
- Test: `tests/unit/explain_transaction/test_transaction_explanation_presenter.py`

**Interfaces:**
- Consumes: the Task 4 entities (`TransactionExplanation`, `ExplainedTransaction`, `FxConversion`, `DeclineInfo`, `SpendingHabit`, `UsualAmountRange`, `AppActivity`, `Section`).
- Produces: `explain_transaction_lambda.delivery.presenters.transaction_explanation.present_transaction_explanation(explanation: TransactionExplanation) -> dict[str, Any]`. The result is JSON-safe: every value is a str, int, bool, None, list or dict. Task 8 dumps it with `json.dumps(body, ensure_ascii=False)`.
- **Output keys** (spec §5):
  - Top level: `transaction`, `fx`, `decline`, `habit`, `app_activity`, `unavailable`.
  - `transaction`: `transaction_id`, `transaction_date`, `card_last4`, `merchant_name`, `merchant_category`, `amount`, `currency`, `channel`, `transaction_city`, `transaction_country`, `transaction_status`.
  - `fx`: `card_currency`, `rate_date`, `rate`, `amount_in_card_currency`.
  - `decline`: `response_code`, `meaning`, `contradicts_card_state`.
  - `habit`: `history_count`, `times_at_merchant_90d`, `usual_amount_range`, `country_seen_before`. `usual_amount_range` is `{low, high, currency}` or null.
  - `app_activity`, when found: `found`, `event_date`, `minutes_from_charge`, `ip_country`, `ip_city`, `conflict`. When not found it is only `{"found": false}`, and when the query failed it is null.
  - `unavailable`: a list of section names.

- [ ] **Step 1: Write the failing tests**

`tests/unit/explain_transaction/test_transaction_explanation_presenter.py`:

```python
"""Tests for the transaction explanation presenter (spec section 5)."""

import dataclasses
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest
from explain_transaction_lambda.delivery.presenters.transaction_explanation import (
    present_transaction_explanation,
)
from explain_transaction_lambda.domain.entities.transaction_explanation import (
    AppActivity,
    DeclineInfo,
    ExplainedTransaction,
    FxConversion,
    Section,
    SpendingHabit,
    TransactionExplanation,
    UsualAmountRange,
)

from .fakes import CHARGE_DATE, TRANSACTION_ID

pytestmark = pytest.mark.unit

# Spec section 5, verbatim: P07's charge as the agent sees it.
P07_JSON = """
{
  "transaction": {
    "transaction_id": "TRX-23BIJAU4GL46ATPW9STY",
    "transaction_date": "2026-05-31T06:09:15",
    "card_last4": "4497",
    "merchant_name": "Estación de Servicio",
    "merchant_category": "Transport",
    "amount": "288.69",
    "currency": "USD",
    "channel": "Web",
    "transaction_city": "Ciudad de México",
    "transaction_country": "México",
    "transaction_status": "Approved"
  },
  "fx": null,
  "decline": null,
  "habit": {
    "history_count": 1,
    "times_at_merchant_90d": 0,
    "usual_amount_range": null,
    "country_seen_before": true
  },
  "app_activity": { "found": false },
  "unavailable": []
}
"""

P07 = TransactionExplanation(
    transaction=ExplainedTransaction(
        transaction_id=TRANSACTION_ID,
        transaction_date=CHARGE_DATE,
        card_last4="4497",
        merchant_name="Estación de Servicio",
        merchant_category="Transport",
        amount=Decimal("288.69"),
        currency="USD",
        channel="Web",
        transaction_city="Ciudad de México",
        transaction_country="México",
        transaction_status="Approved",
    ),
    fx=None,
    decline=None,
    habit=SpendingHabit(
        history_count=1,
        times_at_merchant_90d=0,
        usual_amount_range=None,
        country_seen_before=True,
    ),
    app_activity=AppActivity(found=False),
    unavailable=(),
)

FOUND = AppActivity(
    found=True,
    event_date=datetime(2026, 5, 31, 5, 39, 15),
    minutes_from_charge=-30,
    ip_country="Colombia",
    ip_city="Bogotá",
    conflict=True,
)


def present(**changes: Any) -> dict[str, Any]:
    """Present P07's explanation with some fields replaced."""
    return present_transaction_explanation(dataclasses.replace(P07, **changes))


def habit_with_range(low: Decimal, high: Decimal) -> SpendingHabit:
    """Return P07's habit with a usual range in USD."""
    return dataclasses.replace(
        P07.habit,  # type: ignore[arg-type]
        usual_amount_range=UsualAmountRange(low=low, high=high, currency="USD"),
    )


def keys(value: object) -> set[str]:
    """Return every dict key at any depth."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys(v)}
    return set()


def test_p07_matches_the_spec_example() -> None:
    assert present_transaction_explanation(P07) == json.loads(P07_JSON)


def test_output_survives_a_json_round_trip() -> None:
    body = present(
        fx=FxConversion("USD", date(2026, 5, 31), Decimal("0.00025"), Decimal("100")),
        decline=DeclineInfo("54", "expired card", True),
        habit=habit_with_range(Decimal("10"), Decimal("90")),
        app_activity=FOUND,
    )

    assert json.loads(json.dumps(body, ensure_ascii=False)) == body


def test_amounts_are_two_decimal_strings() -> None:
    transaction = dataclasses.replace(P07.transaction, amount=Decimal("288.685"))

    assert present(transaction=transaction)["transaction"]["amount"] == "288.69"


def test_missing_transaction_values_stay_null() -> None:
    transaction = dataclasses.replace(
        P07.transaction, transaction_date=None, amount=None, channel=None
    )

    presented = present(transaction=transaction)["transaction"]

    assert presented["transaction_date"] is None
    assert presented["amount"] is None
    assert presented["channel"] is None


def test_fx_is_presented() -> None:
    fx = FxConversion("USD", date(2026, 5, 31), Decimal("0.00025"), Decimal("100.00"))

    assert present(fx=fx)["fx"] == {
        "card_currency": "USD",
        "rate_date": "2026-05-31",
        "rate": "0.00025",
        "amount_in_card_currency": "100.00",
    }


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        (Decimal("0.00025"), "0.00025"),
        (Decimal("0.0002500"), "0.0002500"),
        (Decimal("1E+1"), "10"),
        (Decimal("1E-7"), "0.0000001"),
        (Decimal("4150.75"), "4150.75"),
    ],
)
def test_rate_keeps_its_decimals_in_plain_notation(rate: Decimal, expected: str) -> None:
    fx = FxConversion("USD", date(2026, 5, 31), rate, Decimal("1"))

    assert present(fx=fx)["fx"]["rate"] == expected


def test_fx_without_a_rate_keeps_nulls() -> None:
    fx = FxConversion("USD", None, None, None)

    assert present(fx=fx)["fx"] == {
        "card_currency": "USD",
        "rate_date": None,
        "rate": None,
        "amount_in_card_currency": None,
    }


def test_decline_is_presented() -> None:
    decline = DeclineInfo("14", "invalid card number", False)

    assert present(decline=decline)["decline"] == {
        "response_code": "14",
        "meaning": "invalid card number",
        "contradicts_card_state": False,
    }


def test_decline_with_unknown_values_keeps_nulls() -> None:
    decline = DeclineInfo(None, None, None)

    assert present(decline=decline)["decline"] == {
        "response_code": None,
        "meaning": None,
        "contradicts_card_state": None,
    }


@pytest.mark.parametrize(
    ("low", "high", "expected_low", "expected_high"),
    [
        (Decimal("123.4500000000001"), Decimal("310.2499999999"), "123.45", "310.25"),
        (Decimal("20.5"), Decimal("99.995"), "20.50", "100.00"),
        (Decimal("10"), Decimal("90"), "10.00", "90.00"),
    ],
)
def test_usual_range_is_quantized(
    low: Decimal, high: Decimal, expected_low: str, expected_high: str
) -> None:
    habit = present(habit=habit_with_range(low, high))["habit"]

    assert habit["usual_amount_range"] == {
        "low": expected_low,
        "high": expected_high,
        "currency": "USD",
    }


def test_habit_keeps_its_nulls() -> None:
    habit = SpendingHabit(
        history_count=0,
        times_at_merchant_90d=None,
        usual_amount_range=None,
        country_seen_before=None,
    )

    assert present(habit=habit)["habit"] == {
        "history_count": 0,
        "times_at_merchant_90d": None,
        "usual_amount_range": None,
        "country_seen_before": None,
    }


def test_found_app_activity_is_presented() -> None:
    assert present(app_activity=FOUND)["app_activity"] == {
        "found": True,
        "event_date": "2026-05-31T05:39:15",
        "minutes_from_charge": -30,
        "ip_country": "Colombia",
        "ip_city": "Bogotá",
        "conflict": True,
    }


def test_app_activity_not_found_is_only_found_false() -> None:
    assert present(app_activity=AppActivity(found=False))["app_activity"] == {
        "found": False
    }


def test_failed_sections_are_null_and_named() -> None:
    body = present(
        habit=None,
        app_activity=None,
        unavailable=(Section.HABIT, Section.APP_ACTIVITY),
    )

    assert body["habit"] is None
    assert body["app_activity"] is None
    assert body["unavailable"] == ["habit", "app_activity"]


def test_no_key_mentions_fraud_or_score() -> None:
    body = present(
        fx=FxConversion("USD", date(2026, 5, 31), Decimal("0.00025"), Decimal("100")),
        decline=DeclineInfo("54", "expired card", True),
        habit=habit_with_range(Decimal("10"), Decimal("90")),
        app_activity=FOUND,
    )

    all_keys = keys(body)
    assert "found" in all_keys  # the walk reached the nested sections
    assert not [key for key in all_keys if "fraud" in key or "score" in key]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/unit/explain_transaction/test_transaction_explanation_presenter.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: an error during collection, `ModuleNotFoundError: No module named 'explain_transaction_lambda.delivery.presenters.transaction_explanation'`.

- [ ] **Step 3: Write the presenter**

`delivery/presenters/transaction_explanation.py`:

```python
"""Present a transaction explanation as the JSON returned to the agent."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from explain_transaction_lambda.domain.entities.transaction_explanation import (
    AppActivity,
    DeclineInfo,
    ExplainedTransaction,
    FxConversion,
    SpendingHabit,
    TransactionExplanation,
    UsualAmountRange,
)

_CENTS: Final = Decimal("0.01")


def present_transaction_explanation(
    explanation: TransactionExplanation,
) -> dict[str, Any]:
    """Return the explanation as JSON-safe values (spec section 5).

    Amounts are 2-decimal strings rounded half up; the rate keeps its stored
    decimals. Timestamps are ISO 8601 without a time zone, as stored. Missing
    values stay None. There is no fraud or score field.
    """
    return {
        "transaction": _transaction(explanation.transaction),
        "fx": _fx(explanation.fx),
        "decline": _decline(explanation.decline),
        "habit": _habit(explanation.habit),
        "app_activity": _app_activity(explanation.app_activity),
        "unavailable": [section.value for section in explanation.unavailable],
    }


def _transaction(transaction: ExplainedTransaction) -> dict[str, Any]:
    """Present the charge itself."""
    return {
        "transaction_id": transaction.transaction_id,
        "transaction_date": _iso(transaction.transaction_date),
        "card_last4": transaction.card_last4,
        "merchant_name": transaction.merchant_name,
        "merchant_category": transaction.merchant_category,
        "amount": _amount(transaction.amount),
        "currency": transaction.currency,
        "channel": transaction.channel,
        "transaction_city": transaction.transaction_city,
        "transaction_country": transaction.transaction_country,
        "transaction_status": transaction.transaction_status,
    }


def _fx(fx: FxConversion | None) -> dict[str, Any] | None:
    """Present the conversion; the rate in plain notation, never exponent form."""
    if fx is None:
        return None
    return {
        "card_currency": fx.card_currency,
        "rate_date": _iso(fx.rate_date),
        "rate": None if fx.rate is None else format(fx.rate, "f"),
        "amount_in_card_currency": _amount(fx.amount_in_card_currency),
    }


def _decline(decline: DeclineInfo | None) -> dict[str, Any] | None:
    """Present why the charge was declined."""
    if decline is None:
        return None
    return {
        "response_code": decline.response_code,
        "meaning": decline.meaning,
        "contradicts_card_state": decline.contradicts_card_state,
    }


def _habit(habit: SpendingHabit | None) -> dict[str, Any] | None:
    """Present the habit; None means its query failed."""
    if habit is None:
        return None
    return {
        "history_count": habit.history_count,
        "times_at_merchant_90d": habit.times_at_merchant_90d,
        "usual_amount_range": _usual_range(habit.usual_amount_range),
        "country_seen_before": habit.country_seen_before,
    }


def _usual_range(usual: UsualAmountRange | None) -> dict[str, Any] | None:
    """Present the range rounded to cents: percentile_cont leaves float noise."""
    if usual is None:
        return None
    return {
        "low": _amount(usual.low),
        "high": _amount(usual.high),
        "currency": usual.currency,
    }


def _app_activity(app_activity: AppActivity | None) -> dict[str, Any] | None:
    """Present the closest event; only ``found`` when there was none."""
    if app_activity is None:
        return None
    if not app_activity.found:
        return {"found": False}
    return {
        "found": True,
        "event_date": _iso(app_activity.event_date),
        "minutes_from_charge": app_activity.minutes_from_charge,
        "ip_country": app_activity.ip_country,
        "ip_city": app_activity.ip_city,
        "conflict": app_activity.conflict,
    }


def _iso(value: date | None) -> str | None:
    """Return an ISO 8601 string of a date or timestamp, keeping None."""
    return None if value is None else value.isoformat()


def _amount(value: Decimal | None) -> str | None:
    """Return a 2-decimal string rounded half up, keeping None."""
    if value is None:
        return None
    return str(value.quantize(_CENTS, rounding=ROUND_HALF_UP))
```

- [ ] **Step 4: Run them to verify they pass**

Run: `$PY -m pytest tests/unit/explain_transaction/test_transaction_explanation_presenter.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: all pass, 0 failed (about 22 tests).

- [ ] **Step 5: Lint**

Run: `$PY -m ruff format --check gateway/tools/explain_transaction tests/unit/explain_transaction </dev/null && $PY -m ruff check gateway/tools/explain_transaction tests/unit/explain_transaction </dev/null`
Expected: clean.

---

### Task 7: The dependency builder

**Files:**
- Create: `delivery/dependencies/dependencies_builder.py` (sed copy of the get_session_context builder, then two changes)
- Test: `tests/unit/explain_transaction/test_delivery_wiring.py`

**Interfaces:**
- Consumes:
  - `ExplainTransactionUseCase(database_repository=..., query_provider=...)` from Task 4. It takes no `max_rows`.
  - The three SQL files from Task 5, found under `QUERIES_ROOT / "postgresql"`.
  - The copied `delivery/settings.py`, adapters and connectors from Task 1.
  - From `fakes.py`: `FakeConnector`, `make_any_row`, `CUSTOMER_ID`, `TRANSACTION_ID`, `PRODUCT_ID`, `CHARGE_DATE`, `QUERY_NAMES`.
- Produces, in `explain_transaction_lambda.delivery.dependencies.dependencies_builder`, for Task 8:
  - `build_explain_transaction_use_case(env: Mapping[str, str]) -> ExplainTransactionUseCase | None`. It never raises.
  - `build_clock(env: Mapping[str, str]) -> ClockSettings | None`. It never raises.
  - `build_database_repository(engine, connector) -> DatabaseRepository`.
  - `build_query_provider(engine) -> QueryProvider`.
  - Also `QUERIES_ROOT`, `SQL_DIALECTS`, `build_settings`, `build_dsql_settings`, `build_connector`, all unchanged from the copy.

- [ ] **Step 1: Write the failing tests**

`tests/unit/explain_transaction/test_delivery_wiring.py`:

```python
"""Tests for the dependency wiring of the explain_transaction tool."""

from datetime import datetime, timezone

import explain_transaction_lambda.utils.connectors.dsql as dsql_module
import pytest
from explain_transaction_lambda.application.ports.errors import (
    DataSourceConnectionError,
)
from explain_transaction_lambda.application.use_cases.explain_transaction import (
    ExplainTransactionUseCase,
)
from explain_transaction_lambda.delivery.dependencies import dependencies_builder
from explain_transaction_lambda.delivery.dependencies.dependencies_builder import (
    QUERIES_ROOT,
    SQL_DIALECTS,
    build_clock,
    build_connector,
    build_database_repository,
    build_dsql_settings,
    build_explain_transaction_use_case,
    build_query_provider,
    build_settings,
)
from explain_transaction_lambda.delivery.settings import (
    ClockSettings,
    ConfigurationError,
    DatabaseEngine,
    DatabaseSettings,
    DsqlSettings,
)
from explain_transaction_lambda.infrastructure.repositories.dsql_repository import (
    DsqlRepository,
)
from explain_transaction_lambda.utils.connectors.dsql import DsqlConnector

from .fakes import (
    CHARGE_DATE,
    CUSTOMER_ID,
    PRODUCT_ID,
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
    assert "Invalid AS_OF for explain_transaction" in caplog.text


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
    assert "DISTINCT ON" in provider.get("explain_transaction")


def test_every_engine_has_a_dialect_folder_with_every_query() -> None:
    for engine in DatabaseEngine:
        for name in QUERY_NAMES:
            assert (QUERIES_ROOT / SQL_DIALECTS[engine] / f"{name}.sql").is_file()


def test_queries_root_is_this_tools_own_folder() -> None:
    assert QUERIES_ROOT.parent.name == "explain_transaction_lambda"


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


def test_use_case_is_wired_with_real_adapters_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector([make_any_row()])
    use_fake_connector(monkeypatch, connector)

    use_case = build_explain_transaction_use_case(ENV)
    assert isinstance(use_case, ExplainTransactionUseCase)
    explanation = use_case.execute(CUSTOMER_ID, TRANSACTION_ID, as_of=AS_OF)

    assert explanation.transaction.transaction_id == TRANSACTION_ID
    assert explanation.unavailable == ()
    assert explanation.app_activity is not None
    assert explanation.app_activity.found is True
    # The eager cold-start connection is the one every query runs on.
    assert len(connector.connections) == 1
    queries = executed(connector)
    assert len(queries) == 3
    assert "FROM transactions AS t" in queries[0][0]
    assert queries[0][1] == {
        "customer_id": CUSTOMER_ID,
        "transaction_id": TRANSACTION_ID,
        "as_of": AS_OF_SQL,
    }
    assert queries[1][1]["product_id"] == PRODUCT_ID
    assert queries[1][1]["charge_date"] == CHARGE_DATE
    assert queries[2][1] == {
        "customer_id": CUSTOMER_ID,
        "charge_date": CHARGE_DATE,
        "as_of": AS_OF_SQL,
    }


def test_max_rows_is_still_parsed_but_unused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector([make_any_row()])
    use_fake_connector(monkeypatch, connector)

    use_case = build_explain_transaction_use_case({**ENV, "MAX_ROWS": "3"})

    assert use_case is not None
    assert use_case.execute(CUSTOMER_ID, TRANSACTION_ID, as_of=AS_OF).unavailable == ()


def test_use_case_build_opens_the_connection_eagerly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector()
    use_fake_connector(monkeypatch, connector)

    build_explain_transaction_use_case(ENV)

    assert len(connector.connections) == 1


def test_use_case_build_survives_a_failed_cold_start_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector(
        DataSourceConnectionError("no route to host"), [make_any_row()]
    )
    use_fake_connector(monkeypatch, connector)

    use_case = build_explain_transaction_use_case(ENV)

    assert use_case is not None
    assert use_case.execute(CUSTOMER_ID, TRANSACTION_ID, as_of=AS_OF).unavailable == ()


@pytest.mark.parametrize(
    "env",
    [
        {},
        {**ENV, "DB_ENGINE": "oracle"},
        {**ENV, "DB_ENGINE": "postgresql"},
        {**ENV, "MAX_ROWS": "0"},
        {"AWS_REGION": "us-east-1"},
        {"DSQL_CLUSTER_ENDPOINT": ENDPOINT},
        {**ENV, "DSQL_CLUSTER_ENDPOINT": f"https://{ENDPOINT}"},
    ],
)
def test_use_case_build_with_bad_configuration_returns_none(
    env: dict[str, str],
) -> None:
    assert build_explain_transaction_use_case(env) is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/unit/explain_transaction/test_delivery_wiring.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: a collection error, `ModuleNotFoundError: No module named 'explain_transaction_lambda.delivery.dependencies.dependencies_builder'`.

- [ ] **Step 3: Copy the builder and make the two changes**

```bash
SRC=gateway/tools/get_session_context/get_session_context_lambda/delivery/dependencies/dependencies_builder.py
DST=gateway/tools/explain_transaction/explain_transaction_lambda/delivery/dependencies/dependencies_builder.py
sed -e 's/get_session_context/explain_transaction/g' \
    -e 's/GetSessionContextUseCase/ExplainTransactionUseCase/g' \
    -e '/max_rows=settings.max_rows,/d' \
    "$SRC" > "$DST"
grep -n "max_rows\|GetSessionContext\|get_session_context" "$DST"
grep -n "def build_explain_transaction_use_case\|ExplainTransactionUseCase(" "$DST"
```

Expected:
- The first grep prints nothing.
- The second grep prints the `def build_explain_transaction_use_case(` line and the `use_case = ExplainTransactionUseCase(` line.

Ruling 1 explains why the `max_rows=` line goes. `DatabaseSettings` still parses `MAX_ROWS`, so a bad value still makes the build return `None`. The `{**ENV, "MAX_ROWS": "0"}` case checks this.

`delivery/dependencies/__init__.py` came over in Task 1. If it's missing, stop: Task 1 is incomplete.

- [ ] **Step 4: Run them to verify they pass**

Run: `$PY -m pytest tests/unit/explain_transaction/test_delivery_wiring.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: `24 passed`.

- [ ] **Step 5: Check isolation and lint**

```bash
grep -rnE "(get_session_context|list_credit_cards|list_card_transactions|transaction_fraud_detection)_lambda" gateway/tools/explain_transaction tests/unit/explain_transaction
$PY -m ruff format --check gateway/tools/explain_transaction tests/unit/explain_transaction </dev/null
$PY -m ruff check gateway/tools/explain_transaction tests/unit/explain_transaction </dev/null
```

Expected: the grep prints nothing and both ruff commands are clean. If `ruff format --check` only flags the builder because the new names are longer, run `$PY -m ruff format gateway/tools/explain_transaction/explain_transaction_lambda/delivery/dependencies/dependencies_builder.py </dev/null` once and re-check.

---

### Task 8: The handler

**Files:**
- Create: `delivery/handler.py`
- Test: `tests/unit/explain_transaction/test_explain_transaction_handler.py`

**Interfaces:**
- Consumes:
  - From Task 7: `build_explain_transaction_use_case`, `build_clock`, `build_database_repository` and `build_query_provider`.
  - From Task 6: `present_transaction_explanation`.
  - From Task 2: `DomainError` and `DataSourceUnavailableError`.
  - From Task 4: `ExplainTransactionUseCase.execute(customer_id: object, transaction_id: object, as_of: datetime)`.
  - From `fakes.py`: `FakeExplainRepository`, `FakeQueryProvider`, `FakeConnector`, `explain_responses`, `make_core_row`, `make_any_row`, `Outcome`, `CUSTOMER_ID`, `TRANSACTION_ID`, `QUERY_NAMES`.
- Produces: `explain_transaction_lambda.delivery.handler.handler(event: object, context: object) -> dict[str, Any]`. Its handler string is `explain_transaction_lambda/delivery/handler.handler`, which the CDK loop in Task 9 derives from the tool name. The module also has:
  - `TOOL_NAME = "explain_transaction"`
  - `UNEXPECTED_ERROR_MESSAGE`
  - `USE_CASE` and `CLOCK`, both built when the module loads.

- [ ] **Step 1: Write the failing tests**

`tests/unit/explain_transaction/test_explain_transaction_handler.py`:

```python
"""Tests for the explain_transaction Lambda handler."""

import importlib
import json
import logging
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from typing import Any

import psycopg
import pytest
from explain_transaction_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryExecutionError,
)
from explain_transaction_lambda.application.use_cases.explain_transaction import (
    ExplainTransactionUseCase,
)
from explain_transaction_lambda.delivery.dependencies.dependencies_builder import (
    build_database_repository,
    build_query_provider,
)
from explain_transaction_lambda.delivery.settings import ClockSettings, DatabaseEngine
from explain_transaction_lambda.domain.errors import (
    DataSourceUnavailableError,
    ExplainDataIntegrityError,
    ExplainLookupError,
    TransactionNotFoundError,
)

from .fakes import (
    CUSTOMER_ID,
    QUERY_NAMES,
    TRANSACTION_ID,
    FakeConnector,
    FakeExplainRepository,
    FakeQueryProvider,
    Outcome,
    explain_responses,
    make_any_row,
    make_core_row,
)

pytestmark = pytest.mark.unit

EVENT = {"customer_id": CUSTOMER_ID, "transaction_id": TRANSACTION_ID}
AS_OF = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
# What the SQL receives: the same instant as naive UTC.
AS_OF_SQL = datetime(2026, 6, 17, 23, 59, 59)
INVALID_CUSTOMER_ID = (
    "Invalid value for 'customer_id': is required and must be a non-empty "
    "string. Ask the customer to confirm and retry."
)
INVALID_TRANSACTION_ID = (
    "Invalid value for 'transaction_id': is required and must be a non-empty "
    "string. Ask the customer to confirm and retry."
)
OUTPUT_KEYS = ["transaction", "fx", "decline", "habit", "app_activity", "unavailable"]


def make_context(
    tool_name: str = "explain-transaction-target___explain_transaction",
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
    import explain_transaction_lambda.delivery.handler as handler_module

    return importlib.reload(handler_module)


def wire(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, Outcome] | None = None,
) -> FakeExplainRepository:
    """Point the handler at a use case over a fake repository and a fixed clock."""
    database_repository = FakeExplainRepository(
        explain_responses() if responses is None else responses
    )
    use_case = ExplainTransactionUseCase(
        database_repository=database_repository, query_provider=FakeQueryProvider()
    )
    monkeypatch.setattr(module, "USE_CASE", use_case)
    monkeypatch.setattr(module, "CLOCK", ClockSettings(as_of=AS_OF))
    return database_repository


def wire_connector(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, connector: Any
) -> None:
    """Point the handler at real adapters over a fake connector and a fixed clock."""
    use_case = ExplainTransactionUseCase(
        database_repository=build_database_repository(
            DatabaseEngine.AURORA_DSQL, connector
        ),
        query_provider=build_query_provider(DatabaseEngine.AURORA_DSQL),
    )
    monkeypatch.setattr(module, "USE_CASE", use_case)
    monkeypatch.setattr(module, "CLOCK", ClockSettings(as_of=AS_OF))


def text(response: dict[str, Any]) -> str:
    """Return the JSON text of a success response."""
    content = response["content"]
    assert content[0]["type"] == "text"
    return content[0]["text"]


def body(response: dict[str, Any]) -> dict[str, Any]:
    """Decode the JSON text of a success response."""
    return json.loads(text(response))


def test_success_returns_gateway_content_with_the_explanation(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch)

    response = module.handler(EVENT, make_context())
    payload = body(response)

    assert list(payload) == OUTPUT_KEYS
    assert payload["transaction"]["transaction_id"] == TRANSACTION_ID
    assert payload["transaction"]["amount"] == "288.69"
    assert payload["fx"] is None
    assert payload["decline"] is None
    assert payload["habit"]["history_count"] == 1
    assert payload["app_activity"] == {"found": False}
    assert payload["unavailable"] == []
    # ensure_ascii=False: accents reach the agent as they are.
    assert "Estación de Servicio" in text(response)


def test_success_over_real_adapters(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire_connector(module, monkeypatch, FakeConnector([make_any_row()]))

    payload = body(module.handler(EVENT, make_context()))

    assert payload["transaction"]["transaction_id"] == TRANSACTION_ID
    assert payload["app_activity"]["found"] is True
    assert payload["unavailable"] == []


def test_both_ids_and_now_reach_the_use_case(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_repository = wire(module, monkeypatch)

    module.handler(
        {
            "customer_id": " cli-ex6boaoefzhq ",
            "transaction_id": " trx-23bijau4gl46atpw9sty ",
        },
        make_context(),
    )

    assert database_repository.queries == list(QUERY_NAMES)
    assert database_repository.calls[0][1] == {
        "customer_id": CUSTOMER_ID,
        "transaction_id": TRANSACTION_ID,
        "as_of": AS_OF_SQL,
    }


def test_unknown_event_keys_are_ignored(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_repository = wire(module, monkeypatch)

    response = module.handler({**EVENT, "as_of": "2020-01-01"}, make_context())

    assert "content" in response
    assert database_repository.calls[0][1]["as_of"] == AS_OF_SQL


def test_a_failed_section_comes_back_null_and_unavailable(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(
        module,
        monkeypatch,
        explain_responses(
            transaction_habit=QueryExecutionError(
                "function percentile_cont is not supported"
            )
        ),
    )

    payload = body(module.handler(EVENT, make_context()))

    assert payload["habit"] is None
    assert payload["unavailable"] == ["habit"]
    assert payload["app_activity"] == {"found": False}


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

    module.handler(EVENT, make_context())
    module.handler(EVENT, make_context())

    sent = [
        params["as_of"]
        for name, params in database_repository.calls
        if name == "explain_transaction"
    ]
    assert sent == [datetime(2026, 6, 17, 23, 59, 59), datetime(2026, 6, 18, 8, 30)]


@pytest.mark.parametrize(
    "event",
    [
        None,
        [],
        "customer_id=CLI-EX6BOAOEFZHQ",
        {},
        {"transaction_id": TRANSACTION_ID},
        {"customer_id": None, "transaction_id": TRANSACTION_ID},
        {"customer_id": "", "transaction_id": TRANSACTION_ID},
        {"customer_id": "   ", "transaction_id": TRANSACTION_ID},
        {"customer_id": 42, "transaction_id": TRANSACTION_ID},
        {"customer_id": True, "transaction_id": TRANSACTION_ID},
    ],
)
def test_invalid_customer_id_returns_the_input_error_without_a_query(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, event: object
) -> None:
    database_repository = wire(module, monkeypatch)

    response = module.handler(event, make_context())

    assert response == {"error": INVALID_CUSTOMER_ID}
    assert database_repository.calls == []


@pytest.mark.parametrize(
    "transaction_id", [None, "", "   ", 42, True, ["TRX-23BIJAU4GL46ATPW9STY"]]
)
def test_invalid_transaction_id_returns_the_input_error_without_a_query(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, transaction_id: object
) -> None:
    database_repository = wire(module, monkeypatch)

    response = module.handler(
        {"customer_id": CUSTOMER_ID, "transaction_id": transaction_id},
        make_context(),
    )

    assert response == {"error": INVALID_TRANSACTION_ID}
    assert database_repository.calls == []


def test_a_missing_transaction_id_returns_the_input_error(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_repository = wire(module, monkeypatch)

    response = module.handler({"customer_id": CUSTOMER_ID}, make_context())

    assert response == {"error": INVALID_TRANSACTION_ID}
    assert database_repository.calls == []


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        (DataSourceConnectionError("down"), DataSourceUnavailableError.MESSAGE),
        (QueryExecutionError("boom"), ExplainLookupError.MESSAGE),
        ([], TransactionNotFoundError.MESSAGE),
        ([make_core_row(transaction_id=None)], ExplainDataIntegrityError.MESSAGE),
    ],
    ids=["unavailable", "lookup", "not-found", "integrity"],
)
def test_a_core_failure_returns_its_message(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    outcome: Outcome,
    message: str,
) -> None:
    database_repository = wire(
        module, monkeypatch, explain_responses(explain_transaction=outcome)
    )

    assert module.handler(EVENT, make_context()) == {"error": message}
    assert database_repository.queries == ["explain_transaction"]


def test_query_failure_over_real_adapters_returns_the_lookup_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = psycopg.errors.UndefinedTable('relation "transactions" does not exist')
    wire_connector(module, monkeypatch, FakeConnector(error))

    response = module.handler(EVENT, make_context())

    assert response == {"error": ExplainLookupError.MESSAGE}


@pytest.mark.parametrize(
    "context",
    [
        make_context("other-target___text_analysis_tool"),
        make_context("fraud-target___transaction_fraud_detection"),
        None,
        SimpleNamespace(client_context=None),
        SimpleNamespace(client_context=SimpleNamespace(custom={})),
        SimpleNamespace(client_context=SimpleNamespace(custom=None)),
        make_context(42),  # type: ignore[arg-type]
    ],
)
def test_wrong_or_missing_tool_name_returns_an_error(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, context: object
) -> None:
    database_repository = wire(module, monkeypatch)

    response = module.handler(EVENT, context)

    assert set(response) == {"error"}
    assert "explain_transaction" in response["error"]
    assert database_repository.calls == []


def test_tool_name_without_a_target_prefix_is_accepted(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch)

    assert "content" in module.handler(EVENT, make_context("explain_transaction"))


def test_unexpected_exception_returns_a_generic_message_without_internals(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("password=hunter2 host=db.internal")

    monkeypatch.setattr(module, "USE_CASE", SimpleNamespace(execute=explode))
    monkeypatch.setattr(module, "CLOCK", ClockSettings(as_of=AS_OF))

    response = module.handler(EVENT, make_context())

    assert response == {"error": module.UNEXPECTED_ERROR_MESSAGE}
    assert module.UNEXPECTED_ERROR_MESSAGE == (
        "Unexpected internal error explaining the charge. "
        "Offer a hand-off to a human agent."
    )
    assert "hunter2" not in response["error"]


def test_missing_configuration_returns_data_source_unavailable(
    module: ModuleType,
) -> None:
    assert module.USE_CASE is None

    response = module.handler(EVENT, make_context())

    assert response == {"error": DataSourceUnavailableError.MESSAGE}


def test_missing_clock_returns_data_source_unavailable(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_repository = wire(module, monkeypatch)
    monkeypatch.setattr(module, "CLOCK", None)

    response = module.handler(EVENT, make_context())

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

    response = module.handler(EVENT, make_context())

    assert response == {"error": DataSourceUnavailableError.MESSAGE}


def test_success_log_names_unavailable_but_no_customer_data(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    wire(
        module,
        monkeypatch,
        explain_responses(transaction_habit=QueryExecutionError("boom")),
    )
    caplog.set_level(logging.INFO)

    module.handler(EVENT, make_context())

    assert (
        "explain_transaction returned explanation (unavailable=['habit'])"
        in caplog.text
    )
    for private in (
        CUSTOMER_ID,
        TRANSACTION_ID,
        "Estación",
        "288.69",
        "Ciudad de México",
    ):
        assert private not in caplog.text
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/unit/explain_transaction/test_explain_transaction_handler.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: every test errors with `ModuleNotFoundError: No module named 'explain_transaction_lambda.delivery.handler'`, raised from the `module` fixture.

- [ ] **Step 3: Write the handler**

`delivery/handler.py` is new, so write the whole file. Don't sed-copy it.

```python
"""Lambda handler for the ``explain_transaction`` Gateway tool.

Handler string: ``explain_transaction_lambda/delivery/handler.handler``.

Input: the tool arguments as the event (see
``gateway/tools/explain_transaction/tool_spec.json``); the tool name arrives in
``context.client_context.custom["bedrockAgentCoreToolName"]`` with a
``<target>___`` prefix, as in ``gateway/tools/sample_tool``. ``customer_id``
and ``transaction_id`` are passed to the use case bare, exactly as they came;
the use case cleans them.

Output: ``{"content": [{"type": "text", "text": <JSON>}]}`` on success, or
``{"error": <agent-facing message>}``. Only a failure of the core query (the
charge) is an error; a failed habit or app-activity section comes back null and
is named in ``unavailable``. Raw exception text is never returned: it could
leak SQL, hosts or driver details to the model.

The use case and its whole graph (settings, connector, connection, adapters) are
built once, when the module loads, by dependencies_builder; a warm container
reuses them. The handler builds nothing itself.

AS_OF (optional) is read once into CLOCK; "now" is CLOCK.now() on every call,
so a warm container never freezes the real clock. An invalid AS_OF answers every
request with DataSourceUnavailableError's message.

TODO(ledgerlens): R5 - customer_id is trusted from the tool input. Authorization
  depends on a Cedar policy matching it to the token's customer_id claim; neither
  the policy nor the claim exists yet (product design sections 5 and 10).
"""

import json
import logging
import os
from collections.abc import Mapping
from typing import Any, Final

from explain_transaction_lambda.delivery.dependencies.dependencies_builder import (
    build_clock,
    build_explain_transaction_use_case,
)
from explain_transaction_lambda.delivery.presenters.transaction_explanation import (
    present_transaction_explanation,
)
from explain_transaction_lambda.domain.errors import (
    DataSourceUnavailableError,
    DomainError,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TOOL_NAME: Final = "explain_transaction"
_TOOL_NAME_DELIMITER: Final = "___"
UNEXPECTED_ERROR_MESSAGE: Final = (
    "Unexpected internal error explaining the charge. "
    "Offer a hand-off to a human agent."
)
_WRONG_TOOL_MESSAGE: Final = (
    f"This function only serves the '{TOOL_NAME}' tool. "
    "Don't retry; offer a hand-off to a human agent."
)


USE_CASE = build_explain_transaction_use_case(os.environ)
CLOCK = build_clock(os.environ)


def handler(event: object, context: object) -> dict[str, Any]:
    """Explain one credit-card charge for the agent.

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
        body = present_transaction_explanation(
            USE_CASE.execute(
                _argument(event, "customer_id"),
                _argument(event, "transaction_id"),
                as_of=CLOCK.now(),
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

    logger.info(
        "%s returned explanation (unavailable=%s)", TOOL_NAME, body["unavailable"]
    )
    return {"content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]}


def _argument(event: object, name: str) -> object:
    """Return the event's ``name`` argument as it came, or None for a non-object event.

    The use case validates and cleans it, so a bad value becomes that
    argument's InvalidInputError message.
    """
    if not isinstance(event, Mapping):
        return None
    return event.get(name)


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

The get_session_context docstring has an R1 TODO saying there is no CDK yet. It's dropped here because Task 9 adds the CDK.

- [ ] **Step 4: Run them to verify they pass**

Run: `$PY -m pytest tests/unit/explain_transaction/test_explain_transaction_handler.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: `43 passed`.

- [ ] **Step 5: Run the tool's tests, check isolation and lint**

```bash
$PY -m pytest tests/unit/explain_transaction -q -p no:cacheprovider </dev/null 2>&1 | tail -2
grep -rnE "(get_session_context|list_credit_cards|list_card_transactions|transaction_fraud_detection)_lambda" gateway/tools/explain_transaction tests/unit/explain_transaction
grep -rnE "fraud_score|is_fraud" gateway/tools/explain_transaction
$PY -m ruff format --check gateway/tools/explain_transaction tests/unit/explain_transaction </dev/null
$PY -m ruff check gateway/tools/explain_transaction tests/unit/explain_transaction </dev/null
```

Expected:
- All tests pass, 0 failed.
- Both greps print nothing. The tool spec's mention of `transaction_fraud_detection` doesn't match either pattern.
- Both ruff commands are clean.

---

### Task 9: CDK

**Files:**
- Modify: `infra-cdk/lib/data-construct.ts`, the `tools` array near line 216. It already has the uncommitted `transaction_fraud_detection` entry.
- Modify: `infra-cdk/test/data-construct.test.ts`, line 65 and the `test.each` table near line 86.

**Interfaces:**
- Consumes: the tool folder from Tasks 1–8. The `PythonFunction` loop bundles `gateway/tools/<tool>/` and uses the handler `<tool>_lambda.delivery.handler.handler`.
- Produces: the CDK function `ledgerlens-explain-transaction`, which is deployed in Task 11.

- [ ] **Step 1: Change the test first**

In `infra-cdk/test/data-construct.test.ts`, change:

```ts
  expect(vpcFns).toHaveLength(5) // the read check and the four tools
```

to:

```ts
  expect(vpcFns).toHaveLength(6) // the read check and the five tools
```

Then add a row to the `test.each` table, after the `transaction_fraud_detection` row:

```ts
  ["explain_transaction", "ledgerlens-explain-transaction"],
```

- [ ] **Step 2: Run the CDK test to see it fail**

Run: `cd infra-cdk && npx jest test/data-construct.test.ts 2>&1 | tail -15; cd ..`
Expected: 2 failures.
- The VPC count test: expected 6, received 5.
- The new `explain_transaction` row: there's no function named `ledgerlens-explain-transaction`.

- [ ] **Step 3: Add the tool to the stack**

In `infra-cdk/lib/data-construct.ts`, add one entry to the `tools` array, after `transaction_fraud_detection`:

```ts
      { tool: "explain_transaction", id: "ExplainTransaction" },
```

The loop already sets the function name, VPC, role, `DSQL_CLUSTER_ENDPOINT`, `AS_OF` and the log group.

- [ ] **Step 4: Run the CDK tests to see them pass**

Run: `cd infra-cdk && npx jest 2>&1 | tail -6; cd ..`
Expected: every test suite passes, 0 failed.

- [ ] **Step 5: Show the diff**

Run: `git diff -- infra-cdk/lib/data-construct.ts infra-cdk/test/data-construct.test.ts`

Expected: the diff holds the earlier fraud hunks (its `tools` entry and test row, and the count going from 4 to 5 in the uncommitted work) plus this task's changes:
- the `explain_transaction` entry;
- its test row;
- the count going from 5 to 6.

Then run `git status --short -- infra-cdk`. It must list only those two files. If `infra-cdk/config.yaml` appears, it was modified before this plan; leave it and never stage it.

---

### Task 10: Product design doc and the full suite

**Files:**
- Modify: `docs/LEDGERLENS_PRODUCT_DESIGN.md` §7.5, which uses CRLF line endings.

**Interfaces:**
- Consumes:
  - the `tool_spec.json` description and the three SQL files from Task 5;
  - the output shape from Task 6;
  - `DECLINE_MEANINGS` from Task 3.
- Produces: documentation only. It covers spec §10 and ruling 8.

- [ ] **Step 1: Replace §7.5, keeping CRLF**

Save this script to the scratchpad as `fix_7_5.py` and run it with `$PY <scratchpad>/fix_7_5.py </dev/null` from the repo root.

It replaces everything from the `### 7.5` heading up to, but not including, the `---` line before `### 7.6`. It looks up both ends by text, so it doesn't depend on line numbers, and it leaves the fraud work's §7.6 alone. The tool spec description and the SQL come from the tool's own files, so the doc can't drift from them. The SQL is shown without its header comments.

```python
"""Replace product design section 7.5 with the explain_transaction design."""

import json
from pathlib import Path

DOC = Path("docs/LEDGERLENS_PRODUCT_DESIGN.md")
TOOL = Path("gateway/tools/explain_transaction")
QUERIES = TOOL / "explain_transaction_lambda/queries/postgresql"

description = json.loads((TOOL / "tool_spec.json").read_text(encoding="utf-8"))[0][
    "description"
]


def sql_body(name: str) -> list[str]:
    """Return the query's lines without its leading comment header."""
    lines = (QUERIES / f"{name}.sql").read_text(encoding="utf-8").splitlines()
    first = next(i for i, line in enumerate(lines) if not line.startswith("--"))
    return lines[first:]


OUTPUT = {
    "transaction": {
        "transaction_id": "TRX-23BIJAU4GL46ATPW9STY",
        "transaction_date": "2026-05-31T06:09:15",
        "card_last4": "4497",
        "merchant_name": "Estación de Servicio",
        "merchant_category": "Transport",
        "amount": "288.69",
        "currency": "USD",
        "channel": "Web",
        "transaction_city": "Ciudad de México",
        "transaction_country": "México",
        "transaction_status": "Approved",
    },
    "fx": None,
    "decline": None,
    "habit": {
        "history_count": 1,
        "times_at_merchant_90d": 0,
        "usual_amount_range": None,
        "country_seen_before": True,
    },
    "app_activity": {"found": False},
    "unavailable": [],
}

NEW = [
    "### 7.5 `explain_transaction` (A2)",
    "",
    "**Purpose:** everything needed to explain one credit-card charge, in a "
    "single call. It explains; it never judges fraud (that is §7.6).",
    "",
    "**Spec:** [2026-10-03-explain-transaction-lambda-design.md]"
    "(superpowers/specs/2026-10-03-explain-transaction-lambda-design.md)",
    "",
    f'**tool_spec description:** "{description}"',
    "",
    "**Input:** `customer_id`, `transaction_id`",
    "",
    "**Output** (P07's charge; amounts are 2-decimal strings)",
    "```json",
    *json.dumps(OUTPUT, indent=2, ensure_ascii=False).splitlines(),
    "```",
    "",
    "- `fx`, for a charge in another currency than the card's: `card_currency`, "
    "`rate_date`, `rate` (the stored `sell_rate`, all its decimals) and "
    "`amount_in_card_currency`. `rate` is null when the bank has no rate for "
    "that day.",
    "- `decline`, for `Declined` charges only: `response_code`, `meaning`, "
    "`contradicts_card_state`.",
    "- `habit.usual_amount_range` is `{low, high, currency}` (10th to 90th "
    "percentile of same-currency approved charges), or null with fewer than 3 "
    "of them.",
    "- `app_activity` with `found: true` adds `event_date`, `minutes_from_charge` "
    "(negative before the charge), `ip_country`, `ip_city` and `conflict`.",
    "- A section whose query failed is null and named in `unavailable`; only a "
    "failure loading the charge itself is an error.",
    "",
    "**Decline meanings** (static table in the Lambda)",
    "",
    "| `response_code` | Meaning |",
    "|---|---|",
    "| 05 | declined by the issuer, no specific reason |",
    "| 14 | invalid card number |",
    "| 51 | insufficient available credit |",
    "| 54 | expired card |",
    "",
    "An unknown code keeps the code with a null meaning. "
    "`contradicts_card_state` is true for code 54 when the card's expiration "
    "date is on or after the charge date (D18: about 12,020 declines), so the "
    "agent doesn't tell the customer an unexpired card is expired.",
    "",
    "**Queries** (PostgreSQL dialect, psycopg placeholders)",
    "",
    "*The charge, its card and that day's rate (ownership check on "
    "`customer_id`, credit cards only):*",
    "```sql",
    *sql_body("explain_transaction"),
    "```",
    "",
    "*Habit: approved charges on the same card in the 90 days before the "
    "charge, excluding the charge:*",
    "```sql",
    *sql_body("transaction_habit"),
    "```",
    "",
    "*App activity: the closest digital event within ±2 h of the charge; "
    "`conflict` only for in-person channels (ATM, POS, Branch) whose country "
    "differs from the event's IP country, compared accent- and case-folded:*",
    "```sql",
    *sql_body("transaction_app_activity"),
    "```",
    "",
    "App activity is usually not found (D36); that's normal and never feeds a "
    "verdict.",
    "",
]

raw = DOC.read_bytes().decode("utf-8")
assert raw.count("\n") == raw.count("\r\n"), "expected CRLF only"
lines = raw.split("\r\n")
start = lines.index("### 7.5 `explain_transaction` (A2)")
next_heading = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("### 7.6"))
end = max(i for i in range(start, next_heading) if lines[i] == "---")
lines[start:end] = NEW
DOC.write_bytes("\r\n".join(lines).encode("utf-8"))
print(f"replaced lines {start + 1}-{end} with {len(NEW)} lines")
```

Expected: one line that starts with `replaced lines 498-`. The end line and the new line count depend on the SQL files.

- [ ] **Step 2: Check the section and the line endings**

```bash
sed -n '/^### 7.5/,/^### 7.6/p' docs/LEDGERLENS_PRODUCT_DESIGN.md | tr -d '\r'
file docs/LEDGERLENS_PRODUCT_DESIGN.md
grep -c "merchant_hint\|location_check" docs/LEDGERLENS_PRODUCT_DESIGN.md
git diff --stat -- docs/LEDGERLENS_PRODUCT_DESIGN.md
```

Expected:
- The section shows the new text and the three SQL bodies, then `---` and the `### 7.6` heading.
- `file` still says `with CRLF line terminators`.
- The `grep -c` prints `0`. Ruling 8 drops `merchant_hint`, and spec §5 renames `location_check`. If it prints more than 0, show the lines: they're outside §7.5, so report them rather than edit them.
- The diff touches only this file. It holds §7.5's lines plus the earlier, uncommitted §7.6 hunks from the fraud work, not the whole file.

- [ ] **Step 3: Run the whole suite**

Run the suite command from Global Constraints.
Expected: `N passed, 1 deselected`, where N is 1166 plus every test in `tests/unit/explain_transaction/`, and 0 failed. Get that count with `$PY -m pytest tests/unit/explain_transaction -q -p no:cacheprovider --co </dev/null | tail -1`.

- [ ] **Step 4: Lint the whole tool and check the tree**

```bash
$PY -m ruff format --check gateway/tools/explain_transaction tests/unit/explain_transaction </dev/null
$PY -m ruff check gateway/tools/explain_transaction tests/unit/explain_transaction </dev/null
grep -rnE "(get_session_context|list_credit_cards|list_card_transactions|transaction_fraud_detection)_lambda" gateway/tools/explain_transaction tests/unit/explain_transaction
find gateway/tools/explain_transaction tests/unit/explain_transaction -name __pycache__ -prune -o -type f -print | sort
git status --short
```

Expected:
- Both ruff commands are clean, and the grep prints nothing.
- `find` lists the tool's files only: no `.pyc`.
- `git status` lists the fraud work from before (its folders, plan and spec, and the hunks in `docs/LEDGERLENS_PRODUCT_DESIGN.md` and both `infra-cdk` files) plus this plan's work: `gateway/tools/explain_transaction/`, `tests/unit/explain_transaction/`, the same doc and `infra-cdk` files, this plan, and the classify spec if it is untracked. Nothing is staged.

---

### Task 11: Joint deploy and acceptance (deferred: don't run during this plan)

**Don't run this task when executing this plan.** The user decided that `transaction_fraud_detection`, `explain_transaction` and `classify_call_type` deploy together, after all three are built. This task's steps run in that joint session, next to the fraud plan's Task 12 and the classify plan's deploy task. The deploy changes the real AWS account, so it also needs the user's explicit go-ahead at that time.

When executing this plan, finish after Task 10. Tell the user Tasks 1–10 are done, with the suite and CDK test results, and that Task 11 is waiting for the joint deploy.

**Files:** none changed.

**Interfaces:**
- Consumes: everything above.
- Produces: the deployed `ledgerlens-explain-transaction` function and the five acceptance results.

- [ ] **Step 1: Deploy the data stack (once, for all three tools)**

Run: `cd infra-cdk && npx cdk deploy ledgerlens-bank-assistant-data --exclusively --require-approval never --profile ledgerlens 2>&1 | tail -15; cd ..`
Expected: the stack update finishes with `✅  ledgerlens-bank-assistant-data`. The change set adds the new functions and their log groups, and doesn't replace any existing function.

- [ ] **Step 2: Run the five acceptance checks**

Use the scratchpad as `S`. The client context is built the same way as in the earlier tools' acceptance runs:

```bash
S="<scratchpad>"
CC=$(printf '{"custom":{"bedrockAgentCoreToolName":"target___explain_transaction"}}' | base64 -w0)
invoke() {
  printf '%s' "$2" > "$S/$1.json"
  aws lambda invoke --function-name ledgerlens-explain-transaction \
    --client-context "$CC" --cli-binary-format raw-in-base64-out \
    --payload "fileb://$S/$1.json" --profile ledgerlens --region us-east-1 \
    "$S/$1_out.json" >/dev/null && cat "$S/$1_out.json" && echo
}
invoke p07 '{"customer_id":"CLI-EX6BOAOEFZHQ","transaction_id":"TRX-23BIJAU4GL46ATPW9STY"}'
invoke p05_decline '{"customer_id":"<P05 customer_id>","transaction_id":"TRX-YLR3CXW0CFHFUNT2IUWZ"}'
invoke p05_brazil '{"customer_id":"<P05 customer_id>","transaction_id":"TRX-MQKFELIPWT098DXTN2WN"}'
invoke p09 '{"customer_id":"<P09 customer_id>","transaction_id":"TRX-RX1ENVJQ5J26GXX7T8F7"}'
invoke p03 '{"customer_id":"<P03 customer_id>","transaction_id":"TRX-LJGEBUAOX0G4CL4RQSIU"}'
```

Before running, replace each `<Pnn customer_id>` with that persona's `customer_id` from the curated personas list (`docs/` or `data_load` curate output). Every charge must be checked with its owner's id, because another customer's id returns "not found" by design.

Expected (spec §1 acceptance; the deployed `AS_OF` is `2026-06-17T23:59:59`):
- **`p07`:**
  - `fx: null` and `decline: null`;
  - `habit` filled, with `history_count` 1 and `usual_amount_range` null;
  - `app_activity.found` either false or true.
- **`p05_decline`:** `decline.response_code` `"14"`, with meaning `"invalid card number"` and `contradicts_card_state: false`.
- **`p05_brazil`:** `fx: null`. Report `habit.country_seen_before` as it comes: it is false unless Brazil appears in the card's prior 90 days.
- **`p09`:** `decline.response_code` `"54"` and `contradicts_card_state: true`.
- **`p03`:** `transaction.transaction_status` `"Reversed"` and `decline: null`.
- **All five:**
  - `unavailable: []`. If `habit` is unavailable on DSQL (R3), report it; don't change the SQL without the user.
  - No key or value contains `fraud_score`, `score` or `is_fraud`.

If any result differs, stop and show the user the full output. Don't change the SQL or the rules to make the results match.

- [ ] **Step 3: Report**

Show the user all five outputs in full and say which checks passed. Then wait for their command to commit. Don't commit or push on your own.
