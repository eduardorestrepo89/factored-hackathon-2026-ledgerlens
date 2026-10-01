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
