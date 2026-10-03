"""Session context entities returned by the get_session_context use case.

Every field that comes from a nullable column is ``| None``: the source data has
about 5% nulls, and a row with a null column is still returned.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum


@dataclass(frozen=True)
class Customer:
    """The customer's profile, without any sensitive column.

    ``customer_id`` is never None: it is the row's key.
    """

    customer_id: str
    first_name: str | None
    country: str | None
    city: str | None
    customer_status: str | None


@dataclass(frozen=True)
class CreditCard:
    """One of the customer's credit cards (the same fields as list_credit_cards).

    ``product_status`` is a plain string because the database may hold values
    outside the four known ones. The internal ``product_id`` is never exposed;
    other tools address cards by ``card_last4``.
    """

    card_last4: str | None
    product_status: str | None
    currency: str | None
    current_balance: Decimal | None
    credit_limit: Decimal | None
    available_credit: Decimal | None
    expiration_date: date | None
    days_past_due: int | None


class TransactionFlag(str, Enum):
    """A risk flag on a recent transaction, declared in output order."""

    DECLINED = "declined"
    FOREIGN = "foreign"
    ABOVE_USUAL_AMOUNT = "above_usual_amount"
    NEW_MERCHANT = "new_merchant"


@dataclass(frozen=True)
class RecentTransaction:
    """A credit-card transaction from the 72 hours up to as_of.

    ``flags`` holds only the flags that are true, in enum order.
    """

    transaction_id: str | None
    transaction_date: datetime | None
    card_last4: str | None
    merchant_name: str | None
    amount: Decimal | None
    currency: str | None
    transaction_status: str | None
    transaction_country: str | None
    flags: tuple[TransactionFlag, ...]


@dataclass(frozen=True)
class DigitalSignal:
    """An app/web event from the 24 hours up to as_of that carries a signal.

    ``signal`` is never None, because rows without one are filtered in SQL. It's
    a plain string: the SQL owns the mapping and the contract test pins the four
    values.
    """

    event_date: datetime | None
    signal: str
    page_title: str | None
    ip_country: str | None
    ip_city: str | None


@dataclass(frozen=True)
class OpenCase:
    """A complaint or claim that is open at as_of."""

    complaint_id: str | None
    case_type: str | None
    category: str | None
    subcategory: str | None
    status: str | None
    priority: str | None
    sla_breached: bool | None
    claimed_amount: Decimal | None
    currency: str | None
    days_open: int | None


class Section(str, Enum):
    """A snapshot section that can fail on its own, declared in output order.

    Each value is the name of the SessionContext attribute that holds it.
    """

    CARDS = "cards"
    RECENT_TRANSACTIONS = "recent_transactions"
    DIGITAL_SIGNALS = "digital_signals"
    OPEN_CASES = "open_cases"


@dataclass(frozen=True)
class SessionContext:
    """The customer's snapshot at as_of.

    A section is None when it couldn't be loaded; it is then listed in
    ``unavailable``. An empty tuple means there is nothing. ``truncated`` lists
    the sections that had more rows than their cap. Both lists are in enum order.
    """

    as_of: datetime
    customer: Customer
    cards: tuple[CreditCard, ...] | None
    recent_transactions: tuple[RecentTransaction, ...] | None
    digital_signals: tuple[DigitalSignal, ...] | None
    open_cases: tuple[OpenCase, ...] | None
    truncated: tuple[Section, ...]
    unavailable: tuple[Section, ...]
