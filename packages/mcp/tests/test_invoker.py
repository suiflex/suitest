"""McpInvoker tests — pool + routing + audit + Redis events end-to-end.

These tests drive the invoker against the stdio mock MCP server. Redis pub/sub
is captured by an in-process recording stub (the same pattern as
:mod:`packages.mcp.tests.test_health`) so we can assert exact event payload
sequences without paying the cost of fakeredis's pub/sub event loop.

Audit is captured by a tiny stub session that records every ``add()`` —
``AuditLog`` rows accumulate in a list the tests can inspect. The real
SQLAlchemy + Postgres path is exercised in :mod:`packages.db.tests.test_audit`.

The two failure-path tests exercise :class:`McpToolTimeout` (via a 0.05s
``call_timeout_seconds`` against the mock's ``echo``, which we slow with a
sleep argument) and :class:`McpToolFailed` (via the mock's ``boom`` tool).
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import pytest
from suitest_mcp.errors import McpToolFailed, McpToolTimeout
from suitest_mcp.invoker import InvokeContext, McpInvoker
from suitest_mcp.models import McpProviderConfig, McpTransport
from suitest_mcp.pool import McpPool
from suitest_mcp.registry import McpRegistry
from suitest_shared.domain.enums import TargetKind

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from mcp_server_mock import MockMcpServer

pytestmark = pytest.mark.asyncio


# --- Test doubles ---------------------------------------------------------


class _RecordingRedis:
    """In-process Redis stub matching the ``publish`` method shape.

    Same pattern as :mod:`test_health` — sidesteps fakeredis pub/sub timing
    quirks under :data:`asyncio_mode = "strict"`.
    """

    def __init__(self) -> None:
        self.published: dict[str, list[str]] = {}

    async def publish(self, channel: str, payload: str) -> int:
        self.published.setdefault(channel, []).append(payload)
        return 1

    async def aclose(self) -> None:
        return None


class _RecordingAuditSession:
    """Captures every ``AuditLog`` row written via :func:`write_audit`."""

    def __init__(self, sink: list[Any]) -> None:
        self._sink = sink

    def add(self, instance: object) -> None:
        self._sink.append(instance)

    async def commit(self) -> None:
        return None


class _RecordingAuditFactory:
    """``async_sessionmaker``-shaped factory yielding recording sessions."""

    def __init__(self) -> None:
        self.rows: list[Any] = []

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[_RecordingAuditSession]:
        yield _RecordingAuditSession(self.rows)


# --- Builders -------------------------------------------------------------


def _registry_with(name: str, cfg: McpProviderConfig) -> McpRegistry:
    reg = McpRegistry()
    reg._by_workspace["ws"] = {name: cfg}
    return reg


def _mock_cfg(command: list[str], **overrides: Any) -> McpProviderConfig:
    return McpProviderConfig(
        id="builtin:mock",
        workspace_id="ws",
        name="mock",
        kind="test",
        transport=McpTransport.STDIO,
        command=command,
        **overrides,
    )


def _ctx(*, run_id: str | None = "r1", step_id: str | None = "s1") -> InvokeContext:
    return InvokeContext(
        workspace_id="ws",
        target_kind=TargetKind.CUSTOM,
        run_id=run_id,
        step_id=step_id,
        actor_user_id="u1",
    )


# --- Tests ----------------------------------------------------------------


async def test_invoker_emits_start_end_and_returns_ok(
    mock_mcp_server: MockMcpServer,
) -> None:
    """Happy path: explicit provider routing, echo tool, both events published."""
    reg = _registry_with("mock", _mock_cfg(mock_mcp_server.command))
    pool = McpPool()
    redis = _RecordingRedis()
    audit = _RecordingAuditFactory()
    invoker = McpInvoker(
        registry=reg,
        pool=pool,
        health=None,
        redis_client=redis,  # type: ignore[arg-type]
        audit_session_factory=audit,
    )
    try:
        result = await invoker.invoke(
            explicit_provider="mock",
            tool="echo",
            arguments={"x": 1},
            ctx=_ctx(),
        )
    finally:
        await pool.shutdown()

    assert result.ok is True
    messages = redis.published["run:r1"]
    events = [json.loads(m)["event"] for m in messages]
    assert events == ["mcp.tool.start", "mcp.tool.end"]
    end = json.loads(messages[1])["data"]
    assert end["outcome"] == "ok"
    assert end["error"] is None
    assert end["durationMs"] >= 0
    assert end["runId"] == "r1"
    assert end["stepId"] == "s1"


async def test_invoker_health_gated_raises_when_provider_down(
    mock_mcp_server: MockMcpServer,
) -> None:
    """Health monitor reporting non-routable → McpToolFailed, no pool acquire."""

    class _DownHealth:
        def is_routable(self, provider_id: str) -> bool:
            return False

    reg = _registry_with("mock", _mock_cfg(mock_mcp_server.command))
    pool = McpPool()
    redis = _RecordingRedis()
    audit = _RecordingAuditFactory()
    invoker = McpInvoker(
        registry=reg,
        pool=pool,
        health=_DownHealth(),  # type: ignore[arg-type]
        redis_client=redis,  # type: ignore[arg-type]
        audit_session_factory=audit,
    )
    try:
        with pytest.raises(McpToolFailed, match="auto-disabled"):
            await invoker.invoke(
                explicit_provider="mock",
                tool="echo",
                arguments={},
                ctx=_ctx(),
            )
    finally:
        await pool.shutdown()

    # Gated calls short-circuit BEFORE the start event / audit row.
    assert "run:r1" not in redis.published
    assert audit.rows == []


async def test_invoker_records_audit_row_on_success(
    mock_mcp_server: MockMcpServer,
) -> None:
    """Every successful invoke appends exactly one ``mcp.invoke`` AuditLog row."""
    from suitest_db.models.audit import AuditLog

    reg = _registry_with("mock", _mock_cfg(mock_mcp_server.command))
    pool = McpPool()
    audit = _RecordingAuditFactory()
    invoker = McpInvoker(
        registry=reg,
        pool=pool,
        health=None,
        redis_client=_RecordingRedis(),  # type: ignore[arg-type]
        audit_session_factory=audit,
    )
    try:
        await invoker.invoke(
            explicit_provider="mock",
            tool="echo",
            arguments={"hello": "world"},
            ctx=_ctx(),
        )
    finally:
        await pool.shutdown()

    assert len(audit.rows) == 1
    row = audit.rows[0]
    assert isinstance(row, AuditLog)
    assert row.workspace_id == "ws"
    assert row.user_id == "u1"
    assert row.action == "mcp.invoke"
    assert row.resource_type == "mcp_provider"
    assert row.resource_id == "mock"
    meta = row.metadata_json
    assert isinstance(meta, dict)
    assert meta["tool"] == "echo"
    assert meta["outcome"] == "ok"
    assert meta["run_id"] == "r1"
    assert meta["step_id"] == "s1"
    # arg_hash is deterministic sha256 of sorted-JSON arguments.
    assert isinstance(meta["arg_hash"], str)
    assert len(meta["arg_hash"]) == 64


async def test_invoker_publishes_timeout_event_on_mcp_tool_timeout(
    mock_mcp_server: MockMcpServer,
) -> None:
    """A timeout during call_tool → ``mcp.tool.end`` with outcome=timeout, raised."""
    # Force the timeout by setting call_timeout_seconds to a tiny value AND
    # giving the mock a payload large enough that the round-trip is non-trivial.
    # Easier route: monkeypatch the session's call_tool to raise McpToolTimeout
    # directly. We do that by routing through a custom McpPool subclass that
    # yields a session whose call_tool is overridden.
    reg = _registry_with("mock", _mock_cfg(mock_mcp_server.command))
    pool = McpPool()
    audit = _RecordingAuditFactory()
    redis = _RecordingRedis()
    invoker = McpInvoker(
        registry=reg,
        pool=pool,
        health=None,
        redis_client=redis,  # type: ignore[arg-type]
        audit_session_factory=audit,
    )

    # Patch the underlying session class's call_tool to raise McpToolTimeout
    # — keeps the invoker code path under test (routing + publish + audit +
    # re-raise) while skipping the actual SDK timeout race.
    async def _raise_timeout(
        self: Any, tool: str, arguments: dict[str, Any], *, timeout_seconds: float
    ) -> Any:
        raise McpToolTimeout(f"tool {tool} timed out after {timeout_seconds}s")

    from suitest_mcp.client import McpSession

    original = McpSession.call_tool
    McpSession.call_tool = _raise_timeout  # type: ignore[method-assign]
    try:
        with pytest.raises(McpToolTimeout):
            await invoker.invoke(
                explicit_provider="mock",
                tool="echo",
                arguments={"x": 1},
                ctx=_ctx(),
            )
    finally:
        McpSession.call_tool = original  # type: ignore[method-assign]
        await pool.shutdown()

    events = [json.loads(m)["event"] for m in redis.published["run:r1"]]
    assert events == ["mcp.tool.start", "mcp.tool.end"]
    end = json.loads(redis.published["run:r1"][1])["data"]
    assert end["outcome"] == "timeout"
    assert end["error"] is not None
    # Audit row still landed for the failure path.
    assert len(audit.rows) == 1
    assert audit.rows[0].metadata_json["outcome"] == "timeout"


async def test_invoker_publishes_failed_event_on_mcp_tool_failed(
    mock_mcp_server: MockMcpServer,
) -> None:
    """``boom`` tool returns isError=true → ``McpToolFailed``, outcome=failed."""
    reg = _registry_with("mock", _mock_cfg(mock_mcp_server.command))
    pool = McpPool()
    audit = _RecordingAuditFactory()
    redis = _RecordingRedis()
    invoker = McpInvoker(
        registry=reg,
        pool=pool,
        health=None,
        redis_client=redis,  # type: ignore[arg-type]
        audit_session_factory=audit,
    )
    try:
        with pytest.raises(McpToolFailed):
            await invoker.invoke(
                explicit_provider="mock",
                tool="boom",
                arguments={},
                ctx=_ctx(),
            )
    finally:
        await pool.shutdown()

    events = [json.loads(m)["event"] for m in redis.published["run:r1"]]
    assert events == ["mcp.tool.start", "mcp.tool.end"]
    end = json.loads(redis.published["run:r1"][1])["data"]
    assert end["outcome"] == "failed"
    assert end["error"] is not None
    assert len(audit.rows) == 1
    assert audit.rows[0].metadata_json["outcome"] == "failed"


async def test_invoker_skips_publish_when_no_run_id(
    mock_mcp_server: MockMcpServer,
) -> None:
    """Out-of-run invocations (no run_id) MUST NOT publish — but still audit."""
    reg = _registry_with("mock", _mock_cfg(mock_mcp_server.command))
    pool = McpPool()
    audit = _RecordingAuditFactory()
    redis = _RecordingRedis()
    invoker = McpInvoker(
        registry=reg,
        pool=pool,
        health=None,
        redis_client=redis,  # type: ignore[arg-type]
        audit_session_factory=audit,
    )
    try:
        result = await invoker.invoke(
            explicit_provider="mock",
            tool="echo",
            arguments={"k": "v"},
            ctx=_ctx(run_id=None, step_id=None),
        )
    finally:
        await pool.shutdown()

    assert result.ok is True
    assert redis.published == {}
    assert len(audit.rows) == 1
    assert audit.rows[0].metadata_json["run_id"] is None
