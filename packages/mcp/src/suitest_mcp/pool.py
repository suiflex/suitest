"""Per-provider connection pool with LRU + TTL + max-sessions cap.

Each :class:`McpProviderConfig.id` gets its own :class:`_ProviderPool` instance,
held inside a top-level :class:`McpPool`. Pools are created lazily on first
acquire under a single registry-wide ``_lock`` (so two simultaneous acquires for
the same provider id share one pool rather than racing).

Concurrency model per pool:
* A ``deque`` of idle sessions (newest at the right, oldest at the left).
* ``live`` counts spawned-but-not-cleaned sessions.
* A single ``asyncio.Condition`` arbitrates everything: waiters wake when a
  session is returned or a slot frees up.
* Acquire path:
    1. Pop the freshest idle session; drop it if its idle TTL has elapsed.
    2. If under ``max_sessions``, reserve a slot (``live += 1``) and spawn.
    3. Otherwise wait on the condition with the remaining queue budget; raise
       :class:`McpPoolExhausted` if the budget is exhausted.
* Spawning happens OUTSIDE the condition lock to avoid blocking the whole
  pool while ``open_session`` performs IO; failure releases the reserved slot.

Workspace cap (``SUITEST_MCP_MAX_SESSIONS_PER_WORKSPACE``, default 16) is
enforced lazily: ``McpPool`` tracks the total ``live`` count per workspace
across every provider it owns. The cap blocks new acquisitions but does not
shrink existing pools (idle TTL handles cleanup).
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import os
import time
from typing import TYPE_CHECKING

import structlog

from suitest_mcp.client import McpSession, open_session
from suitest_mcp.errors import McpPoolExhausted

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from suitest_mcp.models import McpProviderConfig

log = structlog.get_logger(__name__)

_DEFAULT_WORKSPACE_CAP_ENV = "SUITEST_MCP_MAX_SESSIONS_PER_WORKSPACE"
_DEFAULT_WORKSPACE_CAP = 16


def _resolve_workspace_cap() -> int:
    raw = os.environ.get(_DEFAULT_WORKSPACE_CAP_ENV)
    if not raw:
        return _DEFAULT_WORKSPACE_CAP
    try:
        value = int(raw)
    except ValueError:
        log.warning("mcp.pool.invalid_workspace_cap", value=raw)
        return _DEFAULT_WORKSPACE_CAP
    return max(1, value)


class _ProviderPool:
    """Single provider's session pool. Owned by :class:`McpPool`."""

    def __init__(self, provider: McpProviderConfig) -> None:
        self.provider = provider
        self.idle: collections.deque[McpSession] = collections.deque()
        self.live = 0
        self.cond = asyncio.Condition()

    async def acquire(self, *, queue_timeout: float) -> McpSession:
        """Pop an idle session or spawn a new one, respecting ``max_sessions``.

        Returns immediately if an idle session is available, otherwise waits on
        the condition with a budget of ``queue_timeout`` seconds. Raises
        :class:`McpPoolExhausted` when the budget is exhausted.
        """
        deadline = time.monotonic() + queue_timeout
        async with self.cond:
            while True:
                # Drain stale idle sessions first.
                while self.idle:
                    sess = self.idle.pop()
                    if time.monotonic() - sess.last_used_at > self.provider.idle_ttl_seconds:
                        await sess.cleanup()
                        self.live -= 1
                        self.cond.notify()
                        continue
                    return sess
                if self.live < self.provider.max_sessions:
                    self.live += 1
                    break
                wait_time = deadline - time.monotonic()
                if wait_time <= 0:
                    raise McpPoolExhausted(f"pool exhausted for {self.provider.name}")
                try:
                    await asyncio.wait_for(self.cond.wait(), timeout=wait_time)
                except TimeoutError as exc:
                    raise McpPoolExhausted(
                        f"timed out waiting for session on {self.provider.name}"
                    ) from exc

        # Spawn outside the lock so a slow open doesn't block the pool.
        try:
            sess = await open_session(self.provider)
        except BaseException:
            async with self.cond:
                self.live -= 1
                self.cond.notify_all()
            raise
        return sess

    async def release(self, sess: McpSession, *, recycle: bool = False) -> None:
        """Return a session to the idle deque, or destroy it if ``recycle`` is set.

        ``recycle`` should be ``True`` when the caller's tool invocation raised —
        we cannot reuse a session whose underlying transport may be in an
        unknown state.
        """
        async with self.cond:
            cap_value = self.provider.config_json.get("max_requests_per_session", 1000)
            try:
                max_invocations = int(cap_value)
            except (TypeError, ValueError):
                max_invocations = 1000
            destroy = recycle or sess.invocations >= max_invocations
            if destroy:
                self.live -= 1
            else:
                sess.last_used_at = time.monotonic()
                self.idle.append(sess)
            self.cond.notify()
        # Cleanup OUTSIDE the lock — torn-down sessions can take time.
        if destroy:
            with contextlib.suppress(Exception):
                await sess.cleanup()

    async def shutdown(self) -> None:
        async with self.cond:
            sessions = list(self.idle)
            self.idle.clear()
            self.live -= len(sessions)
            self.cond.notify_all()
        for sess in sessions:
            with contextlib.suppress(Exception):
                await sess.cleanup()


class McpPool:
    """Top-level pool registry — one :class:`_ProviderPool` per provider id."""

    def __init__(
        self,
        *,
        queue_timeout_seconds: float = 30.0,
        workspace_cap: int | None = None,
    ) -> None:
        self._pools: dict[str, _ProviderPool] = {}
        self._lock = asyncio.Lock()
        self.queue_timeout_seconds = queue_timeout_seconds
        self._workspace_cap = workspace_cap or _resolve_workspace_cap()

    async def _get_pool(self, provider: McpProviderConfig) -> _ProviderPool:
        async with self._lock:
            pool = self._pools.get(provider.id)
            if pool is None:
                pool = _ProviderPool(provider)
                self._pools[provider.id] = pool
            return pool

    def _workspace_live(self, workspace_id: str) -> int:
        return sum(
            pool.live for pool in self._pools.values() if pool.provider.workspace_id == workspace_id
        )

    @contextlib.asynccontextmanager
    async def acquire(self, provider: McpProviderConfig) -> AsyncIterator[McpSession]:
        """Lease one session for the duration of the ``async with`` block.

        Raises:
            McpPoolExhausted: provider's own pool is full *or* the workspace
                cap is hit and remains hit until the queue timeout elapses.
        """
        pool = await self._get_pool(provider)
        # Workspace cap is enforced via a busy-poll with the same deadline as the
        # per-provider queue timeout; the alternative (a workspace-level
        # Condition) couples every provider's pool to every other. Pragmatic
        # trade-off — caps fire rarely in practice (most workspaces have <16
        # active sessions at peak).
        deadline = time.monotonic() + self.queue_timeout_seconds
        while self._workspace_live(provider.workspace_id) >= self._workspace_cap:
            if time.monotonic() >= deadline:
                raise McpPoolExhausted(
                    f"workspace cap reached ({self._workspace_cap}) for {provider.workspace_id}"
                )
            await asyncio.sleep(0.05)
        sess = await pool.acquire(queue_timeout=self.queue_timeout_seconds)
        recycle = False
        try:
            yield sess
        except Exception:
            recycle = True
            raise
        finally:
            await pool.release(sess, recycle=recycle)

    async def shutdown(self) -> None:
        async with self._lock:
            pools = list(self._pools.values())
            self._pools.clear()
        for pool in pools:
            await pool.shutdown()
