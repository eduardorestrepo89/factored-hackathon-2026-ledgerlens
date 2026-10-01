"""Tests for TransactionFilters parsing, defaults and validation."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from list_card_transactions_lambda.domain.errors import InvalidInputError
from list_card_transactions_lambda.domain.value_objects.transaction_filters import (
    TransactionFilters,
    TransactionStatus,
)

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 29)


def parse(**raw: Any) -> TransactionFilters:
    """Parse raw tool input with a fixed 'today'."""
    return TransactionFilters.from_raw({"customer_id": "CUST-1", **raw}, today=TODAY)


def assert_invalid(field: str, **raw: Any) -> InvalidInputError:
    """Assert that parsing fails on the given field and return the error."""
    with pytest.raises(InvalidInputError) as caught:
        parse(**raw)
    assert caught.value.field == field
    return caught.value


def test_defaults_to_the_last_30_days_with_no_optional_filters() -> None:
    filters = parse()

    assert filters == TransactionFilters(
        customer_id="CUST-1", date_from=date(2026, 8, 30), date_to=TODAY
    )


def test_customer_id_is_trimmed() -> None:
    assert parse(customer_id="  CUST-9 ").customer_id == "CUST-9"


@pytest.mark.parametrize("value", [None, "", "   ", 123])
def test_customer_id_is_required_non_blank_string(value: object) -> None:
    assert_invalid("customer_id", customer_id=value)


def test_missing_customer_id_is_rejected() -> None:
    with pytest.raises(InvalidInputError) as caught:
        TransactionFilters.from_raw({}, today=TODAY)
    assert caught.value.field == "customer_id"


@pytest.mark.parametrize("raw", [None, [], "customer_id=CUST-1", 42])
def test_non_object_input_is_rejected(raw: object) -> None:
    with pytest.raises(InvalidInputError) as caught:
        TransactionFilters.from_raw(raw, today=TODAY)
    assert caught.value.field == "input"
    assert "must be a JSON object" in caught.value.message


def test_explicit_dates_are_parsed() -> None:
    filters = parse(date_from="2026-09-01", date_to="2026-09-15")

    assert (filters.date_from, filters.date_to) == (date(2026, 9, 1), date(2026, 9, 15))


def test_date_from_only_keeps_date_to_as_today() -> None:
    filters = parse(date_from="2026-09-01")

    assert (filters.date_from, filters.date_to) == (date(2026, 9, 1), TODAY)


def test_date_to_only_defaults_date_from_to_30_days_before_it() -> None:
    filters = parse(date_to="2026-06-30")

    assert filters.date_from == date(2026, 5, 31)


@pytest.mark.parametrize(
    "value", ["2026/09/01", "2026-9-1", "20260901", "01-09-2026", "yesterday", 20260901]
)
def test_dates_must_be_iso_yyyy_mm_dd(value: object) -> None:
    error = assert_invalid("date_from", date_from=value)
    assert "YYYY-MM-DD" in error.reason or "string" in error.reason


def test_impossible_calendar_dates_are_rejected() -> None:
    error = assert_invalid("date_to", date_to="2026-02-30")
    assert "real calendar date" in error.reason


def test_date_from_after_date_to_is_rejected() -> None:
    assert_invalid("date_from", date_from="2026-09-20", date_to="2026-09-10")


def test_date_range_of_exactly_180_days_is_allowed() -> None:
    filters = parse(date_from="2026-04-02", date_to="2026-09-29")

    assert (filters.date_to - filters.date_from).days == 180


def test_date_range_over_180_days_is_rejected() -> None:
    error = assert_invalid("date_from", date_from="2026-04-01", date_to="2026-09-29")
    assert "180 days" in error.reason


@pytest.mark.parametrize(
    "field",
    [
        "card_last4",
        "merchant",
        "status",
        "date_from",
        "date_to",
        "min_amount",
        "max_amount",
    ],
)
@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_or_null_optional_fields_mean_no_filter(
    field: str, blank: object
) -> None:
    filters = parse(**{field: blank})

    assert filters == parse()


def test_card_last4_accepts_four_digits_and_trims() -> None:
    assert parse(card_last4=" 0042 ").card_last4 == "0042"


@pytest.mark.parametrize("value", ["123", "12345", "12a4", "١٢٣٤", 1234])
def test_card_last4_must_be_exactly_four_ascii_digits(value: object) -> None:
    assert_invalid("card_last4", card_last4=value)


def test_merchant_is_trimmed() -> None:
    assert parse(merchant="  Óptica Visión ").merchant == "Óptica Visión"


def test_merchant_of_100_characters_is_allowed() -> None:
    assert parse(merchant="m" * 100).merchant == "m" * 100


def test_merchant_over_100_characters_is_rejected() -> None:
    assert_invalid("merchant", merchant="m" * 101)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (10, Decimal("10")),
        (10.5, Decimal("10.5")),
        (0.1, Decimal("0.1")),
        ("12.30", Decimal("12.30")),
        (" 7 ", Decimal("7")),
        (0, Decimal("0")),
    ],
)
def test_amounts_parse_to_exact_decimals(value: object, expected: Decimal) -> None:
    assert parse(min_amount=value).min_amount == expected
    assert parse(max_amount=value).max_amount == expected


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        "abc",
        float("nan"),
        float("inf"),
        "NaN",
        "Infinity",
        "-Infinity",
        [1],
        {"value": 1},
    ],
)
def test_amounts_reject_booleans_non_numbers_and_non_finite(value: object) -> None:
    assert_invalid("min_amount", min_amount=value)


def test_negative_amounts_are_rejected() -> None:
    assert_invalid("max_amount", max_amount=-1)


def test_min_amount_above_max_amount_is_rejected() -> None:
    assert_invalid("min_amount", min_amount=50, max_amount=10)


def test_equal_min_and_max_amount_is_allowed() -> None:
    filters = parse(min_amount="10.00", max_amount=10)

    assert filters.min_amount == filters.max_amount


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Approved", TransactionStatus.APPROVED),
        ("declined", TransactionStatus.DECLINED),
        (" PENDING ", TransactionStatus.PENDING),
        ("reversed", TransactionStatus.REVERSED),
    ],
)
def test_status_matches_case_insensitively(
    value: str, expected: TransactionStatus
) -> None:
    assert parse(status=value).status is expected


def test_status_enum_matches_the_data_dictionary() -> None:
    # transaction_status values confirmed with the dataset's categorical values.
    assert [s.value for s in TransactionStatus] == [
        "Approved",
        "Declined",
        "Pending",
        "Reversed",
    ]


def test_unknown_status_lists_the_allowed_values() -> None:
    error = assert_invalid("status", status="Refunded")
    assert error.reason == "must be one of Approved, Declined, Pending, Reversed"


def test_filters_are_immutable() -> None:
    filters = parse()

    with pytest.raises(AttributeError):
        filters.customer_id = "OTHER"  # type: ignore[misc]
