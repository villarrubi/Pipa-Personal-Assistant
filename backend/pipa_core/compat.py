"""Import bridge for the existing Windows Agent modules.

The core is kept under ``backend`` while the current Windows integration
remains under ``windows-agent``. This small bridge keeps both launch modes
working until the shared packages are split into installable distributions.
"""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_windows_agent_importable() -> None:
    agent_root = Path(__file__).resolve().parents[2] / "windows-agent"
    if str(agent_root) not in sys.path:
        sys.path.insert(0, str(agent_root))
