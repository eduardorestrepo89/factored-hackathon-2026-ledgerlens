# `list_card_transactions` Lambda: Design

**Date:** 2026-09-29
**Status:** Approved. Implementation plan: `docs/superpowers/plans/2026-09-29-list-card-transactions-lambda.md`
**Parent design:** [LEDGERLENS_PRODUCT_DESIGN.md](../../LEDGERLENS_PRODUCT_DESIGN.md), §7.4
**Updated 2026-09-30:** Aurora DSQL replaces Aurora PostgreSQL. See [2026-09-30-dsql-engine-design.md](2026-09-30-dsql-engine-design.md); §2, §4, §5, §6, §7 and §8 below already describe the DSQL version.
**Updated 2026-10-01:** the code now lives in `gateway/tools/list_card_transactions/list_card_transactions_lambda/`. See [2026-10-01-self-contained-tool-folders-design.md](2026-10-01-self-contained-tool-folders-design.md).

---

## 1. Goal

Build the first LedgerLens Gateway tool, `list_card_transactions`. It lets the agent search a customer's card transactions with optional filters.

This first tool also sets the pattern every later tool follows: a **shared core with hexagonal (clean-architecture) layers**, so tools don't depend on any particular database. Adding a tool means adding a use case, a query file, a handler and a `tool_spec.json`. Adding a database engine means adding a connector, a repository and a query dialect folder. The domain and application layers never change for either.

### Success criteria
- Layers depend only inward: `domain` ← `application` ← (`infrastructure`, `utils`, `delivery`).
- `application` never imports `psycopg`, `boto3` or anything from `infrastructure`.
- Every infrastructure failure reaches the agent as a clear, actionable domain message, never as a raw exception string.
- Unit tests cover all four layers without a database or AWS.
- Heavy type hints everywhere. Every module, class and public function has a docstring saying what it does.

### Requirements given by the user
- Folders: `domain`, `application`, `infrastructure`, `delivery`, `utils` (for connectors) and `queries` (SQL out of the code).
- A database repository **port**. The repository's only method is `execute_query`, and it receives the **connector in its constructor**.
- The use case:
  - receives the repository **typed as the port**
  - loads the query by name
  - passes the query to the repository
- `delivery/dependencies/dependencies_builder.py` is the **only** place that builds objects (settings, connector, adapters, use case). The handler module calls it once at load time and keeps the ready use case globally, so warm invocations reuse it.
- The use case converts infrastructure errors into **domain errors** with clear messages for the agent.
- Responses follow the repo's Gateway tool format (see `gateway/tools/sample_tool/sample_tool_lambda.py`).

---

## 2. Structure

```
gateway/tools/ledgerlens_tools/                     ← CDK asset root, shared by every tool Lambda
├── requirements.txt                                ← psycopg[binary] (boto3 is in the Lambda runtime)
└── ledgerlens/
    ├── __init__.py
    ├── domain/
    │   ├── entities/card_transaction.py            ← CardTransaction, CardTransactionsResult
    │   ├── value_objects/transaction_filters.py    ← TransactionFilters, TransactionStatus
    │   └── errors.py                               ← DomainError hierarchy
    ├── application/
    │   ├── ports/database_repository.py            ← DatabaseRepository (ABC)
    │   ├── ports/query_provider.py                 ← QueryProvider (ABC)
    │   ├── ports/errors.py                         ← port errors raised by adapters
    │   └── use_cases/list_card_transactions.py     ← ListCardTransactionsUseCase
    ├── infrastructure/
    │   ├── repositories/dsql_repository.py         ← DsqlRepository(DatabaseRepository)
    │   └── queries/file_query_provider.py          ← FileQueryProvider(QueryProvider)
    ├── utils/
    │   ├── connectors/base.py                      ← PsycopgConnector (ABC, connection lifecycle)
    │   └── connectors/dsql.py                      ← DsqlConnector(PsycopgConnector)
    ├── queries/
    │   └── postgresql/list_card_transactions.sql   ← PostgreSQL dialect, used by Aurora DSQL
    └── delivery/
        ├── settings.py                             ← DatabaseEngine, DatabaseSettings, DsqlSettings,
        │                                              ConfigurationError
        ├── presenters/card_transactions.py         ← result → agent JSON
        ├── dependencies/dependencies_builder.py    ← build_settings, build_connector,
        │                                              build_database_repository, build_query_provider,
        │                                              build_list_card_transactions_use_case
        └── list_card_transactions_handler.py       ← handler(event, context)

gateway/tools/list_card_transactions/tool_spec.json ← agent-facing name, description, inputSchema
tests/unit/ledgerlens_tools/                        ← conftest.py adds gateway/tools/ledgerlens_tools to sys.path
```

- Every sub-package has an `__init__.py`.
- The `ledgerlens/` package inside the asset root keeps imports unambiguous: `from ledgerlens.domain.errors import ...`.
- The Lambda handler string is `ledgerlens/delivery/list_card_transactions_handler.handler`.

### Adding more tools later
Each tool adds files to the same core:
- a domain entity (and a value object if it has inputs)
- `application/use_cases/<tool>.py`
- `queries/postgresql/<tool>.sql`
- `delivery/<tool>_handler.py`
- a `build_<tool>_use_case(env)` function in the use cases block of `delivery/dependencies/dependencies_builder.py`
- `gateway/tools/<tool>/tool_spec.json`

The ports, repository, query provider and connector are reused. Each tool deploys as **its own Lambda**, built from the same asset with a different handler, so each gets its own IAM role, timeout and Cedar action. Each handler calls only its own tool's builder, so a Lambda never builds (or fails on) another tool's dependencies. A tool with extra settings gets its own settings class, built in its block.

---

## 3. Contracts

### 3.1 Ports (`application/ports/`)
```python
class DatabaseRepository(ABC):
    """Port for running parameterised queries against any database."""

    @abstractmethod
    def execute_query(self, query: str, params: Mapping[str, object]) -> list[dict[str, Any]]:
        """Execute a parameterised query and return the rows as dictionaries keyed by column name.

        Raises:
            DataSourceConnectionError, QueryLimitExceededError, QueryExecutionError
        """


class QueryProvider(ABC):
    """Port for loading SQL text by logical name for the configured dialect."""

    @abstractmethod
    def get(self, name: str) -> str:
        """Return the SQL text of the named query.

        Raises:
            QueryNotFoundError
        """
```

### 3.2 Domain (`domain/`)
```python
class TransactionStatus(str, Enum):
    APPROVED = "Approved"
    DECLINED = "Declined"
    PENDING = "Pending"
    REVERSED = "Reversed"


@dataclass(frozen=True)
class TransactionFilters:
    """Validated search criteria for a customer's card transactions."""
    customer_id: str
    date_from: date
    date_to: date
    card_last4: str | None = None
    merchant: str | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    status: TransactionStatus | None = None

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any], today: date) -> "TransactionFilters":
        """Parse untyped tool input, apply the defaults and validate. Raises InvalidInputError."""
```

**Validation rules.** Each failure raises `InvalidInputError(field, reason)`.

| Field | Rule |
|---|---|
| `customer_id` | Required, a string, not blank after trimming |
| `date_to` | ISO date. Default: `today` (UTC, passed in so tests are deterministic) |
| `date_from` | ISO date. Default: `date_to - 30 days`. Must be ≤ `date_to` |
| Date range | `date_to - date_from` ≤ 180 days |
| `card_last4` | Exactly 4 digits |
| `merchant` | Trimmed; empty becomes `None`; ≤ 100 characters |
| `min_amount` / `max_amount` | Parsed as `Decimal`, ≥ 0; `min_amount` ≤ `max_amount` when both are given |
| `status` | One of `TransactionStatus` |

```python
@dataclass(frozen=True)
class CardTransaction:
    """A single card transaction as returned to the agent."""
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
    """The outcome of a transaction search, capped at a maximum number of rows."""
    transactions: tuple[CardTransaction, ...]
    truncated: bool
```

- Nullable fields (including `currency` and `transaction_status`) are `| None` because the dataset has about 5% nulls in nullable columns. A null there is returned as JSON null, not treated as a data-integrity error.
- `transaction_status` on the entity is a `str`, not the enum, so an unexpected value in the data never fails the call. The enum holds every value in the dataset (`Approved`, `Declined`, `Pending`, `Reversed`).
- Categorical columns are returned exactly as stored. `transaction_country` holds country names, not ISO codes, and the data mixes `Mexico` and `México`; no filter uses it, so nothing depends on normalising it.

### 3.3 Use case (`application/use_cases/list_card_transactions.py`)
```python
class ListCardTransactionsUseCase:
    """Search a customer's card transactions through a database-agnostic repository."""

    QUERY_NAME: Final = "list_card_transactions"

    def __init__(self, database_repository: DatabaseRepository, query_provider: QueryProvider, max_rows: int = 25) -> None: ...

    def execute(self, filters: TransactionFilters) -> CardTransactionsResult:
        """Load the query, run it with the filters and return at most max_rows transactions.

        Raises:
            DataSourceUnavailableError, SearchTooBroadError, TransactionLookupError, DataIntegrityError
        """
```

Steps:
1. Load the SQL with `self._query_provider.get(QUERY_NAME)`.
2. Build the params: every filter field (the enum becomes its `.value`) plus `limit = max_rows + 1`.
3. Call `self._database_repository.execute_query(sql, params)`.
4. Map each row to a `CardTransaction`. A `KeyError`, `TypeError` or `ValueError` becomes `DataIntegrityError`.
5. Return `CardTransactionsResult(transactions=rows[:max_rows], truncated=len(rows) > max_rows)`.

**Why the truncation flag:** without it, the agent can't tell "this is everything" from "more exist". It could then wrongly tell a customer a charge doesn't exist, or skip charges during the fraud-scoping step. Fetching one extra row detects this without a `COUNT(*)`.

### 3.4 Output to the agent
Success, in the repo's Gateway format:
```json
{"content": [{"type": "text", "text": "{\"transactions\": [...], \"count\": 3, \"truncated\": false}"}]}
```
Each transaction contains:
- `transaction_date` as an ISO 8601 string
- `amount` as a 2-decimal **string** (no float rounding)
- the rest of the fields as-is, with `null` kept for missing values

Error: `{"error": "<agent-facing message>"}`.

### 3.5 SQL (`queries/postgresql/list_card_transactions.sql`)
- Based on the query in parent design §7.4.
- psycopg named placeholders: `%(customer_id)s`.
- Optional filters are cast so the type is known even when the value is `NULL`, for example `(%(card_last4)s::text IS NULL OR RIGHT(p.product_number, 4) = %(card_last4)s)`.
- Duplicate rows are removed with `DISTINCT ON (transaction_id)` inside a sub-query. The outer query orders by `transaction_date DESC` and applies `LIMIT %(limit)s`.
- Partitions are pruned with `process_date BETWEEN %(date_from)s AND %(date_to)s`.
- Credit cards only: `p.product_type = 'Tarjeta Crédito'`, the exact filter `list_credit_cards` uses. *Amended 2026-10-03: the query had no product filter, so transactions on accounts, loans and debit cards came back under last-4s that `list_credit_cards` never shows (persona P07 got 7 rows instead of 4).* Unit tests check the literal and that the file is NFC UTF-8 without a BOM.
- The merchant filter uses `strpos(...) > 0` instead of `ILIKE`, so wildcard characters in the customer's text match literally and no `%%` escaping is needed.
- The merchant filter ignores accents as well as case, because merchant names carry them (`Clínica Médica`, `Óptica Visión`, `Servicios Públicos`) and customers often type without them. Both sides go through the same `lower(translate(x, '<accented>', '<plain>'))`. `translate()` maps upper- and lower-case Spanish and Portuguese accents first, because `lower()` can leave non-ASCII letters alone under a C collation. It is core PostgreSQL, so no `unaccent` extension is needed (Aurora DSQL supports none). Unit tests check that both sides use the same mapping, that each pair only strips the accent, and that it covers every accented letter in the dataset's merchant names.
- The connector pins `client_encoding=utf8` so accented text reaches the server intact.
- A header comment in the file lists its parameters and the assumptions still to be checked. The file must contain no `%` outside placeholders (psycopg would read it as a placeholder); a unit test enforces this.

### 3.6 `tool_spec.json`
One tool, `list_card_transactions`:
- The description comes from parent design §7.4.
- `inputSchema` properties: `customer_id` (required), `card_last4`, `date_from`, `date_to`, `merchant`, `min_amount`, `max_amount`, and `status` (an enum of every `TransactionStatus` value; a unit test keeps them in sync).

---

## 4. Errors

### 4.1 Port errors (`application/ports/errors.py`)
Adapters raise these errors, wrapping the original exception (`raise ... from exc`). The base class is `DataAccessError(Exception)`.

| Error | Raised by | When |
|---|---|---|
| `DataSourceConnectionError` | Repository, connector | The connection can't be opened or was lost (`psycopg.OperationalError` other than the limits below, and connector failures) |
| `QueryLimitExceededError` | Repository | The query hit a database time or resource limit: `OutOfMemory` (`53200`, 128 MiB), `ProgramLimitExceeded` (`54000`, 300 s transaction age) or `QueryCanceled` (`57014`). Never retried. |
| `QueryExecutionError` | Repository | Any other `psycopg.Error` |
| `QueryNotFoundError` | Query provider | No `<name>.sql` exists for the dialect |

They live under `application/ports/` because they're part of the port contract. The use case catches them without importing `infrastructure`.

### 4.2 Domain errors (`domain/errors.py`)
The base is `DomainError(Exception)` with `message: str`. The message is agent-facing and says what to do next.

| Domain error | Translated from | Message |
|---|---|---|
| `InvalidInputError(field, reason)` | `TransactionFilters` validation | "Invalid value for '{field}': {reason}. Ask the customer to confirm and retry." |
| `DataSourceUnavailableError` | `DataSourceConnectionError` | "Transaction data is temporarily unavailable. Tell the customer and offer to retry in a moment or hand off to a human agent." |
| `SearchTooBroadError` | `QueryLimitExceededError` | "The transaction search was too broad for the database. Retry with a narrower date range or add a card or merchant filter." |
| `TransactionLookupError` | `QueryExecutionError`, `QueryNotFoundError` | "Transactions can't be retrieved right now due to an internal error. Don't retry; offer a hand-off to a human agent." |
| `DataIntegrityError` | Mapping a row fails | "Transaction data came back in an unexpected format. Don't retry; offer a hand-off to a human agent." |

An empty result is **not** an error. It returns `count: 0`.

### 4.3 Handler behavior (`delivery/list_card_transactions_handler.py`)
1. Check the tool name from `context.client_context.custom["bedrockAgentCoreToolName"]`, removing the `<target>___` prefix. A mismatch returns `{"error": ...}`, the same as the sample tool.
2. Build `TransactionFilters.from_raw(event, today=<UTC today>)`.
3. `result = use_case.execute(filters)`, then serialize (§3.4).
4. Error handling:
   - `DomainError`: log at WARNING, return `{"error": err.message}`.
   - Any other `Exception`: `logger.exception(...)`, return `{"error": "Unexpected internal error listing transactions. Offer a hand-off to a human agent."}`.
   - **Never** return `str(e)`. It could leak SQL, hosts or driver details to the model. The sample tool does this; we deliberately don't.

---

## 5. Connection lifecycle and configuration

### 5.1 Connectors (`utils/connectors/`)
Details in the DSQL spec, §4.
- `PsycopgConnector(ABC)` in `base.py` owns the lifecycle:
  - `connection()` returns the cached connection and opens a new one when it's missing, closed or older than `max_age`.
  - `reset()` closes and drops it.
  - Any failure in the abstract `_open()` is wrapped in `DataSourceConnectionError`.
- `DsqlConnector(cluster_endpoint, region, db_user, dsql_client=None, connect=psycopg.connect)` in `dsql.py` implements `_open()`. `MAX_AGE` is 55 minutes, which recycles the connection before DSQL closes it at 60. Each open does two things:
  - It generates a fresh IAM token with boto3's `dsql` client. `admin` uses the admin token method.
  - It connects with `port=5432`, `dbname="postgres"`, `sslmode="require"`, `client_encoding="utf8"`, `connect_timeout=5`, `autocommit=True` and `row_factory=dict_row`. It passes **no** `options`, because DSQL rejects `statement_timeout` and `default_transaction_read_only`.

### 5.2 Repository (`infrastructure/repositories/dsql_repository.py`)
`DsqlRepository(connector: PsycopgConnector)` implements `execute_query`:
- It gets `connector.connection()`, runs the query with the params and returns `fetchall()`.
- DSQL limit errors (`OutOfMemory`, `ProgramLimitExceeded`, `QueryCanceled`) are caught **first** and raise `QueryLimitExceededError` without a retry.
- On any other `psycopg.OperationalError` it calls `connector.reset()` and **retries once**. A second failure raises `DataSourceConnectionError`. The retry is safe because the role can only `SELECT`.
- Other `psycopg` errors map as shown in §4.1.

### 5.3 Wiring (`delivery/dependencies/dependencies_builder.py`)
This module owns all object construction, in labelled blocks:

| Block | Function | Builds |
|---|---|---|
| Settings | `build_settings(env) -> DatabaseSettings` | Engine and `MAX_ROWS` |
| Settings | `build_dsql_settings(env) -> DsqlSettings` | DSQL connection settings |
| Connection | `build_connector(settings, env) -> PsycopgConnector` | `DsqlConnector`, without connecting |
| Adapters | `build_database_repository(engine, connector) -> DatabaseRepository` | `DsqlRepository` |
| Adapters | `build_query_provider(engine) -> QueryProvider` (cached) | `FileQueryProvider(<package>/queries/<SQL_DIALECTS[engine]>)`; `aurora_dsql` maps to `postgresql` |
| Use cases | `build_list_card_transactions_use_case(env) -> ListCardTransactionsUseCase \| None` | The whole graph for this tool |

| Variable | Default | Meaning |
|---|---|---|
| `DB_ENGINE` | `aurora_dsql` | The only supported value |
| `DSQL_CLUSTER_ENDPOINT` | (required) | Cluster host; no scheme, no port |
| `DSQL_DB_USER` | `ledgerlens_readonly` | Database role; `admin` switches to the admin token |
| `AWS_REGION` | (required, set by Lambda) | Region used to sign the token |
| `MAX_ROWS` | `25` | Row cap per call |

- An unknown `DB_ENGINE` or invalid variable raises `ConfigurationError` inside the builders. The use case builder catches it, logs it and returns `None`.

### 5.4 Cold start and warm reuse
- The handler module runs `USE_CASE = build_list_card_transactions_use_case(os.environ)` once, at load time, and builds nothing itself.
- The use case builder opens the connection **eagerly** inside `try/except`.
  - On failure it logs and continues, so the Lambda init doesn't crash.
  - The first query retries the connection lazily. If it fails again, the agent gets `DataSourceUnavailableError`.
- `USE_CASE is None` (bad configuration) makes every request return `DataSourceUnavailableError`'s message.
- Reusing the whole graph across warm invocations is safe because every built object is **stateless between requests**: request data travels through `execute(filters)`, never through attributes. The connection is the only shared state, and it heals itself (reconnect when closed, reset and retry once). New code must keep this rule.

---

## 6. Tests (`tests/unit/ledgerlens_tools/`, pytest, TDD, no database or AWS)

| File | Covers |
|---|---|
| `test_transaction_filters.py` | Every validation rule and default in §3.2, using a fixed `today` |
| `test_list_card_transactions_use_case.py` | Mapping rows to entities, the exact SQL name and params sent, truncation (26 rows → 25 plus `truncated=True`), each port error → the right domain error and message, bad row → `DataIntegrityError`, empty result |
| `test_file_query_provider.py` | Reads the file, caches it (a second call doesn't re-read), missing file → `QueryNotFoundError` (`tmp_path`) |
| `test_dsql_repository.py` | Each psycopg exception → the right port error, DSQL limit errors not retried, one retry on `OperationalError` followed by success, a second failure raises; rows returned (mocked connector and cursor) |
| `test_psycopg_connector.py` | The base connection lifecycle: lazy open, reuse, reopen when closed or older than `max_age`, `reset()`, failures wrapped in `DataSourceConnectionError` |
| `test_dsql_connector.py` | The exact connect arguments (no `options`), a fresh token per open, admin vs normal token method, token failure → `DataSourceConnectionError` |
| `test_settings.py` | `DatabaseSettings` and `DsqlSettings` defaults and validation |
| `test_delivery_wiring.py` | Each builder block, the use case wired end to end over a fake connector, `MAX_ROWS` honoured, eager connection, failed cold-start connection still yields a working use case, bad configuration → `None` |
| `test_list_card_transactions_handler.py` | Success format, `DomainError` → `{"error": msg}`, unexpected exception → generic message with no internals, wrong tool name, cold start with a failed connection still returns a clean error, missing configuration → unavailable message |
| `conftest.py` | Adds `gateway/tools/ledgerlens_tools` to `sys.path`; shared fakes in `ledgerlens_fakes.py` (`FakeDatabaseRepository`, `FakeQueryProvider`, `FakeConnector`) |

Tests are marked `@pytest.mark.unit`, following `tests/pytest.ini`.

---

## 7. Scope

**In scope:**
- All code in §2–§5
- `list_card_transactions.sql`
- `tool_spec.json`
- `requirements.txt`
- the unit tests in §6

**Out of scope (later specs):**
- CDK: a `PythonFunction` per tool (ARM64, Python 3.13), `gateway.addLambdaTarget(...)`, the `dsql:DbConnect` grant, VPC/PrivateLink if needed, environment variables
- Aurora DSQL cluster, schema and data load, and the read-only `ledgerlens_readonly` role
- Cedar policy for `list-card-transactions-target___list_card_transactions`
- Integration tests of the SQL against a real DSQL cluster
- Removing the sample tool

---

## 8. Risks and pending work

These are also left as `TODO(ledgerlens):` comments in the code, at the place each one applies.

| # | Risk or pending item | Where the comment goes | Follow-up |
|---|---|---|---|
| R1 | **Infrastructure isn't written yet.** No CDK Lambda, Gateway target or `dsql:DbConnect` grant (`dsql:DbConnectAdmin` only if `DSQL_DB_USER=admin`), so the tool can't be deployed or called by the agent yet. | `delivery/list_card_transactions_handler.py` module docstring, `requirements.txt` header | CDK spec (parent design §15) |
| R2 | **The DSQL cluster doesn't exist yet.** `DSQL_CLUSTER_ENDPOINT` has nothing real to point to. | `utils/connectors/dsql.py` | DSQL cluster and data-load spec |
| R3 | **The SQL is untested on DSQL.** Column names match the ERD. `DISTINCT ON`, `translate()`, `strpos()`, `NULLS LAST` and `%(name)s` binds are standard PostgreSQL, but DSQL support and the plan under the 128 MiB query limit aren't verified. | `queries/postgresql/list_card_transactions.sql` header | Smoke test against a real cluster |
| R4 | ~~`transaction_status` values are assumed~~ **Resolved:** confirmed against the dataset's categorical values (`Approved`, `Declined`, `Pending`, `Reversed`). | `TransactionStatus`, `tool_spec.json` | — |
| R5 | **`customer_id` trusts the tool input.** Authorization relies on Cedar matching it to the token's `customer_id` claim. That policy and the claim don't exist yet (parent design §5 and §10). | Handler module docstring | Cedar and pre-token claim spec |
| R6 | **The DB role is the only write guard.** DSQL rejects `default_transaction_read_only`. `ledgerlens_readonly` must be created with `SELECT`-only grants and mapped to the Lambda's IAM role (`AWS IAM GRANT`). If it's misconfigured, nothing else stops writes. | `utils/connectors/dsql.py`, `DsqlRepository` docstring | DSQL cluster spec |
| R7 | **Mostly resolved:** DSQL allows 10,000 connections per cluster. What's left is the 100 new connections/s rate (burst 1,000) during mass cold starts, which surfaces as "temporarily unavailable" (a failed connect isn't retried within the request). | `utils/connectors/dsql.py` | Cap `reservedConcurrentExecutions` per tool Lambda if it ever matters |
| R8 | **Duplicate rows (about 2%)** are removed at query time with `DISTINCT ON`. Cleaning the data would remove the need. | SQL header | Data-load spec |
| R9 | **`psycopg[binary]` needs an ARM64 Linux build.** Packaging requires Docker bundling (`PythonFunction`); a plain `Code.fromAsset` won't work. | `requirements.txt` header | CDK spec |
| R10 | **No per-query timeout.** DSQL rejects `statement_timeout`. A slow query runs until the Lambda times out (DSQL caps it at 300 s), and the agent gets the platform's generic timeout instead of `SearchTooBroadError`. | `DsqlRepository` docstring | CDK spec: Lambda timeout well under the agent's tool timeout |
| R11 | **`sslmode=require` doesn't verify the server certificate.** `verify-full` needs the Amazon root CA bundled with the Lambda. | `utils/connectors/dsql.py` | Hardening |
| R12 | **Server-side cancel on DSQL is unverified,** so the `QueryCanceled` mapping may never fire. Harmless either way. | `DsqlRepository` | Smoke test |
| R13 | **The DSQL token methods need a recent boto3.** The Lambda runtime's bundled boto3 may predate the `dsql` client. | `requirements.txt` header | CDK spec: check the runtime version or pin the minimum release |
