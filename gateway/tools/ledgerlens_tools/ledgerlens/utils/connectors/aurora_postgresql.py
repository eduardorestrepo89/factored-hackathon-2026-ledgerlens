"""Aurora PostgreSQL connector: one cached psycopg connection per Lambda container.

TODO(ledgerlens): R2 - no Aurora cluster or secret exists yet; DB_SECRET_ARN has
  nothing real to point at until the Aurora and data-load spec lands.
TODO(ledgerlens): R6 - default_transaction_read_only=on guards against writes, but
  the secret should belong to a read-only DB user (ledgerlens_readonly).
TODO(ledgerlens): R7 - one connection per warm container, so many concurrent
  containers could exhaust Aurora's max_connections. Accepted for the demo; no
  mitigation is built. Beyond a demo: cap reservedConcurrentExecutions per tool
  Lambda, then RDS Proxy (only the secret's host changes). The RDS Data API is an
  alternative, as a new DatabaseRepository adapter.
"""

import json
import logging
from collections.abc import Callable, Mapping
from typing import Any, Final, Protocol

import boto3
import psycopg
from psycopg.rows import dict_row

from ledgerlens.application.ports.errors import DataSourceConnectionError

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT_SECONDS: Final = 5
_DEFAULT_PORT: Final = 5432


class SecretsClient(Protocol):
    """The part of the boto3 Secrets Manager client the connector uses."""

    def get_secret_value(self, *, SecretId: str) -> Mapping[str, Any]:  # noqa: N803
        """Return the secret payload; ``SecretString`` holds the JSON credentials."""
        ...


class AuroraPostgreSQLConnector:
    """Open and cache a read-only psycopg connection to Aurora PostgreSQL.

    Credentials come from a Secrets Manager secret with the standard RDS keys
    (host, port, dbname, username, password). They are read on every (re)connect,
    so a rotated password is picked up after a reset.
    """

    def __init__(
        self,
        secret_arn: str,
        statement_timeout_ms: int,
        secrets_client: SecretsClient | None = None,
        connect: Callable[..., psycopg.Connection[Any]] = psycopg.connect,
    ) -> None:
        """Configure the connector without opening a connection.

        Args:
            secret_arn: ARN of the Secrets Manager secret with the credentials.
            statement_timeout_ms: Server-side timeout applied to every statement.
            secrets_client: Secrets Manager client; created lazily if omitted.
            connect: Connection factory; replaced in tests.
        """
        self._secret_arn: str = secret_arn
        self._statement_timeout_ms: int = statement_timeout_ms
        self._secrets_client: SecretsClient | None = secrets_client
        self._connect: Callable[..., psycopg.Connection[Any]] = connect
        self._connection: psycopg.Connection[Any] | None = None

    def connection(self) -> psycopg.Connection[Any]:
        """Return the cached connection, opening a new one if missing or closed.

        Raises:
            DataSourceConnectionError: The secret or the database couldn't be
                reached.
        """
        if self._connection is None or self._connection.closed:
            self._connection = self._open()
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

    def _open(self) -> psycopg.Connection[Any]:
        """Read the credentials and open a new connection.

        Raises:
            DataSourceConnectionError: Any failure, chained to the original error.
        """
        try:
            credentials = self._read_secret()
            return self._connect(
                host=credentials["host"],
                port=int(credentials.get("port", _DEFAULT_PORT)),
                dbname=credentials["dbname"],
                user=credentials["username"],
                password=credentials["password"],
                sslmode="require",
                connect_timeout=_CONNECT_TIMEOUT_SECONDS,
                autocommit=True,
                row_factory=dict_row,
                options=(
                    f"-c statement_timeout={self._statement_timeout_ms} "
                    "-c default_transaction_read_only=on"
                ),
            )
        except Exception as exc:
            raise DataSourceConnectionError(
                "Could not open a connection to Aurora PostgreSQL"
            ) from exc

    def _read_secret(self) -> Mapping[str, Any]:
        """Fetch and parse the credentials JSON from Secrets Manager."""
        if self._secrets_client is None:
            self._secrets_client = boto3.client("secretsmanager")
        response = self._secrets_client.get_secret_value(SecretId=self._secret_arn)
        credentials: Mapping[str, Any] = json.loads(response["SecretString"])
        return credentials
