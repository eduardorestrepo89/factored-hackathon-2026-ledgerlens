"""Pytest setup for get_session_context: make its Lambda package importable.

The ``get_session_context_lambda`` package lives in the Lambda asset root
``gateway/tools/get_session_context``, so that folder is put on ``sys.path``
exactly as the Lambda runtime does.
"""

import sys
from pathlib import Path

_ASSET_ROOT = (
    Path(__file__).resolve().parents[3] / "gateway" / "tools" / "get_session_context"
)

if str(_ASSET_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASSET_ROOT))
