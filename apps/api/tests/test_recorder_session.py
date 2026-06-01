"""Tests for the live browser recorder (M2 Task 4).

Drives the recorder end-to-end against a real DB with a MOCKED
:class:`McpInvoker` (no browser) and an in-process ``fakeredis`` for pub/sub.
The HTTP endpoints exercise the start / finalize / cancel contract (incl. the
410-on-expired + 404-cross-workspace gates); the manager-level behaviours
(append persistence, masking, idle expiry) are exercised directly so we do not
need a live WS client to push events.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import fakeredis.aioredis
import pytest
import pytest_asyncio
import suitest_api.routers.generators as generators_router
from sqlalchemy import select, update
from suitest_agent.generators.recorder import RecorderSessionManager
from suitest_api.auth.db import get_async_session
from suitest_api.auth.manager import current_active_user
from suitest_api.main import create_app
from suitest_db.models.case import TestCase
from suitest_db.models.recorder_session import RecorderSession
from suitest_db.repositories.recorder_sessions import RecorderSessionRepo
from suitest_mcp.models import McpToolResult
from suitest_shared.domain.enums import CaseSource, CaseStatus, Role
from suitest_shared.schemas.generator_input import (
    RecorderEvent,
    RecorderEventKind,
)

if TYPE_CHECKING:
    from api_harness import ApiDb
    from fastapi import FastAPI
    from httpx import AsyncClient
    from suitest_db.models.user import User
    from suitest_mcp.invoker import InvokeContext

_START_URL = "https://app.test/login"


class _FakeInvoker:
    """Records invocations; start/stop recording return empty (no trace)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def invoke(
        self,
        *,
        explicit_provider: str | None,
        tool: str,
        arguments: dict[str, object],
        ctx: InvokeContext,
    ) -> McpToolResult:
        self.calls.append(tool)
        return McpToolResult(ok=True, output={}, duration_ms=1)


@pytest_asyncio.fixture
async def fake_redis() -> AsyncIterator[object]:
    """In-process Redis. Typed ``object`` because the pre-commit mypy hook does
    not pull ``fakeredis`` stubs (would raise ``no-any-unimported``)."""
    server = fakeredis.FakeServer()
    client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture(autouse=True)
def _mock_invoker(monkeypatch: pytest.MonkeyPatch) -> _FakeInvoker:
    """Replace the router's invoker wiring with a recording fake."""
    invoker = _FakeInvoker()
    monkeypatch.setattr(
        generators_router,
        "_build_mcp_invoker",
        lambda workspace_id, request: invoker,
    )
    return invoker


def _build_app(api_db: ApiDb, user: User, redis: object) -> FastAPI:
    """create_app() with a session override, a current user, and fakeredis.

    ``ws_redis`` is set so the recorder endpoints can publish, but we do NOT run
    the lifespan (no :class:`WsConnectionManager` background listener) — these
    HTTP tests never open a WS, and a lingering listener bound to a finished
    test's event loop would otherwise corrupt the next test's DB engine.
    """
    app = create_app()
    app.state.ws_redis = redis

    async def _override_session() -> AsyncIterator[object]:
        async with api_db.maker() as session:
            yield session

    app.dependency_overrides[get_async_session] = _override_session
    app.dependency_overrides[current_active_user] = lambda: user
    return app


@asynccontextmanager
async def _client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Yield an httpx client bound to ``app`` WITHOUT running its lifespan."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def _seed_project_suite(
    api_db: ApiDb, ws_id: str, *, slug: str = "rec-proj"
) -> tuple[str, str]:
    """Create a project + suite; return (project_id, suite_id)."""
    from suitest_db.models.project import Project, Suite

    async with api_db.maker() as session:
        project = Project(workspace_id=ws_id, slug=slug, name="P")
        session.add(project)
        await session.flush()
        suite = Suite(project_id=project.id, name="S", order=0)
        session.add(suite)
        await session.commit()
        return project.id, suite.id


async def _start(client: AsyncClient, ws_id: str, project_id: str) -> dict[str, object]:
    resp = await client.post(
        "/api/v1/generators/recorder/sessions",
        headers={"X-Workspace-Id": ws_id},
        json={"project_id": project_id, "start_url": _START_URL},
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, object] = resp.json()
    return body


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_session_creates_row(api_db: ApiDb, fake_redis: object) -> None:
    user = await api_db.seed_user(email="rec-start@example.com")
    ws = await api_db.member_workspace(user, slug="rec-start-ws")
    project_id, _suite_id = await _seed_project_suite(api_db, ws.id)

    app = _build_app(api_db, user, fake_redis)
    async with _client(app) as c:
        body = await _start(c, ws.id, project_id)

    assert body["ws_room"] == f"recorder:{body['session_id']}"
    async with api_db.maker() as session:
        row = await session.scalar(
            select(RecorderSession).where(RecorderSession.id == body["session_id"])
        )
        assert row is not None
        assert row.status == "active"
        assert row.workspace_id == ws.id


@pytest.mark.asyncio
async def test_append_event_persists(api_db: ApiDb, fake_redis: object) -> None:
    user = await api_db.seed_user(email="rec-append@example.com")
    ws = await api_db.member_workspace(user, slug="rec-append-ws")
    project_id, _suite_id = await _seed_project_suite(api_db, ws.id)

    async with api_db.maker() as session:
        invoker = _FakeInvoker()
        mgr = RecorderSessionManager(invoker, RecorderSessionRepo(session), fake_redis)  # type: ignore[arg-type]
        row, _ = await mgr.start(
            ws.id,
            str(user.id),
            _start_request(project_id),
        )
        await session.commit()
        sid = row.id

    async with api_db.maker() as session:
        mgr = RecorderSessionManager(_FakeInvoker(), RecorderSessionRepo(session), fake_redis)  # type: ignore[arg-type]
        for i in range(3):
            await mgr.append_event(
                sid,
                ws.id,
                RecorderEvent(
                    kind=RecorderEventKind.CLICK,
                    timestamp=datetime.now(tz=UTC),
                    selector=f"#btn-{i}",
                ),
            )
        await session.commit()

    async with api_db.maker() as session:
        row2 = await session.scalar(select(RecorderSession).where(RecorderSession.id == sid))
        assert row2 is not None
        assert len(row2.captured_events_json) == 3


@pytest.mark.asyncio
async def test_finalize_emits_case_with_steps_per_event(api_db: ApiDb, fake_redis: object) -> None:
    user = await api_db.seed_user(email="rec-fin@example.com")
    ws = await api_db.member_workspace(user, slug="rec-fin-ws")
    project_id, suite_id = await _seed_project_suite(api_db, ws.id)

    app = _build_app(api_db, user, fake_redis)
    async with _client(app) as c:
        body = await _start(c, ws.id, project_id)
        sid = str(body["session_id"])

        await _append_via_manager(api_db, fake_redis, sid, ws.id, _four_events())

        resp = await c.post(
            f"/api/v1/generators/recorder/sessions/{sid}/finalize",
            headers={"X-Workspace-Id": ws.id},
            json={"target_suite_id": suite_id, "name": "Recorded login"},
        )
    assert resp.status_code == 200, resp.text
    detail = resp.json()
    assert detail["source"] == CaseSource.RECORDER.value
    assert len(detail["steps"]) == 4

    async with api_db.maker() as session:
        case = await session.scalar(select(TestCase).where(TestCase.suite_id == suite_id))
        assert case is not None
        assert case.status is CaseStatus.DRAFT
        row = await session.scalar(select(RecorderSession).where(RecorderSession.id == sid))
        assert row is not None
        assert row.status == "finalized"
        assert row.finalized_case_id == case.id


@pytest.mark.asyncio
async def test_finalize_masks_password_field(api_db: ApiDb, fake_redis: object) -> None:
    user = await api_db.seed_user(email="rec-mask@example.com")
    ws = await api_db.member_workspace(user, slug="rec-mask-ws")
    project_id, suite_id = await _seed_project_suite(api_db, ws.id)

    app = _build_app(api_db, user, fake_redis)
    async with _client(app) as c:
        body = await _start(c, ws.id, project_id)
        sid = str(body["session_id"])
        await _append_via_manager(
            api_db,
            fake_redis,
            sid,
            ws.id,
            [
                RecorderEvent(
                    kind=RecorderEventKind.TYPE,
                    timestamp=datetime.now(tz=UTC),
                    selector="#password",
                    text="hunter2-secret",
                    masked=True,
                )
            ],
        )
        resp = await c.post(
            f"/api/v1/generators/recorder/sessions/{sid}/finalize",
            headers={"X-Workspace-Id": ws.id},
            json={"target_suite_id": suite_id, "name": "Masked"},
        )
    assert resp.status_code == 200, resp.text
    step_code = resp.json()["steps"][0]["code"]
    assert "{{password}}" in step_code
    assert "hunter2-secret" not in step_code


@pytest.mark.asyncio
async def test_finalize_after_expired_returns_410(api_db: ApiDb, fake_redis: object) -> None:
    user = await api_db.seed_user(email="rec-exp@example.com")
    ws = await api_db.member_workspace(user, slug="rec-exp-ws")
    project_id, suite_id = await _seed_project_suite(api_db, ws.id)

    app = _build_app(api_db, user, fake_redis)
    async with _client(app) as c:
        body = await _start(c, ws.id, project_id)
        sid = str(body["session_id"])
        # Force the session past its TTL + mark expired (as the sweep would).
        async with api_db.maker() as session:
            await session.execute(
                update(RecorderSession)
                .where(RecorderSession.id == sid)
                .values(status="expired", expires_at=datetime.now(tz=UTC) - timedelta(minutes=1))
            )
            await session.commit()
        resp = await c.post(
            f"/api/v1/generators/recorder/sessions/{sid}/finalize",
            headers={"X-Workspace-Id": ws.id},
            json={"target_suite_id": suite_id, "name": "x"},
        )
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_double_finalize_returns_410(api_db: ApiDb, fake_redis: object) -> None:
    user = await api_db.seed_user(email="rec-dbl@example.com")
    ws = await api_db.member_workspace(user, slug="rec-dbl-ws")
    project_id, suite_id = await _seed_project_suite(api_db, ws.id)

    app = _build_app(api_db, user, fake_redis)
    async with _client(app) as c:
        body = await _start(c, ws.id, project_id)
        sid = str(body["session_id"])
        await _append_via_manager(api_db, fake_redis, sid, ws.id, _four_events())
        first = await c.post(
            f"/api/v1/generators/recorder/sessions/{sid}/finalize",
            headers={"X-Workspace-Id": ws.id},
            json={"target_suite_id": suite_id, "name": "one"},
        )
        assert first.status_code == 200, first.text
        second = await c.post(
            f"/api/v1/generators/recorder/sessions/{sid}/finalize",
            headers={"X-Workspace-Id": ws.id},
            json={"target_suite_id": suite_id, "name": "two"},
        )
    assert second.status_code == 410


@pytest.mark.asyncio
async def test_cancel_session_marks_cancelled(api_db: ApiDb, fake_redis: object) -> None:
    user = await api_db.seed_user(email="rec-cancel@example.com")
    ws = await api_db.member_workspace(user, slug="rec-cancel-ws")
    project_id, _suite_id = await _seed_project_suite(api_db, ws.id)

    app = _build_app(api_db, user, fake_redis)
    async with _client(app) as c:
        body = await _start(c, ws.id, project_id)
        sid = str(body["session_id"])
        resp = await c.delete(
            f"/api/v1/generators/recorder/sessions/{sid}",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 204
    async with api_db.maker() as session:
        row = await session.scalar(select(RecorderSession).where(RecorderSession.id == sid))
        assert row is not None and row.status == "cancelled"


@pytest.mark.asyncio
async def test_cross_workspace_session_returns_404(api_db: ApiDb, fake_redis: object) -> None:
    owner = await api_db.seed_user(email="rec-owner@example.com")
    ws_a = await api_db.member_workspace(owner, slug="rec-a-ws")
    project_id, _ = await _seed_project_suite(api_db, ws_a.id)

    intruder = await api_db.seed_user(email="rec-intruder@example.com")
    ws_b = await api_db.member_workspace(intruder, slug="rec-b-ws")
    _pb, suite_b = await _seed_project_suite(api_db, ws_b.id, slug="rec-b-proj")

    # Owner starts a session in workspace A.
    app_owner = _build_app(api_db, owner, fake_redis)
    async with _client(app_owner) as c:
        body = await _start(c, ws_a.id, project_id)
        sid = str(body["session_id"])

    # Intruder (workspace B) tries to finalize A's session → 404, not 403.
    app_intruder = _build_app(api_db, intruder, fake_redis)
    async with _client(app_intruder) as c:
        resp = await c.post(
            f"/api/v1/generators/recorder/sessions/{sid}/finalize",
            headers={"X-Workspace-Id": ws_b.id},
            json={"target_suite_id": suite_b, "name": "stolen"},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_expire_idle_sessions_background(api_db: ApiDb, fake_redis: object) -> None:
    user = await api_db.seed_user(email="rec-sweep@example.com")
    ws = await api_db.member_workspace(user, slug="rec-sweep-ws")
    project_id, _suite_id = await _seed_project_suite(api_db, ws.id)

    invoker = _FakeInvoker()
    async with api_db.maker() as session:
        mgr = RecorderSessionManager(invoker, RecorderSessionRepo(session), fake_redis)  # type: ignore[arg-type]
        fresh, _ = await mgr.start(ws.id, str(user.id), _start_request(project_id))
        stale, _ = await mgr.start(ws.id, str(user.id), _start_request(project_id))
        await session.commit()
        # Backdate the stale one past its TTL.
        await session.execute(
            update(RecorderSession)
            .where(RecorderSession.id == stale.id)
            .values(expires_at=datetime.now(tz=UTC) - timedelta(minutes=5))
        )
        await session.commit()
        fresh_id, stale_id = fresh.id, stale.id

    async with api_db.maker() as session:
        mgr = RecorderSessionManager(invoker, RecorderSessionRepo(session), fake_redis)  # type: ignore[arg-type]
        count = await mgr.expire_idle_sessions()
        await session.commit()
    assert count == 1
    assert "browser.stop_recording" in invoker.calls

    async with api_db.maker() as session:
        rows = {
            r.id: r.status
            for r in (
                await session.scalars(
                    select(RecorderSession).where(RecorderSession.id.in_([fresh_id, stale_id]))
                )
            ).all()
        }
    assert rows[stale_id] == "expired"
    assert rows[fresh_id] == "active"


@pytest.mark.asyncio
async def test_start_viewer_role_forbidden(api_db: ApiDb, fake_redis: object) -> None:
    user = await api_db.seed_user(email="rec-viewer@example.com")
    ws = await api_db.seed_workspace(slug="rec-viewer-ws", name="V")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER)
    project_id, _suite_id = await _seed_project_suite(api_db, ws.id)

    app = _build_app(api_db, user, fake_redis)
    async with _client(app) as c:
        resp = await c.post(
            "/api/v1/generators/recorder/sessions",
            headers={"X-Workspace-Id": ws.id},
            json={"project_id": project_id, "start_url": _START_URL},
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# helpers


def _start_request(project_id: str):  # type: ignore[no-untyped-def]
    from suitest_shared.schemas.generator_input import RecorderSessionStartRequest

    return RecorderSessionStartRequest(project_id=project_id, start_url=_START_URL)


def _four_events() -> list[RecorderEvent]:
    now = datetime.now(tz=UTC)
    return [
        RecorderEvent(kind=RecorderEventKind.NAVIGATE, timestamp=now, url=_START_URL),
        RecorderEvent(kind=RecorderEventKind.TYPE, timestamp=now, selector="#email", text="a@b.io"),
        RecorderEvent(
            kind=RecorderEventKind.TYPE,
            timestamp=now,
            selector="#password",
            text="secret",
            masked=True,
        ),
        RecorderEvent(kind=RecorderEventKind.CLICK, timestamp=now, selector="#submit"),
    ]


async def _append_via_manager(
    api_db: ApiDb,
    redis: object,
    session_id: str,
    workspace_id: str,
    events: list[RecorderEvent],
) -> None:
    async with api_db.maker() as session:
        mgr = RecorderSessionManager(_FakeInvoker(), RecorderSessionRepo(session), redis)  # type: ignore[arg-type]
        for event in events:
            await mgr.append_event(session_id, workspace_id, event)
        await session.commit()
