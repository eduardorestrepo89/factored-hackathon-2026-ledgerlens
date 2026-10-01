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
