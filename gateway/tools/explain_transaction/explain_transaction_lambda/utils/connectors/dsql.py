"""Aurora DSQL connector: psycopg connections authenticated with IAM tokens.

DSQL_CLUSTER_ENDPOINT is the cluster's PrivateLink host (data stack output
DsqlPrivateHost): the cluster policy refuses connections from outside the VPC.
The token is signed for that host.

TODO(ledgerlens): R6 - the DB role is the only write guard: DSQL rejects
  default_transaction_read_only. ll_read has SELECT-only grants and is mapped to
  the ledgerlens-tools IAM role by the data pipeline's load stage.
TODO(ledgerlens): R7 - mostly resolved: a cluster accepts 10,000 connections.
  What is left is the rate of 100 new connections/s (burst 1,000) during mass
  cold starts, which surfaces as "temporarily unavailable" (a failed connect isn't
  retried within the request). Cap reservedConcurrentExecutions if it ever matters.
TODO(ledgerlens): R11 - sslmode=require doesn't verify the server certificate;
  verify-full needs the Amazon root CA bundled with the Lambda.
"""

import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any, Final, Protocol

import boto3
import psycopg
from psycopg.rows import dict_row

from explain_transaction_lambda.utils.connectors.base import PsycopgConnector

ADMIN_USER: Final = "admin"
_PORT: Final = 5432
_DBNAME: Final = "postgres"
_CONNECT_TIMEOUT_SECONDS: Final = 5


class DsqlTokenClient(Protocol):
    """The part of the boto3 DSQL client the connector uses."""

    def generate_db_connect_auth_token(
        self,
        Hostname: str,  # noqa: N803
        Region: str,  # noqa: N803
    ) -> str:
        """Return a 15-minute IAM token for a custom database role."""
        ...

    def generate_db_connect_admin_auth_token(
        self,
        Hostname: str,  # noqa: N803
        Region: str,  # noqa: N803
    ) -> str:
        """Return a 15-minute IAM token for the admin role."""
        ...


class DsqlConnector(PsycopgConnector):
    """Open psycopg connections to Aurora DSQL with a fresh IAM token each time.

    A token is only checked when connecting, so an open connection outlives its
    token without harm, and every reconnect generates a new one. Connections are
    recycled after MAX_AGE, before DSQL closes them at 60 minutes.
    """

    MAX_AGE: Final = timedelta(minutes=55)

    def __init__(
        self,
        cluster_endpoint: str,
        region: str,
        db_user: str,
        dsql_client: DsqlTokenClient | None = None,
        connect: Callable[..., psycopg.Connection[Any]] = psycopg.connect,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Configure the connector without opening a connection or a boto3 client.

        Args:
            cluster_endpoint: Cluster host, such as abc.dsql.us-east-1.on.aws.
            region: AWS region used to sign the token.
            db_user: Database role; ``admin`` uses the admin token.
            dsql_client: boto3 DSQL client; created lazily on the first open.
            connect: Connection factory; replaced in tests.
            clock: Monotonic time in seconds for MAX_AGE; replaced in tests.
        """
        super().__init__(max_age=self.MAX_AGE, clock=clock)
        self._cluster_endpoint: str = cluster_endpoint
        self._region: str = region
        self._db_user: str = db_user
        self._dsql_client: DsqlTokenClient | None = dsql_client
        self._owns_dsql_client: bool = dsql_client is None
        self._connect: Callable[..., psycopg.Connection[Any]] = connect

    def _open(self) -> psycopg.Connection[Any]:
        """Generate a token and open a TLS connection; the base wraps failures."""
        return self._connect(
            host=self._cluster_endpoint,
            port=_PORT,
            dbname=_DBNAME,
            user=self._db_user,
            password=self._generate_token(),
            sslmode="require",
            # Allowed by DSQL; accented merchant names must reach the server intact.
            client_encoding="utf8",
            connect_timeout=_CONNECT_TIMEOUT_SECONDS,
            autocommit=True,
            row_factory=dict_row,
        )

    def _generate_token(self) -> str:
        """Sign a new IAM token locally (no network call) for the configured role.

        botocore fixes the credentials when the client is created, so a client
        this connector created is dropped when signing fails; the next open
        creates a new one instead of failing forever.
        """
        if self._dsql_client is None:
            self._dsql_client = boto3.client("dsql", region_name=self._region)
        try:
            if self._db_user == ADMIN_USER:
                return self._dsql_client.generate_db_connect_admin_auth_token(
                    Hostname=self._cluster_endpoint, Region=self._region
                )
            return self._dsql_client.generate_db_connect_auth_token(
                Hostname=self._cluster_endpoint, Region=self._region
            )
        except Exception:
            if self._owns_dsql_client:
                self._dsql_client = None
            raise
