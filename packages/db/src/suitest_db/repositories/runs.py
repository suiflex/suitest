"""Run repository with filtered keyset listing + summary/step/artifact loaders."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import extract, func, select
from suitest_db.models.case import TestCase
from suitest_db.models.run import Artifact, Run, RunStep
from suitest_db.public_id import set_workspace_id
from suitest_db.repositories.base import AsyncRepository
from suitest_shared.domain.enums import RunStatus, RunTrigger, StepOutcome, Tier

if TYPE_CHECKING:
    from collections.abc import Sequence


class RunCreate(BaseModel):
    project_id: str
    name: str
    trigger: RunTrigger
    tier_at_runtime: Tier
    # Optional: filled by the ``before_insert`` listener
    # (suitest_db.public_id) from the per-workspace ``R`` sequence.
    public_id: str | None = None
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

    async def create(  # type: ignore[override]
        self, dto: RunCreate, *, workspace_id: str
    ) -> Run:
        """Create a run, deferring ``public_id`` to the ``before_insert`` listener.

        See :meth:`TestCaseRepo.create` for the rationale on the LSP override.
        """
        row = Run(**dto.model_dump(exclude_unset=True))
        set_workspace_id(row, workspace_id)
        self.session.add(row)
        await self.session.flush()
        return row

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

    async def list_since(self, project_id: str, since: datetime) -> Sequence[Run]:
        """All runs for a project created at/after ``since`` (analytics windows)."""
        stmt = (
            select(Run)
            .where(Run.project_id == project_id, Run.created_at >= since)
            .order_by(Run.created_at.asc())
        )
        return (await self.session.scalars(stmt)).all()

    async def heatmap_cells(
        self, project_id: str, since: datetime
    ) -> Sequence[tuple[datetime, int, int]]:
        """Run counts grouped by ``(day, hour)`` since ``since`` (docs/API.md §3.8).

        Returns rows of ``(day_truncated, hour_of_day, count)``; the day is the
        ``date_trunc('day', created_at)`` timestamp and hour is 0-23.
        """
        day = func.date_trunc("day", Run.created_at).label("day")
        hour = extract("hour", Run.created_at).label("hour")
        stmt = (
            select(day, hour, func.count(Run.id))
            .where(Run.project_id == project_id, Run.created_at >= since)
            .group_by(day, hour)
            .order_by(day.asc(), hour.asc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [(d, int(h), int(count)) for d, h, count in rows]

    async def get_steps(self, run_id: str) -> Sequence[RunStep]:
        stmt = select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.step_order.asc())
        return (await self.session.scalars(stmt)).all()

    async def get_steps_with_case_public_id(self, run_id: str) -> Sequence[tuple[RunStep, str]]:
        """Run steps in ``step_order`` paired with each step's case ``public_id``."""
        stmt = (
            select(RunStep, TestCase.public_id)
            .join(TestCase, TestCase.id == RunStep.case_id)
            .where(RunStep.run_id == run_id)
            .order_by(RunStep.step_order.asc())
        )
        return [(step, public_id) for step, public_id in (await self.session.execute(stmt)).all()]

    async def get_artifacts(self, run_id: str) -> Sequence[Artifact]:
        stmt = (
            select(Artifact)
            .join(RunStep, RunStep.id == Artifact.run_step_id)
            .where(RunStep.run_id == run_id)
            .order_by(Artifact.created_at.asc(), Artifact.id.asc())
        )
        return (await self.session.scalars(stmt)).all()
