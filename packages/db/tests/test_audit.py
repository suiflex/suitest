"""Tests for the append-only audit log table (Task 2j)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.audit import write_audit
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


@pytest.mark.asyncio
async def test_write_audit_coerces_user_id_str_to_uuid() -> None:
    """user_id str must land as uuid.UUID — SQLite's Uuid bind crashes on str (DB-free)."""
    captured: list[AuditLog] = []

    class _StubSession:
        def add(self, instance: object) -> None:
            assert isinstance(instance, AuditLog)
            captured.append(instance)

    uid = uuid.uuid4()
    await write_audit(
        _StubSession(),
        workspace_id="ws-1",
        user_id=str(uid),
        action="api_key.create",
        resource_type="api_key",
        resource_id="k-1",
    )
    await write_audit(
        _StubSession(),
        workspace_id="ws-1",
        user_id=None,
        action="api_key.create",
        resource_type="api_key",
        resource_id="k-2",
    )
    assert isinstance(captured[0].user_id, uuid.UUID)
    assert captured[0].user_id == uid
    assert captured[1].user_id is None
