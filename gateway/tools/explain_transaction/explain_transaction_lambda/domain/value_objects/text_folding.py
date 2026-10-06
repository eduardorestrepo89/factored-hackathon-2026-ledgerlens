"""Fold text so country names compare equal regardless of accents, case or spaces."""

import unicodedata


def fold_text(value: str | None) -> str | None:
    """Return ``value`` without accents, case-folded and stripped; None stays None.

    "México" and " MEXICO " both fold to "mexico" (D21). The habit SQL does the
    same comparison with translate() and the list_card_transactions mapping.
    """
    if value is None:
        return None
    decomposed = unicodedata.normalize("NFKD", value)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return plain.casefold().strip()
