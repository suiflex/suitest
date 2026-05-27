"""TestCaseRepo tests including parametrised filters."""

from __future__ import annotations

import pytest
from factories import make_project, make_suite, make_test_case, make_workspace
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.case import TestStep
from suitest_db.repositories.test_cases import TestCaseRepo
from suitest_shared.domain.enums import CaseSource, CaseStatus, Priority


async def _suite(session: AsyncSession):  # type: ignore[no-untyped-def]
    ws = await make_workspace(session)
    project = await make_project(session, workspace=ws)
    return await make_suite(session, project=project)


@pytest.mark.asyncio
async def test_list_paginated_two_pages(session: AsyncSession) -> None:
    repo = TestCaseRepo(session)
    suite = await _suite(session)
    for _ in range(3):
        await make_test_case(session, suite=suite)

    first, cursor = await repo.list_by_suite_filtered(suite.id, limit=2)
    assert len(first) == 2
    assert cursor is not None

    second, cursor2 = await repo.list_by_suite_filtered(suite.id, cursor=cursor, limit=2)
    assert len(second) == 1
    assert cursor2 is None


@pytest.mark.asyncio
async def test_filter_status(session: AsyncSession) -> None:
    repo = TestCaseRepo(session)
    suite = await _suite(session)
    active = await make_test_case(session, suite=suite)
    draft = await make_test_case(session, suite=suite)
    draft.status = CaseStatus.DRAFT
    await session.flush()

    rows, _ = await repo.list_by_suite_filtered(suite.id, status=CaseStatus.DRAFT)
    assert {c.id for c in rows} == {draft.id}
    rows2, _ = await repo.list_by_suite_filtered(suite.id, status=CaseStatus.ACTIVE)
    assert {c.id for c in rows2} == {active.id}


@pytest.mark.asyncio
async def test_filter_source(session: AsyncSession) -> None:
    repo = TestCaseRepo(session)
    suite = await _suite(session)
    manual = await make_test_case(session, suite=suite, source=CaseSource.MANUAL)
    ai = await make_test_case(session, suite=suite, source=CaseSource.AI)

    rows, _ = await repo.list_by_suite_filtered(suite.id, source=CaseSource.AI)
    assert {c.id for c in rows} == {ai.id}
    assert manual.id not in {c.id for c in rows}


@pytest.mark.asyncio
async def test_filter_priority(session: AsyncSession) -> None:
    repo = TestCaseRepo(session)
    suite = await _suite(session)
    p0 = await make_test_case(session, suite=suite)
    p0.priority = Priority.P0
    default = await make_test_case(session, suite=suite)  # P2 default
    await session.flush()

    rows, _ = await repo.list_by_suite_filtered(suite.id, priority=Priority.P0)
    assert {c.id for c in rows} == {p0.id}
    assert default.id not in {c.id for c in rows}


@pytest.mark.asyncio
async def test_filter_tag(session: AsyncSession) -> None:
    repo = TestCaseRepo(session)
    suite = await _suite(session)
    tagged = await make_test_case(session, suite=suite, tags=["smoke"])
    await make_test_case(session, suite=suite, tags=["regression"])

    rows, _ = await repo.list_by_suite_filtered(suite.id, tag="smoke")
    assert {c.id for c in rows} == {tagged.id}


@pytest.mark.asyncio
async def test_filter_q_ilike_name(session: AsyncSession) -> None:
    repo = TestCaseRepo(session)
    suite = await _suite(session)
    login = await make_test_case(session, suite=suite, name="Login flow")
    await make_test_case(session, suite=suite, name="Checkout flow")

    rows, _ = await repo.list_by_suite_filtered(suite.id, q="login")
    assert {c.id for c in rows} == {login.id}


@pytest.mark.asyncio
async def test_get_steps_and_with_steps(session: AsyncSession) -> None:
    repo = TestCaseRepo(session)
    suite = await _suite(session)
    case = await make_test_case(session, suite=suite)
    session.add_all(
        [
            TestStep(case_id=case.id, order=2, action="b", expected="b"),
            TestStep(case_id=case.id, order=1, action="a", expected="a"),
        ]
    )
    await session.flush()

    steps = await repo.get_steps(case.id)
    assert [s.order for s in steps] == [1, 2]

    with_steps = await repo.list_with_steps_by_suite(suite.id)
    assert len(with_steps) == 1
    assert len(with_steps[0].steps) == 2
