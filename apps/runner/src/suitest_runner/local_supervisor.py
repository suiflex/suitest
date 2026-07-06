"""LOCAL-mode run supervisor — no Redis, no ARQ.

`suitest up` launches this alongside the API. It polls the DB for runs left in
``QUEUED`` by the local dispatcher (see api ``run_dispatch``) and executes each
one in-process via :func:`run_test_case`, one at a time.

ponytail: single-concurrency polling loop; upgrade path is the ARQ worker
(server mode) if throughput ever matters. Kept deliberately dumb.
"""

from __future__ import annotations

import asyncio

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from suitest_db.models.run import Run
from suitest_shared.domain.enums import RunStatus

from suitest_runner.jobs.run_test_case import run_test_case
from suitest_runner.local_ctx import build_local_ctx

log = structlog.get_logger(__name__)

_POLL_INTERVAL_SECONDS = 1.0


async def _next_queued_run_ids(session_factory: async_sessionmaker[AsyncSession]) -> list[str]:
    async with session_factory() as session:
        rows = await session.execute(select(Run.id).where(Run.status == RunStatus.QUEUED))
        return [str(r) for r in rows.scalars().all()]


async def drain_once(ctx: dict[str, object]) -> None:
    """Run every currently-QUEUED run once, sequentially. Never propagates."""
    factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]  # type: ignore[assignment]
    try:
        run_ids = await _next_queued_run_ids(factory)
    except Exception:
        log.warning("supervisor.poll_error", exc_info=True)
        return
    for run_id in run_ids:
        try:
            await run_test_case(ctx, run_id)
        except Exception:
            log.error("supervisor.run_error", run_id=run_id, exc_info=True)


async def serve() -> None:
    """Start the LOCAL-mode polling loop.

    Never run this alongside ARQ workers on the same database — both drain
    QUEUED runs and there is no claim-fencing; a run could execute twice.
    """
    ctx: dict[str, object] = {}
    await build_local_ctx(ctx)
    try:
        while True:
            await drain_once(ctx)
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
    finally:
        engine = ctx.get("engine")
        if engine is not None:
            await engine.dispose()  # type: ignore[attr-defined]


if __name__ == "__main__":
    asyncio.run(serve())
