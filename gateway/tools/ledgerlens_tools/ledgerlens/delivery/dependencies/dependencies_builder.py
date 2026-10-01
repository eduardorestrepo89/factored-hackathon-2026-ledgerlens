"""Dependency builder: the only place where LedgerLens objects get built.

Handlers never build anything themselves. At cold start each handler calls its
tool's block below once and reuses the result on every warm invocation. That is
safe because every object built here is stateless between requests: request
data travels through method arguments, never through attributes. Keep it that
way. The connection inside the connector is the only shared state, and it heals
itself (reconnect when closed, reset and retry once on a lost connection).

The module is organised in blocks:

- Settings: environment variables to typed settings.
- Connection: the engine-specific connector (built without connecting).
- Adapters: the engine-specific database repository and query provider.
- Use cases: one function per tool, which builds that tool's whole graph.

Adding a database engine means adding a branch to the connection and adapter
blocks, a connector, a database repository and a ``queries/<engine>/`` folder.
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
from ledgerlens.delivery.settings import ConfigurationError, DatabaseSettings
from ledgerlens.infrastructure.queries.file_query_provider import FileQueryProvider
from ledgerlens.infrastructure.repositories.postgresql_repository import (
    PostgreSQLRepository,
)
from ledgerlens.utils.connectors.aurora_postgresql import AuroraPostgreSQLConnector
from ledgerlens.utils.connectors.base import PsycopgConnector

logger = logging.getLogger(__name__)

QUERIES_ROOT: Final = Path(__file__).resolve().parents[2] / "queries"


# --- Settings ----------------------------------------------------------------


def build_settings(env: Mapping[str, str]) -> DatabaseSettings:
    """Read the database settings from the Lambda environment.

    Raises:
        ConfigurationError: A required variable is missing or a value is invalid.
    """
    return DatabaseSettings.from_env(env)


# --- Connection --------------------------------------------------------------


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


# --- Adapters ----------------------------------------------------------------


def build_database_repository(
    engine: str, connector: PsycopgConnector
) -> DatabaseRepository:
    """Create the database repository adapter for ``engine`` around ``connector``.

    Raises:
        ConfigurationError: The engine isn't supported.
    """
    if engine == "postgresql":
        return PostgreSQLRepository(connector)
    raise ConfigurationError(f"Unsupported DB_ENGINE {engine!r}")


@cache
def build_query_provider(engine: str) -> QueryProvider:
    """Return the query provider for ``engine``'s SQL dialect folder.

    Cached so every tool in the container shares one provider per engine.
    """
    return FileQueryProvider(QUERIES_ROOT / engine)


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
        connector = build_connector(settings)
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
