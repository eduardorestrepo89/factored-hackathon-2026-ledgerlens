"""Tests for DsqlConnector: connect args, IAM tokens, recycling, failures."""

from datetime import timedelta
from typing import Any

import list_card_transactions_lambda.utils.connectors.dsql as dsql_module
import psycopg
import pytest
from botocore.exceptions import NoCredentialsError, UnknownServiceError
from list_card_transactions_lambda.application.ports.errors import (
    DataSourceConnectionError,
)
from list_card_transactions_lambda.utils.connectors.dsql import DsqlConnector
from psycopg.rows import dict_row

from .fakes import FakeClock, FakeConnection, FakeDsqlTokenClient

pytestmark = pytest.mark.unit

ENDPOINT = "abc123.dsql.us-east-1.on.aws"
REGION = "us-east-1"
READONLY_USER = "ledgerlens_readonly"


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
    db_user: str = READONLY_USER,
    tokens: FakeDsqlTokenClient | None = None,
    connect: RecordingConnect | None = None,
    clock: FakeClock | None = None,
) -> tuple[DsqlConnector, FakeDsqlTokenClient, RecordingConnect]:
    """Build a connector wired to doubles."""
    tokens = tokens or FakeDsqlTokenClient()
    connect = connect or RecordingConnect()
    connector = DsqlConnector(
        cluster_endpoint=ENDPOINT,
        region=REGION,
        db_user=db_user,
        dsql_client=tokens,
        connect=connect,
        clock=clock or FakeClock(),
    )
    return connector, tokens, connect


def test_opens_a_tls_connection_with_an_iam_token_and_no_session_options() -> None:
    connector, _, connect = make_connector()

    connection = connector.connection()

    assert connection is connect.connections[0]
    # Exact equality: DSQL rejects statement_timeout and
    # default_transaction_read_only, so no "options" may be sent.
    assert connect.calls == [
        {
            "host": ENDPOINT,
            "port": 5432,
            "dbname": "postgres",
            "user": READONLY_USER,
            "password": "token-1",
            "sslmode": "require",
            "client_encoding": "utf8",
            "connect_timeout": 5,
            "autocommit": True,
            "row_factory": dict_row,
        }
    ]


def test_a_custom_role_uses_the_normal_token_method() -> None:
    connector, tokens, _ = make_connector()

    connector.connection()

    assert tokens.calls == [("generate_db_connect_auth_token", ENDPOINT, REGION)]


def test_admin_uses_the_admin_token_method() -> None:
    connector, tokens, connect = make_connector(db_user="admin")

    connector.connection()

    assert tokens.calls == [("generate_db_connect_admin_auth_token", ENDPOINT, REGION)]
    assert connect.calls[0]["user"] == "admin"


def test_every_open_uses_a_new_token() -> None:
    connector, _, connect = make_connector()
    connector.connection()

    connector.reset()
    connector.connection()

    assert [call["password"] for call in connect.calls] == ["token-1", "token-2"]


def test_reuses_the_open_connection_without_a_new_token() -> None:
    connector, tokens, _ = make_connector()

    assert connector.connection() is connector.connection()
    assert len(tokens.calls) == 1


def test_recycles_connections_after_55_minutes_with_a_fresh_token() -> None:
    assert DsqlConnector.MAX_AGE == timedelta(minutes=55)
    clock = FakeClock()
    connector, _, connect = make_connector(clock=clock)
    first = connector.connection()

    clock.advance(timedelta(minutes=54, seconds=59))
    assert connector.connection() is first

    clock.advance(timedelta(seconds=1))
    second = connector.connection()

    assert second is not first
    assert first.closed is True
    assert [call["password"] for call in connect.calls] == ["token-1", "token-2"]


def test_building_the_connector_does_not_create_a_boto3_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[object] = []
    monkeypatch.setattr(
        dsql_module.boto3, "client", lambda *a, **k: created.append((a, k))
    )

    DsqlConnector(cluster_endpoint=ENDPOINT, region=REGION, db_user=READONLY_USER)

    assert created == []


def test_creates_one_boto3_dsql_client_for_the_region_on_first_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokens = FakeDsqlTokenClient()
    created: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_client(*args: object, **kwargs: object) -> FakeDsqlTokenClient:
        created.append((args, kwargs))
        return tokens

    monkeypatch.setattr(dsql_module.boto3, "client", fake_client)
    connector = DsqlConnector(
        cluster_endpoint=ENDPOINT,
        region=REGION,
        db_user=READONLY_USER,
        connect=RecordingConnect(),
    )

    connector.connection()
    connector.reset()
    connector.connection()

    assert created == [(("dsql",), {"region_name": REGION})]
    assert len(tokens.calls) == 2


@pytest.mark.parametrize(
    ("tokens", "connect"),
    [
        (FakeDsqlTokenClient(error=NoCredentialsError()), None),
        (
            None,
            RecordingConnect(
                error=psycopg.OperationalError(
                    f"connection to {ENDPOINT} failed: access denied for token-1"
                )
            ),
        ),
    ],
)
def test_token_or_connect_failure_raises_data_source_connection_error(
    tokens: FakeDsqlTokenClient | None, connect: RecordingConnect | None
) -> None:
    connector, _, _ = make_connector(tokens=tokens, connect=connect)

    with pytest.raises(DataSourceConnectionError) as caught:
        connector.connection()

    assert caught.value.__cause__ is not None
    assert ENDPOINT not in str(caught.value)
    assert "token" not in str(caught.value)


def unknown_dsql_service() -> UnknownServiceError:
    """The error an old Lambda runtime boto3 raises for the "dsql" client."""
    return UnknownServiceError(service_name="dsql", known_service_names="s3, sts")


def test_a_boto3_without_the_dsql_client_raises_data_source_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def old_boto3_client(*args: object, **kwargs: object) -> object:
        raise unknown_dsql_service()

    monkeypatch.setattr(dsql_module.boto3, "client", old_boto3_client)
    connector = DsqlConnector(
        cluster_endpoint=ENDPOINT,
        region=REGION,
        db_user=READONLY_USER,
        connect=RecordingConnect(),
    )

    with pytest.raises(DataSourceConnectionError):
        connector.connection()


def test_a_client_that_failed_to_sign_is_replaced_on_the_next_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # botocore fixes the credentials when the client is created, so a client
    # created before credentials could be resolved fails forever.
    clients = [FakeDsqlTokenClient(error=NoCredentialsError()), FakeDsqlTokenClient()]
    monkeypatch.setattr(dsql_module.boto3, "client", lambda *a, **k: clients.pop(0))
    connect = RecordingConnect()
    connector = DsqlConnector(
        cluster_endpoint=ENDPOINT,
        region=REGION,
        db_user=READONLY_USER,
        connect=connect,
    )

    with pytest.raises(DataSourceConnectionError):
        connector.connection()
    connector.connection()

    assert clients == []
    assert connect.calls[-1]["password"] == "token-1"


def test_an_injected_client_is_kept_after_a_failed_token() -> None:
    tokens = FakeDsqlTokenClient(error=NoCredentialsError())
    connector, _, _ = make_connector(tokens=tokens)

    for _ in range(2):
        with pytest.raises(DataSourceConnectionError):
            connector.connection()

    assert len(tokens.calls) == 2


def test_a_failed_boto3_client_creation_is_retried_on_the_next_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes: list[object] = [unknown_dsql_service(), FakeDsqlTokenClient()]

    def flaky_boto3_client(*args: object, **kwargs: object) -> object:
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(dsql_module.boto3, "client", flaky_boto3_client)
    connect = RecordingConnect()
    connector = DsqlConnector(
        cluster_endpoint=ENDPOINT,
        region=REGION,
        db_user=READONLY_USER,
        connect=connect,
    )

    with pytest.raises(DataSourceConnectionError):
        connector.connection()
    connector.connection()

    assert outcomes == []
    assert connect.calls[-1]["password"] == "token-1"
