"""Tests for runs / run_steps / artifacts (Task 2e)."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.ids import new_id
from suitest_db.models.case import TestCase
from suitest_db.models.project import Project, Suite
from suitest_db.models.run import Artifact, Run, RunStep
from suitest_db.models.workspace import Workspace
from suitest_shared.domain.enums import (
    ArtifactKind,
    CaseSource,
    RunStatus,
    RunTrigger,
    StepOutcome,
    Tier,
)


async def _project(session: AsyncSession) -> Project:
    ws = Workspace(slug=f"ws-{new_id()}", name="WS")
    session.add(ws)
    await session.flush()
    project = Project(workspace_id=ws.id, slug=f"p-{new_id()}", name="P")
    session.add(project)
    await session.flush()
    return project


async def _case(session: AsyncSession, project: Project) -> TestCase:
    suite = Suite(project_id=project.id, name="S")
    session.add(suite)
    await session.flush()
    case = TestCase(
        suite_id=suite.id, public_id=f"TC-{new_id()}", name="C", source=CaseSource.MANUAL
    )
    session.add(case)
    await session.flush()
    return case


async def _run(session: AsyncSession, project: Project) -> Run:
    run = Run(
        public_id=f"R-{new_id()}",
        project_id=project.id,
        name="Run",
        trigger=RunTrigger.MANUAL,
        status=RunStatus.QUEUED,
        tier_at_runtime=Tier.ZERO,
    )
    session.add(run)
    await session.flush()
    return run


@pytest.mark.asyncio
async def test_run_requires_tier_at_runtime(session: AsyncSession) -> None:
    project = await _project(session)
    run = Run(
        public_id=f"R-{new_id()}",
        project_id=project.id,
        name="Run",
        trigger=RunTrigger.MANUAL,
    )  # tier_at_runtime omitted
    session.add(run)
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_run_step_cascade_on_run_delete(session: AsyncSession) -> None:
    project = await _project(session)
    case = await _case(session, project)
    run = await _run(session, project)
    rs = RunStep(run_id=run.id, case_id=case.id, step_order=1, outcome=StepOutcome.PASS)
    session.add(rs)
    await session.flush()
    rs_id = rs.id

    await session.delete(run)
    await session.flush()
    session.expunge_all()
    assert await session.get(RunStep, rs_id) is None
    # Linked test case survives (no CASCADE on case_id).
    assert await session.get(TestCase, case.id) is not None


@pytest.mark.asyncio
async def test_artifact_cascade_on_run_step_delete(session: AsyncSession) -> None:
    project = await _project(session)
    case = await _case(session, project)
    run = await _run(session, project)
    rs = RunStep(run_id=run.id, case_id=case.id, step_order=1, outcome=StepOutcome.PASS)
    session.add(rs)
    await session.flush()
    art = Artifact(
        run_step_id=rs.id,
        kind=ArtifactKind.SCREENSHOT,
        url="s3://bucket/x.png",
        size_bytes=10,
        mime_type="image/png",
    )
    session.add(art)
    await session.flush()
    art_id = art.id

    await session.delete(rs)
    await session.flush()
    session.expunge_all()
    assert await session.get(Artifact, art_id) is None


@pytest.mark.asyncio
async def test_artifact_url_accepts_both_schemes(session: AsyncSession) -> None:
    project = await _project(session)
    case = await _case(session, project)
    run = await _run(session, project)
    rs = RunStep(run_id=run.id, case_id=case.id, step_order=1, outcome=StepOutcome.PASS)
    session.add(rs)
    await session.flush()
    s3 = Artifact(
        run_step_id=rs.id,
        kind=ArtifactKind.HAR,
        url="s3://b/x.har",
        size_bytes=1,
        mime_type="application/json",
    )
    file = Artifact(
        run_step_id=rs.id,
        kind=ArtifactKind.VIDEO,
        url="file:///tmp/x.webm",
        size_bytes=2,
        mime_type="video/webm",
    )
    session.add_all([s3, file])
    await session.flush()  # both succeed


@pytest.mark.asyncio
async def test_run_metadata_json_roundtrip(session: AsyncSession) -> None:
    project = await _project(session)
    run = Run(
        public_id=f"R-{new_id()}",
        project_id=project.id,
        name="Run",
        trigger=RunTrigger.MANUAL,
        tier_at_runtime=Tier.ZERO,
        metadata_json={"k": "v"},
    )
    session.add(run)
    await session.flush()
    rid = run.id
    session.expunge_all()
    fetched = await session.get(Run, rid)
    assert fetched is not None
    assert fetched.metadata_json == {"k": "v"}
