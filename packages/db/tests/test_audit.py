"""Tests for the append-only audit log table (Task 2j)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.ids import new_id
from suitest_db.models.audit import AuditLog
from suitest_db.models.workspace import Workspace


async def _workspace(session: AsyncSession) -> Workspace:
    ws = Workspace(slug=f"ws-{new_id()}", name="WS")
    session.add(ws)
    await session.flush()
    return ws


@pytest.mark.asyncio
async def test_audit_log_required_fields(session: AsyncSession) -> None:
    ws = await _workspace(session)
    row = AuditLog(workspace_id=ws.id, resource_type="defects", resource_id="D-1")  # action missing
    session.add(row)
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_audit_log_metadata_json_optional(session: AsyncSession) -> None:
    ws = await _workspace(session)
    row = AuditLog(workspace_id=ws.id, action="create", resource_type="defects", resource_id="D-1")
    session.add(row)
    await session.flush()
    fetched = await session.scalar(select(AuditLog).where(AuditLog.id == row.id))
    assert fetched is not None
    assert fetched.metadata_json is None
    assert fetched.created_at is not None
