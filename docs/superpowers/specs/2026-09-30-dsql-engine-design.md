# Aurora DSQL engine for the LedgerLens tools: Design

**Date:** 2026-09-30
**Status:** Draft, awaiting review
**Parent design:** [2026-09-29-list-card-transactions-lambda-design.md](2026-09-29-list-card-transactions-lambda-design.md)

---

## 1. Goal

Make Aurora DSQL the database for the LedgerLens tool Lambdas, starting with `list_card_transactions`, and **remove Aurora PostgreSQL**.

The hexagonal design stays as it is. The domain, the application use case, the SQL file and the handler don't change. What changes is the configuration, the connector, the repository's name and its error mapping, and the wiring.

### Success criteria
- `DB_ENGINE` is kept, defaults to `aurora_dsql`, and accepts only that value.
- The connector authenticates with an IAM token generated per connection. There's no Secrets Manager and no stored password.
- No connection sends a session parameter DSQL rejects (`statement_timeout`, `default_transaction_read_only`).
- DSQL's resource limits reach the agent as "narrow your search", not as "unavailable", and aren't retried.
- Connections are recycled before DSQL's 60-minute cut-off.
- All tests stay unit tests, with no database or AWS.

### Decisions taken during brainstorming
- **Aurora PostgreSQL is removed, not kept alongside DSQL.** `AuroraPostgreSQLConnector`, `SecretsClient`, `DB_SECRET_ARN`, `DB_STATEMENT_TIMEOUT_MS` and their tests go.
- **`PostgreSQLRepository` is renamed `DsqlRepository`**, and the engine-specific names follow DSQL (`DsqlConnector`, `DsqlSettings`, `DSQL_*` variables).
- **The SQL dialect folder stays `queries/postgresql/`.** DSQL speaks PostgreSQL. The engine (`aurora_dsql`) and the dialect (`postgresql`) are separate ideas, linked by one mapping.
- **Decision A: no per-query timeout.** DSQL rejects `statement_timeout`. We rely on the Lambda timeout and DSQL's own 300 s transaction limit (risk R10).
- **`PsycopgConnector` becomes an ABC holding the connection lifecycle.** It was a Protocol that every connector re-implemented. It already played the "cached connector base" role, so it takes the shared code rather than a new base class being added next to it.

---

## 2. Aurora DSQL facts the design relies on

From the AWS documentation (Aurora DSQL user guide):

| Topic | Fact |
|---|---|
| Authentication | IAM token from boto3 `client("dsql").generate_db_connect_auth_token(Hostname, Region)`, or `generate_db_connect_admin_auth_token` for the `admin` role. The token is signed locally (no network call), expires after 15 min by default and is only checked at connect time. |
| Connection | Database `postgres`, port 5432, TLS required. |
| Session parameters | Only `application_name`, `client_encoding`, `datestyle`, `extra_float_digits`, `intervalstyle`, `timezone`, `search_path`, the planner `enable_*` settings, `dsql.enable_batched_nestloop`, `disable_sync_create_index` and `role` can be set. Anything else fails with `setting configuration parameter "x" not supported`, so the whole connection would fail. |
| Database | UTF-8, C collation only, UTC, `REPEATABLE READ`. |
| Limits | Connections are closed after 60 min. A transaction may last at most 300 s (`54000`). A query may use at most 128 MiB (`53200`). 10,000 connections per cluster. 100 new connections/s, burst 1,000. |

---

## 3. Configuration (`delivery/settings.py`)

| Variable | Default | Meaning |
|---|---|---|
| `DB_ENGINE` | `aurora_dsql` | The only supported value. Any other value raises `ConfigurationError`. |
| `MAX_ROWS` | `25` | Row cap per call (unchanged). |
| `DSQL_CLUSTER_ENDPOINT` | (required) | Cluster host, for example `abc123.dsql.us-east-1.on.aws`. Rejected when empty, when it has a scheme (`https://`) or when it has a port (`:5432`). |
| `DSQL_DB_USER` | `ledgerlens_readonly` | Database role to connect as. `admin` switches to the admin token. |
| `AWS_REGION` | (required, set by Lambda) | Region used to sign the token. |

Removed: `DB_SECRET_ARN`, `DB_STATEMENT_TIMEOUT_MS`.

```python
class DatabaseEngine(str, Enum):
    """Database engines the tools can run on."""
    AURORA_DSQL = "aurora_dsql"


@dataclass(frozen=True)
class DatabaseSettings:
    """Settings shared by every tool Lambda, whatever the engine."""
    engine: DatabaseEngine
    max_rows: int

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "DatabaseSettings": ...


@dataclass(frozen=True)
class DsqlSettings:
    """Settings needed only to connect to Aurora DSQL."""
    cluster_endpoint: str
    region: str
    db_user: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "DsqlSettings": ...
```

- `DatabaseSettings` holds what every engine needs. `DsqlSettings` is read only by the DSQL branch of the connection block, so a future engine never fails on DSQL variables it doesn't use.
- `DB_ENGINE` is trimmed and lower-cased, as today. `SUPPORTED_ENGINES` and `DEFAULT_STATEMENT_TIMEOUT_MS` go; the enum is the list of supported engines.
- Every invalid value raises `ConfigurationError` with the variable's name and never with a secret.

---

## 4. Connectors (`utils/connectors/`)

### 4.1 `base.py`: `PsycopgConnector(ABC)`
The Protocol becomes an abstract base class that owns the cached-connection lifecycle. Subclasses only say how to open a connection.

```python
class PsycopgConnector(ABC):
    """Cache one psycopg connection per container and reopen it when needed."""

    def __init__(self, max_age: timedelta | None = None, clock: Callable[[], float] = time.monotonic) -> None: ...

    def connection(self) -> psycopg.Connection[Any]:
        """Return the cached connection, opening a new one if it is missing, closed or older than max_age.

        Raises:
            DataSourceConnectionError: The connection couldn't be opened.
        """

    def reset(self) -> None:
        """Close and drop the cached connection; errors while closing are ignored."""

    @abstractmethod
    def _open(self) -> psycopg.Connection[Any]:
        """Open a new connection. Any exception is wrapped by connection()."""
```

- `connection()` records the open time with `clock()`. When the connection is older than `max_age`, it calls `reset()` and opens a new one. `max_age=None` disables the check.
- `connection()` wraps any exception from `_open()` in `DataSourceConnectionError` with a fixed message and the original as `__cause__`, so no subclass has to, and no host or token reaches the message.
- `clock` is injectable so tests can move time without sleeping.

### 4.2 `dsql.py`: `DsqlConnector(PsycopgConnector)`
Replaces `aurora_postgresql.py`.

```python
class DsqlTokenClient(Protocol):
    """The part of the boto3 DSQL client the connector uses."""
    def generate_db_connect_auth_token(self, Hostname: str, Region: str) -> str: ...
    def generate_db_connect_admin_auth_token(self, Hostname: str, Region: str) -> str: ...


class DsqlConnector(PsycopgConnector):
    """Open psycopg connections to Aurora DSQL with a fresh IAM token each time."""

    MAX_AGE: Final = timedelta(minutes=55)

    def __init__(
        self,
        cluster_endpoint: str,
        region: str,
        db_user: str,
        dsql_client: DsqlTokenClient | None = None,
        connect: Callable[..., psycopg.Connection[Any]] = psycopg.connect,
    ) -> None: ...
```

`_open()`:
1. Creates the boto3 `dsql` client lazily on the first open, so building the connector never touches boto3 (`region_name=region`).
2. Generates a **new token on every open**: `generate_db_connect_admin_auth_token` when `db_user == "admin"`, otherwise `generate_db_connect_auth_token`, both with `Hostname=cluster_endpoint, Region=region`. A token is only checked at connect time, so a long-lived connection outlives its token without harm, and every reconnect gets a valid one.
3. Calls `connect(host=cluster_endpoint, port=5432, dbname="postgres", user=db_user, password=token, sslmode="require", client_encoding="utf8", connect_timeout=5, autocommit=True, row_factory=dict_row)`.
   - **No `options`.** DSQL rejects `statement_timeout` and `default_transaction_read_only`.
   - `client_encoding` is one of the allowed parameters and stays, so accented merchant names reach the server intact.
- `MAX_AGE` (55 min) recycles connections before DSQL closes them at 60 min. Most requests then never meet a dead connection.

### 4.3 Removed
`utils/connectors/aurora_postgresql.py`, `SecretsClient`, and `test_aurora_postgresql_connector.py`. Its R2, R6 and R7 `TODO(ledgerlens)` comments move to `dsql.py`, reworded as in §8.

---

## 5. Repository and errors

### 5.1 `infrastructure/repositories/dsql_repository.py`: `DsqlRepository(DatabaseRepository)`
`PostgreSQLRepository` is renamed and moved. The behaviour is unchanged except for the error mapping below. The catch order matters: psycopg treats SQLSTATE classes 53 and 54 as `OperationalError`, so they must be caught **before** the connection-loss branch.

| DSQL failure | SQLSTATE / psycopg class | Before | Now |
|---|---|---|---|
| Query uses more than 128 MiB | `53200` `OutOfMemory` | reset + retry → "unavailable" | **no retry** → `QueryLimitExceededError` |
| Transaction older than 300 s | `54000` `ProgramLimitExceeded` | reset + retry → "unavailable" | **no retry** → `QueryLimitExceededError` |
| Query cancelled by the server | `57014` `QueryCanceled` | `QueryTimeoutError` | `QueryLimitExceededError` |
| Connection cut, network failure | other `OperationalError` | reset + retry once | unchanged |
| Too many connections, rate limit, bad token | at connect (`53300`, `53400`, auth) | connector → `DataSourceConnectionError` | unchanged; wrapped once in `PsycopgConnector.connection()` |
| Anything else | other `psycopg.Error` | `QueryExecutionError` | unchanged |

- **Retrying stays safe** because the repository only runs `SELECT`s, in autocommit, as a role with `SELECT`-only grants. The docstring says this in place of "read-only session", which no longer exists.
- **No serialization handling.** DSQL's optimistic-concurrency conflicts (`40001`) only affect transactions that write.

### 5.2 Port error rename (`application/ports/errors.py`)
`QueryTimeoutError` → `QueryLimitExceededError`, docstring "The query exceeded a database time or resource limit." With no `statement_timeout`, "timeout" no longer describes it. The use case and the `DatabaseRepository.execute_query` docstring follow the rename.

### 5.3 Domain message (`domain/errors.py`)
`SearchTooBroadError` keeps its name. Its message becomes:

> "The transaction search was too broad for the database. Retry with a narrower date range or add a card or merchant filter."

---

## 6. Wiring (`delivery/dependencies/dependencies_builder.py`)

| Block | Function | Builds |
|---|---|---|
| Settings | `build_settings(env) -> DatabaseSettings` | Engine and `MAX_ROWS` |
| Settings | `build_dsql_settings(env) -> DsqlSettings` | DSQL connection settings |
| Connection | `build_connector(settings, env) -> PsycopgConnector` | `DsqlConnector` for `AURORA_DSQL`, built from `build_dsql_settings(env)` inside that branch; otherwise `ConfigurationError` |
| Adapters | `build_database_repository(engine, connector) -> DatabaseRepository` | `DsqlRepository` for `AURORA_DSQL`; otherwise `ConfigurationError` |
| Adapters | `build_query_provider(engine) -> QueryProvider` (cached) | `FileQueryProvider(QUERIES_ROOT / SQL_DIALECTS[engine])` |
| Use cases | `build_list_card_transactions_use_case(env)` | Unchanged except for passing `env` to `build_connector` |

```python
SQL_DIALECTS: Final[Mapping[DatabaseEngine, str]] = {DatabaseEngine.AURORA_DSQL: "postgresql"}
```

- The `ConfigurationError` fallbacks in `build_connector` and `build_database_repository` become unreachable while the enum has one member. They stay, so adding an engine to the enum without a branch fails loudly.
- The module docstring's "adding a database engine" paragraph is updated: a new enum member, a connector, a database repository, a `SQL_DIALECTS` entry and, when the dialect is new, a `queries/<dialect>/` folder.
- The handler, the eager cold-start connection and the `None`-on-bad-config behaviour don't change.

---

## 7. Tests (`tests/unit/ledgerlens_tools/`, pytest, TDD, no database or AWS)

Fakes are injected through constructors (`connect=`, `dsql_client=`, `clock=`).

| File | Change |
|---|---|
| `test_psycopg_connector.py` (new) | Base lifecycle through a `FakeConnector` that implements only `_open()`. Opens lazily and reuses the open connection. Reopens when the connection is closed, and when it is older than `max_age` (fake clock). No age check when `max_age=None`. `reset()` closes and ignores close errors. An `_open` failure comes out as `DataSourceConnectionError` with the original as `__cause__` and no host or token in the message. |
| `test_dsql_connector.py` (replaces `test_aurora_postgresql_connector.py`) | The exact `connect` kwargs: host, port 5432, dbname `postgres`, user, token as the password, `sslmode=require`, `client_encoding=utf8`, `connect_timeout=5`, autocommit, `dict_row`, and **no `options`**. A new token on every open. `admin` uses the admin token method, any other user the normal one, each with `Hostname` and `Region`. A token failure becomes `DataSourceConnectionError`. `MAX_AGE` is 55 min. Building the connector doesn't create a boto3 client. |
| `test_dsql_repository.py` (replaces `test_postgresql_repository.py`) | Existing cases under the new name. `OutOfMemory` and `ProgramLimitExceeded` → `QueryLimitExceededError` with one attempt and no reset. `QueryCanceled` → `QueryLimitExceededError`. |
| `test_settings.py` (new) | `DB_ENGINE` defaults to `aurora_dsql`; other values are rejected. `DSQL_CLUSTER_ENDPOINT` is required and rejected when empty, with a scheme or with a port. `DSQL_DB_USER` defaults to `ledgerlens_readonly`. `AWS_REGION` is required. `MAX_ROWS` keeps its checks. |
| `test_delivery_wiring.py` | `build_connector` returns a `DsqlConnector` built from the environment. `build_database_repository` returns a `DsqlRepository`. `build_query_provider(AURORA_DSQL)` resolves to `queries/postgresql/`. Bad config parametrized as `[{}, {"DB_ENGINE": "oracle"}, {"DB_ENGINE": "postgresql"}, <no endpoint>, <no region>]` → `None`. Eager-connect and failed cold-start tests unchanged. |
| `test_list_card_transactions_use_case.py` | `QueryTimeoutError` → `QueryLimitExceededError` in the port-error parametrization. |
| `test_errors.py` | Asserts the new `SearchTooBroadError` message. |
| `test_list_card_transactions_handler.py` | `wire()` uses `DatabaseEngine.AURORA_DSQL`. |
| `test_query_contracts.py` | New test: the SQL contains no session statements: no statement starting with `SET` (a word-bounded regex at line start, so `OFFSET` doesn't match) and no `statement_timeout`. |
| `ledgerlens_fakes.py` | `FakeConnector` implements only `_open()`. New `FakeDsqlTokenClient` records its calls and returns `token-1`, `token-2`, and so on. |

Not covered by tests: the SQL running on a real DSQL cluster (R3) and the IAM permission (R1).

---

## 8. Risks and pending work

Changes to the parent spec's risk table (§8 there), mirrored as `TODO(ledgerlens):` comments where each applies:

| # | Risk or pending item | Where the comment goes | Follow-up |
|---|---|---|---|
| R1 | **Infrastructure isn't written yet.** Also needed now: `dsql:DbConnect` on the cluster ARN for the Lambda role (`dsql:DbConnectAdmin` only if `DSQL_DB_USER=admin`). The Secrets Manager grant is no longer needed. | Handler docstring, `requirements.txt` header | CDK spec |
| R2 | **The DSQL cluster doesn't exist yet.** `DSQL_CLUSTER_ENDPOINT` has nothing real to point to. | `utils/connectors/dsql.py` | DSQL cluster and data-load spec |
| R3 | **The SQL is untested on DSQL.** `DISTINCT ON`, `translate()`, `strpos()`, `NULLS LAST` and `%(name)s` binds are standard PostgreSQL, but DSQL support and the plan under the 128 MiB limit are unverified. | SQL header | Smoke test against a real cluster |
| R6 | **The DB role is the only write guard.** DSQL rejects `default_transaction_read_only`. `ledgerlens_readonly` must be created with `SELECT`-only grants and mapped to the Lambda's IAM role (`AWS IAM GRANT`). If it's misconfigured, nothing else stops writes. | `utils/connectors/dsql.py`, `DsqlRepository` docstring | DSQL cluster spec |
| R7 | **Mostly resolved:** 10,000 connections per cluster. What's left is the 100 new connections/s rate (burst 1,000) during mass cold starts, which surfaces as "temporarily unavailable" after one retry. | `utils/connectors/dsql.py` | Cap `reservedConcurrentExecutions` if it ever matters |
| R10 | **No per-query timeout** (decision A). A slow query runs until the Lambda times out (DSQL caps it at 300 s), and the agent gets the platform's generic timeout instead of `SearchTooBroadError`. Set the Lambda timeout well under the agent's tool timeout. | `DsqlRepository` docstring | CDK spec |
| R11 | **`sslmode=require` doesn't verify the server certificate.** `verify-full` needs the Amazon root CA bundled with the Lambda. | `utils/connectors/dsql.py` | Hardening |
| R12 | **Server-side cancel on DSQL is unverified,** so the `QueryCanceled` mapping may never fire. Harmless either way. | `DsqlRepository` | Smoke test |
| R13 | **The DSQL token methods need a recent boto3.** The Lambda runtime's bundled boto3 may predate the `dsql` client. Either check the runtime version or pin the minimum release in `requirements.txt`; the implementation plan records the exact version. | `requirements.txt` header | CDK spec |

R4, R5, R8 and R9 are unchanged.

---

## 9. Scope

**In scope:** everything in §3–§7, the parent spec updated so it doesn't contradict this one, and the `TODO(ledgerlens)` comments in §8.

**Out of scope:**
- CDK and IAM (`dsql:DbConnect`, environment variables, Lambda timeout)
- VPC and PrivateLink endpoints for DSQL
- Creating the cluster, the `ledgerlens_readonly` role and its grants, and loading the data
- Integration tests against a real cluster
- The `aurora-dsql-python-connector` package and connection pooling: tokens are generated by hand with boto3 to avoid a new dependency
