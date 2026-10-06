"""Domain errors: the only failures the agent is allowed to see.

Each message says what went wrong and what the agent should do next. Messages
never contain SQL, hostnames, driver output or other internal details.
"""

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


class DataSourceUnavailableError(_FixedMessageError):
    """The database can't be reached right now; retrying later may work."""

    MESSAGE: ClassVar[str] = (
        "Card data is temporarily unavailable. Tell the customer and offer "
        "to retry in a moment or hand off to a human agent."
    )


class CardLookupError(_FixedMessageError):
    """The query failed or hit a database limit; retrying won't help.

    A limit error gets this message too: the query has no filter the agent
    could narrow.
    """

    MESSAGE: ClassVar[str] = (
        "The customer's cards can't be retrieved right now due to an internal "
        "error. Don't retry; offer a hand-off to a human agent."
    )


class CardDataIntegrityError(_FixedMessageError):
    """A returned row couldn't be mapped to a domain entity."""

    MESSAGE: ClassVar[str] = (
        "Card data came back in an unexpected format. Don't retry; offer a "
        "hand-off to a human agent."
    )
