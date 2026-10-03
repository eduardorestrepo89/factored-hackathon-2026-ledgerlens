"""Pytest setup for explain_transaction: make its Lambda package importable.

The ``explain_transaction_lambda`` package lives in the Lambda asset root
``gateway/tools/explain_transaction``, so that folder is put on ``sys.path``
exactly as the Lambda runtime does.
"""

import sys
from pathlib import Path

_ASSET_ROOT = (
    Path(__file__).resolve().parents[3] / "gateway" / "tools" / "explain_transaction"
)

if str(_ASSET_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASSET_ROOT))
