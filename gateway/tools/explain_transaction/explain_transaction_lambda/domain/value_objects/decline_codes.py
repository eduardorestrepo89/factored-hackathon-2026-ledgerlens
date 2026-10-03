"""What each decline response code means, and which channels are in person.

The response codes in the data are 00, 05, 14, 51, 54 and NULL; declined rows
carry only the last four, or NULL. An unknown code has no meaning here, and the
agent is shown the code with a null meaning.
"""

from collections.abc import Mapping
from typing import Final

DECLINE_MEANINGS: Final[Mapping[str, str]] = {
    "05": "declined by the issuer, no specific reason",
    "14": "invalid card number",
    "51": "insufficient available credit",
    "54": "expired card",
}

# The code whose meaning can contradict the card's own expiration date (D18).
EXPIRED_CARD_CODE: Final = "54"

# The transaction channels where the card is physically present. App and Web
# charges can come from anywhere, so they never conflict with app activity.
IN_PERSON_CHANNELS: Final = frozenset({"ATM", "POS", "Branch"})
