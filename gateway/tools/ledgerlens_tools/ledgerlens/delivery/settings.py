"""Lambda configuration read from environment variables."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

SUPPORTED_ENGINES: Final = frozenset({"postgresql"})
DEFAULT_STATEMENT_TIMEOUT_MS: Final = 5000
DEFAULT_MAX_ROWS: Final = 25


class ConfigurationError(Exception):
    """The Lambda environment is missing a setting or has an invalid one."""


@dataclass(frozen=True)
class DatabaseSettings:
    """Database settings shared by every tool Lambda.

    Attributes:
        engine: Database engine; selects the connector, repository and SQL dialect.
        secret_arn: Secrets Manager secret with the DB credentials.
        statement_timeout_ms: Server-side timeout for every statement.
        max_rows: Maximum rows a tool returns per call.
    """

    engine: str
    secret_arn: str
    statement_timeout_ms: int
    max_rows: int

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "DatabaseSettings":
        """Read and validate DB_ENGINE, DB_SECRET_ARN, DB_STATEMENT_TIMEOUT_MS
        and MAX_ROWS.

        Raises:
            ConfigurationError: A required variable is missing or a value is
                invalid.
        """
        engine = env.get("DB_ENGINE", "").strip().lower()
        if engine not in SUPPORTED_ENGINES:
            allowed = ", ".join(sorted(SUPPORTED_ENGINES))
            raise ConfigurationError(
                f"DB_ENGINE must be one of: {allowed}; got {engine!r}"
            )
        secret_arn = env.get("DB_SECRET_ARN", "").strip()
        if not secret_arn:
            raise ConfigurationError("DB_SECRET_ARN is required")
        return cls(
            engine=engine,
            secret_arn=secret_arn,
            statement_timeout_ms=_positive_int(
                env, "DB_STATEMENT_TIMEOUT_MS", DEFAULT_STATEMENT_TIMEOUT_MS
            ),
            max_rows=_positive_int(env, "MAX_ROWS", DEFAULT_MAX_ROWS),
        )


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
