# list_credit_cards Lambda Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `list_credit_cards` Gateway tool Lambda as a self-contained folder, `gateway/tools/list_credit_cards/list_credit_cards_lambda/`. It lists a customer's credit cards in every status from Aurora DSQL.

**Architecture:**
- The tool has the same hexagonal layers as `list_card_transactions`.
- The infrastructure, ports, settings and connectors are copied file by file, with only the package name changed.
- The domain errors, the entity, the use case (which also cleans `customer_id`), the SQL, the presenter, the builder's use-case block and the handler are this tool's own.
- `customer_id` comes from the event bare. The use case strips and uppercases it before querying.
- No cards gives `"cards": null`.

**Tech Stack:** Python 3.10, pytest 7.1, ruff, psycopg 3, boto3, Git Bash on Windows.

**Spec:** `docs/superpowers/specs/2026-10-01-list-credit-cards-lambda-design.md`. Layout rules: `docs/superpowers/specs/2026-10-01-self-contained-tool-folders-design.md`.

## Global Constraints

- Python: `PY=/c/ProgramData/anaconda3/python`. Run every command from the repo root `C:\GITHUB REPOS\ledgerlens-bank-assistant` in Git Bash. Add `</dev/null` to `$PY` commands so nothing waits on stdin.
- **Do not commit during execution.** The user commits once, on their command, at the end. Never run `git commit` or `git add`.
- Never stage `infra-cdk/config.yaml`, `frontend/public/aws-exports.json` or `frontend/.env`.
- No AWS deploys, no CDK changes, no push and no merge.
- **Self-contained:** nothing in `list_credit_cards` imports from `list_card_transactions`, and nothing in `list_card_transactions` changes. Code is copied, never shared.
- **Copy rule:**
  - Copied files only get `list_card_transactions` → `list_credit_cards`. Task 6 also renames `ListCardTransactionsUseCase` → `ListCreditCardsUseCase`.
  - Never run a blanket replace on the word "transaction": the copied connector and repository rightly mention `default_transaction_read_only` and DSQL's per-transaction limits.
  - Never copy `__pycache__`.
- Names (spec §2):
  - asset folder: `gateway/tools/list_credit_cards/`
  - package: `list_credit_cards_lambda`
  - handler: `delivery/handler.py`
  - handler string: `list_credit_cards_lambda/delivery/handler.handler`
  - tool name: `list_credit_cards`
  - test package: `tests/unit/list_credit_cards/`
- Keep names specific: `database_repository`, `query_provider`.
- Exact values from the spec:
  - SQL card filter: `p.product_type = 'Tarjeta Crédito'`, as NFC UTF-8 with no BOM.
  - Default row cap: 25. The query sends `limit` = max_rows + 1.
  - Customer id example: `CLI-ITIECUE8PRH9`.
  - Bad id message: `Invalid value for 'customer_id': is required and must be a non-empty string. Ask the customer to confirm and retry.`
  - Fixed messages (spec §4.2):
    - `DataSourceUnavailableError`: "Card data is temporarily unavailable. Tell the customer and offer to retry in a moment or hand off to a human agent."
    - `CardLookupError`: "The customer's cards can't be retrieved right now due to an internal error. Don't retry; offer a hand-off to a human agent."
    - `CardDataIntegrityError`: "Card data came back in an unexpected format. Don't retry; offer a hand-off to a human agent."
    - Unexpected error: "Unexpected internal error listing credit cards. Offer a hand-off to a human agent."
- Keep the `TODO(ledgerlens): Rn` tags and the role name `ledgerlens_readonly` exactly as they are.
- Lint: `$PY -m ruff format --check <paths>` and `$PY -m ruff check <paths>`. Fix formatting with `$PY -m ruff format <paths>`.
- **Spec note (§8 vs §4.2):** §8 says `test_errors.py` is "copied with imports changed". The fixed messages are different (§4.2), so `test_errors.py` is rewritten in Task 2. §4.2 wins.

## Review Focus

1. **The literal `'Tarjeta Crédito'` saved decomposed (NFD) or behind a UTF-8 BOM.** Either would make every customer silently get "no cards" (risk C1). Expected: the SQL file is NFC UTF-8 with no BOM, and contains the exact literal. *Pinned by Task 4, `test_credit_card_literal_is_nfc_utf8_without_bom`.*
2. **A lowercase id with spaces around it sent through the handler**, as the agent might type it. Expected: the cursor receives `CLI-ITIECUE8PRH9`. *Pinned by Task 7, `test_bare_customer_id_is_cleaned_before_the_query`.*
3. **A non-object event (`None`, `[]`, a string) or a non-string id (`42`, `True`).** Expected: the `customer_id` error message, and no database connection opened. *Pinned by Task 3, `test_invalid_customer_id_is_rejected_before_the_database_is_called`, and Task 7, `test_invalid_customer_id_returns_the_input_error_without_a_query`.*
4. **Odd column types from the driver:** a `datetime` expiry, or a bool or non-finite amount or `days_past_due`. Expected: the datetime becomes a `date`, and the others raise `CardDataIntegrityError`, never a crash or a wrong value. *Pinned by Task 3, `test_a_timestamp_expiration_date_becomes_a_date` and `test_unmappable_rows_raise_card_data_integrity_error`.*
5. **Truncation boundaries and the empty case.** Expected: 26 rows gives 25 cards plus truncated, 25 rows isn't truncated, 0 rows gives `{"cards": null, "count": 0, "truncated": false}`, and an over-limit card shows a negative `available_credit`. *Pinned by Task 3's truncation tests, Task 5's `test_presenter_returns_null_cards_when_the_customer_has_none` and the negative-amount case, and Task 7's `test_no_cards_returns_null_cards`.*

---

## File map

| Path | Task | Kind |
|---|---|---|
| `gateway/tools/list_credit_cards/requirements.txt` | 1 | copied |
| `list_credit_cards_lambda/**/__init__.py` (14 files, no `value_objects`) | 1 | copied |
| `list_credit_cards_lambda/application/ports/{database_repository,query_provider,errors}.py` | 1 | copied |
| `list_credit_cards_lambda/infrastructure/queries/file_query_provider.py` | 1 | copied |
| `list_credit_cards_lambda/infrastructure/repositories/dsql_repository.py` | 1 | copied |
| `list_credit_cards_lambda/utils/connectors/{base,dsql}.py` | 1 | copied |
| `list_credit_cards_lambda/delivery/settings.py` | 1 | copied |
| `list_credit_cards_lambda/domain/errors.py` | 2 | new (base classes copied) |
| `list_credit_cards_lambda/domain/entities/credit_card.py` | 3 | new |
| `list_credit_cards_lambda/application/use_cases/list_credit_cards.py` | 3 | new |
| `list_credit_cards_lambda/queries/postgresql/list_credit_cards.sql` | 4 | new |
| `list_credit_cards_lambda/delivery/presenters/credit_cards.py` | 5 | new |
| `list_credit_cards_lambda/delivery/dependencies/dependencies_builder.py` | 6 | copied, then renamed |
| `list_credit_cards_lambda/delivery/handler.py` | 7 | new (shape copied) |
| `gateway/tools/list_credit_cards/tool_spec.json` | 7 | new |
| `tests/unit/list_credit_cards/{__init__,conftest,fakes}.py` | 1 | new or adapted |
| `tests/unit/list_credit_cards/test_{settings,file_query_provider,dsql_repository,psycopg_connector,dsql_connector}.py` | 1 | copied |
| `tests/unit/list_credit_cards/test_errors.py` | 2 | rewritten |
| `tests/unit/list_credit_cards/test_list_credit_cards_use_case.py` | 3 | new |
| `tests/unit/list_credit_cards/test_query_contracts.py` | 4, 7 | new |
| `tests/unit/list_credit_cards/test_credit_cards_presenter.py` | 5 | new |
| `tests/unit/list_credit_cards/test_delivery_wiring.py` | 6 | adapted |
| `tests/unit/list_credit_cards/test_list_credit_cards_handler.py` | 7 | adapted |
| `docs/LEDGERLENS_PRODUCT_DESIGN.md` (§7.1, §7.3, §7.7) | 8 | modified |

The `list_credit_cards_lambda/...` paths are under `gateway/tools/list_credit_cards/`.

---

### Task 1: Copy the shared-shape layers and their tests

**Files:**
- Create (copied): every file in the "copied" rows of Task 1 in the file map.
- Create: `tests/unit/list_credit_cards/__init__.py`, `conftest.py`, `fakes.py`
- Test (copied): `tests/unit/list_credit_cards/test_settings.py`, `test_file_query_provider.py`, `test_dsql_repository.py`, `test_psycopg_connector.py`, `test_dsql_connector.py`

**Interfaces:**
- Consumes: the source files in `gateway/tools/list_card_transactions/` and `tests/unit/list_card_transactions/`.
- Produces:
  - The package `list_credit_cards_lambda`, importable once `gateway/tools/list_credit_cards` is on `sys.path` (the conftest does this).
  - `fakes.CUSTOMER_ID = "CLI-ITIECUE8PRH9"`
  - `fakes.make_row(**overrides) -> dict[str, Any]` (a card row)
  - `fakes.FakeDatabaseRepository(rows=None, error=None)`, with `.calls: list[tuple[str, dict]]`
  - `fakes.FakeQueryProvider(queries=None)`: by default it serves `list_credit_cards`, and it records names in `.requested`.
  - `fakes.FakeConnector(*outcomes)`, with `.connections[i].cursors[j].executed`
  - `FakeConnection`, `FakeCursor`, `FakeClock` and `FakeDsqlTokenClient`, unchanged.

- [ ] **Step 1: Create the test package and copy the five infrastructure tests**

```bash
SRC_T=tests/unit/list_card_transactions
DST_T=tests/unit/list_credit_cards
mkdir -p "$DST_T"
: > "$DST_T/__init__.py"
for f in test_settings.py test_file_query_provider.py test_dsql_repository.py \
         test_psycopg_connector.py test_dsql_connector.py fakes.py; do
  sed 's/list_card_transactions/list_credit_cards/g' "$SRC_T/$f" > "$DST_T/$f"
done
```

Write `tests/unit/list_credit_cards/conftest.py`:

```python
"""Pytest setup for list_credit_cards: make its Lambda package importable.

The ``list_credit_cards_lambda`` package lives in the Lambda asset root
``gateway/tools/list_credit_cards``, so that folder is put on ``sys.path``
exactly as the Lambda runtime does.
"""

import sys
from pathlib import Path

_ASSET_ROOT = (
    Path(__file__).resolve().parents[3] / "gateway" / "tools" / "list_credit_cards"
)

if str(_ASSET_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASSET_ROOT))
```

- [ ] **Step 2: Adapt `fakes.py` to card rows**

In `tests/unit/list_credit_cards/fakes.py`, make three edits.

(a) Replace the imports block, from `import time` through `from list_credit_cards_lambda.utils.connectors.base import PsycopgConnector`, with:

```python
import time
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Final

from list_credit_cards_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from list_credit_cards_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryNotFoundError,
)
from list_credit_cards_lambda.application.ports.query_provider import QueryProvider
from list_credit_cards_lambda.utils.connectors.base import PsycopgConnector

# A customer id in the format the customer system issues.
CUSTOMER_ID: Final = "CLI-ITIECUE8PRH9"
```

(b) Replace the whole `make_row` function and the whole `make_filters` function with:

```python
def make_row(**overrides: Any) -> dict[str, Any]:
    """Build a credit card row as psycopg's dict_row returns it."""
    row: dict[str, Any] = {
        "product_id": "PRD-1",
        "card_last4": "4821",
        "product_status": "Active",
        "currency": "COP",
        "current_balance": Decimal("1250000.00"),
        "credit_limit": Decimal("3000000.00"),
        "available_credit": Decimal("1750000.00"),
        "expiration_date": date(2027, 3, 31),
        "days_past_due": 0,
    }
    row.update(overrides)
    return row
```

(c) Check that the sed already made `FakeQueryProvider`'s default `{"list_credit_cards": "SELECT 'list_credit_cards'"}`:

Run: `grep -n "list_credit_cards\|make_filters\|TransactionFilters\|datetime" tests/unit/list_credit_cards/fakes.py`
Expected: the only matches name `list_credit_cards` (including the default `{"list_credit_cards": "SELECT 'list_credit_cards'"}`). There's no `make_filters`, `TransactionFilters` or `datetime`.

- [ ] **Step 3: Run the copied tests to verify they fail**

Run: `$PY -m pytest tests/unit/list_credit_cards -q -p no:cacheprovider </dev/null 2>&1 | tail -5`
Expected: collection errors with `ModuleNotFoundError: No module named 'list_credit_cards_lambda'`.

- [ ] **Step 4: Copy the production files**

```bash
SRC=gateway/tools/list_card_transactions
DST=gateway/tools/list_credit_cards
P=list_card_transactions_lambda
for f in requirements.txt \
  $P/__init__.py \
  $P/application/__init__.py \
  $P/application/ports/__init__.py \
  $P/application/ports/database_repository.py \
  $P/application/ports/query_provider.py \
  $P/application/ports/errors.py \
  $P/application/use_cases/__init__.py \
  $P/delivery/__init__.py \
  $P/delivery/settings.py \
  $P/delivery/dependencies/__init__.py \
  $P/delivery/presenters/__init__.py \
  $P/domain/__init__.py \
  $P/domain/entities/__init__.py \
  $P/infrastructure/__init__.py \
  $P/infrastructure/queries/__init__.py \
  $P/infrastructure/queries/file_query_provider.py \
  $P/infrastructure/repositories/__init__.py \
  $P/infrastructure/repositories/dsql_repository.py \
  $P/utils/__init__.py \
  $P/utils/connectors/__init__.py \
  $P/utils/connectors/base.py \
  $P/utils/connectors/dsql.py; do
  dst="$DST/${f/list_card_transactions_lambda/list_credit_cards_lambda}"
  mkdir -p "$(dirname "$dst")"
  sed 's/list_card_transactions/list_credit_cards/g' "$SRC/$f" > "$dst"
done
sed -i 's/Domain layer: entities, value objects and agent-facing errors. No I\/O./Domain layer: entities and agent-facing errors. No I\/O./' \
  "$DST/list_credit_cards_lambda/domain/__init__.py"
```

There's no `domain/value_objects/` folder. This tool takes no filters (spec §6).

- [ ] **Step 5: Run the copied tests to verify they pass**

Run: `$PY -m pytest tests/unit/list_credit_cards -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: `80 passed` (settings 27, file_query_provider 10, dsql_repository 16, psycopg_connector 13, dsql_connector 14).

- [ ] **Step 6: Check isolation and lint**

```bash
grep -rn "list_card_transactions" gateway/tools/list_credit_cards tests/unit/list_credit_cards
find gateway/tools/list_credit_cards -name __pycache__ -prune -o -type f -print | grep -c .
$PY -m ruff format --check gateway/tools/list_credit_cards tests/unit/list_credit_cards </dev/null
$PY -m ruff check gateway/tools/list_credit_cards tests/unit/list_credit_cards </dev/null
```

Expected:
- The grep prints nothing.
- The file count is `23`: `requirements.txt`, 14 `__init__.py` files and 8 modules.
- If `ruff format --check` lists files, run `$PY -m ruff format` on the same paths and re-check. After that, both ruff commands are clean.

No commit. The task ends with the tree green.

---

### Task 2: Card-worded domain errors

**Files:**
- Create: `gateway/tools/list_credit_cards/list_credit_cards_lambda/domain/errors.py`
- Test: `tests/unit/list_credit_cards/test_errors.py`

**Interfaces:**
- Consumes: `application/ports/errors.py` from Task 1.
- Produces, all in `list_credit_cards_lambda.domain.errors`:
  - `DomainError(message)`, with `.message`
  - `InvalidInputError(field, reason)`, with `.field` and `.reason`
  - `DataSourceUnavailableError()`, `CardLookupError()` and `CardDataIntegrityError()`, each with a class-level `MESSAGE`
  - No `SearchTooBroadError`, `TransactionLookupError` or `DataIntegrityError`.

- [ ] **Step 1: Write the failing test**

`tests/unit/list_credit_cards/test_errors.py`:

```python
"""Tests for domain and port error definitions."""

import list_credit_cards_lambda.domain.errors as errors_module
import pytest
from list_credit_cards_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
    QueryNotFoundError,
)
from list_credit_cards_lambda.domain.errors import (
    CardDataIntegrityError,
    CardLookupError,
    DataSourceUnavailableError,
    DomainError,
    InvalidInputError,
)

pytestmark = pytest.mark.unit


def test_invalid_input_error_formats_field_and_reason() -> None:
    error = InvalidInputError(
        "customer_id", "is required and must be a non-empty string"
    )

    assert error.field == "customer_id"
    assert error.reason == "is required and must be a non-empty string"
    assert error.message == (
        "Invalid value for 'customer_id': is required and must be a non-empty "
        "string. Ask the customer to confirm and retry."
    )
    assert str(error) == error.message


@pytest.mark.parametrize(
    ("error_type", "expected"),
    [
        (
            DataSourceUnavailableError,
            "Card data is temporarily unavailable. Tell the customer and offer "
            "to retry in a moment or hand off to a human agent.",
        ),
        (
            CardLookupError,
            "The customer's cards can't be retrieved right now due to an internal "
            "error. Don't retry; offer a hand-off to a human agent.",
        ),
        (
            CardDataIntegrityError,
            "Card data came back in an unexpected format. Don't retry; offer a "
            "hand-off to a human agent.",
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
    "name", ["SearchTooBroadError", "TransactionLookupError", "DataIntegrityError"]
)
def test_transaction_worded_errors_are_not_defined(name: str) -> None:
    # The query has no filter the agent could narrow (spec section 4.2).
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

- [ ] **Step 2: Run the test to verify it fails**

Run: `$PY -m pytest tests/unit/list_credit_cards/test_errors.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: a collection error, `ModuleNotFoundError: No module named 'list_credit_cards_lambda.domain.errors'`.

- [ ] **Step 3: Write the implementation**

`gateway/tools/list_credit_cards/list_credit_cards_lambda/domain/errors.py`:

```python
"""Domain errors: the only failures the agent is allowed to see.

Each message says what went wrong and what the agent should do next. Messages
never contain SQL, hostnames, driver output or other internal details.
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


class DataSourceUnavailableError(_FixedMessageError):
    """The database can't be reached right now; retrying later may work."""

    MESSAGE: ClassVar[str] = (
        "Card data is temporarily unavailable. Tell the customer and offer "
        "to retry in a moment or hand off to a human agent."
    )


class CardLookupError(_FixedMessageError):
    """The query failed or hit a database limit; retrying won't help.

    A limit error gets this message too: the query has no filter the agent
    could narrow.
    """

    MESSAGE: ClassVar[str] = (
        "The customer's cards can't be retrieved right now due to an internal "
        "error. Don't retry; offer a hand-off to a human agent."
    )


class CardDataIntegrityError(_FixedMessageError):
    """A returned row couldn't be mapped to a domain entity."""

    MESSAGE: ClassVar[str] = (
        "Card data came back in an unexpected format. Don't retry; offer a "
        "hand-off to a human agent."
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `$PY -m pytest tests/unit/list_credit_cards/test_errors.py -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: `11 passed`.

No commit. The task ends with the tree green.

---

### Task 3: CreditCard entity and ListCreditCardsUseCase

**Files:**
- Create: `gateway/tools/list_credit_cards/list_credit_cards_lambda/domain/entities/credit_card.py`
- Create: `gateway/tools/list_credit_cards/list_credit_cards_lambda/application/use_cases/list_credit_cards.py`
- Test: `tests/unit/list_credit_cards/test_list_credit_cards_use_case.py`

**Interfaces:**
- Consumes:
  - From Task 2: `CardDataIntegrityError`, `CardLookupError`, `DataSourceUnavailableError` and `InvalidInputError`.
  - From Task 1: the ports, and the fakes `CUSTOMER_ID`, `make_row`, `FakeDatabaseRepository` and `FakeQueryProvider`.
- Produces:
  - `CreditCard(card_last4: str | None, product_status: str | None, currency: str | None, current_balance: Decimal | None, credit_limit: Decimal | None, available_credit: Decimal | None, expiration_date: date | None, days_past_due: int | None)`: frozen, in this field order.
  - `CreditCardsResult(cards: tuple[CreditCard, ...], truncated: bool)`: frozen.
  - `ListCreditCardsUseCase(database_repository, query_provider, max_rows=25)`, with:
    - `QUERY_NAME = "list_credit_cards"`
    - `execute(customer_id: object) -> CreditCardsResult`
    - query params of exactly `{"customer_id": str, "limit": int}`

- [ ] **Step 1: Write the failing test**

`tests/unit/list_credit_cards/test_list_credit_cards_use_case.py`:

```python
"""Tests for ListCreditCardsUseCase: customer_id cleaning, params, mapping, errors."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from list_credit_cards_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
)
from list_credit_cards_lambda.application.use_cases.list_credit_cards import (
    ListCreditCardsUseCase,
)
from list_credit_cards_lambda.domain.entities.credit_card import (
    CreditCard,
    CreditCardsResult,
)
from list_credit_cards_lambda.domain.errors import (
    CardDataIntegrityError,
    CardLookupError,
    DataSourceUnavailableError,
    DomainError,
    InvalidInputError,
)

from .fakes import CUSTOMER_ID, FakeDatabaseRepository, FakeQueryProvider, make_row

pytestmark = pytest.mark.unit

INVALID_CUSTOMER_ID = (
    "Invalid value for 'customer_id': is required and must be a non-empty "
    "string. Ask the customer to confirm and retry."
)


def run(
    rows: list[dict[str, Any]] | None = None,
    error: Exception | None = None,
    max_rows: int = 25,
    customer_id: object = CUSTOMER_ID,
) -> tuple[CreditCardsResult, FakeDatabaseRepository, FakeQueryProvider]:
    """Execute the use case against fakes and return the result and the fakes."""
    database_repository = FakeDatabaseRepository(rows=rows, error=error)
    query_provider = FakeQueryProvider()
    use_case = ListCreditCardsUseCase(
        database_repository=database_repository,
        query_provider=query_provider,
        max_rows=max_rows,
    )
    return use_case.execute(customer_id), database_repository, query_provider


def test_maps_a_row_to_a_credit_card() -> None:
    result, _, _ = run(rows=[make_row()])

    assert result == CreditCardsResult(
        cards=(
            CreditCard(
                card_last4="4821",
                product_status="Active",
                currency="COP",
                current_balance=Decimal("1250000.00"),
                credit_limit=Decimal("3000000.00"),
                available_credit=Decimal("1750000.00"),
                expiration_date=date(2027, 3, 31),
                days_past_due=0,
            ),
        ),
        truncated=False,
    )


def test_loads_the_named_query_and_passes_its_text_to_the_database_repository() -> None:
    _, database_repository, query_provider = run()

    assert query_provider.requested == ["list_credit_cards"]
    assert database_repository.calls[0][0] == "SELECT 'list_credit_cards'"


def test_sends_exactly_the_customer_id_and_limit() -> None:
    _, database_repository, _ = run()

    assert database_repository.calls[0][1] == {"customer_id": CUSTOMER_ID, "limit": 26}


@pytest.mark.parametrize(
    "raw",
    [
        "CLI-ITIECUE8PRH9",
        "  CLI-ITIECUE8PRH9  ",
        "cli-itiecue8prh9",
        "\tCli-ItieCue8prh9\n",
    ],
)
def test_customer_id_is_stripped_and_uppercased(raw: str) -> None:
    _, database_repository, _ = run(customer_id=raw)

    assert database_repository.calls[0][1]["customer_id"] == "CLI-ITIECUE8PRH9"


def test_customer_id_is_otherwise_sent_unchanged_as_a_bind() -> None:
    # No format check: the id is a bind parameter, so odd characters are harmless.
    _, database_repository, _ = run(customer_id="cli-1'; drop table products;--")

    assert database_repository.calls[0][1]["customer_id"] == (
        "CLI-1'; DROP TABLE PRODUCTS;--"
    )


@pytest.mark.parametrize(
    "raw", [None, "", "   ", "\t\n", 123, 12.5, True, ["CLI-1"], {"id": "CLI-1"}]
)
def test_invalid_customer_id_is_rejected_before_the_database_is_called(
    raw: object,
) -> None:
    database_repository = FakeDatabaseRepository(rows=[make_row()])
    query_provider = FakeQueryProvider()
    use_case = ListCreditCardsUseCase(
        database_repository=database_repository, query_provider=query_provider
    )

    with pytest.raises(InvalidInputError) as caught:
        use_case.execute(raw)

    assert caught.value.field == "customer_id"
    assert caught.value.message == INVALID_CUSTOMER_ID
    assert database_repository.calls == []
    assert query_provider.requested == []


def test_limit_is_max_rows_plus_one() -> None:
    _, database_repository, _ = run(max_rows=3)

    assert database_repository.calls[0][1]["limit"] == 4


def test_returns_max_rows_and_flags_truncation_when_more_exist() -> None:
    rows = [make_row(product_id=f"PRD-{i}", card_last4=f"{i:04d}") for i in range(26)]

    result, _, _ = run(rows=rows)

    assert len(result.cards) == 25
    assert result.cards[-1].card_last4 == "0024"
    assert result.truncated is True


def test_exactly_max_rows_is_not_truncated() -> None:
    rows = [make_row(product_id=f"PRD-{i}") for i in range(25)]

    result, _, _ = run(rows=rows)

    assert len(result.cards) == 25
    assert result.truncated is False


def test_no_cards_is_an_empty_result_not_an_error() -> None:
    result, _, _ = run(rows=[])

    assert result == CreditCardsResult(cards=(), truncated=False)


def test_every_column_may_be_null() -> None:
    null_row = {column: None for column in make_row()}

    result, _, _ = run(rows=[null_row, make_row()])

    assert result.cards[0] == CreditCard(
        card_last4=None,
        product_status=None,
        currency=None,
        current_balance=None,
        credit_limit=None,
        available_credit=None,
        expiration_date=None,
        days_past_due=None,
    )
    assert result.cards[1].card_last4 == "4821"


def test_a_timestamp_expiration_date_becomes_a_date() -> None:
    row = make_row(expiration_date=datetime(2027, 3, 31, 23, 59, tzinfo=timezone.utc))

    result, _, _ = run(rows=[row])

    assert result.cards[0].expiration_date == date(2027, 3, 31)
    assert type(result.cards[0].expiration_date) is date


def test_numbers_are_normalised_and_negative_credit_is_kept() -> None:
    row = make_row(
        card_last4=4821,
        current_balance=100,
        credit_limit=250.5,
        available_credit=Decimal("-50.25"),
        days_past_due=45,
    )

    card = run(rows=[row])[0].cards[0]

    assert card.card_last4 == "4821"
    assert card.current_balance == Decimal("100")
    assert card.credit_limit == Decimal("250.5")
    assert card.available_credit == Decimal("-50.25")
    assert card.days_past_due == 45


@pytest.mark.parametrize(
    ("port_error", "domain_error"),
    [
        (
            DataSourceConnectionError("conn refused host=db.internal"),
            DataSourceUnavailableError,
        ),
        (
            QueryLimitExceededError("query exceeded the 128 MiB memory limit"),
            CardLookupError,
        ),
        (
            QueryExecutionError('relation "products" does not exist'),
            CardLookupError,
        ),
        (DataAccessError("unclassified adapter failure"), CardLookupError),
    ],
)
def test_port_errors_become_domain_errors_without_leaking_details(
    port_error: Exception, domain_error: type[DomainError]
) -> None:
    with pytest.raises(domain_error) as caught:
        run(error=port_error)

    assert caught.value.__cause__ is port_error
    assert str(port_error) not in caught.value.message


def test_missing_query_becomes_card_lookup_error() -> None:
    use_case = ListCreditCardsUseCase(
        database_repository=FakeDatabaseRepository(),
        query_provider=FakeQueryProvider(queries={}),
    )

    with pytest.raises(CardLookupError):
        use_case.execute(CUSTOMER_ID)


@pytest.mark.parametrize(
    "bad_row",
    [
        {k: v for k, v in make_row().items() if k != "credit_limit"},
        make_row(current_balance="1250000.00"),
        make_row(current_balance=True),
        make_row(credit_limit=Decimal("NaN")),
        make_row(available_credit=float("inf")),
        make_row(expiration_date="2027-03-31"),
        make_row(days_past_due="0"),
        make_row(days_past_due=True),
        make_row(days_past_due=Decimal("3")),
    ],
)
def test_unmappable_rows_raise_card_data_integrity_error(
    bad_row: dict[str, Any],
) -> None:
    with pytest.raises(CardDataIntegrityError):
        run(rows=[bad_row])


def test_max_rows_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_rows"):
        ListCreditCardsUseCase(
            database_repository=FakeDatabaseRepository(),
            query_provider=FakeQueryProvider(),
            max_rows=0,
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `$PY -m pytest tests/unit/list_credit_cards/test_list_credit_cards_use_case.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: a collection error, `ModuleNotFoundError: No module named 'list_credit_cards_lambda.application.use_cases.list_credit_cards'`.

- [ ] **Step 3: Write the entity**

`gateway/tools/list_credit_cards/list_credit_cards_lambda/domain/entities/credit_card.py`:

```python
"""Credit card entities returned by the list_credit_cards use case."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class CreditCard:
    """One of the customer's credit cards, as returned to the agent.

    Every field is ``| None`` because the source data has about 5% nulls; a card
    with a null column is still listed. ``product_status`` is a plain string
    because the database may hold values outside the four known ones. The
    internal ``product_id`` is never exposed; other tools address cards by
    ``card_last4``.
    """

    card_last4: str | None
    product_status: str | None
    currency: str | None
    current_balance: Decimal | None
    credit_limit: Decimal | None
    available_credit: Decimal | None
    expiration_date: date | None
    days_past_due: int | None


@dataclass(frozen=True)
class CreditCardsResult:
    """At most max_rows cards; truncated is True when more exist.

    ``cards`` is empty when the customer has no credit cards.
    """

    cards: tuple[CreditCard, ...]
    truncated: bool
```

- [ ] **Step 4: Write the use case**

`gateway/tools/list_credit_cards/list_credit_cards_lambda/application/use_cases/list_credit_cards.py`:

```python
"""Use case: list a customer's credit cards."""

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

from list_credit_cards_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from list_credit_cards_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
)
from list_credit_cards_lambda.application.ports.query_provider import QueryProvider
from list_credit_cards_lambda.domain.entities.credit_card import (
    CreditCard,
    CreditCardsResult,
)
from list_credit_cards_lambda.domain.errors import (
    CardDataIntegrityError,
    CardLookupError,
    DataSourceUnavailableError,
    InvalidInputError,
)


class ListCreditCardsUseCase:
    """List a customer's credit cards through a database-agnostic repository.

    The use case cleans the customer id, loads the SQL by name through the query
    provider, runs it through the database repository port and maps rows to
    domain entities. Port errors are translated into domain errors whose messages
    tell the agent what to do next.
    """

    QUERY_NAME: Final = "list_credit_cards"

    def __init__(
        self,
        database_repository: DatabaseRepository,
        query_provider: QueryProvider,
        max_rows: int = 25,
    ) -> None:
        """Store the ports and the row cap.

        Args:
            database_repository: Executes the query; any DatabaseRepository
                adapter.
            query_provider: Supplies the SQL text for the configured dialect.
            max_rows: Maximum cards returned per call.

        Raises:
            ValueError: If max_rows is less than 1.
        """
        if max_rows < 1:
            raise ValueError("max_rows must be at least 1")
        self._database_repository: DatabaseRepository = database_repository
        self._query_provider: QueryProvider = query_provider
        self._max_rows: int = max_rows

    def execute(self, customer_id: object) -> CreditCardsResult:
        """Clean the id, run the query and return at most max_rows cards.

        One extra row is requested so the result can say whether more exist.
        No rows is an empty result, not an error.

        Args:
            customer_id: The customer id exactly as it came in the tool event.

        Raises:
            InvalidInputError: customer_id is missing, not a string or blank.
                Raised before the database is touched.
            DataSourceUnavailableError: The database can't be reached.
            CardLookupError: The query is missing, failed or hit a database limit.
            CardDataIntegrityError: A returned row couldn't be mapped.
        """
        params = self._params(_clean_customer_id(customer_id))
        try:
            query = self._query_provider.get(self.QUERY_NAME)
            rows = self._database_repository.execute_query(query, params)
        except DataSourceConnectionError as exc:
            raise DataSourceUnavailableError() from exc
        except DataAccessError as exc:
            raise CardLookupError() from exc

        try:
            cards = tuple(_to_card(row) for row in rows[: self._max_rows])
        except (KeyError, TypeError, ValueError) as exc:
            raise CardDataIntegrityError() from exc

        return CreditCardsResult(cards=cards, truncated=len(rows) > self._max_rows)

    def _params(self, customer_id: str) -> dict[str, object]:
        """Build the query parameters; every key must match a SQL placeholder."""
        return {"customer_id": customer_id, "limit": self._max_rows + 1}


def _clean_customer_id(raw: object) -> str:
    """Strip and uppercase the raw id; ids look like ``CLI-ITIECUE8PRH9``.

    There is no format check: a malformed or unknown id just finds no cards.
    Whether the caller may see this customer is the Gateway's Cedar policy's job.

    Raises:
        InvalidInputError: The id isn't a string or is blank after stripping.
    """
    if not isinstance(raw, str):
        raise InvalidInputError(
            "customer_id", "is required and must be a non-empty string"
        )
    customer_id = raw.strip().upper()
    if not customer_id:
        raise InvalidInputError(
            "customer_id", "is required and must be a non-empty string"
        )
    return customer_id


def _to_card(row: Mapping[str, Any]) -> CreditCard:
    """Map one database row to a CreditCard.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type.
        ValueError: An amount isn't finite.
    """
    return CreditCard(
        card_last4=_optional_text(row, "card_last4"),
        product_status=_optional_text(row, "product_status"),
        currency=_optional_text(row, "currency"),
        current_balance=_optional_amount(row, "current_balance"),
        credit_limit=_optional_amount(row, "credit_limit"),
        available_credit=_optional_amount(row, "available_credit"),
        expiration_date=_optional_date(row, "expiration_date"),
        days_past_due=_optional_int(row, "days_past_due"),
    )


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


def _optional_int(row: Mapping[str, Any], column: str) -> int | None:
    """Return a nullable integer column; bool is rejected."""
    value = row[column]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{column} is {type(value).__name__}, expected an integer")
    return value
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `$PY -m pytest tests/unit/list_credit_cards/test_list_credit_cards_use_case.py -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: `39 passed`.

- [ ] **Step 6: Lint**

Run: `$PY -m ruff format --check gateway/tools/list_credit_cards tests/unit/list_credit_cards </dev/null && $PY -m ruff check gateway/tools/list_credit_cards tests/unit/list_credit_cards </dev/null`
Expected: clean. If `format --check` lists files, run `ruff format` on them and re-check.

No commit. The task ends with the tree green.

---

### Task 4: The SQL and its contract tests

**Files:**
- Create: `gateway/tools/list_credit_cards/list_credit_cards_lambda/queries/postgresql/list_credit_cards.sql`
- Test: `tests/unit/list_credit_cards/test_query_contracts.py` (the SQL part; Task 7 adds the tool_spec tests)

**Interfaces:**
- Consumes:
  - From Task 3: `ListCreditCardsUseCase`, `execute` and `CreditCard`.
  - From Task 1: `FileQueryProvider`, and the fakes `CUSTOMER_ID`, `FakeDatabaseRepository` and `FakeQueryProvider`.
- Produces:
  - The SQL file `list_credit_cards.sql`, with placeholders `%(customer_id)s` and `%(limit)s`.
  - It selects `product_id` plus every `CreditCard` field name as a column.
  - In `test_query_contracts.py`: `REPO_ROOT`, `TOOL_ROOT`, `QUERIES_DIR`, `SQL_FILE` and the helper `sql()`. Task 7 adds `TOOL_SPEC` and `tool_spec()`.

- [ ] **Step 1: Write the failing test**

`tests/unit/list_credit_cards/test_query_contracts.py`:

```python
"""Drift tests: the SQL file and tool_spec.json must match the Python contracts."""

import dataclasses
import re
import unicodedata
from pathlib import Path

import pytest
from list_credit_cards_lambda.application.use_cases.list_credit_cards import (
    ListCreditCardsUseCase,
)
from list_credit_cards_lambda.domain.entities.credit_card import CreditCard
from list_credit_cards_lambda.infrastructure.queries.file_query_provider import (
    FileQueryProvider,
)

from .fakes import CUSTOMER_ID, FakeDatabaseRepository, FakeQueryProvider

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_ROOT = REPO_ROOT / "gateway/tools/list_credit_cards"
QUERIES_DIR = TOOL_ROOT / "list_credit_cards_lambda/queries/postgresql"
SQL_FILE = QUERIES_DIR / "list_credit_cards.sql"
PLACEHOLDER = re.compile(r"%\((\w+)\)s")
SESSION_STATEMENT = re.compile(r"^\s*SET\b", re.IGNORECASE | re.MULTILINE)
# Escaped so this test file's own encoding can't change the expected value.
CREDIT_CARD_FILTER = "p.product_type = 'Tarjeta Cr\u00e9dito'"


def sql() -> str:
    """Load the real list_credit_cards query."""
    return FileQueryProvider(QUERIES_DIR).get("list_credit_cards")


def flat_sql() -> str:
    """Return the query with every run of whitespace collapsed to one space."""
    return " ".join(sql().split())


def sent_params() -> dict[str, object]:
    """Return the params the use case actually sends to the database repository."""
    database_repository = FakeDatabaseRepository()
    ListCreditCardsUseCase(
        database_repository=database_repository, query_provider=FakeQueryProvider()
    ).execute(CUSTOMER_ID)
    return database_repository.calls[0][1]


def test_sql_placeholders_match_the_use_case_params_exactly() -> None:
    assert set(PLACEHOLDER.findall(sql())) == set(sent_params())


def test_sql_has_no_stray_percent_signs() -> None:
    # psycopg treats every '%' as a placeholder marker once params are passed,
    # including inside comments.
    assert "%" not in PLACEHOLDER.sub("", sql())


def test_sql_sets_no_session_parameters() -> None:
    # DSQL rejects most session parameters (statement_timeout among them). The
    # regex is anchored at line start so "OFFSET" or "SET" in a comment don't count.
    text = sql()

    assert SESSION_STATEMENT.search(text) is None
    assert "statement_timeout" not in text.lower()


def test_session_statement_check_ignores_offset() -> None:
    assert SESSION_STATEMENT.search("SELECT 1\nOFFSET 0\n") is None
    assert SESSION_STATEMENT.search("SELECT 1;\n  set statement_timeout = 0;\n")


def test_sql_filters_on_the_exact_credit_card_product_type() -> None:
    text = sql()

    assert CREDIT_CARD_FILTER in text
    assert "ILIKE" not in text.upper()


def test_credit_card_literal_is_nfc_utf8_without_bom() -> None:
    # A decomposed accent or a BOM would silently match no cards (risk C1).
    raw = SQL_FILE.read_bytes()

    assert not raw.startswith(b"\xef\xbb\xbf")
    assert CREDIT_CARD_FILTER.encode("utf-8") in raw
    assert unicodedata.is_normalized("NFC", raw.decode("utf-8"))


def test_sql_reads_only_the_customers_products() -> None:
    text = flat_sql()

    assert "FROM products AS p WHERE p.customer_id = %(customer_id)s" in text
    assert "JOIN" not in text.upper()


def test_sql_deduplicates_cards_keeping_the_latest_copy() -> None:
    text = flat_sql()

    assert "SELECT DISTINCT ON (p.product_id)" in text
    assert "ORDER BY p.product_id, p.last_updated DESC NULLS LAST" in text


def test_sql_lists_active_cards_first_then_latest_expiry() -> None:
    assert (
        "ORDER BY (deduplicated.product_status = 'Active') DESC NULLS LAST, "
        "deduplicated.expiration_date DESC NULLS LAST, "
        "deduplicated.product_id LIMIT %(limit)s"
    ) in flat_sql()


def test_sql_selects_every_column_the_use_case_maps() -> None:
    text = sql()

    for field in dataclasses.fields(CreditCard):
        assert re.search(rf"\b{field.name}\b", text), field.name
    assert "AS card_last4" in text
    assert "AS available_credit" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `$PY -m pytest tests/unit/list_credit_cards/test_query_contracts.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: `9 failed, 1 passed`. Every test that loads the SQL fails with `QueryNotFoundError`, or with `FileNotFoundError` for the bytes test. `test_session_statement_check_ignores_offset` passes, because it doesn't read the file.

- [ ] **Step 3: Write the SQL**

Write `gateway/tools/list_credit_cards/list_credit_cards_lambda/queries/postgresql/list_credit_cards.sql` as UTF-8 with no BOM. The `é` must be the single code point U+00E9. Don't write a `%` anywhere, including the comments.

```sql
-- list_credit_cards (PostgreSQL dialect, runs on Aurora DSQL)
--
-- A customer's credit cards in every status, active first, one row per product_id.
-- Used by ListCreditCardsUseCase.
--
-- Parameters (psycopg named placeholders):
--   customer_id  text     required (the use case strips and uppercases it)
--   limit        integer  max rows plus one (the extra row sets truncated=true)
--
-- Credit cards are matched exactly on product_type = 'Tarjeta Crédito', a value
-- from the dataset. product_type is in Spanish, so a pattern on "card" would
-- match nothing. This file is UTF-8 and the connection uses client_encoding=utf8,
-- so the accent reaches the database intact.
-- available_credit is NULL when either operand is NULL, and negative when the
-- card is over its limit; both are returned as they are. product_id is selected
-- only for the deduplication and the final tie-break; the use case doesn't map it.
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster. DISTINCT ON,
--   RIGHT(), NULLS LAST and the binds are standard PostgreSQL, but DSQL support is
--   unverified. Column names follow docs/LATAM_Bank_ERD.md; smoke-test against a
--   real cluster and confirm product_type holds 'Tarjeta Crédito' (risk C1).
-- TODO(ledgerlens): R8 - about 2 in 100 rows are duplicated; DISTINCT ON removes
--   them at query time, keeping the latest last_updated. Drop it once the data
--   load deduplicates.
SELECT deduplicated.*
FROM (
    SELECT DISTINCT ON (p.product_id)
           p.product_id,
           RIGHT(p.product_number, 4)          AS card_last4,
           p.product_status,
           p.currency,
           p.current_balance,
           p.credit_limit,
           p.credit_limit - p.current_balance  AS available_credit,
           p.expiration_date,
           p.days_past_due
    FROM products AS p
    WHERE p.customer_id = %(customer_id)s
      AND p.product_type = 'Tarjeta Crédito'
    ORDER BY p.product_id, p.last_updated DESC NULLS LAST
) AS deduplicated
ORDER BY (deduplicated.product_status = 'Active') DESC NULLS LAST,
         deduplicated.expiration_date DESC NULLS LAST,
         deduplicated.product_id
LIMIT %(limit)s
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `$PY -m pytest tests/unit/list_credit_cards/test_query_contracts.py -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: `10 passed`.

No commit. The task ends with the tree green.

---

### Task 5: Presenter

**Files:**
- Create: `gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/presenters/credit_cards.py`
- Test: `tests/unit/list_credit_cards/test_credit_cards_presenter.py`

**Interfaces:**
- Consumes: `CreditCard` and `CreditCardsResult` from Task 3.
- Produces: `present_credit_cards(result: CreditCardsResult) -> dict[str, Any]`, returning `{"cards": list[dict] | None, "count": int, "truncated": bool}`. Each card dict has these keys, in this order: `card_last4`, `product_status`, `currency`, `current_balance`, `credit_limit`, `available_credit`, `expiration_date`, `days_past_due`.

- [ ] **Step 1: Write the failing test**

`tests/unit/list_credit_cards/test_credit_cards_presenter.py`:

```python
"""Tests for the credit cards presenter: the JSON the agent reads."""

import json
from datetime import date
from decimal import Decimal

import pytest
from list_credit_cards_lambda.delivery.presenters.credit_cards import (
    present_credit_cards,
)
from list_credit_cards_lambda.domain.entities.credit_card import (
    CreditCard,
    CreditCardsResult,
)

pytestmark = pytest.mark.unit

AMOUNT_FIELDS = ("current_balance", "credit_limit", "available_credit")


def make_card(**overrides: object) -> CreditCard:
    """Build a CreditCard for presenter tests."""
    values: dict[str, object] = {
        "card_last4": "4821",
        "product_status": "Active",
        "currency": "COP",
        "current_balance": Decimal("1250000"),
        "credit_limit": Decimal("3000000.00"),
        "available_credit": Decimal("1750000.00"),
        "expiration_date": date(2027, 3, 31),
        "days_past_due": 0,
    }
    values.update(overrides)
    return CreditCard(**values)  # type: ignore[arg-type]


def test_presenter_shapes_the_agent_json() -> None:
    result = CreditCardsResult(cards=(make_card(),), truncated=True)

    assert present_credit_cards(result) == {
        "cards": [
            {
                "card_last4": "4821",
                "product_status": "Active",
                "currency": "COP",
                "current_balance": "1250000.00",
                "credit_limit": "3000000.00",
                "available_credit": "1750000.00",
                "expiration_date": "2027-03-31",
                "days_past_due": 0,
            }
        ],
        "count": 1,
        "truncated": True,
    }


@pytest.mark.parametrize("field", AMOUNT_FIELDS)
@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("7"), "7.00"),
        (Decimal("10.005"), "10.01"),
        (Decimal("0.004"), "0.00"),
        (Decimal("-50.255"), "-50.26"),
    ],
)
def test_presenter_formats_amounts_as_two_decimal_strings(
    field: str, amount: Decimal, expected: str
) -> None:
    result = CreditCardsResult((make_card(**{field: amount}),), False)

    assert present_credit_cards(result)["cards"][0][field] == expected


def test_presenter_keeps_nulls_and_output_is_json_serialisable() -> None:
    card = CreditCard(None, None, None, None, None, None, None, None)

    body = present_credit_cards(CreditCardsResult((card,), False))

    assert set(body["cards"][0].values()) == {None}
    json.dumps(body)


def test_days_past_due_stays_an_integer() -> None:
    body = present_credit_cards(CreditCardsResult((make_card(days_past_due=45),), False))

    assert body["cards"][0]["days_past_due"] == 45


def test_presenter_returns_null_cards_when_the_customer_has_none() -> None:
    assert present_credit_cards(CreditCardsResult((), False)) == {
        "cards": None,
        "count": 0,
        "truncated": False,
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `$PY -m pytest tests/unit/list_credit_cards/test_credit_cards_presenter.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: a collection error, `ModuleNotFoundError: No module named 'list_credit_cards_lambda.delivery.presenters.credit_cards'`.

- [ ] **Step 3: Write the implementation**

`gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/presenters/credit_cards.py`:

```python
"""Present credit card results as the JSON returned to the agent."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from list_credit_cards_lambda.domain.entities.credit_card import (
    CreditCard,
    CreditCardsResult,
)

_CENTS: Final = Decimal("0.01")


def present_credit_cards(result: CreditCardsResult) -> dict[str, Any]:
    """Return ``{"cards": [...] | None, "count": n, "truncated": bool}``.

    ``cards`` is ``None`` (JSON null) when the customer has no credit cards; the
    agent then tells the customer they have none. Dates are ISO 8601 strings and
    amounts are 2-decimal strings, so no float rounding reaches the agent.
    Missing values stay ``None``.
    """
    return {
        "cards": [_present(card) for card in result.cards] if result.cards else None,
        "count": len(result.cards),
        "truncated": result.truncated,
    }


def _present(card: CreditCard) -> dict[str, Any]:
    """Convert one card to JSON-safe values."""
    return {
        "card_last4": card.card_last4,
        "product_status": card.product_status,
        "currency": card.currency,
        "current_balance": _amount(card.current_balance),
        "credit_limit": _amount(card.credit_limit),
        "available_credit": _amount(card.available_credit),
        "expiration_date": (
            None if card.expiration_date is None else card.expiration_date.isoformat()
        ),
        "days_past_due": card.days_past_due,
    }


def _amount(value: Decimal | None) -> str | None:
    """Round half-up to 2 decimals as a string, keeping None."""
    if value is None:
        return None
    return str(value.quantize(_CENTS, rounding=ROUND_HALF_UP))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `$PY -m pytest tests/unit/list_credit_cards/test_credit_cards_presenter.py -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: `16 passed`.

No commit. The task ends with the tree green.

---

### Task 6: Dependencies builder and wiring tests

**Files:**
- Create (copied, then renamed): `gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/dependencies/dependencies_builder.py`
- Test: `tests/unit/list_credit_cards/test_delivery_wiring.py`

**Interfaces:**
- Consumes:
  - From Task 3: `ListCreditCardsUseCase`.
  - From Task 4: the SQL file.
  - From Task 1: settings, connectors, adapters and `FakeConnector`.
- Produces, in `list_credit_cards_lambda.delivery.dependencies.dependencies_builder`:
  - `build_list_credit_cards_use_case(env: Mapping[str, str]) -> ListCreditCardsUseCase | None`
  - Copied unchanged: `QUERIES_ROOT`, `SQL_DIALECTS`, `build_settings`, `build_dsql_settings`, `build_connector`, `build_database_repository` and `build_query_provider`.

- [ ] **Step 1: Write the failing test**

`tests/unit/list_credit_cards/test_delivery_wiring.py`:

```python
"""Tests for the dependency wiring of the list_credit_cards tool."""

import list_credit_cards_lambda.utils.connectors.dsql as dsql_module
import pytest
from list_credit_cards_lambda.application.ports.errors import (
    DataSourceConnectionError,
)
from list_credit_cards_lambda.application.use_cases.list_credit_cards import (
    ListCreditCardsUseCase,
)
from list_credit_cards_lambda.delivery.dependencies import dependencies_builder
from list_credit_cards_lambda.delivery.dependencies.dependencies_builder import (
    QUERIES_ROOT,
    SQL_DIALECTS,
    build_connector,
    build_database_repository,
    build_dsql_settings,
    build_list_credit_cards_use_case,
    build_query_provider,
    build_settings,
)
from list_credit_cards_lambda.delivery.settings import (
    ConfigurationError,
    DatabaseEngine,
    DatabaseSettings,
    DsqlSettings,
)
from list_credit_cards_lambda.infrastructure.repositories.dsql_repository import (
    DsqlRepository,
)
from list_credit_cards_lambda.utils.connectors.dsql import DsqlConnector

from .fakes import CUSTOMER_ID, FakeConnector, make_row

pytestmark = pytest.mark.unit

ENDPOINT = "abc123.dsql.us-east-1.on.aws"
ENV = {"DSQL_CLUSTER_ENDPOINT": ENDPOINT, "AWS_REGION": "us-east-1"}
SETTINGS = DatabaseSettings(engine=DatabaseEngine.AURORA_DSQL, max_rows=25)


def test_build_settings_reads_the_environment() -> None:
    assert build_settings(ENV) == SETTINGS


def test_build_dsql_settings_reads_the_environment() -> None:
    assert build_dsql_settings(ENV) == DsqlSettings(
        cluster_endpoint=ENDPOINT, region="us-east-1", db_user="ledgerlens_readonly"
    )


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
    assert "DISTINCT ON" in provider.get("list_credit_cards")


def test_every_engine_has_a_dialect_folder_with_the_sql() -> None:
    for engine in DatabaseEngine:
        sql_file = QUERIES_ROOT / SQL_DIALECTS[engine] / "list_credit_cards.sql"
        assert sql_file.is_file()


def test_queries_root_is_this_tools_own_folder() -> None:
    assert QUERIES_ROOT.parent.name == "list_credit_cards_lambda"


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


def test_use_case_is_wired_with_real_adapters_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector([make_row()])
    use_fake_connector(monkeypatch, connector)

    use_case = build_list_credit_cards_use_case(ENV)
    assert isinstance(use_case, ListCreditCardsUseCase)
    result = use_case.execute(CUSTOMER_ID)

    assert result.cards[0].card_last4 == "4821"
    executed_sql, params = connector.connections[-1].cursors[0].executed[0]
    assert "FROM products" in executed_sql
    assert params == {"customer_id": CUSTOMER_ID, "limit": 26}


def test_use_case_uses_max_rows_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector([make_row(product_id=f"PRD-{i}") for i in range(4)])
    use_fake_connector(monkeypatch, connector)

    use_case = build_list_credit_cards_use_case({**ENV, "MAX_ROWS": "3"})
    assert use_case is not None
    result = use_case.execute(CUSTOMER_ID)

    assert len(result.cards) == 3
    assert result.truncated is True


def test_use_case_build_opens_the_connection_eagerly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector()
    use_fake_connector(monkeypatch, connector)

    build_list_credit_cards_use_case(ENV)

    assert len(connector.connections) == 1


def test_use_case_build_survives_a_failed_cold_start_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector(DataSourceConnectionError("no route to host"), [])
    use_fake_connector(monkeypatch, connector)

    use_case = build_list_credit_cards_use_case(ENV)

    assert use_case is not None
    assert use_case.execute(CUSTOMER_ID).cards == ()


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
    assert build_list_credit_cards_use_case(env) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `$PY -m pytest tests/unit/list_credit_cards/test_delivery_wiring.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: a collection error, `ModuleNotFoundError: No module named 'list_credit_cards_lambda.delivery.dependencies.dependencies_builder'`.

- [ ] **Step 3: Copy the builder and rename the tool**

```bash
sed -e 's/list_card_transactions/list_credit_cards/g' \
    -e 's/ListCardTransactionsUseCase/ListCreditCardsUseCase/g' \
  gateway/tools/list_card_transactions/list_card_transactions_lambda/delivery/dependencies/dependencies_builder.py \
  > gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/dependencies/dependencies_builder.py
grep -n -i "transaction" gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/dependencies/dependencies_builder.py
```

Expected: the grep prints nothing. The source builder mentions "transaction" only in tool and class names, and the sed renames all of them.

- [ ] **Step 4: Run the test to verify it passes**

Run: `$PY -m pytest tests/unit/list_credit_cards/test_delivery_wiring.py -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: `20 passed`.

- [ ] **Step 5: Lint**

Run: `$PY -m ruff format --check gateway/tools/list_credit_cards tests/unit/list_credit_cards </dev/null && $PY -m ruff check gateway/tools/list_credit_cards tests/unit/list_credit_cards </dev/null`
Expected: clean. The sed can change line lengths, so if `format --check` lists the builder, run `ruff format` on it and re-check.

No commit. The task ends with the tree green.

---

### Task 7: Handler, tool_spec and their tests

**Files:**
- Create: `gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/handler.py`
- Create: `gateway/tools/list_credit_cards/tool_spec.json`
- Test: `tests/unit/list_credit_cards/test_list_credit_cards_handler.py`
- Modify: `tests/unit/list_credit_cards/test_query_contracts.py` (add the tool_spec tests)

**Interfaces:**
- Consumes:
  - From Task 6: `build_list_credit_cards_use_case`, `build_database_repository` and `build_query_provider`.
  - From Task 5: `present_credit_cards`.
  - From Task 2: `DataSourceUnavailableError`, `CardLookupError` and `DomainError`.
  - From Task 3: `ListCreditCardsUseCase`.
- Produces, in `list_credit_cards_lambda.delivery.handler`:
  - `handler(event: object, context: object) -> dict[str, Any]`
  - `TOOL_NAME = "list_credit_cards"`
  - `UNEXPECTED_ERROR_MESSAGE`
  - the module global `USE_CASE`
  - `tool_spec.json`, a one-element JSON array.

- [ ] **Step 1: Write the failing handler test**

`tests/unit/list_credit_cards/test_list_credit_cards_handler.py`:

```python
"""Tests for the list_credit_cards Lambda handler."""

import importlib
import json
from types import ModuleType, SimpleNamespace
from typing import Any

import psycopg
import pytest
from list_credit_cards_lambda.application.ports.errors import (
    DataSourceConnectionError,
)
from list_credit_cards_lambda.application.use_cases.list_credit_cards import (
    ListCreditCardsUseCase,
)
from list_credit_cards_lambda.delivery.dependencies.dependencies_builder import (
    build_database_repository,
    build_query_provider,
)
from list_credit_cards_lambda.delivery.settings import DatabaseEngine
from list_credit_cards_lambda.domain.errors import (
    CardLookupError,
    DataSourceUnavailableError,
)

from .fakes import CUSTOMER_ID, FakeConnector, make_row

pytestmark = pytest.mark.unit

EVENT = {"customer_id": CUSTOMER_ID}
INVALID_CUSTOMER_ID = (
    "Invalid value for 'customer_id': is required and must be a non-empty "
    "string. Ask the customer to confirm and retry."
)


def make_context(
    tool_name: str = "list-credit-cards-target___list_credit_cards",
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
    ):
        monkeypatch.delenv(name, raising=False)
    import list_credit_cards_lambda.delivery.handler as handler_module

    return importlib.reload(handler_module)


def wire(module: ModuleType, monkeypatch: pytest.MonkeyPatch, connector: Any) -> None:
    """Point the handler's global use case at real adapters over a fake connector."""
    use_case = ListCreditCardsUseCase(
        database_repository=build_database_repository(
            DatabaseEngine.AURORA_DSQL, connector
        ),
        query_provider=build_query_provider(DatabaseEngine.AURORA_DSQL),
        max_rows=25,
    )
    monkeypatch.setattr(module, "USE_CASE", use_case)


def body(response: dict[str, Any]) -> dict[str, Any]:
    """Decode the JSON text of a success response."""
    content = response["content"]
    assert content[0]["type"] == "text"
    return json.loads(content[0]["text"])


def sent_params(connector: FakeConnector) -> Any:
    """Return the params of the first query the connector executed."""
    return connector.connections[-1].cursors[0].executed[0][1]


def test_success_returns_gateway_content_with_the_cards(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector([make_row()]))

    payload = body(module.handler(EVENT, make_context()))

    assert payload["count"] == 1
    assert payload["truncated"] is False
    assert payload["cards"][0] == {
        "card_last4": "4821",
        "product_status": "Active",
        "currency": "COP",
        "current_balance": "1250000.00",
        "credit_limit": "3000000.00",
        "available_credit": "1750000.00",
        "expiration_date": "2027-03-31",
        "days_past_due": 0,
    }


def test_bare_customer_id_is_cleaned_before_the_query(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = FakeConnector([make_row()])
    wire(module, monkeypatch, connector)

    module.handler({"customer_id": "  cli-itiecue8prh9 "}, make_context())

    assert sent_params(connector) == {"customer_id": "CLI-ITIECUE8PRH9", "limit": 26}


def test_unknown_event_keys_are_ignored(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = FakeConnector([make_row()])
    wire(module, monkeypatch, connector)

    response = module.handler({**EVENT, "status": "Blocked"}, make_context())

    assert "content" in response
    assert sent_params(connector) == {"customer_id": CUSTOMER_ID, "limit": 26}


def test_no_cards_returns_null_cards(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector([]))

    assert body(module.handler(EVENT, make_context())) == {
        "cards": None,
        "count": 0,
        "truncated": False,
    }


@pytest.mark.parametrize(
    "event",
    [
        None,
        [],
        "customer_id=CLI-ITIECUE8PRH9",
        {},
        {"customer_id": None},
        {"customer_id": ""},
        {"customer_id": "   "},
        {"customer_id": 42},
        {"customer_id": True},
    ],
)
def test_invalid_customer_id_returns_the_input_error_without_a_query(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, event: object
) -> None:
    connector = FakeConnector([make_row()])
    wire(module, monkeypatch, connector)

    response = module.handler(event, make_context())

    assert response == {"error": INVALID_CUSTOMER_ID}
    assert connector.connections == []


def test_query_failure_returns_the_card_lookup_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = psycopg.errors.UndefinedTable('relation "products" does not exist')
    wire(module, monkeypatch, FakeConnector(error))

    response = module.handler(EVENT, make_context())

    assert response == {"error": CardLookupError.MESSAGE}


@pytest.mark.parametrize(
    "context",
    [
        make_context("other-target___text_analysis_tool"),
        make_context("list-card-transactions-target___list_card_transactions"),
        None,
        SimpleNamespace(client_context=None),
        SimpleNamespace(client_context=SimpleNamespace(custom={})),
        SimpleNamespace(client_context=SimpleNamespace(custom=None)),
    ],
)
def test_wrong_or_missing_tool_name_returns_an_error(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, context: object
) -> None:
    connector = FakeConnector()
    wire(module, monkeypatch, connector)

    response = module.handler(EVENT, context)

    assert set(response) == {"error"}
    assert "list_credit_cards" in response["error"]
    assert connector.connections == []


def test_tool_name_without_a_target_prefix_is_accepted(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector([]))

    assert "content" in module.handler(EVENT, make_context("list_credit_cards"))


def test_unexpected_exception_returns_a_generic_message_without_internals(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: object) -> None:
        raise RuntimeError("password=hunter2 host=db.internal")

    monkeypatch.setattr(module, "USE_CASE", SimpleNamespace(execute=explode))

    response = module.handler(EVENT, make_context())

    assert response == {"error": module.UNEXPECTED_ERROR_MESSAGE}
    assert module.UNEXPECTED_ERROR_MESSAGE == (
        "Unexpected internal error listing credit cards. "
        "Offer a hand-off to a human agent."
    )
    assert "hunter2" not in response["error"]


def test_missing_configuration_returns_data_source_unavailable(
    module: ModuleType,
) -> None:
    assert module.USE_CASE is None

    response = module.handler(EVENT, make_context())

    assert response == {"error": DataSourceUnavailableError.MESSAGE}


def test_cold_start_failure_then_failed_retry_returns_unavailable(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector(DataSourceConnectionError("down")))

    response = module.handler(EVENT, make_context())

    assert response == {"error": DataSourceUnavailableError.MESSAGE}
```

- [ ] **Step 2: Add the failing tool_spec tests to the contracts**

In `tests/unit/list_credit_cards/test_query_contracts.py`, make three edits.

Add `import json` and `from typing import Any` to the imports. The block then starts:

```python
import dataclasses
import json
import re
import unicodedata
from pathlib import Path
from typing import Any
```

After the `SQL_FILE = ...` line, add:

```python
TOOL_SPEC = TOOL_ROOT / "tool_spec.json"
```

Append at the end of the file:

```python
def tool_spec() -> dict[str, Any]:
    """Load the single tool definition from tool_spec.json."""
    specs = json.loads(TOOL_SPEC.read_text(encoding="utf-8"))
    assert isinstance(specs, list) and len(specs) == 1
    return specs[0]


def test_tool_spec_name_and_required_fields() -> None:
    spec = tool_spec()

    assert spec["name"] == "list_credit_cards"
    assert spec["inputSchema"]["required"] == ["customer_id"]


def test_tool_spec_has_only_the_customer_id_property() -> None:
    properties = tool_spec()["inputSchema"]["properties"]

    assert set(properties) == {"customer_id"}
    assert properties["customer_id"]["type"] == "string"


def test_tool_spec_description_states_the_cap_and_the_null_result() -> None:
    description = tool_spec()["description"]

    assert "at most 25 cards" in description
    assert "'cards' is null when the customer has no credit cards" in description
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `$PY -m pytest tests/unit/list_credit_cards/test_list_credit_cards_handler.py tests/unit/list_credit_cards/test_query_contracts.py -q -p no:cacheprovider </dev/null 2>&1 | tail -4`
Expected:
- The handler file fails to collect with `ModuleNotFoundError: No module named 'list_credit_cards_lambda.delivery.handler'`.
- In the contracts file, the three tool_spec tests fail with `FileNotFoundError` and the 10 SQL tests pass.

- [ ] **Step 4: Write the handler**

`gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/handler.py`:

```python
"""Lambda handler for the ``list_credit_cards`` Gateway tool.

Handler string: ``list_credit_cards_lambda/delivery/handler.handler``.

Input: the tool arguments as the event (see
``gateway/tools/list_credit_cards/tool_spec.json``); the tool name arrives in
``context.client_context.custom["bedrockAgentCoreToolName"]`` with a
``<target>___`` prefix, as in ``gateway/tools/sample_tool``. ``customer_id`` is
passed to the use case bare, exactly as it came; the use case cleans it.

Output: ``{"content": [{"type": "text", "text": <JSON>}]}`` on success, or
``{"error": <agent-facing message>}``. Unlike the sample tool, raw exception text
is never returned: it could leak SQL, hosts or driver details to the model.

The use case and its whole graph (settings, connector, connection, adapters) are
built once, when the module loads, by dependencies_builder; a warm container
reuses them. The handler builds nothing itself.

TODO(ledgerlens): R1 - no CDK yet: no PythonFunction, Gateway target, env vars
  (DB_ENGINE, DSQL_CLUSTER_ENDPOINT, DSQL_DB_USER) or dsql:DbConnect grant on the
  cluster ARN (dsql:DbConnectAdmin only if DSQL_DB_USER=admin). The tool can't be
  deployed or called by the agent until the CDK spec lands.
TODO(ledgerlens): R5 - customer_id is trusted from the tool input. Authorization
  depends on a Cedar policy matching it to the token's customer_id claim; neither
  the policy nor the claim exists yet (product design sections 5 and 10).
"""

import json
import logging
import os
from collections.abc import Mapping
from typing import Any, Final

from list_credit_cards_lambda.delivery.dependencies.dependencies_builder import (
    build_list_credit_cards_use_case,
)
from list_credit_cards_lambda.delivery.presenters.credit_cards import (
    present_credit_cards,
)
from list_credit_cards_lambda.domain.errors import (
    DataSourceUnavailableError,
    DomainError,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TOOL_NAME: Final = "list_credit_cards"
_TOOL_NAME_DELIMITER: Final = "___"
UNEXPECTED_ERROR_MESSAGE: Final = (
    "Unexpected internal error listing credit cards. "
    "Offer a hand-off to a human agent."
)
_WRONG_TOOL_MESSAGE: Final = (
    f"This function only serves the '{TOOL_NAME}' tool. "
    "Don't retry; offer a hand-off to a human agent."
)


USE_CASE = build_list_credit_cards_use_case(os.environ)


def handler(event: object, context: object) -> dict[str, Any]:
    """List the customer's credit cards for the agent.

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
        if USE_CASE is None:
            raise DataSourceUnavailableError()
        body = present_credit_cards(USE_CASE.execute(_customer_id(event)))
    except DomainError as err:
        logger.warning(
            "%s returned an error: %s", TOOL_NAME, err.message, exc_info=True
        )
        return {"error": err.message}
    except Exception:
        logger.exception("Unexpected error in %s", TOOL_NAME)
        return {"error": UNEXPECTED_ERROR_MESSAGE}

    logger.info(
        "%s returned %d cards (truncated=%s)",
        TOOL_NAME,
        body["count"],
        body["truncated"],
    )
    return {"content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]}


def _customer_id(event: object) -> object:
    """Return the event's customer_id as it came, or None for a non-object event.

    The use case validates and cleans it, so a bad value becomes the
    customer_id InvalidInputError message.
    """
    if not isinstance(event, Mapping):
        return None
    return event.get("customer_id")


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

- [ ] **Step 5: Write the tool_spec**

`gateway/tools/list_credit_cards/tool_spec.json` (UTF-8, two-space indent, ends with a newline):

```json
[
  {
    "name": "list_credit_cards",
    "description": "Lists the customer's credit cards in every status (active, blocked, closed, suspended) with last 4 digits, status, currency, balance, credit limit, available credit, expiry date and days past due. Use when the customer asks about their cards, or to confirm which card they mean before searching transactions or blocking a card. Returns at most 25 cards, active first, as JSON with 'cards', 'count' and 'truncated'. Amounts are strings with 2 decimals in the card's currency. 'cards' is null when the customer has no credit cards.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "customer_id": {
          "type": "string",
          "description": "The authenticated customer's id from get_session_context."
        }
      },
      "required": ["customer_id"]
    }
  }
]
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `$PY -m pytest tests/unit/list_credit_cards/test_list_credit_cards_handler.py tests/unit/list_credit_cards/test_query_contracts.py -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: `37 passed`. That's 24 in the handler file and 13 in the contracts file.

- [ ] **Step 7: Run the whole tool's tests and lint**

Run: `$PY -m pytest tests/unit/list_credit_cards -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: `203 passed`. The counts are:

| File | Tests |
|---|---|
| copied infrastructure tests | 80 |
| `test_errors.py` | 11 |
| use case | 39 |
| contracts | 13 |
| presenter | 16 |
| wiring | 20 |
| handler | 24 |

Run: `$PY -m ruff format --check gateway/tools/list_credit_cards tests/unit/list_credit_cards </dev/null && $PY -m ruff check gateway/tools/list_credit_cards tests/unit/list_credit_cards </dev/null`
Expected: clean.

If a per-file count differs from this plan's number but every test passes and each listed test name exists, the plan's arithmetic is wrong. Record a ruling with the real count; it isn't a failure.

No commit. The task ends with the tree green.

---

### Task 8: Product design fix, full verification and hand-over

**Files:**
- Modify: `docs/LEDGERLENS_PRODUCT_DESIGN.md` (§7.1 Q1, §7.3, §7.7)
- Modify: `docs/superpowers/specs/2026-10-01-list-credit-cards-lambda-design.md` (status line)

**Interfaces:**
- Consumes: everything above.
- Produces: a green tree, ready for the user's commit command.

- [ ] **Step 1: Find the lines to fix**

Run: `grep -n "ILIKE '%card%'\|^\*\*Query:\*\* Q1" docs/LEDGERLENS_PRODUCT_DESIGN.md`
Expected: exactly three lines:
- `  AND p.product_type ILIKE '%card%';` (§7.1)
- `**Query:** Q1 (section 7.1), without the customer columns.` (§7.3)
- `  AND product_type ILIKE '%card%'` (§7.7)

Don't trust line numbers. Edit by matching the text.

- [ ] **Step 2: Apply the three edits**

§7.1: replace `  AND p.product_type ILIKE '%card%';` with `  AND p.product_type = 'Tarjeta Crédito';`

§7.7: replace `  AND product_type ILIKE '%card%'` with `  AND product_type = 'Tarjeta Crédito'`

§7.3: replace `**Query:** Q1 (section 7.1), without the customer columns.` with:

```markdown
**Query:** Q1 (section 7.1), without the customer columns.

Credit cards only (`product_type = 'Tarjeta Crédito'`), in every status, active first. Spec: [2026-10-01-list-credit-cards-lambda-design.md](superpowers/specs/2026-10-01-list-credit-cards-lambda-design.md).
```

In the spec, replace `**Status:** Draft, awaiting review.` with `**Status:** Approved 2026-10-01.`

Run: `grep -n "ILIKE '%card%'" docs/LEDGERLENS_PRODUCT_DESIGN.md; grep -c "Tarjeta Crédito" docs/LEDGERLENS_PRODUCT_DESIGN.md`
Expected: the first grep prints nothing, and the count is `3`. The other `ILIKE` lines in §7.1's page-title query and §7.4's merchant filter stay as they are.

- [ ] **Step 3: Run the full unit suite from a clean cache**

```bash
find gateway/tools/list_credit_cards tests/unit/list_credit_cards -name __pycache__ -type d -exec rm -rf {} +
$PY -m pytest tests/unit -q -p no:cacheprovider </dev/null 2>&1 | tail -2
```

Expected: `464 passed`, which is the 261 existing tests plus 203 new ones. There are no failures or errors. This one run proves the two tools' packages and test packages don't collide.

- [ ] **Step 4: Run the isolation and lint checks**

```bash
grep -rn "list_card_transactions" gateway/tools/list_credit_cards tests/unit/list_credit_cards
grep -rn "list_credit_cards" gateway/tools/list_card_transactions tests/unit/list_card_transactions
git status --short gateway/tools/list_card_transactions tests/unit/list_card_transactions
$PY -m ruff format --check gateway/tools/list_credit_cards tests/unit/list_credit_cards </dev/null
$PY -m ruff check gateway/tools/list_credit_cards tests/unit/list_credit_cards </dev/null
```

Expected:
- Both greps print nothing.
- `git status` for the first tool prints nothing.
- Both ruff commands are clean.

- [ ] **Step 5: Show the change set and hand over for the commit**

Run: `git status --short`
Expected, with no other paths:

```
 M docs/LEDGERLENS_PRODUCT_DESIGN.md
 M infra-cdk/config.yaml
?? docs/superpowers/plans/2026-10-01-list-credit-cards-lambda.md
?? docs/superpowers/specs/2026-10-01-list-credit-cards-lambda-design.md
?? gateway/tools/list_credit_cards/
?? tests/unit/list_credit_cards/
```

`infra-cdk/config.yaml` was already modified before this plan. It must never be staged.

Stop here and ask the user for the commit command. Don't commit.
