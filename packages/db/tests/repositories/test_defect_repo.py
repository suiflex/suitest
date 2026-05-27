"""DefectRepo tests including timeline ordering."""

from __future__ import annotations

import pytest
from factories import make_audit_log, make_defect, make_workspace
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.defects import DefectRepo
from suitest_shared.domain.enums import DefectStatus, Severity


@pytest.mark.asyncio
async def test_list_paginated_two_pages(session: AsyncSession) -> None:
    repo = DefectRepo(session)
    ws = await make_workspace(session)
    for _ in range(3):
        await make_defect(session, workspace=ws)

    first, cursor = await repo.list_by_workspace(ws.id, limit=2)
    assert len(first) == 2
    assert cursor is not None

    second, cursor2 = await repo.list_by_workspace(ws.id, cursor=cursor, limit=2)
    assert len(second) == 1
    assert cursor2 is None


@pytest.mark.asyncio
async def test_list_filters(session: AsyncSession) -> None:
    repo = DefectRepo(session)
    ws = await make_workspace(session)
    crit = await make_defect(
        session, workspace=ws, severity=Severity.CRITICAL, status=DefectStatus.OPEN
    )
    await make_defect(session, workspace=ws, severity=Severity.LOW, status=DefectStatus.CLOSED)

    rows, _ = await repo.list_by_workspace(ws.id, severity=Severity.CRITICAL)
    assert {d.id for d in rows} == {crit.id}
    rows2, _ = await repo.list_by_workspace(ws.id, status=DefectStatus.OPEN)
    assert {d.id for d in rows2} == {crit.id}


@pytest.mark.asyncio
async def test_timeline_ordering(session: AsyncSession) -> None:
    repo = DefectRepo(session)
    ws = await make_workspace(session)
    defect = await make_defect(session, workspace=ws)
    await make_audit_log(session, workspace=ws, action="updated", resource_id=defect.id)
    await make_audit_log(session, workspace=ws, action="resolved", resource_id=defect.id)

    timeline = await repo.timeline(defect.id)
    assert [e.action for e in timeline] == ["created", "updated", "resolved"]
    ats = [e.at for e in timeline]
    assert ats == sorted(ats)
