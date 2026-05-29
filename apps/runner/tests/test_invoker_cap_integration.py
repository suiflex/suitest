"""Workspace-cap integration test for :class:`McpInvoker` (M1c Task 21).

The pure-cap unit tests in ``packages/mcp/tests/test_workspace_cap.py`` cover
the queue semantics in isolation. This module exercises the *wiring*: an
``McpInvoker`` constructed with a :class:`WorkspacePoolCap` must serialise
8 parallel ``invoke()`` calls through a cap of 4 without ever exceeding the
ceiling — even though the underlying provider pool would happily grant more.

We sub in a fake :class:`McpPool` whose ``acquire`` increments a peak counter
on entry and decrements on exit, so the assertion is on the *actual* live
session count at the pool layer (i.e. the cap effectively constrains real
work, not just a hypothetical slot count). The pool's tool call simulates a
non-trivial step by sleeping briefly under ``asyncio.sleep``.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from suitest_mcp.invoker import InvokeContext, McpInvoker
from suitest_mcp.models import McpProviderConfig, McpToolResult, McpTransport
from suitest_mcp.registry import McpRegistry
from suitest_mcp.workspace_cap import WorkspacePoolCap
from suitest_shared.domain.enums import TargetKind

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.asyncio


# --- Fakes ---------------------------------------------------------------


class _PeakTrackingPool:
    """Stand-in for :class:`McpPool` that tracks live session count.

    Each ``acquire`` increments ``live`` on entry under a lock so we can
    capture an exact peak across overlapping coroutines. The yielded
    "session" is a MagicMock whose ``call_tool`` returns a fast
    :class:`McpToolResult` after a brief sleep — enough to force overlap
    between the 8 invokes in the stress test below.
    """

    def __init__(self) -> None:
        self.live = 0
        self.peak = 0
        self._lock = asyncio.Lock()

    @contextlib.asynccontextmanager
    async def acquire(self, _provider: McpProviderConfig) -> AsyncIterator[Any]:
        async with self._lock:
            self.live += 1
            if self.live > self.peak:
                self.peak = self.live

        async def _call_tool(
            tool: str,
            arguments: dict[str, object],
            *,
            timeout_seconds: float,
        ) -> McpToolResult:
            # Brief sleep so coroutines actually overlap inside the pool.
            await asyncio.sleep(0.02)
            return McpToolResult(ok=True, output={"tool": tool}, stdout="{}", duration_ms=20)

        sess = MagicMock()
        sess.call_tool = _call_tool
        try:
            yield sess
        finally:
            async with self._lock:
                self.live -= 1


class _RecordingRedis:
    async def publish(self, _channel: str, _payload: str) -> int:
        return 1


class _NullAuditSession:
    def add(self, _instance: object) -> None:
        return None

    async def commit(self) -> None:
        return None


class _NullAuditFactory:
    @contextlib.asynccontextmanager
    async def __call__(self) -> AsyncIterator[_NullAuditSession]:
        yield _NullAuditSession()


# --- Helpers --------------------------------------------------------------


def _provider() -> McpProviderConfig:
    return McpProviderConfig(
        id="prov-fake",
        workspace_id="ws-cap",
        name="fake",
        kind="test",
        transport=McpTransport.STDIO,
        command=["/bin/true"],
    )


def _registry_with(provider: McpProviderConfig) -> McpRegistry:
    reg = McpRegistry()
    reg._by_workspace[provider.workspace_id] = {provider.name: provider}
    return reg


def _ctx(workspace_id: str, idx: int) -> InvokeContext:
    return InvokeContext(
        workspace_id=workspace_id,
        target_kind=TargetKind.CUSTOM,
        run_id=f"run-{idx}",
        step_id=f"step-{idx}",
        actor_user_id="u1",
    )


# --- Tests ----------------------------------------------------------------


async def test_invoker_8_parallel_throttled_to_cap_4() -> None:
    """8 parallel invoke() coroutines, cap=4 → peak live ≤ 4 at the pool layer.

    This is the runner-shaped twin of
    ``test_concurrent_8_throttled_to_max_4`` in the MCP unit suite — the
    cap is wired through ``McpInvoker`` (not exercised in isolation) and the
    peak is measured at the *pool* boundary, proving the cap actually
    serialises real work and not just a hypothetical counter.
    """
    provider = _provider()
    registry = _registry_with(provider)
    pool = _PeakTrackingPool()
    cap = WorkspacePoolCap(max_per_workspace=4, queue_timeout_seconds=10.0)
    invoker = McpInvoker(
        registry=registry,
        pool=pool,  # type: ignore[arg-type]
        health=None,
        redis_client=_RecordingRedis(),  # type: ignore[arg-type]
        audit_session_factory=_NullAuditFactory(),
        workspace_cap=cap,
    )

    async def _one(i: int) -> McpToolResult:
        return await invoker.invoke(
            explicit_provider="fake",
            tool="t",
            arguments={"i": i},
            ctx=_ctx("ws-cap", i),
        )

    results = await asyncio.gather(*(_one(i) for i in range(8)))
    assert len(results) == 8
    assert all(r.ok for r in results)
    assert pool.peak <= 4, f"workspace cap not enforced — peak live was {pool.peak}"
    assert pool.peak >= 1
    # Counter drained.
    assert pool.live == 0
    assert cap.live("ws-cap") == 0


async def test_invoker_without_cap_runs_unthrottled() -> None:
    """No cap → invoker bypasses workspace serialisation (legacy path)."""
    provider = _provider()
    registry = _registry_with(provider)
    pool = _PeakTrackingPool()
    invoker = McpInvoker(
        registry=registry,
        pool=pool,  # type: ignore[arg-type]
        health=None,
        redis_client=_RecordingRedis(),  # type: ignore[arg-type]
        audit_session_factory=_NullAuditFactory(),
        workspace_cap=None,
    )

    async def _one(i: int) -> McpToolResult:
        return await invoker.invoke(
            explicit_provider="fake",
            tool="t",
            arguments={"i": i},
            ctx=_ctx("ws-cap", i),
        )

    results = await asyncio.gather(*(_one(i) for i in range(8)))
    assert len(results) == 8
    # Without the cap, peak can exceed 4 — we don't assert an exact number
    # because asyncio scheduling is non-deterministic, but the pool MUST have
    # admitted more than the cap value at least once to prove the cap is the
    # thing doing the throttling in the other test.
    assert pool.peak >= 5
