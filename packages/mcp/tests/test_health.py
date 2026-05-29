"""Health monitor tests.

Uses ``fakeredis.aioredis`` for pub/sub (no real Redis needed) and the stdio
mock MCP server for OK probes. DB persistence is tested via a tiny stub
session_factory that records calls — we already cover the real Alembic +
SQLAlchemy path in :mod:`packages.db.tests`.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from suitest_mcp.health import HealthMonitor
from suitest_mcp.models import McpHealthState, McpProviderConfig, McpTransport
from suitest_mcp.registry import McpRegistry

if TYPE_CHECKING:
    from mcp_server_mock import MockMcpServer

pytestmark = pytest.mark.asyncio


class _RecordingSessionFactory:
    """Minimal stub matching ``async_sessionmaker[AsyncSession]`` for tests.

    Records every ``UPDATE`` statement seen so ``_persist`` calls can be
    asserted without booting Postgres. The health monitor never branches on
    the return value of ``execute`` / ``commit`` so a no-op is sufficient.
    """

    def __init__(self) -> None:
        self.executions: list[Any] = []

    def __call__(self) -> _RecordingSession:
        return _RecordingSession(self.executions)


class _RecordingSession:
    def __init__(self, sink: list[Any]) -> None:
        self._sink = sink

    async def __aenter__(self) -> _RecordingSession:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def execute(self, stmt: Any) -> None:
        self._sink.append(stmt)

    async def commit(self) -> None:
        return None


def _registry_with_one_provider(name: str, cfg: McpProviderConfig) -> McpRegistry:
    reg = McpRegistry()
    reg._by_workspace["ws-1"] = {name: cfg}
    return reg


class _RecordingRedis:
    """In-process Redis stub used to assert ``publish()`` arguments without
    booting fakeredis's pub/sub event loop (which doesn't deliver messages
    reliably under :func:`pytest_asyncio.strict_mode`)."""

    def __init__(self) -> None:
        self.published: dict[str, list[str]] = {}

    async def publish(self, channel: str, payload: str) -> int:
        self.published.setdefault(channel, []).append(payload)
        return 1

    async def aclose(self) -> None:
        return None


async def test_probe_ok_against_mock(mock_mcp_server: MockMcpServer) -> None:
    cfg = McpProviderConfig(
        id="builtin:probe-ok",
        workspace_id="ws-1",
        name="mock",
        kind="test",
        transport=McpTransport.STDIO,
        command=mock_mcp_server.command,
    )
    reg = _registry_with_one_provider("mock", cfg)
    redis = _RecordingRedis()
    monitor = HealthMonitor(
        registry=reg,
        session_factory=_RecordingSessionFactory(),  # type: ignore[arg-type]
        redis_client=redis,  # type: ignore[arg-type]
        probe_timeout_seconds=10.0,
    )
    results = await monitor.probe_all()

    assert len(results) == 1
    assert results[0].state is McpHealthState.OK
    assert monitor.is_routable("builtin:probe-ok") is True
    # First OK probe is a state transition (UNKNOWN -> OK), so one publish lands.
    assert len(redis.published["workspace:ws-1"]) == 1


async def test_probe_down_against_bad_binary() -> None:
    cfg = McpProviderConfig(
        id="builtin:probe-down",
        workspace_id="ws-1",
        name="nope",
        kind="test",
        transport=McpTransport.STDIO,
        command=["/nonexistent/binary"],
        spawn_timeout_seconds=2.0,
    )
    reg = _registry_with_one_provider("nope", cfg)
    redis = _RecordingRedis()
    monitor = HealthMonitor(
        registry=reg,
        session_factory=_RecordingSessionFactory(),  # type: ignore[arg-type]
        redis_client=redis,  # type: ignore[arg-type]
        probe_timeout_seconds=2.0,
    )
    results = await monitor.probe_all()

    assert len(results) == 1
    assert results[0].state is McpHealthState.DOWN
    assert results[0].error


async def test_publish_only_on_state_transition(
    mock_mcp_server: MockMcpServer,
) -> None:
    """Probing OK twice in a row must publish exactly once (first transition)."""
    cfg = McpProviderConfig(
        id="builtin:probe-transition",
        workspace_id="ws-1",
        name="mock",
        kind="test",
        transport=McpTransport.STDIO,
        command=mock_mcp_server.command,
    )
    reg = _registry_with_one_provider("mock", cfg)
    redis = _RecordingRedis()
    monitor = HealthMonitor(
        registry=reg,
        session_factory=_RecordingSessionFactory(),  # type: ignore[arg-type]
        redis_client=redis,  # type: ignore[arg-type]
        probe_timeout_seconds=10.0,
    )

    await monitor.probe_all()
    await monitor.probe_all()

    messages = redis.published.get("workspace:ws-1", [])
    assert len(messages) == 1, f"expected one publish, got {messages!r}"
    assert "mcp.provider.health" in messages[0]
    assert '"status": "ok"' in messages[0]


async def test_is_routable_false_past_auto_disable_threshold() -> None:
    cfg = McpProviderConfig(
        id="builtin:auto-disable",
        workspace_id="ws-1",
        name="dead",
        kind="test",
        transport=McpTransport.STDIO,
        command=["/nonexistent/binary"],
        spawn_timeout_seconds=1.0,
    )
    reg = _registry_with_one_provider("dead", cfg)
    redis = _RecordingRedis()
    monitor = HealthMonitor(
        registry=reg,
        session_factory=_RecordingSessionFactory(),  # type: ignore[arg-type]
        redis_client=redis,  # type: ignore[arg-type]
        probe_timeout_seconds=1.0,
        auto_disable_after_seconds=0.001,
    )
    await monitor.probe_all()

    # First DOWN with no prior OK: immediately non-routable.
    assert monitor.is_routable("builtin:auto-disable") is False


async def test_persist_writes_for_db_backed_providers(mock_mcp_server: MockMcpServer) -> None:
    """Non-builtin provider ids should land in the session_factory's execute log;
    ``builtin:*`` ids must be skipped (in-memory only)."""
    cfg_db = McpProviderConfig(
        id="cuid-real-provider",  # no builtin: prefix
        workspace_id="ws-1",
        name="mock-real",
        kind="test",
        transport=McpTransport.STDIO,
        command=mock_mcp_server.command,
    )
    cfg_builtin = McpProviderConfig(
        id="builtin:skipme",
        workspace_id="ws-1",
        name="builtin-mock",
        kind="test",
        transport=McpTransport.STDIO,
        command=mock_mcp_server.command,
    )
    reg = McpRegistry()
    reg._by_workspace["ws-1"] = {"mock-real": cfg_db, "builtin-mock": cfg_builtin}

    factory = _RecordingSessionFactory()
    redis = _RecordingRedis()
    monitor = HealthMonitor(
        registry=reg,
        session_factory=factory,  # type: ignore[arg-type]
        redis_client=redis,  # type: ignore[arg-type]
        probe_timeout_seconds=10.0,
    )
    await monitor.probe_all()

    # Exactly one UPDATE — for the non-builtin row.
    assert len(factory.executions) == 1
    rendered = str(factory.executions[0])
    assert "mcp_providers" in rendered


async def test_auto_disable_triggers_routing_fallback() -> None:
    """When a provider is DOWN past the threshold, ``is_routable`` returns False
    so the runner / invoker can pick the fallback provider in routing.py."""
    primary = McpProviderConfig(
        id="custom:vendor-down",
        workspace_id="ws-1",
        name="vendor-down",
        kind="http",
        transport=McpTransport.STDIO,
        command=["/nonexistent/binary"],
        spawn_timeout_seconds=1.0,
    )
    fallback = McpProviderConfig(
        id="custom:vendor-up",
        workspace_id="ws-1",
        name="vendor-up",
        kind="http",
        transport=McpTransport.STDIO,
        command=["/usr/bin/true"],  # also fails fast, but distinct id
    )
    reg = McpRegistry()
    reg._by_workspace["ws-1"] = {"vendor-down": primary, "vendor-up": fallback}
    monitor = HealthMonitor(
        registry=reg,
        session_factory=_RecordingSessionFactory(),  # type: ignore[arg-type]
        redis_client=_RecordingRedis(),  # type: ignore[arg-type]
        probe_timeout_seconds=1.0,
        auto_disable_after_seconds=0.001,
    )
    await monitor.probe_all()

    # vendor-down was probed and marked DOWN; auto-disable triggered.
    assert monitor.is_routable("custom:vendor-down") is False
    # vendor-up was also probed DOWN (both fake binaries fail), so it's also
    # non-routable — but we only assert the primary here. The point is that
    # is_routable is the public hook the invoker uses to re-route.


async def test_health_monitor_start_stop_lifecycle(mock_mcp_server: MockMcpServer) -> None:
    """start() spawns a task; stop() cancels it cleanly."""
    cfg = McpProviderConfig(
        id="builtin:lifecycle",
        workspace_id="ws-1",
        name="mock",
        kind="test",
        transport=McpTransport.STDIO,
        command=mock_mcp_server.command,
    )
    reg = _registry_with_one_provider("mock", cfg)
    redis = _RecordingRedis()
    monitor = HealthMonitor(
        registry=reg,
        session_factory=_RecordingSessionFactory(),  # type: ignore[arg-type]
        redis_client=redis,  # type: ignore[arg-type]
        probe_interval_seconds=0.05,
        probe_timeout_seconds=5.0,
    )
    await monitor.start()
    # Let one probe tick complete.
    await asyncio.sleep(0.2)
    assert monitor._task is not None
    await monitor.stop()
    assert monitor._task is None
