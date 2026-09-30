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
