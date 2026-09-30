"""LOCAL-mode run supervisor — no Redis, no ARQ.

`suitest up` launches this alongside the API. It polls the DB for runs left in
``QUEUED`` by the local dispatcher (see api ``run_dispatch``) and executes each
one in-process via :func:`run_test_case`, one at a time.

ponytail: single-concurrency polling loop; upgrade path is the ARQ worker
(server mode) if throughput ever matters. Kept deliberately dumb.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from suitest_db.models.run import Run
from suitest_shared.domain.enums import RunStatus

from suitest_runner.jobs.run_test_case import run_test_case
from suitest_runner.local_ctx import build_local_ctx

if TYPE_CHECKING:
    import io

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = structlog.get_logger(__name__)

_POLL_INTERVAL_SECONDS = 1.0


def _acquire_supervisor_lock(timeout_seconds: float = 3.0) -> io.TextIOWrapper | None:
    """Acquire a single-instance advisory lock for the local supervisor.

    Retries briefly to gracefully handle restarts where the outgoing supervisor
    process is still flushing and releasing its file lock.
    """
    data_dir = os.environ.get("SUITEST_DATA_DIR")
    if data_dir:
        lock_dir = Path(data_dir)
    elif "SUITEST_ARTIFACTS_DIR" in os.environ:
        lock_dir = Path(os.environ["SUITEST_ARTIFACTS_DIR"]).parent
    else:
        lock_dir = Path.cwd() / ".suitest"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = lock_dir / "supervisor.lock"

    deadline = time.monotonic() + timeout_seconds
    while True:
        f = None
        try:
            f = open(lock_file, "a+", encoding="utf-8")  # noqa: SIM115
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            f.seek(0)
            f.truncate()
            f.write(f"{os.getpid()}\n")
            f.flush()
            return f
        except (BlockingIOError, OSError):
            if f is not None:
                with contextlib.suppress(OSError):
                    f.close()
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.2)


async def _reconcile_zombie_runs(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Reconcile runs left in RUNNING from a prior crashed supervisor process."""
    try:
        async with session_factory() as session:
            rows = await session.execute(select(Run).where(Run.status == RunStatus.RUNNING))
            zombies = rows.scalars().all()
            if zombies:
                now = datetime.now(UTC)
                for z in zombies:
                    z.status = RunStatus.INTERRUPTED
                    z.completed_at = now
                    if z.started_at is not None:
                        started = (
                            z.started_at
                            if z.started_at.tzinfo is not None
                            else z.started_at.replace(tzinfo=UTC)
                        )
                        z.duration_ms = max(0, int((now - started).total_seconds() * 1000))
                    meta = dict(z.metadata_json or {})
                    meta["reconciliation"] = "Supervisor restarted while run was in progress"
                    z.metadata_json = meta
                    log.warning("supervisor.zombie_run_reconciled", run_id=z.id)
                await session.commit()
    except Exception:
        log.warning("supervisor.zombie_reconciliation_failed", exc_info=True)


async def _next_queued_run_ids(session_factory: async_sessionmaker[AsyncSession]) -> list[str]:
    async with session_factory() as session:
        rows = await session.execute(
            select(Run.id).where(Run.status == RunStatus.QUEUED).order_by(Run.created_at.asc())
        )
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
        except (Exception, asyncio.CancelledError) as exc:
            log.error("supervisor.run_interrupted", run_id=run_id, exc_info=True)
            try:
                async with factory() as session:
                    run_row = await session.get(Run, run_id)
                    if run_row is not None and run_row.status == RunStatus.RUNNING:
                        now = datetime.now(UTC)
                        run_row.status = RunStatus.INTERRUPTED
                        run_row.completed_at = now
                        if run_row.started_at is not None:
                            started = (
                                run_row.started_at
                                if run_row.started_at.tzinfo is not None
                                else run_row.started_at.replace(tzinfo=UTC)
                            )
                            run_row.duration_ms = max(
                                0, int((now - started).total_seconds() * 1000)
                            )
                        meta = dict(run_row.metadata_json or {})
                        meta["reconciliation"] = (
                            "Supervisor stopped or task cancelled"
                            if isinstance(exc, asyncio.CancelledError)
                            else f"Supervisor error during run: {exc}"
                        )
                        run_row.metadata_json = meta
                        await session.commit()
            except Exception:
                log.warning("supervisor.reconcile_error_failed", run_id=run_id, exc_info=True)
            if isinstance(exc, asyncio.CancelledError):
                raise


async def serve() -> None:
    """Start the LOCAL-mode polling loop.

    Never run this alongside ARQ workers on the same database — both drain
    QUEUED runs and there is no claim-fencing; a run could execute twice.
    """
    lock = _acquire_supervisor_lock()
    if lock is None:
        log.warning(
            "supervisor.already_running",
            message="Another supervisor instance is already running with file lock; exiting.",
        )
        return

    try:
        import dotenv

        dotenv.load_dotenv()
    except ImportError as exc:
        log.debug("supervisor.dotenv_not_available", error=str(exc))

    ctx: dict[str, object] = {}
    try:
        await build_local_ctx(ctx)
        factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]  # type: ignore[assignment]
        await _reconcile_zombie_runs(factory)
        # One startup line so .suitest/logs/supervisor.log proves liveness — the
        # loop is otherwise silent unless a poll/run errors.
        log.info("supervisor.started", poll_interval_seconds=_POLL_INTERVAL_SECONDS)
        while True:
            await drain_once(ctx)
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
    finally:
        engine = ctx.get("engine")
        if engine is not None:
            await engine.dispose()  # type: ignore[attr-defined]
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()
        except OSError as exc:
            log.debug("supervisor.lock_release_failed", error=str(exc))


if __name__ == "__main__":
    asyncio.run(serve())
