"""Pytest setup for list_card_transactions: make its Lambda package importable.

The ``list_card_transactions_lambda`` package lives in the Lambda asset root
``gateway/tools/list_card_transactions``, so that folder is put on ``sys.path``
exactly as the Lambda runtime does.
"""

import sys
from pathlib import Path

_ASSET_ROOT = (
    Path(__file__).resolve().parents[3] / "gateway" / "tools" / "list_card_transactions"
)

if str(_ASSET_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASSET_ROOT))
