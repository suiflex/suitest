"""Shared pytest setup for the agent test suite.

Makes the sibling helper modules in this directory (``security_agent``,
``a11y_agent``) importable under ``--import-mode=importlib``, which does NOT
add test dirs to ``sys.path`` (same pattern as ``apps/api/tests/conftest.py``).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
