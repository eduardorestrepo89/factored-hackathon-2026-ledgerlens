"""Domain errors: the only failures the agent is allowed to see.

Each message says what went wrong and what the agent should do next. Messages
never contain SQL, hostnames, driver output, scores or other internal details.
"""

from typing import ClassVar


class DomainError(Exception):
    """Base class for errors whose message is safe to show the agent.

    Attributes:
        message: The agent-facing text.
    """

    def __init__(self, message: str) -> None:
        """Store the agent-facing message."""
        super().__init__(message)
        self.message: str = message


class InvalidInputError(DomainError):
    """A tool argument is missing or malformed.

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


class TransactionNotFoundError(_FixedMessageError):
    """No credit-card charge of this customer has the transaction_id."""

    MESSAGE: ClassVar[str] = (
        "No credit-card charge with this transaction_id belongs to this "
        "customer. Don't guess; ask the customer to confirm the charge, or "
        "call list_card_transactions to find it."
    )


class DataSourceUnavailableError(_FixedMessageError):
    """The database can't be reached right now; retrying later may work."""

    MESSAGE: ClassVar[str] = (
        "Transaction details are temporarily unavailable. Offer to retry in a "
        "moment or hand off to a human agent."
    )


class ExplainLookupError(_FixedMessageError):
    """The core query is missing, failed or hit a database limit."""

    MESSAGE: ClassVar[str] = (
        "The charge can't be explained right now due to an internal error. "
        "Don't retry; offer a hand-off to a human agent."
    )


class ExplainDataIntegrityError(_FixedMessageError):
    """The core row couldn't be mapped to a domain entity."""

    MESSAGE: ClassVar[str] = (
        "The charge's data came back in an unexpected format. Don't retry; "
        "offer a hand-off to a human agent."
    )
