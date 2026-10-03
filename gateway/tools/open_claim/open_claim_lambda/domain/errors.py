"""Domain errors: the only failures the agent is allowed to see.

Each message says what went wrong and what the agent should do next. Messages
never contain SQL, hostnames, driver output or other internal details; the only
variable text is transaction ids the agent sent, after validation.
"""

from collections.abc import Sequence
from typing import ClassVar


class DomainError(Exception):
    """Base class for agent-facing errors raised by the use case.

    Attributes:
        message: Agent-facing text describing the failure and the next step.
    """

    def __init__(self, message: str) -> None:
        """Store the agent-facing message."""
        super().__init__(message)
        self.message: str = message


class InvalidInputError(DomainError):
    """A tool argument failed validation.

    Attributes:
        field: Name of the offending tool argument.
        reason: Short human-readable rule that was broken.
    """

    def __init__(self, field: str, reason: str) -> None:
        """Build the message from the field name and the broken rule."""
        self.field: str = field
        self.reason: str = reason
        super().__init__(
            f"Invalid value for '{field}': {reason}. "
            "Ask the customer to confirm and retry."
        )


class _FixedMessageError(DomainError):
    """Base for domain errors whose message never varies."""

    MESSAGE: ClassVar[str] = ""

    def __init__(self) -> None:
        """Use the class-level MESSAGE as the agent-facing message."""
        super().__init__(self.MESSAGE)


class TransactionsNotFoundError(DomainError):
    """Some requested ids aren't among the customer's credit card transactions.

    Attributes:
        transaction_ids: The missing ids, as the agent sent them (cleaned).
    """

    def __init__(self, transaction_ids: Sequence[str]) -> None:
        """Name the missing ids in the message."""
        self.transaction_ids: tuple[str, ...] = tuple(transaction_ids)
        super().__init__(
            "These transactions weren't found among the customer's credit card "
            f"transactions: {', '.join(self.transaction_ids)}. Check them with "
            "list_card_transactions and retry."
        )


class DataSourceUnavailableError(_FixedMessageError):
    """The database can't be reached right now; retrying later may work."""

    MESSAGE: ClassVar[str] = (
        "The claim service is temporarily unavailable. Tell the customer and "
        "offer to retry in a moment or hand off to a human agent."
    )


class ClaimError(_FixedMessageError):
    """A query failed; retrying won't help."""

    MESSAGE: ClassVar[str] = (
        "The claim couldn't be opened due to an internal error. Don't retry; "
        "offer a hand-off to a human agent."
    )


class ClaimDataIntegrityError(_FixedMessageError):
    """A returned transaction row couldn't be read."""

    MESSAGE: ClassVar[str] = (
        "Transaction data came back in an unexpected format. Don't retry; "
        "offer a hand-off to a human agent."
    )
