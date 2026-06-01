"""Discovery probe tests (M2-7) — connect + tools/list against the stdio mock."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_mcp.discovery import McpDiscoveryError, discover_provider
from suitest_mcp.models import McpProviderConfig, McpTransport

if TYPE_CHECKING:
    from mcp_server_mock import MockMcpServer

pytestmark = pytest.mark.asyncio


def _cfg(command: list[str]) -> McpProviderConfig:
    return McpProviderConfig(
        id="probe",
        workspace_id="w1",
        name="mock",
        kind="test",
        transport=McpTransport.STDIO,
        command=command,
        spawn_timeout_seconds=15.0,
    )


async def test_discover_returns_tool_catalog(mock_mcp_server: MockMcpServer) -> None:
    result = await discover_provider(_cfg(mock_mcp_server.command))
    names = {t.name for t in result.tools}
    assert {"echo", "boom"} <= names
    # Every tool carries its advertised input schema.
    echo = next(t for t in result.tools if t.name == "echo")
    assert echo.input_schema == {"type": "object"}


async def test_discover_bad_command_raises(tmp_path_factory: pytest.TempPathFactory) -> None:
    missing = tmp_path_factory.mktemp("nope") / "does_not_exist.py"
    import sys

    with pytest.raises(McpDiscoveryError):
        await discover_provider(_cfg([sys.executable, str(missing)]))
