"""Use case: validate a hand-off to a human agent and give it an id."""

import base64
import hashlib
import re
from typing import Final

from human_agent_hand_off_lambda.domain.entities.hand_off import (
    HandOff,
    HandOffResult,
)
from human_agent_hand_off_lambda.domain.errors import InvalidInputError

PRIORITIES: Final = ("high", "normal")
REASONS: Final = ("FRAUD_CONFIRMED", "CUSTOMER_REQUEST", "UNRESOLVED", "OUT_OF_SCOPE")
MAX_SUMMARY_LENGTH: Final = 2000
MAX_RELATED_IDS: Final = 20
HAND_OFF_ID_PREFIX: Final = "HO-"
_HAND_OFF_ID_LENGTH: Final = 8
_RELATED_ID: Final = re.compile(r"[A-Z0-9-]{1,40}")
_RELATED_IDS_REASON: Final = (
    f"must be a list of at most {MAX_RELATED_IDS} ids made of letters, "
    "digits and dashes"
)


class HandOffUseCase:
    """Validate a hand-off and give it an id derived from its content.

    Every field but the summary is a closed set or an id, so only the summary
    carries free text written by the model. Nothing is stored or sent: the
    frontend reads the result from the agent's stream
    (docs/superpowers/specs/2026-10-03-human-hand-off-frontend-design.md, section 2).
    """

    def execute(
        self,
        customer_id: object,
        priority: object,
        reason: object,
        summary: object,
        related_ids: object,
    ) -> HandOffResult:
        """Validate every input, then return the hand-off with its id.

        Args:
            customer_id: The customer id exactly as it came in the tool event.
            priority: high or normal, as it came.
            reason: One of REASONS, as it came.
            summary: The summary for the human agent, as it came.
            related_ids: Optional list of related record ids, as it came.

        Raises:
            InvalidInputError: An input is invalid.
        """
        hand_off = HandOff(
            customer_id=_clean_customer_id(customer_id),
            priority=_clean_priority(priority),
            reason=_clean_reason(reason),
            summary=_clean_summary(summary),
            related_ids=_clean_related_ids(related_ids),
        )
        return HandOffResult(hand_off_id=hand_off_id(hand_off), hand_off=hand_off)


def hand_off_id(hand_off: HandOff) -> str:
    """Return ``HO-`` plus 8 base32 characters of a SHA-256 over the content.

    The same content always gives the same id, so a retried or repeated call
    never makes a second case. Related ids are sorted, so their order doesn't
    matter.
    """
    content = "|".join(
        (
            hand_off.customer_id,
            hand_off.priority,
            hand_off.reason,
            hand_off.summary,
            ",".join(sorted(hand_off.related_ids)),
        )
    )
    digest = hashlib.sha256(content.encode("utf-8")).digest()
    encoded = base64.b32encode(digest).decode("ascii")
    return HAND_OFF_ID_PREFIX + encoded[:_HAND_OFF_ID_LENGTH]


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
