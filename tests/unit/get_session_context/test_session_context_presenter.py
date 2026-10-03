"""Tests for the session context presenter."""

import dataclasses
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from get_session_context_lambda.delivery.presenters.session_context import (
    present_session_context,
)
from get_session_context_lambda.domain.entities.session_context import (
    CreditCard,
    Customer,
    DigitalSignal,
    OpenCase,
    RecentTransaction,
    Section,
    SessionContext,
    TransactionFlag,
)

pytestmark = pytest.mark.unit

AS_OF = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
CUSTOMER = Customer(
    customer_id="CLI-ITIECUE8PRH9",
    first_name="Ana",
    country="Colombia",
    city="Bogotá",
    customer_status="Active",
)
CARD = CreditCard(
    card_last4="4821",
    product_status="Active",
    currency="COP",
    current_balance=Decimal("1250000.00"),
    credit_limit=Decimal("3000000.00"),
    available_credit=Decimal("1750000.00"),
    expiration_date=date(2027, 3, 31),
    days_past_due=0,
)
TRANSACTION = RecentTransaction(
    transaction_id="TX-1",
    transaction_date=datetime(2026, 3, 14, 10, 42),
    card_last4="4821",
    merchant_name="EXITO",
    amount=Decimal("350000.00"),
    currency="COP",
    transaction_status="Declined",
    transaction_country="Colombia",
    flags=(TransactionFlag.DECLINED, TransactionFlag.ABOVE_USUAL_AMOUNT),
)
SIGNAL = DigitalSignal(
    event_date=datetime(2026, 3, 14, 10, 48),
    signal="FAILED_ACTION",
    page_title="Tarjeta de Crédito",
    ip_country="Colombia",
    ip_city="Bogotá",
)
CASE = OpenCase(
    complaint_id="C-1182",
    case_type="Claim",
    category="Transactions",
    subcategory="Cargo no reconocido",
    status="Open",
    priority="High",
    sla_breached=False,
    claimed_amount=Decimal("350000.00"),
    currency="COP",
    days_open=3,
)


def make_context(**overrides: Any) -> SessionContext:
    """Build a full SessionContext; keyword arguments replace fields."""
    values: dict[str, Any] = {
        "as_of": AS_OF,
        "customer": CUSTOMER,
        "cards": (CARD,),
        "recent_transactions": (TRANSACTION,),
        "digital_signals": (SIGNAL,),
        "open_cases": (CASE,),
        "truncated": (),
        "unavailable": (),
    }
    values.update(overrides)
    return SessionContext(**values)


def test_presents_the_full_snapshot() -> None:
    assert present_session_context(make_context()) == {
        "as_of": "2026-03-14T12:00:00Z",
        "customer": {
            "customer_id": "CLI-ITIECUE8PRH9",
            "first_name": "Ana",
            "country": "Colombia",
            "city": "Bogotá",
            "customer_status": "Active",
        },
        "cards": [
            {
                "card_last4": "4821",
                "product_status": "Active",
                "currency": "COP",
                "current_balance": "1250000.00",
                "credit_limit": "3000000.00",
                "available_credit": "1750000.00",
                "expiration_date": "2027-03-31",
                "days_past_due": 0,
            }
        ],
        "recent_transactions": [
            {
                "transaction_id": "TX-1",
                "transaction_date": "2026-03-14T10:42:00",
                "card_last4": "4821",
                "merchant_name": "EXITO",
                "amount": "350000.00",
                "currency": "COP",
                "transaction_status": "Declined",
                "transaction_country": "Colombia",
                "flags": ["declined", "above_usual_amount"],
            }
        ],
        "digital_signals": [
            {
                "event_date": "2026-03-14T10:48:00",
                "signal": "FAILED_ACTION",
                "page_title": "Tarjeta de Crédito",
                "ip_country": "Colombia",
                "ip_city": "Bogotá",
            }
        ],
        "open_cases": [
            {
                "complaint_id": "C-1182",
                "case_type": "Claim",
                "category": "Transactions",
                "subcategory": "Cargo no reconocido",
                "status": "Open",
                "priority": "High",
                "sla_breached": False,
                "claimed_amount": "350000.00",
                "currency": "COP",
                "days_open": 3,
            }
        ],
        "truncated": [],
        "unavailable": [],
    }


@pytest.mark.parametrize(
    "as_of",
    [
        datetime(2026, 3, 14, 12, 0, 0, 123456, tzinfo=timezone.utc),
        datetime(2026, 3, 14, 7, 0, tzinfo=timezone(timedelta(hours=-5))),
    ],
    ids=["microseconds", "other-zone"],
)
def test_as_of_is_utc_with_a_z_and_whole_seconds(as_of: datetime) -> None:
    assert present_session_context(make_context(as_of=as_of))["as_of"] == (
        "2026-03-14T12:00:00Z"
    )


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("0.005"), "0.01"),
        (Decimal("2.345"), "2.35"),
        (Decimal("10"), "10.00"),
        (Decimal("-1.005"), "-1.01"),
    ],
)
def test_amounts_are_rounded_half_up_to_two_decimals(
    amount: Decimal, expected: str
) -> None:
    context = make_context(
        cards=(dataclasses.replace(CARD, current_balance=amount),),
        recent_transactions=(dataclasses.replace(TRANSACTION, amount=amount),),
        open_cases=(dataclasses.replace(CASE, claimed_amount=amount),),
    )

    body = present_session_context(context)

    assert body["cards"][0]["current_balance"] == expected
    assert body["recent_transactions"][0]["amount"] == expected
    assert body["open_cases"][0]["claimed_amount"] == expected


def test_missing_values_are_null() -> None:
    context = make_context(
        customer=dataclasses.replace(CUSTOMER, first_name=None, city=None),
        cards=(
            dataclasses.replace(
                CARD, current_balance=None, expiration_date=None, days_past_due=None
            ),
        ),
        recent_transactions=(
            dataclasses.replace(
                TRANSACTION, transaction_date=None, amount=None, flags=()
            ),
        ),
        digital_signals=(dataclasses.replace(SIGNAL, event_date=None, ip_city=None),),
        open_cases=(
            dataclasses.replace(
                CASE, sla_breached=None, claimed_amount=None, days_open=None
            ),
        ),
    )

    body = present_session_context(context)

    assert body["customer"]["first_name"] is None
    assert body["customer"]["city"] is None
    card = body["cards"][0]
    assert (
        card["current_balance"],
        card["expiration_date"],
        card["days_past_due"],
    ) == (
        None,
        None,
        None,
    )
    transaction = body["recent_transactions"][0]
    assert transaction["transaction_date"] is None
    assert transaction["amount"] is None
    assert transaction["flags"] == []
    assert body["digital_signals"][0]["event_date"] is None
    case = body["open_cases"][0]
    assert (case["sla_breached"], case["claimed_amount"], case["days_open"]) == (
        None,
        None,
        None,
    )


def test_empty_sections_are_empty_lists() -> None:
    body = present_session_context(
        make_context(
            cards=(), recent_transactions=(), digital_signals=(), open_cases=()
        )
    )

    for section in Section:
        assert body[section.value] == []
    assert body["unavailable"] == []


def test_unavailable_sections_are_null_and_named() -> None:
    body = present_session_context(
        make_context(
            recent_transactions=None,
            open_cases=None,
            unavailable=(Section.RECENT_TRANSACTIONS, Section.OPEN_CASES),
        )
    )

    assert body["recent_transactions"] is None
    assert body["open_cases"] is None
    assert body["cards"] is not None
    assert body["unavailable"] == ["recent_transactions", "open_cases"]


def test_truncated_sections_are_named() -> None:
    body = present_session_context(
        make_context(truncated=(Section.CARDS, Section.DIGITAL_SIGNALS))
    )

    assert body["truncated"] == ["cards", "digital_signals"]


def test_the_body_is_json_serialisable() -> None:
    text = json.dumps(present_session_context(make_context()), ensure_ascii=False)

    assert "Bogotá" in text
    assert json.loads(text)["as_of"] == "2026-03-14T12:00:00Z"
