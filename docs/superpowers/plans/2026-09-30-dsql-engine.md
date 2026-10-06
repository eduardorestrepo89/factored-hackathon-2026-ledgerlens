# Aurora DSQL Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Aurora DSQL the only database engine of the `list_card_transactions` tool. Remove Aurora PostgreSQL and keep the hexagonal design and `DB_ENGINE`.

**Architecture:**
- `PsycopgConnector` changes from a Protocol to an abstract base class. It owns the cached-connection lifecycle: lazy open, reopen when closed or older than `max_age`, reset, and wrapping of open failures. `DsqlConnector` only implements `_open()`, which makes a fresh IAM token and calls `psycopg.connect`.
- `PostgreSQLRepository` becomes `DsqlRepository`. It maps DSQL limit errors to the renamed port error `QueryLimitExceededError`.
- Settings split into `DatabaseSettings` (engine and max rows) and `DsqlSettings` (endpoint, region and user).
- The builder maps the `DatabaseEngine` enum to the existing `queries/postgresql/` folder through `SQL_DIALECTS`.

**Tech Stack:** Python (must run on 3.10 locally and 3.13 in Lambda), psycopg 3 (`psycopg[binary]`), boto3 `dsql` client (≥ 1.35.74), pytest, ruff 0.14.1.

**Spec:** [`docs/superpowers/specs/2026-09-30-dsql-engine-design.md`](../specs/2026-09-30-dsql-engine-design.md). Read it before starting. The parent spec, [`2026-09-29-list-card-transactions-lambda-design.md`](../specs/2026-09-29-list-card-transactions-lambda-design.md), already describes the DSQL design.

### Decisions this plan adds to the spec
- **`DsqlConnector` takes an extra `clock` argument** (default `time.monotonic`) and passes it to the base class. Tests can then check the 55-minute recycle through behaviour instead of private attributes.
- **R13 is resolved by pinning `boto3>=1.35.74,<2` in `requirements.txt`.**
  - The boto3 `dsql` client and both `generate_db_connect_*auth_token` methods first appear in boto3/botocore **1.35.74** (2024-12-03). This was verified against the wheels: botocore 1.35.73 has no `botocore/data/dsql/`.
  - The pin makes the asset bundle a boto3 that is known to work, whatever the runtime ships.
- **`DSQL_CLUSTER_ENDPOINT` also rejects a `/`** (a trailing slash or a path), alongside a scheme and a port. All three get one message: "must be a bare host name".
- **`build_query_provider` raises `ConfigurationError`** for an engine that has no `SQL_DIALECTS` entry, instead of raising `KeyError`.
- **`FakeClock` goes in `ledgerlens_fakes.py`,** because the base-connector tests and the DSQL connector tests both use it.

## Global Constraints

- Code must run on **Python 3.10**: no `datetime.UTC`, no `typing.Self`, no `StrEnum` (use `class X(str, Enum)`), no `except*`. Lambda will run 3.13.
- Ruff: line length 88, rules `E,F,W,I,N,UP,S,B,A,C4,T20` (from `pyproject.toml`). Every task ends with `ruff format` and then `ruff check --fix` on the files it touched.
- Full type hints on every function (`disallow_untyped_defs` style). Every module, class and public function has a docstring.
- Layer rule: nothing under `ledgerlens/domain` or `ledgerlens/application` imports `psycopg`, `boto3`, `ledgerlens.infrastructure`, `ledgerlens.utils` or `ledgerlens.delivery`.
- Agent-facing messages and exception messages never contain exception text, SQL, hostnames, tokens or driver details.
- Use specific names: `database_repository`, `query_provider`, `DsqlRepository`, `DsqlConnector`, `DsqlSettings`. Never generic `repository` or `queries`.
- DSQL facts the code relies on:
  - dbname `postgres`, port `5432`, TLS required.
  - No `statement_timeout` or `default_transaction_read_only`; a session can only set an allowlist of parameters, which includes `client_encoding`.
  - Connections are closed at 60 min.
  - Token methods: `generate_db_connect_auth_token(Hostname, Region)` and `generate_db_connect_admin_auth_token(Hostname, Region)`.
- psycopg classes SQLSTATE 53200 (`OutOfMemory`), 54000 (`ProgramLimitExceeded`) and 57014 (`QueryCanceled`) as `psycopg.OperationalError` subclasses. Catch them **before** `OperationalError`.
- Risks are left as `TODO(ledgerlens): R<n> - ...` comments exactly where the spec's §8 table says.
- Tests live in `tests/unit/ledgerlens_tools/`. Each module starts with `pytestmark = pytest.mark.unit`. No test touches a database, the network or AWS.
- Git:
  - `git add` or `git mv` or `git rm` only the files named in the task.
  - **Never** stage `infra-cdk/config.yaml` (it contains a personal email), `docs/architecture-diagram/FAST-architecture.drawio`, `frontend/public/aws-exports.json` or `frontend/.env`.
  - Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  - Don't push.
- No AWS deploys and no CDK changes (out of scope, R1).

## Review Focus

1. **`DSQL_CLUSTER_ENDPOINT` pasted from the console as a URL or with a port** (`https://abc.dsql.us-east-1.on.aws`, `abc...on.aws:5432`, trailing `/`, surrounding spaces). Spaces are trimmed; the rest must fail at cold start with a `ConfigurationError` that names the variable. It must never surface later as a confusing connect failure. Pinned in Task 5 (`test_settings.py`).
2. **A warm container keeps a connection past DSQL's 60-minute cut-off.** The connection must be recycled at 55 minutes, before the query, with a fresh token, so the customer never sees "temporarily unavailable". Pinned in Task 2 (base, fake clock) and Task 4 (`DsqlConnector`, real `MAX_AGE`).
3. **A query breaks a DSQL limit** (128 MiB → 53200, 300 s → 54000). The agent must get `SearchTooBroadError` ("narrower date range…"), not "temporarily unavailable", and the query must not be retried or the connection reset. Pinned in Task 3.
4. **Token generation fails:**
   - the Lambda role has no credentials;
   - the runtime boto3 is too old to know the `dsql` client (`UnknownServiceError` at client creation);
   - an expired or denied token is rejected at connect.

   Each must come out as `DataSourceConnectionError` (so "temporarily unavailable"). The message must contain no host or token, and the next request must try again rather than stay poisoned. Pinned in Task 2 and Task 4.
5. **Cold start with incomplete config** (no `AWS_REGION`, no endpoint, `DB_ENGINE=postgresql` left over from the old setup). The handler must still import, and every request gets the "unavailable" message. Pinned in Task 5 (wiring parametrization and the handler fixture).

---

All commands run from the repo root, `C:\GITHUB REPOS\ledgerlens-bank-assistant`, in **Git Bash**. Use the Anaconda interpreter, because the default `python` (3.13) has no pytest:

```bash
PY=/c/ProgramData/anaconda3/python
```

Full suite: `$PY -m pytest tests/unit/ledgerlens_tools -q`. Before Task 1 it reports **198 passed**.

Lint for a task (always `format` first, so E501 only reports lines the formatter can't wrap):

```bash
$PY -m ruff format gateway/tools/ledgerlens_tools tests/unit/ledgerlens_tools && $PY -m ruff check --fix gateway/tools/ledgerlens_tools tests/unit/ledgerlens_tools
```

Paths below are shortened as follows:
- `L/` is `gateway/tools/ledgerlens_tools/ledgerlens/`
- `T/` is `tests/unit/ledgerlens_tools/`

Use the full paths in commands.

---

### Task 1: Rename `QueryTimeoutError` to `QueryLimitExceededError` and reword `SearchTooBroadError`

Without a `statement_timeout`, "timeout" no longer describes the error: it now covers DSQL's memory and transaction-age limits too.

**Files:**
- Modify: `L/application/ports/errors.py:17-18`
- Modify: `L/application/ports/database_repository.py:30`
- Modify: `L/application/use_cases/list_card_transactions.py:12,69,78`
- Modify: `L/domain/errors.py:60-66`
- Modify: `L/infrastructure/repositories/postgresql_repository.py:13,41,49` (temporary; Task 3 renames this file)
- Test: `T/test_errors.py`, `T/test_list_card_transactions_use_case.py`, `T/test_postgresql_repository.py`

**Interfaces:**
- Produces: `ledgerlens.application.ports.errors.QueryLimitExceededError(DataAccessError)`. `QueryTimeoutError` no longer exists.
- Produces: `SearchTooBroadError.MESSAGE == "The transaction search was too broad for the database. Retry with a narrower date range or add a card or merchant filter."`

- [ ] **Step 1: Update the tests**

In `T/test_errors.py`:
- Replace `QueryTimeoutError,` with `QueryLimitExceededError,` in the import from `ledgerlens.application.ports.errors`. The names in that import must stay alphabetical: `DataAccessError, DataSourceConnectionError, QueryExecutionError, QueryLimitExceededError, QueryNotFoundError`.
- In the `test_port_errors_share_a_base_class` parametrization, replace `QueryTimeoutError,` with `QueryLimitExceededError,`.
- Replace the `SearchTooBroadError` case with:

```python
        (
            SearchTooBroadError,
            "The transaction search was too broad for the database. Retry with a "
            "narrower date range or add a card or merchant filter.",
        ),
```

In `T/test_list_card_transactions_use_case.py`:
- Replace `QueryTimeoutError,` with `QueryLimitExceededError,` in the import, keeping it alphabetical.
- Replace the parametrize case:

```python
        (
            QueryLimitExceededError("query exceeded the 128 MiB memory limit"),
            SearchTooBroadError,
        ),
```

In `T/test_postgresql_repository.py`:
- Replace `QueryTimeoutError,` with `QueryLimitExceededError,` in the import.
- Change `pytest.raises(QueryTimeoutError)` to `pytest.raises(QueryLimitExceededError)`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest tests/unit/ledgerlens_tools/test_errors.py tests/unit/ledgerlens_tools/test_list_card_transactions_use_case.py tests/unit/ledgerlens_tools/test_postgresql_repository.py -q`
Expected: collection errors, `ImportError: cannot import name 'QueryLimitExceededError'`.

- [ ] **Step 3: Rename the port error**

In `L/application/ports/errors.py`, replace lines 17-18 with:

```python
class QueryLimitExceededError(DataAccessError):
    """The query exceeded a database time or resource limit."""
```

In `L/application/ports/database_repository.py`, replace the `QueryTimeoutError` line of the `Raises:` block with:

```python
            QueryLimitExceededError: The query exceeded a database time or resource
                limit.
```

- [ ] **Step 4: Update the use case**

In `L/application/use_cases/list_card_transactions.py`:
- In the import from `ledgerlens.application.ports.errors`, replace `QueryTimeoutError,` with `QueryLimitExceededError,`.
- Replace the docstring line `SearchTooBroadError: The query hit the statement timeout.` with:

```python
            SearchTooBroadError: The query exceeded a database time or resource
                limit.
```

- Replace `except QueryTimeoutError as exc:` with `except QueryLimitExceededError as exc:`.

- [ ] **Step 5: Reword the domain error**

In `L/domain/errors.py`, replace the `SearchTooBroadError` class with:

```python
class SearchTooBroadError(_FixedMessageError):
    """The query exceeded a database limit; a narrower search may succeed."""

    MESSAGE: ClassVar[str] = (
        "The transaction search was too broad for the database. Retry with a "
        "narrower date range or add a card or merchant filter."
    )
```

- [ ] **Step 6: Keep the old repository compiling until Task 3**

In `L/infrastructure/repositories/postgresql_repository.py`:
- Replace `QueryTimeoutError,` with `QueryLimitExceededError,` in the import, keeping it alphabetical: `DataSourceConnectionError, QueryExecutionError, QueryLimitExceededError`.
- Replace the docstring line `QueryTimeoutError: The statement timeout cancelled the query.` with `QueryLimitExceededError: The server cancelled the query.`
- Replace `raise QueryTimeoutError("Statement timeout exceeded") from exc` with `raise QueryLimitExceededError("The server cancelled the query") from exc`.

- [ ] **Step 7: Check that no reference is left**

Run: `grep -rn "QueryTimeoutError\|took too long" gateway/tools/ledgerlens_tools tests/unit/ledgerlens_tools --include=*.py`
Expected: no output.

- [ ] **Step 8: Lint and run the full suite**

Run the lint command, then `$PY -m pytest tests/unit/ledgerlens_tools -q`.
Expected: 198 passed.

- [ ] **Step 9: Commit**

```bash
git add gateway/tools/ledgerlens_tools/ledgerlens/application/ports/errors.py \
  gateway/tools/ledgerlens_tools/ledgerlens/application/ports/database_repository.py \
  gateway/tools/ledgerlens_tools/ledgerlens/application/use_cases/list_card_transactions.py \
  gateway/tools/ledgerlens_tools/ledgerlens/domain/errors.py \
  gateway/tools/ledgerlens_tools/ledgerlens/infrastructure/repositories/postgresql_repository.py \
  tests/unit/ledgerlens_tools/test_errors.py \
  tests/unit/ledgerlens_tools/test_list_card_transactions_use_case.py \
  tests/unit/ledgerlens_tools/test_postgresql_repository.py
git commit -F - <<'EOF'
refactor(tools): rename QueryTimeoutError to QueryLimitExceededError

Aurora DSQL has no statement_timeout; the error now covers any database
time or resource limit, and SearchTooBroadError's message says so.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 2: `PsycopgConnector` abstract base class owns the connection lifecycle

**Files:**
- Modify (rewrite): `L/utils/connectors/base.py`
- Modify (rewrite): `L/utils/connectors/aurora_postgresql.py` (temporary; deleted in Task 5)
- Modify: `T/ledgerlens_fakes.py` (`FakeConnector` rewrite, new `FakeClock`)
- Create: `T/test_psycopg_connector.py`
- Modify: `T/test_postgresql_repository.py:86-93`
- Modify: `T/test_aurora_postgresql_connector.py:80-86`

**Interfaces:**
- Produces:

```python
class PsycopgConnector(ABC):
    def __init__(self, max_age: timedelta | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None: ...
    def connection(self) -> psycopg.Connection[Any]: ...   # raises DataSourceConnectionError
    def reset(self) -> None: ...
    @abstractmethod
    def _open(self) -> psycopg.Connection[Any]: ...
```

- Produces (fakes):
  - `FakeConnector(*outcomes, max_age=None, clock=time.monotonic)` keeps the attributes `.connections: list[FakeConnection]` and `.reset_calls: int`.
  - `FakeClock(start=1000.0)` is callable, has `.now` and `.advance(delta: timedelta)`.

- [ ] **Step 1: Rewrite `FakeConnector` and add `FakeClock` in `T/ledgerlens_fakes.py`**

Replace the imports at the top with:

```python
"""Test doubles and builders shared by the LedgerLens tool tests."""

import time
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
```

(The `ledgerlens` imports below them stay unchanged.)

Replace the whole `FakeConnector` class (from `class FakeConnector(PsycopgConnector):` to the end of the file) with:

```python
class FakeConnector(PsycopgConnector):
    """PsycopgConnector double whose _open() serves the next queued outcome.

    The base class caches the connection, so the next outcome is only used after
    a reset, a closed connection or max_age. The last outcome repeats. A
    DataSourceConnectionError outcome is raised by _open() (connection() wraps
    it); any other exception is raised by cursor.execute().
    """

    def __init__(
        self,
        *outcomes: Outcome,
        max_age: timedelta | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Queue the outcomes; with none, every query returns no rows."""
        super().__init__(max_age=max_age, clock=clock)
        self._outcomes: list[Outcome] = list(outcomes) or [[]]
        self.connections: list[FakeConnection] = []
        self.reset_calls = 0

    def reset(self) -> None:
        """Count the reset, then let the base class close the connection."""
        self.reset_calls += 1
        super().reset()

    def _open(self) -> Any:
        """Return a connection double for the next outcome."""
        outcome = (
            self._outcomes.pop(0) if len(self._outcomes) > 1 else self._outcomes[0]
        )
        if isinstance(outcome, DataSourceConnectionError):
            raise outcome
        connection = FakeConnection(outcome)
        self.connections.append(connection)
        return connection


class FakeClock:
    """Monotonic clock double that only moves when told to."""

    def __init__(self, start: float = 1000.0) -> None:
        """Start at ``start`` seconds."""
        self.now = start

    def __call__(self) -> float:
        """Return the current time in seconds."""
        return self.now

    def advance(self, delta: timedelta) -> None:
        """Move the clock forward by ``delta``."""
        self.now += delta.total_seconds()
```

- [ ] **Step 2: Write `T/test_psycopg_connector.py`**

```python
"""Tests for the PsycopgConnector base: caching, recycling, reset, failures."""

from datetime import timedelta
from typing import Any

import psycopg
import pytest
from ledgerlens.application.ports.errors import DataSourceConnectionError
from ledgerlens.utils.connectors.base import PsycopgConnector
from ledgerlens_fakes import FakeClock, FakeConnector

pytestmark = pytest.mark.unit

MAX_AGE = timedelta(minutes=55)


class FailingConnector(PsycopgConnector):
    """Connector whose _open() always raises ``failure``."""

    def __init__(self, failure: Exception) -> None:
        """Raise ``failure`` on every open."""
        super().__init__()
        self.failure = failure

    def _open(self) -> Any:
        """Fail to open."""
        raise self.failure


def test_base_class_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        PsycopgConnector()  # type: ignore[abstract]


def test_opens_lazily_and_reuses_the_open_connection() -> None:
    connector = FakeConnector()
    assert connector.connections == []

    first = connector.connection()

    assert connector.connection() is first
    assert connector.connections == [first]


def test_reopens_when_the_connection_is_closed() -> None:
    connector = FakeConnector()
    first = connector.connection()
    first.closed = True

    second = connector.connection()

    assert second is not first
    assert len(connector.connections) == 2


def test_recycles_a_connection_once_it_reaches_max_age() -> None:
    clock = FakeClock()
    connector = FakeConnector(max_age=MAX_AGE, clock=clock)
    first = connector.connection()

    clock.advance(MAX_AGE - timedelta(seconds=1))
    assert connector.connection() is first

    clock.advance(timedelta(seconds=1))
    second = connector.connection()

    assert second is not first
    assert first.closed is True
    assert connector.reset_calls == 1


def test_age_counts_from_the_latest_open() -> None:
    clock = FakeClock()
    connector = FakeConnector(max_age=MAX_AGE, clock=clock)
    connector.connection()
    clock.advance(MAX_AGE)
    second = connector.connection()

    clock.advance(MAX_AGE - timedelta(seconds=1))

    assert connector.connection() is second


def test_no_age_check_without_max_age() -> None:
    clock = FakeClock()
    connector = FakeConnector(clock=clock)
    first = connector.connection()

    clock.advance(timedelta(days=1))

    assert connector.connection() is first


def test_reset_closes_and_drops_the_connection() -> None:
    connector = FakeConnector()
    first = connector.connection()

    connector.reset()

    assert first.closed is True
    assert connector.connection() is not first


def test_reset_without_a_connection_is_a_no_op() -> None:
    connector = FakeConnector()

    connector.reset()

    assert connector.connections == []


def test_reset_ignores_errors_while_closing() -> None:
    connector = FakeConnector()
    connection = connector.connection()

    def broken_close() -> None:
        raise psycopg.OperationalError("already gone")

    connection.close = broken_close  # type: ignore[method-assign]

    connector.reset()

    assert connector.connection() is not connection


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("host=abc123.dsql.us-east-1.on.aws password=token-1"),
        psycopg.OperationalError("connection to abc123.dsql.us-east-1.on.aws failed"),
        DataSourceConnectionError("raw failure from a subclass"),
    ],
)
def test_open_failure_becomes_data_source_connection_error_without_details(
    failure: Exception,
) -> None:
    with pytest.raises(DataSourceConnectionError) as caught:
        FailingConnector(failure).connection()

    assert caught.value.__cause__ is failure
    assert "dsql" not in str(caught.value)
    assert "token" not in str(caught.value)


def test_a_failed_open_is_retried_on_the_next_call() -> None:
    connector = FakeConnector(DataSourceConnectionError("no route to host"), [])

    with pytest.raises(DataSourceConnectionError):
        connector.connection()

    assert connector.connection() is connector.connections[0]
```

- [ ] **Step 3: Update the two existing tests that depend on the old fake**

In `T/test_postgresql_repository.py`, replace `test_connector_failure_propagates_unchanged` with:

```python
def test_connector_failure_propagates_as_data_source_connection_error() -> None:
    failure = DataSourceConnectionError("no route to host")
    connector = FakeConnector(failure)

    with pytest.raises(DataSourceConnectionError) as caught:
        PostgreSQLRepository(connector).execute_query(QUERY, PARAMS)

    assert caught.value.__cause__ is failure
    assert connector.reset_calls == 0
```

In `T/test_aurora_postgresql_connector.py`, delete `test_connector_explicitly_implements_the_psycopg_connector_protocol` and its `@pytest.mark.parametrize` decorator (lines 80-86). Inheriting from the ABC is now required. Remove the now-unused imports `PsycopgConnector` and `FakeConnector`, and keep `FakeConnection`.

- [ ] **Step 4: Run the tests to verify they fail**

Run: `$PY -m pytest tests/unit/ledgerlens_tools -q`
Expected: failures and errors. `FakeConnector` calls `super().__init__(max_age=..., clock=...)` on a Protocol, which raises `TypeError`, and `test_base_class_cannot_be_instantiated` fails.

- [ ] **Step 5: Rewrite `L/utils/connectors/base.py`**

```python
"""Connection lifecycle shared by psycopg-based connectors."""

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import psycopg

from ledgerlens.application.ports.errors import DataSourceConnectionError

logger = logging.getLogger(__name__)


class PsycopgConnector(ABC):
    """Cache one psycopg connection per Lambda container and reopen it when needed.

    Subclasses only say how to open a connection (``_open``). This class reopens
    it when it is missing, closed or older than ``max_age``, and wraps every
    open failure in DataSourceConnectionError.
    """

    def __init__(
        self,
        max_age: timedelta | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Configure the lifecycle without opening a connection.

        Args:
            max_age: Reopen connections at least this old; None disables the check.
            clock: Monotonic time in seconds; replaced in tests.
        """
        self._max_age: timedelta | None = max_age
        self._clock: Callable[[], float] = clock
        self._connection: psycopg.Connection[Any] | None = None
        self._opened_at: float = 0.0

    def connection(self) -> psycopg.Connection[Any]:
        """Return the cached connection, opening a new one if needed.

        A new one is opened when the cached connection is missing, closed or at
        least ``max_age`` old.

        Raises:
            DataSourceConnectionError: The connection couldn't be opened. The
                original error is chained as ``__cause__``.
        """
        if self._connection is not None and self._is_too_old():
            logger.info("Recycling a database connection older than %s", self._max_age)
            self.reset()
        if self._connection is None or self._connection.closed:
            try:
                connection = self._open()
            except Exception as exc:
                # Fixed message: hosts, users and tokens never reach logs or agents.
                raise DataSourceConnectionError(
                    "Could not open a database connection"
                ) from exc
            self._connection, self._opened_at = connection, self._clock()
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

    @abstractmethod
    def _open(self) -> psycopg.Connection[Any]:
        """Open a new connection. Any exception is wrapped by connection()."""

    def _is_too_old(self) -> bool:
        """Return True when max_age is set and the connection has reached it."""
        if self._max_age is None:
            return False
        return self._clock() - self._opened_at >= self._max_age.total_seconds()
```

- [ ] **Step 6: Make `AuroraPostgreSQLConnector` a subclass that only opens connections**

This is a temporary step to keep the suite green; Task 5 deletes the file. Replace everything in `L/utils/connectors/aurora_postgresql.py` from `import json` to the end of the file with the code below. Keep the module docstring and its TODOs.

```python
import json
from collections.abc import Callable, Mapping
from typing import Any, Final, Protocol

import boto3
import psycopg
from psycopg.rows import dict_row

from ledgerlens.utils.connectors.base import PsycopgConnector

_CONNECT_TIMEOUT_SECONDS: Final = 5
_DEFAULT_PORT: Final = 5432


class SecretsClient(Protocol):
    """The part of the boto3 Secrets Manager client the connector uses."""

    def get_secret_value(self, *, SecretId: str) -> Mapping[str, Any]:  # noqa: N803
        """Return the secret payload; ``SecretString`` holds the JSON credentials."""
        ...


class AuroraPostgreSQLConnector(PsycopgConnector):
    """Open read-only psycopg connections to Aurora PostgreSQL.

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
        super().__init__()
        self._secret_arn: str = secret_arn
        self._statement_timeout_ms: int = statement_timeout_ms
        self._secrets_client: SecretsClient | None = secrets_client
        self._connect: Callable[..., psycopg.Connection[Any]] = connect

    def _open(self) -> psycopg.Connection[Any]:
        """Read the credentials and open a new connection."""
        credentials = self._read_secret()
        return self._connect(
            host=credentials["host"],
            port=int(credentials.get("port", _DEFAULT_PORT)),
            dbname=credentials["dbname"],
            user=credentials["username"],
            password=credentials["password"],
            sslmode="require",
            # Accented merchant names and filters must reach the server intact.
            client_encoding="utf8",
            connect_timeout=_CONNECT_TIMEOUT_SECONDS,
            autocommit=True,
            row_factory=dict_row,
            options=(
                f"-c statement_timeout={self._statement_timeout_ms} "
                "-c default_transaction_read_only=on"
            ),
        )

    def _read_secret(self) -> Mapping[str, Any]:
        """Fetch and parse the credentials JSON from Secrets Manager."""
        if self._secrets_client is None:
            self._secrets_client = boto3.client("secretsmanager")
        response = self._secrets_client.get_secret_value(SecretId=self._secret_arn)
        credentials: Mapping[str, Any] = json.loads(response["SecretString"])
        return credentials
```

- [ ] **Step 7: Lint and run the full suite**

Run the lint command, then `$PY -m pytest tests/unit/ledgerlens_tools -q`.
Expected: everything passes. That is 198 minus the 2 deleted MRO cases, plus 14 new tests in `test_psycopg_connector.py` (the parametrized one counts 3).

- [ ] **Step 8: Commit**

```bash
git add gateway/tools/ledgerlens_tools/ledgerlens/utils/connectors/base.py \
  gateway/tools/ledgerlens_tools/ledgerlens/utils/connectors/aurora_postgresql.py \
  tests/unit/ledgerlens_tools/ledgerlens_fakes.py \
  tests/unit/ledgerlens_tools/test_psycopg_connector.py \
  tests/unit/ledgerlens_tools/test_postgresql_repository.py \
  tests/unit/ledgerlens_tools/test_aurora_postgresql_connector.py
git commit -F - <<'EOF'
refactor(tools): make PsycopgConnector a base class owning the lifecycle

Caching, reopening a closed or too-old connection, reset and wrapping of
open failures move into the base; subclasses only implement _open().

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 3: `DsqlRepository` with DSQL limit errors

**Files:**
- Rename: `L/infrastructure/repositories/postgresql_repository.py` → `L/infrastructure/repositories/dsql_repository.py` (rewrite)
- Rename: `T/test_postgresql_repository.py` → `T/test_dsql_repository.py` (rewrite)
- Modify: `L/delivery/dependencies/dependencies_builder.py:36-38,88`
- Modify: `T/test_delivery_wiring.py:29-31,111`

**Interfaces:**
- Consumes: `PsycopgConnector` (Task 2) and `QueryLimitExceededError` (Task 1).
- Produces: `ledgerlens.infrastructure.repositories.dsql_repository.DsqlRepository(connector: PsycopgConnector)`, a `DatabaseRepository`.

- [ ] **Step 1: Move and rewrite the test**

```bash
git mv tests/unit/ledgerlens_tools/test_postgresql_repository.py tests/unit/ledgerlens_tools/test_dsql_repository.py
```

Replace the content of `T/test_dsql_repository.py` with:

```python
"""Tests for DsqlRepository: rows, error mapping and the single retry."""

import psycopg
import pytest
from ledgerlens.application.ports.errors import (
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
)
from ledgerlens.infrastructure.repositories.dsql_repository import DsqlRepository
from ledgerlens_fakes import FakeConnector, make_row

pytestmark = pytest.mark.unit

QUERY = "SELECT * FROM transactions WHERE customer_id = %(customer_id)s"
PARAMS = {"customer_id": "CUST-1"}


def test_returns_rows_as_dicts_and_passes_query_and_params() -> None:
    connector = FakeConnector([make_row()])

    rows = DsqlRepository(connector).execute_query(QUERY, PARAMS)

    assert rows == [make_row()]
    assert connector.connections[0].cursors[0].executed == [(QUERY, PARAMS)]


@pytest.mark.parametrize(
    "error",
    [
        psycopg.errors.OutOfMemory("query exceeded the 128 MiB limit (53200)"),
        psycopg.errors.ProgramLimitExceeded("transaction age limit of 300s (54000)"),
        psycopg.errors.QueryCanceled("canceling statement (57014)"),
    ],
)
def test_dsql_limit_errors_raise_query_limit_exceeded_without_retry(
    error: psycopg.Error,
) -> None:
    # Each one is an OperationalError subclass: it must not hit the retry branch.
    assert isinstance(error, psycopg.OperationalError)
    connector = FakeConnector(error)

    with pytest.raises(QueryLimitExceededError) as caught:
        DsqlRepository(connector).execute_query(QUERY, PARAMS)

    assert caught.value.__cause__ is error
    assert connector.reset_calls == 0
    assert len(connector.connections) == 1
    assert len(connector.connections[0].cursors) == 1


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
        DsqlRepository(connector).execute_query(QUERY, PARAMS)

    assert caught.value.__cause__ is error
    assert connector.reset_calls == 0


def test_operational_error_resets_and_retries_once_then_succeeds() -> None:
    connector = FakeConnector(
        psycopg.OperationalError("server closed the connection"), [make_row()]
    )

    rows = DsqlRepository(connector).execute_query(QUERY, PARAMS)

    assert rows == [make_row()]
    assert connector.reset_calls == 1
    assert len(connector.connections) == 2


def test_second_operational_error_raises_data_source_connection_error() -> None:
    lost = psycopg.OperationalError("server closed the connection")
    connector = FakeConnector(lost)

    with pytest.raises(DataSourceConnectionError) as caught:
        DsqlRepository(connector).execute_query(QUERY, PARAMS)

    assert caught.value.__cause__ is lost
    assert connector.reset_calls == 2
    assert len(connector.connections) == 2


def test_connector_failure_propagates_as_data_source_connection_error() -> None:
    failure = DataSourceConnectionError("no route to host")
    connector = FakeConnector(failure)

    with pytest.raises(DataSourceConnectionError) as caught:
        DsqlRepository(connector).execute_query(QUERY, PARAMS)

    assert caught.value.__cause__ is failure
    assert connector.reset_calls == 0
```

In `T/test_delivery_wiring.py`:
- Replace the import `from ledgerlens.infrastructure.repositories.postgresql_repository import (PostgreSQLRepository,)` with `from ledgerlens.infrastructure.repositories.dsql_repository import DsqlRepository`.
- In `test_build_database_repository_wraps_the_connector_for_the_engine`, change `isinstance(database_repository, PostgreSQLRepository)` to `isinstance(database_repository, DsqlRepository)`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest tests/unit/ledgerlens_tools/test_dsql_repository.py tests/unit/ledgerlens_tools/test_delivery_wiring.py -q`
Expected: collection errors, `ModuleNotFoundError: No module named 'ledgerlens.infrastructure.repositories.dsql_repository'`.

- [ ] **Step 3: Move and rewrite the repository**

```bash
git mv gateway/tools/ledgerlens_tools/ledgerlens/infrastructure/repositories/postgresql_repository.py gateway/tools/ledgerlens_tools/ledgerlens/infrastructure/repositories/dsql_repository.py
```

Replace the content of `L/infrastructure/repositories/dsql_repository.py` with:

```python
"""DatabaseRepository adapter for Aurora DSQL through psycopg 3.

TODO(ledgerlens): R6 - the DB role is the only write guard. DSQL rejects
  default_transaction_read_only, so ledgerlens_readonly must have SELECT-only
  grants. If it is misconfigured, nothing else stops writes.
TODO(ledgerlens): R10 - no per-query timeout: DSQL rejects statement_timeout. A
  slow query runs until the Lambda times out (DSQL caps a transaction at 300 s),
  and the agent gets the platform's generic timeout instead of
  SearchTooBroadError. Keep the Lambda timeout well under the agent's tool
  timeout.
TODO(ledgerlens): R12 - server-side cancel on DSQL is unverified, so the
  QueryCanceled mapping may never fire. Harmless either way.
"""

import logging
from collections.abc import Mapping
from typing import Any, Final

import psycopg

from ledgerlens.application.ports.database_repository import DatabaseRepository
from ledgerlens.application.ports.errors import (
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
)
from ledgerlens.utils.connectors.base import PsycopgConnector

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS: Final = 2
# SQLSTATE 53200 (128 MiB per query), 54000 (300 s per transaction) and 57014
# (cancelled). psycopg classes all three as OperationalError subclasses.
_LIMIT_ERRORS: Final = (
    psycopg.errors.OutOfMemory,
    psycopg.errors.ProgramLimitExceeded,
    psycopg.errors.QueryCanceled,
)


class DsqlRepository(DatabaseRepository):
    """Run parameterised SQL on Aurora DSQL and translate psycopg errors.

    A lost connection (``OperationalError``) is reset and the query retried once.
    That is safe because the repository only runs SELECTs, in autocommit, as a
    role with SELECT-only grants. A query that breaks a DSQL limit is never
    retried: it would fail the same way.
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
            QueryLimitExceededError: The query exceeded a DSQL memory or time
                limit, or the server cancelled it.
            QueryExecutionError: Any other database error.
        """
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return self._run(query, params)
            except _LIMIT_ERRORS as exc:
                # OperationalError subclasses: must be caught first, never retried.
                raise QueryLimitExceededError(
                    "The query exceeded a database limit"
                ) from exc
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
                raise QueryExecutionError(
                    "The database failed to run the query"
                ) from exc
        raise AssertionError("unreachable: the retry loop always returns or raises")

    def _run(self, query: str, params: Mapping[str, object]) -> list[dict[str, Any]]:
        """Run the query once on the connector's current connection."""
        connection = self._connector.connection()
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
```

- [ ] **Step 4: Point the builder at `DsqlRepository`**

In `L/delivery/dependencies/dependencies_builder.py`:
- Replace the three-line import of `PostgreSQLRepository` with:

```python
from ledgerlens.infrastructure.repositories.dsql_repository import DsqlRepository
```

- In `build_database_repository`, replace `return PostgreSQLRepository(connector)` with `return DsqlRepository(connector)`. The `engine == "postgresql"` check stays until Task 5.

- [ ] **Step 5: Lint and run the full suite**

Run the lint command, then `$PY -m pytest tests/unit/ledgerlens_tools -q`.
Expected: everything passes.
Also run: `grep -rn "PostgreSQLRepository\|postgresql_repository" gateway/tools tests/unit --include=*.py`
Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add gateway/tools/ledgerlens_tools/ledgerlens/infrastructure/repositories/postgresql_repository.py \
  gateway/tools/ledgerlens_tools/ledgerlens/infrastructure/repositories/dsql_repository.py \
  gateway/tools/ledgerlens_tools/ledgerlens/delivery/dependencies/dependencies_builder.py \
  tests/unit/ledgerlens_tools/test_postgresql_repository.py \
  tests/unit/ledgerlens_tools/test_dsql_repository.py \
  tests/unit/ledgerlens_tools/test_delivery_wiring.py
git commit -F - <<'EOF'
refactor(tools): rename PostgreSQLRepository to DsqlRepository

Map DSQL's 128 MiB (53200) and 300 s (54000) limits and server cancels
(57014) to QueryLimitExceededError without a retry; they are
OperationalError subclasses, so they are caught before the reconnect path.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

(`git add` on the old paths records their deletion after `git mv`. If git complains that the old path doesn't exist, drop it from the command; `git mv` already staged the rename.)

---

### Task 4: `DsqlConnector` with IAM tokens

This change only adds files. The Aurora PostgreSQL connector stays until Task 5.

**Files:**
- Create: `L/utils/connectors/dsql.py`
- Modify: `T/ledgerlens_fakes.py` (add `FakeDsqlTokenClient`)
- Create: `T/test_dsql_connector.py`

**Interfaces:**
- Consumes: `PsycopgConnector(max_age, clock)` (Task 2) and `FakeClock` (Task 2).
- Produces:

```python
ADMIN_USER: Final = "admin"

class DsqlTokenClient(Protocol):
    def generate_db_connect_auth_token(self, Hostname: str, Region: str) -> str: ...
    def generate_db_connect_admin_auth_token(self, Hostname: str, Region: str) -> str: ...

class DsqlConnector(PsycopgConnector):
    MAX_AGE: Final = timedelta(minutes=55)
    def __init__(self, cluster_endpoint: str, region: str, db_user: str,
                 dsql_client: DsqlTokenClient | None = None,
                 connect: Callable[..., psycopg.Connection[Any]] = psycopg.connect,
                 clock: Callable[[], float] = time.monotonic) -> None: ...
```

- Produces (fakes): `FakeDsqlTokenClient(error=None)` with `.calls: list[tuple[str, str, str]]` holding `(method, Hostname, Region)`. Its tokens are `"token-1"`, `"token-2"`, and so on.

- [ ] **Step 1: Add `FakeDsqlTokenClient` to the end of `T/ledgerlens_fakes.py`**

```python
class FakeDsqlTokenClient:
    """boto3 DSQL client double; returns token-1, token-2, ... and records calls."""

    def __init__(self, error: Exception | None = None) -> None:
        """Raise ``error`` from every token method if given."""
        self.error = error
        self.calls: list[tuple[str, str, str]] = []

    def generate_db_connect_auth_token(
        self,
        Hostname: str,  # noqa: N803
        Region: str,  # noqa: N803
    ) -> str:
        """Return the next token for a custom database role."""
        return self._token("generate_db_connect_auth_token", Hostname, Region)

    def generate_db_connect_admin_auth_token(
        self,
        Hostname: str,  # noqa: N803
        Region: str,  # noqa: N803
    ) -> str:
        """Return the next token for the admin role."""
        return self._token("generate_db_connect_admin_auth_token", Hostname, Region)

    def _token(self, method: str, hostname: str, region: str) -> str:
        """Record the call, then raise the configured error or return a token."""
        self.calls.append((method, hostname, region))
        if self.error is not None:
            raise self.error
        return f"token-{len(self.calls)}"
```

- [ ] **Step 2: Write `T/test_dsql_connector.py`**

```python
"""Tests for DsqlConnector: connect args, IAM tokens, recycling, failures."""

from datetime import timedelta
from typing import Any

import ledgerlens.utils.connectors.dsql as dsql_module
import psycopg
import pytest
from ledgerlens.application.ports.errors import DataSourceConnectionError
from ledgerlens.utils.connectors.dsql import DsqlConnector
from ledgerlens_fakes import FakeClock, FakeConnection, FakeDsqlTokenClient
from psycopg.rows import dict_row

pytestmark = pytest.mark.unit

ENDPOINT = "abc123.dsql.us-east-1.on.aws"
REGION = "us-east-1"
READONLY_USER = "ledgerlens_readonly"


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
    db_user: str = READONLY_USER,
    tokens: FakeDsqlTokenClient | None = None,
    connect: RecordingConnect | None = None,
    clock: FakeClock | None = None,
) -> tuple[DsqlConnector, FakeDsqlTokenClient, RecordingConnect]:
    """Build a connector wired to doubles."""
    tokens = tokens or FakeDsqlTokenClient()
    connect = connect or RecordingConnect()
    connector = DsqlConnector(
        cluster_endpoint=ENDPOINT,
        region=REGION,
        db_user=db_user,
        dsql_client=tokens,
        connect=connect,
        clock=clock or FakeClock(),
    )
    return connector, tokens, connect


def test_opens_a_tls_connection_with_an_iam_token_and_no_session_options() -> None:
    connector, _, connect = make_connector()

    connection = connector.connection()

    assert connection is connect.connections[0]
    # Exact equality: DSQL rejects statement_timeout and
    # default_transaction_read_only, so no "options" may be sent.
    assert connect.calls == [
        {
            "host": ENDPOINT,
            "port": 5432,
            "dbname": "postgres",
            "user": READONLY_USER,
            "password": "token-1",
            "sslmode": "require",
            "client_encoding": "utf8",
            "connect_timeout": 5,
            "autocommit": True,
            "row_factory": dict_row,
        }
    ]


def test_a_custom_role_uses_the_normal_token_method() -> None:
    connector, tokens, _ = make_connector()

    connector.connection()

    assert tokens.calls == [("generate_db_connect_auth_token", ENDPOINT, REGION)]


def test_admin_uses_the_admin_token_method() -> None:
    connector, tokens, connect = make_connector(db_user="admin")

    connector.connection()

    assert tokens.calls == [("generate_db_connect_admin_auth_token", ENDPOINT, REGION)]
    assert connect.calls[0]["user"] == "admin"


def test_every_open_uses_a_new_token() -> None:
    connector, _, connect = make_connector()
    connector.connection()

    connector.reset()
    connector.connection()

    assert [call["password"] for call in connect.calls] == ["token-1", "token-2"]


def test_reuses_the_open_connection_without_a_new_token() -> None:
    connector, tokens, _ = make_connector()

    assert connector.connection() is connector.connection()
    assert len(tokens.calls) == 1


def test_recycles_connections_after_55_minutes_with_a_fresh_token() -> None:
    assert DsqlConnector.MAX_AGE == timedelta(minutes=55)
    clock = FakeClock()
    connector, _, connect = make_connector(clock=clock)
    first = connector.connection()

    clock.advance(timedelta(minutes=54, seconds=59))
    assert connector.connection() is first

    clock.advance(timedelta(seconds=1))
    second = connector.connection()

    assert second is not first
    assert first.closed is True
    assert [call["password"] for call in connect.calls] == ["token-1", "token-2"]


def test_building_the_connector_does_not_create_a_boto3_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[object] = []
    monkeypatch.setattr(
        dsql_module.boto3, "client", lambda *a, **k: created.append((a, k))
    )

    DsqlConnector(cluster_endpoint=ENDPOINT, region=REGION, db_user=READONLY_USER)

    assert created == []


def test_creates_one_boto3_dsql_client_for_the_region_on_first_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokens = FakeDsqlTokenClient()
    created: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_client(*args: object, **kwargs: object) -> FakeDsqlTokenClient:
        created.append((args, kwargs))
        return tokens

    monkeypatch.setattr(dsql_module.boto3, "client", fake_client)
    connector = DsqlConnector(
        cluster_endpoint=ENDPOINT,
        region=REGION,
        db_user=READONLY_USER,
        connect=RecordingConnect(),
    )

    connector.connection()
    connector.reset()
    connector.connection()

    assert created == [(("dsql",), {"region_name": REGION})]
    assert len(tokens.calls) == 2


@pytest.mark.parametrize(
    ("tokens", "connect"),
    [
        (FakeDsqlTokenClient(error=RuntimeError("NoCredentialsError")), None),
        (
            None,
            RecordingConnect(
                error=psycopg.OperationalError(
                    f"connection to {ENDPOINT} failed: access denied for token-1"
                )
            ),
        ),
    ],
)
def test_token_or_connect_failure_raises_data_source_connection_error(
    tokens: FakeDsqlTokenClient | None, connect: RecordingConnect | None
) -> None:
    connector, _, _ = make_connector(tokens=tokens, connect=connect)

    with pytest.raises(DataSourceConnectionError) as caught:
        connector.connection()

    assert caught.value.__cause__ is not None
    assert ENDPOINT not in str(caught.value)
    assert "token" not in str(caught.value)


def test_a_boto3_without_the_dsql_client_raises_data_source_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An old Lambda runtime boto3 raises UnknownServiceError for "dsql".
    def old_boto3_client(*args: object, **kwargs: object) -> object:
        raise RuntimeError("Unknown service: 'dsql'")

    monkeypatch.setattr(dsql_module.boto3, "client", old_boto3_client)
    connector = DsqlConnector(
        cluster_endpoint=ENDPOINT,
        region=REGION,
        db_user=READONLY_USER,
        connect=RecordingConnect(),
    )

    with pytest.raises(DataSourceConnectionError):
        connector.connection()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `$PY -m pytest tests/unit/ledgerlens_tools/test_dsql_connector.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'ledgerlens.utils.connectors.dsql'`.

- [ ] **Step 4: Write `L/utils/connectors/dsql.py`**

```python
"""Aurora DSQL connector: psycopg connections authenticated with IAM tokens.

TODO(ledgerlens): R2 - the DSQL cluster doesn't exist yet; DSQL_CLUSTER_ENDPOINT
  has nothing real to point to until the DSQL cluster and data-load spec lands.
TODO(ledgerlens): R6 - the DB role is the only write guard: DSQL rejects
  default_transaction_read_only. ledgerlens_readonly must be created with
  SELECT-only grants and mapped to the Lambda's IAM role (AWS IAM GRANT).
TODO(ledgerlens): R7 - mostly resolved: a cluster accepts 10,000 connections.
  What is left is the rate of 100 new connections/s (burst 1,000) during mass
  cold starts, which surfaces as "temporarily unavailable" after one retry. Cap
  reservedConcurrentExecutions if it ever matters.
TODO(ledgerlens): R11 - sslmode=require doesn't verify the server certificate;
  verify-full needs the Amazon root CA bundled with the Lambda.
"""

import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any, Final, Protocol

import boto3
import psycopg
from psycopg.rows import dict_row

from ledgerlens.utils.connectors.base import PsycopgConnector

ADMIN_USER: Final = "admin"
_PORT: Final = 5432
_DBNAME: Final = "postgres"
_CONNECT_TIMEOUT_SECONDS: Final = 5


class DsqlTokenClient(Protocol):
    """The part of the boto3 DSQL client the connector uses."""

    def generate_db_connect_auth_token(
        self,
        Hostname: str,  # noqa: N803
        Region: str,  # noqa: N803
    ) -> str:
        """Return a 15-minute IAM token for a custom database role."""
        ...

    def generate_db_connect_admin_auth_token(
        self,
        Hostname: str,  # noqa: N803
        Region: str,  # noqa: N803
    ) -> str:
        """Return a 15-minute IAM token for the admin role."""
        ...


class DsqlConnector(PsycopgConnector):
    """Open psycopg connections to Aurora DSQL with a fresh IAM token each time.

    A token is only checked when connecting, so an open connection outlives its
    token without harm, and every reconnect generates a new one. Connections are
    recycled after MAX_AGE, before DSQL closes them at 60 minutes.
    """

    MAX_AGE: Final = timedelta(minutes=55)

    def __init__(
        self,
        cluster_endpoint: str,
        region: str,
        db_user: str,
        dsql_client: DsqlTokenClient | None = None,
        connect: Callable[..., psycopg.Connection[Any]] = psycopg.connect,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Configure the connector without opening a connection or a boto3 client.

        Args:
            cluster_endpoint: Cluster host, such as abc.dsql.us-east-1.on.aws.
            region: AWS region used to sign the token.
            db_user: Database role; ``admin`` uses the admin token.
            dsql_client: boto3 DSQL client; created lazily on the first open.
            connect: Connection factory; replaced in tests.
            clock: Monotonic time in seconds for MAX_AGE; replaced in tests.
        """
        super().__init__(max_age=self.MAX_AGE, clock=clock)
        self._cluster_endpoint: str = cluster_endpoint
        self._region: str = region
        self._db_user: str = db_user
        self._dsql_client: DsqlTokenClient | None = dsql_client
        self._connect: Callable[..., psycopg.Connection[Any]] = connect

    def _open(self) -> psycopg.Connection[Any]:
        """Generate a token and open a TLS connection; the base wraps failures."""
        return self._connect(
            host=self._cluster_endpoint,
            port=_PORT,
            dbname=_DBNAME,
            user=self._db_user,
            password=self._generate_token(),
            sslmode="require",
            # Allowed by DSQL; accented merchant names must reach the server intact.
            client_encoding="utf8",
            connect_timeout=_CONNECT_TIMEOUT_SECONDS,
            autocommit=True,
            row_factory=dict_row,
        )

    def _generate_token(self) -> str:
        """Sign a new IAM token locally (no network call) for the configured role."""
        if self._dsql_client is None:
            self._dsql_client = boto3.client("dsql", region_name=self._region)
        if self._db_user == ADMIN_USER:
            return self._dsql_client.generate_db_connect_admin_auth_token(
                Hostname=self._cluster_endpoint, Region=self._region
            )
        return self._dsql_client.generate_db_connect_auth_token(
            Hostname=self._cluster_endpoint, Region=self._region
        )
```

- [ ] **Step 5: Lint and run the full suite**

Run the lint command, then `$PY -m pytest tests/unit/ledgerlens_tools -q`.
Expected: everything passes.

- [ ] **Step 6: Commit**

```bash
git add gateway/tools/ledgerlens_tools/ledgerlens/utils/connectors/dsql.py \
  tests/unit/ledgerlens_tools/ledgerlens_fakes.py \
  tests/unit/ledgerlens_tools/test_dsql_connector.py
git commit -F - <<'EOF'
feat(tools): add DsqlConnector with IAM token authentication

A fresh token per open (admin token for the admin role), dbname postgres,
TLS, no session options, and a 55-minute recycle before DSQL's 60-minute
connection cut-off.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 5: DSQL settings and wiring; remove Aurora PostgreSQL

This task switches the engine.

**Files:**
- Modify (rewrite): `L/delivery/settings.py`
- Create: `T/test_settings.py`
- Modify (rewrite): `L/delivery/dependencies/dependencies_builder.py`
- Modify: `T/test_delivery_wiring.py` (from line 1 to the end of `test_use_case_build_with_bad_configuration_returns_none`)
- Modify: `T/test_list_card_transactions_handler.py:13-18,34-41,44-51`
- Modify: `L/delivery/list_card_transactions_handler.py:18-20`
- Delete: `L/utils/connectors/aurora_postgresql.py`, `T/test_aurora_postgresql_connector.py`

**Interfaces:**
- Consumes: `DsqlConnector` (Task 4), `DsqlRepository` (Task 3) and `PsycopgConnector` (Task 2).
- Produces:

```python
class DatabaseEngine(str, Enum): AURORA_DSQL = "aurora_dsql"
DatabaseSettings(engine: DatabaseEngine, max_rows: int).from_env(env)
DsqlSettings(cluster_endpoint: str, region: str, db_user: str).from_env(env)
SQL_DIALECTS: Final[Mapping[DatabaseEngine, str]]
build_settings(env) -> DatabaseSettings
build_dsql_settings(env) -> DsqlSettings
build_connector(settings: DatabaseSettings, env: Mapping[str, str]) -> PsycopgConnector
build_database_repository(engine: DatabaseEngine, connector) -> DatabaseRepository
build_query_provider(engine: DatabaseEngine) -> QueryProvider
```

- [ ] **Step 1: Write `T/test_settings.py`**

```python
"""Tests for the Lambda settings read from environment variables."""

import pytest
from ledgerlens.delivery.settings import (
    ConfigurationError,
    DatabaseEngine,
    DatabaseSettings,
    DsqlSettings,
)

pytestmark = pytest.mark.unit

ENDPOINT = "abc123.dsql.us-east-1.on.aws"
DSQL_ENV = {"DSQL_CLUSTER_ENDPOINT": ENDPOINT, "AWS_REGION": "us-east-1"}


def test_database_settings_default_to_aurora_dsql_and_25_rows() -> None:
    assert DatabaseSettings.from_env({}) == DatabaseSettings(
        engine=DatabaseEngine.AURORA_DSQL, max_rows=25
    )


@pytest.mark.parametrize("raw", ["aurora_dsql", " Aurora_DSQL ", "", "  "])
def test_db_engine_is_trimmed_lower_cased_and_defaulted(raw: str) -> None:
    settings = DatabaseSettings.from_env({"DB_ENGINE": raw})

    assert settings.engine is DatabaseEngine.AURORA_DSQL


@pytest.mark.parametrize("raw", ["postgresql", "oracle", "dsql"])
def test_unsupported_db_engine_is_rejected(raw: str) -> None:
    with pytest.raises(ConfigurationError, match="DB_ENGINE.*aurora_dsql"):
        DatabaseSettings.from_env({"DB_ENGINE": raw})


def test_max_rows_can_be_overridden() -> None:
    assert DatabaseSettings.from_env({"MAX_ROWS": " 10 "}).max_rows == 10


@pytest.mark.parametrize("raw", ["abc", "0", "-5", "2.5"])
def test_invalid_max_rows_is_rejected(raw: str) -> None:
    with pytest.raises(ConfigurationError, match="MAX_ROWS"):
        DatabaseSettings.from_env({"MAX_ROWS": raw})


def test_dsql_settings_read_endpoint_and_region_and_default_the_user() -> None:
    assert DsqlSettings.from_env(DSQL_ENV) == DsqlSettings(
        cluster_endpoint=ENDPOINT, region="us-east-1", db_user="ledgerlens_readonly"
    )


def test_dsql_settings_trim_every_value_and_read_the_user() -> None:
    env = {
        "DSQL_CLUSTER_ENDPOINT": f"  {ENDPOINT}  ",
        "AWS_REGION": " us-east-1 ",
        "DSQL_DB_USER": " admin ",
    }

    assert DsqlSettings.from_env(env) == DsqlSettings(
        cluster_endpoint=ENDPOINT, region="us-east-1", db_user="admin"
    )


def test_a_blank_db_user_falls_back_to_the_read_only_role() -> None:
    settings = DsqlSettings.from_env({**DSQL_ENV, "DSQL_DB_USER": "   "})

    assert settings.db_user == "ledgerlens_readonly"


@pytest.mark.parametrize(
    "endpoint",
    [
        "",
        "   ",
        f"https://{ENDPOINT}",
        f"{ENDPOINT}:5432",
        f"{ENDPOINT}/",
    ],
)
def test_invalid_cluster_endpoint_is_rejected(endpoint: str) -> None:
    with pytest.raises(ConfigurationError, match="DSQL_CLUSTER_ENDPOINT"):
        DsqlSettings.from_env({**DSQL_ENV, "DSQL_CLUSTER_ENDPOINT": endpoint})


def test_missing_cluster_endpoint_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="DSQL_CLUSTER_ENDPOINT"):
        DsqlSettings.from_env({"AWS_REGION": "us-east-1"})


@pytest.mark.parametrize("env", [{"DSQL_CLUSTER_ENDPOINT": ENDPOINT}, {**DSQL_ENV, "AWS_REGION": " "}])
def test_missing_region_is_rejected(env: dict[str, str]) -> None:
    with pytest.raises(ConfigurationError, match="AWS_REGION"):
        DsqlSettings.from_env(env)
```

- [ ] **Step 2: Update `T/test_delivery_wiring.py`**

Replace everything from line 1 to the end of `test_use_case_build_with_bad_configuration_returns_none` with the code below. `make_transaction` and the presenter tests below it stay unchanged.

```python
"""Tests for dependency wiring and the card transactions presenter."""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import ledgerlens.utils.connectors.dsql as dsql_module
import pytest
from ledgerlens.application.ports.errors import DataSourceConnectionError
from ledgerlens.application.use_cases.list_card_transactions import (
    ListCardTransactionsUseCase,
)
from ledgerlens.delivery.dependencies import dependencies_builder
from ledgerlens.delivery.dependencies.dependencies_builder import (
    QUERIES_ROOT,
    SQL_DIALECTS,
    build_connector,
    build_database_repository,
    build_dsql_settings,
    build_list_card_transactions_use_case,
    build_query_provider,
    build_settings,
)
from ledgerlens.delivery.presenters.card_transactions import (
    present_card_transactions,
)
from ledgerlens.delivery.settings import (
    ConfigurationError,
    DatabaseEngine,
    DatabaseSettings,
    DsqlSettings,
)
from ledgerlens.domain.entities.card_transaction import (
    CardTransaction,
    CardTransactionsResult,
)
from ledgerlens.infrastructure.repositories.dsql_repository import DsqlRepository
from ledgerlens.utils.connectors.dsql import DsqlConnector
from ledgerlens_fakes import FakeConnector, make_filters, make_row

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
    assert "DISTINCT ON" in provider.get("list_card_transactions")


def test_every_engine_has_a_dialect_folder_with_the_sql() -> None:
    for engine in DatabaseEngine:
        sql_file = QUERIES_ROOT / SQL_DIALECTS[engine] / "list_card_transactions.sql"
        assert sql_file.is_file()


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

    use_case = build_list_card_transactions_use_case(ENV)
    assert isinstance(use_case, ListCardTransactionsUseCase)
    result = use_case.execute(make_filters())

    assert result.transactions[0].transaction_id == "TX-1"
    executed_sql, params = connector.connections[-1].cursors[0].executed[0]
    assert "FROM transactions" in executed_sql
    assert params["limit"] == 26


def test_use_case_uses_max_rows_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector([make_row(transaction_id=str(i)) for i in range(4)])
    use_fake_connector(monkeypatch, connector)

    use_case = build_list_card_transactions_use_case({**ENV, "MAX_ROWS": "3"})
    assert use_case is not None
    result = use_case.execute(make_filters())

    assert len(result.transactions) == 3
    assert result.truncated is True


def test_use_case_build_opens_the_connection_eagerly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector()
    use_fake_connector(monkeypatch, connector)

    build_list_card_transactions_use_case(ENV)

    assert len(connector.connections) == 1


def test_use_case_build_survives_a_failed_cold_start_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = FakeConnector(DataSourceConnectionError("no route to host"), [])
    use_fake_connector(monkeypatch, connector)

    use_case = build_list_card_transactions_use_case(ENV)

    assert use_case is not None
    assert use_case.execute(make_filters()).transactions == ()


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
    assert build_list_card_transactions_use_case(env) is None
```

- [ ] **Step 3: Update `T/test_list_card_transactions_handler.py`**

Add the import below the `dependencies_builder` import block:

```python
from ledgerlens.delivery.settings import DatabaseEngine
```

Replace the `module` fixture's loop with the following. Clearing the endpoint makes the cold-start build return `None`, so importing the module never calls AWS.

```python
    for name in (
        "DB_ENGINE",
        "MAX_ROWS",
        "DSQL_CLUSTER_ENDPOINT",
        "DSQL_DB_USER",
        "AWS_REGION",
    ):
        monkeypatch.delenv(name, raising=False)
```

In `wire()`, replace the two `"postgresql"` arguments:

```python
        database_repository=build_database_repository(
            DatabaseEngine.AURORA_DSQL, connector
        ),
        query_provider=build_query_provider(DatabaseEngine.AURORA_DSQL),
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `$PY -m pytest tests/unit/ledgerlens_tools/test_settings.py tests/unit/ledgerlens_tools/test_delivery_wiring.py tests/unit/ledgerlens_tools/test_list_card_transactions_handler.py -q`
Expected: collection errors, `ImportError: cannot import name 'DatabaseEngine'` (and `SQL_DIALECTS`, `build_dsql_settings`).

- [ ] **Step 5: Rewrite `L/delivery/settings.py`**

```python
"""Lambda configuration read from environment variables."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final

DEFAULT_MAX_ROWS: Final = 25
DEFAULT_DSQL_DB_USER: Final = "ledgerlens_readonly"


class ConfigurationError(Exception):
    """The Lambda environment is missing a setting or has an invalid one."""


class DatabaseEngine(str, Enum):
    """Database engines the tools can run on."""

    AURORA_DSQL = "aurora_dsql"


@dataclass(frozen=True)
class DatabaseSettings:
    """Settings shared by every tool Lambda, whatever the engine.

    Attributes:
        engine: Database engine; selects the connector, repository and SQL dialect.
        max_rows: Maximum rows a tool returns per call.
    """

    engine: DatabaseEngine
    max_rows: int

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "DatabaseSettings":
        """Read and validate DB_ENGINE (default aurora_dsql) and MAX_ROWS.

        Raises:
            ConfigurationError: A value is invalid.
        """
        return cls(
            engine=_engine(env),
            max_rows=_positive_int(env, "MAX_ROWS", DEFAULT_MAX_ROWS),
        )


@dataclass(frozen=True)
class DsqlSettings:
    """Settings needed only to connect to Aurora DSQL.

    Attributes:
        cluster_endpoint: Cluster host, such as abc123.dsql.us-east-1.on.aws.
        region: AWS region used to sign the IAM token.
        db_user: Database role to connect as; ``admin`` uses the admin token.
    """

    cluster_endpoint: str
    region: str
    db_user: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "DsqlSettings":
        """Read and validate DSQL_CLUSTER_ENDPOINT, AWS_REGION and DSQL_DB_USER.

        Raises:
            ConfigurationError: A required variable is missing or a value is
                invalid.
        """
        return cls(
            cluster_endpoint=_cluster_endpoint(env),
            region=_required(env, "AWS_REGION"),
            db_user=env.get("DSQL_DB_USER", "").strip() or DEFAULT_DSQL_DB_USER,
        )


def _engine(env: Mapping[str, str]) -> DatabaseEngine:
    """Parse DB_ENGINE; blank or missing means Aurora DSQL.

    Raises:
        ConfigurationError: The value isn't a supported engine.
    """
    raw = env.get("DB_ENGINE", "").strip().lower() or DatabaseEngine.AURORA_DSQL.value
    try:
        return DatabaseEngine(raw)
    except ValueError as exc:
        allowed = ", ".join(engine.value for engine in DatabaseEngine)
        raise ConfigurationError(
            f"DB_ENGINE must be one of: {allowed}; got {raw!r}"
        ) from exc


def _cluster_endpoint(env: Mapping[str, str]) -> str:
    """Parse DSQL_CLUSTER_ENDPOINT as a bare host name.

    Raises:
        ConfigurationError: The value is missing or has a scheme, port or path.
    """
    endpoint = _required(env, "DSQL_CLUSTER_ENDPOINT")
    if ":" in endpoint or "/" in endpoint:
        raise ConfigurationError(
            "DSQL_CLUSTER_ENDPOINT must be a bare host name without a scheme, port "
            f"or path, such as abc123.dsql.us-east-1.on.aws; got {endpoint!r}"
        )
    return endpoint


def _required(env: Mapping[str, str], name: str) -> str:
    """Return a required variable, trimmed.

    Raises:
        ConfigurationError: The variable is missing or blank.
    """
    value = env.get(name, "").strip()
    if not value:
        raise ConfigurationError(f"{name} is required")
    return value


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

- [ ] **Step 6: Rewrite `L/delivery/dependencies/dependencies_builder.py`**

```python
"""Dependency builder: the only place where LedgerLens objects get built.

Handlers never build anything themselves. At cold start each handler calls its
tool's block below once and reuses the result on every warm invocation. That is
safe because every object built here is stateless between requests: request
data travels through method arguments, never through attributes. Keep it that
way. The connection inside the connector is the only shared state, and it heals
itself (reconnect when closed or too old, reset and retry once on a lost
connection).

The module is organised in blocks:

- Settings: environment variables to typed settings.
- Connection: the engine-specific connector (built without connecting).
- Adapters: the engine-specific database repository and query provider.
- Use cases: one function per tool, which builds that tool's whole graph.

Adding a database engine means adding a DatabaseEngine member, a branch to the
connection and adapter blocks (with its connector and database repository), a
SQL_DIALECTS entry and, when the dialect is new, a ``queries/<dialect>/`` folder.
Adding a tool means adding one function to the use cases block. A tool builds
only its own graph, so it never fails on settings it doesn't use.
"""

import logging
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Final

from ledgerlens.application.ports.database_repository import DatabaseRepository
from ledgerlens.application.ports.query_provider import QueryProvider
from ledgerlens.application.use_cases.list_card_transactions import (
    ListCardTransactionsUseCase,
)
from ledgerlens.delivery.settings import (
    ConfigurationError,
    DatabaseEngine,
    DatabaseSettings,
    DsqlSettings,
)
from ledgerlens.infrastructure.queries.file_query_provider import FileQueryProvider
from ledgerlens.infrastructure.repositories.dsql_repository import DsqlRepository
from ledgerlens.utils.connectors.base import PsycopgConnector
from ledgerlens.utils.connectors.dsql import DsqlConnector

logger = logging.getLogger(__name__)

QUERIES_ROOT: Final = Path(__file__).resolve().parents[2] / "queries"
# The SQL folder each engine runs; Aurora DSQL speaks the PostgreSQL dialect.
SQL_DIALECTS: Final[Mapping[DatabaseEngine, str]] = {
    DatabaseEngine.AURORA_DSQL: "postgresql",
}


# --- Settings ----------------------------------------------------------------


def build_settings(env: Mapping[str, str]) -> DatabaseSettings:
    """Read the engine-independent database settings from the Lambda environment.

    Raises:
        ConfigurationError: A value is invalid.
    """
    return DatabaseSettings.from_env(env)


def build_dsql_settings(env: Mapping[str, str]) -> DsqlSettings:
    """Read the Aurora DSQL connection settings from the Lambda environment.

    Raises:
        ConfigurationError: A required variable is missing or a value is invalid.
    """
    return DsqlSettings.from_env(env)


# --- Connection --------------------------------------------------------------


def build_connector(
    settings: DatabaseSettings, env: Mapping[str, str]
) -> PsycopgConnector:
    """Create the connector for the configured engine without connecting.

    Engine-specific settings are read inside the engine's branch, so an engine
    never fails on variables it doesn't use.

    Raises:
        ConfigurationError: The engine isn't supported or its settings are invalid.
    """
    if settings.engine == DatabaseEngine.AURORA_DSQL:
        dsql_settings = build_dsql_settings(env)
        return DsqlConnector(
            cluster_endpoint=dsql_settings.cluster_endpoint,
            region=dsql_settings.region,
            db_user=dsql_settings.db_user,
        )
    raise ConfigurationError(f"Unsupported DB_ENGINE {settings.engine!r}")


# --- Adapters ----------------------------------------------------------------


def build_database_repository(
    engine: DatabaseEngine, connector: PsycopgConnector
) -> DatabaseRepository:
    """Create the database repository adapter for ``engine`` around ``connector``.

    Raises:
        ConfigurationError: The engine isn't supported.
    """
    if engine == DatabaseEngine.AURORA_DSQL:
        return DsqlRepository(connector)
    raise ConfigurationError(f"Unsupported DB_ENGINE {engine!r}")


@cache
def build_query_provider(engine: DatabaseEngine) -> QueryProvider:
    """Return the query provider for ``engine``'s SQL dialect folder.

    Cached so every tool in the container shares one provider per engine.

    Raises:
        ConfigurationError: The engine has no SQL dialect.
    """
    dialect = SQL_DIALECTS.get(engine)
    if dialect is None:
        raise ConfigurationError(f"No SQL dialect for DB_ENGINE {engine!r}")
    return FileQueryProvider(QUERIES_ROOT / dialect)


# --- Use cases ---------------------------------------------------------------


def build_list_card_transactions_use_case(
    env: Mapping[str, str],
) -> ListCardTransactionsUseCase | None:
    """Build the list_card_transactions use case and its whole graph. Never raises.

    Called once per container at cold start. The connection is opened eagerly so
    the first request doesn't pay for it. A failed connection is only logged,
    because the database repository reconnects lazily on the first query.

    Returns:
        The ready use case, or None when the configuration is invalid. Every
        request then gets DataSourceUnavailableError's message.
    """
    try:
        settings = build_settings(env)
        connector = build_connector(settings, env)
        use_case = ListCardTransactionsUseCase(
            database_repository=build_database_repository(settings.engine, connector),
            query_provider=build_query_provider(settings.engine),
            max_rows=settings.max_rows,
        )
    except ConfigurationError:
        logger.exception("Invalid database configuration for list_card_transactions")
        return None
    try:
        connector.connection()
    except Exception:
        logger.warning(
            "Cold-start database connection failed; the first request will retry",
            exc_info=True,
        )
    return use_case
```

- [ ] **Step 7: Update the handler's R1 TODO**

In `L/delivery/list_card_transactions_handler.py`, replace the three `TODO(ledgerlens): R1` lines with:

```
TODO(ledgerlens): R1 - no CDK yet: no PythonFunction, Gateway target, env vars
  (DB_ENGINE, DSQL_CLUSTER_ENDPOINT, DSQL_DB_USER) or dsql:DbConnect grant on the
  cluster ARN (dsql:DbConnectAdmin only if DSQL_DB_USER=admin). The tool can't be
  deployed or called by the agent until the CDK spec lands.
```

- [ ] **Step 8: Delete the Aurora PostgreSQL connector and its test**

```bash
git rm gateway/tools/ledgerlens_tools/ledgerlens/utils/connectors/aurora_postgresql.py \
  tests/unit/ledgerlens_tools/test_aurora_postgresql_connector.py
```

- [ ] **Step 9: Lint and run the full suite**

Run the lint command, then `$PY -m pytest tests/unit/ledgerlens_tools -q`.
Expected: everything passes.
Also run: `grep -rn "AuroraPostgreSQL\|aurora_postgresql\|DB_SECRET_ARN\|DB_STATEMENT_TIMEOUT_MS\|SUPPORTED_ENGINES\|secretsmanager\|\"postgresql\"" gateway/tools tests/unit --include=*.py`
Expected: exactly one hit, the `SQL_DIALECTS` entry `DatabaseEngine.AURORA_DSQL: "postgresql",` in `dependencies_builder.py`. Any other hit is a leftover to fix.

- [ ] **Step 10: Commit**

```bash
git add gateway/tools/ledgerlens_tools/ledgerlens/delivery/settings.py \
  gateway/tools/ledgerlens_tools/ledgerlens/delivery/dependencies/dependencies_builder.py \
  gateway/tools/ledgerlens_tools/ledgerlens/delivery/list_card_transactions_handler.py \
  tests/unit/ledgerlens_tools/test_settings.py \
  tests/unit/ledgerlens_tools/test_delivery_wiring.py \
  tests/unit/ledgerlens_tools/test_list_card_transactions_handler.py
git commit -F - <<'EOF'
feat(tools): make Aurora DSQL the only database engine

DB_ENGINE defaults to aurora_dsql (its only value); DsqlSettings reads
DSQL_CLUSTER_ENDPOINT, AWS_REGION and DSQL_DB_USER inside the DSQL branch;
SQL_DIALECTS maps the engine to queries/postgresql. The Aurora PostgreSQL
connector, its Secrets Manager client and DB_SECRET_ARN are removed.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

(The `git rm` from Step 8 is already staged and goes into this commit.)

---

### Task 6: SQL contract against session statements, risk notes, boto3 pin

**Files:**
- Modify: `T/test_query_contracts.py` (new test)
- Modify: `L/queries/postgresql/list_card_transactions.sql:1,25-26`
- Modify: `gateway/tools/ledgerlens_tools/requirements.txt`

**Interfaces:** none. This task only adds tests and text.

- [ ] **Step 1: Write the contract test**

Add the following to `T/test_query_contracts.py`.

Below `TRANSLATE = ...`:

```python
SESSION_STATEMENT = re.compile(r"^\s*SET\b", re.IGNORECASE | re.MULTILINE)
```

After `test_sql_has_no_stray_percent_signs`:

```python
def test_sql_sets_no_session_parameters() -> None:
    # DSQL rejects most session parameters (statement_timeout among them). The
    # regex is anchored at line start so "OFFSET" or "SET" in a comment don't count.
    text = sql()

    assert SESSION_STATEMENT.search(text) is None
    assert "statement_timeout" not in text.lower()


def test_session_statement_check_ignores_offset() -> None:
    assert SESSION_STATEMENT.search("SELECT 1\nOFFSET 0\n") is None
    assert SESSION_STATEMENT.search("SELECT 1;\n  set statement_timeout = 0;\n")
```

- [ ] **Step 2: Run the contract tests**

Run: `$PY -m pytest tests/unit/ledgerlens_tools/test_query_contracts.py -q`
Expected: PASS. The SQL already has no session statements, so this test guards against regressions and won't fail first. To confirm the guard catches one, temporarily add a line `SET statement_timeout = 0;` at the top of the SQL file. Run the test and see `test_sql_sets_no_session_parameters` FAIL. Then remove the line.

- [ ] **Step 3: Update the SQL header**

In `L/queries/postgresql/list_card_transactions.sql`:
- Replace line 1 with `-- list_card_transactions (PostgreSQL dialect, runs on Aurora DSQL)`.
- Replace the two `R3` lines (25-26) with:

```sql
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster. DISTINCT ON,
--   translate(), strpos(), NULLS LAST and the binds are standard PostgreSQL, but
--   DSQL support and the plan under the 128 MiB per-query limit are unverified.
--   Column names follow docs/LATAM_Bank_ERD.md; smoke-test against a real cluster.
```

- [ ] **Step 4: Pin boto3 and update `gateway/tools/ledgerlens_tools/requirements.txt`**

Replace the whole file with:

```
# Runtime dependencies for every LedgerLens tool Lambda (shared asset).
#
# TODO(ledgerlens): R1 - no CDK yet: nothing packages or deploys this asset, no
#   Gateway target points at it, and the Lambda role has no dsql:DbConnect grant.
#   See the CDK spec (product design section 15).
# TODO(ledgerlens): R9 - psycopg[binary] ships native wheels. Build with a CDK
#   PythonFunction (Docker bundling, ARM64 Linux); plain Code.fromAsset won't work.
# TODO(ledgerlens): R13 - the Aurora DSQL client and its token methods first
#   shipped in boto3/botocore 1.35.74 (2024-12-03). The Lambda runtime's bundled
#   boto3 may be older, so the minimum is pinned and bundled with the asset. Drop
#   the pin once the CDK spec confirms the runtime's boto3 version.
boto3>=1.35.74,<2
psycopg[binary]>=3.2,<4
```

- [ ] **Step 5: Check that the local boto3 meets the pin**

Run: `$PY -c "import boto3; print(boto3.__version__); boto3.client('dsql', region_name='us-east-1').generate_db_connect_auth_token"`
Expected: a version ≥ 1.35.74 (1.40.29 at the time of writing) and no error. The method is only looked up, never called, so no AWS call is made.

- [ ] **Step 6: Lint and run the full suite**

Run the lint command, then `$PY -m pytest tests/unit/ledgerlens_tools -q`.
Expected: everything passes.

Final sweep:

```bash
grep -rn "TODO(ledgerlens): R" gateway/tools/ledgerlens_tools | sed 's/:.*TODO(ledgerlens): / /' | sort
```

Expected:
- R1 in the handler and `requirements.txt`
- R2, R6, R7 and R11 in `dsql.py`
- R3 and R8 in the SQL
- R6, R10 and R12 in `dsql_repository.py`
- R9 and R13 in `requirements.txt`
- R5 in the handler

No R2/R6/R7 should remain anywhere that mentions Aurora PostgreSQL, Secrets Manager or `DB_SECRET_ARN`.

- [ ] **Step 7: Commit**

```bash
git add tests/unit/ledgerlens_tools/test_query_contracts.py \
  gateway/tools/ledgerlens_tools/ledgerlens/queries/postgresql/list_card_transactions.sql \
  gateway/tools/ledgerlens_tools/requirements.txt
git commit -F - <<'EOF'
chore(tools): guard the SQL against session statements and pin boto3 for DSQL

DSQL rejects most SET parameters, so a contract test keeps them out of the
SQL. boto3>=1.35.74 is the first release with the dsql client (R13).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```
