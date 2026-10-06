"""Errors that data-access adapters raise; part of the port contract.

Adapters wrap driver exceptions in these (``raise ... from exc``) so that use
cases can react to failures without importing any infrastructure code. Their
messages are for logs only and are never shown to the agent.
"""


class DataAccessError(Exception):
    """Base class for every failure raised through a data-access port."""


class DataSourceConnectionError(DataAccessError):
    """The database connection couldn't be opened or was lost."""


class QueryLimitExceededError(DataAccessError):
    """The query exceeded a database time or resource limit."""


class QueryExecutionError(DataAccessError):
    """The database rejected or failed to run the query."""


class QueryNotFoundError(DataAccessError):
    """No SQL text exists for the requested query name."""


class DuplicateKeyError(DataAccessError):
    """The statement broke a unique constraint (SQLSTATE 23505)."""


class WriteConflictError(DataAccessError):
    """DSQL kept rejecting the write with a concurrency conflict (SQLSTATE 40001)."""
