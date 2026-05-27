"""Tests for defects + external issues (Task 2f)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.ids import new_id
from suitest_db.models.defect import Defect, ExternalIssue
from suitest_db.models.workspace import Workspace
from suitest_shared.domain.enums import DefectStatus, DiagnosisKind, Severity


async def _workspace(session: AsyncSession) -> Workspace:
    ws = Workspace(slug=f"ws-{new_id()}", name="WS")
    session.add(ws)
    await session.flush()
    return ws


async def _defect(session: AsyncSession, ws: Workspace) -> Defect:
    defect = Defect(
        public_id=f"D-{new_id()}",
        workspace_id=ws.id,
        title="Bug",
        severity=Severity.HIGH,
        created_by="maya@suitest.io",
    )
    session.add(defect)
    await session.flush()
    return defect


@pytest.mark.asyncio
async def test_defect_default_diagnosis_is_manual_triage(session: AsyncSession) -> None:
    ws = await _workspace(session)
    defect = await _defect(session, ws)
    fetched = await session.scalar(select(Defect).where(Defect.id == defect.id))
    assert fetched is not None
    assert fetched.agent_diagnosis_kind is DiagnosisKind.MANUAL_TRIAGE
    assert fetched.status is DefectStatus.OPEN


@pytest.mark.asyncio
async def test_defect_severity_required(session: AsyncSession) -> None:
    ws = await _workspace(session)
    defect = Defect(
        public_id=f"D-{new_id()}",
        workspace_id=ws.id,
        title="Bug",
        created_by="maya@suitest.io",
    )  # severity omitted
    session.add(defect)
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_external_issue_unique_provider_pair(session: AsyncSession) -> None:
    ws = await _workspace(session)
    defect = await _defect(session, ws)
    session.add(
        ExternalIssue(
            defect_id=defect.id,
            provider="jira",
            external_id="PROJ-1",
            external_url="https://jira/PROJ-1",
        )
    )
    await session.flush()
    session.add(
        ExternalIssue(
            defect_id=defect.id,
            provider="jira",
            external_id="PROJ-1",
            external_url="https://jira/PROJ-1-dup",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()
