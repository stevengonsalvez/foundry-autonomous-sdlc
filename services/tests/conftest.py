from __future__ import annotations

import sys
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[2] / "agents"
for p in (AGENTS, AGENTS / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from conftest import World, world  # noqa: E402,F401  (agents/tests/conftest.py fixtures, reused)
