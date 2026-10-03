"""Connection lifecycle shared by psycopg-based connectors."""

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import psycopg

from list_credit_cards_lambda.application.ports.errors import (
    DataSourceConnectionError,
)

logger = logging.getLogger(__name__)


class PsycopgConnector(ABC):
    """Cache one psycopg connection per Lambda container and reopen it when needed.

    Subclasses only say how to open a connection (``_open``). This class reopens
    it when it is missing, closed or older than ``max_age``, and wraps every
    open failure in DataSourceConnectionError.
    """

    def __init__(
        self,
        max_age: timedelta | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Configure the lifecycle without opening a connection.

        Args:
            max_age: Reopen connections at least this old; None disables the check.
            clock: Monotonic time in seconds; replaced in tests.
        """
        self._max_age: timedelta | None = max_age
        self._clock: Callable[[], float] = clock
        self._connection: psycopg.Connection[Any] | None = None
        self._opened_at: float = 0.0

    def connection(self) -> psycopg.Connection[Any]:
        """Return the cached connection, opening a new one if needed.

        A new one is opened when the cached connection is missing, closed or at
        least ``max_age`` old.

        Raises:
            DataSourceConnectionError: The connection couldn't be opened. The
                original error is chained as ``__cause__``.
        """
        if self._connection is not None and self._is_too_old():
            logger.info("Recycling a database connection older than %s", self._max_age)
            self.reset()
        if self._connection is None or self._connection.closed:
            try:
                connection = self._open()
            except Exception as exc:
                # Fixed message: hosts, users and tokens never reach the agent; the
                # chained cause (which may name the host) is only logged.
                raise DataSourceConnectionError(
                    "Could not open a database connection"
                ) from exc
            self._connection, self._opened_at = connection, self._clock()
        return self._connection

    def reset(self) -> None:
        """Close and drop the cached connection; errors while closing are ignored."""
        connection, self._connection = self._connection, None
        if connection is None:
            return
        try:
            connection.close()
        except Exception:
            logger.warning("Ignoring error while closing a connection", exc_info=True)

    @abstractmethod
    def _open(self) -> psycopg.Connection[Any]:
        """Open a new connection. Any exception is wrapped by connection()."""

    def _is_too_old(self) -> bool:
        """Return True when max_age is set and the connection has reached it."""
        if self._max_age is None:
            return False
        return self._clock() - self._opened_at >= self._max_age.total_seconds()
