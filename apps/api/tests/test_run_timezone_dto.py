"""Tests for Run DTOs UTC timezone serialization and SQLite persistence (Issue #176).

On SQLite, standard SQLAlchemy DateTime(timezone=True) strips timezone metadata
on read (returning tzinfo=None). UtcDateTime in suitest_db.types ensures that
all datetimes read back from SQLite or stored into SQLite retain tzinfo=UTC,
guaranteeing that Pydantic DTOs and API endpoints serialize timestamps with the 'Z' suffix.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from suitest_api.auth.db import get_async_session
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.main import create_app
from suitest_api.schemas.run import RunLogItem, RunReplayStep, RunStepPublic
from suitest_api.schemas.runs import RunPublic
from suitest_db.bootstrap import create_local_schema
from suitest_db.engine import make_engine
from suitest_db.ids import new_id
from suitest_db.models.case import TestCase
from suitest_db.models.project import Project, Suite
from suitest_db.models.run import Run, RunStep
from suitest_db.models.run_step_log import RunStepLog
from suitest_db.models.workspace import Workspace
from suitest_db.settings import DbSettings
from suitest_shared.domain.enums import CaseSource, Role, RunStatus, RunTrigger, StepOutcome, Tier


@pytest.mark.asyncio
async def test_run_and_step_sqlite_roundtrip_preserves_utc_and_serializes_with_z(
    tmp_path: Path,
) -> None:
    """Loading real Run and RunStep rows from SQLite must yield UTC datetimes and emit 'Z'."""
    settings = DbSettings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'runs_tz.db'}")
    engine = make_engine(settings)
    await create_local_schema(engine)

    maker = async_sessionmaker(engine, expire_on_commit=False)
    dt_started = datetime(2026, 9, 10, 10, 0, 0, tzinfo=UTC)
    dt_completed = datetime(2026, 9, 10, 10, 5, 0, tzinfo=UTC)

    async with maker() as session:
        ws = Workspace(slug=f"ws-{new_id()}", name="WS")
        session.add(ws)
        await session.flush()

        proj = Project(workspace_id=ws.id, slug=f"p-{new_id()}", name="P")
        session.add(proj)
        await session.flush()

        suite = Suite(project_id=proj.id, name="Smoke", order=0)
        session.add(suite)
        await session.flush()

        case = TestCase(
            suite_id=suite.id,
            workspace_id=ws.id,
            public_id="TC-100",
            name="case-1",
            source=CaseSource.MANUAL,
        )
        session.add(case)
        await session.flush()

        run = Run(
            public_id=f"R-{new_id()}",
            project_id=proj.id,
            workspace_id=ws.id,
            name="blackbox run",
            trigger=RunTrigger.MANUAL,
            status=RunStatus.PASS,
            tier_at_runtime=Tier.ZERO,
            started_at=dt_started,
            completed_at=dt_completed,
            total_steps=1,
            passed_steps=1,
            failed_steps=0,
            duration_ms=300000,
        )
        session.add(run)
        await session.flush()

        step = RunStep(
            run_id=run.id,
            case_id=case.id,
            step_order=1,
            outcome=StepOutcome.PASS,
            started_at=dt_started,
            completed_at=dt_completed,
            duration_ms=300000,
        )
        session.add(step)
        await session.commit()
        run_id = run.id
        step_id = step.id

    # Open a fresh session to read back from SQLite without cache
    async with maker() as session:
        loaded_run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one()
        loaded_step = (
            await session.execute(select(RunStep).where(RunStep.id == step_id))
        ).scalar_one()

        # Verify ORM level timezone preservation
        assert loaded_run.started_at is not None
        assert loaded_run.started_at.tzinfo == UTC
        assert loaded_run.completed_at is not None
        assert loaded_run.completed_at.tzinfo == UTC
        assert loaded_run.created_at is not None
        assert loaded_run.created_at.tzinfo == UTC

        assert loaded_step.started_at is not None
        assert loaded_step.started_at.tzinfo == UTC
        assert loaded_step.completed_at is not None
        assert loaded_step.completed_at.tzinfo == UTC

        # DTO serialization: RunPublic
        run_dto = RunPublic.model_validate(loaded_run)
        run_data = run_dto.model_dump(mode="json", by_alias=True)
        assert run_data["startedAt"] == "2026-09-10T10:00:00Z"
        assert run_data["completedAt"] == "2026-09-10T10:05:00Z"
        assert run_data["createdAt"].endswith("Z")

        # DTO serialization: RunStepPublic
        step_dto = RunStepPublic(
            id=loaded_step.id,
            run_id=loaded_step.run_id,
            case_id=loaded_step.case_id,
            case_public_id="TC-100",
            step_order=loaded_step.step_order,
            outcome=loaded_step.outcome,
            started_at=loaded_step.started_at,
            completed_at=loaded_step.completed_at,
        )
        step_data = step_dto.model_dump(mode="json")
        assert step_data["started_at"] == "2026-09-10T10:00:00Z"
        assert step_data["completed_at"] == "2026-09-10T10:05:00Z"

        # DTO serialization: RunReplayStep
        replay_step = RunReplayStep(
            id=loaded_step.id,
            step_order=loaded_step.step_order,
            case_public_id="TC-100",
            outcome=loaded_step.outcome,
            started_at=loaded_step.started_at,
        )
        replay_data = replay_step.model_dump(mode="json", by_alias=True)
        assert replay_data["startedAt"] == "2026-09-10T10:00:00Z"

    await engine.dispose()


@pytest.mark.asyncio
async def test_run_step_log_sqlite_roundtrip_and_api_logs_endpoint(tmp_path: Path) -> None:
    """Loading RunStepLog from SQLite preserves UTC tzinfo and /runs/{id}/logs emits 'Z'."""
    settings = DbSettings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'logs_tz.db'}")
    engine = make_engine(settings)
    await create_local_schema(engine)

    maker = async_sessionmaker(engine, expire_on_commit=False)

    dt_log = datetime(2026, 9, 10, 10, 15, 0, tzinfo=UTC)

    async with maker() as session:
        ws = Workspace(slug=f"ws-{new_id()}", name="Logs WS")
        session.add(ws)
        await session.flush()

        proj = Project(workspace_id=ws.id, slug=f"p-{new_id()}", name="Logs Project")
        session.add(proj)
        await session.flush()

        run = Run(
            public_id=f"R-{new_id()}",
            project_id=proj.id,
            workspace_id=ws.id,
            name="run-logs-test",
            trigger=RunTrigger.MANUAL,
            status=RunStatus.PASS,
            tier_at_runtime=Tier.ZERO,
        )
        session.add(run)
        await session.flush()

        log = RunStepLog(
            run_id=run.id,
            seq=1,
            level="info",
            message="persisted log message",
            created_at=dt_log,
        )
        session.add(log)
        await session.commit()
        run_id = run.id
        log_id = log.id
        ws_id = ws.id

    # 1. Verify direct ORM read from SQLite
    async with maker() as session:
        loaded_log = (
            await session.execute(select(RunStepLog).where(RunStepLog.id == log_id))
        ).scalar_one()
        assert loaded_log.created_at is not None
        assert loaded_log.created_at.tzinfo == UTC

        log_item = RunLogItem(
            seq=loaded_log.seq,
            level=loaded_log.level,
            message=loaded_log.message,
            created_at=loaded_log.created_at,
        )
        item_data = log_item.model_dump(mode="json", by_alias=True)
        assert item_data["createdAt"] == "2026-09-10T10:15:00Z"

    # 2. Verify through the real GET /api/v1/runs/{id}/logs endpoint on SQLite
    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_async_session] = _override_session
    app.dependency_overrides[require_workspace_membership] = lambda: TenantContext(
        workspace_id=ws_id, user_id="test-user", role=Role.ADMIN
    )

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/runs/{run_id}/logs?cursor=0&limit=50",
                headers={"X-Workspace-Id": ws_id},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert len(body["items"]) == 1
            assert body["items"][0]["message"] == "persisted log message"
            assert body["items"][0]["createdAt"] == "2026-09-10T10:15:00Z"

    await engine.dispose()


def test_run_log_item_normalizes_naive_datetime() -> None:
    """RunLogItem validator must normalize naive datetimes to UTC with 'Z' serialization."""
    naive_dt = datetime(2026, 9, 10, 10, 20, 0)
    item = RunLogItem(seq=1, level="info", message="naive dt test", created_at=naive_dt)
    assert item.created_at.tzinfo == UTC

    data = item.model_dump(mode="json", by_alias=True)
    assert data["createdAt"] == "2026-09-10T10:20:00Z"
