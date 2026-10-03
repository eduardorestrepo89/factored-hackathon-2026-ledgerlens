"""Port for loading SQL text by logical name."""

from abc import ABC, abstractmethod


class QueryProvider(ABC):
    """Port for loading SQL text by logical name for the configured dialect."""

    @abstractmethod
    def get(self, name: str) -> str:
        """Return the SQL text of the named query.

        Args:
            name: Logical query name, e.g. ``"get_session_context"``.

        Raises:
            QueryNotFoundError: No query with that name exists for the dialect.
        """
