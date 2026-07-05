"""Build the ``run_test_case`` ctx for LOCAL mode — no Redis, no ARQ.

Mirrors the non-broker half of :func:`suitest_runner.worker.startup`: same
engine / session factory / MCP registry / pool / invoker, but the redis client
is replaced by :class:`suitest_runner.null_publisher.NullPublisher`, the ARQ
pool is omitted, and the defect auto-filer (which enqueues downstream ARQ jobs)
is left unset.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from suitest_mcp.invoker import McpInvoker
from suitest_mcp.pool import McpPool
from suitest_mcp.registry import McpRegistry
from suitest_mcp.workspace_cap import WorkspacePoolCap

from suitest_runner.null_publisher import NullPublisher
from suitest_runner.observability import setup_observability
from suitest_runner.settings import get_settings


async def build_local_ctx(ctx: dict[str, object]) -> None:
    """Populate ``ctx`` in place with the keys ``run_test_case`` requires."""
    setup_observability()
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    publisher = NullPublisher()
    registry = McpRegistry()
    pool = McpPool(
        queue_timeout_seconds=settings.mcp_queue_timeout_seconds,
        workspace_cap=settings.mcp_max_sessions_per_workspace,
    )
    workspace_cap = WorkspacePoolCap(
        max_per_workspace=settings.mcp_max_sessions_per_workspace,
        queue_timeout_seconds=settings.mcp_queue_timeout_seconds,
    )
    invoker = McpInvoker(
        registry=registry,
        pool=pool,
        health=None,
        redis_client=publisher,  # type: ignore[arg-type]  # NullPublisher duck-types the publish surface
        audit_session_factory=session_factory,
        workspace_cap=workspace_cap,
    )
    ctx["settings"] = settings
    ctx["engine"] = engine
    ctx["session_factory"] = session_factory
    ctx["redis"] = publisher
    ctx["invoker"] = invoker
    ctx["registry"] = registry
    ctx["defect_auto_filer"] = None
