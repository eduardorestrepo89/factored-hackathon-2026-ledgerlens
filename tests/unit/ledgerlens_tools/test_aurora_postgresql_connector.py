"""Tests for AuroraPostgreSQLConnector: connect args, caching, reset, failures."""

import json
from collections.abc import Mapping
from typing import Any

import psycopg
import pytest
from ledgerlens.application.ports.errors import DataSourceConnectionError
from ledgerlens.utils.connectors.aurora_postgresql import AuroraPostgreSQLConnector
from ledgerlens.utils.connectors.base import PsycopgConnector
from ledgerlens_fakes import FakeConnection, FakeConnector
from psycopg.rows import dict_row

pytestmark = pytest.mark.unit

SECRET_ARN = "arn:aws:secretsmanager:us-east-1:111111111111:secret:ledgerlens-db"
SECRET = {
    "host": "db.cluster.local",
    "port": "5432",
    "dbname": "ledgerlens",
    "username": "ledgerlens_readonly",
    "password": "not-a-real-password",  # noqa: S105
}


class FakeSecretsClient:
    """Secrets Manager double returning a JSON SecretString."""

    def __init__(
        self, secret: Mapping[str, Any] | None = None, error: Exception | None = None
    ) -> None:
        """Return ``secret`` or raise ``error``."""
        self.secret = secret if secret is not None else SECRET
        self.error = error
        self.requested: list[str] = []

    def get_secret_value(self, *, SecretId: str) -> dict[str, Any]:  # noqa: N803
        """Record the ARN and return the secret payload."""
        self.requested.append(SecretId)
        if self.error is not None:
            raise self.error
        return {"SecretString": json.dumps(self.secret)}


class RecordingConnect:
    """psycopg.connect double that records kwargs."""

    def __init__(self, error: Exception | None = None) -> None:
        """Raise ``error`` on every call if given."""
        self.error = error
        self.calls: list[dict[str, Any]] = []
        self.connections: list[FakeConnection] = []

    def __call__(self, **kwargs: Any) -> FakeConnection:
        """Record kwargs and return a new connection double."""
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        connection = FakeConnection()
        self.connections.append(connection)
        return connection


def make_connector(
    secrets: FakeSecretsClient | None = None, connect: RecordingConnect | None = None
) -> tuple[AuroraPostgreSQLConnector, FakeSecretsClient, RecordingConnect]:
    """Build a connector wired to doubles."""
    secrets = secrets or FakeSecretsClient()
    connect = connect or RecordingConnect()
    connector = AuroraPostgreSQLConnector(
        secret_arn=SECRET_ARN,
        statement_timeout_ms=5000,
        secrets_client=secrets,
        connect=connect,
    )
    return connector, secrets, connect


@pytest.mark.parametrize("connector_class", [AuroraPostgreSQLConnector, FakeConnector])
def test_connector_explicitly_implements_the_psycopg_connector_protocol(
    connector_class: type,
) -> None:
    # Explicit inheritance makes type checkers verify the connector against
    # the protocol instead of relying on matching method names.
    assert PsycopgConnector in connector_class.__mro__


def test_opens_a_read_only_tls_connection_from_the_secret() -> None:
    connector, secrets, connect = make_connector()

    connection = connector.connection()

    assert connection is connect.connections[0]
    assert secrets.requested == [SECRET_ARN]
    assert connect.calls == [
        {
            "host": "db.cluster.local",
            "port": 5432,
            "dbname": "ledgerlens",
            "user": "ledgerlens_readonly",
            "password": "not-a-real-password",
            "sslmode": "require",
            "client_encoding": "utf8",
            "connect_timeout": 5,
            "autocommit": True,
            "row_factory": dict_row,
            "options": "-c statement_timeout=5000 -c default_transaction_read_only=on",
        }
    ]


def test_port_defaults_to_5432_when_the_secret_has_none() -> None:
    secret = {k: v for k, v in SECRET.items() if k != "port"}
    connector, _, connect = make_connector(secrets=FakeSecretsClient(secret))

    connector.connection()

    assert connect.calls[0]["port"] == 5432


def test_reuses_the_cached_connection() -> None:
    connector, _, connect = make_connector()

    assert connector.connection() is connector.connection()
    assert len(connect.calls) == 1


def test_reconnects_when_the_cached_connection_is_closed() -> None:
    connector, _, connect = make_connector()
    first = connector.connection()
    first.closed = True

    second = connector.connection()

    assert second is not first
    assert len(connect.calls) == 2


def test_reset_closes_and_drops_the_connection() -> None:
    connector, _, connect = make_connector()
    first = connector.connection()

    connector.reset()

    assert first.closed is True
    assert connector.connection() is not first
    assert len(connect.calls) == 2


def test_reset_without_a_connection_is_a_no_op() -> None:
    connector, _, connect = make_connector()

    connector.reset()

    assert connect.calls == []


def test_reset_ignores_errors_while_closing() -> None:
    connector, _, _ = make_connector()
    connection = connector.connection()

    def broken_close() -> None:
        raise psycopg.OperationalError("already gone")

    connection.close = broken_close  # type: ignore[method-assign]

    connector.reset()


@pytest.mark.parametrize(
    ("secrets", "connect"),
    [
        (FakeSecretsClient(error=RuntimeError("AccessDenied")), RecordingConnect()),
        (FakeSecretsClient(secret={"host": "db"}), RecordingConnect()),
        (FakeSecretsClient(), RecordingConnect(error=psycopg.OperationalError("x"))),
    ],
)
def test_any_failure_to_open_raises_data_source_connection_error(
    secrets: FakeSecretsClient, connect: RecordingConnect
) -> None:
    connector, _, _ = make_connector(secrets=secrets, connect=connect)

    with pytest.raises(DataSourceConnectionError) as caught:
        connector.connection()

    assert caught.value.__cause__ is not None
