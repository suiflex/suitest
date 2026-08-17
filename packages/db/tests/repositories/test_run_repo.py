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
from suitest_db.models.case import TestStep
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

    result = await repo.get_with_summary(run.id)
    assert result is not None
    fetched_run, summary = result
    assert fetched_run.id == run.id
    assert summary.total_steps == 4
    assert summary.passed_steps == 2
    assert summary.failed_steps == 2
    # Read path must not mutate the tracked ORM instance — denorm counters on
    # ``Run`` stay at their stored values (0 here) until the runner flushes.
    assert fetched_run.total_steps == 0
    assert fetched_run.passed_steps == 0
    assert fetched_run.failed_steps == 0


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


async def _two_cases_with_one_step_each(session: AsyncSession, project):  # type: ignore[no-untyped-def]
    """Two cases in one suite, one step each. Returns ``(case_a, case_b)``."""
    suite = await make_suite(session, project=project)
    cases = []
    for name in ("A", "B"):
        case = await make_test_case(session, suite=suite, name=name)
        session.add(
            TestStep(case_id=case.id, order=1, action=f"act {name}", expected=f"exp {name}")
        )
        cases.append(case)
    await session.flush()
    return cases[0], cases[1]


@pytest.mark.asyncio
async def test_get_with_selection_honors_persisted_selection(session: AsyncSession) -> None:
    """A run that selected one case executes that case only — not its whole project."""
    project = await _project(session)
    case_a, _case_b = await _two_cases_with_one_step_each(session, project)
    run = await make_run(session, project=project)
    run.metadata_json = {"selection": [{"case_id": case_a.id}]}
    await session.flush()

    loaded, selection = await RunRepo(session).get_with_selection(run.id)

    assert loaded is not None
    assert [case_id for case_id, _order, _step in selection] == [case_a.id]


@pytest.mark.asyncio
async def test_get_with_selection_falls_back_to_project_wide(session: AsyncSession) -> None:
    """Runs predating the persisted selection keep the old project-wide behavior."""
    project = await _project(session)
    case_a, case_b = await _two_cases_with_one_step_each(session, project)
    run = await make_run(session, project=project)

    _loaded, selection = await RunRepo(session).get_with_selection(run.id)

    assert sorted(case_id for case_id, _order, _step in selection) == sorted([case_a.id, case_b.id])
