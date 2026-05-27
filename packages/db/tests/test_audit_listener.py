"""Tests for the global ``after_flush`` audit listener (Task 6).

The listener is registered as a side effect of importing ``suitest_db`` (see
``suitest_db/__init__.py``). These tests exercise it through real session writes
against the Postgres testcontainer — there is no HTTP involved. Attribution is
injected by setting :data:`suitest_db.audit.audit_ctx` directly (the role the
ASGI middleware plays at runtime), and always reset in a ``finally`` so one test
never leaks context into the next.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from factories import (
    make_defect,
    make_project,
    make_suite,
    make_test_case,
    make_user,
    make_workspace,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.audit import AuditContext, audit_ctx
from suitest_db.models.audit import AuditLog
from suitest_db.models.workspace import Workspace
from suitest_shared.domain.enums import DefectStatus


@pytest_asyncio.fixture
async def workspace(session: AsyncSession) -> Workspace:
    return await make_workspace(session)


@pytest_asyncio.fixture
async def bound_ctx(workspace: Workspace) -> AsyncIterator[AuditContext]:
    """Bind a request-like audit context for the duration of one test."""
    ctx = AuditContext(
        user_id=None,
        workspace_id=workspace.id,
        ip_address="10.0.0.1",
        user_agent="pytest-agent",
    )
    token = audit_ctx.set(ctx)
    try:
        yield ctx
    finally:
        audit_ctx.reset(token)


async def _audit_rows(session: AsyncSession, resource_id: str) -> list[AuditLog]:
    await session.flush()
    result = await session.scalars(select(AuditLog).where(AuditLog.resource_id == resource_id))
    return list(result)


@pytest.mark.asyncio
async def test_audit_listener_inserts_row_on_create(
    session: AsyncSession, workspace: Workspace, bound_ctx: AuditContext
) -> None:
    project = await make_project(session, workspace=workspace)
    suite = await make_suite(session, project=project)
    case = await make_test_case(session, suite=suite)

    rows = await _audit_rows(session, case.public_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "insert"
    assert row.resource_type == "test_cases"
    assert row.resource_id == case.public_id
    assert row.workspace_id == workspace.id
    assert row.ip_address == "10.0.0.1"
    assert row.user_agent == "pytest-agent"
    assert row.metadata_json is None


@pytest.mark.asyncio
async def test_audit_listener_skips_unaudited_table(
    session: AsyncSession, bound_ctx: AuditContext
) -> None:
    # ``users`` is not in AUDITED_TABLES → no audit row.
    user = await make_user(session)
    rows = await _audit_rows(session, str(user.id))
    assert rows == []


@pytest.mark.asyncio
async def test_audit_listener_no_context_skips(session: AsyncSession, workspace: Workspace) -> None:
    # No bound_ctx fixture → audit_ctx is None → listener early-returns.
    assert audit_ctx.get() is None
    project = await make_project(session, workspace=workspace)
    suite = await make_suite(session, project=project)
    case = await make_test_case(session, suite=suite)

    rows = await _audit_rows(session, case.public_id)
    assert rows == []


@pytest.mark.asyncio
async def test_audit_listener_update_captures_changes(
    session: AsyncSession, workspace: Workspace, bound_ctx: AuditContext
) -> None:
    defect = await make_defect(session, workspace=workspace, status=DefectStatus.OPEN)
    # Drop the insert audit row so we assert only on the update below.
    await session.flush()

    defect.status = DefectStatus.IN_PROGRESS
    await session.flush()

    result = await session.scalars(
        select(AuditLog).where(
            AuditLog.resource_id == defect.public_id, AuditLog.action == "update"
        )
    )
    rows = list(result)
    assert len(rows) == 1
    assert rows[0].metadata_json == {"changes": {"status": ["OPEN", "IN_PROGRESS"]}}


@pytest.mark.asyncio
async def test_audit_listener_delete_records(
    session: AsyncSession, workspace: Workspace, bound_ctx: AuditContext
) -> None:
    defect = await make_defect(session, workspace=workspace)
    public_id = defect.public_id
    await session.flush()

    await session.delete(defect)
    await session.flush()

    result = await session.scalars(
        select(AuditLog).where(AuditLog.resource_id == public_id, AuditLog.action == "delete")
    )
    rows = list(result)
    assert len(rows) == 1
    assert rows[0].resource_type == "defects"
