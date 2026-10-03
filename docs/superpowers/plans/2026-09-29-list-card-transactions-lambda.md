# `list_card_transactions` Lambda Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first LedgerLens Gateway tool, `list_card_transactions`, as a hexagonal Python core that every later tool Lambda reuses.

**Architecture:** One shared asset (`gateway/tools/ledgerlens_tools/ledgerlens/`) with `domain` ← `application` ← (`infrastructure`, `utils`, `delivery`) layers. The use case depends only on the `DatabaseRepository` and `QueryProvider` ports. The PostgreSQL adapter runs SQL loaded from `queries/postgresql/`. The Lambda handler in `delivery` keeps the Aurora connector global and gets the use case from `build_dependencies(connector, settings)`.

**Tech Stack:** Python (code must run on 3.10 locally and 3.13 in Lambda), psycopg 3 (`psycopg[binary]`), boto3 (Secrets Manager), pytest, ruff.

**Spec:** [`docs/superpowers/specs/2026-09-29-list-card-transactions-lambda-design.md`](../specs/2026-09-29-list-card-transactions-lambda-design.md). Read it before starting. The deviations listed below have already been merged back into the spec.

### Deviations from the first version of the spec (already reflected in the spec)
- `CardTransaction.currency` and `transaction_status` are `str | None`. The dataset has about 5% nulls, so making them required would turn ordinary rows into `DataIntegrityError`.
- `build_dependencies(connector, settings)` takes a `DatabaseSettings` so it doesn't read `os.environ` itself.
- Extra delivery files:
  - `delivery/settings.py`: environment parsing and `ConfigurationError`.
  - `delivery/database.py`: engine wiring shared by every tool.
  - `delivery/presenters/card_transactions.py`: JSON shaping.
- `utils/connectors/base.py` defines a `PsycopgConnector` Protocol, so the repository and tests don't depend on the concrete connector class.
- The merchant filter uses `strpos(lower(...), lower(...)) > 0` instead of `ILIKE '%' || ... || '%'`. Wildcards in the input then match literally, and the SQL needs no `%%` escaping for psycopg.

## Global Constraints

- Code must run on **Python 3.10**: no `datetime.UTC`, no `typing.Self`, no `StrEnum`, no `except*`. Lambda will run 3.13.
- Ruff: line length 88, rules `E,F,W,I,N,UP,S,B,A,C4,T20` (from `pyproject.toml`). Every task ends with `ruff check --fix` and `ruff format` on the files it touched.
- Heavy type hints on every function (`disallow_untyped_defs` style). Every module, class and public function has a docstring.
- Layer rule: nothing under `ledgerlens/domain` or `ledgerlens/application` imports `psycopg`, `boto3`, `ledgerlens.infrastructure`, `ledgerlens.utils` or `ledgerlens.delivery`.
- Agent-facing messages never contain exception text, SQL, hostnames or driver details.
- Risks are left as `TODO(ledgerlens): R<n> - ...` comments exactly where the spec's §8 table says.
- Tests live in `tests/unit/ledgerlens_tools/`, each module starts with `pytestmark = pytest.mark.unit`, and none touches a database, the network or AWS.
- Git:
  - `git add` only the files named in the task. **Never** stage `infra-cdk/config.yaml` (it contains a personal email) or `docs/architecture-diagram/FAST-architecture.drawio`.
  - Commit messages must **not** contain a `Co-Authored-By` line.
  - Don't push.
- No AWS deploys and no CDK changes (out of scope, R1).

## Review Focus

1. **Empty strings or `null` in optional tool arguments** (`"card_last4": ""`, `"status": null`): the agent often sends these. They must mean "no filter", not a validation error. Tested in Task 2.
2. **Dates in other formats or impossible dates** (`2026/09/01`, `2026-9-1`, `20260901`, `2026-02-30`): must raise `InvalidInputError` identically on 3.10 and 3.13. 3.11+ `fromisoformat` accepts `20260901`, so a strict regex runs first. Tested in Task 2.
3. **Odd amounts** (`true`, `NaN`, `Infinity`, `"12.30"`, `10.5`): booleans and non-finite numbers are rejected. Numeric strings and floats parse to exact `Decimal`s. Tested in Task 2.
4. **Rows with `NULL` currency, status or merchant**: returned as `null` to the agent, not turned into `DataIntegrityError`. Tested in Task 3.
5. **A malformed Lambda invocation** (`event` is `None` or a list, `context` is `None`, no `client_context`): returns a clean `{"error": ...}` and never raises. Tested in Task 7.

---

## File Map

```
gateway/tools/ledgerlens_tools/
├── requirements.txt                                         Task 1
└── ledgerlens/
    ├── __init__.py (+ every sub-package __init__.py)         Task 1
    ├── domain/errors.py                                     Task 1
    ├── domain/value_objects/transaction_filters.py          Task 2
    ├── domain/entities/card_transaction.py                  Task 3
    ├── application/ports/errors.py                          Task 1
    ├── application/ports/database_repository.py             Task 3
    ├── application/ports/query_provider.py                  Task 3
    ├── application/use_cases/list_card_transactions.py      Task 3
    ├── infrastructure/queries/file_query_provider.py        Task 4
    ├── queries/postgresql/list_card_transactions.sql        Task 4
    ├── utils/connectors/base.py                             Task 5
    ├── utils/connectors/aurora_postgresql.py                Task 5
    ├── infrastructure/repositories/postgresql_repository.py Task 5
    ├── delivery/settings.py                                 Task 6
    ├── delivery/database.py                                 Task 6
    ├── delivery/dependencies/list_card_transactions.py      Task 6
    ├── delivery/presenters/card_transactions.py             Task 6
    └── delivery/list_card_transactions_handler.py           Task 7
gateway/tools/list_card_transactions/tool_spec.json          Task 4
requirements-dev.txt (modify)                                Task 1
tests/unit/ledgerlens_tools/
├── conftest.py                                              Task 1
├── ledgerlens_fakes.py                                      Task 3 (extended in Task 5)
├── test_errors.py                                           Task 1
├── test_transaction_filters.py                              Task 2
├── test_list_card_transactions_use_case.py                  Task 3
├── test_file_query_provider.py                              Task 4
├── test_query_contracts.py                                  Task 4
├── test_aurora_postgresql_connector.py                      Task 5
├── test_postgresql_repository.py                            Task 5
├── test_delivery_wiring.py                                  Task 6
└── test_list_card_transactions_handler.py                   Task 7
```

`tests/unit/ledgerlens_tools/` has **no** `__init__.py`. pytest's default `prepend` import mode then puts that folder on `sys.path`, so `from ledgerlens_fakes import ...` works. (`tests/unit` itself isn't a package: its file is misspelled `__init.py`. Leave it alone.)

All commands run from the repo root, `C:\GITHUB REPOS\ledgerlens-bank-assistant`, in **Git Bash**. They use `&&` and `grep`, which Windows PowerShell 5.1 doesn't support. Lint always runs `ruff format` first and then `ruff check --fix`, so that E501 only reports lines the formatter can't wrap.

---

### Task 1: Scaffold packages, errors, dev dependencies and test path

**Files:**
- Create:
  - `gateway/tools/ledgerlens_tools/requirements.txt`
  - the 15 `__init__.py` files listed in Step 3
  - `gateway/tools/ledgerlens_tools/ledgerlens/domain/errors.py`
  - `gateway/tools/ledgerlens_tools/ledgerlens/application/ports/errors.py`
  - `tests/unit/ledgerlens_tools/conftest.py`
- Modify: `requirements-dev.txt`
- Test: `tests/unit/ledgerlens_tools/test_errors.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `ledgerlens.domain.errors`:
    - `DomainError(message: str)` with `.message: str`
    - `InvalidInputError(field: str, reason: str)` with `.field` and `.reason`
    - `DataSourceUnavailableError()`, `SearchTooBroadError()`, `TransactionLookupError()`, `DataIntegrityError()`, each with a fixed message and a `MESSAGE` class attribute
  - `ledgerlens.application.ports.errors`: `DataAccessError(Exception)` and its subclasses `DataSourceConnectionError`, `QueryTimeoutError`, `QueryExecutionError`, `QueryNotFoundError`.

- [ ] **Step 1: Install the dev dependencies**

Append to `requirements-dev.txt` (keep the existing lines):

```text
psycopg[binary]>=3.2,<4
```

Run: `python -m pip install "psycopg[binary]>=3.2,<4" "ruff==0.14.1"`
Expected: `Successfully installed ...`. Then run `python -c "import psycopg; print(psycopg.__version__)"`, which should print `3.x.y`.

- [ ] **Step 2: Create the test path setup**

`tests/unit/ledgerlens_tools/conftest.py`:

```python
"""Pytest setup for the LedgerLens tools: make the ``ledgerlens`` package importable.

The package lives in the Lambda asset root ``gateway/tools/ledgerlens_tools``, so
that folder is put on ``sys.path`` exactly as the Lambda runtime does.
"""

import sys
from pathlib import Path

_ASSET_ROOT = (
    Path(__file__).resolve().parents[3] / "gateway" / "tools" / "ledgerlens_tools"
)

if str(_ASSET_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASSET_ROOT))
```

- [ ] **Step 3: Create the package skeleton**

Create each `__init__.py` below. Its only content is the one-line docstring shown.

| File (under `gateway/tools/ledgerlens_tools/ledgerlens/`) | Docstring |
|---|---|
| `__init__.py` | `"""LedgerLens bank assistant tools: shared hexagonal core for every tool Lambda."""` |
| `domain/__init__.py` | `"""Domain layer: entities, value objects and agent-facing errors. No I/O."""` |
| `domain/entities/__init__.py` | `"""Domain entities returned by use cases."""` |
| `domain/value_objects/__init__.py` | `"""Validated, immutable inputs to use cases."""` |
| `application/__init__.py` | `"""Application layer: use cases and the ports they depend on."""` |
| `application/ports/__init__.py` | `"""Ports (interfaces) implemented by infrastructure adapters."""` |
| `application/use_cases/__init__.py` | `"""Use cases: one class per tool."""` |
| `infrastructure/__init__.py` | `"""Infrastructure layer: adapters that implement the application ports."""` |
| `infrastructure/repositories/__init__.py` | `"""DatabaseRepository adapters, one per database engine."""` |
| `infrastructure/queries/__init__.py` | `"""QueryProvider adapters."""` |
| `utils/__init__.py` | `"""Shared technical helpers used by infrastructure and delivery."""` |
| `utils/connectors/__init__.py` | `"""Database connectors that own connection lifecycle."""` |
| `delivery/__init__.py` | `"""Delivery layer: Lambda handlers, configuration and dependency wiring."""` |
| `delivery/dependencies/__init__.py` | `"""Per-tool dependency builders, each exposing build_dependencies()."""` |
| `delivery/presenters/__init__.py` | `"""Turn use-case results into the JSON returned to the agent."""` |

`gateway/tools/ledgerlens_tools/requirements.txt`:

```text
# Runtime dependencies for every LedgerLens tool Lambda (shared asset).
# boto3 is provided by the AWS Lambda Python runtime and is not listed here.
#
# TODO(ledgerlens): R1 - no CDK yet: nothing packages or deploys this asset, and no
#   Gateway target points at it. See the CDK spec (product design section 15).
# TODO(ledgerlens): R9 - psycopg[binary] ships native wheels. Build with a CDK
#   PythonFunction (Docker bundling, ARM64 Linux); plain Code.fromAsset won't work.
psycopg[binary]>=3.2,<4
```

- [ ] **Step 4: Write the failing test**

`tests/unit/ledgerlens_tools/test_errors.py`:

```python
"""Tests for domain and port error definitions."""

import pytest

from ledgerlens.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    QueryExecutionError,
    QueryNotFoundError,
    QueryTimeoutError,
)
from ledgerlens.domain.errors import (
    DataIntegrityError,
    DataSourceUnavailableError,
    DomainError,
    InvalidInputError,
    SearchTooBroadError,
    TransactionLookupError,
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
            DataSourceUnavailableError,
            "Transaction data is temporarily unavailable. Tell the customer and "
            "offer to retry in a moment or hand off to a human agent.",
        ),
        (
            SearchTooBroadError,
            "The transaction search took too long. Retry with a narrower date "
            "range or add a card or merchant filter.",
        ),
        (
            TransactionLookupError,
            "Transactions can't be retrieved right now due to an internal error. "
            "Don't retry; offer a hand-off to a human agent.",
        ),
        (
            DataIntegrityError,
            "Transaction data came back in an unexpected format. Don't retry; "
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
    "error_type",
    [
        DataSourceConnectionError,
        QueryTimeoutError,
        QueryExecutionError,
        QueryNotFoundError,
    ],
)
def test_port_errors_share_a_base_class(error_type: type[DataAccessError]) -> None:
    assert issubclass(error_type, DataAccessError)
    assert not issubclass(error_type, DomainError)
```

- [ ] **Step 5: Run the test to verify it fails**

Run: `python -m pytest tests/unit/ledgerlens_tools/test_errors.py -v`
Expected: collection ERROR with `ModuleNotFoundError: No module named 'ledgerlens.domain.errors'`.

- [ ] **Step 6: Implement the errors**

`gateway/tools/ledgerlens_tools/ledgerlens/domain/errors.py`:

```python
"""Domain errors: the only failures the agent is allowed to see.

Each message says what went wrong and what the agent should do next. Messages
never contain SQL, hostnames, driver output or other internal details.
"""

from typing import ClassVar


class DomainError(Exception):
    """Base class for agent-facing errors raised by use cases and value objects.

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
        "Transaction data is temporarily unavailable. Tell the customer and "
        "offer to retry in a moment or hand off to a human agent."
    )


class SearchTooBroadError(_FixedMessageError):
    """The query hit the statement timeout; a narrower search may succeed."""

    MESSAGE: ClassVar[str] = (
        "The transaction search took too long. Retry with a narrower date "
        "range or add a card or merchant filter."
    )


class TransactionLookupError(_FixedMessageError):
    """The query failed for an internal reason; retrying won't help."""

    MESSAGE: ClassVar[str] = (
        "Transactions can't be retrieved right now due to an internal error. "
        "Don't retry; offer a hand-off to a human agent."
    )


class DataIntegrityError(_FixedMessageError):
    """A returned row couldn't be mapped to a domain entity."""

    MESSAGE: ClassVar[str] = (
        "Transaction data came back in an unexpected format. Don't retry; "
        "offer a hand-off to a human agent."
    )
```

`gateway/tools/ledgerlens_tools/ledgerlens/application/ports/errors.py`:

```python
"""Errors that data-access adapters raise; part of the port contract.

Adapters wrap driver exceptions in these (``raise ... from exc``) so that use
cases can react to failures without importing any infrastructure code. Their
messages are for logs only and are never shown to the agent.
"""


class DataAccessError(Exception):
    """Base class for every failure raised through a data-access port."""


class DataSourceConnectionError(DataAccessError):
    """The database connection couldn't be opened or was lost."""


class QueryTimeoutError(DataAccessError):
    """The statement was cancelled by the database statement timeout."""


class QueryExecutionError(DataAccessError):
    """The database rejected or failed to run the query."""


class QueryNotFoundError(DataAccessError):
    """No SQL text exists for the requested query name."""
```

- [ ] **Step 7: Run the tests and lint**

Run: `python -m pytest tests/unit/ledgerlens_tools -v`
Expected: 9 passed.

Run: `python -m ruff format gateway/tools/ledgerlens_tools tests/unit/ledgerlens_tools && python -m ruff check --fix gateway/tools/ledgerlens_tools tests/unit/ledgerlens_tools`
Expected: `All checks passed!` (any import-order fixes are applied automatically).

- [ ] **Step 8: Commit**

```bash
git add \n  gateway/tools/ledgerlens_tools/ledgerlens/__init__.py \n  gateway/tools/ledgerlens_tools/ledgerlens/domain/__init__.py \n  gateway/tools/ledgerlens_tools/ledgerlens/domain/entities/__init__.py \n  gateway/tools/ledgerlens_tools/ledgerlens/domain/value_objects/__init__.py \n  gateway/tools/ledgerlens_tools/ledgerlens/application/__init__.py \n  gateway/tools/ledgerlens_tools/ledgerlens/application/ports/__init__.py \n  gateway/tools/ledgerlens_tools/ledgerlens/application/use_cases/__init__.py \n  gateway/tools/ledgerlens_tools/ledgerlens/infrastructure/__init__.py \n  gateway/tools/ledgerlens_tools/ledgerlens/infrastructure/repositories/__init__.py \n  gateway/tools/ledgerlens_tools/ledgerlens/infrastructure/queries/__init__.py \n  gateway/tools/ledgerlens_tools/ledgerlens/utils/__init__.py \n  gateway/tools/ledgerlens_tools/ledgerlens/utils/connectors/__init__.py \n  gateway/tools/ledgerlens_tools/ledgerlens/delivery/__init__.py \n  gateway/tools/ledgerlens_tools/ledgerlens/delivery/dependencies/__init__.py \n  gateway/tools/ledgerlens_tools/ledgerlens/delivery/presenters/__init__.py \n  gateway/tools/ledgerlens_tools/ledgerlens/domain/errors.py \n  gateway/tools/ledgerlens_tools/ledgerlens/application/ports/errors.py \n  gateway/tools/ledgerlens_tools/requirements.txt \n  requirements-dev.txt \n  tests/unit/ledgerlens_tools/conftest.py \n  tests/unit/ledgerlens_tools/test_errors.py
git commit -m "feat(tools): scaffold ledgerlens tools package and error hierarchy"
```

---

### Task 2: `TransactionFilters` value object

**Files:**
- Create: `gateway/tools/ledgerlens_tools/ledgerlens/domain/value_objects/transaction_filters.py`
- Test: `tests/unit/ledgerlens_tools/test_transaction_filters.py`

**Interfaces:**
- Consumes: `InvalidInputError(field, reason)` from Task 1.
- Produces:
  - `TransactionStatus(str, Enum)` with `APPROVED="Approved"`, `DECLINED="Declined"`, `PENDING="Pending"`.
  - Frozen dataclass `TransactionFilters(customer_id: str, date_from: date, date_to: date, card_last4: str | None = None, merchant: str | None = None, min_amount: Decimal | None = None, max_amount: Decimal | None = None, status: TransactionStatus | None = None)`.
  - `TransactionFilters.from_raw(raw: object, today: date) -> TransactionFilters`.
  - Constants `DEFAULT_WINDOW_DAYS = 30`, `MAX_WINDOW_DAYS = 180`, `MAX_MERCHANT_LENGTH = 100`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/ledgerlens_tools/test_transaction_filters.py`:

```python
"""Tests for TransactionFilters parsing, defaults and validation."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from ledgerlens.domain.errors import InvalidInputError
from ledgerlens.domain.value_objects.transaction_filters import (
    TransactionFilters,
    TransactionStatus,
)

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 29)


def parse(**raw: Any) -> TransactionFilters:
    """Parse raw tool input with a fixed 'today'."""
    return TransactionFilters.from_raw({"customer_id": "CUST-1", **raw}, today=TODAY)


def assert_invalid(field: str, **raw: Any) -> InvalidInputError:
    """Assert that parsing fails on the given field and return the error."""
    with pytest.raises(InvalidInputError) as caught:
        parse(**raw)
    assert caught.value.field == field
    return caught.value


def test_defaults_to_the_last_30_days_with_no_optional_filters() -> None:
    filters = parse()

    assert filters == TransactionFilters(
        customer_id="CUST-1", date_from=date(2026, 8, 30), date_to=TODAY
    )


def test_customer_id_is_trimmed() -> None:
    assert parse(customer_id="  CUST-9 ").customer_id == "CUST-9"


@pytest.mark.parametrize("value", [None, "", "   ", 123])
def test_customer_id_is_required_non_blank_string(value: object) -> None:
    assert_invalid("customer_id", customer_id=value)


def test_missing_customer_id_is_rejected() -> None:
    with pytest.raises(InvalidInputError) as caught:
        TransactionFilters.from_raw({}, today=TODAY)
    assert caught.value.field == "customer_id"


@pytest.mark.parametrize("raw", [None, [], "customer_id=CUST-1", 42])
def test_non_object_input_is_rejected(raw: object) -> None:
    with pytest.raises(InvalidInputError) as caught:
        TransactionFilters.from_raw(raw, today=TODAY)
    assert caught.value.field == "input"
    assert "must be a JSON object" in caught.value.message


def test_explicit_dates_are_parsed() -> None:
    filters = parse(date_from="2026-09-01", date_to="2026-09-15")

    assert (filters.date_from, filters.date_to) == (date(2026, 9, 1), date(2026, 9, 15))


def test_date_from_only_keeps_date_to_as_today() -> None:
    filters = parse(date_from="2026-09-01")

    assert (filters.date_from, filters.date_to) == (date(2026, 9, 1), TODAY)


def test_date_to_only_defaults_date_from_to_30_days_before_it() -> None:
    filters = parse(date_to="2026-06-30")

    assert filters.date_from == date(2026, 5, 31)


@pytest.mark.parametrize(
    "value", ["2026/09/01", "2026-9-1", "20260901", "01-09-2026", "yesterday", 20260901]
)
def test_dates_must_be_iso_yyyy_mm_dd(value: object) -> None:
    error = assert_invalid("date_from", date_from=value)
    assert "YYYY-MM-DD" in error.reason or "string" in error.reason


def test_impossible_calendar_dates_are_rejected() -> None:
    error = assert_invalid("date_to", date_to="2026-02-30")
    assert "real calendar date" in error.reason


def test_date_from_after_date_to_is_rejected() -> None:
    assert_invalid("date_from", date_from="2026-09-20", date_to="2026-09-10")


def test_date_range_of_exactly_180_days_is_allowed() -> None:
    filters = parse(date_from="2026-04-02", date_to="2026-09-29")

    assert (filters.date_to - filters.date_from).days == 180


def test_date_range_over_180_days_is_rejected() -> None:
    error = assert_invalid("date_from", date_from="2026-04-01", date_to="2026-09-29")
    assert "180 days" in error.reason


@pytest.mark.parametrize(
    "field", ["card_last4", "merchant", "status", "date_from", "date_to",
              "min_amount", "max_amount"]
)
@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_or_null_optional_fields_mean_no_filter(field: str, blank: object) -> None:
    filters = parse(**{field: blank})

    assert filters == parse()


def test_card_last4_accepts_four_digits_and_trims() -> None:
    assert parse(card_last4=" 0042 ").card_last4 == "0042"


@pytest.mark.parametrize("value", ["123", "12345", "12a4", "١٢٣٤", 1234])
def test_card_last4_must_be_exactly_four_ascii_digits(value: object) -> None:
    assert_invalid("card_last4", card_last4=value)


def test_merchant_is_trimmed() -> None:
    assert parse(merchant="  Café Aroma ").merchant == "Café Aroma"


def test_merchant_of_100_characters_is_allowed() -> None:
    assert parse(merchant="m" * 100).merchant == "m" * 100


def test_merchant_over_100_characters_is_rejected() -> None:
    assert_invalid("merchant", merchant="m" * 101)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (10, Decimal("10")),
        (10.5, Decimal("10.5")),
        (0.1, Decimal("0.1")),
        ("12.30", Decimal("12.30")),
        (" 7 ", Decimal("7")),
        (0, Decimal("0")),
    ],
)
def test_amounts_parse_to_exact_decimals(value: object, expected: Decimal) -> None:
    assert parse(min_amount=value).min_amount == expected
    assert parse(max_amount=value).max_amount == expected


@pytest.mark.parametrize(
    "value",
    [True, False, "abc", float("nan"), float("inf"), "NaN", "Infinity", "-Infinity",
     [1], {"value": 1}],
)
def test_amounts_reject_booleans_non_numbers_and_non_finite(value: object) -> None:
    assert_invalid("min_amount", min_amount=value)


def test_negative_amounts_are_rejected() -> None:
    assert_invalid("max_amount", max_amount=-1)


def test_min_amount_above_max_amount_is_rejected() -> None:
    assert_invalid("min_amount", min_amount=50, max_amount=10)


def test_equal_min_and_max_amount_is_allowed() -> None:
    filters = parse(min_amount="10.00", max_amount=10)

    assert filters.min_amount == filters.max_amount


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Approved", TransactionStatus.APPROVED),
        ("declined", TransactionStatus.DECLINED),
        (" PENDING ", TransactionStatus.PENDING),
    ],
)
def test_status_matches_case_insensitively(
    value: str, expected: TransactionStatus
) -> None:
    assert parse(status=value).status is expected


def test_unknown_status_lists_the_allowed_values() -> None:
    error = assert_invalid("status", status="Refunded")
    assert error.reason == "must be one of Approved, Declined, Pending"


def test_filters_are_immutable() -> None:
    filters = parse()

    with pytest.raises(AttributeError):
        filters.customer_id = "OTHER"  # type: ignore[misc]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/ledgerlens_tools/test_transaction_filters.py -v`
Expected: collection ERROR with `ModuleNotFoundError: No module named 'ledgerlens.domain.value_objects.transaction_filters'`.

- [ ] **Step 3: Implement `TransactionFilters`**

`gateway/tools/ledgerlens_tools/ledgerlens/domain/value_objects/transaction_filters.py`:

```python
"""Validated search criteria for listing a customer's card transactions."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Final

from ledgerlens.domain.errors import InvalidInputError

DEFAULT_WINDOW_DAYS: Final = 30
MAX_WINDOW_DAYS: Final = 180
MAX_MERCHANT_LENGTH: Final = 100

# Strict patterns: Python 3.11+ date.fromisoformat also accepts "20260901", so the
# format is checked first to behave the same on 3.10 (local) and 3.13 (Lambda).
_ISO_DATE: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_CARD_LAST4: Final = re.compile(r"[0-9]{4}")


class TransactionStatus(str, Enum):
    """Transaction statuses the agent can filter by.

    TODO(ledgerlens): R4 - these values are assumed, not confirmed against the data
      dictionary (product design Q1). Update this enum and tool_spec.json together.
    """

    APPROVED = "Approved"
    DECLINED = "Declined"
    PENDING = "Pending"


@dataclass(frozen=True)
class TransactionFilters:
    """Validated search criteria for a customer's card transactions.

    Attributes:
        customer_id: Customer whose transactions are searched.
        date_from: First processing date included (inclusive).
        date_to: Last processing date included (inclusive).
        card_last4: Last four digits of one card, or None for every card.
        merchant: Case-insensitive substring of the merchant name, or None.
        min_amount: Smallest amount included, or None.
        max_amount: Largest amount included, or None.
        status: Transaction status to match, or None for any status.
    """

    customer_id: str
    date_from: date
    date_to: date
    card_last4: str | None = None
    merchant: str | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    status: TransactionStatus | None = None

    @classmethod
    def from_raw(cls, raw: object, today: date) -> "TransactionFilters":
        """Parse untyped tool input, apply the defaults and validate it.

        Empty strings and nulls in optional fields mean "no filter".

        Args:
            raw: The tool arguments exactly as received from the Gateway.
            today: Current UTC date, passed in so tests are deterministic.

        Returns:
            The validated filters.

        Raises:
            InvalidInputError: If any argument breaks a validation rule.
        """
        if not isinstance(raw, Mapping):
            raise InvalidInputError("input", "must be a JSON object")

        customer_id = raw.get("customer_id")
        if not isinstance(customer_id, str) or not customer_id.strip():
            raise InvalidInputError(
                "customer_id", "is required and must be a non-empty string"
            )

        parsed_to = _parse_date(raw, "date_to")
        date_to = parsed_to if parsed_to is not None else today
        parsed_from = _parse_date(raw, "date_from")
        date_from = (
            parsed_from
            if parsed_from is not None
            else date_to - timedelta(days=DEFAULT_WINDOW_DAYS)
        )
        if date_from > date_to:
            raise InvalidInputError("date_from", "must be on or before date_to")
        if (date_to - date_from).days > MAX_WINDOW_DAYS:
            raise InvalidInputError(
                "date_from", f"the date range can't exceed {MAX_WINDOW_DAYS} days"
            )

        min_amount = _parse_amount(raw, "min_amount")
        max_amount = _parse_amount(raw, "max_amount")
        if min_amount is not None and max_amount is not None and min_amount > max_amount:
            raise InvalidInputError(
                "min_amount", "must be less than or equal to max_amount"
            )

        return cls(
            customer_id=customer_id.strip(),
            date_from=date_from,
            date_to=date_to,
            card_last4=_parse_card_last4(raw),
            merchant=_parse_merchant(raw),
            min_amount=min_amount,
            max_amount=max_amount,
            status=_parse_status(raw),
        )


def _optional_text(raw: Mapping[str, Any], field: str) -> str | None:
    """Return the trimmed string value of ``field``, or None if null or blank.

    Raises:
        InvalidInputError: If the value is present but not a string.
    """
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidInputError(field, "must be a string")
    return value.strip() or None


def _parse_date(raw: Mapping[str, Any], field: str) -> date | None:
    """Parse an optional YYYY-MM-DD date.

    Raises:
        InvalidInputError: If the value has another format or isn't a real date.
    """
    text = _optional_text(raw, field)
    if text is None:
        return None
    if not _ISO_DATE.fullmatch(text):
        raise InvalidInputError(field, "must be a date in YYYY-MM-DD format")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise InvalidInputError(field, "is not a real calendar date") from exc


def _parse_card_last4(raw: Mapping[str, Any]) -> str | None:
    """Parse the optional last four card digits.

    Raises:
        InvalidInputError: If the value isn't exactly four ASCII digits.
    """
    value = raw.get("card_last4")
    if value is not None and not isinstance(value, str):
        raise InvalidInputError("card_last4", "must be exactly 4 digits as a string")
    text = _optional_text(raw, "card_last4")
    if text is not None and not _CARD_LAST4.fullmatch(text):
        raise InvalidInputError("card_last4", "must be exactly 4 digits")
    return text


def _parse_merchant(raw: Mapping[str, Any]) -> str | None:
    """Parse the optional merchant search text.

    Raises:
        InvalidInputError: If the text is longer than MAX_MERCHANT_LENGTH.
    """
    text = _optional_text(raw, "merchant")
    if text is not None and len(text) > MAX_MERCHANT_LENGTH:
        raise InvalidInputError(
            "merchant", f"must be at most {MAX_MERCHANT_LENGTH} characters"
        )
    return text


def _parse_amount(raw: Mapping[str, Any], field: str) -> Decimal | None:
    """Parse an optional non-negative amount into an exact Decimal.

    Floats are converted through ``str`` so 10.5 becomes Decimal("10.5"), not its
    binary approximation.

    Raises:
        InvalidInputError: If the value is a boolean, not numeric, not finite or
            negative.
    """
    value = raw.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str | Decimal):
        raise InvalidInputError(field, "must be a number")
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise InvalidInputError(field, "must be a number") from exc
    if not amount.is_finite():
        raise InvalidInputError(field, "must be a finite number")
    if amount < 0:
        raise InvalidInputError(field, "must be zero or greater")
    return amount


def _parse_status(raw: Mapping[str, Any]) -> TransactionStatus | None:
    """Parse the optional status, matching the enum values case-insensitively.

    Raises:
        InvalidInputError: If the value isn't one of TransactionStatus.
    """
    text = _optional_text(raw, "status")
    if text is None:
        return None
    for status in TransactionStatus:
        if status.value.casefold() == text.casefold():
            return status
    allowed = ", ".join(status.value for status in TransactionStatus)
    raise InvalidInputError("status", f"must be one of {allowed}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/ledgerlens_tools/test_transaction_filters.py -v`
Expected: all pass. The test IDs include the parametrized cases.

- [ ] **Step 5: Lint**

Run: `python -m ruff format gateway/tools/ledgerlens_tools tests/unit/ledgerlens_tools && python -m ruff check --fix gateway/tools/ledgerlens_tools tests/unit/ledgerlens_tools`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add gateway/tools/ledgerlens_tools/ledgerlens/domain/value_objects/transaction_filters.py tests/unit/ledgerlens_tools/test_transaction_filters.py
git commit -m "feat(tools): add TransactionFilters value object with validation"
```

---

### Task 3: Entities, ports and `ListCardTransactionsUseCase`

**Files:**
- Create:
  - `gateway/tools/ledgerlens_tools/ledgerlens/domain/entities/card_transaction.py`
  - `gateway/tools/ledgerlens_tools/ledgerlens/application/ports/database_repository.py`
  - `gateway/tools/ledgerlens_tools/ledgerlens/application/ports/query_provider.py`
  - `gateway/tools/ledgerlens_tools/ledgerlens/application/use_cases/list_card_transactions.py`
  - `tests/unit/ledgerlens_tools/ledgerlens_fakes.py`
- Test: `tests/unit/ledgerlens_tools/test_list_card_transactions_use_case.py`

**Interfaces:**
- Consumes:
  - `TransactionFilters` and `TransactionStatus` (Task 2)
  - the domain errors and port errors (Task 1)
- Produces:
  - `CardTransaction` (frozen dataclass) with these fields:
    - `transaction_id: str`
    - `transaction_date: datetime`
    - `card_last4: str`
    - `amount: Decimal`
    - `currency: str | None`
    - `transaction_status: str | None`
    - `merchant_name: str | None`
    - `merchant_category: str | None`
    - `channel: str | None`
    - `transaction_city: str | None`
    - `transaction_country: str | None`
  - `CardTransactionsResult(transactions: tuple[CardTransaction, ...], truncated: bool)`.
  - ABC `DatabaseRepository.execute_query(query: str, params: Mapping[str, object]) -> list[dict[str, Any]]`.
  - ABC `QueryProvider.get(name: str) -> str`.
  - `ListCardTransactionsUseCase(repository: DatabaseRepository, queries: QueryProvider, max_rows: int = 25)` with:
    - `.execute(filters) -> CardTransactionsResult`
    - `QUERY_NAME = "list_card_transactions"`
    - the query params, which have exactly these keys: `customer_id, date_from, date_to, card_last4, merchant, min_amount, max_amount, status, limit`
  - Test fakes: `FakeRepository`, `FakeQueryProvider`, `make_row(**overrides)`, `make_filters(**overrides)`.

- [ ] **Step 1: Write the entities and ports**

These are interfaces with no behavior, so the use-case tests in Step 3 cover them.

`gateway/tools/ledgerlens_tools/ledgerlens/domain/entities/card_transaction.py`:

```python
"""Card transaction entities returned by the list_card_transactions use case."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class CardTransaction:
    """A single card transaction as returned to the agent.

    Nullable columns are ``| None`` because the source data has about 5% nulls.
    ``transaction_status`` is a plain string, not TransactionStatus, because the
    database may hold values outside the three filterable ones.
    """

    transaction_id: str
    transaction_date: datetime
    card_last4: str
    amount: Decimal
    currency: str | None
    transaction_status: str | None
    merchant_name: str | None
    merchant_category: str | None
    channel: str | None
    transaction_city: str | None
    transaction_country: str | None


@dataclass(frozen=True)
class CardTransactionsResult:
    """The outcome of a transaction search, capped at a maximum number of rows.

    Attributes:
        transactions: Matching transactions, newest first.
        truncated: True when more matches exist than were returned.
    """

    transactions: tuple[CardTransaction, ...]
    truncated: bool
```

`gateway/tools/ledgerlens_tools/ledgerlens/application/ports/database_repository.py`:

```python
"""Port for running parameterised queries against any database engine."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any


class DatabaseRepository(ABC):
    """Port for running parameterised queries against any database.

    Implementations are plain query executors: they know how to run SQL on one
    engine, not which SQL to run.
    """

    @abstractmethod
    def execute_query(
        self, query: str, params: Mapping[str, object]
    ) -> list[dict[str, Any]]:
        """Execute a parameterised query and return its rows.

        Args:
            query: SQL text with the engine's named placeholders.
            params: Values for the placeholders, keyed by name.

        Returns:
            Rows as dictionaries keyed by column name.

        Raises:
            DataSourceConnectionError: The connection couldn't be opened or was lost.
            QueryTimeoutError: The statement timeout cancelled the query.
            QueryExecutionError: The database failed to run the query.
        """
```

`gateway/tools/ledgerlens_tools/ledgerlens/application/ports/query_provider.py`:

```python
"""Port for loading SQL text by logical name."""

from abc import ABC, abstractmethod


class QueryProvider(ABC):
    """Port for loading SQL text by logical name for the configured dialect."""

    @abstractmethod
    def get(self, name: str) -> str:
        """Return the SQL text of the named query.

        Args:
            name: Logical query name, e.g. ``"list_card_transactions"``.

        Raises:
            QueryNotFoundError: No query with that name exists for the dialect.
        """
```

- [ ] **Step 2: Write the shared test fakes**

`tests/unit/ledgerlens_tools/ledgerlens_fakes.py`:

```python
"""Test doubles and builders shared by the LedgerLens tool tests."""

from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from ledgerlens.application.ports.database_repository import DatabaseRepository
from ledgerlens.application.ports.errors import QueryNotFoundError
from ledgerlens.application.ports.query_provider import QueryProvider
from ledgerlens.domain.value_objects.transaction_filters import TransactionFilters


class FakeRepository(DatabaseRepository):
    """DatabaseRepository double that records calls and returns canned rows."""

    def __init__(
        self,
        rows: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        """Return ``rows`` from every call, or raise ``error`` if given."""
        self.rows: list[dict[str, Any]] = rows if rows is not None else []
        self.error = error
        self.calls: list[tuple[str, dict[str, object]]] = []

    def execute_query(
        self, query: str, params: Mapping[str, object]
    ) -> list[dict[str, Any]]:
        """Record the call, then raise the configured error or return the rows."""
        self.calls.append((query, dict(params)))
        if self.error is not None:
            raise self.error
        return [dict(row) for row in self.rows]


class FakeQueryProvider(QueryProvider):
    """QueryProvider double backed by an in-memory mapping."""

    def __init__(self, queries: Mapping[str, str] | None = None) -> None:
        """Serve ``queries``; by default only list_card_transactions exists."""
        self.queries: dict[str, str] = dict(
            queries
            if queries is not None
            else {"list_card_transactions": "SELECT 'list_card_transactions'"}
        )
        self.requested: list[str] = []

    def get(self, name: str) -> str:
        """Record the name and return its SQL, or raise QueryNotFoundError."""
        self.requested.append(name)
        if name not in self.queries:
            raise QueryNotFoundError(f"no query named {name!r}")
        return self.queries[name]


def make_row(**overrides: Any) -> dict[str, Any]:
    """Build a database row as psycopg's dict_row returns it."""
    row: dict[str, Any] = {
        "transaction_id": "TX-1",
        "transaction_date": datetime(2026, 9, 20, 14, 30, tzinfo=timezone.utc),
        "card_last4": "4242",
        "merchant_name": "Café Aroma",
        "merchant_category": "Restaurants",
        "amount": Decimal("12.50"),
        "currency": "COP",
        "channel": "POS",
        "transaction_city": "Medellín",
        "transaction_country": "CO",
        "transaction_status": "Approved",
    }
    row.update(overrides)
    return row


def make_filters(**overrides: Any) -> TransactionFilters:
    """Build valid TransactionFilters, overriding any field."""
    values: dict[str, Any] = {
        "customer_id": "CUST-1",
        "date_from": date(2026, 8, 30),
        "date_to": date(2026, 9, 29),
    }
    values.update(overrides)
    return TransactionFilters(**values)
```

- [ ] **Step 3: Write the failing use-case tests**

`tests/unit/ledgerlens_tools/test_list_card_transactions_use_case.py`:

```python
"""Tests for ListCardTransactionsUseCase: params, mapping, truncation, errors."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from ledgerlens_fakes import FakeQueryProvider, FakeRepository, make_filters, make_row

from ledgerlens.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    QueryExecutionError,
    QueryTimeoutError,
)
from ledgerlens.application.use_cases.list_card_transactions import (
    ListCardTransactionsUseCase,
)
from ledgerlens.domain.entities.card_transaction import (
    CardTransaction,
    CardTransactionsResult,
)
from ledgerlens.domain.errors import (
    DataIntegrityError,
    DataSourceUnavailableError,
    DomainError,
    SearchTooBroadError,
    TransactionLookupError,
)
from ledgerlens.domain.value_objects.transaction_filters import TransactionStatus

pytestmark = pytest.mark.unit


def run(
    rows: list[dict[str, Any]] | None = None,
    error: Exception | None = None,
    max_rows: int = 25,
) -> tuple[CardTransactionsResult, FakeRepository, FakeQueryProvider]:
    """Execute the use case against fakes and return the result and the fakes."""
    repository = FakeRepository(rows=rows, error=error)
    queries = FakeQueryProvider()
    use_case = ListCardTransactionsUseCase(repository, queries, max_rows=max_rows)
    return use_case.execute(make_filters()), repository, queries


def test_maps_a_row_to_a_card_transaction() -> None:
    result, _, _ = run(rows=[make_row()])

    assert result == CardTransactionsResult(
        transactions=(
            CardTransaction(
                transaction_id="TX-1",
                transaction_date=datetime(2026, 9, 20, 14, 30, tzinfo=timezone.utc),
                card_last4="4242",
                amount=Decimal("12.50"),
                currency="COP",
                transaction_status="Approved",
                merchant_name="Café Aroma",
                merchant_category="Restaurants",
                channel="POS",
                transaction_city="Medellín",
                transaction_country="CO",
            ),
        ),
        truncated=False,
    )


def test_loads_the_named_query_and_passes_its_text_to_the_repository() -> None:
    _, repository, queries = run()

    assert queries.requested == ["list_card_transactions"]
    assert repository.calls[0][0] == "SELECT 'list_card_transactions'"


def test_sends_every_filter_and_limit_as_params() -> None:
    repository = FakeRepository()
    use_case = ListCardTransactionsUseCase(repository, FakeQueryProvider())
    filters = make_filters(
        card_last4="4242",
        merchant="aroma",
        min_amount=Decimal("1.00"),
        max_amount=Decimal("99.99"),
        status=TransactionStatus.DECLINED,
    )

    use_case.execute(filters)

    assert repository.calls[0][1] == {
        "customer_id": "CUST-1",
        "date_from": date(2026, 8, 30),
        "date_to": date(2026, 9, 29),
        "card_last4": "4242",
        "merchant": "aroma",
        "min_amount": Decimal("1.00"),
        "max_amount": Decimal("99.99"),
        "status": "Declined",
        "limit": 26,
    }


def test_absent_filters_are_sent_as_none() -> None:
    _, repository, _ = run()

    params = repository.calls[0][1]
    for key in ("card_last4", "merchant", "min_amount", "max_amount", "status"):
        assert params[key] is None


def test_limit_is_max_rows_plus_one() -> None:
    _, repository, _ = run(max_rows=3)

    assert repository.calls[0][1]["limit"] == 4


def test_returns_max_rows_and_flags_truncation_when_more_exist() -> None:
    rows = [make_row(transaction_id=f"TX-{i}") for i in range(26)]

    result, _, _ = run(rows=rows)

    assert len(result.transactions) == 25
    assert result.transactions[-1].transaction_id == "TX-24"
    assert result.truncated is True


def test_exactly_max_rows_is_not_truncated() -> None:
    rows = [make_row(transaction_id=f"TX-{i}") for i in range(25)]

    result, _, _ = run(rows=rows)

    assert len(result.transactions) == 25
    assert result.truncated is False


def test_empty_result_is_not_an_error() -> None:
    result, _, _ = run(rows=[])

    assert result == CardTransactionsResult(transactions=(), truncated=False)


def test_null_optional_columns_are_kept_as_none() -> None:
    nullable = (
        "currency",
        "transaction_status",
        "merchant_name",
        "merchant_category",
        "channel",
        "transaction_city",
        "transaction_country",
    )
    row = make_row(**dict.fromkeys(nullable))

    result, _, _ = run(rows=[row])

    transaction = result.transactions[0]
    for column in nullable:
        assert getattr(transaction, column) is None


def test_numeric_ids_and_float_amounts_are_normalised() -> None:
    result, _, _ = run(rows=[make_row(transaction_id=123, amount=12.5)])

    assert result.transactions[0].transaction_id == "123"
    assert result.transactions[0].amount == Decimal("12.5")


@pytest.mark.parametrize(
    ("port_error", "domain_error"),
    [
        (DataSourceConnectionError("conn refused host=db.internal"),
         DataSourceUnavailableError),
        (QueryTimeoutError("canceling statement due to statement timeout"),
         SearchTooBroadError),
        (QueryExecutionError('relation "transactions" does not exist'),
         TransactionLookupError),
        (DataAccessError("unclassified adapter failure"), TransactionLookupError),
    ],
)
def test_port_errors_become_domain_errors_without_leaking_details(
    port_error: Exception, domain_error: type[DomainError]
) -> None:
    with pytest.raises(domain_error) as caught:
        run(error=port_error)

    assert caught.value.__cause__ is port_error
    assert str(port_error) not in caught.value.message


def test_missing_query_becomes_transaction_lookup_error() -> None:
    use_case = ListCardTransactionsUseCase(
        FakeRepository(), FakeQueryProvider(queries={})
    )

    with pytest.raises(TransactionLookupError):
        use_case.execute(make_filters())


@pytest.mark.parametrize(
    "bad_row",
    [
        {k: v for k, v in make_row().items() if k != "amount"},
        make_row(transaction_id=None),
        make_row(card_last4=None),
        make_row(transaction_date="2026-09-20T14:30:00"),
        make_row(transaction_date=None),
        make_row(amount=None),
        make_row(amount="12.50"),
        make_row(amount=True),
        make_row(amount=Decimal("NaN")),
    ],
)
def test_unmappable_rows_raise_data_integrity_error(bad_row: dict[str, Any]) -> None:
    with pytest.raises(DataIntegrityError):
        run(rows=[bad_row])


def test_max_rows_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_rows"):
        ListCardTransactionsUseCase(FakeRepository(), FakeQueryProvider(), max_rows=0)
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/ledgerlens_tools/test_list_card_transactions_use_case.py -v`
Expected: collection ERROR with `ModuleNotFoundError: No module named 'ledgerlens.application.use_cases.list_card_transactions'`.

- [ ] **Step 5: Implement the use case**

`gateway/tools/ledgerlens_tools/ledgerlens/application/use_cases/list_card_transactions.py`:

```python
"""Use case: search a customer's card transactions."""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from ledgerlens.application.ports.database_repository import DatabaseRepository
from ledgerlens.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    QueryTimeoutError,
)
from ledgerlens.application.ports.query_provider import QueryProvider
from ledgerlens.domain.entities.card_transaction import (
    CardTransaction,
    CardTransactionsResult,
)
from ledgerlens.domain.errors import (
    DataIntegrityError,
    DataSourceUnavailableError,
    SearchTooBroadError,
    TransactionLookupError,
)
from ledgerlens.domain.value_objects.transaction_filters import TransactionFilters


class ListCardTransactionsUseCase:
    """Search a customer's card transactions through a database-agnostic repository.

    The use case loads the SQL by name, runs it through the repository port and
    maps rows to domain entities. Port errors are translated into domain errors
    whose messages tell the agent what to do next.
    """

    QUERY_NAME: Final = "list_card_transactions"

    def __init__(
        self,
        repository: DatabaseRepository,
        queries: QueryProvider,
        max_rows: int = 25,
    ) -> None:
        """Store the ports and the row cap.

        Args:
            repository: Executes the query; any DatabaseRepository adapter.
            queries: Supplies the SQL text for the configured dialect.
            max_rows: Maximum transactions returned per call.

        Raises:
            ValueError: If max_rows is less than 1.
        """
        if max_rows < 1:
            raise ValueError("max_rows must be at least 1")
        self._repository: DatabaseRepository = repository
        self._queries: QueryProvider = queries
        self._max_rows: int = max_rows

    def execute(self, filters: TransactionFilters) -> CardTransactionsResult:
        """Load the query, run it with the filters and return at most max_rows rows.

        One extra row is requested so the result can say whether more exist.

        Raises:
            DataSourceUnavailableError: The database can't be reached.
            SearchTooBroadError: The query hit the statement timeout.
            TransactionLookupError: The query is missing or failed to run.
            DataIntegrityError: A returned row couldn't be mapped.
        """
        try:
            query = self._queries.get(self.QUERY_NAME)
            rows = self._repository.execute_query(query, self._params(filters))
        except DataSourceConnectionError as exc:
            raise DataSourceUnavailableError() from exc
        except QueryTimeoutError as exc:
            raise SearchTooBroadError() from exc
        except DataAccessError as exc:
            raise TransactionLookupError() from exc

        try:
            transactions = tuple(
                _to_transaction(row) for row in rows[: self._max_rows]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise DataIntegrityError() from exc

        return CardTransactionsResult(
            transactions=transactions, truncated=len(rows) > self._max_rows
        )

    def _params(self, filters: TransactionFilters) -> dict[str, object]:
        """Build the query parameters; every key must match a SQL placeholder."""
        return {
            "customer_id": filters.customer_id,
            "date_from": filters.date_from,
            "date_to": filters.date_to,
            "card_last4": filters.card_last4,
            "merchant": filters.merchant,
            "min_amount": filters.min_amount,
            "max_amount": filters.max_amount,
            "status": filters.status.value if filters.status is not None else None,
            "limit": self._max_rows + 1,
        }


def _to_transaction(row: Mapping[str, Any]) -> CardTransaction:
    """Map one database row to a CardTransaction.

    Raises:
        KeyError: A column is missing.
        TypeError: A required column has the wrong type.
        ValueError: A required column is null or the amount isn't finite.
    """
    return CardTransaction(
        transaction_id=_required_text(row, "transaction_id"),
        transaction_date=_required_datetime(row, "transaction_date"),
        card_last4=_required_text(row, "card_last4"),
        amount=_required_amount(row, "amount"),
        currency=_optional_text(row, "currency"),
        transaction_status=_optional_text(row, "transaction_status"),
        merchant_name=_optional_text(row, "merchant_name"),
        merchant_category=_optional_text(row, "merchant_category"),
        channel=_optional_text(row, "channel"),
        transaction_city=_optional_text(row, "transaction_city"),
        transaction_country=_optional_text(row, "transaction_country"),
    )


def _required_text(row: Mapping[str, Any], column: str) -> str:
    """Return a non-null column as text (numeric ids become strings)."""
    value = row[column]
    if value is None:
        raise ValueError(f"{column} is null")
    return str(value)


def _optional_text(row: Mapping[str, Any], column: str) -> str | None:
    """Return a nullable column as text, keeping None."""
    value = row[column]
    return None if value is None else str(value)


def _required_datetime(row: Mapping[str, Any], column: str) -> datetime:
    """Return a non-null timestamp column."""
    value = row[column]
    if value is None:
        raise ValueError(f"{column} is null")
    if not isinstance(value, datetime):
        raise TypeError(f"{column} is {type(value).__name__}, expected datetime")
    return value


def _required_amount(row: Mapping[str, Any], column: str) -> Decimal:
    """Return a non-null, finite numeric column as an exact Decimal."""
    value = row[column]
    if value is None:
        raise ValueError(f"{column} is null")
    if isinstance(value, bool) or not isinstance(value, Decimal | int | float):
        raise TypeError(f"{column} is {type(value).__name__}, expected a number")
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    if not amount.is_finite():
        raise ValueError(f"{column} is not finite")
    return amount
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/ledgerlens_tools -v`
Expected: all pass.

- [ ] **Step 7: Check the layer rule and lint**

Run: `grep -rnE "psycopg|boto3|ledgerlens\.(infrastructure|utils|delivery)" gateway/tools/ledgerlens_tools/ledgerlens/domain gateway/tools/ledgerlens_tools/ledgerlens/application`
Expected: no output.

Run: `python -m ruff format gateway/tools/ledgerlens_tools tests/unit/ledgerlens_tools && python -m ruff check --fix gateway/tools/ledgerlens_tools tests/unit/ledgerlens_tools`
Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add gateway/tools/ledgerlens_tools/ledgerlens/domain/entities/card_transaction.py gateway/tools/ledgerlens_tools/ledgerlens/application/ports/database_repository.py gateway/tools/ledgerlens_tools/ledgerlens/application/ports/query_provider.py gateway/tools/ledgerlens_tools/ledgerlens/application/use_cases/list_card_transactions.py tests/unit/ledgerlens_tools/ledgerlens_fakes.py tests/unit/ledgerlens_tools/test_list_card_transactions_use_case.py
git commit -m "feat(tools): add list card transactions use case, entities and ports"
```

---

### Task 4: `FileQueryProvider`, the SQL and `tool_spec.json`

**Files:**
- Create:
  - `gateway/tools/ledgerlens_tools/ledgerlens/infrastructure/queries/file_query_provider.py`
  - `gateway/tools/ledgerlens_tools/ledgerlens/queries/postgresql/list_card_transactions.sql`
  - `gateway/tools/list_card_transactions/tool_spec.json`
- Test:
  - `tests/unit/ledgerlens_tools/test_file_query_provider.py`
  - `tests/unit/ledgerlens_tools/test_query_contracts.py`

**Interfaces:**
- Consumes:
  - `QueryProvider` and `QueryNotFoundError` (Tasks 1 and 3)
  - `ListCardTransactionsUseCase` with its param keys (Task 3)
  - `TransactionFilters` and `TransactionStatus` (Task 2)
  - the fakes (Task 3)
- Produces: `FileQueryProvider(directory: Path)` implementing `get(name) -> str`. It caches each file after the first read. Names must match `[a-z0-9_]+`. A missing, unreadable or empty file raises `QueryNotFoundError`.

- [ ] **Step 1: Write the failing provider tests**

`tests/unit/ledgerlens_tools/test_file_query_provider.py`:

```python
"""Tests for FileQueryProvider: reading, caching and missing queries."""

from pathlib import Path

import pytest

from ledgerlens.application.ports.errors import QueryNotFoundError
from ledgerlens.infrastructure.queries.file_query_provider import FileQueryProvider

pytestmark = pytest.mark.unit


def test_reads_the_named_sql_file(tmp_path: Path) -> None:
    (tmp_path / "list_card_transactions.sql").write_text("SELECT 1", encoding="utf-8")

    assert FileQueryProvider(tmp_path).get("list_card_transactions") == "SELECT 1"


def test_caches_the_query_after_the_first_read(tmp_path: Path) -> None:
    path = tmp_path / "q.sql"
    path.write_text("SELECT 1", encoding="utf-8")
    provider = FileQueryProvider(tmp_path)

    provider.get("q")
    path.write_text("SELECT 2", encoding="utf-8")

    assert provider.get("q") == "SELECT 1"


def test_missing_file_raises_query_not_found(tmp_path: Path) -> None:
    with pytest.raises(QueryNotFoundError):
        FileQueryProvider(tmp_path).get("missing")


def test_empty_file_raises_query_not_found(tmp_path: Path) -> None:
    (tmp_path / "blank.sql").write_text("  \n", encoding="utf-8")

    with pytest.raises(QueryNotFoundError):
        FileQueryProvider(tmp_path).get("blank")


@pytest.mark.parametrize("name", ["../secrets", "a/b", "Q", "", "q.sql", "q;drop"])
def test_rejects_names_that_are_not_simple_identifiers(
    tmp_path: Path, name: str
) -> None:
    with pytest.raises(QueryNotFoundError):
        FileQueryProvider(tmp_path).get(name)
```

- [ ] **Step 2: Write the failing contract (drift) tests**

These tests pin the real SQL file and `tool_spec.json` to the code, so a renamed parameter or enum value fails here and not in production.

`tests/unit/ledgerlens_tools/test_query_contracts.py`:

```python
"""Drift tests: the SQL file and tool_spec.json must match the Python contracts."""

import dataclasses
import json
import re
from pathlib import Path
from typing import Any

import pytest
from ledgerlens_fakes import FakeQueryProvider, FakeRepository, make_filters

from ledgerlens.application.use_cases.list_card_transactions import (
    ListCardTransactionsUseCase,
)
from ledgerlens.domain.value_objects.transaction_filters import (
    TransactionFilters,
    TransactionStatus,
)
from ledgerlens.infrastructure.queries.file_query_provider import FileQueryProvider

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
QUERIES_DIR = (
    REPO_ROOT / "gateway/tools/ledgerlens_tools/ledgerlens/queries/postgresql"
)
TOOL_SPEC = REPO_ROOT / "gateway/tools/list_card_transactions/tool_spec.json"
PLACEHOLDER = re.compile(r"%\((\w+)\)s")


def sql() -> str:
    """Load the real list_card_transactions query."""
    return FileQueryProvider(QUERIES_DIR).get("list_card_transactions")


def sent_params() -> dict[str, object]:
    """Return the params the use case actually sends to the repository."""
    repository = FakeRepository()
    ListCardTransactionsUseCase(repository, FakeQueryProvider()).execute(
        make_filters()
    )
    return repository.calls[0][1]


def tool_spec() -> dict[str, Any]:
    """Load the single tool definition from tool_spec.json."""
    specs = json.loads(TOOL_SPEC.read_text(encoding="utf-8"))
    assert isinstance(specs, list) and len(specs) == 1
    return specs[0]


def test_sql_placeholders_match_the_use_case_params_exactly() -> None:
    assert set(PLACEHOLDER.findall(sql())) == set(sent_params())


def test_sql_has_no_stray_percent_signs() -> None:
    # psycopg treats every '%' as a placeholder marker once params are passed.
    assert "%" not in PLACEHOLDER.sub("", sql())


def test_sql_selects_every_column_the_use_case_maps() -> None:
    text = sql()
    for column in (
        "transaction_id", "transaction_date", "card_last4", "amount", "currency",
        "transaction_status", "merchant_name", "merchant_category", "channel",
        "transaction_city", "transaction_country",
    ):
        assert column in text


def test_tool_spec_name_and_required_fields() -> None:
    spec = tool_spec()

    assert spec["name"] == "list_card_transactions"
    assert spec["inputSchema"]["required"] == ["customer_id"]


def test_tool_spec_properties_match_the_filter_fields() -> None:
    properties = set(tool_spec()["inputSchema"]["properties"])

    assert properties == {f.name for f in dataclasses.fields(TransactionFilters)}


def test_tool_spec_status_enum_matches_the_domain_enum() -> None:
    status = tool_spec()["inputSchema"]["properties"]["status"]

    assert status["enum"] == [s.value for s in TransactionStatus]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/ledgerlens_tools/test_file_query_provider.py tests/unit/ledgerlens_tools/test_query_contracts.py -v`
Expected: collection ERROR with `ModuleNotFoundError: No module named 'ledgerlens.infrastructure.queries.file_query_provider'`.

- [ ] **Step 4: Implement `FileQueryProvider`**

`gateway/tools/ledgerlens_tools/ledgerlens/infrastructure/queries/file_query_provider.py`:

```python
"""QueryProvider adapter that reads ``<name>.sql`` files from a dialect folder."""

import re
from pathlib import Path
from typing import Final

from ledgerlens.application.ports.errors import QueryNotFoundError
from ledgerlens.application.ports.query_provider import QueryProvider

# Only simple identifiers: blocks path traversal such as "../secrets".
_QUERY_NAME: Final = re.compile(r"[a-z0-9_]+")


class FileQueryProvider(QueryProvider):
    """Load SQL text from ``<directory>/<name>.sql`` and cache it per instance.

    Files ship inside the Lambda asset and never change at runtime, so each file
    is read at most once per container.
    """

    def __init__(self, directory: Path) -> None:
        """Serve queries from ``directory`` (one folder per SQL dialect)."""
        self._directory: Path = directory
        self._cache: dict[str, str] = {}

    def get(self, name: str) -> str:
        """Return the SQL text of the named query.

        Raises:
            QueryNotFoundError: The name is invalid, or the file is missing,
                unreadable or empty.
        """
        cached = self._cache.get(name)
        if cached is not None:
            return cached
        if not _QUERY_NAME.fullmatch(name):
            raise QueryNotFoundError(f"Invalid query name: {name!r}")
        path = self._directory / f"{name}.sql"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise QueryNotFoundError(f"Query {name!r} not found at {path}") from exc
        if not text.strip():
            raise QueryNotFoundError(f"Query {name!r} at {path} is empty")
        self._cache[name] = text
        return text
```

- [ ] **Step 5: Write the SQL**

`gateway/tools/ledgerlens_tools/ledgerlens/queries/postgresql/list_card_transactions.sql`. **Don't** put a percent sign anywhere in this file except the placeholders (the drift test enforces this).

```sql
-- list_card_transactions (PostgreSQL)
--
-- A customer's card transactions, newest first, one row per transaction_id.
-- Used by ListCardTransactionsUseCase.
--
-- Parameters (psycopg named placeholders):
--   customer_id  text     required
--   date_from    date     required (the use case applies the 30-day default)
--   date_to      date     required
--   card_last4   text     optional, NULL means every card
--   merchant     text     optional, case-insensitive substring of merchant_name
--   min_amount   numeric  optional
--   max_amount   numeric  optional
--   status       text     optional
--   limit        integer  max rows plus one (the extra row sets truncated=true)
--
-- Optional parameters are cast so PostgreSQL knows their type even when NULL.
-- The merchant filter uses strpos() instead of ILIKE so wildcard characters in
-- the customer's text match literally.
--
-- TODO(ledgerlens): R3 - not yet run against a real PostgreSQL database. Column
--   names follow docs/LATAM_Bank_ERD.md; add integration tests with a container.
-- TODO(ledgerlens): R4 - transaction_status values (Approved, Declined, Pending)
--   are assumed; confirm them with the data dictionary.
-- TODO(ledgerlens): R8 - about 2 in 100 rows are duplicated; DISTINCT ON removes
--   them at query time. Drop it once the data load deduplicates.
SELECT deduplicated.*
FROM (
    SELECT DISTINCT ON (t.transaction_id)
           t.transaction_id,
           t.transaction_date,
           RIGHT(p.product_number, 4) AS card_last4,
           t.merchant_name,
           t.merchant_category,
           t.amount,
           t.currency,
           t.channel,
           t.transaction_city,
           t.transaction_country,
           t.transaction_status
    FROM transactions AS t
    JOIN products AS p ON p.product_id = t.product_id
    WHERE t.customer_id = %(customer_id)s
      AND t.process_date BETWEEN %(date_from)s::date AND %(date_to)s::date
      AND (%(card_last4)s::text IS NULL
           OR RIGHT(p.product_number, 4) = %(card_last4)s::text)
      AND (%(merchant)s::text IS NULL
           OR strpos(lower(t.merchant_name), lower(%(merchant)s::text)) > 0)
      AND (%(min_amount)s::numeric IS NULL OR t.amount >= %(min_amount)s::numeric)
      AND (%(max_amount)s::numeric IS NULL OR t.amount <= %(max_amount)s::numeric)
      AND (%(status)s::text IS NULL OR t.transaction_status = %(status)s::text)
    ORDER BY t.transaction_id, t.transaction_date DESC
) AS deduplicated
ORDER BY deduplicated.transaction_date DESC, deduplicated.transaction_id
LIMIT %(limit)s
```

- [ ] **Step 6: Write `tool_spec.json`**

`gateway/tools/list_card_transactions/tool_spec.json` uses the same array format as `gateway/tools/sample_tool/tool_spec.json`:

```json
[
  {
    "name": "list_card_transactions",
    "description": "Searches the customer's card transactions. Use to find the transaction the customer is asking about, or to list recent activity on a card. Returns at most 25 rows, newest first, as JSON with 'transactions', 'count' and 'truncated'. Amounts are strings with 2 decimals in the transaction's currency. If 'truncated' is true, more matches exist: narrow the dates or add a card, merchant, amount or status filter.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "customer_id": {
          "type": "string",
          "description": "The authenticated customer's id from get_session_context."
        },
        "card_last4": {
          "type": "string",
          "description": "Optional. Last 4 digits of the card."
        },
        "date_from": {
          "type": "string",
          "format": "date",
          "description": "Optional. First date, YYYY-MM-DD. Defaults to 30 days before date_to. The range can't exceed 180 days."
        },
        "date_to": {
          "type": "string",
          "format": "date",
          "description": "Optional. Last date, YYYY-MM-DD. Defaults to today (UTC)."
        },
        "merchant": {
          "type": "string",
          "description": "Optional. Case-insensitive partial match on the merchant name, up to 100 characters."
        },
        "min_amount": {
          "type": "number",
          "description": "Optional. Smallest amount to include, zero or greater."
        },
        "max_amount": {
          "type": "number",
          "description": "Optional. Largest amount to include, zero or greater."
        },
        "status": {
          "type": "string",
          "enum": ["Approved", "Declined", "Pending"],
          "description": "Optional. Only transactions with this status."
        }
      },
      "required": ["customer_id"]
    }
  }
]
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/ledgerlens_tools -v`
Expected: all pass.

- [ ] **Step 8: Lint**

Run: `python -m ruff format gateway/tools/ledgerlens_tools tests/unit/ledgerlens_tools && python -m ruff check --fix gateway/tools/ledgerlens_tools tests/unit/ledgerlens_tools`
Expected: `All checks passed!`

- [ ] **Step 9: Commit**

```bash
git add gateway/tools/ledgerlens_tools/ledgerlens/infrastructure/queries/file_query_provider.py gateway/tools/ledgerlens_tools/ledgerlens/queries/postgresql/list_card_transactions.sql gateway/tools/list_card_transactions/tool_spec.json tests/unit/ledgerlens_tools/test_file_query_provider.py tests/unit/ledgerlens_tools/test_query_contracts.py
git commit -m "feat(tools): add file query provider, list_card_transactions SQL and tool spec"
```

---

### Task 5: Aurora PostgreSQL connector and `PostgreSQLRepository`

**Files:**
- Create:
  - `gateway/tools/ledgerlens_tools/ledgerlens/utils/connectors/base.py`
  - `gateway/tools/ledgerlens_tools/ledgerlens/utils/connectors/aurora_postgresql.py`
  - `gateway/tools/ledgerlens_tools/ledgerlens/infrastructure/repositories/postgresql_repository.py`
- Modify: `tests/unit/ledgerlens_tools/ledgerlens_fakes.py` (append the psycopg doubles)
- Test:
  - `tests/unit/ledgerlens_tools/test_aurora_postgresql_connector.py`
  - `tests/unit/ledgerlens_tools/test_postgresql_repository.py`

**Interfaces:**
- Consumes: `DatabaseRepository` (Task 3) and the port errors (Task 1).
- Produces:
  - Protocol `PsycopgConnector` with `connection() -> psycopg.Connection[Any]` and `reset() -> None`.
  - Protocol `SecretsClient` with `get_secret_value(*, SecretId: str) -> Mapping[str, Any]`.
  - `AuroraPostgreSQLConnector(secret_arn: str, statement_timeout_ms: int, secrets_client: SecretsClient | None = None, connect: Callable[..., psycopg.Connection[Any]] = psycopg.connect)`.
  - `PostgreSQLRepository(connector: PsycopgConnector)`, which implements `execute_query`.
  - Test doubles `FakeCursor`, `FakeConnection` and `FakeConnector(*outcomes)`:
    - each `connection()` call takes the next outcome; the last outcome repeats
    - an outcome is either a list of rows or an exception
    - a psycopg error is raised by `cursor.execute`
    - a `DataSourceConnectionError` is raised by `connection()` itself

- [ ] **Step 1: Append the psycopg doubles to the fakes**

In `tests/unit/ledgerlens_tools/ledgerlens_fakes.py`, replace the `QueryNotFoundError` import line with:

```python
from ledgerlens.application.ports.errors import (
    DataSourceConnectionError,
    QueryNotFoundError,
)
```

Append to the end of the file:

```python
Outcome = list[dict[str, Any]] | Exception


class FakeCursor:
    """psycopg cursor double: records execute() and returns or raises its outcome."""

    def __init__(self, outcome: Outcome) -> None:
        """Serve ``outcome`` from execute()/fetchall()."""
        self._outcome = outcome
        self.executed: list[tuple[str, Mapping[str, object]]] = []

    def __enter__(self) -> "FakeCursor":
        """Support ``with connection.cursor() as cursor``."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Nothing to clean up."""

    def execute(self, query: str, params: Mapping[str, object]) -> None:
        """Record the call; raise the outcome if it is an exception."""
        self.executed.append((query, params))
        if isinstance(self._outcome, Exception):
            raise self._outcome

    def fetchall(self) -> list[dict[str, Any]]:
        """Return the canned rows."""
        assert not isinstance(self._outcome, Exception)
        return self._outcome


class FakeConnection:
    """psycopg connection double exposing cursor(), close() and closed."""

    def __init__(self, outcome: Outcome | None = None) -> None:
        """Every cursor from this connection serves ``outcome``."""
        self._outcome: Outcome = outcome if outcome is not None else []
        self.cursors: list[FakeCursor] = []
        self.closed = False

    def cursor(self) -> FakeCursor:
        """Open a new cursor double."""
        cursor = FakeCursor(self._outcome)
        self.cursors.append(cursor)
        return cursor

    def close(self) -> None:
        """Mark the connection closed."""
        self.closed = True


class FakeConnector:
    """PsycopgConnector double; each connection() serves the next outcome.

    The last outcome repeats. A DataSourceConnectionError outcome is raised by
    connection() itself; any other exception is raised by cursor.execute().
    """

    def __init__(self, *outcomes: Outcome) -> None:
        """Queue the outcomes; with none, every query returns no rows."""
        self._outcomes: list[Outcome] = list(outcomes) or [[]]
        self.connections: list[FakeConnection] = []
        self.reset_calls = 0

    def connection(self) -> Any:
        """Return a connection double for the next outcome."""
        outcome = (
            self._outcomes.pop(0) if len(self._outcomes) > 1 else self._outcomes[0]
        )
        if isinstance(outcome, DataSourceConnectionError):
            raise outcome
        connection = FakeConnection(outcome)
        self.connections.append(connection)
        return connection

    def reset(self) -> None:
        """Count resets."""
        self.reset_calls += 1
```

- [ ] **Step 2: Write the failing connector tests**

`tests/unit/ledgerlens_tools/test_aurora_postgresql_connector.py`:

```python
"""Tests for AuroraPostgreSQLConnector: connect args, caching, reset, failures."""

import json
from collections.abc import Mapping
from typing import Any

import psycopg
import pytest
from ledgerlens_fakes import FakeConnection
from psycopg.rows import dict_row

from ledgerlens.application.ports.errors import DataSourceConnectionError
from ledgerlens.utils.connectors.aurora_postgresql import AuroraPostgreSQLConnector

pytestmark = pytest.mark.unit

SECRET_ARN = "arn:aws:secretsmanager:us-east-1:111111111111:secret:ledgerlens-db"
SECRET = {
    "host": "db.cluster.local",
    "port": "5432",
    "dbname": "ledgerlens",
    "username": "ledgerlens_readonly",
    "password": "not-a-real-password",  # noqa: S105
}


class FakeSecretsClient:
    """Secrets Manager double returning a JSON SecretString."""

    def __init__(
        self, secret: Mapping[str, Any] | None = None, error: Exception | None = None
    ) -> None:
        """Return ``secret`` or raise ``error``."""
        self.secret = secret if secret is not None else SECRET
        self.error = error
        self.requested: list[str] = []

    def get_secret_value(self, *, SecretId: str) -> dict[str, Any]:  # noqa: N803
        """Record the ARN and return the secret payload."""
        self.requested.append(SecretId)
        if self.error is not None:
            raise self.error
        return {"SecretString": json.dumps(self.secret)}


class RecordingConnect:
    """psycopg.connect double that records kwargs."""

    def __init__(self, error: Exception | None = None) -> None:
        """Raise ``error`` on every call if given."""
        self.error = error
        self.calls: list[dict[str, Any]] = []
        self.connections: list[FakeConnection] = []

    def __call__(self, **kwargs: Any) -> FakeConnection:
        """Record kwargs and return a new connection double."""
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        connection = FakeConnection()
        self.connections.append(connection)
        return connection


def make_connector(
    secrets: FakeSecretsClient | None = None, connect: RecordingConnect | None = None
) -> tuple[AuroraPostgreSQLConnector, FakeSecretsClient, RecordingConnect]:
    """Build a connector wired to doubles."""
    secrets = secrets or FakeSecretsClient()
    connect = connect or RecordingConnect()
    connector = AuroraPostgreSQLConnector(
        secret_arn=SECRET_ARN,
        statement_timeout_ms=5000,
        secrets_client=secrets,
        connect=connect,
    )
    return connector, secrets, connect


def test_opens_a_read_only_tls_connection_from_the_secret() -> None:
    connector, secrets, connect = make_connector()

    connection = connector.connection()

    assert connection is connect.connections[0]
    assert secrets.requested == [SECRET_ARN]
    assert connect.calls == [
        {
            "host": "db.cluster.local",
            "port": 5432,
            "dbname": "ledgerlens",
            "user": "ledgerlens_readonly",
            "password": "not-a-real-password",
            "sslmode": "require",
            "connect_timeout": 5,
            "autocommit": True,
            "row_factory": dict_row,
            "options": "-c statement_timeout=5000 -c default_transaction_read_only=on",
        }
    ]


def test_port_defaults_to_5432_when_the_secret_has_none() -> None:
    secret = {k: v for k, v in SECRET.items() if k != "port"}
    connector, _, connect = make_connector(secrets=FakeSecretsClient(secret))

    connector.connection()

    assert connect.calls[0]["port"] == 5432


def test_reuses_the_cached_connection() -> None:
    connector, _, connect = make_connector()

    assert connector.connection() is connector.connection()
    assert len(connect.calls) == 1


def test_reconnects_when_the_cached_connection_is_closed() -> None:
    connector, _, connect = make_connector()
    first = connector.connection()
    first.closed = True

    second = connector.connection()

    assert second is not first
    assert len(connect.calls) == 2


def test_reset_closes_and_drops_the_connection() -> None:
    connector, _, connect = make_connector()
    first = connector.connection()

    connector.reset()

    assert first.closed is True
    assert connector.connection() is not first
    assert len(connect.calls) == 2


def test_reset_without_a_connection_is_a_no_op() -> None:
    connector, _, connect = make_connector()

    connector.reset()

    assert connect.calls == []


def test_reset_ignores_errors_while_closing() -> None:
    connector, _, _ = make_connector()
    connection = connector.connection()

    def broken_close() -> None:
        raise psycopg.OperationalError("already gone")

    connection.close = broken_close  # type: ignore[method-assign]

    connector.reset()


@pytest.mark.parametrize(
    ("secrets", "connect"),
    [
        (FakeSecretsClient(error=RuntimeError("AccessDenied")), RecordingConnect()),
        (FakeSecretsClient(secret={"host": "db"}), RecordingConnect()),
        (FakeSecretsClient(), RecordingConnect(error=psycopg.OperationalError("x"))),
    ],
)
def test_any_failure_to_open_raises_data_source_connection_error(
    secrets: FakeSecretsClient, connect: RecordingConnect
) -> None:
    connector, _, _ = make_connector(secrets=secrets, connect=connect)

    with pytest.raises(DataSourceConnectionError) as caught:
        connector.connection()

    assert caught.value.__cause__ is not None
```

- [ ] **Step 3: Write the failing repository tests**

`tests/unit/ledgerlens_tools/test_postgresql_repository.py`:

```python
"""Tests for PostgreSQLRepository: rows, error mapping and the single retry."""

import psycopg
import pytest
from ledgerlens_fakes import FakeConnector, make_row

from ledgerlens.application.ports.errors import (
    DataSourceConnectionError,
    QueryExecutionError,
    QueryTimeoutError,
)
from ledgerlens.infrastructure.repositories.postgresql_repository import (
    PostgreSQLRepository,
)

pytestmark = pytest.mark.unit

QUERY = "SELECT * FROM transactions WHERE customer_id = %(customer_id)s"
PARAMS = {"customer_id": "CUST-1"}


def test_returns_rows_as_dicts_and_passes_query_and_params() -> None:
    connector = FakeConnector([make_row()])

    rows = PostgreSQLRepository(connector).execute_query(QUERY, PARAMS)

    assert rows == [make_row()]
    assert connector.connections[0].cursors[0].executed == [(QUERY, PARAMS)]


def test_statement_timeout_raises_query_timeout_without_retry() -> None:
    cancelled = psycopg.errors.QueryCanceled("canceling statement due to timeout")
    connector = FakeConnector(cancelled)

    with pytest.raises(QueryTimeoutError) as caught:
        PostgreSQLRepository(connector).execute_query(QUERY, PARAMS)

    assert caught.value.__cause__ is cancelled
    assert connector.reset_calls == 0
    assert len(connector.connections) == 1


@pytest.mark.parametrize(
    "error",
    [
        psycopg.errors.UndefinedTable('relation "transactions" does not exist'),
        psycopg.ProgrammingError("bad query"),
        psycopg.DataError("invalid input syntax"),
    ],
)
def test_other_psycopg_errors_raise_query_execution_error(
    error: psycopg.Error,
) -> None:
    connector = FakeConnector(error)

    with pytest.raises(QueryExecutionError) as caught:
        PostgreSQLRepository(connector).execute_query(QUERY, PARAMS)

    assert caught.value.__cause__ is error
    assert connector.reset_calls == 0


def test_operational_error_resets_and_retries_once_then_succeeds() -> None:
    connector = FakeConnector(
        psycopg.OperationalError("server closed the connection"), [make_row()]
    )

    rows = PostgreSQLRepository(connector).execute_query(QUERY, PARAMS)

    assert rows == [make_row()]
    assert connector.reset_calls == 1
    assert len(connector.connections) == 2


def test_second_operational_error_raises_data_source_connection_error() -> None:
    lost = psycopg.OperationalError("server closed the connection")
    connector = FakeConnector(lost)

    with pytest.raises(DataSourceConnectionError) as caught:
        PostgreSQLRepository(connector).execute_query(QUERY, PARAMS)

    assert caught.value.__cause__ is lost
    assert connector.reset_calls == 2
    assert len(connector.connections) == 2


def test_connector_failure_propagates_unchanged() -> None:
    failure = DataSourceConnectionError("secret unreadable")
    connector = FakeConnector(failure)

    with pytest.raises(DataSourceConnectionError) as caught:
        PostgreSQLRepository(connector).execute_query(QUERY, PARAMS)

    assert caught.value is failure
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/ledgerlens_tools/test_aurora_postgresql_connector.py tests/unit/ledgerlens_tools/test_postgresql_repository.py -v`
Expected: collection ERROR with `ModuleNotFoundError: No module named 'ledgerlens.utils.connectors.aurora_postgresql'`.

- [ ] **Step 5: Implement the connector Protocol and the connector**

`gateway/tools/ledgerlens_tools/ledgerlens/utils/connectors/base.py`:

```python
"""Connector contract shared by psycopg-based repositories."""

from typing import Any, Protocol

import psycopg


class PsycopgConnector(Protocol):
    """Owns one psycopg connection's lifecycle for a Lambda container."""

    def connection(self) -> psycopg.Connection[Any]:
        """Return an open connection, opening a new one if needed.

        Raises:
            DataSourceConnectionError: The connection couldn't be opened.
        """
        ...

    def reset(self) -> None:
        """Close and forget the cached connection so the next call reconnects."""
        ...
```

`gateway/tools/ledgerlens_tools/ledgerlens/utils/connectors/aurora_postgresql.py`:

```python
"""Aurora PostgreSQL connector: one cached psycopg connection per Lambda container.

TODO(ledgerlens): R2 - no Aurora cluster or secret exists yet; DB_SECRET_ARN has
  nothing real to point at until the Aurora and data-load spec lands.
TODO(ledgerlens): R6 - default_transaction_read_only=on guards against writes, but
  the secret should belong to a read-only DB user (ledgerlens_readonly).
TODO(ledgerlens): R7 - one connection per warm container, so many concurrent
  containers could exhaust Aurora's max_connections. Accepted for the demo; no
  mitigation is built. Beyond a demo: cap reservedConcurrentExecutions per tool
  Lambda, then RDS Proxy (only the secret's host changes). The RDS Data API is an
  alternative, as a new DatabaseRepository adapter.
"""

import json
import logging
from collections.abc import Callable, Mapping
from typing import Any, Final, Protocol

import boto3
import psycopg
from psycopg.rows import dict_row

from ledgerlens.application.ports.errors import DataSourceConnectionError

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT_SECONDS: Final = 5
_DEFAULT_PORT: Final = 5432


class SecretsClient(Protocol):
    """The part of the boto3 Secrets Manager client the connector uses."""

    def get_secret_value(self, *, SecretId: str) -> Mapping[str, Any]:  # noqa: N803
        """Return the secret payload; ``SecretString`` holds the JSON credentials."""
        ...


class AuroraPostgreSQLConnector:
    """Open and cache a read-only psycopg connection to Aurora PostgreSQL.

    Credentials come from a Secrets Manager secret with the standard RDS keys
    (host, port, dbname, username, password). They are read on every (re)connect,
    so a rotated password is picked up after a reset.
    """

    def __init__(
        self,
        secret_arn: str,
        statement_timeout_ms: int,
        secrets_client: SecretsClient | None = None,
        connect: Callable[..., psycopg.Connection[Any]] = psycopg.connect,
    ) -> None:
        """Configure the connector without opening a connection.

        Args:
            secret_arn: ARN of the Secrets Manager secret with the credentials.
            statement_timeout_ms: Server-side timeout applied to every statement.
            secrets_client: Secrets Manager client; created lazily if omitted.
            connect: Connection factory; replaced in tests.
        """
        self._secret_arn: str = secret_arn
        self._statement_timeout_ms: int = statement_timeout_ms
        self._secrets_client: SecretsClient | None = secrets_client
        self._connect: Callable[..., psycopg.Connection[Any]] = connect
        self._connection: psycopg.Connection[Any] | None = None

    def connection(self) -> psycopg.Connection[Any]:
        """Return the cached connection, opening a new one if missing or closed.

        Raises:
            DataSourceConnectionError: The secret or the database couldn't be
                reached.
        """
        if self._connection is None or self._connection.closed:
            self._connection = self._open()
        return self._connection

    def reset(self) -> None:
        """Close and drop the cached connection; errors while closing are ignored."""
        connection, self._connection = self._connection, None
        if connection is None:
            return
        try:
            connection.close()
        except Exception:
            logger.warning("Ignoring error while closing a connection", exc_info=True)

    def _open(self) -> psycopg.Connection[Any]:
        """Read the credentials and open a new connection.

        Raises:
            DataSourceConnectionError: Any failure, chained to the original error.
        """
        try:
            credentials = self._read_secret()
            return self._connect(
                host=credentials["host"],
                port=int(credentials.get("port", _DEFAULT_PORT)),
                dbname=credentials["dbname"],
                user=credentials["username"],
                password=credentials["password"],
                sslmode="require",
                connect_timeout=_CONNECT_TIMEOUT_SECONDS,
                autocommit=True,
                row_factory=dict_row,
                options=(
                    f"-c statement_timeout={self._statement_timeout_ms} "
                    "-c default_transaction_read_only=on"
                ),
            )
        except Exception as exc:
            raise DataSourceConnectionError(
                "Could not open a connection to Aurora PostgreSQL"
            ) from exc

    def _read_secret(self) -> Mapping[str, Any]:
        """Fetch and parse the credentials JSON from Secrets Manager."""
        if self._secrets_client is None:
            self._secrets_client = boto3.client("secretsmanager")
        response = self._secrets_client.get_secret_value(SecretId=self._secret_arn)
        credentials: Mapping[str, Any] = json.loads(response["SecretString"])
        return credentials
```

- [ ] **Step 6: Implement the repository**

`gateway/tools/ledgerlens_tools/ledgerlens/infrastructure/repositories/postgresql_repository.py`:

```python
"""DatabaseRepository adapter for PostgreSQL through psycopg 3."""

import logging
from collections.abc import Mapping
from typing import Any, Final

import psycopg

from ledgerlens.application.ports.database_repository import DatabaseRepository
from ledgerlens.application.ports.errors import (
    DataSourceConnectionError,
    QueryExecutionError,
    QueryTimeoutError,
)
from ledgerlens.utils.connectors.base import PsycopgConnector

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS: Final = 2


class PostgreSQLRepository(DatabaseRepository):
    """Run parameterised SQL on PostgreSQL and translate psycopg errors.

    A lost connection (``OperationalError``) is reset and the query retried once.
    That is safe because every query runs in a read-only session.
    """

    def __init__(self, connector: PsycopgConnector) -> None:
        """Use ``connector`` to obtain (and reset) the database connection."""
        self._connector: PsycopgConnector = connector

    def execute_query(
        self, query: str, params: Mapping[str, object]
    ) -> list[dict[str, Any]]:
        """Execute the query and return all rows as dictionaries.

        Raises:
            DataSourceConnectionError: The connection failed twice, or couldn't be
                opened.
            QueryTimeoutError: The statement timeout cancelled the query.
            QueryExecutionError: Any other database error.
        """
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return self._run(query, params)
            except psycopg.errors.QueryCanceled as exc:
                # Subclass of OperationalError: must be caught first, never retried.
                raise QueryTimeoutError("Statement timeout exceeded") from exc
            except psycopg.OperationalError as exc:
                self._connector.reset()
                if attempt == _MAX_ATTEMPTS:
                    raise DataSourceConnectionError(
                        "Database connection failed after a retry"
                    ) from exc
                logger.warning(
                    "Database connection failed; reconnecting and retrying once",
                    exc_info=True,
                )
            except psycopg.Error as exc:
                raise QueryExecutionError("The database failed to run the query") from exc
        raise AssertionError("unreachable: the retry loop always returns or raises")

    def _run(self, query: str, params: Mapping[str, object]) -> list[dict[str, Any]]:
        """Run the query once on the connector's current connection."""
        connection = self._connector.connection()
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/ledgerlens_tools -v`
Expected: all pass.

- [ ] **Step 8: Lint**

Run: `python -m ruff format gateway/tools/ledgerlens_tools tests/unit/ledgerlens_tools && python -m ruff check --fix gateway/tools/ledgerlens_tools tests/unit/ledgerlens_tools`
Expected: `All checks passed!` If ruff flags `S105` or `N803` anywhere other than the lines already marked `noqa`, fix the code; don't add more `noqa`.

- [ ] **Step 9: Commit**

```bash
git add gateway/tools/ledgerlens_tools/ledgerlens/utils/connectors/base.py gateway/tools/ledgerlens_tools/ledgerlens/utils/connectors/aurora_postgresql.py gateway/tools/ledgerlens_tools/ledgerlens/infrastructure/repositories/postgresql_repository.py tests/unit/ledgerlens_tools/ledgerlens_fakes.py tests/unit/ledgerlens_tools/test_aurora_postgresql_connector.py tests/unit/ledgerlens_tools/test_postgresql_repository.py
git commit -m "feat(tools): add Aurora PostgreSQL connector and PostgreSQL repository"
```

---

### Task 6: Settings, database wiring, `build_dependencies` and the presenter

**Files:**
- Create:
  - `gateway/tools/ledgerlens_tools/ledgerlens/delivery/settings.py`
  - `gateway/tools/ledgerlens_tools/ledgerlens/delivery/database.py`
  - `gateway/tools/ledgerlens_tools/ledgerlens/delivery/dependencies/list_card_transactions.py`
  - `gateway/tools/ledgerlens_tools/ledgerlens/delivery/presenters/card_transactions.py`
- Test: `tests/unit/ledgerlens_tools/test_delivery_wiring.py`

**Interfaces:**
- Consumes: every class from Tasks 1 through 5, and `FakeConnector` and `make_row`.
- Produces:
  - `ConfigurationError(Exception)`.
  - Frozen dataclass `DatabaseSettings(engine: str, secret_arn: str, statement_timeout_ms: int, max_rows: int)` with `from_env(env: Mapping[str, str]) -> DatabaseSettings`.
  - `QUERIES_ROOT: Path`.
  - `build_connector(settings) -> PsycopgConnector`.
  - `build_repository(engine: str, connector: PsycopgConnector) -> DatabaseRepository`.
  - `build_query_provider(engine: str) -> QueryProvider`, cached per engine.
  - `build_dependencies(connector: PsycopgConnector, settings: DatabaseSettings) -> ListCardTransactionsUseCase`.
  - `present_card_transactions(result: CardTransactionsResult) -> dict[str, Any]`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/ledgerlens_tools/test_delivery_wiring.py`:

```python
"""Tests for settings, dependency wiring and the card transactions presenter."""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from ledgerlens_fakes import FakeConnector, make_filters, make_row

from ledgerlens.application.use_cases.list_card_transactions import (
    ListCardTransactionsUseCase,
)
from ledgerlens.delivery.database import (
    QUERIES_ROOT,
    build_connector,
    build_query_provider,
)
from ledgerlens.delivery.dependencies.list_card_transactions import (
    build_dependencies,
)
from ledgerlens.delivery.presenters.card_transactions import (
    present_card_transactions,
)
from ledgerlens.delivery.settings import ConfigurationError, DatabaseSettings
from ledgerlens.domain.entities.card_transaction import (
    CardTransaction,
    CardTransactionsResult,
)
from ledgerlens.utils.connectors.aurora_postgresql import AuroraPostgreSQLConnector

pytestmark = pytest.mark.unit

ENV = {"DB_ENGINE": "postgresql", "DB_SECRET_ARN": "arn:aws:secretsmanager:x"}
SETTINGS = DatabaseSettings(
    engine="postgresql",
    secret_arn="arn:aws:secretsmanager:x",
    statement_timeout_ms=5000,
    max_rows=25,
)


def test_settings_apply_defaults() -> None:
    assert DatabaseSettings.from_env(ENV) == SETTINGS


def test_settings_read_overrides_and_normalise_engine() -> None:
    env = {
        **ENV,
        "DB_ENGINE": " PostgreSQL ",
        "DB_STATEMENT_TIMEOUT_MS": "8000",
        "MAX_ROWS": "10",
    }

    settings = DatabaseSettings.from_env(env)

    assert (settings.engine, settings.statement_timeout_ms, settings.max_rows) == (
        "postgresql",
        8000,
        10,
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"DB_ENGINE": ""}, "DB_ENGINE"),
        ({"DB_ENGINE": "mysql"}, "DB_ENGINE"),
        ({"DB_SECRET_ARN": "  "}, "DB_SECRET_ARN"),
        ({"DB_STATEMENT_TIMEOUT_MS": "abc"}, "DB_STATEMENT_TIMEOUT_MS"),
        ({"DB_STATEMENT_TIMEOUT_MS": "0"}, "DB_STATEMENT_TIMEOUT_MS"),
        ({"MAX_ROWS": "-5"}, "MAX_ROWS"),
    ],
)
def test_invalid_settings_raise_configuration_error(
    overrides: dict[str, str], message: str
) -> None:
    with pytest.raises(ConfigurationError, match=message):
        DatabaseSettings.from_env({**ENV, **overrides})


def test_missing_variables_raise_configuration_error() -> None:
    with pytest.raises(ConfigurationError, match="DB_ENGINE"):
        DatabaseSettings.from_env({})


def test_build_connector_does_not_connect() -> None:
    connector = build_connector(SETTINGS)

    assert isinstance(connector, AuroraPostgreSQLConnector)


def test_query_provider_is_cached_per_engine_and_finds_the_sql() -> None:
    provider = build_query_provider("postgresql")

    assert provider is build_query_provider("postgresql")
    assert "DISTINCT ON" in provider.get("list_card_transactions")
    assert (QUERIES_ROOT / "postgresql" / "list_card_transactions.sql").is_file()


def test_build_dependencies_wires_real_adapters_end_to_end() -> None:
    connector = FakeConnector([make_row()])

    use_case = build_dependencies(connector, SETTINGS)
    result = use_case.execute(make_filters())

    assert isinstance(use_case, ListCardTransactionsUseCase)
    assert result.transactions[0].transaction_id == "TX-1"
    executed_sql, params = connector.connections[0].cursors[0].executed[0]
    assert "FROM transactions" in executed_sql
    assert params["limit"] == 26


def test_build_dependencies_uses_max_rows_from_settings() -> None:
    connector = FakeConnector([make_row(transaction_id=str(i)) for i in range(4)])
    settings = DatabaseSettings("postgresql", "arn", 5000, max_rows=3)

    result = build_dependencies(connector, settings).execute(make_filters())

    assert len(result.transactions) == 3
    assert result.truncated is True


def make_transaction(**overrides: object) -> CardTransaction:
    """Build a CardTransaction for presenter tests."""
    values: dict[str, object] = {
        "transaction_id": "TX-1",
        "transaction_date": datetime(
            2026, 9, 20, 14, 30, tzinfo=timezone(timedelta(hours=-5))
        ),
        "card_last4": "4242",
        "amount": Decimal("12.5"),
        "currency": "COP",
        "transaction_status": "Approved",
        "merchant_name": "Café Aroma",
        "merchant_category": "Restaurants",
        "channel": "POS",
        "transaction_city": "Medellín",
        "transaction_country": "CO",
    }
    values.update(overrides)
    return CardTransaction(**values)  # type: ignore[arg-type]


def test_presenter_shapes_the_agent_json() -> None:
    result = CardTransactionsResult(transactions=(make_transaction(),), truncated=True)

    assert present_card_transactions(result) == {
        "transactions": [
            {
                "transaction_id": "TX-1",
                "transaction_date": "2026-09-20T14:30:00-05:00",
                "card_last4": "4242",
                "merchant_name": "Café Aroma",
                "merchant_category": "Restaurants",
                "amount": "12.50",
                "currency": "COP",
                "channel": "POS",
                "transaction_city": "Medellín",
                "transaction_country": "CO",
                "transaction_status": "Approved",
            }
        ],
        "count": 1,
        "truncated": True,
    }


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("7"), "7.00"),
        (Decimal("10.005"), "10.01"),
        (Decimal("0.004"), "0.00"),
        (Decimal("412000.38"), "412000.38"),
    ],
)
def test_presenter_formats_amounts_as_two_decimal_strings(
    amount: Decimal, expected: str
) -> None:
    result = CardTransactionsResult((make_transaction(amount=amount),), False)

    assert present_card_transactions(result)["transactions"][0]["amount"] == expected


def test_presenter_keeps_nulls_and_output_is_json_serialisable() -> None:
    transaction = make_transaction(currency=None, merchant_name=None)
    body = present_card_transactions(CardTransactionsResult((transaction,), False))

    assert body["transactions"][0]["currency"] is None
    assert body["transactions"][0]["merchant_name"] is None
    json.dumps(body)


def test_presenter_handles_an_empty_result() -> None:
    assert present_card_transactions(CardTransactionsResult((), False)) == {
        "transactions": [],
        "count": 0,
        "truncated": False,
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/ledgerlens_tools/test_delivery_wiring.py -v`
Expected: collection ERROR with `ModuleNotFoundError: No module named 'ledgerlens.delivery.database'`.

- [ ] **Step 3: Implement the settings**

`gateway/tools/ledgerlens_tools/ledgerlens/delivery/settings.py`:

```python
"""Lambda configuration read from environment variables."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

SUPPORTED_ENGINES: Final = frozenset({"postgresql"})
DEFAULT_STATEMENT_TIMEOUT_MS: Final = 5000
DEFAULT_MAX_ROWS: Final = 25


class ConfigurationError(Exception):
    """The Lambda environment is missing a setting or has an invalid one."""


@dataclass(frozen=True)
class DatabaseSettings:
    """Database settings shared by every tool Lambda.

    Attributes:
        engine: Database engine; selects the connector, repository and SQL dialect.
        secret_arn: Secrets Manager secret with the DB credentials.
        statement_timeout_ms: Server-side timeout for every statement.
        max_rows: Maximum rows a tool returns per call.
    """

    engine: str
    secret_arn: str
    statement_timeout_ms: int
    max_rows: int

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "DatabaseSettings":
        """Read and validate DB_ENGINE, DB_SECRET_ARN, DB_STATEMENT_TIMEOUT_MS
        and MAX_ROWS.

        Raises:
            ConfigurationError: A required variable is missing or a value is
                invalid.
        """
        engine = env.get("DB_ENGINE", "").strip().lower()
        if engine not in SUPPORTED_ENGINES:
            allowed = ", ".join(sorted(SUPPORTED_ENGINES))
            raise ConfigurationError(f"DB_ENGINE must be one of: {allowed}; got {engine!r}")
        secret_arn = env.get("DB_SECRET_ARN", "").strip()
        if not secret_arn:
            raise ConfigurationError("DB_SECRET_ARN is required")
        return cls(
            engine=engine,
            secret_arn=secret_arn,
            statement_timeout_ms=_positive_int(
                env, "DB_STATEMENT_TIMEOUT_MS", DEFAULT_STATEMENT_TIMEOUT_MS
            ),
            max_rows=_positive_int(env, "MAX_ROWS", DEFAULT_MAX_ROWS),
        )


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    """Parse an optional positive integer variable.

    Raises:
        ConfigurationError: The value isn't an integer greater than zero.
    """
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero, got {value}")
    return value
```

- [ ] **Step 4: Implement the database wiring**

`gateway/tools/ledgerlens_tools/ledgerlens/delivery/database.py`:

```python
"""Engine-specific wiring shared by every tool's build_dependencies().

Adding a database engine means adding a branch here, a connector, a repository
and a ``queries/<engine>/`` folder. Use cases don't change.
"""

from functools import cache
from pathlib import Path
from typing import Final

from ledgerlens.application.ports.database_repository import DatabaseRepository
from ledgerlens.application.ports.query_provider import QueryProvider
from ledgerlens.delivery.settings import ConfigurationError, DatabaseSettings
from ledgerlens.infrastructure.queries.file_query_provider import FileQueryProvider
from ledgerlens.infrastructure.repositories.postgresql_repository import (
    PostgreSQLRepository,
)
from ledgerlens.utils.connectors.aurora_postgresql import AuroraPostgreSQLConnector
from ledgerlens.utils.connectors.base import PsycopgConnector

QUERIES_ROOT: Final = Path(__file__).resolve().parents[1] / "queries"


def build_connector(settings: DatabaseSettings) -> PsycopgConnector:
    """Create the connector for the configured engine without connecting.

    Raises:
        ConfigurationError: The engine isn't supported.
    """
    if settings.engine == "postgresql":
        return AuroraPostgreSQLConnector(
            secret_arn=settings.secret_arn,
            statement_timeout_ms=settings.statement_timeout_ms,
        )
    raise ConfigurationError(f"Unsupported DB_ENGINE {settings.engine!r}")


def build_repository(engine: str, connector: PsycopgConnector) -> DatabaseRepository:
    """Create the repository adapter for ``engine`` around ``connector``.

    Raises:
        ConfigurationError: The engine isn't supported.
    """
    if engine == "postgresql":
        return PostgreSQLRepository(connector)
    raise ConfigurationError(f"Unsupported DB_ENGINE {engine!r}")


@cache
def build_query_provider(engine: str) -> QueryProvider:
    """Return the query provider for ``engine``'s SQL dialect folder.

    Cached so SQL files are read once per container, even though
    build_dependencies() runs on every invocation.
    """
    return FileQueryProvider(QUERIES_ROOT / engine)
```

- [ ] **Step 5: Implement `build_dependencies`**

`gateway/tools/ledgerlens_tools/ledgerlens/delivery/dependencies/list_card_transactions.py`:

```python
"""Dependency builder for the list_card_transactions tool."""

from ledgerlens.application.use_cases.list_card_transactions import (
    ListCardTransactionsUseCase,
)
from ledgerlens.delivery.database import build_query_provider, build_repository
from ledgerlens.delivery.settings import DatabaseSettings
from ledgerlens.utils.connectors.base import PsycopgConnector


def build_dependencies(
    connector: PsycopgConnector, settings: DatabaseSettings
) -> ListCardTransactionsUseCase:
    """Wire the use case around the global connector.

    Cheap to call on every invocation: it only builds plain objects. The
    connection lives in the connector, and SQL text is cached by the provider.
    """
    return ListCardTransactionsUseCase(
        repository=build_repository(settings.engine, connector),
        queries=build_query_provider(settings.engine),
        max_rows=settings.max_rows,
    )
```

- [ ] **Step 6: Implement the presenter**

`gateway/tools/ledgerlens_tools/ledgerlens/delivery/presenters/card_transactions.py`:

```python
"""Present card transaction results as the JSON returned to the agent."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from ledgerlens.domain.entities.card_transaction import (
    CardTransaction,
    CardTransactionsResult,
)

_CENTS: Final = Decimal("0.01")


def present_card_transactions(result: CardTransactionsResult) -> dict[str, Any]:
    """Return ``{"transactions": [...], "count": n, "truncated": bool}``.

    Dates are ISO 8601 strings and amounts are 2-decimal strings, so no float
    rounding reaches the agent. Missing values stay ``None`` (JSON null).
    """
    return {
        "transactions": [_present(t) for t in result.transactions],
        "count": len(result.transactions),
        "truncated": result.truncated,
    }


def _present(transaction: CardTransaction) -> dict[str, Any]:
    """Convert one transaction to JSON-safe values."""
    return {
        "transaction_id": transaction.transaction_id,
        "transaction_date": transaction.transaction_date.isoformat(),
        "card_last4": transaction.card_last4,
        "merchant_name": transaction.merchant_name,
        "merchant_category": transaction.merchant_category,
        "amount": str(transaction.amount.quantize(_CENTS, rounding=ROUND_HALF_UP)),
        "currency": transaction.currency,
        "channel": transaction.channel,
        "transaction_city": transaction.transaction_city,
        "transaction_country": transaction.transaction_country,
        "transaction_status": transaction.transaction_status,
    }
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/ledgerlens_tools -v`
Expected: all pass.

- [ ] **Step 8: Lint**

Run: `python -m ruff format gateway/tools/ledgerlens_tools tests/unit/ledgerlens_tools && python -m ruff check --fix gateway/tools/ledgerlens_tools tests/unit/ledgerlens_tools`
Expected: `All checks passed!`

- [ ] **Step 9: Commit**

```bash
git add gateway/tools/ledgerlens_tools/ledgerlens/delivery/settings.py gateway/tools/ledgerlens_tools/ledgerlens/delivery/database.py gateway/tools/ledgerlens_tools/ledgerlens/delivery/dependencies/list_card_transactions.py gateway/tools/ledgerlens_tools/ledgerlens/delivery/presenters/card_transactions.py tests/unit/ledgerlens_tools/test_delivery_wiring.py
git commit -m "feat(tools): add settings, dependency wiring and transactions presenter"
```

---

### Task 7: Lambda handler

**Files:**
- Create: `gateway/tools/ledgerlens_tools/ledgerlens/delivery/list_card_transactions_handler.py`
- Test: `tests/unit/ledgerlens_tools/test_list_card_transactions_handler.py`

**Interfaces:**
- Consumes:
  - `DatabaseSettings`, `ConfigurationError` and `build_connector` (Task 6)
  - `build_dependencies` and `present_card_transactions` (Task 6)
  - `TransactionFilters` (Task 2)
  - `DomainError` and `DataSourceUnavailableError` (Task 1)
- Produces:
  - Module globals `SETTINGS` and `CONNECTOR`, set at import by `_initialise(os.environ)`.
  - `handler(event: object, context: object) -> dict[str, Any]`.
  - Constants `TOOL_NAME` and `UNEXPECTED_ERROR_MESSAGE`.
  - The Lambda handler string is `ledgerlens/delivery/list_card_transactions_handler.handler`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/ledgerlens_tools/test_list_card_transactions_handler.py`:

```python
"""Tests for the list_card_transactions Lambda handler."""

import importlib
import json
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from ledgerlens_fakes import FakeConnector, make_row

from ledgerlens.application.ports.errors import DataSourceConnectionError
from ledgerlens.delivery.settings import DatabaseSettings
from ledgerlens.domain.errors import DataSourceUnavailableError

pytestmark = pytest.mark.unit

SETTINGS = DatabaseSettings("postgresql", "arn:aws:secretsmanager:x", 5000, 25)
EVENT = {"customer_id": "CUST-1", "date_from": "2026-09-01", "date_to": "2026-09-29"}


def make_context(
    tool_name: str = "list-card-transactions-target___list_card_transactions",
) -> SimpleNamespace:
    """Build a Lambda context carrying the Gateway tool name."""
    return SimpleNamespace(
        client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": tool_name})
    )


@pytest.fixture
def module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Import the handler module fresh, with no DB env vars (no AWS calls)."""
    for name in ("DB_ENGINE", "DB_SECRET_ARN", "DB_STATEMENT_TIMEOUT_MS", "MAX_ROWS"):
        monkeypatch.delenv(name, raising=False)
    import ledgerlens.delivery.list_card_transactions_handler as handler_module

    return importlib.reload(handler_module)


def wire(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, connector: Any
) -> None:
    """Point the handler's globals at test settings and a fake connector."""
    monkeypatch.setattr(module, "SETTINGS", SETTINGS)
    monkeypatch.setattr(module, "CONNECTOR", connector)


def body(response: dict[str, Any]) -> dict[str, Any]:
    """Decode the JSON text of a success response."""
    content = response["content"]
    assert content[0]["type"] == "text"
    return json.loads(content[0]["text"])


def test_success_returns_gateway_content_with_the_transactions(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector([make_row()]))

    response = module.handler(EVENT, make_context())

    payload = body(response)
    assert payload["count"] == 1
    assert payload["truncated"] is False
    assert payload["transactions"][0]["amount"] == "12.50"
    assert payload["transactions"][0]["transaction_date"] == "2026-09-20T14:30:00+00:00"


def test_non_ascii_text_is_not_escaped(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector([make_row()]))

    response = module.handler(EVENT, make_context())

    assert "Café Aroma" in response["content"][0]["text"]


def test_empty_result_is_a_success(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector([]))

    assert body(module.handler(EVENT, make_context()))["count"] == 0


def test_invalid_input_returns_the_domain_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = FakeConnector([make_row()])
    wire(module, monkeypatch, connector)

    response = module.handler({**EVENT, "card_last4": "12"}, make_context())

    assert response == {
        "error": "Invalid value for 'card_last4': must be exactly 4 digits. "
        "Ask the customer to confirm and retry."
    }
    assert connector.connections == []


@pytest.mark.parametrize("event", [None, [], "customer_id=CUST-1"])
def test_non_object_event_returns_a_clean_error(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, event: object
) -> None:
    wire(module, monkeypatch, FakeConnector())

    response = module.handler(event, make_context())

    assert "must be a JSON object" in response["error"]


@pytest.mark.parametrize(
    "context",
    [
        make_context("other-target___text_analysis_tool"),
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
    assert "list_card_transactions" in response["error"]
    assert connector.connections == []


def test_tool_name_without_a_target_prefix_is_accepted(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector([]))

    assert "content" in module.handler(EVENT, make_context("list_card_transactions"))


def test_unexpected_exception_returns_a_generic_message_without_internals(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector())

    def explode(*_args: object) -> None:
        raise RuntimeError("password=hunter2 host=db.internal")

    monkeypatch.setattr(module, "build_dependencies", explode)

    response = module.handler(EVENT, make_context())

    assert response == {"error": module.UNEXPECTED_ERROR_MESSAGE}
    assert "hunter2" not in response["error"]


def test_missing_configuration_returns_data_source_unavailable(
    module: ModuleType,
) -> None:
    assert module.SETTINGS is None
    assert module.CONNECTOR is None

    response = module.handler(EVENT, make_context())

    assert response == {"error": DataSourceUnavailableError.MESSAGE}


def test_initialise_survives_a_failed_cold_start_connection(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = FakeConnector(DataSourceConnectionError("no route to host"))
    monkeypatch.setattr(module, "build_connector", lambda _settings: connector)

    settings, returned = module._initialise(
        {"DB_ENGINE": "postgresql", "DB_SECRET_ARN": "arn:aws:secretsmanager:x"}
    )

    assert settings == SETTINGS
    assert returned is connector


def test_cold_start_failure_then_failed_retry_returns_unavailable(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch, FakeConnector(DataSourceConnectionError("down")))

    response = module.handler(EVENT, make_context())

    assert response == {"error": DataSourceUnavailableError.MESSAGE}


def test_initialise_with_bad_configuration_returns_nones(module: ModuleType) -> None:
    assert module._initialise({"DB_ENGINE": "oracle"}) == (None, None)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/ledgerlens_tools/test_list_card_transactions_handler.py -v`
Expected: every test ERRORs in the `module` fixture with `ModuleNotFoundError: No module named 'ledgerlens.delivery.list_card_transactions_handler'`.

- [ ] **Step 3: Implement the handler**

`gateway/tools/ledgerlens_tools/ledgerlens/delivery/list_card_transactions_handler.py`:

```python
"""Lambda handler for the ``list_card_transactions`` Gateway tool.

Handler string: ``ledgerlens/delivery/list_card_transactions_handler.handler``.

Input: the tool arguments as the event (see
``gateway/tools/list_card_transactions/tool_spec.json``); the tool name arrives in
``context.client_context.custom["bedrockAgentCoreToolName"]`` with a
``<target>___`` prefix, as in ``gateway/tools/sample_tool``.

Output: ``{"content": [{"type": "text", "text": <JSON>}]}`` on success, or
``{"error": <agent-facing message>}``. Unlike the sample tool, raw exception text
is never returned: it could leak SQL, hosts or driver details to the model.

The connector (and its connection) is global, created when the module loads so a
warm container reuses it; build_dependencies() is called per invocation.

TODO(ledgerlens): R1 - no CDK yet: no PythonFunction, Gateway target, VPC, security
  group, secret grant or env vars (DB_ENGINE, DB_SECRET_ARN). The tool can't be
  deployed or called by the agent until the CDK spec lands.
TODO(ledgerlens): R5 - customer_id is trusted from the tool input. Authorization
  depends on a Cedar policy matching it to the token's customer_id claim; neither
  the policy nor the claim exists yet (product design sections 5 and 10).
"""

import json
import logging
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Final

from ledgerlens.delivery.database import build_connector
from ledgerlens.delivery.dependencies.list_card_transactions import (
    build_dependencies,
)
from ledgerlens.delivery.presenters.card_transactions import (
    present_card_transactions,
)
from ledgerlens.delivery.settings import ConfigurationError, DatabaseSettings
from ledgerlens.domain.errors import DataSourceUnavailableError, DomainError
from ledgerlens.domain.value_objects.transaction_filters import TransactionFilters
from ledgerlens.utils.connectors.base import PsycopgConnector

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TOOL_NAME: Final = "list_card_transactions"
_TOOL_NAME_DELIMITER: Final = "___"
UNEXPECTED_ERROR_MESSAGE: Final = (
    "Unexpected internal error listing transactions. "
    "Offer a hand-off to a human agent."
)
_WRONG_TOOL_MESSAGE: Final = (
    f"This function only serves the '{TOOL_NAME}' tool. "
    "Don't retry; offer a hand-off to a human agent."
)


def _initialise(
    env: Mapping[str, str],
) -> tuple[DatabaseSettings | None, PsycopgConnector | None]:
    """Load settings and open the global connection at cold start. Never raises.

    A failed connection is only logged: the first request retries it lazily, so
    the Lambda init doesn't crash. Bad configuration yields ``(None, None)`` and
    every request then returns DataSourceUnavailableError's message.
    """
    try:
        settings = DatabaseSettings.from_env(env)
        connector = build_connector(settings)
    except ConfigurationError:
        logger.exception("Invalid database configuration for %s", TOOL_NAME)
        return None, None
    try:
        connector.connection()
    except Exception:
        logger.warning(
            "Cold-start database connection failed; the first request will retry",
            exc_info=True,
        )
    return settings, connector


SETTINGS, CONNECTOR = _initialise(os.environ)


def handler(event: object, context: object) -> dict[str, Any]:
    """Search the customer's card transactions for the agent.

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
        if SETTINGS is None or CONNECTOR is None:
            raise DataSourceUnavailableError()
        use_case = build_dependencies(CONNECTOR, SETTINGS)
        filters = TransactionFilters.from_raw(
            event, today=datetime.now(timezone.utc).date()
        )
        body = present_card_transactions(use_case.execute(filters))
    except DomainError as err:
        logger.warning("%s returned an error: %s", TOOL_NAME, err.message, exc_info=True)
        return {"error": err.message}
    except Exception:
        logger.exception("Unexpected error in %s", TOOL_NAME)
        return {"error": UNEXPECTED_ERROR_MESSAGE}

    logger.info(
        "%s returned %d transactions (truncated=%s)",
        TOOL_NAME,
        body["count"],
        body["truncated"],
    )
    return {
        "content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]
    }


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

The raw event is deliberately **not** logged, because it holds customer identifiers and search terms.

- [ ] **Step 4: Run the whole suite to verify it passes**

Run: `python -m pytest tests/unit/ledgerlens_tools -v`
Expected: all pass.

Run: `python -m pytest tests/unit -m unit -q`
Expected: the existing `test_mcp_registry.py` still passes alongside the new tests.

- [ ] **Step 5: Final layer and TODO checks, then lint**

Run: `grep -rnE "psycopg|boto3|ledgerlens\.(infrastructure|utils|delivery)" gateway/tools/ledgerlens_tools/ledgerlens/domain gateway/tools/ledgerlens_tools/ledgerlens/application`
Expected: no output.

Run: `grep -rnoE --include="*.py" --include="*.sql" --include="*.txt" "TODO\(ledgerlens\): R[0-9]" gateway/tools/ledgerlens_tools | sort -t: -k3`
Expected: R1 twice (handler, requirements), R2 (connector), R3 (SQL), R4 twice (enum, SQL), R5 (handler), R6 (connector), R7 (connector), R8 (SQL), R9 (requirements).

Run: `python -m ruff format gateway/tools/ledgerlens_tools tests/unit/ledgerlens_tools && python -m ruff check --fix gateway/tools/ledgerlens_tools tests/unit/ledgerlens_tools`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add gateway/tools/ledgerlens_tools/ledgerlens/delivery/list_card_transactions_handler.py tests/unit/ledgerlens_tools/test_list_card_transactions_handler.py
git commit -m "feat(tools): add list_card_transactions Lambda handler"
```

---

## After all tasks

- Check `git status`. `infra-cdk/config.yaml` and the drawio file must still be **unstaged**, as they were before.
- Nothing is deployed. The next specs are CDK (R1, R9), Aurora and data load (R2, R6, R8), and Cedar with the customer claim (R5).
