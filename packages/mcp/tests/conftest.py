"""Shared fixtures for ``packages/mcp/tests``.

``--import-mode=importlib`` does not put the tests directory on ``sys.path``, so
sibling helper modules (e.g. ``mcp_server_mock``) are not importable from test
files by default. We add the tests directory to ``sys.path`` here so tests can
``from mcp_server_mock import MockMcpServer`` without a tests/__init__.py.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from mcp_server_mock import MockMcpServer  # noqa: E402


@pytest.fixture
def mock_mcp_server(tmp_path: Path) -> Iterator[MockMcpServer]:
    """Materialise the stdio mock MCP server script for one test.

    Function-scoped because :func:`tmp_path` is function-scoped. Writing the
    script is < 1 KB so the overhead is negligible.
    """
    yield MockMcpServer(tmp_path)
