"""Tests for the hand-off domain errors."""

import pytest
from human_agent_hand_off_lambda.domain.errors import (
    DomainError,
    HandOffUnavailableError,
    InvalidInputError,
)

pytestmark = pytest.mark.unit


def test_invalid_input_error_formats_field_and_reason() -> None:
    error = InvalidInputError("priority", "must be high or normal")

    assert error.message == (
        "Invalid value for 'priority': must be high or normal. "
        "Ask the customer to confirm and retry."
    )


def test_hand_off_unavailable_tells_the_agent_what_to_say() -> None:
    error = HandOffUnavailableError()

    assert isinstance(error, DomainError)
    assert (
        error.message
        == HandOffUnavailableError.MESSAGE
        == (
            "The hand-off to a human agent couldn't be sent right now. Tell the "
            "customer you couldn't reach a person and that they can contact the "
            "bank through its usual channels."
        )
    )
