"""Lambda configuration read from environment variables."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

_TOPIC_ARN_PREFIX: Final = "arn:aws:sns:"


class ConfigurationError(Exception):
    """The Lambda environment is missing a setting or has an invalid one."""


@dataclass(frozen=True)
class HandOffSettings:
    """Where hand-offs are published.

    Attributes:
        topic_arn: The SNS topic, ledgerlens-human-handoff in the data stack.
        region: Region of the SNS client; the Lambda runtime sets AWS_REGION.
    """

    topic_arn: str
    region: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "HandOffSettings":
        """Read and validate HANDOFF_TOPIC_ARN and AWS_REGION.

        Raises:
            ConfigurationError: A variable is missing, or the ARN isn't an SNS
                topic ARN.
        """
        topic_arn = _required(env, "HANDOFF_TOPIC_ARN")
        if not topic_arn.startswith(_TOPIC_ARN_PREFIX):
            raise ConfigurationError(
                "HANDOFF_TOPIC_ARN must be an SNS topic ARN (arn:aws:sns:...), "
                f"got {topic_arn!r}"
            )
        return cls(topic_arn=topic_arn, region=_required(env, "AWS_REGION"))


def _required(env: Mapping[str, str], name: str) -> str:
    """Return a required variable, trimmed.

    Raises:
        ConfigurationError: The variable is missing or blank.
    """
    value = env.get(name, "").strip()
    if not value:
        raise ConfigurationError(f"{name} is required")
    return value
