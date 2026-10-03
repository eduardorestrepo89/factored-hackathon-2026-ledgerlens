"""Port for running parameterised queries against any database engine."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any


class DatabaseRepository(ABC):
    """Port for running parameterised queries against any database.

    Implementations are plain query executors: they know how to run SQL on one
    engine, not which SQL to run.
    """

    @abstractmethod
    def execute_query(
        self, query: str, params: Mapping[str, object]
    ) -> list[dict[str, Any]]:
        """Execute a parameterised query and return its rows.

        Args:
            query: SQL text with the engine's named placeholders.
            params: Values for the placeholders, keyed by name.

        Returns:
            Rows as dictionaries keyed by column name.

        Raises:
            DataSourceConnectionError: The connection couldn't be opened or was lost.
            QueryLimitExceededError: The query exceeded a database time or resource
                limit.
            QueryExecutionError: The database failed to run the query.
            DuplicateKeyError: The statement broke a unique constraint.
            WriteConflictError: The write kept conflicting with other transactions.
        """
