"""Dependency builder: the only place where this tool's objects get built.

The handler never builds anything itself. At cold start it calls
build_hand_off_use_case once and reuses the result on every warm invocation.
That is safe because nothing built here keeps request data; the SNS client is
created on the first publish and reused.
"""

import logging
from collections.abc import Mapping

from human_agent_hand_off_lambda.application.use_cases.hand_off import HandOffUseCase
from human_agent_hand_off_lambda.delivery.settings import (
    ConfigurationError,
    HandOffSettings,
)
from human_agent_hand_off_lambda.infrastructure.publishers.sns_publisher import (
    SnsHandOffPublisher,
)

logger = logging.getLogger(__name__)


def build_hand_off_use_case(env: Mapping[str, str]) -> HandOffUseCase | None:
    """Build the human_agent_hand_off use case and its publisher. Never raises.

    Returns:
        The ready use case, or None when the configuration is invalid. Every
        request then gets HandOffUnavailableError's message.
    """
    try:
        settings = HandOffSettings.from_env(env)
    except ConfigurationError:
        logger.exception("Invalid configuration for human_agent_hand_off")
        return None
    return HandOffUseCase(
        publisher=SnsHandOffPublisher(
            topic_arn=settings.topic_arn, region=settings.region
        )
    )
