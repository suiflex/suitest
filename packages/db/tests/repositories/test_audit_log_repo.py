"""AuditLogRepo tests."""

from __future__ import annotations

import pytest
from factories import make_audit_log, make_workspace
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.audit_logs import AuditLogRepo


@pytest.mark.asyncio
async def test_list_paginated_two_pages(session: AsyncSession) -> None:
    repo = AuditLogRepo(session)
    ws = await make_workspace(session)
    for i in range(3):
        await make_audit_log(session, workspace=ws, action=f"a{i}", resource_id=f"r{i}")

    first, cursor = await repo.list_by_workspace(ws.id, limit=2)
    assert len(first) == 2
    assert cursor is not None

    second, cursor2 = await repo.list_by_workspace(ws.id, cursor=cursor, limit=2)
    assert len(second) == 1
    assert cursor2 is None


@pytest.mark.asyncio
async def test_append_stores_before_after(session: AsyncSession) -> None:
    repo = AuditLogRepo(session)
    ws = await make_workspace(session)
    row = await repo.append(
        workspace_id=ws.id,
        action="case.update",
        resource_type="test_case",
        resource_id="tc-1",
        before={"name": "old"},
        after={"name": "new"},
        ip="127.0.0.1",
        ua="pytest",
    )
    assert row.id is not None
    assert row.metadata_json == {"before": {"name": "old"}, "after": {"name": "new"}}
    assert row.ip_address == "127.0.0.1"
    assert row.user_agent == "pytest"
