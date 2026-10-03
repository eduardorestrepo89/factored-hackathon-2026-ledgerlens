"""Pytest setup for human_agent_hand_off: make its Lambda package importable.

The ``human_agent_hand_off_lambda`` package lives in the Lambda asset root
``gateway/tools/human_agent_hand_off``, so that folder is put on ``sys.path``
exactly as the Lambda runtime does.
"""

import sys
from pathlib import Path

_ASSET_ROOT = (
    Path(__file__).resolve().parents[3] / "gateway" / "tools" / "human_agent_hand_off"
)

if str(_ASSET_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASSET_ROOT))
