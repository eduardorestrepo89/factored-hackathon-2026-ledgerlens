"""Tests for the call classification presenter (spec section 5)."""

import dataclasses
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest
from classify_call_type_lambda.delivery.presenters.call_classification import (
    present_call_classification,
)
from classify_call_type_lambda.domain.entities.call_classification import (
    CallClassification,
    Candidate,
    RankedReason,
)
from classify_call_type_lambda.domain.entities.candidates import (
    AppEventCandidate,
    CardCandidate,
    CaseCandidate,
    TransactionCandidate,
)
from classify_call_type_lambda.domain.value_objects.call_reasons import CallReason

from .fakes import CHARGE_DATE, TRANSACTION_ID

pytestmark = pytest.mark.unit

R = CallReason
TODAY = date(2026, 6, 17)

# Spec section 5, verbatim: P07's flagged charge as the agent sees it.
P07_JSON = """
{
  "reasons": [
    {
      "reason": "FRAUD_SUSPECTED",
      "confidence": 0.77,
      "ref_id": "TRX-23BIJAU4GL46ATPW9STY",
      "evidence": {
        "transaction_date": "2026-05-31T06:09:15",
        "card_last4": "4497",
        "merchant_name": "Estación de Servicio",
        "amount": "288.69",
        "currency": "USD",
        "transaction_status": "Approved"
      }
    }
  ],
  "unavailable": []
}
"""

CHARGE = TransactionCandidate(
    transaction_id=TRANSACTION_ID,
    transaction_date=CHARGE_DATE,
    card_last4="4497",
    card_currency="USD",
    merchant_name="Estación de Servicio",
    amount=Decimal("288.69"),
    currency="USD",
    transaction_status="Approved",
    response_code="00",
    transaction_country="México",
    home_country="México",
    fraud_score=Decimal("62.37"),
)
CARD = CardCandidate(
    card_last4="7718",
    product_status="Active",
    expiration_date=date(2026, 7, 1),
    days_past_due=45,
)
CASE = CaseCandidate(
    complaint_id="CMP-FHCLR8TGWMBD0YFOCLYS",
    case_type="Claim",
    category="Cards",
    subcategory="Unrecognized charge",
    status="In Progress",
    sla_breached=None,
    days_open=12,
    creation_date=datetime(2026, 6, 5, 9, 30),
)
EVENT = AppEventCandidate(
    event_id="EVT-0001",
    event_date=datetime(2026, 6, 17, 21, 59, 59),
    page_title="Pagar Servicios",
    action="submit_payment",
)

TRANSACTION_KEYS = {
    "transaction_date",
    "card_last4",
    "merchant_name",
    "amount",
    "currency",
    "transaction_status",
}
EVIDENCE_KEYS: dict[CallReason, set[str]] = {
    R.FRAUD_SUSPECTED: TRANSACTION_KEYS,
    R.DECLINED_TRANSACTION: TRANSACTION_KEYS | {"response_code"},
    R.UNRECOGNIZED_CHARGE_REVIEW: TRANSACTION_KEYS,
    R.OPEN_CASE_FOLLOWUP: {
        "case_type",
        "category",
        "subcategory",
        "status",
        "sla_breached",
        "days_open",
    },
    R.PENDING_TRANSACTION: TRANSACTION_KEYS,
    R.REVERSED_TRANSACTION: TRANSACTION_KEYS,
    R.CARD_NOT_ACTIVE: {"card_last4", "product_status"},
    R.FAILED_APP_ACTION: {"event_date", "page_title", "action"},
    R.FOREIGN_TRANSACTION: TRANSACTION_KEYS
    | {"transaction_country", "home_country", "card_currency"},
    R.PAYMENT_OVERDUE: {"card_last4", "days_past_due"},
    R.CARD_EXPIRING: {"card_last4", "expiration_date", "days_left"},
}
CANDIDATE_OF: dict[CallReason, Candidate] = {
    R.FRAUD_SUSPECTED: CHARGE,
    R.DECLINED_TRANSACTION: CHARGE,
    R.UNRECOGNIZED_CHARGE_REVIEW: CHARGE,
    R.OPEN_CASE_FOLLOWUP: CASE,
    R.PENDING_TRANSACTION: CHARGE,
    R.REVERSED_TRANSACTION: CHARGE,
    R.CARD_NOT_ACTIVE: CARD,
    R.FAILED_APP_ACTION: EVENT,
    R.FOREIGN_TRANSACTION: CHARGE,
    R.PAYMENT_OVERDUE: CARD,
    R.CARD_EXPIRING: CARD,
}
REF_ID_OF: dict[type, str] = {
    TransactionCandidate: TRANSACTION_ID,
    CaseCandidate: "CMP-FHCLR8TGWMBD0YFOCLYS",
    CardCandidate: "7718",
    AppEventCandidate: "EVT-0001",
}


def ranked(
    reason: CallReason,
    candidate: Candidate | None = None,
    confidence: str = "0.77",
) -> RankedReason:
    """Rank one reason over its default candidate."""
    candidate = candidate or CANDIDATE_OF[reason]
    return RankedReason(
        reason=reason,
        confidence=Decimal(confidence),
        ref_id=REF_ID_OF[type(candidate)],
        candidate=candidate,
    )


def present(
    *reasons: RankedReason, unavailable: tuple[CallReason, ...] = ()
) -> dict[str, Any]:
    """Present a classification as of TODAY."""
    return present_call_classification(
        CallClassification(reasons=reasons, unavailable=unavailable, as_of_date=TODAY)
    )


def evidence(item: RankedReason) -> dict[str, Any]:
    """Present one reason and return its evidence."""
    return present(item)["reasons"][0]["evidence"]


def keys(value: object) -> set[str]:
    """Return every dict key at any depth."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys(v)}
    return set()


# --- the whole body ----------------------------------------------------------


def test_p07_matches_the_spec_example() -> None:
    assert present(ranked(R.FRAUD_SUSPECTED)) == json.loads(P07_JSON)


def test_nothing_found_is_two_empty_lists() -> None:
    assert present() == {"reasons": [], "unavailable": []}


def test_unavailable_lists_the_reason_names_in_order() -> None:
    body = present(unavailable=(R.OPEN_CASE_FOLLOWUP, R.FAILED_APP_ACTION))

    assert body["unavailable"] == ["OPEN_CASE_FOLLOWUP", "FAILED_APP_ACTION"]


def test_reasons_keep_their_order() -> None:
    body = present(
        ranked(R.DECLINED_TRANSACTION, confidence="0.84"),
        ranked(R.OPEN_CASE_FOLLOWUP, confidence="0.60"),
        ranked(R.CARD_EXPIRING, confidence="0.35"),
    )

    assert [item["reason"] for item in body["reasons"]] == [
        "DECLINED_TRANSACTION",
        "OPEN_CASE_FOLLOWUP",
        "CARD_EXPIRING",
    ]
    assert [item["ref_id"] for item in body["reasons"]] == [
        TRANSACTION_ID,
        "CMP-FHCLR8TGWMBD0YFOCLYS",
        "7718",
    ]


def test_output_survives_a_json_round_trip() -> None:
    body = present(*(ranked(reason) for reason in CallReason))

    assert json.loads(json.dumps(body, ensure_ascii=False)) == body


# --- confidence -------------------------------------------------------------


@pytest.mark.parametrize(
    ("confidence", "expected"), [("0.60", 0.6), ("0.77", 0.77), ("1.00", 1.0)]
)
def test_confidence_is_a_json_number(confidence: str, expected: float) -> None:
    value = present(ranked(R.FRAUD_SUSPECTED, confidence=confidence))["reasons"][0][
        "confidence"
    ]

    assert type(value) is float
    assert value == expected


# --- evidence ---------------------------------------------------------------


@pytest.mark.parametrize("reason", list(CallReason))
def test_evidence_keys_per_reason(reason: CallReason) -> None:
    assert set(evidence(ranked(reason))) == EVIDENCE_KEYS[reason]


def test_declined_evidence_has_the_response_code() -> None:
    charge = dataclasses.replace(
        CHARGE, transaction_status="Declined", response_code="51"
    )

    assert evidence(ranked(R.DECLINED_TRANSACTION, charge)) == {
        "transaction_date": "2026-05-31T06:09:15",
        "card_last4": "4497",
        "merchant_name": "Estación de Servicio",
        "amount": "288.69",
        "currency": "USD",
        "transaction_status": "Declined",
        "response_code": "51",
    }


def test_foreign_evidence_has_both_countries_and_the_card_currency() -> None:
    charge = dataclasses.replace(
        CHARGE, transaction_country="Brasil", currency="BRL", card_currency="USD"
    )

    found = evidence(ranked(R.FOREIGN_TRANSACTION, charge))

    assert found["transaction_country"] == "Brasil"
    assert found["home_country"] == "México"
    assert found["currency"] == "BRL"
    assert found["card_currency"] == "USD"


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("288.685"), "288.69"),
        (Decimal("288.684"), "288.68"),
        (Decimal("1E+3"), "1000.00"),
        (Decimal("12"), "12.00"),
        (None, None),
    ],
)
def test_amounts_are_two_decimal_strings(
    amount: Decimal | None, expected: str | None
) -> None:
    charge = dataclasses.replace(CHARGE, amount=amount)

    assert evidence(ranked(R.FRAUD_SUSPECTED, charge))["amount"] == expected


def test_missing_transaction_values_stay_null() -> None:
    charge = TransactionCandidate(
        transaction_id=TRANSACTION_ID,
        transaction_date=None,
        card_last4=None,
        card_currency=None,
        merchant_name=None,
        amount=None,
        currency=None,
        transaction_status=None,
        response_code=None,
        transaction_country=None,
        home_country=None,
        fraud_score=None,
    )

    found = evidence(ranked(R.FOREIGN_TRANSACTION, charge))

    assert set(found.values()) == {None}


def test_case_evidence() -> None:
    assert evidence(ranked(R.OPEN_CASE_FOLLOWUP)) == {
        "case_type": "Claim",
        "category": "Cards",
        "subcategory": "Unrecognized charge",
        "status": "In Progress",
        "sla_breached": None,
        "days_open": 12,
    }


def test_card_not_active_evidence() -> None:
    card = dataclasses.replace(CARD, product_status="Blocked")

    assert evidence(ranked(R.CARD_NOT_ACTIVE, card)) == {
        "card_last4": "7718",
        "product_status": "Blocked",
    }


def test_payment_overdue_evidence() -> None:
    assert evidence(ranked(R.PAYMENT_OVERDUE)) == {
        "card_last4": "7718",
        "days_past_due": 45,
    }


@pytest.mark.parametrize(
    ("expiration_date", "iso", "days_left"),
    [
        (date(2026, 6, 17), "2026-06-17", 0),
        (date(2026, 6, 18), "2026-06-18", 1),
        (date(2026, 7, 17), "2026-07-17", 30),
        (None, None, None),
    ],
)
def test_card_expiring_days_left(
    expiration_date: date | None, iso: str | None, days_left: int | None
) -> None:
    card = dataclasses.replace(CARD, expiration_date=expiration_date)

    assert evidence(ranked(R.CARD_EXPIRING, card)) == {
        "card_last4": "7718",
        "expiration_date": iso,
        "days_left": days_left,
    }


def test_app_event_evidence() -> None:
    assert evidence(ranked(R.FAILED_APP_ACTION)) == {
        "event_date": "2026-06-17T21:59:59",
        "page_title": "Pagar Servicios",
        "action": "submit_payment",
    }


def test_no_key_mentions_fraud_or_score() -> None:
    body = present(*(ranked(reason) for reason in CallReason))

    all_keys = keys(body)
    assert "days_left" in all_keys  # the walk reached the evidence
    assert not [key for key in all_keys if "fraud" in key or "score" in key]
    assert "62.37" not in json.dumps(body)  # the score's value isn't leaked either
