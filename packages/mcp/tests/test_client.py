"""Generic MCP client transport + lifecycle tests against the stdio mock."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from suitest_mcp.client import open_session
from suitest_mcp.errors import McpHandshakeFailed, McpToolFailed, McpToolTimeout
from suitest_mcp.models import McpProviderConfig, McpTransport

if TYPE_CHECKING:
    from mcp_server_mock import MockMcpServer

pytestmark = pytest.mark.asyncio


def _cfg(command: list[str], **overrides: Any) -> McpProviderConfig:
    return McpProviderConfig(
        id="p1",
        workspace_id="w1",
        name="mock",
        kind="test",
        transport=McpTransport.STDIO,
        command=command,
        **overrides,
    )


async def test_open_session_lists_tools(mock_mcp_server: MockMcpServer) -> None:
    sess = await open_session(_cfg(mock_mcp_server.command))
    try:
        tools = await sess.list_tools()
    finally:
        await sess.cleanup()
    names = {t["name"] for t in tools}
    assert "echo" in names
    assert "boom" in names


async def test_call_tool_returns_result(mock_mcp_server: MockMcpServer) -> None:
    sess = await open_session(_cfg(mock_mcp_server.command))
    try:
        result = await sess.call_tool("echo", {"hello": "world"}, timeout_seconds=10.0)
    finally:
        await sess.cleanup()
    assert result.ok
    assert "ECHO" in result.stdout
    assert "hello" in result.stdout
    assert result.duration_ms >= 0
    assert sess.invocations == 1


async def test_call_tool_failure_raises(mock_mcp_server: MockMcpServer) -> None:
    sess = await open_session(_cfg(mock_mcp_server.command))
    try:
        with pytest.raises(McpToolFailed):
            await sess.call_tool("boom", {}, timeout_seconds=10.0)
    finally:
        await sess.cleanup()


async def test_call_tool_timeout(mock_mcp_server: MockMcpServer) -> None:
    sess = await open_session(_cfg(mock_mcp_server.command))
    try:
        with pytest.raises((McpToolTimeout, asyncio.CancelledError)):
            await sess.call_tool("echo", {}, timeout_seconds=0.0001)
    finally:
        await sess.cleanup()


async def test_open_session_handshake_failure_raises() -> None:
    """A non-existent binary must raise McpHandshakeFailed (not bubble OSError)."""
    cfg = _cfg(["/nonexistent/path/to/mcp-binary"], spawn_timeout_seconds=2.0)
    with pytest.raises(McpHandshakeFailed):
        await open_session(cfg)


async def test_stdio_without_command_raises() -> None:
    cfg = McpProviderConfig(
        id="x",
        workspace_id="w",
        name="bad",
        kind="test",
        transport=McpTransport.STDIO,
    )
    with pytest.raises(McpHandshakeFailed):
        await open_session(cfg)
