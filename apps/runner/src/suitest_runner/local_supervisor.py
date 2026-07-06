"""LOCAL-mode run supervisor — no Redis, no ARQ.

`suitest up` launches this alongside the API. It polls the DB for runs left in
``QUEUED`` by the local dispatcher (see api ``run_dispatch``) and executes each
one in-process via :func:`run_test_case`, one at a time.

ponytail: single-concurrency polling loop; upgrade path is the ARQ worker
(server mode) if throughput ever matters. Kept deliberately dumb.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from suitest_db.models.run import Run
from suitest_shared.domain.enums import RunStatus

from suitest_runner.jobs.run_test_case import run_test_case
from suitest_runner.local_ctx import build_local_ctx

_POLL_INTERVAL_SECONDS = 1.0


async def _next_queued_run_ids(session_factory: object) -> list[str]:
    async with session_factory() as session:  # type: ignore[operator]
        rows = await session.execute(select(Run.id).where(Run.status == RunStatus.QUEUED))
        return [str(r) for r in rows.scalars().all()]


async def drain_once(ctx: dict[str, object]) -> None:
    """Run every currently-QUEUED run once, sequentially."""
    factory = ctx["session_factory"]
    for run_id in await _next_queued_run_ids(factory):
        await run_test_case(ctx, run_id)


async def serve() -> None:
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
