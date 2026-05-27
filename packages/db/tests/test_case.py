"""Tests for test_cases / test_steps / case_tags (Task 2c)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.ids import new_id
from suitest_db.models.case import CaseTag, TestCase, TestStep
from suitest_db.models.project import Project, Suite
from suitest_db.models.workspace import Workspace
from suitest_shared.domain.case import TestStep as DomainTestStep
from suitest_shared.domain.enums import CaseSource, CaseStatus, Priority, TargetKind, Tier


async def _suite(session: AsyncSession) -> Suite:
    ws = Workspace(slug=f"ws-{new_id()}", name="WS")
    session.add(ws)
    await session.flush()
    project = Project(workspace_id=ws.id, slug=f"p-{new_id()}", name="P")
    session.add(project)
    await session.flush()
    suite = Suite(project_id=project.id, name="S")
    session.add(suite)
    await session.flush()
    return suite


async def _case(session: AsyncSession) -> TestCase:
    suite = await _suite(session)
    case = TestCase(
        suite_id=suite.id, public_id=f"TC-{new_id()}", name="Case", source=CaseSource.MANUAL
    )
    session.add(case)
    await session.flush()
    return case


@pytest.mark.asyncio
async def test_test_case_minimum_fields(session: AsyncSession) -> None:
    case = await _case(session)
    fetched = await session.scalar(select(TestCase).where(TestCase.id == case.id))
    assert fetched is not None
    assert fetched.status is CaseStatus.ACTIVE
    assert fetched.priority is Priority.P2
    assert fetched.source is CaseSource.MANUAL


@pytest.mark.asyncio
async def test_test_step_order_unique_per_case(session: AsyncSession) -> None:
    case = await _case(session)
    session.add(TestStep(case_id=case.id, order=1, action="a", expected="e"))
    await session.flush()
    session.add(TestStep(case_id=case.id, order=1, action="b", expected="e2"))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_test_step_defaults(session: AsyncSession) -> None:
    case = await _case(session)
    step = TestStep(case_id=case.id, order=1, action="click", expected="ok")
    session.add(step)
    await session.flush()
    fetched = await session.scalar(select(TestStep).where(TestStep.id == step.id))
    assert fetched is not None
    assert fetched.mcp_provider == "playwright-mcp"
    assert fetched.target_kind is TargetKind.FE_WEB


@pytest.mark.asyncio
async def test_case_tag_unique(session: AsyncSession) -> None:
    case = await _case(session)
    session.add(CaseTag(case_id=case.id, tag="smoke"))
    await session.flush()
    session.add(CaseTag(case_id=case.id, tag="smoke"))
    with pytest.raises(IntegrityError):
        await session.flush()


def test_executable_computed_zero_tier() -> None:
    step = DomainTestStep(id="s", case_id="c", order=1, action="click", expected="ok")
    assert step.executable(Tier.ZERO) is False
    step_with_code = DomainTestStep(
        id="s", case_id="c", order=1, action="", expected="ok", code="await page.click()"
    )
    assert step_with_code.executable(Tier.ZERO) is True


def test_executable_computed_cloud_tier() -> None:
    step = DomainTestStep(id="s", case_id="c", order=1, action="click", expected="ok")
    assert step.executable(Tier.CLOUD) is True


@pytest.mark.asyncio
async def test_cascade_delete_case_cascades_steps_tags(session: AsyncSession) -> None:
    case = await _case(session)
    step = TestStep(case_id=case.id, order=1, action="a", expected="e")
    tag = CaseTag(case_id=case.id, tag="smoke")
    session.add_all([step, tag])
    await session.flush()
    step_id, tag_id = step.id, tag.id

    await session.delete(case)
    await session.flush()
    assert await session.get(TestStep, step_id) is None
    assert await session.get(CaseTag, tag_id) is None
