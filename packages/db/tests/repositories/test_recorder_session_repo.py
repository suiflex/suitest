"""RecorderSessionRepo tests (M2 Task 4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from factories import make_project, make_suite, make_test_case, make_workspace
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.recorder_sessions import (
    RecorderSessionCreate,
    RecorderSessionRepo,
)


async def _make_session(
    session: AsyncSession,
    repo: RecorderSessionRepo,
    *,
    status: str = "active",
    expires_in_minutes: int = 30,
) -> tuple[str, str]:
    """Create a workspace + project + recorder row; return (session_id, ws_id)."""
    ws = await make_workspace(session)
    project = await make_project(session, workspace=ws)
    row = await repo.create(
        RecorderSessionCreate(
            workspace_id=ws.id,
            project_id=project.id,
            start_url="https://app.test/login",
            ws_room="recorder:placeholder",
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=expires_in_minutes),
            status=status,
        )
    )
    return row.id, ws.id


@pytest.mark.asyncio
async def test_create_and_get_by_id(session: AsyncSession) -> None:
    repo = RecorderSessionRepo(session)
    sid, ws_id = await _make_session(session, repo)

    got = await repo.get_by_id(sid, workspace_id=ws_id)
    assert got is not None
    assert got.status == "active"
    assert got.mcp_provider == "playwright-mcp"
    assert got.captured_events_json == []


@pytest.mark.asyncio
async def test_get_by_id_cross_workspace_returns_none(session: AsyncSession) -> None:
    repo = RecorderSessionRepo(session)
    sid, _ws_id = await _make_session(session, repo)
    other = await make_workspace(session)

    assert await repo.get_by_id(sid, workspace_id=other.id) is None
    # Unscoped lookup still finds it.
    assert await repo.get_by_id(sid) is not None


@pytest.mark.asyncio
async def test_append_event_persists(session: AsyncSession) -> None:
    repo = RecorderSessionRepo(session)
    sid, ws_id = await _make_session(session, repo)

    await repo.append_event(sid, {"kind": "navigate", "url": "https://app.test"})
    await repo.append_event(sid, {"kind": "click", "selector": "#go"})
    row = await repo.get_by_id(sid, workspace_id=ws_id)
    assert row is not None
    assert len(row.captured_events_json) == 2
    assert row.captured_events_json[0]["kind"] == "navigate"


@pytest.mark.asyncio
async def test_append_event_cross_workspace_returns_none(session: AsyncSession) -> None:
    repo = RecorderSessionRepo(session)
    sid, _ws_id = await _make_session(session, repo)
    other = await make_workspace(session)

    assert await repo.append_event(sid, {"kind": "navigate"}, workspace_id=other.id) is None


@pytest.mark.asyncio
async def test_update_status(session: AsyncSession) -> None:
    repo = RecorderSessionRepo(session)
    sid, ws_id = await _make_session(session, repo)

    updated = await repo.update_status(sid, "cancelled", workspace_id=ws_id)
    assert updated is not None and updated.status == "cancelled"
    assert await repo.update_status(sid, "cancelled", workspace_id="nope") is None


@pytest.mark.asyncio
async def test_mark_finalized(session: AsyncSession) -> None:
    repo = RecorderSessionRepo(session)
    ws = await make_workspace(session)
    project = await make_project(session, workspace=ws)
    suite = await make_suite(session, project=project)
    case = await make_test_case(session, suite=suite)
    row0 = await repo.create(
        RecorderSessionCreate(
            workspace_id=ws.id,
            project_id=project.id,
            start_url="https://app.test/login",
            ws_room="recorder:placeholder",
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=30),
        )
    )
    now = datetime.now(tz=UTC)

    row = await repo.mark_finalized(
        row0.id, finalized_case_id=case.id, finalized_at=now, workspace_id=ws.id
    )
    assert row is not None
    assert row.status == "finalized"
    assert row.finalized_case_id == case.id
    assert row.finalized_at is not None


@pytest.mark.asyncio
async def test_list_active_expired(session: AsyncSession) -> None:
    repo = RecorderSessionRepo(session)
    # One already expired, one healthy.
    expired_id, _ = await _make_session(session, repo, expires_in_minutes=-5)
    fresh_id, _ = await _make_session(session, repo, expires_in_minutes=30)
    # An expired-but-already-finalized row must NOT be returned.
    fin_id, fin_ws = await _make_session(session, repo, expires_in_minutes=-5)
    await repo.update_status(fin_id, "finalized", workspace_id=fin_ws)

    rows = await repo.list_active_expired(datetime.now(tz=UTC))
    ids = {r.id for r in rows}
    assert expired_id in ids
    assert fresh_id not in ids
    assert fin_id not in ids
