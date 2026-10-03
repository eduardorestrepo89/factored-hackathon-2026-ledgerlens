"""Tests for HandOffUseCase."""

from typing import Any

import pytest
from human_agent_hand_off_lambda.application.ports.errors import PublishError
from human_agent_hand_off_lambda.application.use_cases.hand_off import HandOffUseCase
from human_agent_hand_off_lambda.domain.entities.hand_off import (
    HandOff,
    HandOffResult,
)
from human_agent_hand_off_lambda.domain.errors import (
    HandOffUnavailableError,
    InvalidInputError,
)

from .fakes import CUSTOMER_ID, FakePublisher

pytestmark = pytest.mark.unit

SUMMARY = (
    "Customer did not recognise 2 charges (USD 740.00 BESTBUY Miami). Card 4821 "
    "blocked. Claim CMP-4KQ2ZJ7M3XH5TB6RWN2Y opened."
)
ARGS: dict[str, Any] = {
    "customer_id": CUSTOMER_ID,
    "priority": "high",
    "reason": "FRAUD_CONFIRMED",
    "summary": SUMMARY,
    "related_ids": ["TRX-88", "CMP-4KQ2ZJ7M3XH5TB6RWN2Y"],
}
RELATED_IDS_REASON = (
    "must be a list of at most 20 ids made of letters, digits and dashes"
)


def hand_off(publisher: FakePublisher, **overrides: Any) -> HandOffResult:
    """Run the use case with ARGS, overridden by ``overrides``."""
    return HandOffUseCase(publisher=publisher).execute(**{**ARGS, **overrides})


def test_a_valid_hand_off_is_published_and_its_reference_returned() -> None:
    publisher = FakePublisher(reference="msg-1")

    assert hand_off(publisher) == HandOffResult(hand_off_id="msg-1", priority="high")
    assert publisher.published == [
        HandOff(
            customer_id=CUSTOMER_ID,
            priority="high",
            reason="FRAUD_CONFIRMED",
            summary=SUMMARY,
            related_ids=("TRX-88", "CMP-4KQ2ZJ7M3XH5TB6RWN2Y"),
        )
    ]


def test_inputs_are_cleaned_before_publishing() -> None:
    publisher = FakePublisher()

    hand_off(
        publisher,
        customer_id=" cli-itiecue8prh9 ",
        priority=" Normal ",
        reason=" customer_request ",
        summary=f"  {SUMMARY}\n",
        related_ids=[" trx-88 "],
    )

    assert publisher.published[0] == HandOff(
        customer_id=CUSTOMER_ID,
        priority="normal",
        reason="CUSTOMER_REQUEST",
        summary=SUMMARY,
        related_ids=("TRX-88",),
    )


@pytest.mark.parametrize("related_ids", [None, []])
def test_related_ids_are_optional(related_ids: object) -> None:
    publisher = FakePublisher()

    hand_off(publisher, related_ids=related_ids)

    assert publisher.published[0].related_ids == ()


def test_a_summary_of_2000_characters_and_20_related_ids_are_accepted() -> None:
    publisher = FakePublisher()

    hand_off(
        publisher,
        summary="á" * 2000,
        related_ids=[f"TRX-{i}" for i in range(20)],
    )

    assert len(publisher.published[0].summary) == 2000
    assert len(publisher.published[0].related_ids) == 20


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("customer_id", None, "is required and must be a non-empty string"),
        ("customer_id", "   ", "is required and must be a non-empty string"),
        ("priority", "urgent", "must be high or normal"),
        ("priority", None, "must be high or normal"),
        (
            "reason",
            "ANGRY",
            "must be one of: FRAUD_CONFIRMED, CUSTOMER_REQUEST, UNRESOLVED, "
            "OUT_OF_SCOPE",
        ),
        ("summary", "", "must be a summary of 1 to 2000 characters"),
        ("summary", "   ", "must be a summary of 1 to 2000 characters"),
        ("summary", "x" * 2001, "must be a summary of 1 to 2000 characters"),
        ("summary", 42, "must be a summary of 1 to 2000 characters"),
        ("related_ids", "TRX-88", RELATED_IDS_REASON),
        ("related_ids", ["TRX 88"], RELATED_IDS_REASON),
        ("related_ids", ["TRX-88;DROP"], RELATED_IDS_REASON),
        ("related_ids", ["SEÑOR-1"], RELATED_IDS_REASON),
        ("related_ids", [42], RELATED_IDS_REASON),
        ("related_ids", [""], RELATED_IDS_REASON),
        ("related_ids", ["X" * 41], RELATED_IDS_REASON),
        ("related_ids", [f"TRX-{i}" for i in range(21)], RELATED_IDS_REASON),
    ],
)
def test_invalid_input_is_rejected_before_publishing(
    field: str, value: object, reason: str
) -> None:
    publisher = FakePublisher()

    with pytest.raises(InvalidInputError) as caught:
        hand_off(publisher, **{field: value})

    assert caught.value.field == field
    assert caught.value.reason == reason
    assert publisher.published == []


def test_a_failed_publish_raises_hand_off_unavailable() -> None:
    failure = PublishError("SNS publish failed")

    with pytest.raises(HandOffUnavailableError) as caught:
        hand_off(FakePublisher(error=failure))

    assert caught.value.__cause__ is failure
