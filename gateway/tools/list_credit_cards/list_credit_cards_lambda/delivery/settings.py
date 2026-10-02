"""Lambda configuration read from environment variables."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final

DEFAULT_MAX_ROWS: Final = 25
DEFAULT_DSQL_DB_USER: Final = "ledgerlens_readonly"
# Public DSQL endpoints carry their region: <cluster id>.dsql.<region>.on.aws.
_PUBLIC_ENDPOINT: Final = re.compile(r"[^.]+\.dsql\.([a-z0-9-]+)\.on\.aws")


class ConfigurationError(Exception):
    """The Lambda environment is missing a setting or has an invalid one."""


class DatabaseEngine(str, Enum):
    """Database engines the tools can run on."""

    AURORA_DSQL = "aurora_dsql"


@dataclass(frozen=True)
class DatabaseSettings:
    """Database settings that don't depend on the engine.

    Attributes:
        engine: Database engine; selects the connector, repository and SQL dialect.
        max_rows: Maximum rows a tool returns per call.
    """

    engine: DatabaseEngine
    max_rows: int

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "DatabaseSettings":
        """Read and validate DB_ENGINE (default aurora_dsql) and MAX_ROWS.

        Raises:
            ConfigurationError: A value is invalid.
        """
        return cls(
            engine=_engine(env),
            max_rows=_positive_int(env, "MAX_ROWS", DEFAULT_MAX_ROWS),
        )


@dataclass(frozen=True)
class DsqlSettings:
    """Settings needed only to connect to Aurora DSQL.

    Attributes:
        cluster_endpoint: Cluster host, such as abc123.dsql.us-east-1.on.aws.
        region: AWS region used to sign the IAM token.
        db_user: Database role to connect as; ``admin`` uses the admin token.
    """

    cluster_endpoint: str
    region: str
    db_user: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "DsqlSettings":
        """Read and validate DSQL_CLUSTER_ENDPOINT, AWS_REGION and DSQL_DB_USER.

        Raises:
            ConfigurationError: A required variable is missing or a value is
                invalid.
        """
        cluster_endpoint = _cluster_endpoint(env)
        region = _required(env, "AWS_REGION")
        _check_endpoint_region(cluster_endpoint, region)
        return cls(
            cluster_endpoint=cluster_endpoint,
            region=region,
            db_user=env.get("DSQL_DB_USER", "").strip() or DEFAULT_DSQL_DB_USER,
        )


def _engine(env: Mapping[str, str]) -> DatabaseEngine:
    """Parse DB_ENGINE; blank or missing means Aurora DSQL.

    Raises:
        ConfigurationError: The value isn't a supported engine.
    """
    raw = env.get("DB_ENGINE", "").strip().lower() or DatabaseEngine.AURORA_DSQL.value
    try:
        return DatabaseEngine(raw)
    except ValueError as exc:
        allowed = ", ".join(engine.value for engine in DatabaseEngine)
        raise ConfigurationError(
            f"DB_ENGINE must be one of: {allowed}; got {raw!r}"
        ) from exc


def _cluster_endpoint(env: Mapping[str, str]) -> str:
    """Parse DSQL_CLUSTER_ENDPOINT as a bare, fully qualified host name.

    Raises:
        ConfigurationError: The value is missing, has a scheme, port or path, or
            has no dot (a cluster ID pasted instead of the endpoint).
    """
    endpoint = _required(env, "DSQL_CLUSTER_ENDPOINT")
    if ":" in endpoint or "/" in endpoint or "." not in endpoint:
        raise ConfigurationError(
            "DSQL_CLUSTER_ENDPOINT must be a bare host name without a scheme, port "
            f"or path, such as abc123.dsql.us-east-1.on.aws; got {endpoint!r}"
        )
    return endpoint


def _check_endpoint_region(cluster_endpoint: str, region: str) -> None:
    """Reject a public endpoint whose region differs from the token's region.

    The IAM token is signed for ``region``, so a cluster in another region would
    reject every connection. Custom hosts (PrivateLink) aren't checked.

    Raises:
        ConfigurationError: The endpoint names a region other than ``region``.
    """
    match = _PUBLIC_ENDPOINT.fullmatch(cluster_endpoint)
    if match is not None and match.group(1) != region:
        raise ConfigurationError(
            f"DSQL_CLUSTER_ENDPOINT is in region {match.group(1)!r} but AWS_REGION "
            f"is {region!r}; the IAM token must be signed for the cluster's region"
        )


def _required(env: Mapping[str, str], name: str) -> str:
    """Return a required variable, trimmed.

    Raises:
        ConfigurationError: The variable is missing or blank.
    """
    value = env.get(name, "").strip()
    if not value:
        raise ConfigurationError(f"{name} is required")
    return value


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    """Parse an optional positive integer variable.

    Raises:
        ConfigurationError: The value isn't an integer greater than zero.
    """
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero, got {value}")
    return value
