"""Pytest setup for open_claim: make its Lambda package importable.

The ``open_claim_lambda`` package lives in the Lambda asset root
``gateway/tools/open_claim``, so that folder is put on ``sys.path``
exactly as the Lambda runtime does.
"""

import sys
from pathlib import Path

_ASSET_ROOT = Path(__file__).resolve().parents[3] / "gateway" / "tools" / "open_claim"

if str(_ASSET_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASSET_ROOT))
