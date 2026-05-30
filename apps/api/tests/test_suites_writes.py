"""M1d-4 — suite write endpoint tests (docs/API.md §3.4).

Covers ``POST /suites``, ``PATCH /suites/:id`` (incl. ``case_order`` reorder),
``DELETE /suites/:id?confirmCascade=...``, and ``POST /suites/:id/restore``.
Each test exercises ONE acceptance criterion from plan-05b — happy paths
first, then cross-workspace 404, role-gate 403, case_order mismatch,
cascade confirmation, restore idempotency, audit + WS broadcast.
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
# Fixture helpers
# ---------------------------------------------------------------------------


async def _project(api_db: ApiDb, ws_id: str, *, slug: str = "sw-proj") -> Project:
    project = Project(workspace_id=ws_id, slug=slug, name="P")
    await api_db.add_all([project])
    return project


async def _suite(api_db: ApiDb, project_id: str, *, name: str = "S", order: int = 0) -> Suite:
    suite = Suite(project_id=project_id, name=name, order=order)
    await api_db.add_all([suite])
    return suite


async def _case(
    api_db: ApiDb,
    suite_id: str,
    *,
    public_id: str,
    order_in_suite: int = 0,
) -> TestCase:
    case = TestCase(
        suite_id=suite_id,
        public_id=public_id,
        name=public_id,
        source=CaseSource.MANUAL,
        order_in_suite=order_in_suite,
    )
    await api_db.add_all([case])
    return case


# ---------------------------------------------------------------------------
# POST /suites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_suite_creates_under_project(api_db: ApiDb) -> None:
    """Happy path: 201, returned ``id`` non-empty, scoped to the project."""
    user = await api_db.seed_user(email="sw-create@example.com")
    ws = await api_db.member_workspace(user, slug="sw-create-ws")
    project = await _project(api_db, ws.id)

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/suites",
            json={"projectId": project.id, "name": "Smoke", "description": "demo"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["project_id"] == project.id
    assert body["name"] == "Smoke"
    assert body["case_count"] == 0
    assert body["id"]


@pytest.mark.asyncio
async def test_post_suite_cross_workspace_project_id_returns_404(api_db: ApiDb) -> None:
    """Project lives in another workspace → 404 (NOT 403, no enumeration oracle)."""
    user = await api_db.seed_user(email="sw-xws-post@example.com")
    ws = await api_db.member_workspace(user, slug="sw-xws-post-ws")
    other = await api_db.seed_workspace(slug="sw-xws-post-other", name="Other")
    project = await _project(api_db, other.id, slug="sw-xws-post-other-p")

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/suites",
            json={"projectId": project.id, "name": "X"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_post_suite_role_VIEWER_returns_403(api_db: ApiDb) -> None:
    """VIEWER cannot create suites per docs/API.md role gate."""
    user = await api_db.seed_user(email="sw-viewer-post@example.com")
    ws = await api_db.seed_workspace(slug="sw-viewer-post-ws", name="ViewerWs")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER)
    project = await _project(api_db, ws.id)

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/suites",
            json={"projectId": project.id, "name": "X"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PATCH /suites/:id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_suite_metadata_updates_name_description(api_db: ApiDb) -> None:
    """PATCH metadata-only → name + description applied."""
    user = await api_db.seed_user(email="sw-patch@example.com")
    ws = await api_db.member_workspace(user, slug="sw-patch-ws")
    project = await _project(api_db, ws.id)
    suite = await _suite(api_db, project.id, name="orig")

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/suites/{suite.id}",
            json={"name": "renamed", "description": "newdesc"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "renamed"
    assert body["description"] == "newdesc"


@pytest.mark.asyncio
async def test_patch_suite_case_order_reorder_atomic(api_db: ApiDb) -> None:
    """Submitting ``caseOrder`` rewrites every case's ``order_in_suite`` atomically."""
    user = await api_db.seed_user(email="sw-reorder@example.com")
    ws = await api_db.member_workspace(user, slug="sw-reorder-ws")
    project = await _project(api_db, ws.id)
    suite = await _suite(api_db, project.id)
    case_a = await _case(api_db, suite.id, public_id="TC-1045", order_in_suite=0)
    case_b = await _case(api_db, suite.id, public_id="TC-1046", order_in_suite=1)
    case_c = await _case(api_db, suite.id, public_id="TC-1047", order_in_suite=2)

    new_order = [case_c.id, case_a.id, case_b.id]
    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/suites/{suite.id}",
            json={"caseOrder": new_order},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text

    async with api_db.maker() as session:
        rows = (await session.scalars(select(TestCase).where(TestCase.suite_id == suite.id))).all()
    ranks = {r.id: r.order_in_suite for r in rows}
    assert ranks[case_c.id] == 0
    assert ranks[case_a.id] == 1
    assert ranks[case_b.id] == 2


@pytest.mark.asyncio
async def test_patch_suite_case_order_unknown_id_returns_400(api_db: ApiDb) -> None:
    """Unknown case id in case_order → 400 with ``details.unknown``."""
    user = await api_db.seed_user(email="sw-reorder-unk@example.com")
    ws = await api_db.member_workspace(user, slug="sw-reorder-unk-ws")
    project = await _project(api_db, ws.id)
    suite = await _suite(api_db, project.id)
    await _case(api_db, suite.id, public_id="TC-A", order_in_suite=0)

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/suites/{suite.id}",
            json={"caseOrder": ["does-not-exist"]},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 400, resp.text
    envelope = resp.json()["detail"]["error"]
    assert envelope["code"] == "INVALID_CASE_ORDER"
    assert envelope["details"]["unknown"] == ["does-not-exist"]


@pytest.mark.asyncio
async def test_patch_suite_case_order_missing_id_returns_400(api_db: ApiDb) -> None:
    """Live case missing from case_order → 400 with ``details.missing``."""
    user = await api_db.seed_user(email="sw-reorder-miss@example.com")
    ws = await api_db.member_workspace(user, slug="sw-reorder-miss-ws")
    project = await _project(api_db, ws.id)
    suite = await _suite(api_db, project.id)
    case_a = await _case(api_db, suite.id, public_id="TC-X", order_in_suite=0)
    case_b = await _case(api_db, suite.id, public_id="TC-Y", order_in_suite=1)

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/suites/{suite.id}",
            json={"caseOrder": [case_a.id]},  # case_b omitted
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 400, resp.text
    envelope = resp.json()["detail"]["error"]
    assert envelope["code"] == "INVALID_CASE_ORDER"
    assert envelope["details"]["missing"] == [case_b.id]


@pytest.mark.asyncio
async def test_patch_suite_cross_workspace_returns_404(api_db: ApiDb) -> None:
    """Suite in another workspace → 404 (NEVER 403)."""
    user = await api_db.seed_user(email="sw-xws-patch@example.com")
    ws = await api_db.member_workspace(user, slug="sw-xws-patch-ws")
    other = await api_db.seed_workspace(slug="sw-xws-patch-other", name="Other")
    project = await _project(api_db, other.id, slug="sw-xws-patch-p")
    suite = await _suite(api_db, project.id)

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/suites/{suite.id}",
            json={"name": "x"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /suites/:id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_suite_without_confirmCascade_returns_409(api_db: ApiDb) -> None:
    """Suite with cases + no ``confirmCascade`` → 409 ``CONFIRM_CASCADE_REQUIRED``."""
    user = await api_db.seed_user(email="sw-del-409@example.com")
    ws = await api_db.member_workspace(user, slug="sw-del-409-ws")
    project = await _project(api_db, ws.id)
    suite = await _suite(api_db, project.id)
    await _case(api_db, suite.id, public_id="TC-D1")
    await _case(api_db, suite.id, public_id="TC-D2")

    async with api_db.client(user) as c:
        resp = await c.delete(
            f"/api/v1/suites/{suite.id}",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 409, resp.text
    envelope = resp.json()["detail"]["error"]
    assert envelope["code"] == "CONFIRM_CASCADE_REQUIRED"
    assert envelope["details"]["childCount"] == 2
    assert envelope["details"]["resourceType"] == "suite"


@pytest.mark.asyncio
async def test_delete_suite_with_confirmCascade_cascade_tombstones_children(
    api_db: ApiDb,
) -> None:
    """``?confirmCascade=true`` → 204; suite + every active case land tombstoned."""
    user = await api_db.seed_user(email="sw-del-cascade@example.com")
    ws = await api_db.member_workspace(user, slug="sw-del-cascade-ws")
    project = await _project(api_db, ws.id)
    suite = await _suite(api_db, project.id)
    case_a = await _case(api_db, suite.id, public_id="TC-C1")
    case_b = await _case(api_db, suite.id, public_id="TC-C2")

    async with api_db.client(user) as c:
        resp = await c.delete(
            f"/api/v1/suites/{suite.id}?confirmCascade=true",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 204, resp.text

    async with api_db.maker() as session:
        s = await session.get(Suite, suite.id)
        a = await session.get(TestCase, case_a.id)
        b = await session.get(TestCase, case_b.id)
    assert s is not None and s.deleted_at is not None
    assert a is not None and a.deleted_at is not None
    assert b is not None and b.deleted_at is not None


@pytest.mark.asyncio
async def test_delete_suite_with_zero_children_no_confirm_needed(api_db: ApiDb) -> None:
    """Empty suite needs no ``confirmCascade`` → 204 immediately."""
    user = await api_db.seed_user(email="sw-del-empty@example.com")
    ws = await api_db.member_workspace(user, slug="sw-del-empty-ws")
    project = await _project(api_db, ws.id)
    suite = await _suite(api_db, project.id)

    async with api_db.client(user) as c:
        resp = await c.delete(
            f"/api/v1/suites/{suite.id}",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 204, resp.text


@pytest.mark.asyncio
async def test_delete_suite_re_delete_returns_404(api_db: ApiDb) -> None:
    """Idempotency: re-DELETE a tombstoned suite → 404 (already gone)."""
    user = await api_db.seed_user(email="sw-del-idem@example.com")
    ws = await api_db.member_workspace(user, slug="sw-del-idem-ws")
    project = await _project(api_db, ws.id)
    suite = await _suite(api_db, project.id)

    async with api_db.client(user) as c:
        first = await c.delete(
            f"/api/v1/suites/{suite.id}",
            headers={"X-Workspace-Id": ws.id},
        )
        second = await c.delete(
            f"/api/v1/suites/{suite.id}",
            headers={"X-Workspace-Id": ws.id},
        )
    assert first.status_code == 204
    assert second.status_code == 404


# ---------------------------------------------------------------------------
# POST /suites/:id/restore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_suite_clears_deleted_at_but_not_children(api_db: ApiDb) -> None:
    """Restore flips ``suites.deleted_at`` to NULL — children stay tombstoned."""
    user = await api_db.seed_user(email="sw-restore@example.com")
    ws = await api_db.member_workspace(user, slug="sw-restore-ws")
    project = await _project(api_db, ws.id)
    suite = await _suite(api_db, project.id)
    case_a = await _case(api_db, suite.id, public_id="TC-R1")

    async with api_db.client(user) as c:
        del_resp = await c.delete(
            f"/api/v1/suites/{suite.id}?confirmCascade=true",
            headers={"X-Workspace-Id": ws.id},
        )
    assert del_resp.status_code == 204

    async with api_db.client(user) as c:
        restore_resp = await c.post(
            f"/api/v1/suites/{suite.id}/restore",
            headers={"X-Workspace-Id": ws.id},
        )
    assert restore_resp.status_code == 204, restore_resp.text

    async with api_db.maker() as session:
        s = await session.get(Suite, suite.id)
        a = await session.get(TestCase, case_a.id)
    assert s is not None and s.deleted_at is None
    assert a is not None and a.deleted_at is not None


@pytest.mark.asyncio
async def test_restore_suite_idempotent(api_db: ApiDb) -> None:
    """Re-POST after restore returns 204 (idempotent)."""
    user = await api_db.seed_user(email="sw-restore-idem@example.com")
    ws = await api_db.member_workspace(user, slug="sw-restore-idem-ws")
    project = await _project(api_db, ws.id)
    suite = await _suite(api_db, project.id)

    async with api_db.client(user) as c:
        resp = await c.post(
            f"/api/v1/suites/{suite.id}/restore",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# LIST excludes deleted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_suites_excludes_deleted(api_db: ApiDb) -> None:
    """``GET /suites`` default-filters ``deleted_at IS NULL`` (partial index path)."""
    user = await api_db.seed_user(email="sw-list-act@example.com")
    ws = await api_db.member_workspace(user, slug="sw-list-act-ws")
    project = await _project(api_db, ws.id)
    active = await _suite(api_db, project.id, name="active")
    deleted = await _suite(api_db, project.id, name="dead")
    async with api_db.client(user) as c:
        await c.delete(
            f"/api/v1/suites/{deleted.id}",
            headers={"X-Workspace-Id": ws.id},
        )
        resp = await c.get(
            f"/api/v1/suites?projectId={project.id}",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.json()}
    assert ids == {active.id}


# ---------------------------------------------------------------------------
# Cross-workspace + role gate (DELETE / restore / PATCH)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_suite_cross_workspace_returns_404(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="sw-del-xws@example.com")
    ws = await api_db.member_workspace(user, slug="sw-del-xws-ws")
    other = await api_db.seed_workspace(slug="sw-del-xws-other", name="Other")
    project = await _project(api_db, other.id, slug="sw-del-xws-other-p")
    suite = await _suite(api_db, project.id)

    async with api_db.client(user) as c:
        resp = await c.delete(
            f"/api/v1/suites/{suite.id}",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_suite_role_VIEWER_returns_403(api_db: ApiDb) -> None:
    """VIEWER cannot delete suites — role gate fires before scope check."""
    user = await api_db.seed_user(email="sw-del-viewer@example.com")
    ws = await api_db.seed_workspace(slug="sw-del-viewer-ws", name="V")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER)
    project = await _project(api_db, ws.id)
    suite = await _suite(api_db, project.id)

    async with api_db.client(user) as c:
        resp = await c.delete(
            f"/api/v1/suites/{suite.id}",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_patch_suite_role_VIEWER_returns_403(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="sw-patch-viewer@example.com")
    ws = await api_db.seed_workspace(slug="sw-patch-viewer-ws", name="V")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER)
    project = await _project(api_db, ws.id)
    suite = await _suite(api_db, project.id)

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/suites/{suite.id}",
            json={"name": "x"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_restore_suite_role_VIEWER_returns_403(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="sw-restore-viewer@example.com")
    ws = await api_db.seed_workspace(slug="sw-restore-viewer-ws", name="V")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER)
    project = await _project(api_db, ws.id)
    suite = await _suite(api_db, project.id)

    async with api_db.client(user) as c:
        resp = await c.post(
            f"/api/v1/suites/{suite.id}/restore",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_suite_audit_row_written(api_db: ApiDb) -> None:
    """``suite.created`` audit row lands with the workspace + resource id."""
    user = await api_db.seed_user(email="sw-audit-create@example.com")
    ws = await api_db.member_workspace(user, slug="sw-audit-create-ws")
    project = await _project(api_db, ws.id)

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/suites",
            json={"projectId": project.id, "name": "Audited"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 201, resp.text
    async with api_db.maker() as session:
        rows = (await session.scalars(select(AuditLog).where(AuditLog.workspace_id == ws.id))).all()
    actions = {r.action for r in rows}
    assert "suite.created" in actions


@pytest.mark.asyncio
async def test_delete_suite_audit_row_written_with_child_ids(api_db: ApiDb) -> None:
    """Cascade delete audits ``suite.soft_deleted_with_cascade`` with ``childCaseIds``."""
    user = await api_db.seed_user(email="sw-audit-del@example.com")
    ws = await api_db.member_workspace(user, slug="sw-audit-del-ws")
    project = await _project(api_db, ws.id)
    suite = await _suite(api_db, project.id)
    case_a = await _case(api_db, suite.id, public_id="TC-AD1")
    case_b = await _case(api_db, suite.id, public_id="TC-AD2")

    async with api_db.client(user) as c:
        resp = await c.delete(
            f"/api/v1/suites/{suite.id}?confirmCascade=true",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 204

    async with api_db.maker() as session:
        rows = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.workspace_id == ws.id,
                    AuditLog.action == "suite.soft_deleted_with_cascade",
                )
            )
        ).all()
    assert rows, "cascade soft-delete must write an explicit audit row"
    metadata = rows[0].metadata_json or {}
    expected_ids = sorted([case_a.id, case_b.id])
    assert sorted(metadata.get("childCaseIds", [])) == expected_ids
    assert metadata.get("childCount") == 2


# ---------------------------------------------------------------------------
# WS broadcast
# ---------------------------------------------------------------------------


# mypy: warn_unused_ignores=False
@pytest.mark.asyncio
async def test_post_suite_emits_suite_created_ws_event(api_db: ApiDb) -> None:
    """A successful create publishes ``suite.created`` on ``workspace:<wsId>``."""
    import fakeredis
    import fakeredis.aioredis
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    user = await api_db.seed_user(email="sw-ws-event@example.com")
    ws = await api_db.member_workspace(user, slug="sw-ws-event-ws")
    project = await _project(api_db, ws.id)

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
            resp = await c.post(
                "/api/v1/suites",
                json={"projectId": project.id, "name": "WS"},
                headers={"X-Workspace-Id": ws.id},
            )
            assert resp.status_code == 201
            await _drain()

    await pubsub.aclose()  # type: ignore[no-untyped-call]
    await redis_client.aclose()  # type: ignore[no-untyped-call]
    assert received, "WS publish must reach the workspace:<id> channel"
    decoded = received[0].decode()
    assert "suite.created" in decoded
