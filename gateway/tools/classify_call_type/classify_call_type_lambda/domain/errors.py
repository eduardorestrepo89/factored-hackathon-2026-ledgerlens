"""Domain errors: the only failures the agent is allowed to see.

Each message says what went wrong and what the agent should do next. Messages
never contain SQL, hostnames, driver output, scores or other internal details.
A failed candidate query is not an error: its reasons are listed in
``unavailable``. Only a failure of all four queries is.
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


class DataSourceUnavailableError(_FixedMessageError):
    """All four queries failed and at least one couldn't connect."""

    MESSAGE: ClassVar[str] = (
        "Call reasons are temporarily unavailable. Greet the customer and ask "
        "how you can help."
    )


class CallReasonLookupError(_FixedMessageError):
    """All four queries failed, none of them on the connection."""

    MESSAGE: ClassVar[str] = (
        "Call reasons can't be computed right now due to an internal error. "
        "Don't retry; greet the customer and ask how you can help."
    )
