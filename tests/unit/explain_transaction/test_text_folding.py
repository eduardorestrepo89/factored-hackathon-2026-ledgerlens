"""Tests for fold_text, which compares country names loosely."""

import pytest
from explain_transaction_lambda.domain.value_objects.text_folding import fold_text

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("México", " MEXICO "),
        ("Colombia", "colombia"),
        ("Perú", "PERU"),
    ],
)
def test_accents_case_and_spaces_fold_equal(left: str, right: str) -> None:
    assert fold_text(left) == fold_text(right)


def test_fold_text_returns_plain_lower_case() -> None:
    assert fold_text("México") == "mexico"
    assert fold_text("São Paulo") == "sao paulo"


def test_different_countries_stay_different() -> None:
    assert fold_text("Brasil") != fold_text("México")


def test_none_stays_none() -> None:
    assert fold_text(None) is None
