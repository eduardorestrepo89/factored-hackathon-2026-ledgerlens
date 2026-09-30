"""DatabaseRepository adapter for PostgreSQL through psycopg 3."""

import logging
from collections.abc import Mapping
from typing import Any, Final

import psycopg

from ledgerlens.application.ports.database_repository import DatabaseRepository
from ledgerlens.application.ports.errors import (
    DataSourceConnectionError,
    QueryExecutionError,
    QueryTimeoutError,
)
from ledgerlens.utils.connectors.base import PsycopgConnector

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS: Final = 2


class PostgreSQLRepository(DatabaseRepository):
    """Run parameterised SQL on PostgreSQL and translate psycopg errors.

    A lost connection (``OperationalError``) is reset and the query retried once.
    That is safe because every query runs in a read-only session.
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
            QueryTimeoutError: The statement timeout cancelled the query.
            QueryExecutionError: Any other database error.
        """
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return self._run(query, params)
            except psycopg.errors.QueryCanceled as exc:
                # Subclass of OperationalError: must be caught first, never retried.
                raise QueryTimeoutError("Statement timeout exceeded") from exc
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
