"""Port for loading SQL text by logical name."""

from abc import ABC, abstractmethod


class QueryProvider(ABC):
    """Port for loading SQL text by logical name for the configured dialect."""

    @abstractmethod
    def get(self, name: str) -> str:
        """Return the SQL text of the named query.

        Args:
            name: Logical query name, e.g. ``"classify_call_type"``.

        Raises:
            QueryNotFoundError: No query with that name exists for the dialect.
        """
