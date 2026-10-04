"""Tests for HandOffUseCase and the content-derived hand-off id."""

import re
from typing import Any

import pytest
from human_agent_hand_off_lambda.application.use_cases.hand_off import (
    HandOffUseCase,
    hand_off_id,
)
from human_agent_hand_off_lambda.domain.entities.hand_off import (
    HandOff,
    HandOffResult,
)
from human_agent_hand_off_lambda.domain.errors import InvalidInputError

from .fakes import CUSTOMER_ID

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
# sha256 over "CLI-ITIECUE8PRH9|high|FRAUD_CONFIRMED|<SUMMARY>|CMP-4KQ2ZJ7M3XH5TB6RWN2Y,TRX-88"
EXPECTED_ID = "HO-AYIWT2IJ"
RELATED_IDS_REASON = (
    "must be a list of at most 20 ids made of letters, digits and dashes"
)


def run(**overrides: Any) -> HandOffResult:
    """Run the use case with ARGS, overridden by ``overrides``."""
    return HandOffUseCase().execute(**{**ARGS, **overrides})


def test_a_valid_hand_off_is_returned_with_its_id() -> None:
    assert run() == HandOffResult(
        hand_off_id=EXPECTED_ID,
        hand_off=HandOff(
            customer_id=CUSTOMER_ID,
            priority="high",
            reason="FRAUD_CONFIRMED",
            summary=SUMMARY,
            related_ids=("TRX-88", "CMP-4KQ2ZJ7M3XH5TB6RWN2Y"),
        ),
    )


def test_the_id_is_ho_and_eight_base32_characters() -> None:
    assert re.fullmatch(r"HO-[A-Z2-7]{8}", run().hand_off_id)
    assert hand_off_id(run().hand_off) == run().hand_off_id


def test_inputs_are_cleaned_and_cleaning_keeps_the_id() -> None:
    result = run(
        customer_id=" cli-itiecue8prh9 ",
        priority=" High ",
        reason=" fraud_confirmed ",
        summary=f"  {SUMMARY}\n",
        related_ids=[" cmp-4kq2zj7m3xh5tb6rwn2y ", "trx-88"],
    )

    assert result.hand_off.customer_id == CUSTOMER_ID
    assert result.hand_off.priority == "high"
    assert result.hand_off.reason == "FRAUD_CONFIRMED"
    assert result.hand_off.summary == SUMMARY
    assert result.hand_off.related_ids == ("CMP-4KQ2ZJ7M3XH5TB6RWN2Y", "TRX-88")
    # related ids are sorted inside the hash, so their order doesn't matter
    assert result.hand_off_id == EXPECTED_ID


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("customer_id", "CLI-OTHER0000001"),
        ("priority", "normal"),
        ("reason", "UNRESOLVED"),
        ("summary", "Otro resumen."),
        ("related_ids", ["TRX-99"]),
    ],
)
def test_any_field_change_gives_a_new_id(field: str, value: object) -> None:
    assert run(**{field: value}).hand_off_id != EXPECTED_ID


@pytest.mark.parametrize("related_ids", [None, []])
def test_related_ids_are_optional(related_ids: object) -> None:
    assert run(related_ids=related_ids).hand_off.related_ids == ()


def test_a_summary_of_2000_characters_and_20_related_ids_are_accepted() -> None:
    result = run(summary="á" * 2000, related_ids=[f"TRX-{i}" for i in range(20)])

    assert len(result.hand_off.summary) == 2000
    assert len(result.hand_off.related_ids) == 20


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
def test_invalid_input_is_rejected(field: str, value: object, reason: str) -> None:
    with pytest.raises(InvalidInputError) as caught:
        run(**{field: value})

    assert caught.value.field == field
    assert caught.value.reason == reason
