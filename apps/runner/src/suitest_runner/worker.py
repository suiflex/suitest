"""ARQ :class:`WorkerSettings` for the Suitest runner.

Boots a shared MCP registry + pool, an async SQLAlchemy engine, and a Redis
client on startup; tears them down cleanly on shutdown. The placeholder
:func:`suitest_runner.jobs.run_test_case.run_test_case` job ships in Task 10 —
the real executor lands in Task 11.

Type-ignore notes (kept narrow on purpose, see root ``pyproject.toml`` mypy
override for ``suitest_runner.worker``):

* ARQ's :class:`arq.typing.WorkerSettingsBase` declares ``on_startup`` /
  ``on_shutdown`` as :class:`arq.typing.StartupShutdown`, a Protocol typed
  against ``dict[Any, Any]``. CLAUDE.md forbids ``Any``, so the lifecycle hooks
  here take ``dict[str, object]`` instead. Assigning them to ARQ's slots
  produces a Protocol-shape mismatch that ARQ tolerates at runtime
  (``await on_startup(ctx)`` with a real ``dict[str, Any]`` works regardless of
  the parameter type annotation).
* :func:`redis.asyncio.from_url` is untyped in the redis-py async stubs we
  ship, so the call site is the only place we silence ``no-untyped-call``.
"""

from __future__ import annotations

import structlog
from arq.connections import RedisSettings
from redis import asyncio as redis_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from suitest_mcp.invoker import McpInvoker
from suitest_mcp.pool import McpPool
from suitest_mcp.registry import McpRegistry
from suitest_mcp.workspace_cap import WorkspacePoolCap

from suitest_runner.jobs.run_test_case import run_test_case
from suitest_runner.observability import setup_observability
from suitest_runner.settings import RunnerSettings, get_settings

log = structlog.get_logger(__name__)


async def startup(ctx: dict[str, object]) -> None:
    """Populate ``ctx`` with the engine, session factory, redis, registry, pool.

    Resolved at boot from :class:`RunnerSettings` so the same process can be
    pointed at different brokers / databases via env without code changes.
    """
    setup_observability()
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    redis_client = redis_asyncio.from_url(  # type: ignore[no-untyped-call]
        settings.redis_url,
        decode_responses=False,
    )
    registry = McpRegistry()
    pool = McpPool(
        queue_timeout_seconds=settings.mcp_queue_timeout_seconds,
        workspace_cap=settings.mcp_max_sessions_per_workspace,
    )
    # Task 21: fair-queue cap layered above the per-provider pool. The cap
    # serialises waiters via asyncio.Condition (FIFO) so cross-provider bursts
    # in one workspace can't blow past the configured ceiling. ``queue_timeout``
    # is canonicalised on the cap so the invoker reads one source of truth.
    workspace_cap = WorkspacePoolCap(
        max_per_workspace=settings.mcp_max_sessions_per_workspace,
        queue_timeout_seconds=settings.mcp_queue_timeout_seconds,
    )
    # health=None for now — Task 21 wires the live HealthMonitor that the
    # invoker consults to skip DOWN providers. Until then every routable
    # provider is treated as healthy.
    invoker = McpInvoker(
        registry=registry,
        pool=pool,
        health=None,
        redis_client=redis_client,
        audit_session_factory=session_factory,
        workspace_cap=workspace_cap,
    )
    ctx["settings"] = settings
    ctx["engine"] = engine
    ctx["session_factory"] = session_factory
    ctx["redis"] = redis_client
    ctx["registry"] = registry
    ctx["pool"] = pool
    ctx["workspace_cap"] = workspace_cap
    ctx["invoker"] = invoker
    log.info(
        "runner.started",
        concurrency=settings.max_jobs_concurrent,
        max_retries=settings.max_retries,
        job_timeout_seconds=settings.job_timeout_seconds,
        mcp_workspace_cap=settings.mcp_max_sessions_per_workspace,
        mcp_queue_timeout=settings.mcp_queue_timeout_seconds,
        queue=settings.queue_name,
    )


async def shutdown(ctx: dict[str, object]) -> None:
    """Drain ctx resources in reverse order: pool → redis → engine.

    Each lookup is defensive so a partially-populated ctx (startup raised
    mid-way) still releases whatever did make it in.
    """
    pool = ctx.get("pool")
    if isinstance(pool, McpPool):
        await pool.shutdown()
    redis_client = ctx.get("redis")
    if isinstance(redis_client, redis_asyncio.Redis):
        await redis_client.aclose()
    engine = ctx.get("engine")
    # Late import keeps the engine type out of module-level eager imports for
    # tooling that loads suitest_runner.worker without SQLAlchemy installed.
    from sqlalchemy.ext.asyncio import AsyncEngine

    if isinstance(engine, AsyncEngine):
        await engine.dispose()
    log.info("runner.stopped")


# ``RunnerSettings()`` is resolved once at class-definition time so the ARQ CLI,
# which reads class attributes (not instance attributes), gets the env-resolved
# values without us having to subclass and override ``__init_subclass__``. The
# trade-off is that re-importing this module after mutating env in-process
# won't re-resolve — production processes only import once, and test code uses
# the ``startup`` hook (which calls ``get_settings()`` again) for env-driven
# assertions.
_settings = RunnerSettings()


class WorkerSettings:
    """ARQ worker settings consumed by :func:`arq.worker.run_worker`.

    Class attributes (not instance) per arq convention — the ARQ CLI introspects
    ``WorkerSettings.__dict__`` directly.
    """

    functions = [run_test_case]  # noqa: RUF012 — ARQ reads this as a class attribute
    queue_name: str = "suitest:runs"
    max_jobs: int = _settings.max_jobs_concurrent
    max_tries: int = _settings.max_retries + 1
    job_timeout: int = _settings.job_timeout_seconds
    keep_result: int = _settings.keep_result_seconds
    redis_settings: RedisSettings = RedisSettings.from_dsn(_settings.redis_url)
    on_startup = startup  # type: ignore[assignment]
    on_shutdown = shutdown  # type: ignore[assignment]
