# get_session_context Lambda Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- Add an optional `AS_OF` env var ("now" for demos) to the two existing tool Lambdas.
- Build the `get_session_context` Gateway tool Lambda as a self-contained folder, `gateway/tools/get_session_context/get_session_context_lambda/`. It returns one snapshot of the customer: profile, credit cards, 72-hour transactions with risk flags, 24-hour app/web signals and open cases.

**Architecture:**
- Task 1 adds `ClockSettings` and `build_clock` to `list_credit_cards` and `list_card_transactions`. Each handler reads "now" from `CLOCK.now()` on every call.
- Task 2 copies `list_credit_cards` (which now has the clock) file by file into the new folder, with only the package name changed.
- The domain errors, entities, use case, five SQL files, presenter, handler and `tool_spec.json` are this tool's own.
- The use case runs five queries one after another on the single autocommit connection:
  - The customer section is required. Its failure fails the call with one fixed message.
  - Each of the other four sections fails on its own: it comes back `None` and is named in `unavailable`.

**Tech Stack:** Python 3.13 (project `.venv`), pytest, ruff, psycopg 3, boto3, Git Bash on Windows.

**Spec:** `docs/superpowers/specs/2026-10-01-get-session-context-lambda-design.md`. Layout rules: `docs/superpowers/specs/2026-10-01-self-contained-tool-folders-design.md`.

## Global Constraints

- Python: `PY=.venv/Scripts/python`. Run every command from the repo root `C:\GITHUB REPOS\ledgerlens-bank-assistant` in Git Bash. Add `</dev/null` to `$PY` commands so nothing waits on stdin. Never use Anaconda.
- **Do not commit during execution.** The user commits once, on their command, at the end. Never run `git commit` or `git add`.
- Never stage `infra-cdk/config.yaml`, `frontend/public/aws-exports.json` or `frontend/.env`.
- No AWS deploys, no CDK changes, no push and no merge.
- **Self-contained:**
  - Nothing in `get_session_context` imports from another tool.
  - The only changes to the other two tools are Task 1's `AS_OF` changes.
  - Code is copied, never shared.
- **Copy rule:**
  - Copy from `gateway/tools/list_credit_cards/` **after Task 1**, so the copy already has `ClockSettings` and `build_clock`.
  - Copied files only get `list_credit_cards` → `get_session_context`. Task 7 also renames `ListCreditCardsUseCase` → `GetSessionContextUseCase`.
  - Never copy `__pycache__`.
- Names (spec §3):
  - asset folder: `gateway/tools/get_session_context/`
  - package: `get_session_context_lambda`
  - handler string: `get_session_context_lambda/delivery/handler.handler`
  - tool name: `get_session_context`
  - test package: `tests/unit/get_session_context/`
- Query (file) names, unchanged from the spec:
  - `session_customer_profile`
  - `session_credit_cards`
  - `session_recent_transactions`
  - `session_digital_signals`
  - `session_open_cases`
- Keep names specific: `database_repository`, `query_provider`.
- Exact values from the spec:
  - `AS_OF` error: `AS_OF must be an ISO 8601 date or timestamp, got '<raw>'`.
  - Clock log line: `Invalid AS_OF for <tool>`.
  - Caps: `max_rows` (default 25) for cards, transactions and signals; `min(5, max_rows)` for open cases. Each query sends `limit = cap + 1`.
  - Bad id message: `Invalid value for 'customer_id': is required and must be a non-empty string. Ask the customer to confirm and retry.`
  - Section warning: `get_session_context section %s unavailable`.
  - Handler log: `%s returned context (unavailable=%s, truncated=%s)`.
  - Fixed messages (spec §6.2) and the unexpected-error message (spec §6.3): copy them verbatim from Task 3 and Task 8.
- Keep the `TODO(ledgerlens): Rn` tags and the role name `ledgerlens_readonly` exactly as they are.
- `datetime.fromisoformat` must accept `Z` and a bare date. That needs Python 3.11 or later. The venv is 3.13; the CDK runtime choice (R1) must be 3.11 or later too.
- Lint: `$PY -m ruff format --check <paths>` and `$PY -m ruff check <paths>`. Fix formatting with `$PY -m ruff format <paths>`.
- Baseline before Task 1: `$PY -m pytest tests/unit -q -p no:cacheprovider` → `515 passed`.
- **Plan rulings on the spec:**
  - §10.2 lists `test_errors.py` as "copied with imports changed". The fixed messages differ (§6.2), so Task 3 rewrites it. §6.2 wins.
  - §9 doesn't mention §7.1's `tool_spec.json` block in the product design. That block says it's exactly what the model sees, so Task 9 replaces it with §4.6's.
  - `tool_spec.json` is created in Task 5, with the contract tests that check it, not in Task 8.

## Review Focus

1. **One non-core section fails** (for example, DSQL rejects `percentile_cont` in the transactions query, or a row has an odd type). Expected: that section is `null` and named in `unavailable`, every other section is still returned, and the agent never sees an error. *Pinned by Task 4, `test_a_failed_section_is_none_and_listed_unavailable` and `test_an_unmappable_row_makes_only_its_section_unavailable`, and Task 8, `test_a_failed_section_comes_back_null_and_unavailable`.*
2. **`AS_OF` written with an offset, a `Z` or as a bare date.** Expected: it's converted to aware UTC, and the SQL receives the same instant as naive UTC. *Pinned by Task 1, `test_as_of_is_parsed_as_utc`, and Task 4, `test_an_aware_as_of_in_another_zone_is_sent_as_naive_utc`.*
3. **A warm container reused across calls with `AS_OF` unset.** Expected: "now" is read on every call, never frozen at cold start. *Pinned by Task 1, `test_now_is_the_real_utc_time_when_unset` and `test_without_as_of_date_to_is_today`, and Task 8, `test_now_is_read_on_every_call`.*
4. **A `NULL` flag** (unknown country, no history) **or a non-bool flag from the driver.** Expected: `NULL` is "not flagged". A non-bool makes only the transactions section unavailable. *Pinned by Task 4, `test_null_flags_mean_not_flagged` and `test_a_non_bool_flag_makes_only_transactions_unavailable`.*
5. **Cap boundaries and small `MAX_ROWS`.** Expected:
   - 26 rows give 25 plus `truncated`, and 25 rows aren't truncated.
   - Open cases cut at 5 (6 rows → 5 plus `truncated`).
   - With `MAX_ROWS=3`, open cases are capped at 3.

   *Pinned by Task 4, `test_each_list_is_capped_and_marked_truncated`, `test_exactly_the_cap_is_not_truncated` and `test_max_rows_below_five_caps_open_cases`.*

---

## File map

| Path | Task | Kind |
|---|---|---|
| `gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/settings.py` | 1 | modified (`ClockSettings`) |
| `gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/dependencies/dependencies_builder.py` | 1 | modified (`build_clock`) |
| `gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/handler.py` | 1 | modified (`CLOCK` guard) |
| `gateway/tools/list_card_transactions/list_card_transactions_lambda/delivery/{settings,handler}.py`, `.../dependencies/dependencies_builder.py` | 1 | modified (same, plus `today` from `CLOCK`) |
| `tests/unit/list_credit_cards/test_{settings,delivery_wiring,list_credit_cards_handler}.py` | 1 | modified |
| `tests/unit/list_card_transactions/test_{settings,delivery_wiring,list_card_transactions_handler}.py` | 1 | modified |
| `gateway/tools/get_session_context/requirements.txt` | 2 | copied |
| `get_session_context_lambda/**/__init__.py` (14 files) | 2 | copied |
| `get_session_context_lambda/application/ports/{database_repository,query_provider,errors}.py` | 2 | copied |
| `get_session_context_lambda/infrastructure/queries/file_query_provider.py` | 2 | copied |
| `get_session_context_lambda/infrastructure/repositories/dsql_repository.py` | 2 | copied |
| `get_session_context_lambda/utils/connectors/{base,dsql}.py` | 2 | copied |
| `get_session_context_lambda/delivery/settings.py` | 2 | copied |
| `tests/unit/get_session_context/{__init__,conftest,fakes}.py` | 2 | new or adapted |
| `tests/unit/get_session_context/test_{settings,file_query_provider,dsql_repository,psycopg_connector,dsql_connector}.py` | 2 | copied |
| `get_session_context_lambda/domain/errors.py` + `tests/.../test_errors.py` | 3 | new (base classes copied) |
| `get_session_context_lambda/domain/entities/session_context.py` | 4 | new |
| `get_session_context_lambda/application/use_cases/get_session_context.py` + `tests/.../test_get_session_context_use_case.py` | 4 | new |
| `get_session_context_lambda/queries/postgresql/session_*.sql` (5 files) | 5 | new (`session_credit_cards.sql` copied) |
| `gateway/tools/get_session_context/tool_spec.json` + `tests/.../test_query_contracts.py` | 5 | new |
| `get_session_context_lambda/delivery/presenters/session_context.py` + `tests/.../test_session_context_presenter.py` | 6 | new |
| `get_session_context_lambda/delivery/dependencies/dependencies_builder.py` + `tests/.../test_delivery_wiring.py` | 7 | copied, then renamed |
| `get_session_context_lambda/delivery/handler.py` + `tests/.../test_get_session_context_handler.py` | 8 | new (shape copied) |
| `docs/LEDGERLENS_PRODUCT_DESIGN.md` | 9 | modified (§7, §7.1, §17) |

---

### Task 1: `AS_OF` in `list_credit_cards` and `list_card_transactions`

**Files:**
- Modify: `gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/settings.py`
- Modify: `gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/dependencies/dependencies_builder.py`
- Modify: `gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/handler.py`
- Modify: the same three files under `gateway/tools/list_card_transactions/list_card_transactions_lambda/`
- Test: `tests/unit/list_credit_cards/test_settings.py`, `test_delivery_wiring.py`, `test_list_credit_cards_handler.py`
- Test: `tests/unit/list_card_transactions/test_settings.py`, `test_delivery_wiring.py`, `test_list_card_transactions_handler.py`

**Interfaces:**
- Consumes: nothing new.
- Produces (in each of the two tools, later copied into the third):
  - `delivery.settings.ClockSettings(as_of: datetime | None)`, with `ClockSettings.from_env(env) -> ClockSettings` and `.now() -> datetime` (aware UTC).
  - `delivery.dependencies.dependencies_builder.build_clock(env) -> ClockSettings | None`
  - `delivery.handler.CLOCK`, a module global next to `USE_CASE`.

Each step is written for `list_credit_cards` first, with the `list_card_transactions` difference given right after it. The two `settings.py` files are identical apart from the package name, and so are the two sets of settings tests.

- [ ] **Step 1: Write the failing settings tests (both tools)**

In `tests/unit/list_credit_cards/test_settings.py`, add `ClockSettings` to the settings import and add these imports at the top:

```python
from datetime import datetime, timedelta, timezone

import pytest
from list_credit_cards_lambda.delivery.settings import (
    ClockSettings,
    ConfigurationError,
    DatabaseEngine,
    DatabaseSettings,
    DsqlSettings,
)
```

Append to the end of the file:

```python
UTC = timezone.utc


def test_as_of_is_unset_by_default() -> None:
    assert ClockSettings.from_env({}) == ClockSettings(as_of=None)


@pytest.mark.parametrize("raw", ["", "   "])
def test_a_blank_as_of_uses_the_real_clock(raw: str) -> None:
    assert ClockSettings.from_env({"AS_OF": raw}).as_of is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-03-14", datetime(2026, 3, 14, tzinfo=UTC)),
        ("2026-03-14T10:30:00", datetime(2026, 3, 14, 10, 30, tzinfo=UTC)),
        ("2026-03-14T10:30:00-05:00", datetime(2026, 3, 14, 15, 30, tzinfo=UTC)),
        ("2026-03-14T10:30:00Z", datetime(2026, 3, 14, 10, 30, tzinfo=UTC)),
        (" 2026-03-14T10:30:00Z ", datetime(2026, 3, 14, 10, 30, tzinfo=UTC)),
    ],
)
def test_as_of_is_parsed_as_utc(raw: str, expected: datetime) -> None:
    as_of = ClockSettings.from_env({"AS_OF": raw}).as_of

    assert as_of == expected
    assert as_of is not None
    assert as_of.tzinfo == UTC


@pytest.mark.parametrize("raw", ["yesterday", "2026-13-01", "14/03/2026", "now"])
def test_invalid_as_of_is_rejected(raw: str) -> None:
    with pytest.raises(
        ConfigurationError, match="AS_OF must be an ISO 8601 date or timestamp"
    ):
        ClockSettings.from_env({"AS_OF": raw})


def test_now_returns_as_of_when_set() -> None:
    as_of = datetime(2026, 3, 14, 10, 30, tzinfo=UTC)

    assert ClockSettings(as_of=as_of).now() == as_of


def test_now_is_the_real_utc_time_when_unset() -> None:
    clock = ClockSettings(as_of=None)

    before = datetime.now(UTC)
    first = clock.now()
    second = clock.now()
    after = datetime.now(UTC)

    assert before <= first <= second <= after
    assert first.tzinfo == UTC
    assert after - before < timedelta(seconds=5)
```

Make the same change in `tests/unit/list_card_transactions/test_settings.py`, importing from `list_card_transactions_lambda.delivery.settings`.

- [ ] **Step 2: Run them to see them fail**

Run: `$PY -m pytest tests/unit/list_credit_cards/test_settings.py tests/unit/list_card_transactions/test_settings.py -q -p no:cacheprovider </dev/null`
Expected: collection errors, `ImportError: cannot import name 'ClockSettings'`.

- [ ] **Step 3: Add `ClockSettings` to both `settings.py` files**

In `gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/settings.py`, add `from datetime import datetime, timezone` to the imports:

```python
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Final
```

Insert this class right after the `DsqlSettings` class, before `def _engine`:

```python
@dataclass(frozen=True)
class ClockSettings:
    """The tool's notion of "now".

    Attributes:
        as_of: Fixed UTC "now" from AS_OF, or None to use the real clock.
    """

    as_of: datetime | None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "ClockSettings":
        """Read AS_OF, an optional ISO 8601 date or timestamp used as "now".

        Demos set it to a moment inside the historical dataset. Production
        leaves it unset.

        Raises:
            ConfigurationError: The value isn't an ISO 8601 date or timestamp.
        """
        return cls(as_of=_as_of(env))

    def now(self) -> datetime:
        """Return as_of when set, else datetime.now(timezone.utc). Always aware UTC."""
        if self.as_of is not None:
            return self.as_of
        return datetime.now(timezone.utc)
```

Append this helper to the end of the file:

```python
def _as_of(env: Mapping[str, str]) -> datetime | None:
    """Parse AS_OF as aware UTC; blank or missing means the real clock.

    A bare date is midnight UTC, a timestamp without an offset is UTC, and one
    with an offset (or Z) is converted to UTC.

    Raises:
        ConfigurationError: The value isn't an ISO 8601 date or timestamp.
    """
    raw = env.get("AS_OF", "").strip()
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ConfigurationError(
            f"AS_OF must be an ISO 8601 date or timestamp, got {raw!r}"
        ) from exc
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
```

Make the identical change in `gateway/tools/list_card_transactions/list_card_transactions_lambda/delivery/settings.py`.

Check that the two files are still identical apart from the package name:
`diff <(sed 's/list_card_transactions/X/g' gateway/tools/list_card_transactions/list_card_transactions_lambda/delivery/settings.py) <(sed 's/list_credit_cards/X/g' gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/settings.py)`
Expected: no output.

- [ ] **Step 4: Run the settings tests**

Run: `$PY -m pytest tests/unit/list_credit_cards/test_settings.py tests/unit/list_card_transactions/test_settings.py -q -p no:cacheprovider </dev/null`
Expected: all pass.

- [ ] **Step 5: Write the failing wiring tests (both tools)**

In `tests/unit/list_credit_cards/test_delivery_wiring.py`:
- Add `build_clock` to the `dependencies_builder` import list, after `QUERIES_ROOT`/`SQL_DIALECTS` and before `build_connector`.
- Add `ClockSettings` to the settings import list, before `ConfigurationError`.
- Add `from datetime import datetime, timezone` as the first import.

Append:

```python
def test_build_clock_reads_as_of() -> None:
    assert build_clock({"AS_OF": "2026-03-14"}) == ClockSettings(
        as_of=datetime(2026, 3, 14, tzinfo=timezone.utc)
    )


def test_build_clock_without_as_of_uses_the_real_clock() -> None:
    assert build_clock({}) == ClockSettings(as_of=None)


def test_build_clock_with_a_bad_as_of_returns_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert build_clock({"AS_OF": "yesterday"}) is None
    assert "Invalid AS_OF for list_credit_cards" in caplog.text
```

`list_card_transactions` difference: the same three tests in `tests/unit/list_card_transactions/test_delivery_wiring.py`. That file already imports `from datetime import datetime, timedelta, timezone`. The log text is `"Invalid AS_OF for list_card_transactions"`.

Run: `$PY -m pytest tests/unit/list_credit_cards/test_delivery_wiring.py tests/unit/list_card_transactions/test_delivery_wiring.py -q -p no:cacheprovider </dev/null`
Expected: collection errors, `ImportError: cannot import name 'build_clock'`.

- [ ] **Step 6: Add the clock block to both builders**

In `gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/dependencies/dependencies_builder.py`, the module docstring's block list becomes:

```text
- Settings: environment variables to typed settings.
- Clock: AS_OF to the tool's notion of "now".
- Connection: the engine-specific connector (built without connecting).
- Adapters: the engine-specific database repository and query provider.
- Use case: build_list_credit_cards_use_case, which builds the tool's whole
  graph.
```

Add `ClockSettings` to the settings import:

```python
from list_credit_cards_lambda.delivery.settings import (
    ClockSettings,
    ConfigurationError,
    DatabaseEngine,
    DatabaseSettings,
    DsqlSettings,
)
```

Insert this block between `build_dsql_settings` and the `# --- Connection ---` banner:

```python
# --- Clock -------------------------------------------------------------------


def build_clock(env: Mapping[str, str]) -> ClockSettings | None:
    """Read AS_OF, the tool's fixed "now" for demos. Never raises.

    Returns:
        The clock settings, or None when AS_OF is invalid. Every request then
        gets DataSourceUnavailableError's message.
    """
    try:
        return ClockSettings.from_env(env)
    except ConfigurationError:
        logger.exception("Invalid AS_OF for list_credit_cards")
        return None
```

`list_card_transactions` difference: same edits in its builder. The docstring names `build_list_card_transactions_use_case`, and the log text is `"Invalid AS_OF for list_card_transactions"`.

Run the Step 5 command again.
Expected: all pass.

- [ ] **Step 7: Write the failing handler tests for `list_credit_cards`**

In `tests/unit/list_credit_cards/test_list_credit_cards_handler.py`:
- Add `"AS_OF",` to the env names the `module` fixture deletes, after `"AWS_REGION",`.
- Change the settings import to `from list_credit_cards_lambda.delivery.settings import ClockSettings, DatabaseEngine`.

Append:

```python
def test_default_environment_uses_the_real_clock(module: ModuleType) -> None:
    assert module.CLOCK == ClockSettings(as_of=None)


def test_missing_clock_returns_data_source_unavailable(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = FakeConnector([make_row()])
    wire(module, monkeypatch, connector)
    monkeypatch.setattr(module, "CLOCK", None)

    response = module.handler(EVENT, make_context())

    assert response == {"error": DataSourceUnavailableError.MESSAGE}
    assert connector.connections == []


def test_a_bad_as_of_env_var_leaves_the_clock_unset(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AS_OF", "yesterday")

    assert importlib.reload(module).CLOCK is None
```

Run: `$PY -m pytest tests/unit/list_credit_cards/test_list_credit_cards_handler.py -q -p no:cacheprovider </dev/null`
Expected: 3 failures. They are `AttributeError: ... has no attribute 'CLOCK'` for the first and third, and a success response instead of the error for the second.

- [ ] **Step 8: Add `CLOCK` to the `list_credit_cards` handler**

In `gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/handler.py`:

1. In the module docstring, change the R1 env var list from `(DB_ENGINE, DSQL_CLUSTER_ENDPOINT, DSQL_DB_USER)` to `(DB_ENGINE, DSQL_CLUSTER_ENDPOINT, DSQL_DB_USER, AS_OF)`. The wrapped lines become:

```text
TODO(ledgerlens): R1 - no CDK yet: no PythonFunction, Gateway target, env vars
  (DB_ENGINE, DSQL_CLUSTER_ENDPOINT, DSQL_DB_USER, AS_OF) or dsql:DbConnect grant
  on the cluster ARN (dsql:DbConnectAdmin only if DSQL_DB_USER=admin). The tool
  can't be deployed or called by the agent until the CDK spec lands.
```

   Add this paragraph before the TODO lines:

```text
AS_OF (optional) is read once into CLOCK. This tool has no time window, so it
only validates it: an invalid AS_OF answers every request with
DataSourceUnavailableError's message, as any other bad setting does.
```

2. The builder import becomes:

```python
from list_credit_cards_lambda.delivery.dependencies.dependencies_builder import (
    build_clock,
    build_list_credit_cards_use_case,
)
```

3. Below `USE_CASE = build_list_credit_cards_use_case(os.environ)`, add:

```python
CLOCK = build_clock(os.environ)
```

4. The guard inside the `try` becomes:

```python
        if USE_CASE is None or CLOCK is None:
            raise DataSourceUnavailableError()
```

Run the Step 7 command again.
Expected: all pass.

- [ ] **Step 9: Write the failing handler tests for `list_card_transactions`**

In `tests/unit/list_card_transactions/test_list_card_transactions_handler.py`:
- Add `"AS_OF",` to the env names the `module` fixture deletes.
- Add `from datetime import date, datetime, timezone` as the first import.
- Change the settings import to `from list_card_transactions_lambda.delivery.settings import ClockSettings, DatabaseEngine`.

Append:

```python
def sent_params(connector: FakeConnector) -> Any:
    """Return the params of the first query the connector executed."""
    return connector.connections[-1].cursors[0].executed[0][1]


def test_default_date_to_is_the_as_of_date(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = FakeConnector([])
    wire(module, monkeypatch, connector)
    as_of = datetime(2026, 3, 14, 10, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(module, "CLOCK", ClockSettings(as_of=as_of))

    response = module.handler({"customer_id": "CUST-1"}, make_context())

    assert "content" in response
    assert sent_params(connector)["date_to"] == date(2026, 3, 14)
    assert sent_params(connector)["date_from"] == date(2026, 2, 12)


def test_without_as_of_date_to_is_today(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = FakeConnector([])
    wire(module, monkeypatch, connector)

    before = datetime.now(timezone.utc).date()
    module.handler({"customer_id": "CUST-1"}, make_context())
    after = datetime.now(timezone.utc).date()

    assert module.CLOCK == ClockSettings(as_of=None)
    assert sent_params(connector)["date_to"] in {before, after}


def test_missing_clock_returns_data_source_unavailable(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = FakeConnector([make_row()])
    wire(module, monkeypatch, connector)
    monkeypatch.setattr(module, "CLOCK", None)

    response = module.handler(EVENT, make_context())

    assert response == {"error": DataSourceUnavailableError.MESSAGE}
    assert connector.connections == []


def test_a_bad_as_of_env_var_leaves_the_clock_unset(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AS_OF", "yesterday")

    assert importlib.reload(module).CLOCK is None
```

Run: `$PY -m pytest tests/unit/list_card_transactions/test_list_card_transactions_handler.py -q -p no:cacheprovider </dev/null`
Expected: 4 failures. `test_default_date_to_is_the_as_of_date` fails because `date_to` is today, not `2026-03-14`. The others fail with `AttributeError` on `CLOCK`, or with a success response instead of the error.

- [ ] **Step 10: Add `CLOCK` to the `list_card_transactions` handler**

In `gateway/tools/list_card_transactions/list_card_transactions_lambda/delivery/handler.py`:

1. Change the R1 env var list in the docstring exactly as in Step 8, item 1. Add this paragraph before the TODO lines:

```text
AS_OF (optional) is read once into CLOCK; "today" for the default date window
is CLOCK.now() on every call, so a warm container never freezes the real clock.
An invalid AS_OF answers every request with DataSourceUnavailableError's
message.
```

2. Delete `from datetime import datetime, timezone`; nothing else uses it.
3. The builder import becomes:

```python
from list_card_transactions_lambda.delivery.dependencies.dependencies_builder import (
    build_clock,
    build_list_card_transactions_use_case,
)
```

4. Below `USE_CASE = build_list_card_transactions_use_case(os.environ)`, add `CLOCK = build_clock(os.environ)`.
5. The start of the `try` becomes:

```python
        if USE_CASE is None or CLOCK is None:
            raise DataSourceUnavailableError()
        filters = TransactionFilters.from_raw(event, today=CLOCK.now().date())
```

Run the Step 9 command again.
Expected: all pass.

- [ ] **Step 11: Run both tools' suites and lint**

```bash
$PY -m pytest tests/unit/list_credit_cards tests/unit/list_card_transactions -q -p no:cacheprovider </dev/null 2>&1 | tail -2
$PY -m ruff format --check gateway/tools/list_credit_cards gateway/tools/list_card_transactions tests/unit/list_credit_cards tests/unit/list_card_transactions </dev/null
$PY -m ruff check gateway/tools/list_credit_cards gateway/tools/list_card_transactions tests/unit/list_credit_cards tests/unit/list_card_transactions </dev/null
grep -rn "datetime.now" gateway/tools/list_card_transactions/list_card_transactions_lambda/delivery/handler.py
```

Expected:
- pytest: all pass, 0 failed.
- Both ruff commands are clean.
- The grep prints nothing.

---

### Task 2: Copy the shared layers into `get_session_context`

**Files:**
- Create (copied): `gateway/tools/get_session_context/requirements.txt`
- Create (copied): the 14 `__init__.py` files under `gateway/tools/get_session_context/get_session_context_lambda/`
- Create (copied): `application/ports/{database_repository,query_provider,errors}.py`, `infrastructure/queries/file_query_provider.py`, `infrastructure/repositories/dsql_repository.py`, `utils/connectors/{base,dsql}.py`, `delivery/settings.py`
- Create: `tests/unit/get_session_context/__init__.py` (empty), `conftest.py`, `fakes.py`
- Create (copied): `tests/unit/get_session_context/test_{settings,file_query_provider,dsql_repository,psycopg_connector,dsql_connector}.py`

**Interfaces:**
- Consumes: Task 1's `ClockSettings` in `list_credit_cards_lambda/delivery/settings.py`.
- Produces (all under `get_session_context_lambda`):
  - `application.ports.database_repository.DatabaseRepository` with `execute_query(query: str, params: Mapping[str, object]) -> list[dict[str, Any]]`
  - `application.ports.query_provider.QueryProvider` with `get(name: str) -> str`
  - `application.ports.errors`: `DataAccessError`, `DataSourceConnectionError`, `QueryExecutionError`, `QueryLimitExceededError`, `QueryNotFoundError` (all take one message string)
  - `infrastructure.queries.file_query_provider.FileQueryProvider(directory: Path)`
  - `infrastructure.repositories.dsql_repository.DsqlRepository(connector)`
  - `utils.connectors.base.PsycopgConnector`, `utils.connectors.dsql.DsqlConnector`
  - `delivery.settings`: `ConfigurationError`, `DatabaseEngine`, `DatabaseSettings`, `DsqlSettings`, `ClockSettings`
- Produces in `tests/unit/get_session_context/fakes.py`:
  - `CUSTOMER_ID = "CLI-ITIECUE8PRH9"`
  - `QUERY_NAMES: tuple[str, ...]`, the five query names in run order
  - `Outcome = list[dict[str, Any]] | Exception`
  - `FakeQueryProvider(queries: Mapping[str, str] | None = None)`: by default it serves each query name as its own SQL text. Attributes `.queries`, `.requested`.
  - `FakeSessionRepository(responses: Mapping[str, Outcome] | None = None)`: answers by SQL text (= query name). Attributes `.responses`, `.calls: list[tuple[str, dict[str, object]]]`; property `.queries: list[str]`.
  - Row builders: `make_profile_row`, `make_card_row` (alias `make_row`), `make_transaction_row`, `make_signal_row`, `make_case_row`, each taking `**overrides`.
  - `session_responses(**overrides: Outcome) -> dict[str, Outcome]`: one row per query, keyed by query name.
  - `make_any_section_row() -> dict[str, Any]`: one row every section can map. Use it over `FakeConnector`, where every query gets the same rows.
  - Copied unchanged: `FakeCursor`, `FakeConnection`, `FakeConnector(*outcomes, max_age=None, clock=time.monotonic)`, `FakeClock`, `FakeDsqlTokenClient`.

- [ ] **Step 1: Copy the production files**

Run from the repo root (Task 1 must be done first):

```bash
SRC=gateway/tools/list_credit_cards
DST=gateway/tools/get_session_context
mkdir -p "$DST"
sed 's/list_credit_cards/get_session_context/g' "$SRC/requirements.txt" > "$DST/requirements.txt"
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
  mkdir -p "$DST/get_session_context_lambda/$(dirname "$f")"
  sed 's/list_credit_cards/get_session_context/g' \
    "$SRC/list_credit_cards_lambda/$f" > "$DST/get_session_context_lambda/$f"
done
mkdir -p "$DST/get_session_context_lambda/queries/postgresql"
```

The sed already gives the root and use-case docstrings the new tool name. Check them:

```bash
cat gateway/tools/get_session_context/get_session_context_lambda/__init__.py gateway/tools/get_session_context/get_session_context_lambda/application/use_cases/__init__.py
head -1 gateway/tools/get_session_context/requirements.txt
```

Expected:
```text
"""The get_session_context Gateway tool Lambda, in hexagonal layers."""
"""Use case of the get_session_context tool."""
# Runtime dependencies for the get_session_context Lambda.
```

- [ ] **Step 2: Create the test package**

`tests/unit/get_session_context/__init__.py` is an empty file.

`tests/unit/get_session_context/conftest.py`:

```python
"""Pytest setup for get_session_context: make its Lambda package importable.

The ``get_session_context_lambda`` package lives in the Lambda asset root
``gateway/tools/get_session_context``, so that folder is put on ``sys.path``
exactly as the Lambda runtime does.
"""

import sys
from pathlib import Path

_ASSET_ROOT = (
    Path(__file__).resolve().parents[3] / "gateway" / "tools" / "get_session_context"
)

if str(_ASSET_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASSET_ROOT))
```

- [ ] **Step 3: Create `fakes.py`**

Copy it with sed first:

```bash
sed 's/list_credit_cards/get_session_context/g' tests/unit/list_credit_cards/fakes.py > tests/unit/get_session_context/fakes.py
```

Then replace everything from the top of the new file down to, but not including, the line `class FakeCursor:` with this block. The old block ends with `Outcome = list[dict[str, Any]] | Exception`; the new one defines it near the top.

```python
"""Test doubles and builders for the get_session_context tests."""

import time
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from get_session_context_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from get_session_context_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryNotFoundError,
)
from get_session_context_lambda.application.ports.query_provider import QueryProvider
from get_session_context_lambda.utils.connectors.base import PsycopgConnector

# A customer id in the format the customer system issues.
CUSTOMER_ID: Final = "CLI-ITIECUE8PRH9"

# The five queries, in the order the use case runs them.
QUERY_NAMES: Final = (
    "session_customer_profile",
    "session_credit_cards",
    "session_recent_transactions",
    "session_digital_signals",
    "session_open_cases",
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


class FakeSessionRepository(DatabaseRepository):
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


def make_profile_row(**overrides: Any) -> dict[str, Any]:
    """Build a session_customer_profile row as psycopg's dict_row returns it."""
    row: dict[str, Any] = {
        "customer_id": CUSTOMER_ID,
        "first_name": "Ana",
        "country": "Colombia",
        "city": "Bogotá",
        "customer_status": "Active",
    }
    row.update(overrides)
    return row


def make_card_row(**overrides: Any) -> dict[str, Any]:
    """Build a session_credit_cards row as psycopg's dict_row returns it."""
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


# The copied repository tests build rows with make_row.
make_row = make_card_row


def make_transaction_row(**overrides: Any) -> dict[str, Any]:
    """Build a session_recent_transactions row as psycopg's dict_row returns it."""
    row: dict[str, Any] = {
        "transaction_id": "TX-1",
        "transaction_date": datetime(2026, 3, 14, 10, 42),
        "card_last4": "4821",
        "merchant_name": "EXITO",
        "amount": Decimal("350000.00"),
        "currency": "COP",
        "transaction_status": "Declined",
        "transaction_country": "Colombia",
        "is_declined": True,
        "is_foreign": False,
        "is_above_usual_amount": True,
        "is_new_merchant": False,
    }
    row.update(overrides)
    return row


def make_signal_row(**overrides: Any) -> dict[str, Any]:
    """Build a session_digital_signals row as psycopg's dict_row returns it."""
    row: dict[str, Any] = {
        "event_date": datetime(2026, 3, 14, 10, 48),
        "signal": "FAILED_ACTION",
        "page_title": "Tarjeta de Crédito",
        "ip_country": "Colombia",
        "ip_city": "Bogotá",
        "event_id": "EV-1",
    }
    row.update(overrides)
    return row


def make_case_row(**overrides: Any) -> dict[str, Any]:
    """Build a session_open_cases row as psycopg's dict_row returns it."""
    row: dict[str, Any] = {
        "complaint_id": "C-1182",
        "case_type": "Claim",
        "category": "Transactions",
        "subcategory": "Cargo no reconocido",
        "status": "Open",
        "priority": "High",
        "sla_breached": False,
        "claimed_amount": Decimal("350000.00"),
        "currency": "COP",
        "days_open": 3,
    }
    row.update(overrides)
    return row


def session_responses(**overrides: Outcome) -> dict[str, Outcome]:
    """Return one row per query, keyed by query name; overrides replace a query."""
    responses: dict[str, Outcome] = {
        "session_customer_profile": [make_profile_row()],
        "session_credit_cards": [make_card_row()],
        "session_recent_transactions": [make_transaction_row()],
        "session_digital_signals": [make_signal_row()],
        "session_open_cases": [make_case_row()],
    }
    responses.update(overrides)
    return responses


def make_any_section_row() -> dict[str, Any]:
    """Build one row that every section can map.

    FakeConnector serves the same rows to every query, so end-to-end tests over
    real adapters need a row with every section's columns. The only shared
    column, currency, is "COP" in every builder.
    """
    return {
        **make_case_row(),
        **make_signal_row(),
        **make_transaction_row(),
        **make_card_row(),
        **make_profile_row(),
    }
```

Keep everything from `class FakeCursor:` to the end of the file exactly as copied.

- [ ] **Step 4: Copy the adapter tests**

```bash
for t in test_settings test_file_query_provider test_dsql_repository test_psycopg_connector test_dsql_connector; do
  sed 's/list_credit_cards/get_session_context/g' tests/unit/list_credit_cards/$t.py > tests/unit/get_session_context/$t.py
done
```

- [ ] **Step 5: Run the copied tests**

Run: `$PY -m pytest tests/unit/get_session_context -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: all pass, 0 failed. These tests cover copied code, so they pass at once. They prove the copy, not new behaviour.

- [ ] **Step 6: Check isolation and lint**

```bash
grep -rn "list_credit_cards\|list_card_transactions" gateway/tools/get_session_context tests/unit/get_session_context
$PY -m ruff format --check gateway/tools/get_session_context tests/unit/get_session_context </dev/null
$PY -m ruff check gateway/tools/get_session_context tests/unit/get_session_context </dev/null
```

Expected: the grep prints nothing, and both ruff commands are clean.

---

### Task 3: Domain errors

**Files:**
- Create: `gateway/tools/get_session_context/get_session_context_lambda/domain/errors.py`
- Test: `tests/unit/get_session_context/test_errors.py`

**Interfaces:**
- Consumes: Task 2's port errors (test only).
- Produces in `get_session_context_lambda.domain.errors`:
  - `DomainError(message)` with `.message`
  - `InvalidInputError(field, reason)` with `.field` and `.reason`
  - Fixed-message errors, each built with no arguments and carrying `MESSAGE: ClassVar[str]`: `DataSourceUnavailableError`, `SessionContextLookupError`, `CustomerNotFoundError`, `SessionContextDataIntegrityError`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/get_session_context/test_errors.py`:

```python
"""Tests for domain and port error definitions."""

import get_session_context_lambda.domain.errors as errors_module
import pytest
from get_session_context_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
    QueryNotFoundError,
)
from get_session_context_lambda.domain.errors import (
    CustomerNotFoundError,
    DataSourceUnavailableError,
    DomainError,
    InvalidInputError,
    SessionContextDataIntegrityError,
    SessionContextLookupError,
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
            "Customer data is temporarily unavailable. Greet the customer, ask how "
            "you can help, and offer to retry in a moment or hand off to a human "
            "agent.",
        ),
        (
            SessionContextLookupError,
            "The customer's context can't be retrieved right now due to an "
            "internal error. Don't retry; ask the customer how you can help and "
            "offer a hand-off to a human agent if needed.",
        ),
        (
            CustomerNotFoundError,
            "No customer record matches this customer_id. Don't guess or retry; "
            "offer a hand-off to a human agent.",
        ),
        (
            SessionContextDataIntegrityError,
            "Customer data came back in an unexpected format. Don't retry; offer "
            "a hand-off to a human agent.",
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


@pytest.mark.parametrize("name", ["CardLookupError", "CardDataIntegrityError"])
def test_card_worded_errors_are_not_defined(name: str) -> None:
    # This tool's failures are about the whole context (spec section 6.2).
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

- [ ] **Step 2: Run them to see them fail**

Run: `$PY -m pytest tests/unit/get_session_context/test_errors.py -q -p no:cacheprovider </dev/null`
Expected: a collection error, `ModuleNotFoundError: No module named 'get_session_context_lambda.domain.errors'`.

- [ ] **Step 3: Write `domain/errors.py`**

```python
"""Domain errors: the only failures the agent is allowed to see.

Each message says what went wrong and what the agent should do next. Messages
never contain SQL, hostnames, driver output or other internal details. Only the
customer section raises them; a failure in any other section makes that section
unavailable instead (spec section 4.4).
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
        "Customer data is temporarily unavailable. Greet the customer, ask how "
        "you can help, and offer to retry in a moment or hand off to a human "
        "agent."
    )


class SessionContextLookupError(_FixedMessageError):
    """The customer query failed or hit a database limit; retrying won't help."""

    MESSAGE: ClassVar[str] = (
        "The customer's context can't be retrieved right now due to an "
        "internal error. Don't retry; ask the customer how you can help and "
        "offer a hand-off to a human agent if needed."
    )


class CustomerNotFoundError(_FixedMessageError):
    """No customer row matches the customer_id."""

    MESSAGE: ClassVar[str] = (
        "No customer record matches this customer_id. Don't guess or retry; "
        "offer a hand-off to a human agent."
    )


class SessionContextDataIntegrityError(_FixedMessageError):
    """The customer row couldn't be mapped to a domain entity."""

    MESSAGE: ClassVar[str] = (
        "Customer data came back in an unexpected format. Don't retry; offer "
        "a hand-off to a human agent."
    )
```

- [ ] **Step 4: Run the tests**

Run: `$PY -m pytest tests/unit/get_session_context/test_errors.py -q -p no:cacheprovider </dev/null`
Expected: all pass.

---

### Task 4: Entities and use case

**Files:**
- Create: `gateway/tools/get_session_context/get_session_context_lambda/domain/entities/session_context.py`
- Create: `gateway/tools/get_session_context/get_session_context_lambda/application/use_cases/get_session_context.py`
- Test: `tests/unit/get_session_context/test_get_session_context_use_case.py`

**Interfaces:**
- Consumes: Task 2's ports and fakes, and Task 3's domain errors.
- Produces in `get_session_context_lambda.domain.entities.session_context`:
  - frozen dataclasses `Customer`, `CreditCard`, `RecentTransaction`, `DigitalSignal`, `OpenCase`, `SessionContext`, with fields exactly as in spec §4.3
  - `TransactionFlag(str, Enum)`: `DECLINED`, `FOREIGN`, `ABOVE_USUAL_AMOUNT`, `NEW_MERCHANT`
  - `Section(str, Enum)`: `CARDS`, `RECENT_TRANSACTIONS`, `DIGITAL_SIGNALS`, `OPEN_CASES`. Each value equals the `SessionContext` attribute name.
- Produces in `get_session_context_lambda.application.use_cases.get_session_context`:
  - `GetSessionContextUseCase(database_repository, query_provider, max_rows: int = 25)` with `OPEN_CASES_CAP = 5` and `execute(customer_id: object, as_of: datetime) -> SessionContext`
  - `PROFILE_QUERY_NAME = "session_customer_profile"`
  - `SECTION_QUERY_NAMES: Mapping[Section, str]`

- [ ] **Step 1: Write the failing tests**

`tests/unit/get_session_context/test_get_session_context_use_case.py`:

```python
"""Tests for the get_session_context use case."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from get_session_context_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
    QueryNotFoundError,
)
from get_session_context_lambda.application.use_cases.get_session_context import (
    PROFILE_QUERY_NAME,
    SECTION_QUERY_NAMES,
    GetSessionContextUseCase,
)
from get_session_context_lambda.domain.entities.session_context import (
    CreditCard,
    Customer,
    DigitalSignal,
    OpenCase,
    RecentTransaction,
    Section,
    SessionContext,
    TransactionFlag,
)
from get_session_context_lambda.domain.errors import (
    CustomerNotFoundError,
    DataSourceUnavailableError,
    DomainError,
    InvalidInputError,
    SessionContextDataIntegrityError,
    SessionContextLookupError,
)

from .fakes import (
    CUSTOMER_ID,
    QUERY_NAMES,
    FakeQueryProvider,
    FakeSessionRepository,
    Outcome,
    make_card_row,
    make_case_row,
    make_profile_row,
    make_signal_row,
    make_transaction_row,
    session_responses,
)

pytestmark = pytest.mark.unit

AS_OF = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
# What the SQL receives: the same instant as naive UTC.
AS_OF_SQL = datetime(2026, 3, 14, 12, 0)
INVALID_CUSTOMER_ID = (
    "Invalid value for 'customer_id': is required and must be a non-empty "
    "string. Ask the customer to confirm and retry."
)
SECTION_ERRORS = [
    DataSourceConnectionError("connection refused"),
    QueryExecutionError("function percentile_cont is not supported"),
    QueryLimitExceededError("statement timeout"),
    QueryNotFoundError("no query named 'session_open_cases'"),
]


def make_use_case(
    responses: dict[str, Outcome] | None = None, max_rows: int = 25
) -> tuple[GetSessionContextUseCase, FakeSessionRepository]:
    """Build the use case over a fake repository; default: one row per query."""
    database_repository = FakeSessionRepository(
        session_responses() if responses is None else responses
    )
    use_case = GetSessionContextUseCase(
        database_repository=database_repository,
        query_provider=FakeQueryProvider(),
        max_rows=max_rows,
    )
    return use_case, database_repository


def section_items(context: SessionContext, section: Section) -> Any:
    """Return the section's tuple, or None when it's unavailable."""
    return getattr(context, section.value)


def warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return the text of every warning the use case logged."""
    return [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]


def test_execute_returns_the_full_snapshot() -> None:
    use_case, _ = make_use_case()

    context = use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert context == SessionContext(
        as_of=AS_OF,
        customer=Customer(
            customer_id=CUSTOMER_ID,
            first_name="Ana",
            country="Colombia",
            city="Bogotá",
            customer_status="Active",
        ),
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
        recent_transactions=(
            RecentTransaction(
                transaction_id="TX-1",
                transaction_date=datetime(2026, 3, 14, 10, 42),
                card_last4="4821",
                merchant_name="EXITO",
                amount=Decimal("350000.00"),
                currency="COP",
                transaction_status="Declined",
                transaction_country="Colombia",
                flags=(TransactionFlag.DECLINED, TransactionFlag.ABOVE_USUAL_AMOUNT),
            ),
        ),
        digital_signals=(
            DigitalSignal(
                event_date=datetime(2026, 3, 14, 10, 48),
                signal="FAILED_ACTION",
                page_title="Tarjeta de Crédito",
                ip_country="Colombia",
                ip_city="Bogotá",
            ),
        ),
        open_cases=(
            OpenCase(
                complaint_id="C-1182",
                case_type="Claim",
                category="Transactions",
                subcategory="Cargo no reconocido",
                status="Open",
                priority="High",
                sla_breached=False,
                claimed_amount=Decimal("350000.00"),
                currency="COP",
                days_open=3,
            ),
        ),
        truncated=(),
        unavailable=(),
    )


def test_query_names_follow_the_sections() -> None:
    assert PROFILE_QUERY_NAME == "session_customer_profile"
    assert (PROFILE_QUERY_NAME, *SECTION_QUERY_NAMES.values()) == QUERY_NAMES
    assert list(SECTION_QUERY_NAMES) == list(Section)


def test_queries_run_one_after_another_in_section_order() -> None:
    use_case, database_repository = make_use_case()

    use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert database_repository.queries == list(QUERY_NAMES)


def test_each_query_gets_exactly_its_params() -> None:
    use_case, database_repository = make_use_case()

    use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert dict(database_repository.calls) == {
        "session_customer_profile": {"customer_id": CUSTOMER_ID},
        "session_credit_cards": {"customer_id": CUSTOMER_ID, "limit": 26},
        "session_recent_transactions": {
            "customer_id": CUSTOMER_ID,
            "as_of": AS_OF_SQL,
            "limit": 26,
        },
        "session_digital_signals": {
            "customer_id": CUSTOMER_ID,
            "as_of": AS_OF_SQL,
            "limit": 26,
        },
        "session_open_cases": {
            "customer_id": CUSTOMER_ID,
            "as_of": AS_OF_SQL,
            "limit": 6,
        },
    }


def test_an_aware_as_of_in_another_zone_is_sent_as_naive_utc() -> None:
    use_case, database_repository = make_use_case()
    bogota = timezone(timedelta(hours=-5))

    context = use_case.execute(
        CUSTOMER_ID, as_of=datetime(2026, 3, 14, 7, 0, tzinfo=bogota)
    )

    sent = [params["as_of"] for _q, params in database_repository.calls if "as_of" in params]
    assert len(sent) == 3
    for as_of in sent:
        assert as_of == AS_OF_SQL
        assert as_of.tzinfo is None
    assert context.as_of == AS_OF
    assert context.as_of.tzinfo == timezone.utc


def test_a_naive_as_of_is_rejected_before_any_query() -> None:
    use_case, database_repository = make_use_case()

    with pytest.raises(ValueError, match="aware"):
        use_case.execute(CUSTOMER_ID, as_of=AS_OF_SQL)

    assert database_repository.calls == []


def test_customer_id_is_stripped_and_uppercased() -> None:
    use_case, database_repository = make_use_case()

    use_case.execute("  cli-itiecue8prh9 ", as_of=AS_OF)

    assert {params["customer_id"] for _q, params in database_repository.calls} == {
        CUSTOMER_ID
    }


@pytest.mark.parametrize("customer_id", [None, "", "   ", 42, True, ["CLI-1"]])
def test_invalid_customer_id_is_rejected_before_any_query(customer_id: object) -> None:
    use_case, database_repository = make_use_case()

    with pytest.raises(InvalidInputError) as raised:
        use_case.execute(customer_id, as_of=AS_OF)

    assert raised.value.message == INVALID_CUSTOMER_ID
    assert database_repository.calls == []


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (DataSourceConnectionError("connection refused"), DataSourceUnavailableError),
        (QueryExecutionError("relation does not exist"), SessionContextLookupError),
        (QueryLimitExceededError("statement timeout"), SessionContextLookupError),
        (QueryNotFoundError("no query"), SessionContextLookupError),
    ],
)
def test_a_customer_section_failure_fails_the_call_and_stops(
    error: DataAccessError, expected: type[DomainError]
) -> None:
    use_case, database_repository = make_use_case(
        session_responses(session_customer_profile=error)
    )

    with pytest.raises(expected) as raised:
        use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert raised.value.__cause__ is error
    assert database_repository.queries == ["session_customer_profile"]


def test_a_missing_profile_query_is_a_lookup_error() -> None:
    database_repository = FakeSessionRepository(session_responses())
    use_case = GetSessionContextUseCase(
        database_repository=database_repository,
        query_provider=FakeQueryProvider({"session_credit_cards": "x"}),
    )

    with pytest.raises(SessionContextLookupError):
        use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert database_repository.calls == []


def test_no_customer_row_is_customer_not_found() -> None:
    use_case, database_repository = make_use_case(
        session_responses(session_customer_profile=[])
    )

    with pytest.raises(CustomerNotFoundError):
        use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert database_repository.queries == ["session_customer_profile"]


@pytest.mark.parametrize(
    "row",
    [make_profile_row(customer_id=None), {"customer_id": CUSTOMER_ID}],
    ids=["null-customer-id", "missing-columns"],
)
def test_an_unmappable_customer_row_is_a_data_integrity_error(
    row: dict[str, Any],
) -> None:
    use_case, database_repository = make_use_case(
        session_responses(session_customer_profile=[row])
    )

    with pytest.raises(SessionContextDataIntegrityError):
        use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert database_repository.queries == ["session_customer_profile"]


@pytest.mark.parametrize("error", SECTION_ERRORS, ids=lambda e: type(e).__name__)
@pytest.mark.parametrize("section", list(Section), ids=lambda s: s.value)
def test_a_failed_section_is_none_and_listed_unavailable(
    section: Section, error: DataAccessError, caplog: pytest.LogCaptureFixture
) -> None:
    use_case, database_repository = make_use_case(
        session_responses(**{SECTION_QUERY_NAMES[section]: error})
    )

    context = use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert section_items(context, section) is None
    assert context.unavailable == (section,)
    assert context.truncated == ()
    for other in Section:
        if other is not section:
            assert len(section_items(context, other)) == 1
    assert database_repository.queries == list(QUERY_NAMES)
    assert warnings(caplog) == [
        f"get_session_context section {section.value} unavailable"
    ]


@pytest.mark.parametrize(
    ("section", "bad_row"),
    [
        (Section.CARDS, make_card_row(current_balance="lots")),
        (
            Section.RECENT_TRANSACTIONS,
            make_transaction_row(transaction_date="yesterday"),
        ),
        (Section.DIGITAL_SIGNALS, make_signal_row(signal=None)),
        (Section.OPEN_CASES, make_case_row(days_open=True)),
    ],
    ids=lambda value: value.value if isinstance(value, Section) else "",
)
def test_an_unmappable_row_makes_only_its_section_unavailable(
    section: Section, bad_row: dict[str, Any]
) -> None:
    use_case, _ = make_use_case(
        session_responses(**{SECTION_QUERY_NAMES[section]: [bad_row]})
    )

    context = use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert section_items(context, section) is None
    assert context.unavailable == (section,)
    for other in Section:
        if other is not section:
            assert len(section_items(context, other)) == 1


def test_all_four_sections_failing_are_listed_in_order(
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = QueryExecutionError("boom")
    use_case, _ = make_use_case(
        session_responses(**{name: error for name in SECTION_QUERY_NAMES.values()})
    )

    context = use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert context.customer.customer_id == CUSTOMER_ID
    assert context.unavailable == tuple(Section)
    assert [section_items(context, s) for s in Section] == [None] * 4
    assert warnings(caplog) == [
        f"get_session_context section {s.value} unavailable" for s in Section
    ]


def test_empty_sections_are_empty_tuples_not_unavailable() -> None:
    use_case, _ = make_use_case(
        session_responses(**{name: [] for name in SECTION_QUERY_NAMES.values()})
    )

    context = use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert [section_items(context, s) for s in Section] == [(), (), (), ()]
    assert context.unavailable == ()
    assert context.truncated == ()


def responses_with(cards: int, transactions: int, signals: int, cases: int) -> dict[str, Outcome]:
    """Return session responses with the given number of rows per section."""
    return session_responses(
        session_credit_cards=[make_card_row() for _ in range(cards)],
        session_recent_transactions=[make_transaction_row() for _ in range(transactions)],
        session_digital_signals=[make_signal_row() for _ in range(signals)],
        session_open_cases=[make_case_row() for _ in range(cases)],
    )


def test_each_list_is_capped_and_marked_truncated() -> None:
    use_case, _ = make_use_case(responses_with(26, 26, 26, 6))

    context = use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert [len(section_items(context, s)) for s in Section] == [25, 25, 25, 5]
    assert context.truncated == tuple(Section)
    assert context.unavailable == ()


def test_exactly_the_cap_is_not_truncated() -> None:
    use_case, _ = make_use_case(responses_with(25, 25, 25, 5))

    context = use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert [len(section_items(context, s)) for s in Section] == [25, 25, 25, 5]
    assert context.truncated == ()


def test_max_rows_below_five_caps_open_cases() -> None:
    use_case, database_repository = make_use_case(responses_with(4, 4, 4, 4), max_rows=3)

    context = use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert [len(section_items(context, s)) for s in Section] == [3, 3, 3, 3]
    assert context.truncated == tuple(Section)
    limits = {q: p["limit"] for q, p in database_repository.calls if "limit" in p}
    assert limits == {name: 4 for name in SECTION_QUERY_NAMES.values()}


@pytest.mark.parametrize("max_rows", [0, -1])
def test_max_rows_below_one_is_rejected(max_rows: int) -> None:
    with pytest.raises(ValueError, match="max_rows"):
        GetSessionContextUseCase(
            database_repository=FakeSessionRepository(),
            query_provider=FakeQueryProvider(),
            max_rows=max_rows,
        )


def transaction_with(**flags: object) -> RecentTransaction:
    """Run the use case on one transaction row with the given flag columns."""
    use_case, _ = make_use_case(
        session_responses(session_recent_transactions=[make_transaction_row(**flags)])
    )
    transactions = use_case.execute(CUSTOMER_ID, as_of=AS_OF).recent_transactions
    assert transactions is not None
    return transactions[0]


@pytest.mark.parametrize("flag", list(TransactionFlag), ids=lambda f: f.value)
def test_each_flag_maps_from_its_column(flag: TransactionFlag) -> None:
    columns = {f"is_{f.value}": f is flag for f in TransactionFlag}

    assert transaction_with(**columns).flags == (flag,)


def test_all_flags_come_in_enum_order() -> None:
    columns = {f"is_{f.value}": True for f in TransactionFlag}

    assert transaction_with(**columns).flags == tuple(TransactionFlag)


def test_null_flags_mean_not_flagged() -> None:
    columns = {f"is_{f.value}": None for f in TransactionFlag}

    assert transaction_with(**columns).flags == ()


def test_a_non_bool_flag_makes_only_transactions_unavailable() -> None:
    use_case, _ = make_use_case(
        session_responses(session_recent_transactions=[make_transaction_row(is_foreign=1)])
    )

    context = use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert context.recent_transactions is None
    assert context.unavailable == (Section.RECENT_TRANSACTIONS,)
    assert context.cards is not None and len(context.cards) == 1


def test_null_values_stay_none() -> None:
    use_case, _ = make_use_case(
        session_responses(
            session_customer_profile=[make_profile_row(first_name=None, city=None)],
            session_open_cases=[
                make_case_row(sla_breached=None, claimed_amount=None, days_open=None)
            ],
        )
    )

    context = use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert context.customer.first_name is None
    assert context.customer.city is None
    assert context.open_cases is not None
    case = context.open_cases[0]
    assert (case.sla_breached, case.claimed_amount, case.days_open) == (None, None, None)


def test_a_timestamp_expiration_date_keeps_only_the_date() -> None:
    use_case, _ = make_use_case(
        session_responses(
            session_credit_cards=[make_card_row(expiration_date=datetime(2027, 3, 31))]
        )
    )

    cards = use_case.execute(CUSTOMER_ID, as_of=AS_OF).cards

    assert cards is not None
    assert cards[0].expiration_date == date(2027, 3, 31)
```

- [ ] **Step 2: Run them to see them fail**

Run: `$PY -m pytest tests/unit/get_session_context/test_get_session_context_use_case.py -q -p no:cacheprovider </dev/null`
Expected: a collection error, `ModuleNotFoundError: No module named 'get_session_context_lambda.application.use_cases.get_session_context'`.

- [ ] **Step 3: Write the entities**

`gateway/tools/get_session_context/get_session_context_lambda/domain/entities/session_context.py`:

```python
"""Session context entities returned by the get_session_context use case.

Every field that comes from a nullable column is ``| None``: the source data has
about 5% nulls, and a row with a null column is still returned.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum


@dataclass(frozen=True)
class Customer:
    """The customer's profile, without any sensitive column.

    ``customer_id`` is never None: it is the row's key.
    """

    customer_id: str
    first_name: str | None
    country: str | None
    city: str | None
    customer_status: str | None


@dataclass(frozen=True)
class CreditCard:
    """One of the customer's credit cards (the same fields as list_credit_cards).

    ``product_status`` is a plain string because the database may hold values
    outside the four known ones. The internal ``product_id`` is never exposed;
    other tools address cards by ``card_last4``.
    """

    card_last4: str | None
    product_status: str | None
    currency: str | None
    current_balance: Decimal | None
    credit_limit: Decimal | None
    available_credit: Decimal | None
    expiration_date: date | None
    days_past_due: int | None


class TransactionFlag(str, Enum):
    """A risk flag on a recent transaction, declared in output order."""

    DECLINED = "declined"
    FOREIGN = "foreign"
    ABOVE_USUAL_AMOUNT = "above_usual_amount"
    NEW_MERCHANT = "new_merchant"


@dataclass(frozen=True)
class RecentTransaction:
    """A credit-card transaction from the 72 hours up to as_of.

    ``flags`` holds only the flags that are true, in enum order.
    """

    transaction_id: str | None
    transaction_date: datetime | None
    card_last4: str | None
    merchant_name: str | None
    amount: Decimal | None
    currency: str | None
    transaction_status: str | None
    transaction_country: str | None
    flags: tuple[TransactionFlag, ...]


@dataclass(frozen=True)
class DigitalSignal:
    """An app/web event from the 24 hours up to as_of that carries a signal.

    ``signal`` is never None, because rows without one are filtered in SQL. It's
    a plain string: the SQL owns the mapping and the contract test pins the four
    values.
    """

    event_date: datetime | None
    signal: str
    page_title: str | None
    ip_country: str | None
    ip_city: str | None


@dataclass(frozen=True)
class OpenCase:
    """A complaint or claim that is open at as_of."""

    complaint_id: str | None
    case_type: str | None
    category: str | None
    subcategory: str | None
    status: str | None
    priority: str | None
    sla_breached: bool | None
    claimed_amount: Decimal | None
    currency: str | None
    days_open: int | None


class Section(str, Enum):
    """A snapshot section that can fail on its own, declared in output order.

    Each value is the name of the SessionContext attribute that holds it.
    """

    CARDS = "cards"
    RECENT_TRANSACTIONS = "recent_transactions"
    DIGITAL_SIGNALS = "digital_signals"
    OPEN_CASES = "open_cases"


@dataclass(frozen=True)
class SessionContext:
    """The customer's snapshot at as_of.

    A section is None when it couldn't be loaded; it is then listed in
    ``unavailable``. An empty tuple means there is nothing. ``truncated`` lists
    the sections that had more rows than their cap. Both lists are in enum order.
    """

    as_of: datetime
    customer: Customer
    cards: tuple[CreditCard, ...] | None
    recent_transactions: tuple[RecentTransaction, ...] | None
    digital_signals: tuple[DigitalSignal, ...] | None
    open_cases: tuple[OpenCase, ...] | None
    truncated: tuple[Section, ...]
    unavailable: tuple[Section, ...]
```

- [ ] **Step 4: Write the use case**

`gateway/tools/get_session_context/get_session_context_lambda/application/use_cases/get_session_context.py`:

```python
"""Use case: load the customer's session-start snapshot."""

import logging
from collections.abc import Callable, Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Final

from get_session_context_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from get_session_context_lambda.application.ports.errors import (
    DataAccessError,
    DataSourceConnectionError,
)
from get_session_context_lambda.application.ports.query_provider import QueryProvider
from get_session_context_lambda.domain.entities.session_context import (
    CreditCard,
    Customer,
    DigitalSignal,
    OpenCase,
    RecentTransaction,
    Section,
    SessionContext,
    TransactionFlag,
)
from get_session_context_lambda.domain.errors import (
    CustomerNotFoundError,
    DataSourceUnavailableError,
    InvalidInputError,
    SessionContextDataIntegrityError,
    SessionContextLookupError,
)

logger = logging.getLogger(__name__)

PROFILE_QUERY_NAME: Final = "session_customer_profile"
# The query of each section, in Section order.
SECTION_QUERY_NAMES: Final[Mapping[Section, str]] = {
    Section.CARDS: "session_credit_cards",
    Section.RECENT_TRANSACTIONS: "session_recent_transactions",
    Section.DIGITAL_SIGNALS: "session_digital_signals",
    Section.OPEN_CASES: "session_open_cases",
}
# The sections whose query counts back from as_of.
_TIMED_SECTIONS: Final = frozenset(
    {Section.RECENT_TRANSACTIONS, Section.DIGITAL_SIGNALS, Section.OPEN_CASES}
)


class GetSessionContextUseCase:
    """Load the customer's snapshot through a database-agnostic repository.

    Five queries run one after another on the repository's single connection.
    The customer section is the core: its failure fails the call with a domain
    error. Each other section fails on its own: it becomes None and is listed in
    ``unavailable``, and the next section still runs.
    """

    OPEN_CASES_CAP: Final = 5

    def __init__(
        self,
        database_repository: DatabaseRepository,
        query_provider: QueryProvider,
        max_rows: int = 25,
    ) -> None:
        """Store the ports and the row cap.

        Args:
            database_repository: Executes the queries; any DatabaseRepository
                adapter.
            query_provider: Supplies the SQL text for the configured dialect.
            max_rows: Maximum items per list; open cases are capped at
                min(OPEN_CASES_CAP, max_rows).

        Raises:
            ValueError: If max_rows is less than 1.
        """
        if max_rows < 1:
            raise ValueError("max_rows must be at least 1")
        self._database_repository: DatabaseRepository = database_repository
        self._query_provider: QueryProvider = query_provider
        self._max_rows: int = max_rows

    def execute(self, customer_id: object, as_of: datetime) -> SessionContext:
        """Clean the id, then load the customer and the four other sections.

        Each section's query asks for one row more than its cap, so the result
        can say whether more exist.

        Args:
            customer_id: The customer id exactly as it came in the tool event.
            as_of: "Now", an aware datetime. Every query gets it as naive UTC,
                because the ERD's timestamp columns have no time zone.

        Raises:
            InvalidInputError: customer_id is missing, not a string or blank.
                Raised before the database is touched.
            ValueError: as_of is naive (a programming error, not user input).
            DataSourceUnavailableError: The customer query couldn't connect.
            SessionContextLookupError: The customer query is missing, failed or
                hit a database limit.
            CustomerNotFoundError: No customer row matches customer_id.
            SessionContextDataIntegrityError: The customer row couldn't be mapped.
        """
        clean_id = _clean_customer_id(customer_id)
        as_of_utc = _utc(as_of)
        as_of_sql = as_of_utc.replace(tzinfo=None)
        customer = self._customer(clean_id)

        sections: dict[Section, tuple[Any, ...] | None] = {}
        truncated: list[Section] = []
        unavailable: list[Section] = []
        for section in Section:
            cap = self._cap(section)
            try:
                rows = self._run(
                    SECTION_QUERY_NAMES[section],
                    self._params(section, clean_id, as_of_sql),
                )
                items = tuple(_SECTION_MAPPERS[section](row) for row in rows[:cap])
            except (DataAccessError, KeyError, TypeError, ValueError):
                logger.warning(
                    "get_session_context section %s unavailable",
                    section.value,
                    exc_info=True,
                )
                sections[section] = None
                unavailable.append(section)
                continue
            sections[section] = items
            if len(rows) > cap:
                truncated.append(section)

        return SessionContext(
            as_of=as_of_utc,
            customer=customer,
            cards=sections[Section.CARDS],
            recent_transactions=sections[Section.RECENT_TRANSACTIONS],
            digital_signals=sections[Section.DIGITAL_SIGNALS],
            open_cases=sections[Section.OPEN_CASES],
            truncated=tuple(truncated),
            unavailable=tuple(unavailable),
        )

    def _customer(self, customer_id: str) -> Customer:
        """Load and map the customer row, translating every failure.

        Raises:
            DataSourceUnavailableError: The query couldn't connect.
            SessionContextLookupError: Any other data-access failure.
            CustomerNotFoundError: No row came back.
            SessionContextDataIntegrityError: The row couldn't be mapped.
        """
        try:
            rows = self._run(PROFILE_QUERY_NAME, {"customer_id": customer_id})
        except DataSourceConnectionError as exc:
            raise DataSourceUnavailableError() from exc
        except DataAccessError as exc:
            raise SessionContextLookupError() from exc
        if not rows:
            raise CustomerNotFoundError()
        try:
            return _to_customer(rows[0])
        except (KeyError, TypeError, ValueError) as exc:
            raise SessionContextDataIntegrityError() from exc

    def _run(self, name: str, params: Mapping[str, object]) -> list[dict[str, Any]]:
        """Load the named SQL and run it.

        Raises:
            DataAccessError: The query is missing or failed.
        """
        query = self._query_provider.get(name)
        return self._database_repository.execute_query(query, params)

    def _cap(self, section: Section) -> int:
        """Return the maximum number of items the section returns."""
        if section is Section.OPEN_CASES:
            return min(self.OPEN_CASES_CAP, self._max_rows)
        return self._max_rows

    def _params(
        self, section: Section, customer_id: str, as_of_sql: datetime
    ) -> dict[str, object]:
        """Build a section's query parameters; every key must match a placeholder."""
        params: dict[str, object] = {
            "customer_id": customer_id,
            "limit": self._cap(section) + 1,
        }
        if section in _TIMED_SECTIONS:
            params["as_of"] = as_of_sql
        return params


def _clean_customer_id(raw: object) -> str:
    """Strip and uppercase the raw id; ids look like ``CLI-ITIECUE8PRH9``.

    There is no format check: a malformed or unknown id just finds no customer.
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


def _utc(as_of: datetime) -> datetime:
    """Return as_of converted to aware UTC.

    Raises:
        ValueError: as_of is naive.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be an aware datetime")
    return as_of.astimezone(timezone.utc)


def _to_customer(row: Mapping[str, Any]) -> Customer:
    """Map the profile row to a Customer.

    Raises:
        KeyError: A column is missing.
        TypeError: customer_id is None.
    """
    return Customer(
        customer_id=_required_text(row, "customer_id"),
        first_name=_optional_text(row, "first_name"),
        country=_optional_text(row, "country"),
        city=_optional_text(row, "city"),
        customer_status=_optional_text(row, "customer_status"),
    )


def _to_card(row: Mapping[str, Any]) -> CreditCard:
    """Map one card row to a CreditCard.

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


def _to_transaction(row: Mapping[str, Any]) -> RecentTransaction:
    """Map one transaction row to a RecentTransaction.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type.
        ValueError: The amount isn't finite.
    """
    return RecentTransaction(
        transaction_id=_optional_text(row, "transaction_id"),
        transaction_date=_optional_datetime(row, "transaction_date"),
        card_last4=_optional_text(row, "card_last4"),
        merchant_name=_optional_text(row, "merchant_name"),
        amount=_optional_amount(row, "amount"),
        currency=_optional_text(row, "currency"),
        transaction_status=_optional_text(row, "transaction_status"),
        transaction_country=_optional_text(row, "transaction_country"),
        flags=_flags(row),
    )


def _to_signal(row: Mapping[str, Any]) -> DigitalSignal:
    """Map one signal row to a DigitalSignal.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type, or signal is None.
    """
    return DigitalSignal(
        event_date=_optional_datetime(row, "event_date"),
        signal=_required_text(row, "signal"),
        page_title=_optional_text(row, "page_title"),
        ip_country=_optional_text(row, "ip_country"),
        ip_city=_optional_text(row, "ip_city"),
    )


def _to_case(row: Mapping[str, Any]) -> OpenCase:
    """Map one case row to an OpenCase.

    Raises:
        KeyError: A column is missing.
        TypeError: A column has the wrong type.
        ValueError: The amount isn't finite.
    """
    return OpenCase(
        complaint_id=_optional_text(row, "complaint_id"),
        case_type=_optional_text(row, "case_type"),
        category=_optional_text(row, "category"),
        subcategory=_optional_text(row, "subcategory"),
        status=_optional_text(row, "status"),
        priority=_optional_text(row, "priority"),
        sla_breached=_optional_bool(row, "sla_breached"),
        claimed_amount=_optional_amount(row, "claimed_amount"),
        currency=_optional_text(row, "currency"),
        days_open=_optional_int(row, "days_open"),
    )


def _flags(row: Mapping[str, Any]) -> tuple[TransactionFlag, ...]:
    """Return the true flags in enum order; NULL means "not flagged".

    Raises:
        KeyError: A flag column is missing.
        TypeError: A flag column is neither a bool nor None.
    """
    return tuple(
        flag for flag in TransactionFlag if _optional_bool(row, f"is_{flag.value}")
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


# The row mapper of each section.
_SECTION_MAPPERS: Final[Mapping[Section, Callable[[Mapping[str, Any]], Any]]] = {
    Section.CARDS: _to_card,
    Section.RECENT_TRANSACTIONS: _to_transaction,
    Section.DIGITAL_SIGNALS: _to_signal,
    Section.OPEN_CASES: _to_case,
}
```

- [ ] **Step 5: Run the tests**

Run: `$PY -m pytest tests/unit/get_session_context/test_get_session_context_use_case.py -q -p no:cacheprovider </dev/null 2>&1 | tail -2`
Expected: all pass.

- [ ] **Step 6: Lint**

```bash
$PY -m ruff format gateway/tools/get_session_context tests/unit/get_session_context </dev/null
$PY -m ruff check gateway/tools/get_session_context tests/unit/get_session_context </dev/null
```

Expected: `ruff check` is clean. `ruff format` may rewrap a few long test lines; that's fine. Run the Step 5 command again afterwards; expected: all pass.

---

### Task 5: SQL files, `tool_spec.json` and contract tests

**Files:**
- Create: `gateway/tools/get_session_context/get_session_context_lambda/queries/postgresql/session_customer_profile.sql`
- Create: `.../queries/postgresql/session_credit_cards.sql` (copied from `list_credit_cards.sql`, new header)
- Create: `.../queries/postgresql/session_recent_transactions.sql`
- Create: `.../queries/postgresql/session_digital_signals.sql`
- Create: `.../queries/postgresql/session_open_cases.sql`
- Create: `gateway/tools/get_session_context/tool_spec.json`
- Test: `tests/unit/get_session_context/test_query_contracts.py`

**Interfaces:**
- Consumes:
  - Task 4: `GetSessionContextUseCase`, `PROFILE_QUERY_NAME`, `SECTION_QUERY_NAMES` and the entities.
  - Task 2: `FileQueryProvider` and the fakes `QUERY_NAMES`, `FakeQueryProvider`, `FakeSessionRepository`, `session_responses`.
- Produces:
  - Five SQL files whose placeholders are exactly the params the use case sends.
  - The selected columns are the ones the use case maps. Transactions also select `is_declined`, `is_foreign`, `is_above_usual_amount` and `is_new_merchant`.
  - `tool_spec.json` with the spec §4.6 definition.

- [ ] **Step 1: Write the failing contract tests**

`tests/unit/get_session_context/test_query_contracts.py`:

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
from get_session_context_lambda.application.use_cases.get_session_context import (
    GetSessionContextUseCase,
)
from get_session_context_lambda.domain.entities.session_context import (
    CreditCard,
    Customer,
    DigitalSignal,
    OpenCase,
    RecentTransaction,
    TransactionFlag,
)
from get_session_context_lambda.infrastructure.queries.file_query_provider import (
    FileQueryProvider,
)

from .fakes import (
    CUSTOMER_ID,
    QUERY_NAMES,
    FakeQueryProvider,
    FakeSessionRepository,
    session_responses,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_ROOT = REPO_ROOT / "gateway/tools/get_session_context"
QUERIES_DIR = TOOL_ROOT / "get_session_context_lambda/queries/postgresql"
TOOL_SPEC = TOOL_ROOT / "tool_spec.json"
PLACEHOLDER = re.compile(r"%\((\w+)\)s")
SESSION_STATEMENT = re.compile(r"^\s*SET\b", re.IGNORECASE | re.MULTILINE)
SQL_COMMENT = re.compile(r"--[^\n]*")
AS_OF = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
# The accent is built from its code point (NFC U+00E9), so this test file's own
# encoding can't change the expected values.
E_ACUTE = chr(0xE9)
CREDIT_CARD_FILTER = f"p.product_type = 'Tarjeta Cr{E_ACUTE}dito'"
CREDIT_CARD_PAGE = f"'Tarjeta de Cr{E_ACUTE}dito'"
# The entity each query's rows are mapped to.
QUERY_ENTITIES: dict[str, type] = {
    "session_customer_profile": Customer,
    "session_credit_cards": CreditCard,
    "session_recent_transactions": RecentTransaction,
    "session_digital_signals": DigitalSignal,
    "session_open_cases": OpenCase,
}
SENSITIVE_CUSTOMER_COLUMNS = (
    "document_number",
    "document_type",
    "date_of_birth",
    "gender",
    "email",
    "mobile_phone",
    "landline_phone",
    "credit_score",
    "estimated_monthly_income",
)
SIGNALS = (
    "FAILED_ACTION",
    "REVIEWING_TRANSACTIONS",
    "VIEWING_CREDIT_CARD",
    "SEEKING_HELP",
)


def sql(name: str) -> str:
    """Load one of the real queries."""
    return FileQueryProvider(QUERIES_DIR).get(name)


def flat_sql(name: str) -> str:
    """Return the query without comments, every run of whitespace one space."""
    return " ".join(SQL_COMMENT.sub("", sql(name)).split())


def sent_params() -> dict[str, dict[str, object]]:
    """Return the params the use case actually sends, keyed by query name."""
    database_repository = FakeSessionRepository(session_responses())
    GetSessionContextUseCase(
        database_repository=database_repository, query_provider=FakeQueryProvider()
    ).execute(CUSTOMER_ID, as_of=AS_OF)
    return dict(database_repository.calls)


def test_the_query_list_matches_the_sql_folder() -> None:
    assert sorted(path.stem for path in QUERIES_DIR.glob("*.sql")) == sorted(
        QUERY_NAMES
    )
    assert list(QUERY_ENTITIES) == list(QUERY_NAMES)


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_placeholders_match_the_use_case_params_exactly(name: str) -> None:
    assert set(PLACEHOLDER.findall(sql(name))) == set(sent_params()[name])


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_has_no_stray_percent_signs(name: str) -> None:
    # psycopg treats every '%' as a placeholder marker once params are passed,
    # including inside comments.
    assert "%" not in PLACEHOLDER.sub("", sql(name))


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_sets_no_session_parameters(name: str) -> None:
    # DSQL rejects most session parameters (statement_timeout among them).
    text = sql(name)

    assert SESSION_STATEMENT.search(text) is None
    assert "statement_timeout" not in text.lower()


def test_session_statement_check_ignores_offset() -> None:
    assert SESSION_STATEMENT.search("SELECT 1\nOFFSET 0\n") is None
    assert SESSION_STATEMENT.search("SELECT 1;\n  set statement_timeout = 0;\n")


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_is_nfc_utf8_without_bom(name: str) -> None:
    # A decomposed accent or a BOM would silently match nothing (risk C1).
    raw = (QUERIES_DIR / f"{name}.sql").read_bytes()

    assert not raw.startswith(b"\xef\xbb\xbf")
    assert unicodedata.is_normalized("NFC", raw.decode("utf-8"))


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_sql_selects_every_column_the_use_case_maps(name: str) -> None:
    text = flat_sql(name)

    for field in dataclasses.fields(QUERY_ENTITIES[name]):
        if field.name == "flags":
            continue
        assert re.search(rf"\b{field.name}\b", text), field.name


def test_transactions_select_one_column_per_flag() -> None:
    text = flat_sql("session_recent_transactions")

    for flag in TransactionFlag:
        assert f"AS is_{flag.value}" in text, flag.value


def test_profile_selects_no_sensitive_column() -> None:
    text = flat_sql("session_customer_profile")

    assert "c.*" not in text
    for column in SENSITIVE_CUSTOMER_COLUMNS:
        assert column not in text, column


def test_profile_reads_one_customer_keeping_the_latest_copy() -> None:
    text = flat_sql("session_customer_profile")

    assert "SELECT DISTINCT ON (c.customer_id)" in text
    assert "WHERE c.customer_id = %(customer_id)s" in text
    assert "ORDER BY c.customer_id, c.last_updated DESC NULLS LAST" in text


@pytest.mark.parametrize(
    "name", ["session_credit_cards", "session_recent_transactions"]
)
def test_cards_and_transactions_are_credit_cards_only(name: str) -> None:
    text = flat_sql(name)

    assert CREDIT_CARD_FILTER in text
    assert "ILIKE" not in text.upper()


def test_credit_cards_lists_active_cards_first() -> None:
    assert (
        "ORDER BY (deduplicated.product_status = 'Active') DESC NULLS LAST, "
        "deduplicated.expiration_date DESC NULLS LAST, "
        "deduplicated.product_id LIMIT %(limit)s"
    ) in flat_sql("session_credit_cards")


def test_transactions_window_baseline_and_flags() -> None:
    text = flat_sql("session_recent_transactions")

    assert "t.process_date >= (%(as_of)s::date - 90)" in text
    assert "t.transaction_date <= %(as_of)s" in text
    assert "transaction_date >= %(as_of)s - INTERVAL '72 hours'" in text
    assert "transaction_date < %(as_of)s - INTERVAL '72 hours'" in text
    assert "percentile_cont(0.95) WITHIN GROUP (ORDER BY amount_usd)" in text
    assert "WHERE transaction_status = 'Approved'" in text
    assert "(r.transaction_status = 'Declined') AS is_declined" in text
    assert "(r.transaction_country <> h.country) AS is_foreign" in text
    assert (
        "(r.amount_usd > COALESCE(b.p95_usd, 'Infinity')) AS is_above_usual_amount"
    ) in text
    assert "r.merchant_name IS NOT NULL AND NOT EXISTS" in text
    assert "LEFT JOIN home AS h ON TRUE" in text
    assert (
        "ORDER BY r.transaction_date DESC NULLS LAST, r.transaction_id "
        "LIMIT %(limit)s"
    ) in text


def test_signals_map_the_confirmed_values_in_order() -> None:
    text = flat_sql("session_digital_signals")
    rules = [
        "WHEN e.event_type = 'Error' THEN 'FAILED_ACTION'",
        "WHEN e.page_title = 'Mis Movimientos' OR e.action = 'view_transactions' "
        "THEN 'REVIEWING_TRANSACTIONS'",
        f"WHEN e.page_title = {CREDIT_CARD_PAGE} THEN 'VIEWING_CREDIT_CARD'",
        "WHEN e.page_title = 'Ayuda' OR e.action = 'view_help' THEN 'SEEKING_HELP'",
    ]

    positions = [text.find(rule) for rule in rules]
    assert -1 not in positions, positions
    assert positions == sorted(positions)
    for signal in SIGNALS:
        assert f"'{signal}'" in text
    assert "ILIKE" not in text.upper()


def test_signals_window_and_filter() -> None:
    text = flat_sql("session_digital_signals")

    assert "e.process_date >= (%(as_of)s::date - 1)" in text
    assert "e.event_date > %(as_of)s - INTERVAL '24 hours'" in text
    assert "e.event_date <= %(as_of)s" in text
    assert "WHERE signals.signal IS NOT NULL" in text
    assert (
        "ORDER BY signals.event_date DESC NULLS LAST, signals.event_id "
        "LIMIT %(limit)s"
    ) in text


def test_open_cases_are_the_ones_open_at_as_of() -> None:
    text = flat_sql("session_open_cases")

    assert "k.creation_date <= %(as_of)s" in text
    assert "(k.closing_date IS NULL OR k.closing_date > %(as_of)s)" in text
    assert "NOT IN" not in text.upper()
    assert (
        "(%(as_of)s::date - deduplicated.creation_date::date) AS days_open"
    ) in text
    assert (
        "ORDER BY deduplicated.sla_breached DESC NULLS LAST, "
        "deduplicated.creation_date DESC NULLS LAST, "
        "deduplicated.complaint_id LIMIT %(limit)s"
    ) in text


def tool_spec() -> dict[str, Any]:
    """Load the single tool definition from tool_spec.json."""
    specs = json.loads(TOOL_SPEC.read_text(encoding="utf-8"))
    assert isinstance(specs, list) and len(specs) == 1
    return specs[0]


def test_tool_spec_name_and_required_fields() -> None:
    spec = tool_spec()

    assert spec["name"] == "get_session_context"
    assert spec["inputSchema"]["required"] == ["customer_id"]


def test_tool_spec_has_only_the_customer_id_property() -> None:
    properties = tool_spec()["inputSchema"]["properties"]

    assert set(properties) == {"customer_id"}
    assert properties["customer_id"]["type"] == "string"


def test_tool_spec_description_names_flags_signals_and_the_lists() -> None:
    description = tool_spec()["description"]

    for flag in TransactionFlag:
        assert flag.value in description, flag.value
    for signal in SIGNALS:
        assert signal in description, signal
    assert "'unavailable'" in description
    assert "'truncated'" in description
    assert "at most 25 items (5 open cases)" in description
```

- [ ] **Step 2: Run them to see them fail**

Run: `$PY -m pytest tests/unit/get_session_context/test_query_contracts.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: many failures. `QueryNotFoundError` for every SQL test, `FileNotFoundError` for the tool_spec tests, and an assertion error in `test_the_query_list_matches_the_sql_folder`. `test_session_statement_check_ignores_offset` passes.

- [ ] **Step 3: Write `session_customer_profile.sql`**

```sql
-- session_customer_profile (PostgreSQL dialect, runs on Aurora DSQL)
--
-- The customer's profile for the session snapshot. Used by
-- GetSessionContextUseCase; it is the core section, so its failure fails the call.
--
-- Parameters (psycopg named placeholders):
--   customer_id  text  required (the use case strips and uppercases it)
--
-- Sensitive columns (document, date of birth, gender, contact details, credit
-- score, income) are deliberately not selected. No column list wildcard is used,
-- so a new column never leaks by accident.
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster. DISTINCT ON
--   and NULLS LAST are standard PostgreSQL, but DSQL support is unverified. Column
--   names follow docs/LATAM_Bank_ERD.md; smoke-test against a real cluster.
-- TODO(ledgerlens): R8 - about 2 in 100 rows are duplicated; DISTINCT ON removes
--   them at query time, keeping the latest last_updated. Drop it once the data
--   load deduplicates.
SELECT DISTINCT ON (c.customer_id)
       c.customer_id,
       c.first_name,
       c.country,
       c.city,
       c.customer_status
FROM customers AS c
WHERE c.customer_id = %(customer_id)s
ORDER BY c.customer_id, c.last_updated DESC NULLS LAST
```

- [ ] **Step 4: Write `session_credit_cards.sql`**

Copy the body, then replace the header:

```bash
cp gateway/tools/list_credit_cards/list_credit_cards_lambda/queries/postgresql/list_credit_cards.sql gateway/tools/get_session_context/get_session_context_lambda/queries/postgresql/session_credit_cards.sql
```

Replace the first four lines of the new file:

```sql
-- list_credit_cards (PostgreSQL dialect, runs on Aurora DSQL)
--
-- A customer's credit cards in every status, active first, one row per product_id.
-- Used by ListCreditCardsUseCase.
```

with:

```sql
-- session_credit_cards (PostgreSQL dialect, runs on Aurora DSQL)
--
-- The cards section of the session snapshot: the customer's credit cards in every
-- status, active first, one row per product_id. A copy of list_credit_cards.sql
-- from the list_credit_cards tool (copies, not shared code). Used by
-- GetSessionContextUseCase; a failure here only makes the cards section
-- unavailable.
```

Leave everything from `-- Parameters (psycopg named placeholders):` to the end exactly as copied. Check it:

```bash
diff <(tail -n +5 gateway/tools/list_credit_cards/list_credit_cards_lambda/queries/postgresql/list_credit_cards.sql) <(tail -n +8 gateway/tools/get_session_context/get_session_context_lambda/queries/postgresql/session_credit_cards.sql)
```

Expected: no output.

- [ ] **Step 5: Write `session_recent_transactions.sql`**

```sql
-- session_recent_transactions (PostgreSQL dialect, runs on Aurora DSQL)
--
-- Credit-card transactions from the 72 hours up to as_of, newest first, with four
-- risk flags. Used by GetSessionContextUseCase; a failure here only makes the
-- recent_transactions section unavailable.
--
-- Parameters (psycopg named placeholders):
--   customer_id  text       required (the use case strips and uppercases it)
--   as_of        timestamp  "now" as naive UTC (the AS_OF env var, or the real time)
--   limit        integer    max rows plus one (the extra row marks the section truncated)
--
-- Credit cards only (product_type = 'Tarjeta Crédito'), so card_last4 always
-- matches a card in the cards section and the baseline compares like with like.
-- Flags (NULL means "not flagged"; the use case maps NULL to false):
--   is_declined            transaction_status = 'Declined'. Pending and Reversed
--                          are not declines; the model sees them in the status.
--   is_foreign             the transaction country differs from the customer's.
--                          LEFT JOIN home keeps every row when the customer row is
--                          missing: the comparison is NULL, so not foreign.
--   is_above_usual_amount  above the 95th percentile of approved USD amounts in
--                          the 90 days before the window. With no history the
--                          baseline is Infinity, so nothing is flagged.
--   is_new_merchant        a merchant not seen in that history. A NULL merchant
--                          is never new.
-- process_date >= as_of::date - 90 is there for partition pruning (product design
-- section 8.1). CROSS JOIN baseline is safe: an aggregate always returns one row.
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster.
--   percentile_cont ... WITHIN GROUP, DISTINCT ON inside a CTE and 'Infinity' for
--   numeric are standard PostgreSQL, but DSQL support is unverified. If DSQL
--   rejects one, this section comes back unavailable and the rest of the snapshot
--   still works. Column names follow docs/LATAM_Bank_ERD.md. The values
--   'Approved' and 'Declined' are confirmed in the dataset (risk C1, 2026-10-01).
-- TODO(ledgerlens): R8 - about 2 in 100 rows are duplicated; DISTINCT ON removes
--   them at query time. Drop it once the data load deduplicates.
WITH tx_dedup AS (
    SELECT DISTINCT ON (t.transaction_id)
           t.transaction_id, t.transaction_date, t.product_id,
           t.merchant_name, t.amount, t.currency, t.amount_usd,
           t.transaction_status, t.transaction_country,
           RIGHT(p.product_number, 4) AS card_last4
    FROM transactions AS t
    JOIN products AS p ON p.product_id = t.product_id
    WHERE t.customer_id = %(customer_id)s
      AND p.product_type = 'Tarjeta Crédito'
      AND t.process_date >= (%(as_of)s::date - 90)
      AND t.transaction_date <= %(as_of)s
    ORDER BY t.transaction_id, t.transaction_date DESC
),
recent AS (
    SELECT * FROM tx_dedup
    WHERE transaction_date >= %(as_of)s - INTERVAL '72 hours'
),
hist AS (
    SELECT * FROM tx_dedup
    WHERE transaction_date < %(as_of)s - INTERVAL '72 hours'
),
baseline AS (
    SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY amount_usd) AS p95_usd
    FROM hist
    WHERE transaction_status = 'Approved'
),
home AS (
    SELECT c.country
    FROM customers AS c
    WHERE c.customer_id = %(customer_id)s
    ORDER BY c.last_updated DESC NULLS LAST
    LIMIT 1
)
SELECT r.transaction_id,
       r.transaction_date,
       r.card_last4,
       r.merchant_name,
       r.amount,
       r.currency,
       r.transaction_status,
       r.transaction_country,
       (r.transaction_status = 'Declined')                       AS is_declined,
       (r.transaction_country <> h.country)                      AS is_foreign,
       (r.amount_usd > COALESCE(b.p95_usd, 'Infinity'))          AS is_above_usual_amount,
       (r.merchant_name IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM hist AS x
                        WHERE x.merchant_name = r.merchant_name)) AS is_new_merchant
FROM recent AS r
LEFT JOIN home AS h ON TRUE
CROSS JOIN baseline AS b
ORDER BY r.transaction_date DESC NULLS LAST, r.transaction_id
LIMIT %(limit)s
```

- [ ] **Step 6: Write `session_digital_signals.sql`**

```sql
-- session_digital_signals (PostgreSQL dialect, runs on Aurora DSQL)
--
-- App/web events from the 24 hours up to as_of that carry a signal, newest first.
-- Used by GetSessionContextUseCase; a failure here only makes the digital_signals
-- section unavailable.
--
-- Parameters (psycopg named placeholders):
--   customer_id  text       required (the use case strips and uppercases it)
--   as_of        timestamp  "now" as naive UTC (the AS_OF env var, or the real time)
--   limit        integer    max rows plus one (the extra row marks the section truncated)
--
-- The rules are checked in order and the first match wins, so an error on any
-- page is FAILED_ACTION. Matching on action as well keeps the signal when
-- page_title is NULL. Every other page (Inicio, Iniciar Sesión, Cerrar Sesión,
-- Préstamos, Cuenta de Ahorro, Pagar Servicios, Transferir, Mis Cuentas,
-- Productos) has no signal and is filtered out here, so the cap counts real
-- signals. event_id is selected only as a stable tie-break; the use case doesn't
-- map it.
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster. Column
--   names follow docs/LATAM_Bank_ERD.md. The event_type, page_title and action
--   values are confirmed in the dataset (risk C1, 2026-10-01).
-- TODO(ledgerlens): R8 - digital_events isn't deduplicated; a duplicate event only
--   repeats a signal.
SELECT signals.*
FROM (
    SELECT e.event_date,
           CASE
             WHEN e.event_type = 'Error'                                             THEN 'FAILED_ACTION'
             WHEN e.page_title = 'Mis Movimientos' OR e.action = 'view_transactions' THEN 'REVIEWING_TRANSACTIONS'
             WHEN e.page_title = 'Tarjeta de Crédito'                                THEN 'VIEWING_CREDIT_CARD'
             WHEN e.page_title = 'Ayuda' OR e.action = 'view_help'                   THEN 'SEEKING_HELP'
           END AS signal,
           e.page_title,
           e.ip_country,
           e.ip_city,
           e.event_id
    FROM digital_events AS e
    WHERE e.customer_id = %(customer_id)s
      AND e.process_date >= (%(as_of)s::date - 1)
      AND e.event_date >  %(as_of)s - INTERVAL '24 hours'
      AND e.event_date <= %(as_of)s
) AS signals
WHERE signals.signal IS NOT NULL
ORDER BY signals.event_date DESC NULLS LAST, signals.event_id
LIMIT %(limit)s
```

- [ ] **Step 7: Write `session_open_cases.sql`**

```sql
-- session_open_cases (PostgreSQL dialect, runs on Aurora DSQL)
--
-- Complaints and claims open at as_of, SLA breaches first, then the newest. Used
-- by GetSessionContextUseCase; a failure here only makes the open_cases section
-- unavailable.
--
-- Parameters (psycopg named placeholders):
--   customer_id  text       required (the use case strips and uppercases it)
--   as_of        timestamp  "now" as naive UTC (the AS_OF env var, or the real time)
--   limit        integer    max rows plus one (the extra row marks the section truncated)
--
-- "Open at as_of" means created on or before as_of and not closed by then, so a
-- case closed today still counts on a past demo date. status is returned as it is
-- stored now, so on a past AS_OF it can read Closed (risk C3, accepted for demos).
-- date minus date is an integer in PostgreSQL, so days_open maps to an int.
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
       deduplicated.priority,
       deduplicated.sla_breached,
       deduplicated.claimed_amount,
       deduplicated.currency,
       (%(as_of)s::date - deduplicated.creation_date::date) AS days_open
FROM (
    SELECT DISTINCT ON (k.complaint_id) k.*
    FROM complaints AS k
    WHERE k.customer_id = %(customer_id)s
      AND k.creation_date <= %(as_of)s
      AND (k.closing_date IS NULL OR k.closing_date > %(as_of)s)
    ORDER BY k.complaint_id, k.process_date DESC NULLS LAST
) AS deduplicated
ORDER BY deduplicated.sla_breached DESC NULLS LAST,
         deduplicated.creation_date DESC NULLS LAST,
         deduplicated.complaint_id
LIMIT %(limit)s
```

- [ ] **Step 8: Write `tool_spec.json`**

`gateway/tools/get_session_context/tool_spec.json`:

```json
[
  {
    "name": "get_session_context",
    "description": "Returns a snapshot of the customer: profile, credit cards, card transactions from the last 72 hours with risk flags (declined, foreign, above_usual_amount, new_merchant), app/web signals from the last 24 hours (FAILED_ACTION, REVIEWING_TRANSACTIONS, VIEWING_CREDIT_CARD, SEEKING_HELP) and open cases. Already called automatically at session start; call again only if the customer asks you to refresh or more than 30 minutes have passed. Lists hold at most 25 items (5 open cases). An empty list means there is nothing; a null section couldn't be loaded and is named in 'unavailable'. 'truncated' names lists that had more items. Amounts are strings with 2 decimals in the given currency.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "customer_id": {
          "type": "string",
          "description": "The authenticated customer's ID from SESSION CONTEXT."
        }
      },
      "required": ["customer_id"]
    }
  }
]
```

- [ ] **Step 9: Run the contract tests**

Run: `$PY -m pytest tests/unit/get_session_context/test_query_contracts.py -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: all pass.

Then check that the accented literals are NFC and contain no `%` outside placeholders:

```bash
grep -c "Tarjeta Crédito\|Tarjeta de Crédito" gateway/tools/get_session_context/get_session_context_lambda/queries/postgresql/*.sql
```

Expected: each file prints a count. `session_credit_cards.sql`, `session_recent_transactions.sql` and `session_digital_signals.sql` print at least 1; the other two print 0.

---

### Task 6: Presenter

**Files:**
- Create: `gateway/tools/get_session_context/get_session_context_lambda/delivery/presenters/session_context.py`
- Test: `tests/unit/get_session_context/test_session_context_presenter.py`

**Interfaces:**
- Consumes: Task 4's entities (`SessionContext`, `Customer`, `CreditCard`, `RecentTransaction`, `DigitalSignal`, `OpenCase`, `Section`, `TransactionFlag`).
- Produces: `present_session_context(context: SessionContext) -> dict[str, Any]`. It returns the spec §4.5 JSON, and every value in it can go through `json.dumps`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/get_session_context/test_session_context_presenter.py`:

```python
"""Tests for the session context presenter."""

import dataclasses
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from get_session_context_lambda.delivery.presenters.session_context import (
    present_session_context,
)
from get_session_context_lambda.domain.entities.session_context import (
    CreditCard,
    Customer,
    DigitalSignal,
    OpenCase,
    RecentTransaction,
    Section,
    SessionContext,
    TransactionFlag,
)

pytestmark = pytest.mark.unit

AS_OF = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
CUSTOMER = Customer(
    customer_id="CLI-ITIECUE8PRH9",
    first_name="Ana",
    country="Colombia",
    city="Bogotá",
    customer_status="Active",
)
CARD = CreditCard(
    card_last4="4821",
    product_status="Active",
    currency="COP",
    current_balance=Decimal("1250000.00"),
    credit_limit=Decimal("3000000.00"),
    available_credit=Decimal("1750000.00"),
    expiration_date=date(2027, 3, 31),
    days_past_due=0,
)
TRANSACTION = RecentTransaction(
    transaction_id="TX-1",
    transaction_date=datetime(2026, 3, 14, 10, 42),
    card_last4="4821",
    merchant_name="EXITO",
    amount=Decimal("350000.00"),
    currency="COP",
    transaction_status="Declined",
    transaction_country="Colombia",
    flags=(TransactionFlag.DECLINED, TransactionFlag.ABOVE_USUAL_AMOUNT),
)
SIGNAL = DigitalSignal(
    event_date=datetime(2026, 3, 14, 10, 48),
    signal="FAILED_ACTION",
    page_title="Tarjeta de Crédito",
    ip_country="Colombia",
    ip_city="Bogotá",
)
CASE = OpenCase(
    complaint_id="C-1182",
    case_type="Claim",
    category="Transactions",
    subcategory="Cargo no reconocido",
    status="Open",
    priority="High",
    sla_breached=False,
    claimed_amount=Decimal("350000.00"),
    currency="COP",
    days_open=3,
)


def make_context(**overrides: Any) -> SessionContext:
    """Build a full SessionContext; keyword arguments replace fields."""
    values: dict[str, Any] = {
        "as_of": AS_OF,
        "customer": CUSTOMER,
        "cards": (CARD,),
        "recent_transactions": (TRANSACTION,),
        "digital_signals": (SIGNAL,),
        "open_cases": (CASE,),
        "truncated": (),
        "unavailable": (),
    }
    values.update(overrides)
    return SessionContext(**values)


def test_presents_the_full_snapshot() -> None:
    assert present_session_context(make_context()) == {
        "as_of": "2026-03-14T12:00:00Z",
        "customer": {
            "customer_id": "CLI-ITIECUE8PRH9",
            "first_name": "Ana",
            "country": "Colombia",
            "city": "Bogotá",
            "customer_status": "Active",
        },
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
        "recent_transactions": [
            {
                "transaction_id": "TX-1",
                "transaction_date": "2026-03-14T10:42:00",
                "card_last4": "4821",
                "merchant_name": "EXITO",
                "amount": "350000.00",
                "currency": "COP",
                "transaction_status": "Declined",
                "transaction_country": "Colombia",
                "flags": ["declined", "above_usual_amount"],
            }
        ],
        "digital_signals": [
            {
                "event_date": "2026-03-14T10:48:00",
                "signal": "FAILED_ACTION",
                "page_title": "Tarjeta de Crédito",
                "ip_country": "Colombia",
                "ip_city": "Bogotá",
            }
        ],
        "open_cases": [
            {
                "complaint_id": "C-1182",
                "case_type": "Claim",
                "category": "Transactions",
                "subcategory": "Cargo no reconocido",
                "status": "Open",
                "priority": "High",
                "sla_breached": False,
                "claimed_amount": "350000.00",
                "currency": "COP",
                "days_open": 3,
            }
        ],
        "truncated": [],
        "unavailable": [],
    }


@pytest.mark.parametrize(
    "as_of",
    [
        datetime(2026, 3, 14, 12, 0, 0, 123456, tzinfo=timezone.utc),
        datetime(2026, 3, 14, 7, 0, tzinfo=timezone(timedelta(hours=-5))),
    ],
    ids=["microseconds", "other-zone"],
)
def test_as_of_is_utc_with_a_z_and_whole_seconds(as_of: datetime) -> None:
    assert present_session_context(make_context(as_of=as_of))["as_of"] == (
        "2026-03-14T12:00:00Z"
    )


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("0.005"), "0.01"),
        (Decimal("2.345"), "2.35"),
        (Decimal("10"), "10.00"),
        (Decimal("-1.005"), "-1.01"),
    ],
)
def test_amounts_are_rounded_half_up_to_two_decimals(
    amount: Decimal, expected: str
) -> None:
    context = make_context(
        cards=(dataclasses.replace(CARD, current_balance=amount),),
        recent_transactions=(dataclasses.replace(TRANSACTION, amount=amount),),
        open_cases=(dataclasses.replace(CASE, claimed_amount=amount),),
    )

    body = present_session_context(context)

    assert body["cards"][0]["current_balance"] == expected
    assert body["recent_transactions"][0]["amount"] == expected
    assert body["open_cases"][0]["claimed_amount"] == expected


def test_missing_values_are_null() -> None:
    context = make_context(
        customer=dataclasses.replace(CUSTOMER, first_name=None, city=None),
        cards=(
            dataclasses.replace(
                CARD, current_balance=None, expiration_date=None, days_past_due=None
            ),
        ),
        recent_transactions=(
            dataclasses.replace(
                TRANSACTION, transaction_date=None, amount=None, flags=()
            ),
        ),
        digital_signals=(dataclasses.replace(SIGNAL, event_date=None, ip_city=None),),
        open_cases=(
            dataclasses.replace(
                CASE, sla_breached=None, claimed_amount=None, days_open=None
            ),
        ),
    )

    body = present_session_context(context)

    assert body["customer"]["first_name"] is None
    assert body["customer"]["city"] is None
    card = body["cards"][0]
    assert (card["current_balance"], card["expiration_date"], card["days_past_due"]) == (
        None,
        None,
        None,
    )
    transaction = body["recent_transactions"][0]
    assert transaction["transaction_date"] is None
    assert transaction["amount"] is None
    assert transaction["flags"] == []
    assert body["digital_signals"][0]["event_date"] is None
    case = body["open_cases"][0]
    assert (case["sla_breached"], case["claimed_amount"], case["days_open"]) == (
        None,
        None,
        None,
    )


def test_empty_sections_are_empty_lists() -> None:
    body = present_session_context(
        make_context(
            cards=(), recent_transactions=(), digital_signals=(), open_cases=()
        )
    )

    for section in Section:
        assert body[section.value] == []
    assert body["unavailable"] == []


def test_unavailable_sections_are_null_and_named() -> None:
    body = present_session_context(
        make_context(
            recent_transactions=None,
            open_cases=None,
            unavailable=(Section.RECENT_TRANSACTIONS, Section.OPEN_CASES),
        )
    )

    assert body["recent_transactions"] is None
    assert body["open_cases"] is None
    assert body["cards"] is not None
    assert body["unavailable"] == ["recent_transactions", "open_cases"]


def test_truncated_sections_are_named() -> None:
    body = present_session_context(
        make_context(truncated=(Section.CARDS, Section.DIGITAL_SIGNALS))
    )

    assert body["truncated"] == ["cards", "digital_signals"]


def test_the_body_is_json_serialisable() -> None:
    text = json.dumps(present_session_context(make_context()), ensure_ascii=False)

    assert "Bogotá" in text
    assert json.loads(text)["as_of"] == "2026-03-14T12:00:00Z"
```

- [ ] **Step 2: Run them to see them fail**

Run: `$PY -m pytest tests/unit/get_session_context/test_session_context_presenter.py -q -p no:cacheprovider </dev/null`
Expected: a collection error, `ModuleNotFoundError: No module named 'get_session_context_lambda.delivery.presenters.session_context'`.

- [ ] **Step 3: Write the presenter**

`gateway/tools/get_session_context/get_session_context_lambda/delivery/presenters/session_context.py`:

```python
"""Present the session context as the JSON returned to the agent."""

from collections.abc import Callable
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final, TypeVar

from get_session_context_lambda.domain.entities.session_context import (
    CreditCard,
    Customer,
    DigitalSignal,
    OpenCase,
    RecentTransaction,
    SessionContext,
)

_CENTS: Final = Decimal("0.01")

_Item = TypeVar("_Item")


def present_session_context(context: SessionContext) -> dict[str, Any]:
    """Return the snapshot as JSON-safe values (spec section 4.5).

    An empty section is ``[]``; a section that couldn't be loaded is ``None``
    (JSON null) and is named in ``unavailable``. ``as_of`` is UTC with a ``Z``;
    row timestamps are ISO 8601 without a time zone, as stored. Amounts are
    2-decimal strings, so no float rounding reaches the agent. Missing values
    stay ``None``.
    """
    return {
        "as_of": _as_of(context.as_of),
        "customer": _customer(context.customer),
        "cards": _section(context.cards, _card),
        "recent_transactions": _section(context.recent_transactions, _transaction),
        "digital_signals": _section(context.digital_signals, _signal),
        "open_cases": _section(context.open_cases, _case),
        "truncated": [section.value for section in context.truncated],
        "unavailable": [section.value for section in context.unavailable],
    }


def _section(
    items: tuple[_Item, ...] | None, present: Callable[[_Item], dict[str, Any]]
) -> list[dict[str, Any]] | None:
    """Present every item, keeping None for an unavailable section."""
    if items is None:
        return None
    return [present(item) for item in items]


def _customer(customer: Customer) -> dict[str, Any]:
    """Convert the customer to JSON-safe values."""
    return {
        "customer_id": customer.customer_id,
        "first_name": customer.first_name,
        "country": customer.country,
        "city": customer.city,
        "customer_status": customer.customer_status,
    }


def _card(card: CreditCard) -> dict[str, Any]:
    """Convert one card to JSON-safe values."""
    return {
        "card_last4": card.card_last4,
        "product_status": card.product_status,
        "currency": card.currency,
        "current_balance": _amount(card.current_balance),
        "credit_limit": _amount(card.credit_limit),
        "available_credit": _amount(card.available_credit),
        "expiration_date": _iso(card.expiration_date),
        "days_past_due": card.days_past_due,
    }


def _transaction(transaction: RecentTransaction) -> dict[str, Any]:
    """Convert one transaction to JSON-safe values; flags become their names."""
    return {
        "transaction_id": transaction.transaction_id,
        "transaction_date": _iso(transaction.transaction_date),
        "card_last4": transaction.card_last4,
        "merchant_name": transaction.merchant_name,
        "amount": _amount(transaction.amount),
        "currency": transaction.currency,
        "transaction_status": transaction.transaction_status,
        "transaction_country": transaction.transaction_country,
        "flags": [flag.value for flag in transaction.flags],
    }


def _signal(signal: DigitalSignal) -> dict[str, Any]:
    """Convert one digital signal to JSON-safe values."""
    return {
        "event_date": _iso(signal.event_date),
        "signal": signal.signal,
        "page_title": signal.page_title,
        "ip_country": signal.ip_country,
        "ip_city": signal.ip_city,
    }


def _case(case: OpenCase) -> dict[str, Any]:
    """Convert one open case to JSON-safe values."""
    return {
        "complaint_id": case.complaint_id,
        "case_type": case.case_type,
        "category": case.category,
        "subcategory": case.subcategory,
        "status": case.status,
        "priority": case.priority,
        "sla_breached": case.sla_breached,
        "claimed_amount": _amount(case.claimed_amount),
        "currency": case.currency,
        "days_open": case.days_open,
    }


def _as_of(value: datetime) -> str:
    """Return the aware as_of as ISO 8601 UTC, whole seconds, with a Z."""
    utc = value.astimezone(timezone.utc).isoformat(timespec="seconds")
    return utc.replace("+00:00", "Z")


def _iso(value: date | None) -> str | None:
    """Return a date or a timestamp as ISO 8601, keeping None."""
    return None if value is None else value.isoformat()


def _amount(value: Decimal | None) -> str | None:
    """Round half-up to 2 decimals as a string, keeping None."""
    if value is None:
        return None
    return str(value.quantize(_CENTS, rounding=ROUND_HALF_UP))
```

`datetime` is a subclass of `date`, so `_iso` covers both.

- [ ] **Step 4: Run the tests**

Run: `$PY -m pytest tests/unit/get_session_context/test_session_context_presenter.py -q -p no:cacheprovider </dev/null`
Expected: all pass.

---

### Task 7: Dependency builder

**Files:**
- Create (copied): `gateway/tools/get_session_context/get_session_context_lambda/delivery/dependencies/dependencies_builder.py`
- Test: `tests/unit/get_session_context/test_delivery_wiring.py`

**Interfaces:**
- Consumes:
  - Task 1: `build_clock` in the `list_credit_cards` builder (copied here).
  - Task 2: settings, connectors, `DsqlRepository`, `FileQueryProvider`, fakes (`FakeConnector`, `make_any_section_row`, `QUERY_NAMES`, `CUSTOMER_ID`).
  - Task 4: `GetSessionContextUseCase` and `Section`.
  - Task 5: the five SQL files.
- Produces, in `get_session_context_lambda.delivery.dependencies.dependencies_builder`:
  - `QUERIES_ROOT`, `SQL_DIALECTS`
  - `build_settings(env)`, `build_dsql_settings(env)`, `build_clock(env) -> ClockSettings | None`
  - `build_connector(settings, env)`, `build_database_repository(engine, connector)`, `build_query_provider(engine)` (cached)
  - `build_get_session_context_use_case(env) -> GetSessionContextUseCase | None`

- [ ] **Step 1: Write the failing wiring tests**

`tests/unit/get_session_context/test_delivery_wiring.py`:

```python
"""Tests for the dependency wiring of the get_session_context tool."""

from datetime import datetime, timezone

import get_session_context_lambda.utils.connectors.dsql as dsql_module
import pytest
from get_session_context_lambda.application.ports.errors import (
    DataSourceConnectionError,
)
from get_session_context_lambda.application.use_cases.get_session_context import (
    GetSessionContextUseCase,
)
from get_session_context_lambda.delivery.dependencies import dependencies_builder
from get_session_context_lambda.delivery.dependencies.dependencies_builder import (
    QUERIES_ROOT,
    SQL_DIALECTS,
    build_clock,
    build_connector,
    build_database_repository,
    build_dsql_settings,
    build_get_session_context_use_case,
    build_query_provider,
    build_settings,
)
from get_session_context_lambda.delivery.settings import (
    ClockSettings,
    ConfigurationError,
    DatabaseEngine,
    DatabaseSettings,
    DsqlSettings,
)
from get_session_context_lambda.domain.entities.session_context import Section
from get_session_context_lambda.infrastructure.repositories.dsql_repository import (
    DsqlRepository,
)
from get_session_context_lambda.utils.connectors.dsql import DsqlConnector

from .fakes import CUSTOMER_ID, QUERY_NAMES, FakeConnector, make_any_section_row

pytestmark = pytest.mark.unit

ENDPOINT = "abc123.dsql.us-east-1.on.aws"
ENV = {"DSQL_CLUSTER_ENDPOINT": ENDPOINT, "AWS_REGION": "us-east-1"}
SETTINGS = DatabaseSettings(engine=DatabaseEngine.AURORA_DSQL, max_rows=25)
AS_OF = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
# What the SQL receives: the same instant as naive UTC.
AS_OF_SQL = datetime(2026, 3, 14, 12, 0)


def test_build_settings_reads_the_environment() -> None:
    assert build_settings(ENV) == SETTINGS


def test_build_dsql_settings_reads_the_environment() -> None:
    assert build_dsql_settings(ENV) == DsqlSettings(
        cluster_endpoint=ENDPOINT, region="us-east-1", db_user="ledgerlens_readonly"
    )


def test_build_clock_reads_as_of() -> None:
    assert build_clock({"AS_OF": "2026-03-14"}) == ClockSettings(
        as_of=datetime(2026, 3, 14, tzinfo=timezone.utc)
    )


def test_build_clock_without_as_of_uses_the_real_clock() -> None:
    assert build_clock({}) == ClockSettings(as_of=None)


def test_build_clock_with_a_bad_as_of_returns_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert build_clock({"AS_OF": "yesterday"}) is None
    assert "Invalid AS_OF for get_session_context" in caplog.text


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
    assert "DISTINCT ON" in provider.get("session_customer_profile")


def test_every_engine_has_a_dialect_folder_with_every_query() -> None:
    for engine in DatabaseEngine:
        for name in QUERY_NAMES:
            assert (QUERIES_ROOT / SQL_DIALECTS[engine] / f"{name}.sql").is_file()


def test_queries_root_is_this_tools_own_folder() -> None:
    assert QUERIES_ROOT.parent.name == "get_session_context_lambda"


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
    connector = FakeConnector([make_any_section_row()])
    use_fake_connector(monkeypatch, connector)

    use_case = build_get_session_context_use_case(ENV)
    assert isinstance(use_case, GetSessionContextUseCase)
    context = use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert context.customer.customer_id == CUSTOMER_ID
    assert context.unavailable == ()
    assert context.cards is not None and context.cards[0].card_last4 == "4821"
    queries = executed(connector)
    assert len(queries) == 5
    assert "FROM customers" in queries[0][0]
    assert queries[0][1] == {"customer_id": CUSTOMER_ID}
    assert "FROM complaints" in queries[-1][0]
    assert queries[-1][1] == {
        "customer_id": CUSTOMER_ID,
        "as_of": AS_OF_SQL,
        "limit": 6,
    }


def test_use_case_uses_max_rows_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector([make_any_section_row() for _ in range(4)])
    use_fake_connector(monkeypatch, connector)

    use_case = build_get_session_context_use_case({**ENV, "MAX_ROWS": "3"})
    assert use_case is not None
    context = use_case.execute(CUSTOMER_ID, as_of=AS_OF)

    assert context.cards is not None and len(context.cards) == 3
    assert context.open_cases is not None and len(context.open_cases) == 3
    assert context.truncated == tuple(Section)


def test_use_case_build_opens_the_connection_eagerly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector()
    use_fake_connector(monkeypatch, connector)

    build_get_session_context_use_case(ENV)

    assert len(connector.connections) == 1


def test_use_case_build_survives_a_failed_cold_start_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector(
        DataSourceConnectionError("no route to host"), [make_any_section_row()]
    )
    use_fake_connector(monkeypatch, connector)

    use_case = build_get_session_context_use_case(ENV)

    assert use_case is not None
    assert use_case.execute(CUSTOMER_ID, as_of=AS_OF).unavailable == ()


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
    assert build_get_session_context_use_case(env) is None
```

`FakeConnection` and `FakeCursor` come from the copied `fakes.py`. The repository opens one cursor per query, so `executed()` reads every cursor of the last connection. If the copied `FakeCursor` stores `executed` items in another shape, adapt only the `executed()` helper and note it in the ledger.

- [ ] **Step 2: Run them to see them fail**

Run: `$PY -m pytest tests/unit/get_session_context/test_delivery_wiring.py -q -p no:cacheprovider </dev/null`
Expected: a collection error, `ModuleNotFoundError: No module named 'get_session_context_lambda.delivery.dependencies.dependencies_builder'`.

- [ ] **Step 3: Copy the builder**

```bash
sed -e 's/list_credit_cards/get_session_context/g' \
    -e 's/ListCreditCardsUseCase/GetSessionContextUseCase/g' \
    gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/dependencies/dependencies_builder.py \
    > gateway/tools/get_session_context/get_session_context_lambda/delivery/dependencies/dependencies_builder.py
```

The two substitutions are the whole change:
- `list_credit_cards_lambda` imports become `get_session_context_lambda`, and the use-case module path `use_cases.list_credit_cards` becomes `use_cases.get_session_context`.
- `build_list_credit_cards_use_case` becomes `build_get_session_context_use_case`.
- The log lines become `"Invalid AS_OF for get_session_context"` and `"Invalid database configuration for get_session_context"`.
- The use case is built with the same keyword arguments (`database_repository`, `query_provider`, `max_rows`).

Check that nothing else differs:

```bash
diff <(sed -e 's/list_credit_cards/get_session_context/g' -e 's/ListCreditCardsUseCase/GetSessionContextUseCase/g' gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/dependencies/dependencies_builder.py) gateway/tools/get_session_context/get_session_context_lambda/delivery/dependencies/dependencies_builder.py
grep -n "ListCreditCards\|list_credit" gateway/tools/get_session_context/get_session_context_lambda/delivery/dependencies/dependencies_builder.py
```

Expected: both print nothing.

- [ ] **Step 4: Run the tests**

Run: `$PY -m pytest tests/unit/get_session_context/test_delivery_wiring.py -q -p no:cacheprovider </dev/null`
Expected: all pass.

---

### Task 8: Handler

**Files:**
- Create: `gateway/tools/get_session_context/get_session_context_lambda/delivery/handler.py` (shape copied from `list_credit_cards`)
- Test: `tests/unit/get_session_context/test_get_session_context_handler.py`

**Interfaces:**
- Consumes:
  - Task 3: `DomainError`, `DataSourceUnavailableError`, `SessionContextLookupError`, `CustomerNotFoundError`, `SessionContextDataIntegrityError`.
  - Task 4: `GetSessionContextUseCase.execute(customer_id, as_of)`.
  - Task 6: `present_session_context(context)`.
  - Task 7: `build_clock`, `build_get_session_context_use_case`, `build_database_repository`, `build_query_provider`.
- Produces: `get_session_context_lambda.delivery.handler` with `handler(event, context) -> dict[str, Any]`, the module globals `USE_CASE` and `CLOCK`, and `TOOL_NAME`, `UNEXPECTED_ERROR_MESSAGE`.

- [ ] **Step 1: Write the failing handler tests**

`tests/unit/get_session_context/test_get_session_context_handler.py`:

```python
"""Tests for the get_session_context Lambda handler."""

import importlib
import json
import logging
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from typing import Any

import psycopg
import pytest
from get_session_context_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryExecutionError,
)
from get_session_context_lambda.application.use_cases.get_session_context import (
    GetSessionContextUseCase,
)
from get_session_context_lambda.delivery.dependencies.dependencies_builder import (
    build_database_repository,
    build_query_provider,
)
from get_session_context_lambda.delivery.settings import ClockSettings, DatabaseEngine
from get_session_context_lambda.domain.errors import (
    CustomerNotFoundError,
    DataSourceUnavailableError,
    SessionContextDataIntegrityError,
    SessionContextLookupError,
)

from .fakes import (
    CUSTOMER_ID,
    QUERY_NAMES,
    FakeConnector,
    FakeQueryProvider,
    FakeSessionRepository,
    Outcome,
    make_any_section_row,
    make_profile_row,
    session_responses,
)

pytestmark = pytest.mark.unit

EVENT = {"customer_id": CUSTOMER_ID}
AS_OF = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
# What the SQL receives: the same instant as naive UTC.
AS_OF_SQL = datetime(2026, 3, 14, 12, 0)
INVALID_CUSTOMER_ID = (
    "Invalid value for 'customer_id': is required and must be a non-empty "
    "string. Ask the customer to confirm and retry."
)
OUTPUT_KEYS = [
    "as_of",
    "customer",
    "cards",
    "recent_transactions",
    "digital_signals",
    "open_cases",
    "truncated",
    "unavailable",
]


def make_context(
    tool_name: str = "get-session-context-target___get_session_context",
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
    import get_session_context_lambda.delivery.handler as handler_module

    return importlib.reload(handler_module)


def wire(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, Outcome] | None = None,
) -> FakeSessionRepository:
    """Point the handler at a use case over a fake repository and a fixed clock."""
    database_repository = FakeSessionRepository(
        session_responses() if responses is None else responses
    )
    use_case = GetSessionContextUseCase(
        database_repository=database_repository, query_provider=FakeQueryProvider()
    )
    monkeypatch.setattr(module, "USE_CASE", use_case)
    monkeypatch.setattr(module, "CLOCK", ClockSettings(as_of=AS_OF))
    return database_repository


def wire_connector(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, connector: Any
) -> None:
    """Point the handler at real adapters over a fake connector and a fixed clock."""
    use_case = GetSessionContextUseCase(
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


def test_success_returns_gateway_content_with_the_snapshot(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch)

    payload = body(module.handler(EVENT, make_context()))

    assert list(payload) == OUTPUT_KEYS
    assert payload["as_of"] == "2026-03-14T12:00:00Z"
    assert payload["customer"]["customer_id"] == CUSTOMER_ID
    assert payload["customer"]["city"] == "Bogotá"
    assert payload["cards"][0]["available_credit"] == "1750000.00"
    assert payload["recent_transactions"][0]["flags"] == [
        "declined",
        "above_usual_amount",
    ]
    assert payload["digital_signals"][0]["signal"] == "FAILED_ACTION"
    assert payload["open_cases"][0]["days_open"] == 3
    assert payload["truncated"] == []
    assert payload["unavailable"] == []


def test_success_over_real_adapters(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire_connector(module, monkeypatch, FakeConnector([make_any_section_row()]))

    payload = body(module.handler(EVENT, make_context()))

    assert payload["customer"]["customer_id"] == CUSTOMER_ID
    assert payload["unavailable"] == []


def test_bare_customer_id_and_as_of_reach_every_query(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_repository = wire(module, monkeypatch)

    module.handler({"customer_id": "  cli-itiecue8prh9 "}, make_context())

    assert database_repository.queries == list(QUERY_NAMES)
    for name, params in database_repository.calls:
        assert params["customer_id"] == CUSTOMER_ID, name
        if "as_of" in params:
            assert params["as_of"] == AS_OF_SQL, name


def test_unknown_event_keys_are_ignored(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_repository = wire(module, monkeypatch)

    response = module.handler({**EVENT, "as_of": "2020-01-01"}, make_context())

    assert body(response)["as_of"] == "2026-03-14T12:00:00Z"
    assert database_repository.queries == list(QUERY_NAMES)


def test_a_failed_section_comes_back_null_and_unavailable(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(
        module,
        monkeypatch,
        session_responses(
            session_recent_transactions=QueryExecutionError(
                "function percentile_cont is not supported"
            )
        ),
    )

    payload = body(module.handler(EVENT, make_context()))

    assert payload["recent_transactions"] is None
    assert payload["unavailable"] == ["recent_transactions"]
    assert payload["cards"] is not None
    assert payload["digital_signals"] is not None
    assert payload["open_cases"] is not None


def test_now_is_read_on_every_call(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_repository = wire(module, monkeypatch)
    times = iter(
        [
            datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc),
            datetime(2026, 3, 15, 8, 30, tzinfo=timezone.utc),
        ]
    )
    monkeypatch.setattr(module, "CLOCK", SimpleNamespace(now=lambda: next(times)))

    first = body(module.handler(EVENT, make_context()))
    second = body(module.handler(EVENT, make_context()))

    assert first["as_of"] == "2026-03-14T12:00:00Z"
    assert second["as_of"] == "2026-03-15T08:30:00Z"
    sent = [
        params["as_of"]
        for _name, params in database_repository.calls
        if "as_of" in params
    ]
    assert sent[0] == datetime(2026, 3, 14, 12, 0)
    assert sent[-1] == datetime(2026, 3, 15, 8, 30)


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
    database_repository = wire(module, monkeypatch)

    response = module.handler(event, make_context())

    assert response == {"error": INVALID_CUSTOMER_ID}
    assert database_repository.calls == []


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        (DataSourceConnectionError("down"), DataSourceUnavailableError.MESSAGE),
        (QueryExecutionError("boom"), SessionContextLookupError.MESSAGE),
        ([], CustomerNotFoundError.MESSAGE),
        (
            [make_profile_row(customer_id=None)],
            SessionContextDataIntegrityError.MESSAGE,
        ),
    ],
    ids=["unavailable", "lookup", "not-found", "integrity"],
)
def test_a_customer_section_failure_returns_its_message(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    outcome: Outcome,
    message: str,
) -> None:
    wire(module, monkeypatch, session_responses(session_customer_profile=outcome))

    assert module.handler(EVENT, make_context()) == {"error": message}


def test_query_failure_over_real_adapters_returns_the_lookup_message(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = psycopg.errors.UndefinedTable('relation "customers" does not exist')
    wire_connector(module, monkeypatch, FakeConnector(error))

    response = module.handler(EVENT, make_context())

    assert response == {"error": SessionContextLookupError.MESSAGE}


@pytest.mark.parametrize(
    "context",
    [
        make_context("other-target___text_analysis_tool"),
        make_context("list-credit-cards-target___list_credit_cards"),
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

    response = module.handler(EVENT, context)

    assert set(response) == {"error"}
    assert "get_session_context" in response["error"]
    assert database_repository.calls == []


def test_tool_name_without_a_target_prefix_is_accepted(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(module, monkeypatch)

    assert "content" in module.handler(EVENT, make_context("get_session_context"))


def test_unexpected_exception_returns_a_generic_message_without_internals(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("password=hunter2 host=db.internal")

    monkeypatch.setattr(module, "USE_CASE", SimpleNamespace(execute=explode))

    response = module.handler(EVENT, make_context())

    assert response == {"error": module.UNEXPECTED_ERROR_MESSAGE}
    assert module.UNEXPECTED_ERROR_MESSAGE == (
        "Unexpected internal error loading the customer's context. "
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
    wire_connector(module, monkeypatch, FakeConnector(DataSourceConnectionError("down")))

    response = module.handler(EVENT, make_context())

    assert response == {"error": DataSourceUnavailableError.MESSAGE}


def test_success_log_names_the_lists_but_no_customer_data(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    wire(
        module,
        monkeypatch,
        session_responses(session_open_cases=QueryExecutionError("boom")),
    )
    caplog.set_level(logging.INFO)

    module.handler(EVENT, make_context())

    assert (
        "get_session_context returned context "
        "(unavailable=['open_cases'], truncated=[])"
    ) in caplog.text
    assert "Ana" not in caplog.text
    assert "Bogot" not in caplog.text
```

- [ ] **Step 2: Run them to see them fail**

Run: `$PY -m pytest tests/unit/get_session_context/test_get_session_context_handler.py -q -p no:cacheprovider </dev/null`
Expected: every test errors in the `module` fixture with `ModuleNotFoundError: No module named 'get_session_context_lambda.delivery.handler'`.

- [ ] **Step 3: Write the handler**

`gateway/tools/get_session_context/get_session_context_lambda/delivery/handler.py`:

```python
"""Lambda handler for the ``get_session_context`` Gateway tool.

Handler string: ``get_session_context_lambda/delivery/handler.handler``.

Input: the tool arguments as the event (see
``gateway/tools/get_session_context/tool_spec.json``); the tool name arrives in
``context.client_context.custom["bedrockAgentCoreToolName"]`` with a
``<target>___`` prefix, as in ``gateway/tools/sample_tool``. ``customer_id`` is
passed to the use case bare, exactly as it came; the use case cleans it.

Output: ``{"content": [{"type": "text", "text": <JSON>}]}`` on success, or
``{"error": <agent-facing message>}``. Only a customer-section failure is an
error; any other failed section comes back null and is named in
``unavailable``. Raw exception text is never returned: it could leak SQL, hosts
or driver details to the model.

The use case and its whole graph (settings, connector, connection, adapters) are
built once, when the module loads, by dependencies_builder; a warm container
reuses them. The handler builds nothing itself.

AS_OF (optional) is read once into CLOCK; "now" is CLOCK.now() on every call,
so a warm container never freezes the real clock. An invalid AS_OF answers every
request with DataSourceUnavailableError's message.

TODO(ledgerlens): R1 - no CDK yet: no PythonFunction, Gateway target, env vars
  (DB_ENGINE, DSQL_CLUSTER_ENDPOINT, DSQL_DB_USER, AS_OF) or dsql:DbConnect grant
  on the cluster ARN (dsql:DbConnectAdmin only if DSQL_DB_USER=admin). The tool
  can't be deployed or called by the agent until the CDK spec lands.
TODO(ledgerlens): R5 - customer_id is trusted from the tool input. Authorization
  depends on a Cedar policy matching it to the token's customer_id claim; neither
  the policy nor the claim exists yet (product design sections 5 and 10).
"""

import json
import logging
import os
from collections.abc import Mapping
from typing import Any, Final

from get_session_context_lambda.delivery.dependencies.dependencies_builder import (
    build_clock,
    build_get_session_context_use_case,
)
from get_session_context_lambda.delivery.presenters.session_context import (
    present_session_context,
)
from get_session_context_lambda.domain.errors import (
    DataSourceUnavailableError,
    DomainError,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TOOL_NAME: Final = "get_session_context"
_TOOL_NAME_DELIMITER: Final = "___"
UNEXPECTED_ERROR_MESSAGE: Final = (
    "Unexpected internal error loading the customer's context. "
    "Offer a hand-off to a human agent."
)
_WRONG_TOOL_MESSAGE: Final = (
    f"This function only serves the '{TOOL_NAME}' tool. "
    "Don't retry; offer a hand-off to a human agent."
)


USE_CASE = build_get_session_context_use_case(os.environ)
CLOCK = build_clock(os.environ)


def handler(event: object, context: object) -> dict[str, Any]:
    """Load the customer's session snapshot for the agent.

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
        body = present_session_context(
            USE_CASE.execute(_customer_id(event), as_of=CLOCK.now())
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
        "%s returned context (unavailable=%s, truncated=%s)",
        TOOL_NAME,
        body["unavailable"],
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

Everything below the globals is the `list_credit_cards` handler with only the `try` body and the log line changed (spec §6.3). Check it:

```bash
diff gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/handler.py gateway/tools/get_session_context/get_session_context_lambda/delivery/handler.py
```

Expected: differences only in the module docstring, the three imports, `TOOL_NAME`, `UNEXPECTED_ERROR_MESSAGE`, the `USE_CASE` builder name, the `try` body, the handler docstring's first line and the success log line.

- [ ] **Step 4: Run the tests**

Run: `$PY -m pytest tests/unit/get_session_context/test_get_session_context_handler.py -q -p no:cacheprovider </dev/null`
Expected: all pass.

- [ ] **Step 5: Run the whole tool suite and lint**

```bash
$PY -m pytest tests/unit/get_session_context -q -p no:cacheprovider </dev/null 2>&1 | tail -2
$PY -m ruff format gateway/tools/get_session_context tests/unit/get_session_context </dev/null
$PY -m ruff check gateway/tools/get_session_context tests/unit/get_session_context </dev/null
```

Expected: all pass, 0 failed. `ruff format` may rewrap a few long lines in the test files; `ruff check` is clean. Re-run the pytest line if `ruff format` changed anything.

---

### Task 9: Product design doc, full suite and handoff

**Files:**
- Modify: `docs/LEDGERLENS_PRODUCT_DESIGN.md` (CRLF): the §7 `:as_of` bullet, §7.1, and the §17 rows Q1 and Q7.
- Temporary: `<scratchpad>/edit_product_design.py`, deleted at the end of this task.

**Interfaces:**
- Consumes: Task 5's `tool_spec.json`, and the spec's §4.5 output example.
- Produces: no code.

The design doc uses CRLF line endings. Never edit it with the Edit or Write tool, which can turn them into LF. The script below reads the bytes, works on `\n` text, asserts every old block is found exactly once, and writes CRLF back.

- [ ] **Step 1: Write the edit script in the scratchpad**

Write `edit_product_design.py` in the session scratchpad directory (not in the repo):

```python
"""One-off: update docs/LEDGERLENS_PRODUCT_DESIGN.md for get_session_context."""

import json
import re
from pathlib import Path

REPO = Path(r"C:\GITHUB REPOS\ledgerlens-bank-assistant")
DOC = REPO / "docs" / "LEDGERLENS_PRODUCT_DESIGN.md"
SPEC = (
    REPO / "docs" / "superpowers" / "specs"
    / "2026-10-01-get-session-context-lambda-design.md"
)
TOOL_SPEC = REPO / "gateway" / "tools" / "get_session_context" / "tool_spec.json"

raw = DOC.read_bytes()
assert b"\r\n" in raw
text = raw.decode("utf-8").replace("\r\n", "\n")

# --- §7 conventions: the :as_of bullet ---------------------------------------
OLD_AS_OF = (
    "- **Parameters:** `:as_of` is `now()` in production. "
    "For the historical dataset it's a fixed timestamp inside the data.\n"
)
NEW_AS_OF = (
    "- **Parameters:** `:as_of` comes from the optional `AS_OF` env var of each "
    "tool Lambda; unset means the real UTC time (production). Demos set it to a "
    "timestamp inside the dataset.\n"
)
assert text.count(OLD_AS_OF) == 1
text = text.replace(OLD_AS_OF, NEW_AS_OF)

# --- §7.1: from its heading up to §7.2 ---------------------------------------
START = "### 7.1 `get_session_context` (A1, bootstrap)\n"
END = "### 7.2 `classify_call_type` (A1, bootstrap)\n"
assert text.count(START) == 1 and text.count(END) == 1
start, end = text.index(START), text.index(END)

tool_spec = json.loads(TOOL_SPEC.read_text(encoding="utf-8"))[0]
spec_text = SPEC.read_text(encoding="utf-8")
output_shape = re.search(
    r"### 4\.5 .*?```json\n(.*?)```", spec_text, re.DOTALL
).group(1)

NEW_7_1 = (
    START
    + "\n**Purpose:** a single compact snapshot of everything relevant at session "
    "start.\n\n"
    "Spec: [2026-10-01-get-session-context-lambda-design.md]"
    "(superpowers/specs/2026-10-01-get-session-context-lambda-design.md).\n\n"
    "**tool_spec.json**\n```json\n"
    + json.dumps(tool_spec, indent=2, ensure_ascii=False)
    + "\n```\n\n"
    "**Output (shape)**\n"
    "Amounts are 2-decimal strings. An empty list means there is nothing; a "
    "section that couldn't be loaded is `null` and is named in `unavailable`. "
    "`truncated` names the lists that had more rows than their cap (25, open "
    "cases 5).\n```json\n"
    + output_shape
    + "```\n\n"
    "**Queries (run one after another inside the Lambda)**\n\n"
    "Each query lives in "
    "`gateway/tools/get_session_context/get_session_context_lambda/queries/"
    "postgresql/` and asks for one row more than its cap, so the Lambda can "
    "tell whether the list was truncated. Only a failure of the profile query "
    "fails the call; any other failed query makes its section `null`.\n\n"
    "*Q1: profile, then credit cards (two queries).* `session_customer_profile` "
    "selects `customer_id`, `first_name`, `country`, `city` and "
    "`customer_status` only; sensitive fields (document, date of birth, gender, "
    "contact details, credit score, income) are deliberately not selected. "
    "`session_credit_cards` is the `list_credit_cards` query: credit cards "
    "(`product_type = 'Tarjeta Crédito'`) in every status, active first.\n\n"
    "*Q2: recent transactions with flags.* Credit-card transactions from the 72 "
    "hours up to `:as_of`, read through `tx_dedup` (section 8.1).\n"
    "```sql\n"
    "(r.transaction_status = 'Declined')               AS is_declined,\n"
    "(r.transaction_country <> h.country)              AS is_foreign,\n"
    "(r.amount_usd > COALESCE(b.p95_usd, 'Infinity'))  AS is_above_usual_amount,\n"
    "(r.merchant_name IS NOT NULL\n"
    " AND NOT EXISTS (SELECT 1 FROM hist AS x\n"
    "                 WHERE x.merchant_name = r.merchant_name)) AS is_new_merchant\n"
    "```\n"
    "`Pending` and `Reversed` aren't declines; the model sees them in "
    "`transaction_status`. The baseline is the 95th percentile of approved USD "
    "amounts in the 90 days before the window.\n\n"
    "*Q3: app/web activity signals (last 24 hours).* The first matching rule "
    "wins; events with no signal are filtered out in SQL.\n"
    "```sql\n"
    "CASE\n"
    "  WHEN e.event_type = 'Error'                                             "
    "THEN 'FAILED_ACTION'\n"
    "  WHEN e.page_title = 'Mis Movimientos' OR e.action = 'view_transactions' "
    "THEN 'REVIEWING_TRANSACTIONS'\n"
    "  WHEN e.page_title = 'Tarjeta de Crédito'                                "
    "THEN 'VIEWING_CREDIT_CARD'\n"
    "  WHEN e.page_title = 'Ayuda' OR e.action = 'view_help'                   "
    "THEN 'SEEKING_HELP'\n"
    "END AS signal\n"
    "```\n\n"
    "*Q4: open cases.* Cases open at `:as_of`: created on or before it and not "
    "closed by then, SLA breaches first.\n"
    "```sql\n"
    "WHERE k.customer_id = :customer_id\n"
    "  AND k.creation_date <= :as_of\n"
    "  AND (k.closing_date IS NULL OR k.closing_date > :as_of)\n"
    "-- days_open = :as_of::date - creation_date::date\n"
    "```\n"
    "`status` is returned as stored now, so on a past `AS_OF` it can read "
    "`Closed` (accepted for demos).\n\n"
    "---\n\n"
)
text = text[:start] + NEW_7_1 + text[end:]

# --- §17: Q1 and Q7 ----------------------------------------------------------
OLD_Q1 = (
    "| Q1 | Actual values for `transaction_status`, `response_code`, "
    "`product_status`, complaint `status`/`category`/`subcategory` and "
    "`page_title` | Every WHERE clause and the reason taxonomy |\n"
)
NEW_Q1 = (
    "| Q1 | **Partly answered 2026-10-01.** Confirmed by the user: "
    "`transaction_status` is `Approved`, `Declined`, `Pending` or `Reversed`; "
    "`page_title` has 12 values (`Inicio`, `Iniciar Sesión`, `Cerrar Sesión`, "
    "`Mis Movimientos`, `Tarjeta de Crédito`, `Ayuda`, `Préstamos`, "
    "`Cuenta de Ahorro`, `Pagar Servicios`, `Transferir`, `Mis Cuentas`, "
    "`Productos`); `event_type` (7 values, including `Error`), `action` "
    "(10, including `view_transactions` and `view_help`) and `event_category` "
    "(4) are confirmed too. Still open: `response_code`, `product_status`, "
    "complaint `status`/`category`/`subcategory`. | Every WHERE clause and the "
    "reason taxonomy |\n"
)
OLD_Q7 = (
    "| Q7 | Dataset time range, to choose `:as_of` for demos | "
    "All the \"recent\" windows |\n"
)
NEW_Q7 = (
    "| Q7 | **Answered 2026-10-01:** every tool Lambda reads an optional `AS_OF` "
    "env var as \"now\"; demos set it to a timestamp inside the dataset's time "
    "range. | All the \"recent\" windows |\n"
)
for old, new in ((OLD_Q1, NEW_Q1), (OLD_Q7, NEW_Q7)):
    assert text.count(old) == 1, old
    text = text.replace(old, new)

DOC.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
print("updated", DOC)
```

The script writes the accented literals (`é`, `ó`) as plain UTF-8. Make sure the editor saves the script as UTF-8.

- [ ] **Step 2: Run the script and check the result**

```bash
$PY "<scratchpad>/edit_product_design.py" </dev/null
git diff --stat docs/LEDGERLENS_PRODUCT_DESIGN.md
grep -c $'\r$' docs/LEDGERLENS_PRODUCT_DESIGN.md
wc -l < docs/LEDGERLENS_PRODUCT_DESIGN.md
grep -n "Queries (run one after another\|Q1 (section 7.1)\|Partly answered 2026-10-01\|AS_OF\` env var" docs/LEDGERLENS_PRODUCT_DESIGN.md
grep -n "ILIKE\|DISPUTE_INTEREST\|run in parallel" docs/LEDGERLENS_PRODUCT_DESIGN.md
```

Expected:
- The script prints `updated ...`.
- `git diff --stat` shows only `docs/LEDGERLENS_PRODUCT_DESIGN.md` changed.
- The CRLF count equals the line count: every line still ends in CRLF.
- The first grep finds the new §7.1 queries heading, §7.3's unchanged `Q1 (section 7.1)` reference, the Q1 row and the `:as_of` bullet / Q7 row.
- The second grep prints no line from §7.1. If it prints a line, check that it belongs to another section (§7.1's old Q3 used `ILIKE` and `DISPUTE_INTEREST`).

Then read the new §7.1 with `git diff docs/LEDGERLENS_PRODUCT_DESIGN.md` and check that the JSON blocks render as JSON.

- [ ] **Step 3: Delete the script**

```bash
rm "<scratchpad>/edit_product_design.py"
```

- [ ] **Step 4: Run the full suite**

Run: `$PY -m pytest tests/unit -q -p no:cacheprovider </dev/null 2>&1 | tail -3`
Expected: all pass, 0 failed, more than the 515 baseline.

- [ ] **Step 5: Check isolation and lint**

```bash
grep -rn "list_credit_cards\|list_card_transactions" gateway/tools/get_session_context tests/unit/get_session_context
grep -rln "__pycache__" gateway/tools/get_session_context || true
$PY -m ruff format --check gateway/tools tests/unit </dev/null
$PY -m ruff check gateway/tools tests/unit </dev/null
```

Expected:
- The first grep prints only the comment in `session_credit_cards.sql` ("A copy of list_credit_cards.sql from the list_credit_cards tool") and, in `test_get_session_context_handler.py`, the wrong-tool-name context `list-credit-cards-target___list_credit_cards`. No import names another tool.
- Both ruff commands are clean.

- [ ] **Step 6: Check the working tree and hand off**

```bash
git status --short
```

Expected (order may differ):

```text
 M docs/LEDGERLENS_PRODUCT_DESIGN.md
 M gateway/tools/list_card_transactions/list_card_transactions_lambda/delivery/dependencies/dependencies_builder.py
 M gateway/tools/list_card_transactions/list_card_transactions_lambda/delivery/handler.py
 M gateway/tools/list_card_transactions/list_card_transactions_lambda/delivery/settings.py
 M gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/dependencies/dependencies_builder.py
 M gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/handler.py
 M gateway/tools/list_credit_cards/list_credit_cards_lambda/delivery/settings.py
 M infra-cdk/config.yaml
 M tests/unit/list_card_transactions/test_delivery_wiring.py
 M tests/unit/list_card_transactions/test_list_card_transactions_handler.py
 M tests/unit/list_card_transactions/test_settings.py
 M tests/unit/list_credit_cards/test_delivery_wiring.py
 M tests/unit/list_credit_cards/test_list_credit_cards_handler.py
 M tests/unit/list_credit_cards/test_settings.py
?? docs/superpowers/plans/2026-10-01-get-session-context-lambda.md
?? docs/superpowers/specs/2026-10-01-get-session-context-lambda-design.md
?? gateway/tools/get_session_context/
?? tests/unit/get_session_context/
```

`infra-cdk/config.yaml` was already modified before this plan and must never be staged.

Stop here. Don't run `git add` or `git commit`. Report the suite result and the file list to the user, and ask how they want the work committed.
