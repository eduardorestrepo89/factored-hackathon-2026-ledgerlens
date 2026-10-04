"""Candidates: the rows each query returns, mapped before the reason rules run."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class TransactionCandidate:
    """A credit-card charge from the last 72 hours, or a 30-day scored one.

    fraud_score is used for banding only and is never presented.
    """

    transaction_id: str
    transaction_date: datetime | None
    card_last4: str | None
    card_currency: str | None
    merchant_name: str | None
    amount: Decimal | None
    currency: str | None
    transaction_status: str | None
    response_code: str | None
    transaction_country: str | None
    home_country: str | None
    fraud_score: Decimal | None


@dataclass(frozen=True)
class CardCandidate:
    """One of the customer's credit cards, de-duplicated to its latest state."""

    card_last4: str
    product_status: str | None
    expiration_date: date | None
    days_past_due: int | None


@dataclass(frozen=True)
class CaseCandidate:
    """A complaint open at as_of; sla_breached NULL counts as not breached.

    creation_date makes a case created in the last 7 days weigh more, and breaks
    ties between equal cases (the newest wins, spec section 6.3); it is never
    presented.
    """

    complaint_id: str
    case_type: str | None
    category: str | None
    subcategory: str | None
    status: str | None
    sla_breached: bool | None
    days_open: int | None
    creation_date: datetime | None


@dataclass(frozen=True)
class AppEventCandidate:
    """A digital event of type 'Error' from the last 24 hours."""

    event_id: str
    event_date: datetime | None
    page_title: str | None
    action: str | None
