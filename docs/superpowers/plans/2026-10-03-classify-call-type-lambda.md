# classify_call_type Lambda Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `classify_call_type` Gateway tool Lambda as a self-contained folder, `gateway/tools/classify_call_type/classify_call_type_lambda/`. It ranks up to 3 likely reasons the customer is calling. Each reason comes with a confidence, the record it points to (`ref_id`) and structured evidence. The raw fraud score never leaves the Lambda.

**Architecture:** The shared layers are copied from `gateway/tools/get_session_context/` with sed. The domain holds the following, all as pure Python:
- `fraud_bands.py`, copied from `transaction_fraud_detection`;
- `text_folding.py`, copied from `explain_transaction`;
- the reason taxonomy, `call_reasons.py`;
- the candidate entities;
- a `reason_ranking` service that detects, scores and ranks.

The use case runs four candidate queries in sequence, each in its own `try`. A failed source makes only its reasons `unavailable`, and only a failure of all four fails the call. The presenter builds the evidence object for each reason.

**Tech Stack:** Python 3.13 (`.venv`), pytest, ruff, psycopg 3, TypeScript CDK with jest, and Git Bash on Windows.

**Spec:** `docs/superpowers/specs/2026-10-03-classify-call-type-lambda-design.md`

## Global Constraints

- **Python and shell**
  - `PY=.venv/Scripts/python`.
  - Run from the repo root in Git Bash, and add `</dev/null` to every `$PY` command.
  - Use `"$BASH"`, not plain `bash`.
- **Git**
  - Never run `git commit` or `git add`.
  - Never stage `infra-cdk/config.yaml`, `frontend/public/aws-exports.json` or `frontend/.env`.
  - No push and no merge.
  - The working tree already holds the uncommitted `transaction_fraud_detection` and `explain_transaction` work: their tool and test folders, plans and specs, their §7.5 and §7.6 hunks in `docs/LEDGERLENS_PRODUCT_DESIGN.md`, and their hunks in both `infra-cdk` files. Leave all of it as it is.
- **Names**
  - Asset folder: `gateway/tools/classify_call_type/`
  - Package: `classify_call_type_lambda`
  - Handler string: `classify_call_type_lambda/delivery/handler.handler`
  - Lambda: `ledgerlens-classify-call-type`
  - Tests: `tests/unit/classify_call_type/`
  - Queries: `call_reason_transactions`, `call_reason_cards`, `call_reason_cases`, `call_reason_app_events`
  - Keep the specific names `database_repository` and `query_provider`. Never use a generic `repository` or `queries`.
- **Copy rule**
  - Copied files only change `get_session_context` → `classify_call_type`.
  - The builder also changes `GetSessionContextUseCase` → `ClassifyCallTypeUseCase` and drops `max_rows=` (ruling 10).
  - Never copy `__pycache__`. Never import from another tool's folder.
- **Isolation grep:** `grep -rnE "(get_session_context|list_credit_cards|list_card_transactions|transaction_fraud_detection|explain_transaction)_lambda" gateway/tools/classify_call_type tests/unit/classify_call_type` must print nothing. Bare tool names may appear in message text, docstrings and paths.
- **SQL**
  - `is_fraud` appears in no SQL file, comments included.
  - `fraud_score` appears only in `call_reason_transactions.sql`.
  - No `%` appears except in placeholders, comments included: write "40 percent", never the sign.
  - No `SET` statement.
  - UTF-8, NFC, no BOM. Write the files with the Write tool, never with PowerShell.
  - Every SQL file gets the header given in Task 6. The copied card and case bodies drop `LIMIT %(limit)s`.
- **Exact values:** the weights, windows, messages, `tool_spec.json`, SQL and evidence keys are given in full in the tasks below, copied from spec §3.1, §5, §6 and §8. Use them verbatim.
  - Unexpected-error message: `Unexpected internal error ranking call reasons. Greet the customer and ask how you can help.`
  - Handler success log line: `"%s returned reasons=%s (unavailable=%s)"`. It never logs evidence, confidences, ids or scores.
- **Deploy is deferred.** It runs in one joint deploy with `transaction_fraud_detection` and `explain_transaction`. Don't run Task 12 during this plan.
- **Suite command** (the ignores keep duckdb-only data-load tests out):

  ```bash
  .venv/Scripts/python -m pytest tests/unit -q -p no:cacheprovider --ignore=tests/unit/test_data_load_cli.py --ignore=tests/unit/test_data_load_curate.py --ignore=tests/unit/test_data_load_curate_rules.py --ignore=tests/unit/test_data_load_curate_select.py --ignore=tests/unit/test_data_load_ddl.py --ignore=tests/unit/test_data_load_repair.py --ignore=tests/unit/test_data_load_transform.py --ignore=tests/unit/test_dsql_read_check.py -k "not test_dsql_driver_imports" </dev/null
  ```

  The baseline before this plan (with fraud and explain built) is `1491 passed, 1 deselected`.

### Plan rulings on the spec
1. **`days_left`** needs `as_of`'s date, but the presenter only gets the classification. **`CallClassification` gets a third field, `as_of_date: date`**: the date of `as_of` as naive UTC, the same date detection uses. `days_left = (expiration_date - as_of_date).days`. It is `None` when the expiration date is NULL.
2. **`confidence`** is presented as `float(ranked.confidence)`, where the confidence is a Decimal quantized to 2 places. stdlib `json` writes `Decimal("0.60")` as `0.6`, and that's fine. No custom encoder, no strings. Tests compare floats (`== 0.6`), never JSON text.
3. **Decimal age:** `_seconds(delta) = Decimal(delta.days * 86400 + delta.seconds) + Decimal(delta.microseconds) / 1_000_000`. Never use `total_seconds()`, which returns a float.
   - Half-up is pinned where it differs from half-even: DECLINED 8.5 h old scores 76.5, which gives 0.77.
   - P07's charge (2026-05-31 06:09:15 to 2026-06-17 23:59:59 = 17.7436 days) scores 77.2564, which gives 0.77.
4. **Tie between cases:** spec §3.2 is read literally. Cases have no decay and no event time, so equal-weight cases tie on the **lowest `complaint_id`**. The §6.3 SQL sort (breached first, then newest) only orders the rows, and Python decides. If P08 has several open, non-breached cases, this rule decides its acceptance `ref_id` (see Task 12).
5. **Ranking weight** is the candidate's effective weight:
   - 75 for a breached case, 60 for any other case;
   - otherwise `REASON_RULES[reason].weight`.

   `REASON_RULES[OPEN_CASE_FOLLOWUP].weight` is 60, and `OPEN_CASE_BREACHED_WEIGHT = Decimal("75")` is a separate constant.
6. **`unavailable`** is in `CallReason` enum order, not source order. A test fails transactions and cards together, so `CARD_NOT_ACTIVE` must land between `REVERSED_TRANSACTION` and `FOREIGN_TRANSACTION`.
7. **Mapping errors count as failures:**
   - A `KeyError`, `TypeError` or `ValueError` while mapping a source's rows makes that source unavailable, exactly like a `DataAccessError`.
   - Four sources failing on bad rows give `CallReasonLookupError`.
   - The required, non-NULL columns are `transaction_id` (transactions), `card_last4` (cards only), `complaint_id` (cases) and `event_id` (app events). A NULL there is a bad row. A transaction's `card_last4` is nullable (`str | None`), like the spec's §3.4 entity.
8. **The 201-row cap:**
   - More than 200 transaction rows logs a warning.
   - The use case then ranks **every row that came back** (all 201). It doesn't truncate to 200.
   - The SQL orders newest first, so whatever the cap drops is the oldest.
9. **Window edges:** Python windows are inclusive on both ends (`as_of - window <= t <= as_of`), as in spec §3.1. The §6.4 app-events SQL is kept verbatim, with `event_date > as_of - 24h`, which excludes the exact 24 h instant. The Python 24 h boundary test therefore covers a row that SQL never returns. That's harmless, and the SQL isn't changed.
10. **Builder:** after the sed copy, remove `max_rows=settings.max_rows` from the constructor call. Leaving it in raises `TypeError` at import, so every cold start would crash. The settings still parse `MAX_ROWS`.
11. **Blank countries:** FOREIGN by country needs both folded countries to be non-empty. `"  "` folds to `""` and is treated like NULL, so it is never foreign.
12. **Immutable tables:** `REASON_RULES` and `SOURCE_REASONS` are wrapped in `types.MappingProxyType`, so runtime code can't edit the pinned weights (explain's deferred minor T3).

## Review Focus
1. **An aware non-UTC `as_of`** (for example −05:00) with a decline exactly 72 h before it, measured in UTC. It must be included, and every query must get the naive-UTC instant. *Pinned by Task 5, `test_non_utc_as_of_is_converted_before_the_window_check`.*
2. **One approved Brazilian charge scored 62 in the last 72 h.** It must appear twice in the ranking, as `FRAUD_SUSPECTED` and `FOREIGN_TRANSACTION`, with the same `ref_id`. A top-3 cut must drop by score, not by charge. *Pinned by Task 4, `test_one_charge_can_be_two_reasons` and `test_only_the_top_limit_are_kept`.*
3. **A `Blocked` card that is also 180 days past due and expiring.** It must give `CARD_NOT_ACTIVE` only. A `Closed` card gives nothing. *Pinned by Task 4, `test_card_rules`.*
4. **An approved charge with a NULL `fraud_score`.** It must give no fraud reason, but it can still be `FOREIGN_TRANSACTION`. *Pinned by Task 4, `test_transaction_rules`.*
5. **A card expiring today.** It must give `CARD_EXPIRING` with `days_left: 0`, while one expiring yesterday gives nothing. *Pinned by Task 4, `test_card_rules`, and Task 7, `test_card_expiring_days_left`.*

## File map
| Path | Task |
|---|---|
| copied layers, `requirements.txt`, `__init__`s, `conftest.py`, `fakes.py`, 5 copied adapter tests | 1 |
| `domain/errors.py` + `test_errors.py` | 2 |
| `domain/value_objects/{fraud_bands,call_reasons,text_folding}.py` + `test_call_reasons.py`, `test_text_folding.py` | 3 |
| `domain/entities/{candidates,call_classification}.py`, `domain/services/reason_ranking.py` + `test_reason_ranking.py` | 4 |
| `application/use_cases/classify_call_type.py` + `test_classify_call_type_use_case.py` | 5 |
| `queries/postgresql/*.sql` (4 files), `tool_spec.json` + `test_query_contracts.py` | 6 |
| `delivery/presenters/call_classification.py` + `test_call_classification_presenter.py` | 7 |
| `delivery/dependencies/dependencies_builder.py` + `test_delivery_wiring.py` | 8 |
| `delivery/handler.py` + `test_classify_call_type_handler.py` | 9 |
| `infra-cdk/lib/data-construct.ts`, `infra-cdk/test/data-construct.test.ts` | 10 |
| `docs/LEDGERLENS_PRODUCT_DESIGN.md` §7.2 (CRLF) + full suite | 11 |
| joint deploy + acceptance (deferred) | 12 |

All production paths below are relative to `gateway/tools/classify_call_type/classify_call_type_lambda/` unless they start with `gateway/`, `tests/`, `infra-cdk/` or `docs/`.

---

### Task 1: Copy the shared layers into `classify_call_type`

**Files:**
- Create (copied): `gateway/tools/classify_call_type/requirements.txt`
- Create (copied): the 14 `__init__.py` files under `gateway/tools/classify_call_type/classify_call_type_lambda/`
- Create: `domain/value_objects/__init__.py`, `domain/services/__init__.py`, and the folder `queries/postgresql/`
- Create (copied): `application/ports/{database_repository,query_provider,errors}.py`, `infrastructure/queries/file_query_provider.py`, `infrastructure/repositories/dsql_repository.py`, `utils/connectors/{base,dsql}.py`, `delivery/settings.py`
- Create: `tests/unit/classify_call_type/__init__.py` (empty), `conftest.py`, `fakes.py`
- Create (copied): `tests/unit/classify_call_type/test_{settings,file_query_provider,dsql_repository,psycopg_connector,dsql_connector}.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces (all under `classify_call_type_lambda`):
  - `application.ports.database_repository.DatabaseRepository` with `execute_query(query: str, params: Mapping[str, object]) -> list[dict[str, Any]]`
  - `application.ports.query_provider.QueryProvider` with `get(name: str) -> str`
  - `application.ports.errors`: `DataAccessError`, `DataSourceConnectionError`, `QueryExecutionError`, `QueryLimitExceededError`, `QueryNotFoundError` (each takes one message string)
  - `infrastructure.queries.file_query_provider.FileQueryProvider(directory: Path)`
  - `infrastructure.repositories.dsql_repository.DsqlRepository(connector)`
  - `utils.connectors.base.PsycopgConnector`, `utils.connectors.dsql.DsqlConnector`
  - `delivery.settings`: `ConfigurationError`, `DatabaseEngine`, `DatabaseSettings`, `DsqlSettings`, `ClockSettings` (`.now() -> datetime`)
- Produces in `tests/unit/classify_call_type/fakes.py`:
  - Constants:
    - `CUSTOMER_ID = "CLI-EX6BOAOEFZHQ"`, `TRANSACTION_ID = "TRX-23BIJAU4GL46ATPW9STY"`, `CHARGE_DATE = datetime(2026, 5, 31, 6, 9, 15)`
    - `AS_OF = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)`, `AS_OF_SQL = datetime(2026, 6, 17, 23, 59, 59)`
    - `QUERY_NAMES = ("call_reason_transactions", "call_reason_cards", "call_reason_cases", "call_reason_app_events")`
    - `Outcome = list[dict[str, Any]] | Exception`
  - `FakeQueryProvider(queries: Mapping[str, str] | None = None)`: by default it serves each query name as its own SQL text. Attributes `.queries`, `.requested`.
  - `FakeClassifyRepository(responses: Mapping[str, Outcome] | None = None)`: answers by SQL text (= query name). A missing name returns `[]`. Attributes `.responses`, `.calls: list[tuple[str, dict[str, object]]]`; property `.queries: list[str]`.
  - Row builders, each taking `**overrides`: `make_transaction_row` (alias `make_row`), `make_card_row`, `make_case_row`, `make_app_event_row`.
  - `classify_responses(**overrides: Outcome) -> dict[str, Outcome]`: one transaction row and one card row, and `[]` for cases and app events.
  - `make_any_row() -> dict[str, Any]`: the four rows merged. Use it over `FakeConnector`, which serves the same rows to every query.
  - Copied unchanged: `FakeCursor`, `FakeConnection`, `FakeConnector(*outcomes, max_age=None, clock=time.monotonic)`, `FakeClock`, `FakeDsqlTokenClient`.

- [ ] **Step 1: Copy the production files**

```bash
SRC=gateway/tools/get_session_context
DST=gateway/tools/classify_call_type
mkdir -p "$DST"
sed 's/get_session_context/classify_call_type/g' "$SRC/requirements.txt" > "$DST/requirements.txt"
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
  mkdir -p "$DST/classify_call_type_lambda/$(dirname "$f")"
  sed 's/get_session_context/classify_call_type/g' \
    "$SRC/get_session_context_lambda/$f" > "$DST/classify_call_type_lambda/$f"
done
mkdir -p "$DST/classify_call_type_lambda/domain/value_objects"
mkdir -p "$DST/classify_call_type_lambda/domain/services"
mkdir -p "$DST/classify_call_type_lambda/queries/postgresql"
printf '%s\n' '"""Value objects: fraud bands, the call-reason taxonomy and text folding."""' \
  > "$DST/classify_call_type_lambda/domain/value_objects/__init__.py"
printf '%s\n' '"""Domain services: detect, score and rank call reasons. No I/O."""' \
  > "$DST/classify_call_type_lambda/domain/services/__init__.py"
printf '%s\n' '"""Domain layer: value objects, entities, services and agent-facing errors. No I/O."""' \
  > "$DST/classify_call_type_lambda/domain/__init__.py"
```

`get_session_context`'s domain has no `value_objects/` or `services/` folder, so the loop can't copy them. That's why they're written here, and why the domain docstring is rewritten to mention them.

Check the docstrings:

```bash
cat gateway/tools/classify_call_type/classify_call_type_lambda/__init__.py gateway/tools/classify_call_type/classify_call_type_lambda/application/use_cases/__init__.py
head -1 gateway/tools/classify_call_type/requirements.txt
find gateway/tools/classify_call_type -name __pycache__
```

Expected:
```text
"""The classify_call_type Gateway tool Lambda, in hexagonal layers."""
"""Use case of the classify_call_type tool."""
# Runtime dependencies for the classify_call_type Lambda.
```
and `find` prints nothing.

- [ ] **Step 2: Create the test package**

`tests/unit/classify_call_type/__init__.py` is an empty file.

`tests/unit/classify_call_type/conftest.py`:

```python
"""Pytest setup for classify_call_type: make its Lambda package importable.

The ``classify_call_type_lambda`` package lives in the Lambda asset root
``gateway/tools/classify_call_type``, so that folder is put on ``sys.path``
exactly as the Lambda runtime does.
"""

import sys
from pathlib import Path

_ASSET_ROOT = (
    Path(__file__).resolve().parents[3] / "gateway" / "tools" / "classify_call_type"
)

if str(_ASSET_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASSET_ROOT))
```

- [ ] **Step 3: Create `fakes.py`**

Copy it with sed first:

```bash
sed 's/get_session_context/classify_call_type/g' tests/unit/get_session_context/fakes.py > tests/unit/classify_call_type/fakes.py
```

Then replace everything from the top of the new file down to, but not including, the line `class FakeCursor:` with this block. Keep everything from `class FakeCursor:` to the end of the file exactly as copied.

```python
"""Test doubles and builders for the classify_call_type tests."""

import time
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Final

from classify_call_type_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from classify_call_type_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryNotFoundError,
)
from classify_call_type_lambda.application.ports.query_provider import QueryProvider
from classify_call_type_lambda.utils.connectors.base import PsycopgConnector

# Customer P07 of the curated personas and its flagged charge (spec section 1).
CUSTOMER_ID: Final = "CLI-EX6BOAOEFZHQ"
TRANSACTION_ID: Final = "TRX-23BIJAU4GL46ATPW9STY"
CHARGE_DATE: Final = datetime(2026, 5, 31, 6, 9, 15)
# The deployed AS_OF, and what the SQL receives: the same instant as naive UTC.
AS_OF: Final = datetime(2026, 6, 17, 23, 59, 59, tzinfo=timezone.utc)
AS_OF_SQL: Final = datetime(2026, 6, 17, 23, 59, 59)

# The four candidate queries, in the order they run (Source order).
QUERY_NAMES: Final = (
    "call_reason_transactions",
    "call_reason_cards",
    "call_reason_cases",
    "call_reason_app_events",
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


class FakeClassifyRepository(DatabaseRepository):
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
    """Build a call_reason_transactions row as psycopg's dict_row returns it.

    P07's charge from the spec's output example: approved, USD on a USD card, in
    the customer's home country. The score is any value above 50 (the fraud band);
    the stored one isn't needed by the tests.
    """
    row: dict[str, Any] = {
        "transaction_id": TRANSACTION_ID,
        "transaction_date": CHARGE_DATE,
        "card_last4": "4497",
        "card_currency": "USD",
        "merchant_name": "Estación de Servicio",
        "amount": Decimal("288.69"),
        "currency": "USD",
        "transaction_status": "Approved",
        "response_code": "00",
        "transaction_country": "México",
        "fraud_score": Decimal("62.00"),
        "home_country": "México",
    }
    row.update(overrides)
    return row


# The copied repository tests build rows with make_row.
make_row = make_transaction_row


def make_card_row(**overrides: Any) -> dict[str, Any]:
    """Build a call_reason_cards row: an active card in good standing, no reason."""
    row: dict[str, Any] = {
        "card_last4": "4497",
        "product_status": "Active",
        "expiration_date": date(2029, 8, 31),
        "days_past_due": 0,
    }
    row.update(overrides)
    return row


def make_case_row(**overrides: Any) -> dict[str, Any]:
    """Build a call_reason_cases row: P08's open claim, sla_breached NULL."""
    row: dict[str, Any] = {
        "complaint_id": "CMP-FHCLR8TGWMBD0YFOCLYS",
        "case_type": "Claim",
        "category": "Cards",
        "subcategory": "Unrecognized charge",
        "status": "In Progress",
        "sla_breached": None,
        "days_open": 12,
    }
    row.update(overrides)
    return row


def make_app_event_row(**overrides: Any) -> dict[str, Any]:
    """Build a call_reason_app_events row: an app error 2 hours before AS_OF."""
    row: dict[str, Any] = {
        "event_id": "EVT-0001",
        "event_date": AS_OF_SQL - timedelta(hours=2),
        "page_title": "Pagar Servicios",
        "action": "submit_payment",
    }
    row.update(overrides)
    return row


def classify_responses(**overrides: Outcome) -> dict[str, Outcome]:
    """Return P07-like responses, keyed by query name.

    One flagged charge and one card in good standing; no case and no app error.
    Overrides replace a query's outcome.
    """
    responses: dict[str, Outcome] = {
        "call_reason_transactions": [make_transaction_row()],
        "call_reason_cards": [make_card_row()],
        "call_reason_cases": [],
        "call_reason_app_events": [],
    }
    responses.update(overrides)
    return responses


def make_any_row() -> dict[str, Any]:
    """Build one row that every query can map.

    FakeConnector serves the same rows to every query, so end-to-end tests over
    real adapters need a row with every query's columns. The transaction and card
    rows share only card_last4, and both builders give it the same value ("4497").
    Ranked, the row gives FRAUD_SUSPECTED 0.77, OPEN_CASE_FOLLOWUP 0.60 and
    FAILED_APP_ACTION 0.58.
    """
    return {
        **make_transaction_row(),
        **make_card_row(),
        **make_case_row(),
        **make_app_event_row(),
    }
```

The copied tail decides which imports the header needs. If ruff reports an unused import here, remove only that import. If it reports an undefined name (F821), add that import back exactly as the get_session_context header has it.

- [ ] **Step 4: Copy the adapter tests**

```bash
for t in test_settings test_file_query_provider test_dsql_repository test_psycopg_connector test_dsql_connector; do
  sed 's/get_session_context/classify_call_type/g' tests/unit/get_session_context/$t.py > tests/unit/classify_call_type/$t.py
done
```

- [ ] **Step 5: Run the copied tests**

Run: `$PY -m pytest tests/unit/classify_call_type -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: all pass, 0 failed. These tests cover copied code, so they pass at once. They prove the copy, not new behaviour. If a copied repository test fails because it reads a column `make_row` doesn't have, read that test: it must only need *a* row, so pass the column it reads as an override in that one test and record a ruling.

- [ ] **Step 6: Check isolation and lint**

```bash
grep -rnE "(get_session_context|list_credit_cards|list_card_transactions|transaction_fraud_detection|explain_transaction)_lambda" gateway/tools/classify_call_type tests/unit/classify_call_type
grep -rn "get_session_context" gateway/tools/classify_call_type tests/unit/classify_call_type
$PY -m ruff format --check gateway/tools/classify_call_type tests/unit/classify_call_type </dev/null
$PY -m ruff check gateway/tools/classify_call_type tests/unit/classify_call_type </dev/null
```

Expected: both greps print nothing, and both ruff commands are clean. If `ruff format --check` only reports reflowed lines in the copied files (the new package name is longer), run `$PY -m ruff format gateway/tools/classify_call_type tests/unit/classify_call_type </dev/null` once and re-check.

---

### Task 2: Domain errors

**Files:**
- Create: `domain/errors.py`
- Test: `tests/unit/classify_call_type/test_errors.py`

**Interfaces:**
- Consumes: `application.ports.errors` (Task 1).
- Produces, in `classify_call_type_lambda.domain.errors`:
  - `DomainError(message)` with `.message`;
  - `InvalidInputError(field, reason)` with `.field` and `.reason`;
  - `DataSourceUnavailableError()` and `CallReasonLookupError()`, each with a class-level `MESSAGE`.

- [ ] **Step 1: Write the failing test**

`tests/unit/classify_call_type/test_errors.py`:

```python
"""Tests for domain and port error definitions."""

import classify_call_type_lambda.domain.errors as errors_module
import pytest
from classify_call_type_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
    QueryNotFoundError,
)
from classify_call_type_lambda.domain.errors import (
    CallReasonLookupError,
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
            "Call reasons are temporarily unavailable. Greet the customer and ask "
            "how you can help.",
        ),
        (
            CallReasonLookupError,
            "Call reasons can't be computed right now due to an internal error. "
            "Don't retry; greet the customer and ask how you can help.",
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
    [
        "ExplainLookupError",
        "TransactionNotFoundError",
        "FraudCheckLookupError",
        "SessionContextLookupError",
        "CardNotFoundError",
    ],
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

- [ ] **Step 2: Run it to verify it fails**

Run: `$PY -m pytest tests/unit/classify_call_type/test_errors.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: a collection error, `ModuleNotFoundError: No module named 'classify_call_type_lambda.domain.errors'`.

- [ ] **Step 3: Write `domain/errors.py`**

The structure follows explain_transaction's `errors.py`. Don't sed-copy get_session_context's file: it defines classes this tool must not have.

```python
"""Domain errors: the only failures the agent is allowed to see.

Each message says what went wrong and what the agent should do next. Messages
never contain SQL, hostnames, driver output, scores or other internal details.
A failed candidate query is not an error: its reasons are listed in
``unavailable``. Only a failure of all four queries is.
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


class DataSourceUnavailableError(_FixedMessageError):
    """All four queries failed and at least one couldn't connect."""

    MESSAGE: ClassVar[str] = (
        "Call reasons are temporarily unavailable. Greet the customer and ask "
        "how you can help."
    )


class CallReasonLookupError(_FixedMessageError):
    """All four queries failed, none of them on the connection."""

    MESSAGE: ClassVar[str] = (
        "Call reasons can't be computed right now due to an internal error. "
        "Don't retry; greet the customer and ask how you can help."
    )
```

- [ ] **Step 4: Run it to verify it passes**

Run: `$PY -m pytest tests/unit/classify_call_type/test_errors.py -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: `12 passed`

- [ ] **Step 5: Lint**

Run: `$PY -m ruff format --check gateway/tools/classify_call_type tests/unit/classify_call_type </dev/null && $PY -m ruff check gateway/tools/classify_call_type tests/unit/classify_call_type </dev/null`
Expected: clean.

---

### Task 3: Value objects (fraud bands, call reasons, text folding)

**Files:**
- Create: `domain/value_objects/fraud_bands.py`, `domain/value_objects/call_reasons.py`, `domain/value_objects/text_folding.py`
- Test: `tests/unit/classify_call_type/test_call_reasons.py`, `tests/unit/classify_call_type/test_text_folding.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `fraud_bands`: `FRAUD_ABOVE: Final = Decimal("50")`, `REVIEW_ABOVE: Final = Decimal("30")`
  - `call_reasons`:
    - `CallReason(StrEnum)`: 11 members whose value equals the name, in §3.1 order.
    - `Decay(StrEnum)`: `PER_HOUR = "per_hour"`, `PER_DAY = "per_day"`, `NONE = "none"`.
    - `Source(StrEnum)`: `TRANSACTIONS = "transactions"`, `CARDS = "cards"`, `CASES = "cases"`, `APP_EVENTS = "app_events"`, in that order.
    - `ReasonRule` (frozen dataclass): `weight: Decimal`, `window: timedelta | None`, `decay: Decay`.
    - `REASON_RULES: Mapping[CallReason, ReasonRule]`, `OPEN_CASE_BREACHED_WEIGHT: Final = Decimal("75")`, `SOURCE_REASONS: Mapping[Source, tuple[CallReason, ...]]`. Both mappings are `MappingProxyType`.
  - `text_folding`: `fold_text(value: str | None) -> str | None`

- [ ] **Step 1: Write the failing tests**

`tests/unit/classify_call_type/test_call_reasons.py`:

```python
"""Tests for the call-reason taxonomy, its pinned rules and the fraud bands."""

from datetime import timedelta
from decimal import Decimal
from types import MappingProxyType

import pytest
from classify_call_type_lambda.domain.value_objects.call_reasons import (
    OPEN_CASE_BREACHED_WEIGHT,
    REASON_RULES,
    SOURCE_REASONS,
    CallReason,
    Decay,
    ReasonRule,
    Source,
)
from classify_call_type_lambda.domain.value_objects.fraud_bands import (
    FRAUD_ABOVE,
    REVIEW_ABOVE,
)

pytestmark = pytest.mark.unit

_HOURS_72 = timedelta(hours=72)
_DAYS_30 = timedelta(days=30)


def test_enum_order_is_the_final_tie_break() -> None:
    assert [reason.value for reason in CallReason] == [
        "FRAUD_SUSPECTED",
        "DECLINED_TRANSACTION",
        "UNRECOGNIZED_CHARGE_REVIEW",
        "OPEN_CASE_FOLLOWUP",
        "PENDING_TRANSACTION",
        "REVERSED_TRANSACTION",
        "CARD_NOT_ACTIVE",
        "FAILED_APP_ACTION",
        "FOREIGN_TRANSACTION",
        "PAYMENT_OVERDUE",
        "CARD_EXPIRING",
    ]


@pytest.mark.parametrize(
    ("reason", "weight", "window", "decay"),
    [
        (CallReason.FRAUD_SUSPECTED, "95", _DAYS_30, Decay.PER_DAY),
        (CallReason.DECLINED_TRANSACTION, "85", _HOURS_72, Decay.PER_HOUR),
        (CallReason.UNRECOGNIZED_CHARGE_REVIEW, "70", _DAYS_30, Decay.PER_DAY),
        (CallReason.OPEN_CASE_FOLLOWUP, "60", None, Decay.NONE),
        (CallReason.PENDING_TRANSACTION, "65", _HOURS_72, Decay.PER_HOUR),
        (CallReason.REVERSED_TRANSACTION, "65", _HOURS_72, Decay.PER_HOUR),
        (CallReason.CARD_NOT_ACTIVE, "60", None, Decay.NONE),
        (CallReason.FAILED_APP_ACTION, "60", timedelta(hours=24), Decay.PER_HOUR),
        (CallReason.FOREIGN_TRANSACTION, "55", _HOURS_72, Decay.PER_HOUR),
        (CallReason.PAYMENT_OVERDUE, "50", None, Decay.NONE),
        (CallReason.CARD_EXPIRING, "35", None, Decay.NONE),
    ],
)
def test_each_reason_rule_is_pinned(
    reason: CallReason, weight: str, window: timedelta | None, decay: Decay
) -> None:
    assert REASON_RULES[reason] == ReasonRule(
        weight=Decimal(weight), window=window, decay=decay
    )


def test_every_reason_has_a_rule() -> None:
    assert set(REASON_RULES) == set(CallReason)


def test_a_breached_case_weighs_75() -> None:
    assert OPEN_CASE_BREACHED_WEIGHT == Decimal("75")


def test_sources_run_in_this_order() -> None:
    assert [source.value for source in Source] == [
        "transactions",
        "cards",
        "cases",
        "app_events",
    ]


def test_source_reasons_are_pinned() -> None:
    assert dict(SOURCE_REASONS) == {
        Source.TRANSACTIONS: (
            CallReason.FRAUD_SUSPECTED,
            CallReason.DECLINED_TRANSACTION,
            CallReason.UNRECOGNIZED_CHARGE_REVIEW,
            CallReason.PENDING_TRANSACTION,
            CallReason.REVERSED_TRANSACTION,
            CallReason.FOREIGN_TRANSACTION,
        ),
        Source.CARDS: (
            CallReason.CARD_NOT_ACTIVE,
            CallReason.PAYMENT_OVERDUE,
            CallReason.CARD_EXPIRING,
        ),
        Source.CASES: (CallReason.OPEN_CASE_FOLLOWUP,),
        Source.APP_EVENTS: (CallReason.FAILED_APP_ACTION,),
    }


def test_every_reason_comes_from_exactly_one_source() -> None:
    fed = [reason for reasons in SOURCE_REASONS.values() for reason in reasons]

    assert sorted(fed) == sorted(CallReason)
    assert len(fed) == len(set(fed))


def test_tables_are_read_only() -> None:
    assert isinstance(REASON_RULES, MappingProxyType)
    assert isinstance(SOURCE_REASONS, MappingProxyType)
    with pytest.raises(TypeError):
        REASON_RULES[CallReason.FRAUD_SUSPECTED] = ReasonRule(  # type: ignore[index]
            weight=Decimal("1"), window=None, decay=Decay.NONE
        )


def test_fraud_bands_match_transaction_fraud_detection() -> None:
    assert FRAUD_ABOVE == Decimal("50")
    assert REVIEW_ABOVE == Decimal("30")
```

`tests/unit/classify_call_type/test_text_folding.py`:

```python
"""Tests for fold_text, the country comparison of FOREIGN_TRANSACTION."""

import pytest
from classify_call_type_lambda.domain.value_objects.text_folding import fold_text

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("México", "mexico"),
        (" MEXICO ", "mexico"),
        ("Perú", "peru"),
        ("Brasil", "brasil"),
        ("  ", ""),
        ("", ""),
        (None, None),
    ],
)
def test_fold_text(value: str | None, expected: str | None) -> None:
    assert fold_text(value) == expected


def test_accented_and_plain_names_fold_equal() -> None:
    assert fold_text("México") == fold_text("Mexico")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/unit/classify_call_type/test_call_reasons.py tests/unit/classify_call_type/test_text_folding.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: 2 collection errors, `ModuleNotFoundError` for `call_reasons` and `text_folding`.

- [ ] **Step 3: Write the three modules**

`domain/value_objects/fraud_bands.py` is written fresh with only the two constants:

```python
"""Fraud-score bands, copied from transaction_fraud_detection.

The score is 0 to 100. Above FRAUD_ABOVE is FRAUD_SUSPECTED; above REVIEW_ABOVE
and up to FRAUD_ABOVE is UNRECOGNIZED_CHARGE_REVIEW. transaction_fraud_detection
keeps its own copy (tools never share code). Both tools' tests pin 50 and 30, so
a change to one shows up in the other's tests.
"""

from decimal import Decimal
from typing import Final

FRAUD_ABOVE: Final = Decimal("50")
REVIEW_ABOVE: Final = Decimal("30")
```

`domain/value_objects/call_reasons.py`:

```python
"""The call-reason taxonomy: reasons, their pinned rules and the query feeding each.

The weights are hand-set, not learned (DEC-10). They are pinned in tests and in
the spec (section 3.1). CallReason's order is the final ranking tie-break.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class CallReason(StrEnum):
    """A likely reason for the call; the order is the final tie-break."""

    FRAUD_SUSPECTED = "FRAUD_SUSPECTED"
    DECLINED_TRANSACTION = "DECLINED_TRANSACTION"
    UNRECOGNIZED_CHARGE_REVIEW = "UNRECOGNIZED_CHARGE_REVIEW"
    OPEN_CASE_FOLLOWUP = "OPEN_CASE_FOLLOWUP"
    PENDING_TRANSACTION = "PENDING_TRANSACTION"
    REVERSED_TRANSACTION = "REVERSED_TRANSACTION"
    CARD_NOT_ACTIVE = "CARD_NOT_ACTIVE"
    FAILED_APP_ACTION = "FAILED_APP_ACTION"
    FOREIGN_TRANSACTION = "FOREIGN_TRANSACTION"
    PAYMENT_OVERDUE = "PAYMENT_OVERDUE"
    CARD_EXPIRING = "CARD_EXPIRING"


class Decay(StrEnum):
    """How a reason's score falls with the event's age."""

    PER_HOUR = "per_hour"
    PER_DAY = "per_day"
    NONE = "none"


class Source(StrEnum):
    """A candidate query; the use case runs them in this order."""

    TRANSACTIONS = "transactions"
    CARDS = "cards"
    CASES = "cases"
    APP_EVENTS = "app_events"


@dataclass(frozen=True)
class ReasonRule:
    """A reason's base weight, look-back window (None: no window) and decay."""

    weight: Decimal
    window: timedelta | None
    decay: Decay


_HOURS_24: Final = timedelta(hours=24)
_HOURS_72: Final = timedelta(hours=72)
_DAYS_30: Final = timedelta(days=30)

REASON_RULES: Final[Mapping[CallReason, ReasonRule]] = MappingProxyType(
    {
        CallReason.FRAUD_SUSPECTED: ReasonRule(
            Decimal("95"), _DAYS_30, Decay.PER_DAY
        ),
        CallReason.DECLINED_TRANSACTION: ReasonRule(
            Decimal("85"), _HOURS_72, Decay.PER_HOUR
        ),
        CallReason.UNRECOGNIZED_CHARGE_REVIEW: ReasonRule(
            Decimal("70"), _DAYS_30, Decay.PER_DAY
        ),
        # 60 for an open case; a breached one weighs OPEN_CASE_BREACHED_WEIGHT.
        CallReason.OPEN_CASE_FOLLOWUP: ReasonRule(Decimal("60"), None, Decay.NONE),
        CallReason.PENDING_TRANSACTION: ReasonRule(
            Decimal("65"), _HOURS_72, Decay.PER_HOUR
        ),
        CallReason.REVERSED_TRANSACTION: ReasonRule(
            Decimal("65"), _HOURS_72, Decay.PER_HOUR
        ),
        CallReason.CARD_NOT_ACTIVE: ReasonRule(Decimal("60"), None, Decay.NONE),
        CallReason.FAILED_APP_ACTION: ReasonRule(
            Decimal("60"), _HOURS_24, Decay.PER_HOUR
        ),
        CallReason.FOREIGN_TRANSACTION: ReasonRule(
            Decimal("55"), _HOURS_72, Decay.PER_HOUR
        ),
        CallReason.PAYMENT_OVERDUE: ReasonRule(Decimal("50"), None, Decay.NONE),
        CallReason.CARD_EXPIRING: ReasonRule(Decimal("35"), None, Decay.NONE),
    }
)

# Weight of an open case whose sla_breached is true; NULL counts as false (60).
OPEN_CASE_BREACHED_WEIGHT: Final = Decimal("75")

# The reasons each query feeds; a failed query makes exactly these unavailable.
SOURCE_REASONS: Final[Mapping[Source, tuple[CallReason, ...]]] = MappingProxyType(
    {
        Source.TRANSACTIONS: (
            CallReason.FRAUD_SUSPECTED,
            CallReason.DECLINED_TRANSACTION,
            CallReason.UNRECOGNIZED_CHARGE_REVIEW,
            CallReason.PENDING_TRANSACTION,
            CallReason.REVERSED_TRANSACTION,
            CallReason.FOREIGN_TRANSACTION,
        ),
        Source.CARDS: (
            CallReason.CARD_NOT_ACTIVE,
            CallReason.PAYMENT_OVERDUE,
            CallReason.CARD_EXPIRING,
        ),
        Source.CASES: (CallReason.OPEN_CASE_FOLLOWUP,),
        Source.APP_EVENTS: (CallReason.FAILED_APP_ACTION,),
    }
)
```

If `ruff format` lays out the `REASON_RULES` entries differently, accept its layout.

`domain/value_objects/text_folding.py` is explain's code with the docstring rewritten. Explain's docstring talks about its habit SQL, which this tool doesn't have.

```python
"""Fold text so country names compare equal regardless of accents, case or spaces."""

import unicodedata


def fold_text(value: str | None) -> str | None:
    """Return ``value`` without accents, case-folded and stripped; None stays None.

    "México" and " MEXICO " both fold to "mexico" (D21). FOREIGN_TRANSACTION
    compares the charge's country with the customer's home country this way.
    Copied from explain_transaction; tools never share code.
    """
    if value is None:
        return None
    decomposed = unicodedata.normalize("NFKD", value)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return plain.casefold().strip()
```

- [ ] **Step 4: Run them to verify they pass**

Run: `$PY -m pytest tests/unit/classify_call_type/test_call_reasons.py tests/unit/classify_call_type/test_text_folding.py -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: `27 passed`

- [ ] **Step 5: Lint and check the copied wording is gone**

Run: `$PY -m ruff format --check gateway/tools/classify_call_type tests/unit/classify_call_type </dev/null && $PY -m ruff check gateway/tools/classify_call_type tests/unit/classify_call_type </dev/null`
Expected: clean.
Run: `grep -rn "translate()\|habit" gateway/tools/classify_call_type`
Expected: nothing.

---

### Task 4: Entities and the `reason_ranking` service

**Files:**
- Create: `domain/entities/candidates.py`, `domain/entities/call_classification.py`, `domain/services/reason_ranking.py`
- Test: `tests/unit/classify_call_type/test_reason_ranking.py`

**Interfaces:**
- Consumes: Task 3 (`CallReason`, `Decay`, `REASON_RULES`, `OPEN_CASE_BREACHED_WEIGHT`, `FRAUD_ABOVE`, `REVIEW_ABOVE`, `fold_text`).
- Produces:
  - `domain.entities.candidates`, all frozen dataclasses:
    - `TransactionCandidate(transaction_id: str, transaction_date: datetime | None, card_last4: str | None, card_currency: str | None, merchant_name: str | None, amount: Decimal | None, currency: str | None, transaction_status: str | None, response_code: str | None, transaction_country: str | None, home_country: str | None, fraud_score: Decimal | None)`
    - `CardCandidate(card_last4: str, product_status: str | None, expiration_date: date | None, days_past_due: int | None)`
    - `CaseCandidate(complaint_id: str, case_type: str | None, category: str | None, subcategory: str | None, status: str | None, sla_breached: bool | None, days_open: int | None)`
    - `AppEventCandidate(event_id: str, event_date: datetime | None, page_title: str | None, action: str | None)`
  - `domain.entities.call_classification`:
    - `Candidate` (type alias for the union of the four);
    - `RankedReason(reason: CallReason, confidence: Decimal, ref_id: str, candidate: Candidate)`;
    - `CallClassification(reasons: tuple[RankedReason, ...], unavailable: tuple[CallReason, ...], as_of_date: date)` (ruling 1).
  - `domain.services.reason_ranking`. Every datetime is naive UTC.
    - `score(weight: Decimal, decay: Decay, event_time: datetime | None, as_of: datetime) -> Decimal`
    - `to_confidence(score: Decimal) -> Decimal`
    - `transaction_reasons(candidate: TransactionCandidate, as_of: datetime) -> tuple[CallReason, ...]`, in enum order
    - `card_reasons(candidate: CardCandidate, as_of_date: date) -> tuple[CallReason, ...]`
    - `rank(*, transactions: Sequence[TransactionCandidate], cards: Sequence[CardCandidate], cases: Sequence[CaseCandidate], app_events: Sequence[AppEventCandidate], as_of: datetime, limit: int) -> tuple[RankedReason, ...]`

- [ ] **Step 1: Write the failing test**

`tests/unit/classify_call_type/test_reason_ranking.py`:

```python
"""Tests for detecting, scoring and ranking call reasons (spec section 3)."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from classify_call_type_lambda.domain.entities.candidates import (
    AppEventCandidate,
    CardCandidate,
    CaseCandidate,
    TransactionCandidate,
)
from classify_call_type_lambda.domain.services.reason_ranking import (
    card_reasons,
    rank,
    score,
    to_confidence,
    transaction_reasons,
)
from classify_call_type_lambda.domain.value_objects.call_reasons import (
    CallReason,
    Decay,
)

from .fakes import AS_OF_SQL, CHARGE_DATE, TRANSACTION_ID

pytestmark = pytest.mark.unit

AS = AS_OF_SQL
TODAY = AS.date()
R = CallReason


def _tx(age: timedelta = timedelta(hours=1), **overrides: Any) -> TransactionCandidate:
    """An approved, domestic, unscored charge ``age`` before AS: no reason."""
    fields: dict[str, Any] = {
        "transaction_id": "TRX-A",
        "transaction_date": AS - age,
        "card_last4": "4497",
        "card_currency": "USD",
        "merchant_name": "Tienda",
        "amount": Decimal("10.00"),
        "currency": "USD",
        "transaction_status": "Approved",
        "response_code": "00",
        "transaction_country": "México",
        "home_country": "México",
        "fraud_score": None,
    }
    fields.update(overrides)
    return TransactionCandidate(**fields)


def _card(**overrides: Any) -> CardCandidate:
    """An active card in good standing, far from expiring: no reason."""
    fields: dict[str, Any] = {
        "card_last4": "4497",
        "product_status": "Active",
        "expiration_date": date(2029, 8, 31),
        "days_past_due": 0,
    }
    fields.update(overrides)
    return CardCandidate(**fields)


def _case(**overrides: Any) -> CaseCandidate:
    """An open case whose SLA isn't breached."""
    fields: dict[str, Any] = {
        "complaint_id": "CMP-A",
        "case_type": "Claim",
        "category": "Cards",
        "subcategory": "Unrecognized charge",
        "status": "In Progress",
        "sla_breached": False,
        "days_open": 12,
    }
    fields.update(overrides)
    return CaseCandidate(**fields)


def _event(age: timedelta = timedelta(hours=2), **overrides: Any) -> AppEventCandidate:
    """An app error ``age`` before AS."""
    fields: dict[str, Any] = {
        "event_id": "EVT-A",
        "event_date": AS - age,
        "page_title": "Pagar Servicios",
        "action": "submit_payment",
    }
    fields.update(overrides)
    return AppEventCandidate(**fields)


def _rank(
    transactions: tuple[TransactionCandidate, ...] = (),
    cards: tuple[CardCandidate, ...] = (),
    cases: tuple[CaseCandidate, ...] = (),
    app_events: tuple[AppEventCandidate, ...] = (),
    limit: int = 3,
) -> list[tuple[CallReason, Decimal, str]]:
    ranked = rank(
        transactions=transactions,
        cards=cards,
        cases=cases,
        app_events=app_events,
        as_of=AS,
        limit=limit,
    )
    return [(item.reason, item.confidence, item.ref_id) for item in ranked]


# --- score and confidence ---------------------------------------------------


def test_score_decays_one_point_per_hour() -> None:
    event = AS - timedelta(hours=5, minutes=34, seconds=48)  # 5.58 h (P01)

    assert score(Decimal("85"), Decay.PER_HOUR, event, AS) == Decimal("79.42")


def test_score_decays_one_point_per_day() -> None:
    event = AS - timedelta(days=3)

    assert score(Decimal("70"), Decay.PER_DAY, event, AS) == Decimal("67")


def test_p07_age_is_fractional_days() -> None:
    result = score(Decimal("95"), Decay.PER_DAY, CHARGE_DATE, AS)

    assert result.quantize(Decimal("0.0001")) == Decimal("77.2564")
    assert to_confidence(result) == Decimal("0.77")


def test_score_floors_at_40_percent_of_the_weight() -> None:
    event = AS - timedelta(hours=50)

    assert score(Decimal("65"), Decay.PER_HOUR, event, AS) == Decimal("26.0")


def test_a_future_event_counts_as_age_zero() -> None:
    event = AS + timedelta(hours=1)

    assert score(Decimal("85"), Decay.PER_HOUR, event, AS) == Decimal("85")


def test_no_decay_scores_the_weight() -> None:
    assert score(Decimal("60"), Decay.NONE, None, AS) == Decimal("60")


def test_a_decaying_reason_needs_an_event_time() -> None:
    with pytest.raises(ValueError, match="event time"):
        score(Decimal("85"), Decay.PER_HOUR, None, AS)


def test_half_up_rounding_differs_from_half_even() -> None:
    result = score(Decimal("85"), Decay.PER_HOUR, AS - timedelta(hours=8.5), AS)

    assert result == Decimal("76.5")
    assert to_confidence(result) == Decimal("0.77")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("76.5", "0.77"), ("77.2564", "0.77"), ("26", "0.26"), ("60", "0.60")],
)
def test_confidence_is_score_over_100_with_2_decimals(value: str, expected: str) -> None:
    confidence = to_confidence(Decimal(value))

    assert confidence == Decimal(expected)
    assert confidence.as_tuple().exponent == -2


# --- transaction rules ------------------------------------------------------

_H72 = timedelta(hours=72)
_D30 = timedelta(days=30)
_SECOND = timedelta(seconds=1)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param({"fraud_score": Decimal("62")}, (R.FRAUD_SUSPECTED,), id="fraud"),
        pytest.param({"fraud_score": Decimal("50.01")}, (R.FRAUD_SUSPECTED,), id="50.01"),
        pytest.param(
            {"fraud_score": Decimal("50.00")}, (R.UNRECOGNIZED_CHARGE_REVIEW,), id="50.00"
        ),
        pytest.param(
            {"fraud_score": Decimal("30.01")}, (R.UNRECOGNIZED_CHARGE_REVIEW,), id="30.01"
        ),
        pytest.param({"fraud_score": Decimal("30.00")}, (), id="30.00"),
        pytest.param({}, (), id="null-score-domestic"),
        pytest.param(
            {"transaction_country": "Brasil"},
            (R.FOREIGN_TRANSACTION,),
            id="null-score-abroad",
        ),
        pytest.param(
            {"transaction_status": "Declined", "fraud_score": Decimal("62")},
            (R.DECLINED_TRANSACTION,),
            id="declined-scored-62",
        ),
        pytest.param(
            {"transaction_status": "Pending"}, (R.PENDING_TRANSACTION,), id="pending"
        ),
        pytest.param(
            {"transaction_status": "Reversed"}, (R.REVERSED_TRANSACTION,), id="reversed"
        ),
        pytest.param({"transaction_status": None}, (), id="null-status"),
        pytest.param(
            {"transaction_status": "Declined", "age": _H72},
            (R.DECLINED_TRANSACTION,),
            id="declined-72h-in",
        ),
        pytest.param(
            {"transaction_status": "Declined", "age": _H72 + _SECOND},
            (),
            id="declined-72h-out",
        ),
        pytest.param(
            {"fraud_score": Decimal("62"), "age": _D30},
            (R.FRAUD_SUSPECTED,),
            id="fraud-30d-in",
        ),
        pytest.param(
            {"fraud_score": Decimal("62"), "age": _D30 + _SECOND}, (), id="fraud-30d-out"
        ),
        pytest.param(
            {"fraud_score": Decimal("62"), "transaction_country": "Brasil"},
            (R.FRAUD_SUSPECTED, R.FOREIGN_TRANSACTION),
            id="fraud-and-foreign",
        ),
        pytest.param(
            {
                "fraud_score": Decimal("62"),
                "transaction_country": "Brasil",
                "age": _H72 + _SECOND,
            },
            (R.FRAUD_SUSPECTED,),
            id="foreign-window-shorter",
        ),
        pytest.param({"transaction_country": "Mexico"}, (), id="folded-country"),
        pytest.param({"currency": "EUR"}, (R.FOREIGN_TRANSACTION,), id="currency"),
        pytest.param({"transaction_country": None}, (), id="null-country"),
        pytest.param(
            {"transaction_country": "Brasil", "home_country": None},
            (),
            id="null-home",
        ),
        pytest.param({"transaction_country": "  "}, (), id="blank-country"),
        pytest.param({"currency": None}, (), id="null-currency"),
        pytest.param(
            {"transaction_status": "Declined", "transaction_country": "Brasil"},
            (R.DECLINED_TRANSACTION,),
            id="declined-abroad",
        ),
        pytest.param(
            {"fraud_score": Decimal("62"), "transaction_date": None},
            (),
            id="null-date",
        ),
        pytest.param(
            {"transaction_status": "Declined", "age": -_SECOND}, (), id="future"
        ),
    ],
)
def test_transaction_rules(
    overrides: dict[str, Any], expected: tuple[CallReason, ...]
) -> None:
    age = overrides.pop("age", timedelta(hours=1))

    assert transaction_reasons(_tx(age, **overrides), AS) == expected


# --- card rules -------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param(
            {"product_status": "Blocked", "days_past_due": 180, "expiration_date": TODAY},
            (R.CARD_NOT_ACTIVE,),
            id="blocked-only",
        ),
        pytest.param(
            {"product_status": "Suspended"}, (R.CARD_NOT_ACTIVE,), id="suspended"
        ),
        pytest.param(
            {"product_status": "Closed", "days_past_due": 30, "expiration_date": TODAY},
            (),
            id="closed",
        ),
        pytest.param({}, (), id="good-standing"),
        pytest.param({"days_past_due": 5}, (R.PAYMENT_OVERDUE,), id="overdue"),
        pytest.param({"days_past_due": 0}, (), id="dpd-0"),
        pytest.param({"days_past_due": None}, (), id="dpd-null"),
        pytest.param({"expiration_date": TODAY}, (R.CARD_EXPIRING,), id="expires-today"),
        pytest.param(
            {"expiration_date": TODAY - timedelta(days=1)}, (), id="expired-yesterday"
        ),
        pytest.param(
            {"expiration_date": TODAY + timedelta(days=30)},
            (R.CARD_EXPIRING,),
            id="expires-in-30",
        ),
        pytest.param(
            {"expiration_date": TODAY + timedelta(days=31)}, (), id="expires-in-31"
        ),
        pytest.param({"expiration_date": None}, (), id="null-expiration"),
        pytest.param(
            {"days_past_due": 10, "expiration_date": TODAY + timedelta(days=3)},
            (R.PAYMENT_OVERDUE, R.CARD_EXPIRING),
            id="overdue-and-expiring",
        ),
        pytest.param({"product_status": None}, (), id="null-status"),
    ],
)
def test_card_rules(overrides: dict[str, Any], expected: tuple[CallReason, ...]) -> None:
    assert card_reasons(_card(**overrides), TODAY) == expected


# --- ranking ----------------------------------------------------------------


def test_empty_input_ranks_nothing() -> None:
    assert _rank() == []


def test_p07_charge_ranks_fraud_first_at_0_77() -> None:
    charge = _tx(
        transaction_id=TRANSACTION_ID,
        transaction_date=CHARGE_DATE,
        fraud_score=Decimal("62"),
    )

    ranked = rank(
        transactions=(charge,), cards=(), cases=(), app_events=(), as_of=AS, limit=3
    )

    assert len(ranked) == 1
    assert ranked[0].reason is R.FRAUD_SUSPECTED
    assert ranked[0].confidence == Decimal("0.77")
    assert ranked[0].ref_id == TRANSACTION_ID
    assert ranked[0].candidate is charge


def test_one_charge_can_be_two_reasons() -> None:
    charge = _tx(
        timedelta(hours=2), fraud_score=Decimal("62"), transaction_country="Brasil"
    )

    assert _rank(transactions=(charge,)) == [
        (R.FRAUD_SUSPECTED, Decimal("0.95"), "TRX-A"),
        (R.FOREIGN_TRANSACTION, Decimal("0.53"), "TRX-A"),
    ]


def test_only_the_top_limit_are_kept() -> None:
    brazil = _tx(
        timedelta(hours=2), fraud_score=Decimal("62"), transaction_country="Brasil"
    )
    declined = _tx(transaction_id="TRX-B", transaction_status="Declined")
    breached = _case(sla_breached=True)

    assert _rank(transactions=(brazil, declined), cases=(breached,)) == [
        (R.FRAUD_SUSPECTED, Decimal("0.95"), "TRX-A"),
        (R.DECLINED_TRANSACTION, Decimal("0.84"), "TRX-B"),
        (R.OPEN_CASE_FOLLOWUP, Decimal("0.75"), "CMP-A"),
    ]
    assert _rank(transactions=(brazil, declined), cases=(breached,), limit=1) == [
        (R.FRAUD_SUSPECTED, Decimal("0.95"), "TRX-A"),
    ]


def test_the_best_event_per_reason_has_the_highest_score() -> None:
    older = _tx(timedelta(hours=10), transaction_id="TRX-A", transaction_status="Declined")
    newer = _tx(timedelta(hours=2), transaction_id="TRX-B", transaction_status="Declined")

    assert _rank(transactions=(older, newer)) == [
        (R.DECLINED_TRANSACTION, Decimal("0.83"), "TRX-B"),
    ]


def test_tied_scores_go_to_the_newest_event() -> None:
    # Both are at the 40 percent floor (34).
    older = _tx(timedelta(hours=70), transaction_id="TRX-A", transaction_status="Declined")
    newer = _tx(timedelta(hours=60), transaction_id="TRX-B", transaction_status="Declined")

    assert _rank(transactions=(older, newer)) == [
        (R.DECLINED_TRANSACTION, Decimal("0.34"), "TRX-B"),
    ]


def test_tied_scores_and_times_go_to_the_lowest_ref_id() -> None:
    second = _tx(transaction_id="TRX-B", transaction_status="Declined")
    first = _tx(transaction_id="TRX-A", transaction_status="Declined")

    assert _rank(transactions=(second, first)) == [
        (R.DECLINED_TRANSACTION, Decimal("0.84"), "TRX-A"),
    ]


def test_state_reasons_and_cases_tie_on_the_lowest_ref_id() -> None:
    cards = (
        _card(card_last4="9999", product_status="Blocked"),
        _card(card_last4="1234", product_status="Blocked"),
    )
    cases = (_case(complaint_id="CMP-B"), _case(complaint_id="CMP-A"))

    assert _rank(cards=cards, cases=cases) == [
        (R.OPEN_CASE_FOLLOWUP, Decimal("0.60"), "CMP-A"),
        (R.CARD_NOT_ACTIVE, Decimal("0.60"), "1234"),
    ]


def test_a_breached_case_beats_a_lower_id() -> None:
    cases = (_case(complaint_id="CMP-A"), _case(complaint_id="CMP-B", sla_breached=True))

    assert _rank(cases=cases) == [(R.OPEN_CASE_FOLLOWUP, Decimal("0.75"), "CMP-B")]


def test_null_sla_breached_counts_as_not_breached() -> None:
    assert _rank(cases=(_case(sla_breached=None),)) == [
        (R.OPEN_CASE_FOLLOWUP, Decimal("0.60"), "CMP-A"),
    ]


def test_equal_scores_go_to_the_higher_weight() -> None:
    pending = _tx(timedelta(hours=5), transaction_status="Pending")  # 65 - 5 = 60

    assert _rank(transactions=(pending,), cases=(_case(),)) == [
        (R.PENDING_TRANSACTION, Decimal("0.60"), "TRX-A"),
        (R.OPEN_CASE_FOLLOWUP, Decimal("0.60"), "CMP-A"),
    ]


def test_equal_scores_and_weights_go_to_enum_order() -> None:
    blocked = _card(product_status="Blocked")
    error_now = _event(timedelta(0))

    assert _rank(cards=(blocked,), cases=(_case(),), app_events=(error_now,)) == [
        (R.OPEN_CASE_FOLLOWUP, Decimal("0.60"), "CMP-A"),
        (R.CARD_NOT_ACTIVE, Decimal("0.60"), "4497"),
        (R.FAILED_APP_ACTION, Decimal("0.60"), "EVT-A"),
    ]


def test_ranking_uses_the_unrounded_score() -> None:
    # 65 - 5.0042 = 59.9958: rounds to 0.60 like the card, but ranks below it,
    # even though its weight (65) is higher.
    pending = _tx(timedelta(hours=5, seconds=15), transaction_status="Pending")
    blocked = _card(product_status="Blocked")

    assert _rank(transactions=(pending,), cards=(blocked,)) == [
        (R.CARD_NOT_ACTIVE, Decimal("0.60"), "4497"),
        (R.PENDING_TRANSACTION, Decimal("0.60"), "TRX-A"),
    ]


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        pytest.param(
            _event(timedelta(hours=24)),
            [(R.FAILED_APP_ACTION, Decimal("0.36"), "EVT-A")],
            id="24h-in",
        ),
        pytest.param(_event(timedelta(hours=24, seconds=1)), [], id="24h-out"),
        pytest.param(_event(event_date=None), [], id="null-date"),
        pytest.param(_event(-timedelta(seconds=1)), [], id="future"),
    ],
)
def test_app_event_window(
    event: AppEventCandidate, expected: list[tuple[CallReason, Decimal, str]]
) -> None:
    assert _rank(app_events=(event,)) == expected


def test_p10_card_not_active_then_payment_overdue() -> None:
    cards = (
        _card(card_last4="7718", product_status="Blocked"),
        _card(card_last4="2626", days_past_due=180),
    )

    assert _rank(cards=cards) == [
        (R.CARD_NOT_ACTIVE, Decimal("0.60"), "7718"),
        (R.PAYMENT_OVERDUE, Decimal("0.50"), "2626"),
    ]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `$PY -m pytest tests/unit/classify_call_type/test_reason_ranking.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: a collection error, `ModuleNotFoundError: No module named 'classify_call_type_lambda.domain.entities.candidates'`.

- [ ] **Step 3: Write the entities**

`domain/entities/candidates.py`:

```python
"""Candidates: the rows each query returns, mapped before the reason rules run."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class TransactionCandidate:
    """A credit-card charge from the last 72 hours, or a 30-day scored one.

    fraud_score is used for banding only and is never presented.
    """

    transaction_id: str
    transaction_date: datetime | None
    card_last4: str | None
    card_currency: str | None
    merchant_name: str | None
    amount: Decimal | None
    currency: str | None
    transaction_status: str | None
    response_code: str | None
    transaction_country: str | None
    home_country: str | None
    fraud_score: Decimal | None


@dataclass(frozen=True)
class CardCandidate:
    """One of the customer's credit cards, de-duplicated to its latest state."""

    card_last4: str
    product_status: str | None
    expiration_date: date | None
    days_past_due: int | None


@dataclass(frozen=True)
class CaseCandidate:
    """A complaint open at as_of; sla_breached NULL counts as not breached."""

    complaint_id: str
    case_type: str | None
    category: str | None
    subcategory: str | None
    status: str | None
    sla_breached: bool | None
    days_open: int | None


@dataclass(frozen=True)
class AppEventCandidate:
    """A digital event of type 'Error' from the last 24 hours."""

    event_id: str
    event_date: datetime | None
    page_title: str | None
    action: str | None
```

`domain/entities/call_classification.py`:

```python
"""The tool's result: up to 3 ranked reasons and the reasons that couldn't be checked."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from classify_call_type_lambda.domain.entities.candidates import (
    AppEventCandidate,
    CardCandidate,
    CaseCandidate,
    TransactionCandidate,
)
from classify_call_type_lambda.domain.value_objects.call_reasons import CallReason

type Candidate = (
    TransactionCandidate | CardCandidate | CaseCandidate | AppEventCandidate
)


@dataclass(frozen=True)
class RankedReason:
    """A reason with its 2-decimal confidence and the record it points to."""

    reason: CallReason
    confidence: Decimal
    ref_id: str
    candidate: Candidate


@dataclass(frozen=True)
class CallClassification:
    """The ranking, best first, and the unavailable reasons in enum order.

    as_of_date is as_of's date in naive UTC, the date the card rules used. The
    presenter needs it for CARD_EXPIRING's days_left.
    """

    reasons: tuple[RankedReason, ...]
    unavailable: tuple[CallReason, ...]
    as_of_date: date
```

- [ ] **Step 4: Write `domain/services/reason_ranking.py`**

```python
"""Detect, score and rank call reasons (spec section 3). Pure functions, no I/O.

Every datetime here is naive UTC: the rows' timestamps have no time zone, and
the use case converts as_of the same way before calling rank(). The arithmetic is
Decimal throughout; age is fractional (17.74 days, not 17).
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from classify_call_type_lambda.domain.entities.call_classification import (
    Candidate,
    RankedReason,
)
from classify_call_type_lambda.domain.entities.candidates import (
    AppEventCandidate,
    CardCandidate,
    CaseCandidate,
    TransactionCandidate,
)
from classify_call_type_lambda.domain.value_objects.call_reasons import (
    OPEN_CASE_BREACHED_WEIGHT,
    REASON_RULES,
    CallReason,
    Decay,
)
from classify_call_type_lambda.domain.value_objects.fraud_bands import (
    FRAUD_ABOVE,
    REVIEW_ABOVE,
)
from classify_call_type_lambda.domain.value_objects.text_folding import fold_text

_APPROVED: Final = "Approved"
_ACTIVE: Final = "Active"
# The status reasons of a charge that isn't approved.
_STATUS_REASONS: Final = {
    "Declined": CallReason.DECLINED_TRANSACTION,
    "Pending": CallReason.PENDING_TRANSACTION,
    "Reversed": CallReason.REVERSED_TRANSACTION,
}
# Closed cards are not a reason to call about the card.
_NOT_ACTIVE_STATUSES: Final = frozenset({"Blocked", "Suspended"})
_EXPIRING_WITHIN: Final = timedelta(days=30)
_FLOOR: Final = Decimal("0.4")
_SECONDS_PER_UNIT: Final = {
    Decay.PER_HOUR: Decimal(3600),
    Decay.PER_DAY: Decimal(86400),
}
_HUNDRED: Final = Decimal(100)
_CENTS: Final = Decimal("0.01")
_ENUM_ORDER: Final = {reason: index for index, reason in enumerate(CallReason)}


@dataclass(frozen=True)
class _Scored:
    """A detected reason with its unrounded score, before the ranking."""

    reason: CallReason
    score: Decimal
    weight: Decimal
    event_time: datetime | None
    ref_id: str
    candidate: Candidate


def score(
    weight: Decimal, decay: Decay, event_time: datetime | None, as_of: datetime
) -> Decimal:
    """Return the decayed, unrounded score of an event.

    A future event counts as age 0. The score never falls below 40 percent of
    the weight.

    Raises:
        ValueError: A decaying reason has no event time.
    """
    if decay is Decay.NONE:
        return weight
    if event_time is None:
        raise ValueError("a decaying reason needs an event time")
    age = max(_seconds(as_of - event_time), Decimal(0))
    return max(weight - age / _SECONDS_PER_UNIT[decay], _FLOOR * weight)


def to_confidence(score: Decimal) -> Decimal:
    """Return score / 100 with 2 decimals, rounded half-up."""
    return (score / _HUNDRED).quantize(_CENTS, rounding=ROUND_HALF_UP)


def transaction_reasons(
    candidate: TransactionCandidate, as_of: datetime
) -> tuple[CallReason, ...]:
    """Return the reasons a charge triggers, in enum order.

    A charge without a date triggers nothing: every charge reason is timed.
    """
    when = candidate.transaction_date
    if when is None:
        return ()
    found: set[CallReason] = set()
    status = candidate.transaction_status
    if status == _APPROVED:
        band = _fraud_band(candidate.fraud_score)
        if band is not None:
            found.add(band)
        if _is_foreign(candidate):
            found.add(CallReason.FOREIGN_TRANSACTION)
    elif status in _STATUS_REASONS:
        found.add(_STATUS_REASONS[status])
    return tuple(
        reason
        for reason in CallReason
        if reason in found and _in_window(reason, when, as_of)
    )


def card_reasons(candidate: CardCandidate, as_of_date: date) -> tuple[CallReason, ...]:
    """Return the reasons a card's state triggers, in enum order.

    A Blocked or Suspended card is CARD_NOT_ACTIVE only; the other card
    reasons need an Active card.
    """
    status = candidate.product_status
    if status in _NOT_ACTIVE_STATUSES:
        return (CallReason.CARD_NOT_ACTIVE,)
    if status != _ACTIVE:
        return ()
    found: list[CallReason] = []
    if candidate.days_past_due is not None and candidate.days_past_due > 0:
        found.append(CallReason.PAYMENT_OVERDUE)
    expiration = candidate.expiration_date
    if expiration is not None and as_of_date <= expiration <= (
        as_of_date + _EXPIRING_WITHIN
    ):
        found.append(CallReason.CARD_EXPIRING)
    return tuple(found)


def rank(
    *,
    transactions: Sequence[TransactionCandidate],
    cards: Sequence[CardCandidate],
    cases: Sequence[CaseCandidate],
    app_events: Sequence[AppEventCandidate],
    as_of: datetime,
    limit: int,
) -> tuple[RankedReason, ...]:
    """Detect, score and rank every reason; keep the best ``limit``.

    The best event per reason has the highest score, then the newest event,
    then the lowest ref_id. Across reasons: the unrounded score descending,
    then the weight descending, then enum order.
    """
    scored = [
        *_score_transactions(transactions, as_of),
        *_score_cards(cards, as_of),
        *_score_cases(cases, as_of),
        *_score_app_events(app_events, as_of),
    ]
    ordered = sorted(
        _best_per_reason(scored),
        key=lambda item: (-item.score, -item.weight, _ENUM_ORDER[item.reason]),
    )
    return tuple(
        RankedReason(
            reason=item.reason,
            confidence=to_confidence(item.score),
            ref_id=item.ref_id,
            candidate=item.candidate,
        )
        for item in ordered[:limit]
    )


def _score_transactions(
    candidates: Sequence[TransactionCandidate], as_of: datetime
) -> Iterator[_Scored]:
    for candidate in candidates:
        for reason in transaction_reasons(candidate, as_of):
            yield _scored(
                reason,
                candidate,
                candidate.transaction_id,
                candidate.transaction_date,
                as_of,
            )


def _score_cards(candidates: Sequence[CardCandidate], as_of: datetime) -> Iterator[_Scored]:
    for candidate in candidates:
        for reason in card_reasons(candidate, as_of.date()):
            yield _scored(reason, candidate, candidate.card_last4, None, as_of)


def _score_cases(candidates: Sequence[CaseCandidate], as_of: datetime) -> Iterator[_Scored]:
    reason = CallReason.OPEN_CASE_FOLLOWUP
    for candidate in candidates:
        weight = (
            OPEN_CASE_BREACHED_WEIGHT
            if candidate.sla_breached is True
            else REASON_RULES[reason].weight
        )
        yield _scored(reason, candidate, candidate.complaint_id, None, as_of, weight)


def _score_app_events(
    candidates: Sequence[AppEventCandidate], as_of: datetime
) -> Iterator[_Scored]:
    reason = CallReason.FAILED_APP_ACTION
    for candidate in candidates:
        when = candidate.event_date
        if when is not None and _in_window(reason, when, as_of):
            yield _scored(reason, candidate, candidate.event_id, when, as_of)


def _scored(
    reason: CallReason,
    candidate: Candidate,
    ref_id: str,
    event_time: datetime | None,
    as_of: datetime,
    weight: Decimal | None = None,
) -> _Scored:
    """Score one detection with the reason's rule (or an effective weight)."""
    rule = REASON_RULES[reason]
    effective = rule.weight if weight is None else weight
    return _Scored(
        reason=reason,
        score=score(effective, rule.decay, event_time, as_of),
        weight=effective,
        event_time=event_time,
        ref_id=ref_id,
        candidate=candidate,
    )


def _best_per_reason(scored: list[_Scored]) -> list[_Scored]:
    """Keep each reason's best: highest score, then newest, then lowest ref_id."""
    # Stable sorts: first by ref_id ascending, then by (score, time) descending,
    # so equal score and time keep the lowest ref_id first.
    ordered = sorted(scored, key=lambda item: item.ref_id)
    ordered.sort(
        key=lambda item: (item.score, item.event_time or datetime.min), reverse=True
    )
    best: dict[CallReason, _Scored] = {}
    for item in ordered:
        best.setdefault(item.reason, item)
    return list(best.values())


def _fraud_band(fraud_score: Decimal | None) -> CallReason | None:
    """Return the fraud reason of an approved charge's score, or None."""
    if fraud_score is None:
        return None
    if fraud_score > FRAUD_ABOVE:
        return CallReason.FRAUD_SUSPECTED
    if fraud_score > REVIEW_ABOVE:
        return CallReason.UNRECOGNIZED_CHARGE_REVIEW
    return None


def _is_foreign(candidate: TransactionCandidate) -> bool:
    """Return whether the country (folded) or the currency differs.

    A blank country folds to "" and counts as unknown, like NULL.
    """
    country = fold_text(candidate.transaction_country)
    home = fold_text(candidate.home_country)
    by_country = bool(country) and bool(home) and country != home
    by_currency = (
        candidate.currency is not None
        and candidate.card_currency is not None
        and candidate.currency != candidate.card_currency
    )
    return by_country or by_currency


def _in_window(reason: CallReason, when: datetime, as_of: datetime) -> bool:
    """Return whether ``when`` is in the reason's window, both ends inclusive."""
    window = REASON_RULES[reason].window
    return window is None or as_of - window <= when <= as_of


def _seconds(delta: timedelta) -> Decimal:
    """Return a timedelta in exact Decimal seconds (total_seconds() is a float)."""
    return (
        Decimal(delta.days * 86400 + delta.seconds)
        + Decimal(delta.microseconds) / 1_000_000
    )
```

- [ ] **Step 5: Run it to verify it passes**

Run: `$PY -m pytest tests/unit/classify_call_type/test_reason_ranking.py -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: `70 passed`

If `test_score_floors_at_40_percent_of_the_weight` fails only because the result prints as `26.0` versus `26`, check that Decimal equality still holds. It does, because `Decimal("26.0") == Decimal("26")`. A failure there is a real bug.

- [ ] **Step 6: Lint**

Run: `$PY -m ruff format gateway/tools/classify_call_type tests/unit/classify_call_type </dev/null && $PY -m ruff check gateway/tools/classify_call_type tests/unit/classify_call_type </dev/null`
Expected: `ruff check` is clean. Formatting the new files is allowed, but re-run the tests after formatting.

---

### Task 5: The use case

**Files:**
- Create: `application/use_cases/classify_call_type.py`
- Test: `tests/unit/classify_call_type/test_classify_call_type_use_case.py`

**Interfaces:**
- Consumes:
  - Task 1: the ports and port errors, plus `fakes.py`.
  - Task 2: `InvalidInputError`, `DataSourceUnavailableError`, `CallReasonLookupError`.
  - Task 3: `CallReason`, `Source`, `SOURCE_REASONS`, `REVIEW_ABOVE`.
  - Task 4: the four candidates, `CallClassification`, and `rank`.
- Produces: `classify_call_type_lambda.application.use_cases.classify_call_type`:
  - `ClassifyCallTypeUseCase(database_repository: DatabaseRepository, query_provider: QueryProvider)`, with class constants `TOP_N = 3` and `TRANSACTION_CANDIDATE_CAP = 200`;
  - `.execute(customer_id: object, as_of: datetime) -> CallClassification`;
  - the module constant `QUERY_NAMES: Mapping[Source, str]`, in `Source` order.

- [ ] **Step 1: Write the failing test**

`tests/unit/classify_call_type/test_classify_call_type_use_case.py`:

```python
"""Tests for ClassifyCallTypeUseCase (spec section 4)."""

import logging
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from classify_call_type_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
)
from classify_call_type_lambda.application.use_cases.classify_call_type import (
    QUERY_NAMES,
    ClassifyCallTypeUseCase,
)
from classify_call_type_lambda.domain.entities.call_classification import (
    CallClassification,
    RankedReason,
)
from classify_call_type_lambda.domain.entities.candidates import (
    AppEventCandidate,
    CardCandidate,
    CaseCandidate,
    TransactionCandidate,
)
from classify_call_type_lambda.domain.errors import (
    CallReasonLookupError,
    DataSourceUnavailableError,
    InvalidInputError,
)
from classify_call_type_lambda.domain.value_objects.call_reasons import (
    CallReason,
    Source,
)
from classify_call_type_lambda.domain.value_objects.fraud_bands import REVIEW_ABOVE

from .fakes import (
    AS_OF,
    AS_OF_SQL,
    CHARGE_DATE,
    CUSTOMER_ID,
    TRANSACTION_ID,
    FakeClassifyRepository,
    FakeQueryProvider,
    Outcome,
    classify_responses,
    make_app_event_row,
    make_card_row,
    make_case_row,
    make_transaction_row,
)

pytestmark = pytest.mark.unit

R = CallReason
TODAY = date(2026, 6, 17)

P07_CANDIDATE = TransactionCandidate(
    transaction_id=TRANSACTION_ID,
    transaction_date=CHARGE_DATE,
    card_last4="4497",
    card_currency="USD",
    merchant_name="Estación de Servicio",
    amount=Decimal("288.69"),
    currency="USD",
    transaction_status="Approved",
    response_code="00",
    transaction_country="México",
    home_country="México",
    fraud_score=Decimal("62.00"),
)
P07_FRAUD = RankedReason(
    reason=R.FRAUD_SUSPECTED,
    confidence=Decimal("0.77"),
    ref_id=TRANSACTION_ID,
    candidate=P07_CANDIDATE,
)

TRANSACTION_REASONS = (
    R.FRAUD_SUSPECTED,
    R.DECLINED_TRANSACTION,
    R.UNRECOGNIZED_CHARGE_REVIEW,
    R.PENDING_TRANSACTION,
    R.REVERSED_TRANSACTION,
    R.FOREIGN_TRANSACTION,
)
CARD_REASONS = (R.CARD_NOT_ACTIVE, R.PAYMENT_OVERDUE, R.CARD_EXPIRING)


def make_use_case(
    responses: dict[str, Outcome] | None = None,
    query_provider: FakeQueryProvider | None = None,
) -> tuple[ClassifyCallTypeUseCase, FakeClassifyRepository]:
    """Wire the use case to fakes; by default they answer P07."""
    repository = FakeClassifyRepository(
        classify_responses() if responses is None else responses
    )
    use_case = ClassifyCallTypeUseCase(
        database_repository=repository,
        query_provider=query_provider or FakeQueryProvider(),
    )
    return use_case, repository


def _summary(result: CallClassification) -> list[tuple[CallReason, Decimal, str]]:
    return [(item.reason, item.confidence, item.ref_id) for item in result.reasons]


def _without(row: dict[str, Any], column: str) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != column}


# --- the happy path and the params ------------------------------------------


def test_constants_are_pinned() -> None:
    assert ClassifyCallTypeUseCase.TOP_N == 3
    assert ClassifyCallTypeUseCase.TRANSACTION_CANDIDATE_CAP == 200
    assert QUERY_NAMES == {
        Source.TRANSACTIONS: "call_reason_transactions",
        Source.CARDS: "call_reason_cards",
        Source.CASES: "call_reason_cases",
        Source.APP_EVENTS: "call_reason_app_events",
    }


def test_p07_ranks_its_flagged_charge() -> None:
    use_case, _ = make_use_case()

    result = use_case.execute(CUSTOMER_ID, AS_OF)

    assert result == CallClassification(
        reasons=(P07_FRAUD,), unavailable=(), as_of_date=TODAY
    )


def test_queries_run_in_order_with_their_params() -> None:
    use_case, repository = make_use_case()

    use_case.execute(CUSTOMER_ID, AS_OF)

    assert repository.calls == [
        (
            "call_reason_transactions",
            {
                "customer_id": CUSTOMER_ID,
                "as_of": AS_OF_SQL,
                "review_above": Decimal("30"),
                "limit": 201,
            },
        ),
        ("call_reason_cards", {"customer_id": CUSTOMER_ID}),
        ("call_reason_cases", {"customer_id": CUSTOMER_ID, "as_of": AS_OF_SQL}),
        ("call_reason_app_events", {"customer_id": CUSTOMER_ID, "as_of": AS_OF_SQL}),
    ]
    assert repository.calls[0][1]["review_above"] is REVIEW_ABOVE


def test_customer_id_is_stripped_and_uppercased() -> None:
    use_case, repository = make_use_case()

    use_case.execute("  cli-ex6boaoefzhq ", AS_OF)

    assert {params["customer_id"] for _, params in repository.calls} == {CUSTOMER_ID}


@pytest.mark.parametrize("bad", [None, 42, "", "   "])
def test_bad_customer_id_is_rejected_before_any_query(bad: object) -> None:
    use_case, repository = make_use_case()

    with pytest.raises(InvalidInputError) as caught:
        use_case.execute(bad, AS_OF)

    assert caught.value.field == "customer_id"
    assert caught.value.reason == "is required and must be a non-empty string"
    assert repository.calls == []


def test_naive_as_of_is_rejected_before_any_query() -> None:
    use_case, repository = make_use_case()

    with pytest.raises(ValueError, match="aware"):
        use_case.execute(CUSTOMER_ID, AS_OF_SQL)

    assert repository.calls == []


def test_non_utc_as_of_is_converted_before_the_window_check() -> None:
    # 21:00 at -05:00 is 02:00 UTC the next day.
    as_of = datetime(2026, 6, 17, 21, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    as_of_utc = datetime(2026, 6, 18, 2, 0, 0)
    declined = make_transaction_row(
        transaction_id="TRX-D",
        transaction_status="Declined",
        transaction_date=as_of_utc - timedelta(hours=72),
        fraud_score=None,
    )
    # Expired the day before as_of's UTC date (the local date is the 17th).
    card = make_card_row(expiration_date=date(2026, 6, 17))
    use_case, repository = make_use_case(
        classify_responses(
            call_reason_transactions=[declined], call_reason_cards=[card]
        )
    )

    result = use_case.execute(CUSTOMER_ID, as_of)

    assert _summary(result) == [(R.DECLINED_TRANSACTION, Decimal("0.34"), "TRX-D")]
    assert result.as_of_date == date(2026, 6, 18)
    assert repository.calls[0][1]["as_of"] == as_of_utc
    assert repository.calls[2][1]["as_of"] == as_of_utc


def test_unknown_customer_gets_no_reasons() -> None:
    use_case, _ = make_use_case({})

    assert use_case.execute("CLI-NOBODY", AS_OF) == CallClassification(
        reasons=(), unavailable=(), as_of_date=TODAY
    )


def test_the_top_three_are_kept() -> None:
    brazil = make_transaction_row(
        transaction_id="TRX-A",
        transaction_date=AS_OF_SQL - timedelta(hours=2),
        transaction_country="Brasil",
    )
    declined = make_transaction_row(
        transaction_id="TRX-B",
        transaction_date=AS_OF_SQL - timedelta(hours=1),
        transaction_status="Declined",
        fraud_score=None,
    )
    use_case, _ = make_use_case(
        classify_responses(
            call_reason_transactions=[declined, brazil],
            call_reason_cases=[make_case_row(sla_breached=True)],
            call_reason_app_events=[make_app_event_row()],
        )
    )

    result = use_case.execute(CUSTOMER_ID, AS_OF)

    # FAILED_APP_ACTION (0.58) and FOREIGN_TRANSACTION (0.53) are cut.
    assert _summary(result) == [
        (R.FRAUD_SUSPECTED, Decimal("0.95"), "TRX-A"),
        (R.DECLINED_TRANSACTION, Decimal("0.84"), "TRX-B"),
        (R.OPEN_CASE_FOLLOWUP, Decimal("0.75"), "CMP-FHCLR8TGWMBD0YFOCLYS"),
    ]


def test_rows_are_mapped_to_candidates() -> None:
    card = make_card_row(card_last4="7718", product_status="Blocked")
    case = make_case_row()
    event = make_app_event_row()
    use_case, _ = make_use_case(
        classify_responses(
            call_reason_transactions=[],
            call_reason_cards=[card],
            call_reason_cases=[case],
            call_reason_app_events=[event],
        )
    )

    result = use_case.execute(CUSTOMER_ID, AS_OF)

    assert [item.candidate for item in result.reasons] == [
        CaseCandidate(
            complaint_id="CMP-FHCLR8TGWMBD0YFOCLYS",
            case_type="Claim",
            category="Cards",
            subcategory="Unrecognized charge",
            status="In Progress",
            sla_breached=None,
            days_open=12,
        ),
        CardCandidate(
            card_last4="7718",
            product_status="Blocked",
            expiration_date=date(2029, 8, 31),
            days_past_due=0,
        ),
        AppEventCandidate(
            event_id="EVT-0001",
            event_date=AS_OF_SQL - timedelta(hours=2),
            page_title="Pagar Servicios",
            action="submit_payment",
        ),
    ]


# --- a failing source --------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("call_reason_transactions", TRANSACTION_REASONS),
        ("call_reason_cards", CARD_REASONS),
        ("call_reason_cases", (R.OPEN_CASE_FOLLOWUP,)),
        ("call_reason_app_events", (R.FAILED_APP_ACTION,)),
    ],
)
def test_a_failed_source_lists_its_reasons_in_enum_order(
    query: str, expected: tuple[CallReason, ...]
) -> None:
    use_case, _ = make_use_case(
        classify_responses(**{query: QueryExecutionError("boom")})
    )

    result = use_case.execute(CUSTOMER_ID, AS_OF)

    assert result.unavailable == tuple(r for r in CallReason if r in expected)


@pytest.mark.parametrize(
    "error",
    [
        DataSourceConnectionError("down"),
        QueryExecutionError("boom"),
        QueryLimitExceededError("too big"),
    ],
)
def test_the_other_sources_are_still_ranked(
    error: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    use_case, repository = make_use_case(classify_responses(call_reason_cards=error))

    result = use_case.execute(CUSTOMER_ID, AS_OF)

    assert result.reasons == (P07_FRAUD,)
    assert result.unavailable == CARD_REASONS
    assert repository.queries == list(QUERY_NAMES.values())
    assert "classify_call_type source cards unavailable" in caplog.text


def test_unavailable_merges_sources_in_enum_order() -> None:
    use_case, _ = make_use_case(
        classify_responses(
            call_reason_transactions=QueryExecutionError("boom"),
            call_reason_cards=QueryExecutionError("boom"),
        )
    )

    result = use_case.execute(CUSTOMER_ID, AS_OF)

    assert result.unavailable == (
        R.FRAUD_SUSPECTED,
        R.DECLINED_TRANSACTION,
        R.UNRECOGNIZED_CHARGE_REVIEW,
        R.PENDING_TRANSACTION,
        R.REVERSED_TRANSACTION,
        R.CARD_NOT_ACTIVE,
        R.FOREIGN_TRANSACTION,
        R.PAYMENT_OVERDUE,
        R.CARD_EXPIRING,
    )


def test_a_missing_query_makes_its_source_unavailable() -> None:
    provider = FakeQueryProvider({name: name for name in QUERY_NAMES.values()})
    del provider.queries["call_reason_app_events"]
    use_case, repository = make_use_case(query_provider=provider)

    result = use_case.execute(CUSTOMER_ID, AS_OF)

    assert result.reasons == (P07_FRAUD,)
    assert result.unavailable == (R.FAILED_APP_ACTION,)
    assert "call_reason_app_events" not in repository.queries


@pytest.mark.parametrize(
    ("query", "rows"),
    [
        pytest.param(
            "call_reason_transactions",
            [make_transaction_row(transaction_id=None)],
            id="null-transaction-id",
        ),
        pytest.param(
            "call_reason_transactions",
            [_without(make_transaction_row(), "home_country")],
            id="missing-column",
        ),
        pytest.param(
            "call_reason_transactions",
            [make_transaction_row(amount="288.69")],
            id="amount-text",
        ),
        pytest.param(
            "call_reason_transactions",
            [make_transaction_row(fraud_score=Decimal("NaN"))],
            id="score-nan",
        ),
        pytest.param(
            "call_reason_transactions",
            [make_transaction_row(transaction_date="2026-05-31")],
            id="date-text",
        ),
        pytest.param(
            "call_reason_cards", [make_card_row(card_last4=None)], id="null-last4"
        ),
        pytest.param(
            "call_reason_cards", [make_card_row(days_past_due=True)], id="dpd-bool"
        ),
        pytest.param(
            "call_reason_cases", [make_case_row(complaint_id=None)], id="null-case-id"
        ),
        pytest.param(
            "call_reason_cases", [make_case_row(sla_breached="yes")], id="sla-text"
        ),
        pytest.param(
            "call_reason_app_events",
            [make_app_event_row(event_id=None)],
            id="null-event-id",
        ),
    ],
)
def test_a_bad_row_makes_its_source_unavailable(
    query: str, rows: list[dict[str, Any]]
) -> None:
    use_case, _ = make_use_case(classify_responses(**{query: rows}))

    result = use_case.execute(CUSTOMER_ID, AS_OF)

    failed = next(source for source, name in QUERY_NAMES.items() if name == query)
    assert result.unavailable == tuple(
        reason for reason in CallReason if reason in _reasons_of(failed)
    )


def test_a_transaction_without_a_card_last4_still_maps() -> None:
    use_case, _ = make_use_case(
        classify_responses(call_reason_transactions=[make_transaction_row(card_last4=None)])
    )

    result = use_case.execute(CUSTOMER_ID, AS_OF)

    assert result.unavailable == ()
    assert result.reasons[0].candidate == replace(P07_CANDIDATE, card_last4=None)


def _reasons_of(source: Source) -> tuple[CallReason, ...]:
    return {
        Source.TRANSACTIONS: TRANSACTION_REASONS,
        Source.CARDS: CARD_REASONS,
        Source.CASES: (R.OPEN_CASE_FOLLOWUP,),
        Source.APP_EVENTS: (R.FAILED_APP_ACTION,),
    }[source]


# --- all four failing ---------------------------------------------------------


def test_all_four_failing_with_a_connection_error_is_unavailable() -> None:
    responses: dict[str, Outcome] = {
        "call_reason_transactions": QueryExecutionError("boom"),
        "call_reason_cards": DataSourceConnectionError("down"),
        "call_reason_cases": QueryExecutionError("boom"),
        "call_reason_app_events": QueryLimitExceededError("too big"),
    }
    use_case, repository = make_use_case(responses)

    with pytest.raises(DataSourceUnavailableError) as caught:
        use_case.execute(CUSTOMER_ID, AS_OF)

    assert isinstance(caught.value.__cause__, DataSourceConnectionError)
    assert repository.queries == list(QUERY_NAMES.values())


@pytest.mark.parametrize(
    "responses",
    [
        pytest.param(
            {name: QueryExecutionError("boom") for name in QUERY_NAMES.values()},
            id="query-errors",
        ),
        pytest.param(
            {
                "call_reason_transactions": [make_transaction_row(transaction_id=None)],
                "call_reason_cards": [make_card_row(card_last4=None)],
                "call_reason_cases": [make_case_row(complaint_id=None)],
                "call_reason_app_events": [make_app_event_row(event_id=None)],
            },
            id="bad-rows",
        ),
    ],
)
def test_all_four_failing_without_a_connection_error_is_a_lookup_error(
    responses: dict[str, Outcome],
) -> None:
    use_case, _ = make_use_case(responses)

    with pytest.raises(CallReasonLookupError):
        use_case.execute(CUSTOMER_ID, AS_OF)


# --- the transaction cap ------------------------------------------------------


def _quiet_rows(count: int) -> list[dict[str, Any]]:
    """Approved, domestic, unscored charges, newest first: they trigger nothing."""
    return [
        make_transaction_row(
            transaction_id=f"TRX-{index:04d}",
            transaction_date=AS_OF_SQL - timedelta(minutes=index),
            fraud_score=None,
        )
        for index in range(count)
    ]


def test_more_than_the_cap_logs_and_ranks_every_row(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    oldest = make_transaction_row(
        transaction_id="TRX-OLDEST",
        transaction_date=AS_OF_SQL - timedelta(hours=10),
        transaction_status="Declined",
        fraud_score=None,
    )
    use_case, _ = make_use_case(
        classify_responses(call_reason_transactions=[*_quiet_rows(200), oldest])
    )

    result = use_case.execute(CUSTOMER_ID, AS_OF)

    assert _summary(result) == [
        (R.DECLINED_TRANSACTION, Decimal("0.75"), "TRX-OLDEST"),
    ]
    assert "classify_call_type transactions returned 201 rows" in caplog.text


def test_the_cap_itself_does_not_log(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    use_case, _ = make_use_case(
        classify_responses(call_reason_transactions=_quiet_rows(200))
    )

    use_case.execute(CUSTOMER_ID, AS_OF)

    assert caplog.records == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `$PY -m pytest tests/unit/classify_call_type/test_classify_call_type_use_case.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: a collection error, `ModuleNotFoundError: No module named 'classify_call_type_lambda.application.use_cases.classify_call_type'`.

- [ ] **Step 3: Write `application/use_cases/classify_call_type.py`**

The id cleaning, `_utc` and the row helpers are copied from `explain_transaction`'s use case, keeping only the helpers this file uses.

```python
"""Use case: rank the likely reasons the customer is calling."""

import logging
from collections.abc import Callable, Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Final, TypeVar

from classify_call_type_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from classify_call_type_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
)
from classify_call_type_lambda.application.ports.query_provider import QueryProvider
from classify_call_type_lambda.domain.entities.call_classification import (
    CallClassification,
)
from classify_call_type_lambda.domain.entities.candidates import (
    AppEventCandidate,
    CardCandidate,
    CaseCandidate,
    TransactionCandidate,
)
from classify_call_type_lambda.domain.errors import (
    CallReasonLookupError,
    DataSourceUnavailableError,
    InvalidInputError,
)
from classify_call_type_lambda.domain.services.reason_ranking import rank
from classify_call_type_lambda.domain.value_objects.call_reasons import (
    SOURCE_REASONS,
    CallReason,
    Source,
)
from classify_call_type_lambda.domain.value_objects.fraud_bands import REVIEW_ABOVE

logger = logging.getLogger(__name__)

# The candidate query of each source, in the order they run.
QUERY_NAMES: Final[Mapping[Source, str]] = {
    Source.TRANSACTIONS: "call_reason_transactions",
    Source.CARDS: "call_reason_cards",
    Source.CASES: "call_reason_cases",
    Source.APP_EVENTS: "call_reason_app_events",
}

_INVALID_ID: Final = "is required and must be a non-empty string"

_Candidate = TypeVar("_Candidate")


class ClassifyCallTypeUseCase:
    """Rank up to TOP_N call reasons through a database-agnostic repository.

    The four candidate queries run one after another on the repository's single
    connection, each in its own try. A failed query, or a row it returned that
    can't be mapped, makes that source's reasons unavailable; the others are
    still ranked. Only all four failing fails the call.
    """

    TOP_N: Final = 3
    TRANSACTION_CANDIDATE_CAP: Final = 200

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

    def execute(self, customer_id: object, as_of: datetime) -> CallClassification:
        """Clean the input, load the four candidate sources and rank them.

        Args:
            customer_id: The customer id exactly as it came in the tool event.
            as_of: "Now", an aware datetime. Every query and every rule gets it
                as naive UTC, because the ERD's timestamp columns have no time
                zone.

        Raises:
            InvalidInputError: customer_id is missing, not a string or blank.
                Raised before the database is touched.
            ValueError: as_of is naive (a programming error, not user input).
            DataSourceUnavailableError: All four sources failed, at least one
                on the connection.
            CallReasonLookupError: All four sources failed, none on the
                connection.
        """
        clean_customer_id = _clean_customer_id(customer_id)
        as_of_sql = _utc(as_of).replace(tzinfo=None)
        failures: dict[Source, Exception] = {}

        transactions = self._load(
            Source.TRANSACTIONS,
            {
                "customer_id": clean_customer_id,
                "as_of": as_of_sql,
                "review_above": REVIEW_ABOVE,
                "limit": self.TRANSACTION_CANDIDATE_CAP + 1,
            },
            _to_transaction,
            failures,
        )
        if len(transactions) > self.TRANSACTION_CANDIDATE_CAP:
            logger.warning(
                "classify_call_type transactions returned %d rows, above the cap "
                "of %d; the oldest may be missing",
                len(transactions),
                self.TRANSACTION_CANDIDATE_CAP,
            )
        cards = self._load(
            Source.CARDS, {"customer_id": clean_customer_id}, _to_card, failures
        )
        cases = self._load(
            Source.CASES,
            {"customer_id": clean_customer_id, "as_of": as_of_sql},
            _to_case,
            failures,
        )
        app_events = self._load(
            Source.APP_EVENTS,
            {"customer_id": clean_customer_id, "as_of": as_of_sql},
            _to_app_event,
            failures,
        )

        if len(failures) == len(Source):
            _raise_all_failed(failures)

        failed_reasons = {
            reason for source in failures for reason in SOURCE_REASONS[source]
        }
        return CallClassification(
            reasons=rank(
                transactions=transactions,
                cards=cards,
                cases=cases,
                app_events=app_events,
                as_of=as_of_sql,
                limit=self.TOP_N,
            ),
            unavailable=tuple(r for r in CallReason if r in failed_reasons),
            as_of_date=as_of_sql.date(),
        )

    def _load(
        self,
        source: Source,
        params: Mapping[str, object],
        mapper: Callable[[Mapping[str, Any]], _Candidate],
        failures: dict[Source, Exception],
    ) -> tuple[_Candidate, ...]:
        """Run a source's query and map every row.

        On a data-access or mapping failure, record it in ``failures``, log a
        warning and return no candidates.
        """
        try:
            query = self._query_provider.get(QUERY_NAMES[source])
            rows = self._database_repository.execute_query(query, params)
            return tuple(mapper(row) for row in rows)
        # A mapper raises KeyError, TypeError or ValueError on a bad row.
        except (DataAccessError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "classify_call_type source %s unavailable", source.value, exc_info=True
            )
            failures[source] = exc
            return ()


def _raise_all_failed(failures: Mapping[Source, Exception]) -> None:
    """Raise the domain error for four failed sources.

    Raises:
        DataSourceUnavailableError: At least one failure was on the connection.
        CallReasonLookupError: None was.
    """
    for exc in failures.values():
        if isinstance(exc, DataSourceConnectionError):
            raise DataSourceUnavailableError() from exc
    raise CallReasonLookupError() from next(iter(failures.values()))


def _clean_customer_id(raw: object) -> str:
    """Strip and uppercase the raw id; ids look like ``CLI-ITIECUE8PRH9``.

    There is no format check: an unknown id just finds nothing. Whether the
    caller may see this customer is the Gateway's Cedar policy's job.

    Raises:
        InvalidInputError: The id isn't a string or is blank after stripping.
    """
    if not isinstance(raw, str):
        raise InvalidInputError("customer_id", _INVALID_ID)
    customer_id = raw.strip().upper()
    if not customer_id:
        raise InvalidInputError("customer_id", _INVALID_ID)
    return customer_id


def _utc(as_of: datetime) -> datetime:
    """Return as_of converted to aware UTC.

    Raises:
        ValueError: as_of is naive.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be an aware datetime")
    return as_of.astimezone(timezone.utc)


def _to_transaction(row: Mapping[str, Any]) -> TransactionCandidate:
    """Map a call_reason_transactions row.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type, or transaction_id is None.
        ValueError: The amount or the score isn't finite.
    """
    return TransactionCandidate(
        transaction_id=_required_text(row, "transaction_id"),
        transaction_date=_optional_datetime(row, "transaction_date"),
        card_last4=_optional_text(row, "card_last4"),
        card_currency=_optional_text(row, "card_currency"),
        merchant_name=_optional_text(row, "merchant_name"),
        amount=_optional_amount(row, "amount"),
        currency=_optional_text(row, "currency"),
        transaction_status=_optional_text(row, "transaction_status"),
        response_code=_optional_text(row, "response_code"),
        transaction_country=_optional_text(row, "transaction_country"),
        home_country=_optional_text(row, "home_country"),
        fraud_score=_optional_amount(row, "fraud_score"),
    )


def _to_card(row: Mapping[str, Any]) -> CardCandidate:
    """Map a call_reason_cards row.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type, or card_last4 is None.
    """
    return CardCandidate(
        card_last4=_required_text(row, "card_last4"),
        product_status=_optional_text(row, "product_status"),
        expiration_date=_optional_date(row, "expiration_date"),
        days_past_due=_optional_int(row, "days_past_due"),
    )


def _to_case(row: Mapping[str, Any]) -> CaseCandidate:
    """Map a call_reason_cases row.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type, or complaint_id is None.
    """
    return CaseCandidate(
        complaint_id=_required_text(row, "complaint_id"),
        case_type=_optional_text(row, "case_type"),
        category=_optional_text(row, "category"),
        subcategory=_optional_text(row, "subcategory"),
        status=_optional_text(row, "status"),
        sla_breached=_optional_bool(row, "sla_breached"),
        days_open=_optional_int(row, "days_open"),
    )


def _to_app_event(row: Mapping[str, Any]) -> AppEventCandidate:
    """Map a call_reason_app_events row.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type, or event_id is None.
    """
    return AppEventCandidate(
        event_id=_required_text(row, "event_id"),
        event_date=_optional_datetime(row, "event_date"),
        page_title=_optional_text(row, "page_title"),
        action=_optional_text(row, "action"),
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


def _optional_int(row: Mapping[str, Any], column: str) -> int | None:
    """Return a nullable integer column; bool is rejected."""
    value = row[column]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{column} is {type(value).__name__}, expected an integer")
    return value


def _optional_bool(row: Mapping[str, Any], column: str) -> bool | None:
    """Return a nullable boolean column; only bool or None is accepted."""
    value = row[column]
    if value is None or isinstance(value, bool):
        return value
    raise TypeError(f"{column} is {type(value).__name__}, expected a boolean")
```

- [ ] **Step 4: Run it to verify it passes**

Run: `$PY -m pytest tests/unit/classify_call_type/test_classify_call_type_use_case.py -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: `38 passed`

- [ ] **Step 5: Lint**

Run: `$PY -m ruff format gateway/tools/classify_call_type tests/unit/classify_call_type </dev/null && $PY -m ruff check gateway/tools/classify_call_type tests/unit/classify_call_type </dev/null`
Expected: `ruff check` is clean. Re-run the tests if formatting changed anything.

---

### Task 6: SQL, `tool_spec.json` and the contract tests

**Files:**
- Create: `queries/postgresql/call_reason_transactions.sql`, `call_reason_cards.sql`, `call_reason_cases.sql`, `call_reason_app_events.sql`
- Create: `gateway/tools/classify_call_type/tool_spec.json`
- Test: `tests/unit/classify_call_type/test_query_contracts.py`

**Interfaces:**
- Consumes: Task 5 (`ClassifyCallTypeUseCase`, `QUERY_NAMES`) and Task 1 (`FileQueryProvider`, fakes).
- Produces: the four SQL files, named after the query names, and the tool spec. The Task 8 wiring test loads them through `FileQueryProvider`.

Write every file with the Write tool: UTF-8, NFC, no BOM, LF line endings. The SQL files end with a newline after the last line.

- [ ] **Step 1: Write the failing test**

`tests/unit/classify_call_type/test_query_contracts.py`:

```python
"""Drift tests: the SQL files and tool_spec.json must match the Python contracts."""

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import pytest
from classify_call_type_lambda.application.use_cases.classify_call_type import (
    QUERY_NAMES,
    ClassifyCallTypeUseCase,
)
from classify_call_type_lambda.domain.value_objects.call_reasons import CallReason
from classify_call_type_lambda.infrastructure.queries.file_query_provider import (
    FileQueryProvider,
)

from .fakes import (
    AS_OF,
    CUSTOMER_ID,
    FakeClassifyRepository,
    FakeQueryProvider,
    classify_responses,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_ROOT = REPO_ROOT / "gateway/tools/classify_call_type"
QUERIES_DIR = TOOL_ROOT / "classify_call_type_lambda/queries/postgresql"
TOOL_SPEC = TOOL_ROOT / "tool_spec.json"
PLACEHOLDER = re.compile(r"%\((\w+)\)s")
SESSION_STATEMENT = re.compile(r"^\s*SET\b", re.IGNORECASE | re.MULTILINE)
CREDIT_CARD_FILTER = "p.product_type = 'Tarjeta Crédito'"
NAMES = tuple(QUERY_NAMES.values())

# The columns each query must select: the ones the use case maps (Task 5).
SELECTED_COLUMNS = {
    "call_reason_transactions": (
        "transaction_id",
        "transaction_date",
        "card_last4",
        "card_currency",
        "merchant_name",
        "amount",
        "currency",
        "transaction_status",
        "response_code",
        "transaction_country",
        "home_country",
        "fraud_score",
    ),
    "call_reason_cards": (
        "card_last4",
        "product_status",
        "expiration_date",
        "days_past_due",
    ),
    "call_reason_cases": (
        "complaint_id",
        "case_type",
        "category",
        "subcategory",
        "status",
        "sla_breached",
        "days_open",
    ),
    "call_reason_app_events": ("event_id", "event_date", "page_title", "action"),
}


def sql(name: str) -> str:
    """Load one of the real queries."""
    return FileQueryProvider(QUERIES_DIR).get(name)


def sent_params() -> dict[str, dict[str, object]]:
    """Return the params the use case actually sends, keyed by query name."""
    database_repository = FakeClassifyRepository(classify_responses())
    use_case = ClassifyCallTypeUseCase(
        database_repository=database_repository, query_provider=FakeQueryProvider()
    )
    use_case.execute(CUSTOMER_ID, as_of=AS_OF)
    return dict(database_repository.calls)


def tool_spec() -> dict[str, Any]:
    """Load the single tool definition from tool_spec.json."""
    specs = json.loads(TOOL_SPEC.read_text(encoding="utf-8"))
    assert isinstance(specs, list) and len(specs) == 1
    return specs[0]


# --- every query -------------------------------------------------------------


def test_the_folder_holds_exactly_the_four_queries() -> None:
    assert sorted(path.stem for path in QUERIES_DIR.glob("*.sql")) == sorted(NAMES)


def test_every_query_is_sent() -> None:
    assert set(sent_params()) == set(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_sql_placeholders_match_the_use_case_params_exactly(name: str) -> None:
    assert set(PLACEHOLDER.findall(sql(name))) == set(sent_params()[name])


@pytest.mark.parametrize("name", NAMES)
def test_sql_has_no_stray_percent_signs(name: str) -> None:
    # psycopg treats every '%' as a placeholder marker once params are passed.
    assert "%" not in PLACEHOLDER.sub("", sql(name))


@pytest.mark.parametrize("name", NAMES)
def test_sql_sets_no_session_parameters(name: str) -> None:
    # DSQL rejects most session parameters (statement_timeout among them).
    text = sql(name)

    assert SESSION_STATEMENT.search(text) is None
    assert "statement_timeout" not in text.lower()


@pytest.mark.parametrize("name", NAMES)
def test_no_query_reads_is_fraud(name: str) -> None:
    # DEC-10: the label is never read. Comments count too.
    assert "is_fraud" not in sql(name).lower()


@pytest.mark.parametrize(
    "name", [name for name in NAMES if name != "call_reason_transactions"]
)
def test_only_the_transactions_query_reads_the_score(name: str) -> None:
    assert "fraud_score" not in sql(name).lower()


@pytest.mark.parametrize("name", NAMES)
def test_each_query_checks_the_customer(name: str) -> None:
    assert "customer_id = %(customer_id)s" in sql(name)


@pytest.mark.parametrize("name", NAMES)
def test_sql_is_nfc_utf8_without_bom(name: str) -> None:
    # A decomposed accent or a BOM would silently match nothing.
    raw = (QUERIES_DIR / f"{name}.sql").read_bytes()

    assert not raw.startswith(b"\xef\xbb\xbf")
    assert unicodedata.is_normalized("NFC", raw.decode("utf-8"))


@pytest.mark.parametrize("name", NAMES)
def test_sql_selects_every_column_the_use_case_maps(name: str) -> None:
    text = sql(name)
    for column in SELECTED_COLUMNS[name]:
        assert column in text, column


@pytest.mark.parametrize("name", ["call_reason_transactions", "call_reason_cards"])
def test_card_queries_are_credit_cards_only(name: str) -> None:
    raw = (QUERIES_DIR / f"{name}.sql").read_bytes()

    assert CREDIT_CARD_FILTER.encode("utf-8") in raw


# --- the transactions query --------------------------------------------------


def test_transactions_window_is_72_hours_plus_30_day_scored_charges() -> None:
    text = sql("call_reason_transactions")

    assert "SELECT DISTINCT ON (t.transaction_id)" in text
    assert "t.transaction_date >= %(as_of)s - INTERVAL '30 days'" in text
    assert "t.transaction_date <= %(as_of)s" in text
    assert "x.transaction_date >= %(as_of)s - INTERVAL '72 hours'" in text
    assert (
        "x.transaction_status = 'Approved' "
        "AND x.fraud_score > %(review_above)s::numeric"
    ) in text


def test_transactions_are_newest_first_and_capped() -> None:
    text = sql("call_reason_transactions")

    assert "ORDER BY x.transaction_date DESC NULLS LAST, x.transaction_id" in text
    assert text.rstrip().endswith("LIMIT %(limit)s")


def test_transactions_read_the_latest_home_country() -> None:
    text = sql("call_reason_transactions")

    assert "ORDER BY c.last_updated DESC NULLS LAST" in text
    assert "h.country AS home_country" in text


# --- the cards, cases and app events queries ----------------------------------


@pytest.mark.parametrize("name", ["call_reason_cards", "call_reason_cases"])
def test_cards_and_cases_have_no_limit(name: str) -> None:
    assert "LIMIT" not in sql(name)


def test_cards_are_deduplicated_to_the_latest_state() -> None:
    text = sql("call_reason_cards")

    assert "SELECT DISTINCT ON (p.product_id)" in text
    assert "ORDER BY p.product_id, p.last_updated DESC NULLS LAST" in text


def test_cases_are_the_ones_open_at_as_of() -> None:
    text = sql("call_reason_cases")

    assert "k.creation_date <= %(as_of)s" in text
    assert "k.closing_date > %(as_of)s" in text
    assert "k.status NOT IN ('Resolved', 'Closed')" in text
    assert "(%(as_of)s::date - deduplicated.creation_date::date) AS days_open" in text


def test_app_events_are_errors_of_the_last_24_hours() -> None:
    text = sql("call_reason_app_events")

    assert "e.event_type = 'Error'" in text
    assert "e.event_date >  %(as_of)s - INTERVAL '24 hours'" in text
    assert "e.event_date <= %(as_of)s" in text
    assert text.rstrip().endswith("LIMIT 50")


# --- tool_spec.json ------------------------------------------------------------


def test_tool_spec_name_and_required_fields() -> None:
    spec = tool_spec()

    assert spec["name"] == "classify_call_type"
    assert spec["inputSchema"]["required"] == ["customer_id"]
    assert set(spec["inputSchema"]["properties"]) == {"customer_id"}
    assert spec["inputSchema"]["properties"]["customer_id"]["type"] == "string"


def test_tool_spec_description_names_every_reason() -> None:
    description = tool_spec()["description"]

    for reason in CallReason:
        assert reason.value in description, reason
    assert "unavailable" in description
```

- [ ] **Step 2: Run it to verify it fails**

Run: `$PY -m pytest tests/unit/classify_call_type/test_query_contracts.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: failures, among them `QueryNotFoundError` for every query and `FileNotFoundError` for `tool_spec.json`. `test_every_query_is_sent` already passes, because it only runs the use case over fakes.

- [ ] **Step 3: Write `call_reason_transactions.sql`**

The body is spec §6.1, verbatim.

```sql
-- call_reason_transactions (PostgreSQL dialect, runs on Aurora DSQL)
--
-- The charge candidates of ClassifyCallTypeUseCase: the customer's credit-card
-- charges of the last 72 hours, plus the approved ones of the last 30 days scored
-- above the review band. The SQL only narrows the candidates. Python applies every
-- reason rule, the windows included, so the rules have one owner. A failure here
-- only makes the transaction reasons unavailable.
--
-- Parameters (psycopg named placeholders):
--   customer_id   text       required (the use case strips and uppercases it)
--   as_of         timestamp  "now" as naive UTC (the AS_OF env var, or the real time)
--   review_above  numeric    REVIEW_ABOVE from the domain (30)
--   limit         integer    the candidate cap plus one (201)
--
-- fraud_score is read for banding only. Python turns it into a reason and it never
-- leaves the Lambda. Credit cards are matched exactly on
-- product_type = 'Tarjeta Crédito', a value from the dataset. home_country is the
-- customer's latest country, for FOREIGN_TRANSACTION. process_date bounds the scan
-- to the partition days of the 30-day window. Newest first, so when the cap cuts,
-- the oldest charges are the ones dropped.
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster. DISTINCT ON,
--   RIGHT(), interval arithmetic and the binds are standard PostgreSQL, but DSQL
--   support is unverified. Column names follow docs/LATAM_Bank_ERD.md; smoke-test
--   against a real cluster.
-- TODO(ledgerlens): R8 - about 2 in 100 rows are duplicated; DISTINCT ON removes
--   them at query time. Drop it once the data load deduplicates.
WITH tx_dedup AS (
    SELECT DISTINCT ON (t.transaction_id)
           t.transaction_id, t.transaction_date,
           RIGHT(p.product_number, 4) AS card_last4,
           p.currency                 AS card_currency,
           t.merchant_name, t.amount, t.currency, t.transaction_status,
           t.response_code, t.transaction_country, t.fraud_score
    FROM transactions AS t
    JOIN products AS p ON p.product_id = t.product_id
    WHERE t.customer_id = %(customer_id)s
      AND p.product_type = 'Tarjeta Crédito'
      AND t.process_date >= (%(as_of)s::date - 31)
      AND t.transaction_date >= %(as_of)s - INTERVAL '30 days'
      AND t.transaction_date <= %(as_of)s
    ORDER BY t.transaction_id, t.transaction_date DESC NULLS LAST
),
home AS (
    SELECT c.country FROM customers AS c
    WHERE c.customer_id = %(customer_id)s
    ORDER BY c.last_updated DESC NULLS LAST
    LIMIT 1
)
SELECT x.*, h.country AS home_country
FROM tx_dedup AS x
LEFT JOIN home AS h ON TRUE
WHERE x.transaction_date >= %(as_of)s - INTERVAL '72 hours'
   OR (x.transaction_status = 'Approved' AND x.fraud_score > %(review_above)s::numeric)
ORDER BY x.transaction_date DESC NULLS LAST, x.transaction_id
LIMIT %(limit)s
```

- [ ] **Step 4: Write `call_reason_cards.sql`**

The body is `session_credit_cards.sql`'s de-duplication, narrowed to the four columns and with no `LIMIT`.

```sql
-- call_reason_cards (PostgreSQL dialect, runs on Aurora DSQL)
--
-- The card candidates of ClassifyCallTypeUseCase: the customer's credit cards in
-- every status, one row per product_id at its latest state. Python decides
-- CARD_NOT_ACTIVE, PAYMENT_OVERDUE and CARD_EXPIRING. A failure here only makes
-- the card reasons unavailable. There is no LIMIT: a customer has a handful of
-- cards. The deduplication is the one in get_session_context's
-- session_credit_cards.sql (copies, not shared code).
--
-- Parameters (psycopg named placeholders):
--   customer_id  text  required (the use case strips and uppercases it)
--
-- Credit cards are matched exactly on product_type = 'Tarjeta Crédito', a value
-- from the dataset. product_id is selected only for the deduplication and the
-- final tie-break; the use case doesn't map it. product_status is today's state,
-- even on a past AS_OF (risk K4, accepted for demos).
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster. DISTINCT ON,
--   RIGHT(), NULLS LAST and the binds are standard PostgreSQL, but DSQL support is
--   unverified. Column names follow docs/LATAM_Bank_ERD.md; smoke-test against a
--   real cluster.
-- TODO(ledgerlens): R8 - about 2 in 100 rows are duplicated; DISTINCT ON removes
--   them at query time, keeping the latest last_updated. Drop it once the data
--   load deduplicates.
SELECT deduplicated.card_last4,
       deduplicated.product_status,
       deduplicated.expiration_date,
       deduplicated.days_past_due
FROM (
    SELECT DISTINCT ON (p.product_id)
           p.product_id,
           RIGHT(p.product_number, 4)  AS card_last4,
           p.product_status,
           p.expiration_date,
           p.days_past_due
    FROM products AS p
    WHERE p.customer_id = %(customer_id)s
      AND p.product_type = 'Tarjeta Crédito'
    ORDER BY p.product_id, p.last_updated DESC NULLS LAST
) AS deduplicated
ORDER BY deduplicated.card_last4, deduplicated.product_id
```

- [ ] **Step 5: Write `call_reason_cases.sql`**

The body is `session_open_cases.sql`'s open-at-`as_of` filter and de-duplication, narrowed to the `CaseCandidate` columns and with no `LIMIT`.

```sql
-- call_reason_cases (PostgreSQL dialect, runs on Aurora DSQL)
--
-- The case candidates of ClassifyCallTypeUseCase: complaints and claims open at
-- as_of, SLA breaches first, then the newest. Every row is OPEN_CASE_FOLLOWUP;
-- Python picks the best (a breached case, then the lowest complaint_id), so the
-- order here is only for reading. A failure here only makes OPEN_CASE_FOLLOWUP
-- unavailable. There is no LIMIT: a customer has few open cases. The filter is the
-- one in get_session_context's session_open_cases.sql (copies, not shared code).
--
-- Parameters (psycopg named placeholders):
--   customer_id  text       required (the use case strips and uppercases it)
--   as_of        timestamp  "now" as naive UTC (the AS_OF env var, or the real time)
--
-- "Open at as_of" means created on or before as_of and not closed by then, so a
-- case closed today still counts on a past demo date. status is returned as it is
-- stored now (risk K4, accepted for demos). Some Resolved/Closed rows have no
-- closing_date; without a date, status decides, so those don't show up as open
-- forever. date minus date is an integer in PostgreSQL, so days_open maps to an int.
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster. Column
--   names follow docs/LATAM_Bank_ERD.md; smoke-test against a real cluster.
-- TODO(ledgerlens): R8 - about 2 in 100 rows are duplicated; DISTINCT ON removes
--   them at query time, keeping the latest process_date. Drop it once the data
--   load deduplicates.
SELECT deduplicated.complaint_id,
       deduplicated.case_type,
       deduplicated.category,
       deduplicated.subcategory,
       deduplicated.status,
       deduplicated.sla_breached,
       (%(as_of)s::date - deduplicated.creation_date::date) AS days_open
FROM (
    SELECT DISTINCT ON (k.complaint_id) k.*
    FROM complaints AS k
    WHERE k.customer_id = %(customer_id)s
      AND k.creation_date <= %(as_of)s
      AND (k.closing_date > %(as_of)s
           OR (k.closing_date IS NULL AND k.status NOT IN ('Resolved', 'Closed')))
    ORDER BY k.complaint_id, k.process_date DESC NULLS LAST
) AS deduplicated
ORDER BY deduplicated.sla_breached DESC NULLS LAST,
         deduplicated.creation_date DESC NULLS LAST,
         deduplicated.complaint_id
```

- [ ] **Step 6: Write `call_reason_app_events.sql`**

The body is spec §6.4, verbatim. Ruling 9: the `>` on the 24 h edge is kept.

```sql
-- call_reason_app_events (PostgreSQL dialect, runs on Aurora DSQL)
--
-- The app-event candidates of ClassifyCallTypeUseCase: the customer's app or web
-- errors of the last 24 hours, newest first. Every row is FAILED_APP_ACTION;
-- Python keeps the newest. event_type = 'Error' is the same mapping as
-- get_session_context's FAILED_ACTION signal. A failure here only makes
-- FAILED_APP_ACTION unavailable. process_date bounds the scan to the partition
-- days of the window.
--
-- Parameters (psycopg named placeholders):
--   customer_id  text       required (the use case strips and uppercases it)
--   as_of        timestamp  "now" as naive UTC (the AS_OF env var, or the real time)
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster. Interval
--   arithmetic and the binds are standard PostgreSQL, but DSQL support is
--   unverified. Column names follow docs/LATAM_Bank_ERD.md; smoke-test against a
--   real cluster. digital_events has no index on customer_id; time this query on
--   the deployed stack.
SELECT e.event_id, e.event_date, e.page_title, e.action
FROM digital_events AS e
WHERE e.customer_id = %(customer_id)s
  AND e.event_type = 'Error'
  AND e.process_date >= (%(as_of)s::date - 1)
  AND e.event_date >  %(as_of)s - INTERVAL '24 hours'
  AND e.event_date <= %(as_of)s
ORDER BY e.event_date DESC NULLS LAST, e.event_id
LIMIT 50
```

- [ ] **Step 7: Write `gateway/tools/classify_call_type/tool_spec.json`**

This is spec §5.1, verbatim. Keep the description on one line.

```json
[
  {
    "name": "classify_call_type",
    "description": "Ranks up to 3 likely reasons the customer is contacting the bank right now, best first, each with a confidence from 0 to 1, the record it points to (ref_id: a transaction_id, complaint_id, event_id or card last4) and evidence. Reasons: FRAUD_SUSPECTED (the fraud engine flagged an approved charge in the last 30 days), UNRECOGNIZED_CHARGE_REVIEW (a charge the engine wants the customer to confirm), DECLINED_TRANSACTION, PENDING_TRANSACTION and REVERSED_TRANSACTION (last 72 hours), OPEN_CASE_FOLLOWUP, CARD_NOT_ACTIVE (blocked or suspended card), FAILED_APP_ACTION (an app or web error in the last 24 hours), FOREIGN_TRANSACTION (approved charge abroad or in another currency, last 72 hours), PAYMENT_OVERDUE, CARD_EXPIRING (within 30 days). These are hypotheses to open the conversation with, not facts: confirm with the customer. An empty list means nothing stands out; ask how you can help. 'unavailable' names reasons that couldn't be checked. Call it at the start of the conversation.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "customer_id": { "type": "string", "description": "The authenticated customer's ID from SESSION CONTEXT." }
      },
      "required": ["customer_id"]
    }
  }
]
```

- [ ] **Step 8: Run it to verify it passes**

Run: `$PY -m pytest tests/unit/classify_call_type/test_query_contracts.py -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: `45 passed`

- [ ] **Step 9: Lint and check isolation**

```bash
$PY -m ruff format gateway/tools/classify_call_type tests/unit/classify_call_type </dev/null
$PY -m ruff check gateway/tools/classify_call_type tests/unit/classify_call_type </dev/null
grep -rnE "(get_session_context|list_credit_cards|list_card_transactions|transaction_fraud_detection|explain_transaction)_lambda" gateway/tools/classify_call_type tests/unit/classify_call_type
```

Expected: `ruff check` is clean and the grep prints nothing. The SQL headers name `get_session_context` and its files without `_lambda`, which is allowed.

---

### Task 7: The presenter

**Files:**
- Create: `delivery/presenters/call_classification.py`
- Test: `tests/unit/classify_call_type/test_call_classification_presenter.py`

**Interfaces:**
- Consumes: Task 4 (the candidates, `RankedReason`, `CallClassification`), Task 3 (`CallReason`) and Task 1 (`fakes.TRANSACTION_ID`, `CHARGE_DATE`).
- Produces: `classify_call_type_lambda.delivery.presenters.call_classification.present_call_classification(classification: CallClassification) -> dict[str, Any]`. The handler (Task 9) returns it as the tool's JSON body.

- [ ] **Step 1: Write the failing test**

`tests/unit/classify_call_type/test_call_classification_presenter.py`:

```python
"""Tests for the call classification presenter (spec section 5)."""

import dataclasses
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest
from classify_call_type_lambda.delivery.presenters.call_classification import (
    present_call_classification,
)
from classify_call_type_lambda.domain.entities.call_classification import (
    CallClassification,
    Candidate,
    RankedReason,
)
from classify_call_type_lambda.domain.entities.candidates import (
    AppEventCandidate,
    CardCandidate,
    CaseCandidate,
    TransactionCandidate,
)
from classify_call_type_lambda.domain.value_objects.call_reasons import CallReason

from .fakes import CHARGE_DATE, TRANSACTION_ID

pytestmark = pytest.mark.unit

R = CallReason
TODAY = date(2026, 6, 17)

# Spec section 5, verbatim: P07's flagged charge as the agent sees it.
P07_JSON = """
{
  "reasons": [
    {
      "reason": "FRAUD_SUSPECTED",
      "confidence": 0.77,
      "ref_id": "TRX-23BIJAU4GL46ATPW9STY",
      "evidence": {
        "transaction_date": "2026-05-31T06:09:15",
        "card_last4": "4497",
        "merchant_name": "Estación de Servicio",
        "amount": "288.69",
        "currency": "USD",
        "transaction_status": "Approved"
      }
    }
  ],
  "unavailable": []
}
"""

CHARGE = TransactionCandidate(
    transaction_id=TRANSACTION_ID,
    transaction_date=CHARGE_DATE,
    card_last4="4497",
    card_currency="USD",
    merchant_name="Estación de Servicio",
    amount=Decimal("288.69"),
    currency="USD",
    transaction_status="Approved",
    response_code="00",
    transaction_country="México",
    home_country="México",
    fraud_score=Decimal("62.37"),
)
CARD = CardCandidate(
    card_last4="7718",
    product_status="Active",
    expiration_date=date(2026, 7, 1),
    days_past_due=45,
)
CASE = CaseCandidate(
    complaint_id="CMP-FHCLR8TGWMBD0YFOCLYS",
    case_type="Claim",
    category="Cards",
    subcategory="Unrecognized charge",
    status="In Progress",
    sla_breached=None,
    days_open=12,
)
EVENT = AppEventCandidate(
    event_id="EVT-0001",
    event_date=datetime(2026, 6, 17, 21, 59, 59),
    page_title="Pagar Servicios",
    action="submit_payment",
)

TRANSACTION_KEYS = {
    "transaction_date",
    "card_last4",
    "merchant_name",
    "amount",
    "currency",
    "transaction_status",
}
EVIDENCE_KEYS: dict[CallReason, set[str]] = {
    R.FRAUD_SUSPECTED: TRANSACTION_KEYS,
    R.DECLINED_TRANSACTION: TRANSACTION_KEYS | {"response_code"},
    R.UNRECOGNIZED_CHARGE_REVIEW: TRANSACTION_KEYS,
    R.OPEN_CASE_FOLLOWUP: {
        "case_type",
        "category",
        "subcategory",
        "status",
        "sla_breached",
        "days_open",
    },
    R.PENDING_TRANSACTION: TRANSACTION_KEYS,
    R.REVERSED_TRANSACTION: TRANSACTION_KEYS,
    R.CARD_NOT_ACTIVE: {"card_last4", "product_status"},
    R.FAILED_APP_ACTION: {"event_date", "page_title", "action"},
    R.FOREIGN_TRANSACTION: TRANSACTION_KEYS
    | {"transaction_country", "home_country", "card_currency"},
    R.PAYMENT_OVERDUE: {"card_last4", "days_past_due"},
    R.CARD_EXPIRING: {"card_last4", "expiration_date", "days_left"},
}
CANDIDATE_OF: dict[CallReason, Candidate] = {
    R.FRAUD_SUSPECTED: CHARGE,
    R.DECLINED_TRANSACTION: CHARGE,
    R.UNRECOGNIZED_CHARGE_REVIEW: CHARGE,
    R.OPEN_CASE_FOLLOWUP: CASE,
    R.PENDING_TRANSACTION: CHARGE,
    R.REVERSED_TRANSACTION: CHARGE,
    R.CARD_NOT_ACTIVE: CARD,
    R.FAILED_APP_ACTION: EVENT,
    R.FOREIGN_TRANSACTION: CHARGE,
    R.PAYMENT_OVERDUE: CARD,
    R.CARD_EXPIRING: CARD,
}
REF_ID_OF: dict[type, str] = {
    TransactionCandidate: TRANSACTION_ID,
    CaseCandidate: "CMP-FHCLR8TGWMBD0YFOCLYS",
    CardCandidate: "7718",
    AppEventCandidate: "EVT-0001",
}


def ranked(
    reason: CallReason,
    candidate: Candidate | None = None,
    confidence: str = "0.77",
) -> RankedReason:
    """Rank one reason over its default candidate."""
    candidate = candidate or CANDIDATE_OF[reason]
    return RankedReason(
        reason=reason,
        confidence=Decimal(confidence),
        ref_id=REF_ID_OF[type(candidate)],
        candidate=candidate,
    )


def present(*reasons: RankedReason, unavailable: tuple[CallReason, ...] = ()) -> dict[str, Any]:
    """Present a classification as of TODAY."""
    return present_call_classification(
        CallClassification(reasons=reasons, unavailable=unavailable, as_of_date=TODAY)
    )


def evidence(item: RankedReason) -> dict[str, Any]:
    """Present one reason and return its evidence."""
    return present(item)["reasons"][0]["evidence"]


def keys(value: object) -> set[str]:
    """Return every dict key at any depth."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys(v)}
    return set()


# --- the whole body ----------------------------------------------------------


def test_p07_matches_the_spec_example() -> None:
    assert present(ranked(R.FRAUD_SUSPECTED)) == json.loads(P07_JSON)


def test_nothing_found_is_two_empty_lists() -> None:
    assert present() == {"reasons": [], "unavailable": []}


def test_unavailable_lists_the_reason_names_in_order() -> None:
    body = present(unavailable=(R.OPEN_CASE_FOLLOWUP, R.FAILED_APP_ACTION))

    assert body["unavailable"] == ["OPEN_CASE_FOLLOWUP", "FAILED_APP_ACTION"]


def test_reasons_keep_their_order() -> None:
    body = present(
        ranked(R.DECLINED_TRANSACTION, confidence="0.84"),
        ranked(R.OPEN_CASE_FOLLOWUP, confidence="0.60"),
        ranked(R.CARD_EXPIRING, confidence="0.35"),
    )

    assert [item["reason"] for item in body["reasons"]] == [
        "DECLINED_TRANSACTION",
        "OPEN_CASE_FOLLOWUP",
        "CARD_EXPIRING",
    ]
    assert [item["ref_id"] for item in body["reasons"]] == [
        TRANSACTION_ID,
        "CMP-FHCLR8TGWMBD0YFOCLYS",
        "7718",
    ]


def test_output_survives_a_json_round_trip() -> None:
    body = present(*(ranked(reason) for reason in CallReason))

    assert json.loads(json.dumps(body, ensure_ascii=False)) == body


# --- confidence -------------------------------------------------------------


@pytest.mark.parametrize(
    ("confidence", "expected"), [("0.60", 0.6), ("0.77", 0.77), ("1.00", 1.0)]
)
def test_confidence_is_a_json_number(confidence: str, expected: float) -> None:
    value = present(ranked(R.FRAUD_SUSPECTED, confidence=confidence))["reasons"][0][
        "confidence"
    ]

    assert type(value) is float
    assert value == expected


# --- evidence ---------------------------------------------------------------


@pytest.mark.parametrize("reason", list(CallReason))
def test_evidence_keys_per_reason(reason: CallReason) -> None:
    assert set(evidence(ranked(reason))) == EVIDENCE_KEYS[reason]


def test_declined_evidence_has_the_response_code() -> None:
    charge = dataclasses.replace(
        CHARGE, transaction_status="Declined", response_code="51"
    )

    assert evidence(ranked(R.DECLINED_TRANSACTION, charge)) == {
        "transaction_date": "2026-05-31T06:09:15",
        "card_last4": "4497",
        "merchant_name": "Estación de Servicio",
        "amount": "288.69",
        "currency": "USD",
        "transaction_status": "Declined",
        "response_code": "51",
    }


def test_foreign_evidence_has_both_countries_and_the_card_currency() -> None:
    charge = dataclasses.replace(
        CHARGE, transaction_country="Brasil", currency="BRL", card_currency="USD"
    )

    found = evidence(ranked(R.FOREIGN_TRANSACTION, charge))

    assert found["transaction_country"] == "Brasil"
    assert found["home_country"] == "México"
    assert found["currency"] == "BRL"
    assert found["card_currency"] == "USD"


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("288.685"), "288.69"),
        (Decimal("288.684"), "288.68"),
        (Decimal("1E+3"), "1000.00"),
        (Decimal("12"), "12.00"),
        (None, None),
    ],
)
def test_amounts_are_two_decimal_strings(
    amount: Decimal | None, expected: str | None
) -> None:
    charge = dataclasses.replace(CHARGE, amount=amount)

    assert evidence(ranked(R.FRAUD_SUSPECTED, charge))["amount"] == expected


def test_missing_transaction_values_stay_null() -> None:
    charge = TransactionCandidate(
        transaction_id=TRANSACTION_ID,
        transaction_date=None,
        card_last4=None,
        card_currency=None,
        merchant_name=None,
        amount=None,
        currency=None,
        transaction_status=None,
        response_code=None,
        transaction_country=None,
        home_country=None,
        fraud_score=None,
    )

    found = evidence(ranked(R.FOREIGN_TRANSACTION, charge))

    assert set(found.values()) == {None}


def test_case_evidence() -> None:
    assert evidence(ranked(R.OPEN_CASE_FOLLOWUP)) == {
        "case_type": "Claim",
        "category": "Cards",
        "subcategory": "Unrecognized charge",
        "status": "In Progress",
        "sla_breached": None,
        "days_open": 12,
    }


def test_card_not_active_evidence() -> None:
    card = dataclasses.replace(CARD, product_status="Blocked")

    assert evidence(ranked(R.CARD_NOT_ACTIVE, card)) == {
        "card_last4": "7718",
        "product_status": "Blocked",
    }


def test_payment_overdue_evidence() -> None:
    assert evidence(ranked(R.PAYMENT_OVERDUE)) == {
        "card_last4": "7718",
        "days_past_due": 45,
    }


@pytest.mark.parametrize(
    ("expiration_date", "iso", "days_left"),
    [
        (date(2026, 6, 17), "2026-06-17", 0),
        (date(2026, 6, 18), "2026-06-18", 1),
        (date(2026, 7, 17), "2026-07-17", 30),
        (None, None, None),
    ],
)
def test_card_expiring_days_left(
    expiration_date: date | None, iso: str | None, days_left: int | None
) -> None:
    card = dataclasses.replace(CARD, expiration_date=expiration_date)

    assert evidence(ranked(R.CARD_EXPIRING, card)) == {
        "card_last4": "7718",
        "expiration_date": iso,
        "days_left": days_left,
    }


def test_app_event_evidence() -> None:
    assert evidence(ranked(R.FAILED_APP_ACTION)) == {
        "event_date": "2026-06-17T21:59:59",
        "page_title": "Pagar Servicios",
        "action": "submit_payment",
    }


def test_no_key_mentions_fraud_or_score() -> None:
    body = present(*(ranked(reason) for reason in CallReason))

    all_keys = keys(body)
    assert "days_left" in all_keys  # the walk reached the evidence
    assert not [key for key in all_keys if "fraud" in key or "score" in key]
    assert "62.37" not in json.dumps(body)  # the score's value isn't leaked either
```

- [ ] **Step 2: Run it to verify it fails**

Run: `$PY -m pytest tests/unit/classify_call_type/test_call_classification_presenter.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: a collection error, `ModuleNotFoundError: No module named 'classify_call_type_lambda.delivery.presenters.call_classification'`.

- [ ] **Step 3: Write `delivery/presenters/call_classification.py`**

`_iso` and `_amount` are copied from `explain_transaction`'s presenter.

```python
"""Present a call classification as the JSON returned to the agent."""

from collections.abc import Mapping
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from classify_call_type_lambda.domain.entities.call_classification import (
    CallClassification,
    RankedReason,
)
from classify_call_type_lambda.domain.entities.candidates import (
    AppEventCandidate,
    CardCandidate,
    CaseCandidate,
    TransactionCandidate,
)
from classify_call_type_lambda.domain.value_objects.call_reasons import CallReason

_CENTS: Final = Decimal("0.01")

# The evidence a transaction reason adds to the common charge keys (spec section 5).
_TRANSACTION_EXTRA_KEYS: Final[Mapping[CallReason, tuple[str, ...]]] = {
    CallReason.DECLINED_TRANSACTION: ("response_code",),
    CallReason.FOREIGN_TRANSACTION: (
        "transaction_country",
        "home_country",
        "card_currency",
    ),
}


def present_call_classification(classification: CallClassification) -> dict[str, Any]:
    """Return the classification as JSON-safe values (spec section 5).

    confidence is a JSON number (a float of the 2-decimal Decimal). Amounts are
    2-decimal strings rounded half up. Timestamps are ISO 8601 without a time
    zone, as stored. Missing values stay None. No key holds a fraud score.
    """
    return {
        "reasons": [
            _reason(ranked, classification.as_of_date)
            for ranked in classification.reasons
        ],
        "unavailable": [reason.value for reason in classification.unavailable],
    }


def _reason(ranked: RankedReason, as_of_date: date) -> dict[str, Any]:
    """Present one ranked reason with its evidence."""
    return {
        "reason": ranked.reason.value,
        "confidence": float(ranked.confidence),
        "ref_id": ranked.ref_id,
        "evidence": _evidence(ranked, as_of_date),
    }


def _evidence(ranked: RankedReason, as_of_date: date) -> dict[str, Any]:
    """Pick the evidence builder for the candidate's type."""
    candidate = ranked.candidate
    if isinstance(candidate, TransactionCandidate):
        return _transaction_evidence(ranked.reason, candidate)
    if isinstance(candidate, CardCandidate):
        return _card_evidence(ranked.reason, candidate, as_of_date)
    if isinstance(candidate, CaseCandidate):
        return _case_evidence(candidate)
    return _app_event_evidence(candidate)


def _transaction_evidence(
    reason: CallReason, charge: TransactionCandidate
) -> dict[str, Any]:
    """The charge keys, plus the extra keys of DECLINED and FOREIGN."""
    values: dict[str, Any] = {
        "transaction_date": _iso(charge.transaction_date),
        "card_last4": charge.card_last4,
        "merchant_name": charge.merchant_name,
        "amount": _amount(charge.amount),
        "currency": charge.currency,
        "transaction_status": charge.transaction_status,
    }
    extras = {
        "response_code": charge.response_code,
        "transaction_country": charge.transaction_country,
        "home_country": charge.home_country,
        "card_currency": charge.card_currency,
    }
    for key in _TRANSACTION_EXTRA_KEYS.get(reason, ()):
        values[key] = extras[key]
    return values


def _card_evidence(
    reason: CallReason, card: CardCandidate, as_of_date: date
) -> dict[str, Any]:
    """The card's last 4 digits and the one fact behind its reason.

    Raises:
        ValueError: The reason isn't a card reason (a ranking bug).
    """
    if reason is CallReason.CARD_NOT_ACTIVE:
        return {"card_last4": card.card_last4, "product_status": card.product_status}
    if reason is CallReason.PAYMENT_OVERDUE:
        return {"card_last4": card.card_last4, "days_past_due": card.days_past_due}
    if reason is CallReason.CARD_EXPIRING:
        return {
            "card_last4": card.card_last4,
            "expiration_date": _iso(card.expiration_date),
            "days_left": (
                None
                if card.expiration_date is None
                else (card.expiration_date - as_of_date).days
            ),
        }
    raise ValueError(f"{reason.value} is not a card reason")


def _case_evidence(case: CaseCandidate) -> dict[str, Any]:
    """The open case, without its complaint_id (that is the ref_id)."""
    return {
        "case_type": case.case_type,
        "category": case.category,
        "subcategory": case.subcategory,
        "status": case.status,
        "sla_breached": case.sla_breached,
        "days_open": case.days_open,
    }


def _app_event_evidence(event: AppEventCandidate) -> dict[str, Any]:
    """The failed app action, without its event_id (that is the ref_id)."""
    return {
        "event_date": _iso(event.event_date),
        "page_title": event.page_title,
        "action": event.action,
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

- [ ] **Step 4: Run it to verify it passes**

Run: `$PY -m pytest tests/unit/classify_call_type/test_call_classification_presenter.py -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: `36 passed`

- [ ] **Step 5: Lint**

Run: `$PY -m ruff format gateway/tools/classify_call_type tests/unit/classify_call_type </dev/null && $PY -m ruff check gateway/tools/classify_call_type tests/unit/classify_call_type </dev/null`
Expected: `ruff check` is clean. Re-run the tests if formatting changed anything.

---
