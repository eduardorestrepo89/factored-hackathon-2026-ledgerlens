"""Lambda configuration read from environment variables."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Final

# The write tools' role (SELECT; UPDATE on products; INSERT on complaints), mapped to
# ledgerlens-write-tools. A missing DSQL_DB_USER must never fall back to ll_read.
DEFAULT_DSQL_DB_USER: Final = "ll_write"
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
    """

    engine: DatabaseEngine

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "DatabaseSettings":
        """Read and validate DB_ENGINE (default aurora_dsql).

        Raises:
            ConfigurationError: The value is invalid.
        """
        return cls(engine=_engine(env))


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


@dataclass(frozen=True)
class ClockSettings:
    """The tool's notion of "now".

    Attributes:
        as_of: Fixed UTC "now" from AS_OF, or None to use the real clock.
    """

    as_of: datetime | None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "ClockSettings":
        """Read AS_OF, an optional ISO 8601 date or timestamp used as "now".

        Demos set it to a moment inside the historical dataset. Production
        leaves it unset.

        Raises:
            ConfigurationError: The value isn't an ISO 8601 date or timestamp.
        """
        return cls(as_of=_as_of(env))

    def now(self) -> datetime:
        """Return as_of when set, else datetime.now(timezone.utc). Always aware UTC."""
        if self.as_of is not None:
            return self.as_of
        return datetime.now(timezone.utc)


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


def _as_of(env: Mapping[str, str]) -> datetime | None:
    """Parse AS_OF as aware UTC; blank or missing means the real clock.

    A bare date is midnight UTC, a timestamp without an offset is UTC, and one
    with an offset (or Z) is converted to UTC.

    Raises:
        ConfigurationError: The value isn't an ISO 8601 date or timestamp.
    """
    raw = env.get("AS_OF", "").strip()
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        # Near datetime.min/max the shift to UTC overflows: treat it as invalid.
        return value.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ConfigurationError(
            f"AS_OF must be an ISO 8601 date or timestamp, got {raw!r}"
        ) from exc
