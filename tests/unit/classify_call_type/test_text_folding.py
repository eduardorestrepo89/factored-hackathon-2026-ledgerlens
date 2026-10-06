"""Tests for fold_text, the country comparison of FOREIGN_TRANSACTION."""

import pytest
from classify_call_type_lambda.domain.value_objects.text_folding import fold_text

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("México", "mexico"),
        (" MEXICO ", "mexico"),
        ("Perú", "peru"),
        ("Brasil", "brasil"),
        ("  ", ""),
        ("", ""),
        (None, None),
    ],
)
def test_fold_text(value: str | None, expected: str | None) -> None:
    assert fold_text(value) == expected


def test_accented_and_plain_names_fold_equal() -> None:
    assert fold_text("México") == fold_text("Mexico")
