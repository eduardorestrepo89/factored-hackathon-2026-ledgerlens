"""Pytest setup for block_credit_card: make its Lambda package importable.

The ``block_credit_card_lambda`` package lives in the Lambda asset root
``gateway/tools/block_credit_card``, so that folder is put on ``sys.path``
exactly as the Lambda runtime does.
"""

import sys
from pathlib import Path

_ASSET_ROOT = (
    Path(__file__).resolve().parents[3] / "gateway" / "tools" / "block_credit_card"
)

if str(_ASSET_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASSET_ROOT))
