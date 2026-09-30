"""Connector contract shared by psycopg-based repositories."""

from typing import Any, Protocol

import psycopg


class PsycopgConnector(Protocol):
    """Owns one psycopg connection's lifecycle for a Lambda container."""

    def connection(self) -> psycopg.Connection[Any]:
        """Return an open connection, opening a new one if needed.

        Raises:
            DataSourceConnectionError: The connection couldn't be opened.
        """
        ...

    def reset(self) -> None:
        """Close and forget the cached connection so the next call reconnects."""
        ...
