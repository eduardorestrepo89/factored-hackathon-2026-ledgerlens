"""Card transaction entities returned by the list_card_transactions use case."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class CardTransaction:
    """A single card transaction as returned to the agent.

    Nullable columns are ``| None`` because the source data has about 5% nulls.
    ``transaction_status`` is a plain string, not TransactionStatus, because the
    database may hold values outside the three filterable ones.
    """

    transaction_id: str
    transaction_date: datetime
    card_last4: str
    amount: Decimal
    currency: str | None
    transaction_status: str | None
    merchant_name: str | None
    merchant_category: str | None
    channel: str | None
    transaction_city: str | None
    transaction_country: str | None


@dataclass(frozen=True)
class CardTransactionsResult:
    """The outcome of a transaction search, capped at a maximum number of rows.

    Attributes:
        transactions: Matching transactions, newest first.
        truncated: True when more matches exist than were returned.
    """

    transactions: tuple[CardTransaction, ...]
    truncated: bool
