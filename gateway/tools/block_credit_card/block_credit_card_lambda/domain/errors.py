"""Domain errors: the only failures the agent is allowed to see.

Each message says what went wrong and what the agent should do next. Messages
never contain SQL, hostnames, driver output or other internal details; the
card-named ones carry only the 4 digits the agent sent, after validation.
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


class _CardMessageError(DomainError):
    """Base for errors whose message names the card's last 4 digits."""

    TEMPLATE: ClassVar[str] = ""

    def __init__(self, card_last4: str) -> None:
        """Fill the class-level TEMPLATE with the validated last 4 digits."""
        self.card_last4: str = card_last4
        super().__init__(self.TEMPLATE.format(last4=card_last4))


class CardNotFoundError(_CardMessageError):
    """No credit card of this customer ends in these digits."""

    TEMPLATE: ClassVar[str] = (
        "No credit card ending in {last4} was found for this customer. Check the "
        "card with list_credit_cards and confirm it with the customer."
    )


class AmbiguousCardError(_CardMessageError):
    """More than one of the customer's credit cards ends in these digits."""

    TEMPLATE: ClassVar[str] = (
        "More than one of the customer's credit cards ends in {last4}, so it "
        "can't be blocked here. Don't retry; offer an urgent hand-off to a "
        "human agent."
    )


class CardClosedError(_CardMessageError):
    """The card is closed: it can't be charged, so there is nothing to block."""

    TEMPLATE: ClassVar[str] = (
        "The card ending in {last4} is closed, so it can't be charged and needs "
        "no block. Tell the customer."
    )


class DataSourceUnavailableError(_FixedMessageError):
    """The database can't be reached right now; retrying later may work."""

    MESSAGE: ClassVar[str] = (
        "The card service is temporarily unavailable. Tell the customer and "
        "offer to retry in a moment or hand off to a human agent."
    )


class CardUpdateError(_FixedMessageError):
    """A query failed, or the card couldn't be blocked; retrying won't help."""

    MESSAGE: ClassVar[str] = (
        "The card couldn't be blocked due to an internal error. Don't retry; "
        "offer an urgent hand-off to a human agent."
    )


class CardDataIntegrityError(_FixedMessageError):
    """A returned row couldn't be read."""

    MESSAGE: ClassVar[str] = (
        "Card data came back in an unexpected format. Don't retry; offer an "
        "urgent hand-off to a human agent."
    )
