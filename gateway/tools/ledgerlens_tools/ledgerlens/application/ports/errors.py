"""Errors that data-access adapters raise; part of the port contract.

Adapters wrap driver exceptions in these (``raise ... from exc``) so that use
cases can react to failures without importing any infrastructure code. Their
messages are for logs only and are never shown to the agent.
"""


class DataAccessError(Exception):
    """Base class for every failure raised through a data-access port."""


class DataSourceConnectionError(DataAccessError):
    """The database connection couldn't be opened or was lost."""


class QueryTimeoutError(DataAccessError):
    """The statement was cancelled by the database statement timeout."""


class QueryExecutionError(DataAccessError):
    """The database rejected or failed to run the query."""


class QueryNotFoundError(DataAccessError):
    """No SQL text exists for the requested query name."""
