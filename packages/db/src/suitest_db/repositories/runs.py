"""Run repository with filtered keyset listing + summary/step/artifact loaders."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select
from suitest_db.models.run import Artifact, Run, RunStep
from suitest_db.repositories.base import AsyncRepository
from suitest_shared.domain.enums import RunStatus, RunTrigger, StepOutcome, Tier

if TYPE_CHECKING:
    from collections.abc import Sequence


class RunCreate(BaseModel):
    public_id: str
    project_id: str
    name: str
    trigger: RunTrigger
    tier_at_runtime: Tier
    branch: str | None = None
    commit_sha: str | None = None
    env: str = "staging"
    status: RunStatus = RunStatus.QUEUED


class RunUpdate(BaseModel):
    status: RunStatus | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    total_steps: int | None = None
    passed_steps: int | None = None
    failed_steps: int | None = None


class RunRepo(AsyncRepository[Run, RunCreate, RunUpdate]):
    model = Run

    async def list_by_project(
        self,
        project_id: str,
        *,
        status: RunStatus | None = None,
        branch: str | None = None,
        env: str | None = None,
        cursor: tuple[datetime, str] | None = None,
        limit: int = 20,
    ) -> tuple[Sequence[Run], tuple[datetime, str] | None]:
        stmt = select(Run).where(Run.project_id == project_id)
        if status is not None:
            stmt = stmt.where(Run.status == status)
        if branch is not None:
            stmt = stmt.where(Run.branch == branch)
        if env is not None:
            stmt = stmt.where(Run.env == env)
        if cursor is not None:
            cursor_ts, cursor_id = cursor
            stmt = stmt.where(
                (Run.created_at < cursor_ts)
                | ((Run.created_at == cursor_ts) & (Run.id < cursor_id))
            )
        stmt = stmt.order_by(Run.created_at.desc(), Run.id.desc()).limit(limit + 1)

        rows = list((await self.session.scalars(stmt)).all())
        if len(rows) > limit:
            page = rows[:limit]
            last = page[-1]
            next_cursor: tuple[datetime, str] | None = (last.created_at, last.id)
        else:
            page = rows
            next_cursor = None
        return page, next_cursor

    async def get_with_summary(self, run_id: str) -> Run | None:
        """Return a run with ``total/passed/failed_steps`` refreshed from RunSteps.

        The denormalised counters on ``Run`` are authoritative once a run completes,
        but for in-flight runs we recompute from the live ``run_steps`` rows so the
        summary is always consistent with the actual step outcomes.
        """
        run = await self.get_by_id(run_id)
        if run is None:
            return None
        steps = list(
            (await self.session.scalars(select(RunStep).where(RunStep.run_id == run_id))).all()
        )
        run.total_steps = len(steps)
        run.passed_steps = sum(1 for s in steps if s.outcome == StepOutcome.PASS)
        run.failed_steps = sum(
            1 for s in steps if s.outcome in (StepOutcome.FAIL, StepOutcome.ERROR)
        )
        return run

    async def get_steps(self, run_id: str) -> Sequence[RunStep]:
        stmt = select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.step_order.asc())
        return (await self.session.scalars(stmt)).all()

    async def get_artifacts(self, run_id: str) -> Sequence[Artifact]:
        stmt = (
            select(Artifact)
            .join(RunStep, RunStep.id == Artifact.run_step_id)
            .where(RunStep.run_id == run_id)
            .order_by(Artifact.created_at.asc(), Artifact.id.asc())
        )
        return (await self.session.scalars(stmt)).all()
