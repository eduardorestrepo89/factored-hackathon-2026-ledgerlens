# `list_card_transactions` Lambda: Design

**Date:** 2026-09-29
**Status:** Approved. Implementation plan: `docs/superpowers/plans/2026-09-29-list-card-transactions-lambda.md`
**Parent design:** [LEDGERLENS_PRODUCT_DESIGN.md](../../LEDGERLENS_PRODUCT_DESIGN.md), §7.4

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
- The handler in `delivery` calls `build_dependencies()`. The connection is **global and created outside the handler**.
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
    │   ├── repositories/postgresql_repository.py   ← PostgreSQLRepository(DatabaseRepository)
    │   └── queries/file_query_provider.py          ← FileQueryProvider(QueryProvider)
    ├── utils/
    │   ├── connectors/base.py                      ← PsycopgConnector (Protocol)
    │   └── connectors/aurora_postgresql.py         ← AuroraPostgreSQLConnector
    ├── queries/
    │   └── postgresql/list_card_transactions.sql
    └── delivery/
        ├── settings.py                             ← DatabaseSettings.from_env, ConfigurationError
        ├── database.py                             ← engine wiring shared by every tool
        ├── presenters/card_transactions.py         ← result → agent JSON
        ├── dependencies/list_card_transactions.py  ← build_dependencies(connector, settings)
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
- `delivery/dependencies/<tool>.py` with its own `build_dependencies(connector, settings)`
- `gateway/tools/<tool>/tool_spec.json`

The ports, repository, query provider and connector are reused. Each tool deploys as **its own Lambda**, built from the same asset with a different handler, so each gets its own IAM role, timeout and Cedar action. Each handler imports `build_dependencies` from its own tool's dependencies module, so the function name is the same everywhere.

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
            DataSourceConnectionError, QueryTimeoutError, QueryExecutionError
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
- `transaction_status` on the entity is a `str`, not the enum. The database can hold values outside the three filter values (see Risks).

### 3.3 Use case (`application/use_cases/list_card_transactions.py`)
```python
class ListCardTransactionsUseCase:
    """Search a customer's card transactions through a database-agnostic repository."""

    QUERY_NAME: Final = "list_card_transactions"

    def __init__(self, repository: DatabaseRepository, queries: QueryProvider, max_rows: int = 25) -> None: ...

    def execute(self, filters: TransactionFilters) -> CardTransactionsResult:
        """Load the query, run it with the filters and return at most max_rows transactions.

        Raises:
            DataSourceUnavailableError, SearchTooBroadError, TransactionLookupError, DataIntegrityError
        """
```

Steps:
1. Load the SQL with `self._queries.get(QUERY_NAME)`.
2. Build the params: every filter field (the enum becomes its `.value`) plus `limit = max_rows + 1`.
3. Call `self._repository.execute_query(sql, params)`.
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
- The merchant filter uses `strpos(lower(t.merchant_name), lower(%(merchant)s::text)) > 0` instead of `ILIKE`, so wildcard characters in the customer's text match literally and no `%%` escaping is needed.
- A header comment in the file lists its parameters and the assumptions still to be checked. The file must contain no `%` outside placeholders (psycopg would read it as a placeholder); a unit test enforces this.

### 3.6 `tool_spec.json`
One tool, `list_card_transactions`:
- The description comes from parent design §7.4.
- `inputSchema` properties: `customer_id` (required), `card_last4`, `date_from`, `date_to`, `merchant`, `min_amount`, `max_amount`, and `status` (an enum).

---

## 4. Errors

### 4.1 Port errors (`application/ports/errors.py`)
Adapters raise these errors, wrapping the original exception (`raise ... from exc`). The base class is `DataAccessError(Exception)`.

| Error | Raised by | When |
|---|---|---|
| `DataSourceConnectionError` | Repository | The connection can't be opened or was lost (`psycopg.OperationalError`, and connector failures) |
| `QueryTimeoutError` | Repository | Statement timeout (`psycopg.errors.QueryCanceled`) |
| `QueryExecutionError` | Repository | Any other `psycopg.Error` |
| `QueryNotFoundError` | Query provider | No `<name>.sql` exists for the dialect |

They live under `application/ports/` because they're part of the port contract. The use case catches them without importing `infrastructure`.

### 4.2 Domain errors (`domain/errors.py`)
The base is `DomainError(Exception)` with `message: str`. The message is agent-facing and says what to do next.

| Domain error | Translated from | Message |
|---|---|---|
| `InvalidInputError(field, reason)` | `TransactionFilters` validation | "Invalid value for '{field}': {reason}. Ask the customer to confirm and retry." |
| `DataSourceUnavailableError` | `DataSourceConnectionError` | "Transaction data is temporarily unavailable. Tell the customer and offer to retry in a moment or hand off to a human agent." |
| `SearchTooBroadError` | `QueryTimeoutError` | "The transaction search took too long. Retry with a narrower date range or add a card or merchant filter." |
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

### 5.1 Connector (`utils/connectors/aurora_postgresql.py`)
`AuroraPostgreSQLConnector(secret_arn: str, statement_timeout_ms: int, secrets_client: SecretsClient | None = None, connect: Callable[..., psycopg.Connection] = psycopg.connect)` (`connect` is injectable for tests):
- `connection() -> psycopg.Connection` returns the cached connection. If it's missing or closed, it opens a new one:
  - reads the secret (host, port, dbname, username, password)
  - `sslmode="require"`, `connect_timeout=5`, `autocommit=True`, `row_factory=dict_row`
  - `options="-c statement_timeout=<ms> -c default_transaction_read_only=on"`
- `reset() -> None` closes and drops the cached connection.
- Any failure to open raises `DataSourceConnectionError`.

### 5.2 Repository (`infrastructure/repositories/postgresql_repository.py`)
`PostgreSQLRepository(connector: PsycopgConnector)` implements `execute_query`:
- It gets `connector.connection()`, runs the query with the params and returns `fetchall()`.
- On `psycopg.OperationalError` it calls `connector.reset()` and **retries once**. A second failure raises `DataSourceConnectionError`.
- Other `psycopg` errors map as shown in §4.1.

### 5.3 Wiring (`delivery/dependencies/list_card_transactions.py`)
- Reads the environment variables:

  | Variable | Default | Meaning |
  |---|---|---|
  | `DB_ENGINE` | (required) | `postgresql` is the only supported value in this iteration |
  | `DB_SECRET_ARN` | (required) | Secrets Manager secret with the DB credentials |
  | `DB_STATEMENT_TIMEOUT_MS` | `5000` | Per-statement timeout |
  | `MAX_ROWS` | `25` | Row cap per call |

- `build_dependencies(connector: PsycopgConnector, settings: DatabaseSettings) -> ListCardTransactionsUseCase` connects the pieces (settings are parsed once, at module load, by `DatabaseSettings.from_env`):
  - the connector
  - `PostgreSQLRepository`
  - `FileQueryProvider(<package>/queries/<DB_ENGINE>)`
  - the use case
- An unknown `DB_ENGINE` raises a configuration error at startup.

### 5.4 Global connection (in the handler module)
- When the module loads (outside `handler`), it creates the connector and calls `connector.connection()` **eagerly** inside `try/except`.
  - On failure it logs and continues, so the Lambda init doesn't crash.
  - The first query retries the connection lazily. If it fails again, the agent gets `DataSourceUnavailableError`.
- The handler calls `build_dependencies(connector, settings)` to get the use case. Building it is cheap (plain objects, the SQL is cached by the query provider), and the expensive part, the connection, stays global.

---

## 6. Tests (`tests/unit/ledgerlens_tools/`, pytest, TDD, no database or AWS)

| File | Covers |
|---|---|
| `test_transaction_filters.py` | Every validation rule and default in §3.2, using a fixed `today` |
| `test_list_card_transactions_use_case.py` | Mapping rows to entities, the exact SQL name and params sent, truncation (26 rows → 25 plus `truncated=True`), each port error → the right domain error and message, bad row → `DataIntegrityError`, empty result |
| `test_file_query_provider.py` | Reads the file, caches it (a second call doesn't re-read), missing file → `QueryNotFoundError` (`tmp_path`) |
| `test_postgresql_repository.py` | Each psycopg exception → the right port error, one retry on `OperationalError` followed by success, a second failure raises; rows returned (mocked connector and cursor) |
| `test_list_card_transactions_handler.py` | `build_dependencies` wiring (unknown `DB_ENGINE` fails), success format, `DomainError` → `{"error": msg}`, unexpected exception → generic message with no internals, wrong tool name, cold start with a failed connection still returns a clean error |
| `conftest.py` | Adds `gateway/tools/ledgerlens_tools` to `sys.path`; shared fakes (`FakeRepository`, `FakeQueryProvider`) |

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
- CDK: a `PythonFunction` per tool (ARM64, Python 3.13), `gateway.addLambdaTarget(...)`, VPC, subnets and security groups, `secret.grantRead`, environment variables
- Aurora PostgreSQL cluster, schema and data load, and a read-only DB user
- Cedar policy for `list-card-transactions-target___list_card_transactions`
- Integration tests of the SQL against a real PostgreSQL database
- Removing the sample tool

---

## 8. Risks and pending work

These are also left as `TODO(ledgerlens):` comments in the code, at the place each one applies.

| # | Risk or pending item | Where the comment goes | Follow-up |
|---|---|---|---|
| R1 | **Infrastructure isn't written yet.** No CDK Lambda, Gateway target, VPC or secret grant, so the tool can't be deployed or called by the agent yet. | `delivery/list_card_transactions_handler.py` module docstring, `requirements.txt` header | CDK spec (parent design §15) |
| R2 | **Aurora doesn't exist.** `DB_SECRET_ARN` has no real secret to point to. | `utils/connectors/aurora_postgresql.py` | Aurora and data-load spec |
| R3 | **The SQL is untested against a real database.** Column names match the ERD, but syntax and performance aren't verified. | `queries/postgresql/list_card_transactions.sql` header | Integration tests with a PostgreSQL container |
| R4 | **`transaction_status` values are assumed** (`Approved`/`Declined`/`Pending`) and not confirmed with the data dictionary (parent design Q1). | `domain/value_objects/transaction_filters.py` (`TransactionStatus`), the SQL header | Confirm with the data dictionary; update the enum and `tool_spec.json` |
| R5 | **`customer_id` trusts the tool input.** Authorization relies on Cedar matching it to the token's `customer_id` claim. That policy and the claim don't exist yet (parent design §5 and §10). | Handler module docstring | Cedar and pre-token claim spec |
| R6 | **Read-only DB user assumed.** `default_transaction_read_only=on` guards against writes, but the DB user itself should be read-only. | Connector | Aurora spec: create `ledgerlens_readonly` |
| R7 | **Connection scaling.** One connection per warm container. Many concurrent containers could exhaust Aurora's connection limit. Accepted for the demo; no mitigation will be built. | Connector | If this goes beyond a demo: cap `reservedConcurrentExecutions` per tool Lambda, then RDS Proxy (no code change, only the secret's host). The Data API is an alternative as a new repository adapter. |
| R8 | **Duplicate rows (about 2%)** are removed at query time with `DISTINCT ON`. Cleaning the data would remove the need. | SQL header | Data-load spec |
| R9 | **`psycopg[binary]` needs an ARM64 Linux build.** Packaging requires Docker bundling (`PythonFunction`); a plain `Code.fromAsset` won't work. | `requirements.txt` header | CDK spec |
