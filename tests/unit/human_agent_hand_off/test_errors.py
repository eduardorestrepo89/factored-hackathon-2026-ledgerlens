"""Tests for the hand-off domain errors."""

import pytest
from human_agent_hand_off_lambda.domain.errors import DomainError, InvalidInputError

pytestmark = pytest.mark.unit


def test_invalid_input_error_formats_field_and_reason() -> None:
    error = InvalidInputError("priority", "must be high or normal")

    assert isinstance(error, DomainError)
    assert error.message == (
        "Invalid value for 'priority': must be high or normal. "
        "Ask the customer to confirm and retry."
    )
