"""Domain errors: the only failures the agent is allowed to see.

Each message says what went wrong and what the agent should do next. Messages
never contain SQL, hostnames, driver output or other internal details.
"""

from typing import ClassVar


class DomainError(Exception):
    """Base class for agent-facing errors raised by use cases and value objects.

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


class DataSourceUnavailableError(_FixedMessageError):
    """The database can't be reached right now; retrying later may work."""

    MESSAGE: ClassVar[str] = (
        "Transaction data is temporarily unavailable. Tell the customer and "
        "offer to retry in a moment or hand off to a human agent."
    )


class SearchTooBroadError(_FixedMessageError):
    """The query exceeded a database limit; a narrower search may succeed."""

    MESSAGE: ClassVar[str] = (
        "The transaction search was too broad for the database. Retry with a "
        "narrower date range or add a card or merchant filter."
    )


class TransactionLookupError(_FixedMessageError):
    """The query failed for an internal reason; retrying won't help."""

    MESSAGE: ClassVar[str] = (
        "Transactions can't be retrieved right now due to an internal error. "
        "Don't retry; offer a hand-off to a human agent."
    )


class DataIntegrityError(_FixedMessageError):
    """A returned row couldn't be mapped to a domain entity."""

    MESSAGE: ClassVar[str] = (
        "Transaction data came back in an unexpected format. Don't retry; "
        "offer a hand-off to a human agent."
    )
