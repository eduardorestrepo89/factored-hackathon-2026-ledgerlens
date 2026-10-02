"""Pytest setup for list_credit_cards: make its Lambda package importable.

The ``list_credit_cards_lambda`` package lives in the Lambda asset root
``gateway/tools/list_credit_cards``, so that folder is put on ``sys.path``
exactly as the Lambda runtime does.
"""

import sys
from pathlib import Path

_ASSET_ROOT = (
    Path(__file__).resolve().parents[3] / "gateway" / "tools" / "list_credit_cards"
)

if str(_ASSET_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASSET_ROOT))
