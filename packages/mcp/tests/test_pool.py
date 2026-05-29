"""Connection pool tests against the stdio mock MCP server."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from suitest_mcp.errors import McpPoolExhausted
from suitest_mcp.models import McpProviderConfig, McpTransport
from suitest_mcp.pool import McpPool

if TYPE_CHECKING:
    from mcp_server_mock import MockMcpServer

pytestmark = pytest.mark.asyncio


def _cfg(command: list[str], **overrides: Any) -> McpProviderConfig:
    return McpProviderConfig(
        id="prov-stdio-mock",
        workspace_id="ws",
        name="mock",
        kind="test",
        transport=McpTransport.STDIO,
        command=command,
        **overrides,
    )


async def test_pool_reuses_idle_session(mock_mcp_server: MockMcpServer) -> None:
    pool = McpPool()
    try:
        cfg = _cfg(mock_mcp_server.command, max_sessions=1)
        async with pool.acquire(cfg) as s1:
            await s1.call_tool("echo", {"i": 1}, timeout_seconds=10.0)
            invocations_first = s1.invocations
        async with pool.acquire(cfg) as s2:
            # Reused — invocations counter is sticky on the session object.
            assert s2.invocations == invocations_first
    finally:
        await pool.shutdown()


async def test_pool_caps_at_max_sessions(mock_mcp_server: MockMcpServer) -> None:
    pool = McpPool(queue_timeout_seconds=0.3)
    cfg = _cfg(mock_mcp_server.command, max_sessions=2)
    try:
        async with pool.acquire(cfg), pool.acquire(cfg):
            with pytest.raises(McpPoolExhausted):
                async with pool.acquire(cfg):
                    pass
    finally:
        await pool.shutdown()


async def test_pool_evicts_on_idle_ttl(mock_mcp_server: MockMcpServer) -> None:
    pool = McpPool()
    cfg = _cfg(mock_mcp_server.command, max_sessions=1, idle_ttl_seconds=0)
    try:
        async with pool.acquire(cfg) as s1:
            await s1.call_tool("echo", {}, timeout_seconds=10.0)
            invocations_first = s1.invocations
        # idle_ttl_seconds=0 means the session expires the moment it lands in
        # the idle deque — the next acquire MUST spawn a fresh session.
        async with pool.acquire(cfg) as s2:
            assert s2.invocations == 0
            assert s2 is not None
            # Reset counter proves it's not the same object.
            assert invocations_first >= 1
    finally:
        await pool.shutdown()


async def test_pool_recycles_session_on_exception(mock_mcp_server: MockMcpServer) -> None:
    pool = McpPool()
    cfg = _cfg(mock_mcp_server.command, max_sessions=1)
    try:
        with pytest.raises(RuntimeError):
            async with pool.acquire(cfg):
                raise RuntimeError("boom")
        # Session was destroyed — next acquire spawns fresh.
        async with pool.acquire(cfg) as s2:
            assert s2.invocations == 0
    finally:
        await pool.shutdown()


async def test_pool_workspace_cap(mock_mcp_server: MockMcpServer) -> None:
    pool = McpPool(queue_timeout_seconds=0.3, workspace_cap=1)
    try:
        cfg_a = _cfg(mock_mcp_server.command, max_sessions=2)
        # Second provider in the SAME workspace should be capped at the
        # workspace level even though each provider would individually allow
        # more sessions.
        cfg_b = McpProviderConfig(
            id="prov-stdio-mock-2",
            workspace_id="ws",
            name="mock-2",
            kind="test",
            transport=McpTransport.STDIO,
            command=mock_mcp_server.command,
            max_sessions=2,
        )
        async with pool.acquire(cfg_a):
            with pytest.raises(McpPoolExhausted):
                async with pool.acquire(cfg_b):
                    pass
    finally:
        await pool.shutdown()


async def test_pool_concurrent_acquires_serialise(mock_mcp_server: MockMcpServer) -> None:
    """Two concurrent acquires on a max-1 pool serialise via the condition."""
    pool = McpPool(queue_timeout_seconds=5.0)
    cfg = _cfg(mock_mcp_server.command, max_sessions=1)
    order: list[str] = []

    async def worker(label: str, delay: float) -> None:
        async with pool.acquire(cfg) as sess:
            order.append(f"enter:{label}")
            await sess.call_tool("echo", {"l": label}, timeout_seconds=10.0)
            await asyncio.sleep(delay)
            order.append(f"exit:{label}")

    try:
        await asyncio.gather(worker("a", 0.05), worker("b", 0.0))
    finally:
        await pool.shutdown()

    # The two workers must enter/exit in serialised order — no overlap.
    assert order[0].startswith("enter:")
    assert order[1].startswith("exit:") and order[1].split(":")[1] == order[0].split(":")[1]
    assert order[2].startswith("enter:")
    assert order[3].startswith("exit:") and order[3].split(":")[1] == order[2].split(":")[1]
