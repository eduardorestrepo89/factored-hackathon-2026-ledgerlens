"""Pytest setup for classify_call_type: make its Lambda package importable.

The ``classify_call_type_lambda`` package lives in the Lambda asset root
``gateway/tools/classify_call_type``, so that folder is put on ``sys.path``
exactly as the Lambda runtime does.
"""

import sys
from pathlib import Path

_ASSET_ROOT = (
    Path(__file__).resolve().parents[3] / "gateway" / "tools" / "classify_call_type"
)

if str(_ASSET_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASSET_ROOT))
