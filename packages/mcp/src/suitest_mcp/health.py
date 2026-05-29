"""Background MCP health monitor.

A single ``asyncio.Task`` ticks every ``PROBE_INTERVAL_SECONDS`` and, for every
provider registered across every workspace, opens a fresh session and runs a
``list_tools()`` smoke. The result is one of:

* ``OK`` — tools returned at least one entry.
* ``DEGRADED`` — handshake succeeded but ``tools/list`` returned an empty list.
* ``DOWN`` — anything raised (handshake failed, transport died, etc).

The monitor persists ``health_status`` + ``last_health_at`` on the
``mcp_providers`` row (only for non-bundled providers — builtin specs live in
process memory and are never persisted). On every *state transition* (not on
every probe), it publishes ``mcp.provider.health`` on the workspace's Redis
channel ``workspace:<id>`` so the M1c WS gateway can fan-out to live UIs.

Routing auto-disable: :meth:`is_routable` returns ``False`` once a provider has
been DOWN longer than :data:`AUTO_DISABLE_AFTER_SECONDS` (5 minutes) so the
runner / invoker can fall through to a different provider rather than retry a
known-dead one. ``OK`` resets the timer.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import update

from suitest_mcp.client import open_session
from suitest_mcp.models import McpHealthState, McpHealthStatus

if TYPE_CHECKING:
    from redis.asyncio import Redis as AsyncRedis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from suitest_mcp.models import McpProviderConfig
    from suitest_mcp.registry import McpRegistry

log = structlog.get_logger(__name__)

PROBE_INTERVAL_SECONDS = 60
PROBE_TIMEOUT_SECONDS = 5.0
AUTO_DISABLE_AFTER_SECONDS = 300


class HealthMonitor:
    """Async background probe + DB updater + Redis publisher."""

    def __init__(
        self,
        *,
        registry: McpRegistry,
        session_factory: async_sessionmaker[AsyncSession],
        redis_client: AsyncRedis,
        probe_interval_seconds: float = PROBE_INTERVAL_SECONDS,
        probe_timeout_seconds: float = PROBE_TIMEOUT_SECONDS,
        auto_disable_after_seconds: float = AUTO_DISABLE_AFTER_SECONDS,
    ) -> None:
        self.registry = registry
        self.session_factory = session_factory
        self.redis = redis_client
        self.probe_interval_seconds = probe_interval_seconds
        self.probe_timeout_seconds = probe_timeout_seconds
        self.auto_disable_after_seconds = auto_disable_after_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._last_ok_monotonic: dict[str, float] = {}
        self._last_state: dict[str, McpHealthState] = {}

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="mcp-health-monitor")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            with contextlib.suppress(Exception):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.probe_all()
            except Exception:  # pragma: no cover — logged, never raised
                log.exception("mcp.health.loop_error")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self.probe_interval_seconds)

    # -- public API --------------------------------------------------------

    async def probe_all(self) -> list[McpHealthStatus]:
        """Probe every registered provider once. Returns the resulting statuses."""
        results: list[McpHealthStatus] = []
        for workspace_id in self.registry.workspace_ids:
            for provider in self.registry.list_for_workspace(workspace_id):
                status = await self._probe(provider)
                await self._persist(provider, status)
                await self._maybe_publish(workspace_id, provider, status)
                results.append(status)
        return results

    def is_routable(self, provider_id: str) -> bool:
        """Return False once the provider has been DOWN past the auto-disable threshold.

        ``UNKNOWN`` (never probed) and ``OK`` / ``DEGRADED`` are routable. ``DOWN`` is
        routable for the first :data:`auto_disable_after_seconds` after the last OK
        (or after the first DOWN if the provider was never OK) — that gives the
        runner a chance to recover from a single flaky probe before we mark the
        provider non-routable.
        """
        state = self._last_state.get(provider_id, McpHealthState.UNKNOWN)
        if state != McpHealthState.DOWN:
            return True
        last_ok = self._last_ok_monotonic.get(provider_id)
        if last_ok is None:
            return False
        return (time.monotonic() - last_ok) <= self.auto_disable_after_seconds

    # -- probe -------------------------------------------------------------

    async def _probe(self, provider: McpProviderConfig) -> McpHealthStatus:
        start = time.perf_counter()
        try:
            sess = await asyncio.wait_for(
                open_session(provider), timeout=self.probe_timeout_seconds
            )
        except Exception as exc:
            return McpHealthStatus(
                provider_id=provider.id,
                name=provider.name,
                state=McpHealthState.DOWN,
                latency_ms=int((time.perf_counter() - start) * 1000),
                error=str(exc),
                checked_at=datetime.now(tz=UTC),
            )

        try:
            tools = await asyncio.wait_for(sess.list_tools(), timeout=self.probe_timeout_seconds)
            latency_ms = int((time.perf_counter() - start) * 1000)
            state = McpHealthState.OK if tools else McpHealthState.DEGRADED
            return McpHealthStatus(
                provider_id=provider.id,
                name=provider.name,
                state=state,
                latency_ms=latency_ms,
                checked_at=datetime.now(tz=UTC),
            )
        except Exception as exc:
            return McpHealthStatus(
                provider_id=provider.id,
                name=provider.name,
                state=McpHealthState.DOWN,
                latency_ms=int((time.perf_counter() - start) * 1000),
                error=str(exc),
                checked_at=datetime.now(tz=UTC),
            )
        finally:
            with contextlib.suppress(Exception):
                await sess.cleanup()

    # -- persistence + pubsub ---------------------------------------------

    async def _persist(self, provider: McpProviderConfig, status: McpHealthStatus) -> None:
        if provider.id.startswith("builtin:"):
            return  # in-memory only
        # Use a direct UPDATE so we don't load the row first; the health
        # monitor must stay fast under many workspaces.
        from suitest_db.models.mcp_provider import McpProvider  # late import

        stmt = (
            update(McpProvider)
            .where(McpProvider.id == provider.id)
            .values(health_status=status.state.value, last_health_at=status.checked_at)
        )
        async with self.session_factory() as session:
            await session.execute(stmt)
            await session.commit()

    async def _maybe_publish(
        self,
        workspace_id: str,
        provider: McpProviderConfig,
        status: McpHealthStatus,
    ) -> None:
        prev = self._last_state.get(provider.id)
        if status.state == McpHealthState.OK:
            self._last_ok_monotonic[provider.id] = time.monotonic()
        if prev == status.state:
            return
        self._last_state[provider.id] = status.state
        payload = {
            "event": "mcp.provider.health",
            "data": {
                "providerId": provider.id,
                "name": provider.name,
                "status": status.state.value,
                "latencyMs": status.latency_ms,
                "error": status.error,
            },
        }
        await self.redis.publish(f"workspace:{workspace_id}", json.dumps(payload))
