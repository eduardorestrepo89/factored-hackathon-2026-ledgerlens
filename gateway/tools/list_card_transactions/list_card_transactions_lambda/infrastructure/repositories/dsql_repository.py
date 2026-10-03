"""DatabaseRepository adapter for Aurora DSQL through psycopg 3.

TODO(ledgerlens): R6 - the DB role is the only write guard. DSQL rejects
  default_transaction_read_only, so ll_read must keep SELECT-only
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

from list_card_transactions_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from list_card_transactions_lambda.application.ports.errors import (
    DataSourceConnectionError,
    QueryExecutionError,
    QueryLimitExceededError,
)
from list_card_transactions_lambda.utils.connectors.base import PsycopgConnector

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS: Final = 2
# Query limits: SQLSTATE classes 53 (insufficient resources, such as 53200 for
# DSQL's 128 MiB per query) and 54 (program limit exceeded, such as 54000 for
# its 300 s per transaction), plus 57014 (cancelled). psycopg makes them all
# OperationalError subclasses, so they are told apart by SQLSTATE.
_LIMIT_SQLSTATE_CLASSES: Final = ("53", "54")
_CANCELED_SQLSTATE: Final = "57014"
# Too many connections and connection rate exceeded: the connection may recover.
_CONNECTION_LIMIT_SQLSTATES: Final = frozenset({"53300", "53400"})


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
            QueryLimitExceededError: The query exceeded a database resource or
                program limit (SQLSTATE class 53 or 54, except the connection
                limits), or the server cancelled it.
            QueryExecutionError: Any other database error.
        """
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return self._run(query, params)
            except psycopg.OperationalError as exc:
                if _is_query_limit(exc):
                    # Never retried: the same query would fail the same way.
                    raise QueryLimitExceededError(
                        "The query exceeded a database limit"
                    ) from exc
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


def _is_query_limit(exc: psycopg.Error) -> bool:
    """Return True when ``exc`` is a query limit rather than a connection fault."""
    sqlstate = exc.sqlstate or ""
    if sqlstate in _CONNECTION_LIMIT_SQLSTATES:
        return False
    return sqlstate == _CANCELED_SQLSTATE or sqlstate[:2] in _LIMIT_SQLSTATE_CLASSES
