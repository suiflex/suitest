"""RunStepLog repository — append + cursor-paginated read.

Writes are issued by the runner orchestrator per published event; reads back
the same rows via ``GET /api/v1/runs/:id/logs``. The repo intentionally
stays thin (no DTOs other than the bare insert helper) — callers control
the seq counter (Redis ``INCR``) so the repo never has to coordinate
monotonicity across workers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select
from suitest_db.models.run_step_log import RunStepLog
from suitest_db.repositories.base import AsyncRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


class RunStepLogCreate(BaseModel):
    run_id: str
    seq: int
    message: str
    level: str = "info"
    run_step_id: str | None = None


class RunStepLogUpdate(BaseModel):
    """Logs are append-only; the update DTO exists only to satisfy ``AsyncRepository``."""


class RunStepLogRepo(AsyncRepository[RunStepLog, RunStepLogCreate, RunStepLogUpdate]):
    """Append-only log writer + cursor reader."""

    model = RunStepLog

    async def append(
        self,
        *,
        run_id: str,
        run_step_id: str | None,
        level: str,
        message: str,
        seq: int,
    ) -> RunStepLog:
        """Insert one ``run_step_logs`` row carrying the orchestrator's payload."""
        row = RunStepLog(
            run_id=run_id,
            run_step_id=run_step_id,
            seq=seq,
            level=level,
            message=message,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_after(self, run_id: str, *, cursor: int, limit: int) -> Sequence[RunStepLog]:
        """Return up to ``limit`` rows with ``seq > cursor`` ordered ascending by seq.

        ``cursor`` is the last seen ``seq``; passing ``0`` (the default) returns
        the head of the stream. Asc order matches the on-screen append order
        the runs UI expects.
        """
        stmt = (
            select(RunStepLog)
            .where(RunStepLog.run_id == run_id, RunStepLog.seq > cursor)
            .order_by(RunStepLog.seq.asc())
            .limit(limit)
        )
        return (await self.session.scalars(stmt)).all()
