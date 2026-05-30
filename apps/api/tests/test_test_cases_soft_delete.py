"""M1d-3 — test case soft delete + restore endpoint tests (docs/API.md §3.3).

Covers ``DELETE /test-cases/:id`` and ``POST /test-cases/:id/restore`` plus the
``?includeDeleted=true`` query param contract on the read endpoints. Each test
nails ONE acceptance criterion from plan-05b "Task M1d-3":

* DELETE happy → 204 + ``deleted_at`` populated.
* Re-DELETE → 404 (per ``docs/API.md §3.3`` because LIST + GET hide tombstones
  by default — a DELETE that sees nothing is indistinguishable from "no such
  row").
* GET, LIST, PATCH default-filter tombstones.
* ``?includeDeleted=true`` is ADMIN/OWNER only; QA + VIEWER get 403.
* Restore happy → 204 + ``deleted_at IS NULL``.
* Restore of an already-active row → 204 (idempotent per ``docs/API.md §3.3``).
* Restore of a never-existed row → 404.
* Cross-workspace DELETE / restore → 404 (NOT 403 — avoids enumeration oracle).
* Audit rows ``test_case.soft_deleted`` + ``test_case.restored`` written.
* WS events ``case.deleted`` + ``case.restored`` published on
  ``workspace:<wsId>``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select
from suitest_db.models.audit import AuditLog
from suitest_db.models.case import TestCase
from suitest_db.models.project import Project, Suite
from suitest_shared.domain.enums import CaseSource, Role

if TYPE_CHECKING:
    from api_harness import ApiDb


# ---------------------------------------------------------------------------
# Fixture helpers (mirrors M1d-2 conventions in test_test_cases_writes.py)
# ---------------------------------------------------------------------------


async def _project_suite(api_db: ApiDb, ws_id: str, *, slug: str = "tcsd-proj") -> Suite:
    project = Project(workspace_id=ws_id, slug=slug, name="P")
    await api_db.add_all([project])
    suite = Suite(project_id=project.id, name="S", order=0)
    await api_db.add_all([suite])
    return suite


async def _seed_case(
    api_db: ApiDb, suite_id: str, *, public_id: str, name: str = "case"
) -> TestCase:
    case = TestCase(suite_id=suite_id, public_id=public_id, name=name, source=CaseSource.MANUAL)
    await api_db.add_all([case])
    return case


# ---------------------------------------------------------------------------
# DELETE happy path + idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_test_case_returns_204_and_sets_deleted_at(api_db: ApiDb) -> None:
    """DELETE on an active case → 204 + ``deleted_at`` populated."""
    user = await api_db.seed_user(email="tcsd-del@example.com")
    ws = await api_db.member_workspace(user, slug="tcsd-del-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-D1")

    async with api_db.client(user) as c:
        resp = await c.delete(
            f"/api/v1/test-cases/{case.id}",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 204, resp.text

    async with api_db.maker() as session:
        row = await session.scalar(select(TestCase).where(TestCase.id == case.id))
    assert row is not None
    assert row.deleted_at is not None


@pytest.mark.asyncio
async def test_delete_test_case_re_delete_returns_404(api_db: ApiDb) -> None:
    """Re-DELETE against an already-tombstoned case → 404 (not 204)."""
    user = await api_db.seed_user(email="tcsd-redel@example.com")
    ws = await api_db.member_workspace(user, slug="tcsd-redel-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-D2")

    async with api_db.client(user) as c:
        first = await c.delete(
            f"/api/v1/test-cases/{case.id}",
            headers={"X-Workspace-Id": ws.id},
        )
        assert first.status_code == 204, first.text
        second = await c.delete(
            f"/api/v1/test-cases/{case.id}",
            headers={"X-Workspace-Id": ws.id},
        )
    assert second.status_code == 404, second.text


@pytest.mark.asyncio
async def test_delete_test_case_unknown_id_returns_404(api_db: ApiDb) -> None:
    """DELETE on a never-existed id → 404."""
    user = await api_db.seed_user(email="tcsd-unk@example.com")
    ws = await api_db.member_workspace(user, slug="tcsd-unk-ws")
    # No case seeded; arbitrary id below.

    async with api_db.client(user) as c:
        resp = await c.delete(
            "/api/v1/test-cases/ck_does_not_exist",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_delete_test_case_cross_workspace_returns_404(api_db: ApiDb) -> None:
    """DELETE against another workspace's case → 404 (NOT 403)."""
    user = await api_db.seed_user(email="tcsd-xws@example.com")
    ws = await api_db.member_workspace(user, slug="tcsd-xws-ws")
    other = await api_db.seed_workspace(slug="tcsd-xws-other", name="Other")
    suite = await _project_suite(api_db, other.id, slug="tcsd-xws-other-p")
    case = await _seed_case(api_db, suite.id, public_id="TC-XWS")

    async with api_db.client(user) as c:
        resp = await c.delete(
            f"/api/v1/test-cases/{case.id}",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_test_case_role_viewer_returns_403(api_db: ApiDb) -> None:
    """VIEWER cannot delete test cases per docs/API.md role gate."""
    user = await api_db.seed_user(email="tcsd-viewer@example.com")
    ws = await api_db.seed_workspace(slug="tcsd-viewer-ws", name="ViewerWs")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER)
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-VWR")

    async with api_db.client(user) as c:
        resp = await c.delete(
            f"/api/v1/test-cases/{case.id}",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Default filter — GET / LIST / PATCH hide tombstones
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_deleted_test_case_returns_404_by_default(api_db: ApiDb) -> None:
    """After soft delete, GET hides the row → 404."""
    user = await api_db.seed_user(email="tcsd-get@example.com")
    ws = await api_db.member_workspace(user, slug="tcsd-get-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-G1")

    async with api_db.client(user) as c:
        del_resp = await c.delete(
            f"/api/v1/test-cases/{case.id}",
            headers={"X-Workspace-Id": ws.id},
        )
        assert del_resp.status_code == 204
        get_resp = await c.get(
            f"/api/v1/test-cases/{case.id}",
            headers={"X-Workspace-Id": ws.id},
        )
    assert get_resp.status_code == 404, get_resp.text


@pytest.mark.asyncio
async def test_get_deleted_test_case_admin_include_deleted_returns_200(api_db: ApiDb) -> None:
    """ADMIN ``?includeDeleted=true`` surfaces a tombstoned case."""
    user = await api_db.seed_user(email="tcsd-get-admin@example.com")
    ws = await api_db.seed_workspace(slug="tcsd-get-admin-ws", name="AdminWs")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.ADMIN)
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-G2")

    async with api_db.client(user) as c:
        del_resp = await c.delete(
            f"/api/v1/test-cases/{case.id}",
            headers={"X-Workspace-Id": ws.id},
        )
        assert del_resp.status_code == 204
        get_resp = await c.get(
            f"/api/v1/test-cases/{case.id}?includeDeleted=true",
            headers={"X-Workspace-Id": ws.id},
        )
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["id"] == case.id


@pytest.mark.asyncio
async def test_list_test_cases_excludes_deleted_by_default(api_db: ApiDb) -> None:
    """LIST excludes tombstones unless ``?includeDeleted=true``."""
    user = await api_db.seed_user(email="tcsd-list@example.com")
    ws = await api_db.member_workspace(user, slug="tcsd-list-ws")
    suite = await _project_suite(api_db, ws.id)
    keep = await _seed_case(api_db, suite.id, public_id="TC-L1", name="keep")
    drop = await _seed_case(api_db, suite.id, public_id="TC-L2", name="drop")

    async with api_db.client(user) as c:
        del_resp = await c.delete(
            f"/api/v1/test-cases/{drop.id}",
            headers={"X-Workspace-Id": ws.id},
        )
        assert del_resp.status_code == 204
        list_resp = await c.get(
            f"/api/v1/test-cases?suiteId={suite.id}",
            headers={"X-Workspace-Id": ws.id},
        )
    assert list_resp.status_code == 200, list_resp.text
    ids = {item["id"] for item in list_resp.json()["items"]}
    assert keep.id in ids
    assert drop.id not in ids


@pytest.mark.asyncio
async def test_list_include_deleted_qa_returns_403(api_db: ApiDb) -> None:
    """QA asking for ``includeDeleted=true`` is rejected — ADMIN gate."""
    user = await api_db.seed_user(email="tcsd-list-qa@example.com")
    ws = await api_db.seed_workspace(slug="tcsd-list-qa-ws", name="QaWs")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.QA)
    suite = await _project_suite(api_db, ws.id)

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/test-cases?suiteId={suite.id}&includeDeleted=true",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_list_include_deleted_admin_surfaces_tombstones(api_db: ApiDb) -> None:
    """ADMIN can list tombstoned cases via ``?includeDeleted=true``."""
    user = await api_db.seed_user(email="tcsd-list-admin@example.com")
    ws = await api_db.seed_workspace(slug="tcsd-list-admin-ws", name="AdminWs")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.ADMIN)
    suite = await _project_suite(api_db, ws.id)
    drop = await _seed_case(api_db, suite.id, public_id="TC-L3", name="drop")

    async with api_db.client(user) as c:
        del_resp = await c.delete(
            f"/api/v1/test-cases/{drop.id}",
            headers={"X-Workspace-Id": ws.id},
        )
        assert del_resp.status_code == 204
        list_resp = await c.get(
            f"/api/v1/test-cases?suiteId={suite.id}&includeDeleted=true",
            headers={"X-Workspace-Id": ws.id},
        )
    assert list_resp.status_code == 200, list_resp.text
    ids = {item["id"] for item in list_resp.json()["items"]}
    assert drop.id in ids


@pytest.mark.asyncio
async def test_patch_deleted_test_case_returns_404(api_db: ApiDb) -> None:
    """PATCH against a tombstoned case → 404."""
    user = await api_db.seed_user(email="tcsd-patch@example.com")
    ws = await api_db.member_workspace(user, slug="tcsd-patch-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-P1")

    async with api_db.client(user) as c:
        del_resp = await c.delete(
            f"/api/v1/test-cases/{case.id}",
            headers={"X-Workspace-Id": ws.id},
        )
        assert del_resp.status_code == 204
        patch_resp = await c.patch(
            f"/api/v1/test-cases/{case.id}",
            json={"name": "should-fail"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert patch_resp.status_code == 404, patch_resp.text


# ---------------------------------------------------------------------------
# POST /test-cases/:id/restore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_test_case_returns_204_and_clears_deleted_at(api_db: ApiDb) -> None:
    """POST /restore on a tombstoned case → 204 + ``deleted_at IS NULL``."""
    user = await api_db.seed_user(email="tcsd-restore@example.com")
    ws = await api_db.member_workspace(user, slug="tcsd-restore-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-R1")

    async with api_db.client(user) as c:
        del_resp = await c.delete(
            f"/api/v1/test-cases/{case.id}",
            headers={"X-Workspace-Id": ws.id},
        )
        assert del_resp.status_code == 204
        restore_resp = await c.post(
            f"/api/v1/test-cases/{case.id}/restore",
            headers={"X-Workspace-Id": ws.id},
        )
    assert restore_resp.status_code == 204, restore_resp.text

    async with api_db.maker() as session:
        row = await session.scalar(select(TestCase).where(TestCase.id == case.id))
    assert row is not None
    assert row.deleted_at is None


@pytest.mark.asyncio
async def test_restore_already_active_test_case_is_idempotent_204(api_db: ApiDb) -> None:
    """POST /restore on an already-active case → 204 (idempotent)."""
    user = await api_db.seed_user(email="tcsd-restore-noop@example.com")
    ws = await api_db.member_workspace(user, slug="tcsd-restore-noop-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-R2")

    async with api_db.client(user) as c:
        resp = await c.post(
            f"/api/v1/test-cases/{case.id}/restore",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 204, resp.text


@pytest.mark.asyncio
async def test_restore_never_existed_returns_404(api_db: ApiDb) -> None:
    """POST /restore on an unknown id → 404."""
    user = await api_db.seed_user(email="tcsd-restore-404@example.com")
    ws = await api_db.member_workspace(user, slug="tcsd-restore-404-ws")

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases/ck_never_existed/restore",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_restore_cross_workspace_returns_404(api_db: ApiDb) -> None:
    """POST /restore for another workspace's case → 404."""
    user = await api_db.seed_user(email="tcsd-restore-xws@example.com")
    ws = await api_db.member_workspace(user, slug="tcsd-restore-xws-ws")
    other = await api_db.seed_workspace(slug="tcsd-restore-xws-other", name="Other")
    suite = await _project_suite(api_db, other.id, slug="tcsd-restore-xws-p")
    case = await _seed_case(api_db, suite.id, public_id="TC-RXWS")

    async with api_db.client(user) as c:
        resp = await c.post(
            f"/api/v1/test-cases/{case.id}/restore",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_restore_role_viewer_returns_403(api_db: ApiDb) -> None:
    """VIEWER cannot restore test cases per the writer role gate."""
    user = await api_db.seed_user(email="tcsd-restore-viewer@example.com")
    ws = await api_db.seed_workspace(slug="tcsd-restore-viewer-ws", name="ViewerWs")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER)
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-RVWR")

    async with api_db.client(user) as c:
        resp = await c.post(
            f"/api/v1/test-cases/{case.id}/restore",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Audit rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_writes_test_case_soft_deleted_audit_row(api_db: ApiDb) -> None:
    """Every DELETE writes a ``test_case.soft_deleted`` audit row."""
    user = await api_db.seed_user(email="tcsd-audit-del@example.com")
    ws = await api_db.member_workspace(user, slug="tcsd-audit-del-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-AD1")

    async with api_db.client(user) as c:
        resp = await c.delete(
            f"/api/v1/test-cases/{case.id}",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 204

    async with api_db.maker() as session:
        rows = (await session.scalars(select(AuditLog).where(AuditLog.workspace_id == ws.id))).all()
    actions = {r.action for r in rows}
    assert "test_case.soft_deleted" in actions


@pytest.mark.asyncio
async def test_restore_writes_test_case_restored_audit_row(api_db: ApiDb) -> None:
    """Every transitioning restore writes a ``test_case.restored`` audit row."""
    user = await api_db.seed_user(email="tcsd-audit-restore@example.com")
    ws = await api_db.member_workspace(user, slug="tcsd-audit-restore-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-AR1")

    async with api_db.client(user) as c:
        del_resp = await c.delete(
            f"/api/v1/test-cases/{case.id}",
            headers={"X-Workspace-Id": ws.id},
        )
        assert del_resp.status_code == 204
        restore_resp = await c.post(
            f"/api/v1/test-cases/{case.id}/restore",
            headers={"X-Workspace-Id": ws.id},
        )
        assert restore_resp.status_code == 204

    async with api_db.maker() as session:
        rows = (await session.scalars(select(AuditLog).where(AuditLog.workspace_id == ws.id))).all()
    actions = {r.action for r in rows}
    assert "test_case.restored" in actions


# ---------------------------------------------------------------------------
# WS broadcast
# ---------------------------------------------------------------------------


# mypy: warn_unused_ignores=False
@pytest.mark.asyncio
async def test_delete_emits_case_deleted_ws_event(api_db: ApiDb) -> None:
    """A successful DELETE publishes ``case.deleted`` on ``workspace:<wsId>``."""
    import fakeredis
    import fakeredis.aioredis
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    user = await api_db.seed_user(email="tcsd-ws-del@example.com")
    ws = await api_db.member_workspace(user, slug="tcsd-ws-del-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-WSD1")

    server = fakeredis.FakeServer()
    redis_client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    received: list[bytes] = []

    app = api_db.app_for(user)
    app.state.ws_redis = redis_client

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(f"workspace:{ws.id}")

    async def _drain() -> None:
        await pubsub.get_message(ignore_subscribe_messages=False, timeout=1.0)
        for _ in range(5):
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg is not None:
                received.append(msg["data"])
                return

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.delete(
                f"/api/v1/test-cases/{case.id}",
                headers={"X-Workspace-Id": ws.id},
            )
            assert resp.status_code == 204
            await _drain()

    await pubsub.aclose()  # type: ignore[no-untyped-call]
    await redis_client.aclose()  # type: ignore[no-untyped-call]
    assert received, "DELETE must broadcast on workspace:<id>"
    assert "case.deleted" in received[0].decode()


# mypy: warn_unused_ignores=False
@pytest.mark.asyncio
async def test_restore_emits_case_restored_ws_event(api_db: ApiDb) -> None:
    """A transitioning restore publishes ``case.restored`` on ``workspace:<wsId>``."""
    import fakeredis
    import fakeredis.aioredis
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    user = await api_db.seed_user(email="tcsd-ws-restore@example.com")
    ws = await api_db.member_workspace(user, slug="tcsd-ws-restore-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-WSR1")

    server = fakeredis.FakeServer()
    redis_client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    received: list[bytes] = []

    app = api_db.app_for(user)
    app.state.ws_redis = redis_client

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(f"workspace:{ws.id}")

    async def _drain(want: str) -> None:
        await pubsub.get_message(ignore_subscribe_messages=False, timeout=1.0)
        for _ in range(10):
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg is None:
                continue
            data = msg["data"]
            received.append(data)
            if want in data.decode():
                return

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            del_resp = await c.delete(
                f"/api/v1/test-cases/{case.id}",
                headers={"X-Workspace-Id": ws.id},
            )
            assert del_resp.status_code == 204
            restore_resp = await c.post(
                f"/api/v1/test-cases/{case.id}/restore",
                headers={"X-Workspace-Id": ws.id},
            )
            assert restore_resp.status_code == 204
            await _drain("case.restored")

    await pubsub.aclose()  # type: ignore[no-untyped-call]
    await redis_client.aclose()  # type: ignore[no-untyped-call]
    assert any("case.restored" in r.decode() for r in received), [r.decode() for r in received]
