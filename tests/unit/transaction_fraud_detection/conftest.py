"""Pytest setup for transaction_fraud_detection: make its Lambda package importable.

The ``transaction_fraud_detection_lambda`` package lives in the Lambda asset root
``gateway/tools/transaction_fraud_detection``, so that folder is put on
``sys.path`` exactly as the Lambda runtime does.
"""

import sys
from pathlib import Path

_ASSET_ROOT = (
    Path(__file__).resolve().parents[3]
    / "gateway"
    / "tools"
    / "transaction_fraud_detection"
)

if str(_ASSET_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASSET_ROOT))
