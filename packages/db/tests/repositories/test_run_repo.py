"""RunRepo tests including summary and filtered listing."""

from __future__ import annotations

import pytest
from factories import (
    make_project,
    make_run,
    make_run_step,
    make_suite,
    make_test_case,
    make_workspace,
)
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.run import Artifact
from suitest_db.repositories.runs import RunRepo
from suitest_shared.domain.enums import ArtifactKind, RunStatus, StepOutcome


async def _project(session: AsyncSession):  # type: ignore[no-untyped-def]
    ws = await make_workspace(session)
    return await make_project(session, workspace=ws)


@pytest.mark.asyncio
async def test_list_paginated_two_pages(session: AsyncSession) -> None:
    repo = RunRepo(session)
    project = await _project(session)
    for _ in range(3):
        await make_run(session, project=project)

    first, cursor = await repo.list_by_project(project.id, limit=2)
    assert len(first) == 2
    assert cursor is not None

    second, cursor2 = await repo.list_by_project(project.id, cursor=cursor, limit=2)
    assert len(second) == 1
    assert cursor2 is None


@pytest.mark.asyncio
async def test_list_filters(session: AsyncSession) -> None:
    repo = RunRepo(session)
    project = await _project(session)
    passed = await make_run(session, project=project, status=RunStatus.PASS, branch="main")
    await make_run(session, project=project, status=RunStatus.FAIL, branch="dev")

    rows, _ = await repo.list_by_project(project.id, status=RunStatus.PASS)
    assert {r.id for r in rows} == {passed.id}
    rows2, _ = await repo.list_by_project(project.id, branch="main")
    assert {r.id for r in rows2} == {passed.id}


@pytest.mark.asyncio
async def test_get_with_summary(session: AsyncSession) -> None:
    repo = RunRepo(session)
    project = await _project(session)
    suite = await make_suite(session, project=project)
    case = await make_test_case(session, suite=suite)
    run = await make_run(session, project=project)
    await make_run_step(session, run=run, case=case, step_order=1, outcome=StepOutcome.PASS)
    await make_run_step(session, run=run, case=case, step_order=2, outcome=StepOutcome.PASS)
    await make_run_step(session, run=run, case=case, step_order=3, outcome=StepOutcome.FAIL)
    await make_run_step(session, run=run, case=case, step_order=4, outcome=StepOutcome.ERROR)

    summary = await repo.get_with_summary(run.id)
    assert summary is not None
    assert summary.total_steps == 4
    assert summary.passed_steps == 2
    assert summary.failed_steps == 2


@pytest.mark.asyncio
async def test_get_steps_and_artifacts(session: AsyncSession) -> None:
    repo = RunRepo(session)
    project = await _project(session)
    suite = await make_suite(session, project=project)
    case = await make_test_case(session, suite=suite)
    run = await make_run(session, project=project)
    rs = await make_run_step(session, run=run, case=case, step_order=1, outcome=StepOutcome.PASS)
    session.add(
        Artifact(
            run_step_id=rs.id,
            kind=ArtifactKind.SCREENSHOT,
            url="s3://b/x.png",
            size_bytes=1,
            mime_type="image/png",
        )
    )
    await session.flush()

    steps = await repo.get_steps(run.id)
    assert len(steps) == 1
    artifacts = await repo.get_artifacts(run.id)
    assert len(artifacts) == 1
    assert artifacts[0].run_step_id == rs.id
