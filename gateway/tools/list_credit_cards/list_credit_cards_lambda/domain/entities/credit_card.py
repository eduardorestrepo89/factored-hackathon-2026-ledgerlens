"""Credit card entities returned by the list_credit_cards use case."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class CreditCard:
    """One of the customer's credit cards, as returned to the agent.

    Every field is ``| None`` because the source data has about 5% nulls; a card
    with a null column is still listed. ``product_status`` is a plain string
    because the database may hold values outside the four known ones. The
    internal ``product_id`` is never exposed; other tools address cards by
    ``card_last4``.
    """

    card_last4: str | None
    product_status: str | None
    currency: str | None
    current_balance: Decimal | None
    credit_limit: Decimal | None
    available_credit: Decimal | None
    expiration_date: date | None
    days_past_due: int | None


@dataclass(frozen=True)
class CreditCardsResult:
    """At most max_rows cards; truncated is True when more exist.

    ``cards`` is empty when the customer has no credit cards.
    """

    cards: tuple[CreditCard, ...]
    truncated: bool
