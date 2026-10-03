"""Tests for the block_credit_card presenter."""

import pytest
from block_credit_card_lambda.delivery.presenters.card_block import (
    present_card_block,
)
from block_credit_card_lambda.domain.entities.card_block import CardBlock

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("already_blocked", [False, True])
def test_presenter_returns_the_card_status_and_the_already_blocked_flag(
    already_blocked: bool,
) -> None:
    block = CardBlock(
        card_last4="4821", status="Blocked", already_blocked=already_blocked
    )

    assert present_card_block(block) == {
        "card_last4": "4821",
        "status": "Blocked",
        "already_blocked": already_blocked,
    }
