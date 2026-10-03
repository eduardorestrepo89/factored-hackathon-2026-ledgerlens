"""Use case: send the conversation to a human agent."""

import re
from typing import Final

from human_agent_hand_off_lambda.application.ports.errors import PublishError
from human_agent_hand_off_lambda.application.ports.hand_off_publisher import (
    HandOffPublisher,
)
from human_agent_hand_off_lambda.domain.entities.hand_off import (
    HandOff,
    HandOffResult,
)
from human_agent_hand_off_lambda.domain.errors import (
    HandOffUnavailableError,
    InvalidInputError,
)

PRIORITIES: Final = ("high", "normal")
REASONS: Final = ("FRAUD_CONFIRMED", "CUSTOMER_REQUEST", "UNRESOLVED", "OUT_OF_SCOPE")
MAX_SUMMARY_LENGTH: Final = 2000
MAX_RELATED_IDS: Final = 20
_RELATED_ID: Final = re.compile(r"[A-Z0-9-]{1,40}")
_RELATED_IDS_REASON: Final = (
    f"must be a list of at most {MAX_RELATED_IDS} ids made of letters, "
    "digits and dashes"
)


class HandOffUseCase:
    """Validate a hand-off and publish it through the HandOffPublisher port.

    Every field but the summary is a closed set or an id, so only the summary
    carries free text written by the model.
    """

    def __init__(self, publisher: HandOffPublisher) -> None:
        """Store the publisher port."""
        self._publisher: HandOffPublisher = publisher

    def execute(
        self,
        customer_id: object,
        priority: object,
        reason: object,
        summary: object,
        related_ids: object,
    ) -> HandOffResult:
        """Validate every input, then publish the hand-off.

        Args:
            customer_id: The customer id exactly as it came in the tool event.
            priority: high or normal, as it came.
            reason: One of REASONS, as it came.
            summary: The summary for the human agent, as it came.
            related_ids: Optional list of related record ids, as it came.

        Raises:
            InvalidInputError: An input is invalid. Raised before publishing.
            HandOffUnavailableError: The publisher failed.
        """
        hand_off = HandOff(
            customer_id=_clean_customer_id(customer_id),
            priority=_clean_priority(priority),
            reason=_clean_reason(reason),
            summary=_clean_summary(summary),
            related_ids=_clean_related_ids(related_ids),
        )
        try:
            reference = self._publisher.publish(hand_off)
        except PublishError as exc:
            raise HandOffUnavailableError() from exc
        return HandOffResult(hand_off_id=reference, priority=hand_off.priority)


def _clean_customer_id(raw: object) -> str:
    """Strip and uppercase the raw id; ids look like ``CLI-ITIECUE8PRH9``."""
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidInputError(
            "customer_id", "is required and must be a non-empty string"
        )
    return raw.strip().upper()


def _clean_priority(raw: object) -> str:
    """Strip and lowercase; high or normal."""
    if isinstance(raw, str) and raw.strip().lower() in PRIORITIES:
        return raw.strip().lower()
    raise InvalidInputError("priority", "must be high or normal")


def _clean_reason(raw: object) -> str:
    """Strip and uppercase; one of REASONS."""
    if isinstance(raw, str) and raw.strip().upper() in REASONS:
        return raw.strip().upper()
    raise InvalidInputError("reason", f"must be one of: {', '.join(REASONS)}")


def _clean_summary(raw: object) -> str:
    """Strip; 1 to MAX_SUMMARY_LENGTH characters."""
    reason = f"must be a summary of 1 to {MAX_SUMMARY_LENGTH} characters"
    if not isinstance(raw, str):
        raise InvalidInputError("summary", reason)
    summary = raw.strip()
    if not summary or len(summary) > MAX_SUMMARY_LENGTH:
        raise InvalidInputError("summary", reason)
    return summary


def _clean_related_ids(raw: object) -> tuple[str, ...]:
    """Missing means none; else at most MAX_RELATED_IDS ids of [A-Z0-9-], uppercased."""
    if raw is None:
        return ()
    if not isinstance(raw, list) or len(raw) > MAX_RELATED_IDS:
        raise InvalidInputError("related_ids", _RELATED_IDS_REASON)
    ids: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not _RELATED_ID.fullmatch(item.strip().upper()):
            raise InvalidInputError("related_ids", _RELATED_IDS_REASON)
        ids.append(item.strip().upper())
    return tuple(ids)
