"""Dependency builder: the only place where this tool's objects get built.

The handler never builds anything itself. At cold start it calls
build_block_credit_card_use_case once and reuses the result on every warm
invocation. That is safe because every object built here is stateless between
requests: request data travels through method arguments, never through
attributes. Keep it that way. The connection inside the connector is the only
shared state, and it heals itself (reconnect when closed or too old, reset and
retry once on a lost connection).

The module is organised in blocks:

- Settings: environment variables to typed settings.
- Clock: AS_OF to the tool's notion of "now".
- Connection: the engine-specific connector (built without connecting).
- Adapters: the engine-specific database repository and query provider.
- Use case: build_block_credit_card_use_case, which builds the tool's whole
  graph.

Adding a database engine means adding a DatabaseEngine member, a branch to the
connection and adapter blocks (with its connector and database repository), a
SQL_DIALECTS entry and, when the dialect is new, a ``queries/<dialect>/`` folder.
The builder serves the block_credit_card tool only; every other tool has
its own folder and its own builder.
"""

import logging
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Final

from block_credit_card_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from block_credit_card_lambda.application.ports.query_provider import QueryProvider
from block_credit_card_lambda.application.use_cases.block_credit_card import (
    BlockCreditCardUseCase,
)
from block_credit_card_lambda.delivery.settings import (
    ClockSettings,
    ConfigurationError,
    DatabaseEngine,
    DatabaseSettings,
    DsqlSettings,
)
from block_credit_card_lambda.infrastructure.queries.file_query_provider import (
    FileQueryProvider,
)
from block_credit_card_lambda.infrastructure.repositories.dsql_repository import (
    DsqlRepository,
)
from block_credit_card_lambda.utils.connectors.base import PsycopgConnector
from block_credit_card_lambda.utils.connectors.dsql import DsqlConnector

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
        logger.exception("Invalid AS_OF for block_credit_card")
        return None


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

    Cached so the container builds the provider once per engine.

    Raises:
        ConfigurationError: The engine has no SQL dialect.
    """
    dialect = SQL_DIALECTS.get(engine)
    if dialect is None:
        raise ConfigurationError(f"No SQL dialect for DB_ENGINE {engine!r}")
    return FileQueryProvider(QUERIES_ROOT / dialect)


# --- Use cases ---------------------------------------------------------------


def build_block_credit_card_use_case(
    env: Mapping[str, str],
) -> BlockCreditCardUseCase | None:
    """Build the block_credit_card use case and its whole graph. Never raises.

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
        use_case = BlockCreditCardUseCase(
            database_repository=build_database_repository(settings.engine, connector),
            query_provider=build_query_provider(settings.engine),
        )
    except ConfigurationError:
        logger.exception("Invalid database configuration for block_credit_card")
        return None
    try:
        connector.connection()
    except Exception:
        logger.warning(
            "Cold-start database connection failed; the first request will retry",
            exc_info=True,
        )
    return use_case
