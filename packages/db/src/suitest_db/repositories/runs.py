"""Run repository with filtered keyset listing + summary/step/artifact loaders."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import extract, func, select
from suitest_db.models.case import TestCase, TestStep
from suitest_db.models.project import Project, Suite
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


class RunSummary(BaseModel):
    """Step-outcome counters derived from live ``run_steps`` rows.

    Returned alongside the ``Run`` row by :meth:`RunRepo.get_with_summary` so
    the read path stays mutation-free — the denormalised counters on the ORM
    instance are left untouched and only the recomputed values flow out.
    """

    total_steps: int
    passed_steps: int
    failed_steps: int
    duration_ms: int | None = None


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

    async def get_with_summary(self, run_id: str) -> tuple[Run, RunSummary] | None:
        """Return ``(run, summary)`` with counters derived from live RunSteps.

        The denormalised counters on ``Run`` are authoritative once a run completes,
        but for in-flight runs we recompute from the live ``run_steps`` rows so the
        summary is always consistent with the actual step outcomes. To avoid
        mutating tracked ORM state on a read path (which is fragile — any flush
        in the request lifecycle would persist the recompute), counters are
        returned in a separate :class:`RunSummary` dataclass and the ``Run``
        instance is left untouched.
        """
        run = await self.get_by_id(run_id)
        if run is None:
            return None
        steps = list(
            (await self.session.scalars(select(RunStep).where(RunStep.run_id == run_id))).all()
        )
        summary = RunSummary(
            total_steps=len(steps),
            passed_steps=sum(1 for s in steps if s.outcome == StepOutcome.PASS),
            failed_steps=sum(
                1 for s in steps if s.outcome in (StepOutcome.FAIL, StepOutcome.ERROR)
            ),
            duration_ms=run.duration_ms,
        )
        return run, summary

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

    async def summary_for_workspace(self, workspace_id: str) -> dict[str, int]:
        """Aggregated counters for the Runs summary bar (docs/API.md §3.5).

        Returns a dict keyed by ``RunStatus`` value (e.g. ``"PASS"``) plus the
        synthetic keys ``"avg_duration_ms"`` and ``"today"``. Single grouped
        aggregate query for per-status counts + avg duration; second query
        scopes the per-day count. Both queries join ``projects`` to enforce
        the workspace scope (runs only have ``project_id``).
        """
        per_status_stmt = (
            select(
                Run.status,
                func.count().label("n"),
                func.avg(Run.duration_ms).label("avg_ms"),
            )
            .join(Project, Project.id == Run.project_id)
            .where(Project.workspace_id == workspace_id)
            .group_by(Run.status)
        )
        result = await self.session.execute(per_status_stmt)
        counts: dict[str, int] = {}
        total_ms = 0
        total_n = 0
        for row in result.all():
            status_value = row.status.value if hasattr(row.status, "value") else str(row.status)
            counts[status_value] = int(row.n)
            if row.avg_ms is not None:
                total_ms += int(float(row.avg_ms) * int(row.n))
                total_n += int(row.n)
        counts["avg_duration_ms"] = total_ms // total_n if total_n else 0

        today_start = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        today_stmt = (
            select(func.count())
            .select_from(Run)
            .join(Project, Project.id == Run.project_id)
            .where(Project.workspace_id == workspace_id, Run.created_at >= today_start)
        )
        today_count = await self.session.scalar(today_stmt)
        counts["today"] = int(today_count or 0)
        return counts

    async def get_with_selection(
        self, run_id: str
    ) -> tuple[Run | None, list[tuple[str, int, TestStep]]]:
        """Return the run plus the ordered ``(case_id, step_order, TestStep)`` selection.

        The M1c runner does not yet have a first-class ``run_cases`` join table
        — selection is implicit "every active case in the project's suites,
        ordered by ``(suite.order, case.created_at, step.order)``". ``step_order``
        is a per-run counter (0-indexed across all steps in the selection) so
        the orchestrator can index events / RunStep rows by a stable monotonic
        position even when steps span multiple cases. M2 will swap this for a
        persisted selection set when suite/tag filters arrive at run-create
        time.
        """
        run = await self.get_by_id(run_id)
        if run is None:
            return None, []
        stmt = (
            select(TestCase.id, TestStep)
            .join(Suite, Suite.id == TestCase.suite_id)
            .join(TestStep, TestStep.case_id == TestCase.id)
            .where(
                Suite.project_id == run.project_id,
                TestCase.deleted_at.is_(None),
            )
            .order_by(
                Suite.order.asc(),
                TestCase.created_at.asc(),
                TestCase.id.asc(),
                TestStep.order.asc(),
            )
        )
        rows = (await self.session.execute(stmt)).all()
        selection: list[tuple[str, int, TestStep]] = [
            (case_id, idx, step) for idx, (case_id, step) in enumerate(rows)
        ]
        return run, selection

    async def update_status(
        self,
        run_id: str,
        status: RunStatus,
        *,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        duration_ms: int | None = None,
        tier_at_runtime: Tier | None = None,
        total_steps: int | None = None,
        passed_steps: int | None = None,
        failed_steps: int | None = None,
    ) -> Run | None:
        """In-place status + counters update used by the runner orchestrator.

        Each optional field is applied only when supplied so the runner can
        call this once on ``RUNNING`` (starts_at + tier) and again on
        terminal status (completed_at + duration + counters) without us
        having to overload :class:`RunUpdate`.
        """
        run = await self.get_by_id(run_id)
        if run is None:
            return None
        run.status = status
        if started_at is not None:
            run.started_at = started_at
        if completed_at is not None:
            run.completed_at = completed_at
        if duration_ms is not None:
            run.duration_ms = duration_ms
        if tier_at_runtime is not None:
            run.tier_at_runtime = tier_at_runtime
        if total_steps is not None:
            run.total_steps = total_steps
        if passed_steps is not None:
            run.passed_steps = passed_steps
        if failed_steps is not None:
            run.failed_steps = failed_steps
        await self.session.flush()
        return run


class RunStepCreate(BaseModel):
    run_id: str
    case_id: str
    step_order: int
    outcome: StepOutcome
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    stdout: str | None = None
    stderr: str | None = None
    error_message: str | None = None
    state_snapshot: dict[str, object] | None = None


class RunStepUpdate(BaseModel):
    outcome: StepOutcome | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    stdout: str | None = None
    stderr: str | None = None
    error_message: str | None = None
    state_snapshot: dict[str, object] | None = None


class RunStepRepo(AsyncRepository[RunStep, RunStepCreate, RunStepUpdate]):
    """Per-step row writer used by the orchestrator after each dispatch."""

    model = RunStep

    async def create_step(
        self,
        *,
        run_id: str,
        case_id: str,
        step_order: int,
        outcome: StepOutcome,
        started_at: datetime | None,
        completed_at: datetime | None,
        duration_ms: int | None,
        stdout: str | None,
        stderr: str | None,
        error_message: str | None,
        state_snapshot: dict[str, object] | None = None,
    ) -> RunStep:
        """Insert one ``run_steps`` row and return it.

        Named ``create_step`` so it doesn't shadow :meth:`AsyncRepository.create`
        — the orchestrator passes flat keyword args (no DTO) for ergonomics.
        ``state_snapshot`` is the normalized MCP output captured for M5-1 replay.
        """
        row = RunStep(
            run_id=run_id,
            case_id=case_id,
            step_order=step_order,
            outcome=outcome,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            stdout=stdout,
            stderr=stderr,
            error_message=error_message,
            state_snapshot=state_snapshot,
        )
        self.session.add(row)
        await self.session.flush()
        return row


class ArtifactCreate(BaseModel):
    run_step_id: str
    kind: str  # ArtifactKind value; coerced at row construction
    url: str
    size_bytes: int
    mime_type: str
    metadata_json: dict[str, object] | None = None


class ArtifactUpdate(BaseModel):
    url: str | None = None


class ArtifactRepo(AsyncRepository[Artifact, ArtifactCreate, ArtifactUpdate]):
    """Artifact writer used by the upload pipeline after each step."""

    model = Artifact

    async def create_artifact(
        self,
        *,
        run_step_id: str,
        kind: str,
        url: str,
        size_bytes: int,
        mime_type: str,
        metadata: dict[str, object] | None,
    ) -> Artifact:
        """Insert one ``artifacts`` row and return it."""
        from suitest_shared.domain.enums import ArtifactKind

        row = Artifact(
            run_step_id=run_step_id,
            kind=ArtifactKind(kind) if isinstance(kind, str) else kind,
            url=url,
            size_bytes=size_bytes,
            mime_type=mime_type,
            metadata_json=metadata,
        )
        self.session.add(row)
        await self.session.flush()
        return row
