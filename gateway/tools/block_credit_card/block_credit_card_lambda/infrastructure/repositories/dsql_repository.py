"""DatabaseRepository adapter for Aurora DSQL through psycopg 3, for a write tool.

Every statement runs in autocommit, so each one is its own transaction. Compared
with the read tools' copy, two rules are added:

- SQLSTATE 40001 (DSQL's optimistic-concurrency conflict) is retried on the same
  connection after a short jittered sleep, at most _MAX_CONFLICT_ATTEMPTS times
  in all, then raised as WriteConflictError.
- SQLSTATE 23505 (unique violation) becomes DuplicateKeyError and is never
  retried.

The reset-and-retry-once after a lost connection is kept. For writes it is safe
only because every write this tool runs is idempotent: a guarded UPDATE, or an
INSERT whose key is derived from its content (write tools spec section 6.3). A
retry after a commit whose reply was lost then changes nothing, or hits 23505.
Keep every new write idempotent.

ll_write's grants are the only limit on what this tool can change: DSQL rejects
default_transaction_read_only.

TODO(ledgerlens): R10 - no per-query timeout: DSQL rejects statement_timeout. A
  slow query runs until the Lambda times out (DSQL caps a transaction at 300 s).
  Keep the Lambda timeout well under the agent's tool timeout.
TODO(ledgerlens): R12 - server-side cancel on DSQL is unverified, so the
  QueryCanceled mapping may never fire. Harmless either way.
"""

import logging
import random
import time
from collections.abc import Callable, Mapping
from typing import Any, Final

import psycopg

from block_credit_card_lambda.application.ports.database_repository import (
    DatabaseRepository,
)
from block_credit_card_lambda.application.ports.errors import (
    DataSourceConnectionError,
    DuplicateKeyError,
    QueryExecutionError,
    QueryLimitExceededError,
    WriteConflictError,
)
from block_credit_card_lambda.utils.connectors.base import PsycopgConnector

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS: Final = 2
# DSQL fails a conflicting commit with 40001; the statement, its own transaction
# in autocommit, is simply run again.
_MAX_CONFLICT_ATTEMPTS: Final = 3
_CONFLICT_SQLSTATE: Final = "40001"
_UNIQUE_VIOLATION_SQLSTATE: Final = "23505"
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

    A lost connection (``OperationalError``) is reset and the statement retried
    once. A write conflict (40001) is retried on the same connection. A statement
    that breaks a DSQL limit or a unique constraint is never retried: it would
    fail the same way.
    """

    def __init__(
        self,
        connector: PsycopgConnector,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Use ``connector`` for the connection; ``sleep`` is replaced in tests."""
        self._connector: PsycopgConnector = connector
        self._sleep: Callable[[float], None] = sleep

    def execute_query(
        self, query: str, params: Mapping[str, object]
    ) -> list[dict[str, Any]]:
        """Execute the statement and return all rows as dictionaries.

        Raises:
            DataSourceConnectionError: The connection failed twice, or couldn't be
                opened.
            WriteConflictError: DSQL reported a write conflict on every attempt.
            DuplicateKeyError: The statement broke a unique constraint.
            QueryLimitExceededError: The query exceeded a database resource or
                program limit (SQLSTATE class 53 or 54, except the connection
                limits), or the server cancelled it.
            QueryExecutionError: Any other database error.
        """
        connection_failures = 0
        conflicts = 0
        while True:
            try:
                return self._run(query, params)
            except psycopg.OperationalError as exc:
                if exc.sqlstate == _CONFLICT_SQLSTATE:
                    conflicts += 1
                    if conflicts == _MAX_CONFLICT_ATTEMPTS:
                        raise WriteConflictError(
                            "The write kept conflicting with other transactions"
                        ) from exc
                    logger.warning(
                        "Write conflict (40001); retrying, attempt %d of %d",
                        conflicts + 1,
                        _MAX_CONFLICT_ATTEMPTS,
                    )
                    self._sleep(random.uniform(0.05, 0.15) * conflicts)
                    continue
                if _is_query_limit(exc):
                    # Never retried: the same query would fail the same way.
                    raise QueryLimitExceededError(
                        "The query exceeded a database limit"
                    ) from exc
                self._connector.reset()
                connection_failures += 1
                if connection_failures == _MAX_ATTEMPTS:
                    raise DataSourceConnectionError(
                        "Database connection failed after a retry"
                    ) from exc
                logger.warning(
                    "Database connection failed; reconnecting and retrying once",
                    exc_info=True,
                )
            except psycopg.Error as exc:
                if exc.sqlstate == _UNIQUE_VIOLATION_SQLSTATE:
                    raise DuplicateKeyError(
                        "The statement broke a unique constraint"
                    ) from exc
                raise QueryExecutionError(
                    "The database failed to run the query"
                ) from exc

    def _run(self, query: str, params: Mapping[str, object]) -> list[dict[str, Any]]:
        """Run the statement once on the connector's current connection."""
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
