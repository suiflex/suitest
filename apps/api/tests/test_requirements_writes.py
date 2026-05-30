"""M1d-6 — requirement + link CRUD write endpoint tests (docs/API.md §3.7).

Covers ``POST /requirements``, ``PATCH /requirements/:id``,
``DELETE /requirements/:id``, ``POST /requirements/:id/restore``,
``POST /requirements/:id/links`` and ``DELETE /requirements/:id/links/:case_id``.

Each test exercises ONE acceptance criterion from plan-05b — happy paths first,
then the cross-workspace ``CROSS_WORKSPACE_LINK`` 400, idempotent re-POST link,
restore, soft-delete idempotency, role-gate 403, and audit / WS event shape.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select
from suitest_db.models.audit import AuditLog
from suitest_db.models.case import TestCase
from suitest_db.models.project import Project, Suite
from suitest_db.models.requirement import Requirement, RequirementLink
from suitest_shared.domain.enums import CaseSource, Role

if TYPE_CHECKING:
    from api_harness import ApiDb


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


async def _project(api_db: ApiDb, ws_id: str, *, slug: str = "rw-proj") -> Project:
    """Seed a project under ``ws_id`` and return the persisted row."""
    proj = Project(workspace_id=ws_id, slug=slug, name="P")
    await api_db.add_all([proj])
    return proj


async def _suite_and_case(api_db: ApiDb, project: Project, *, case_public_id: str) -> TestCase:
    """Seed a suite + a single test case under ``project`` and return the case row."""
    suite = Suite(project_id=project.id, name="S", order=0)
    await api_db.add_all([suite])
    case = TestCase(
        suite_id=suite.id,
        public_id=case_public_id,
        name="case",
        source=CaseSource.MANUAL,
    )
    await api_db.add_all([case])
    return case


# ---------------------------------------------------------------------------
# POST /requirements
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_requirement_uses_REQ_public_id_from_helper(api_db: ApiDb) -> None:
    """First create on a fresh workspace assigns ``REQ-1``; second goes to ``REQ-2``."""
    user = await api_db.seed_user(email="req-pub@example.com")
    ws = await api_db.member_workspace(user, slug="req-pub-ws")
    proj = await _project(api_db, ws.id)

    async with api_db.client(user) as c:
        first = await c.post(
            "/api/v1/requirements",
            json={"projectId": proj.id, "title": "Login spec"},
            headers={"X-Workspace-Id": ws.id},
        )
        assert first.status_code == 201, first.text
        first_body = first.json()
        assert first_body["public_id"].startswith("REQ-")
        suffix = int(first_body["public_id"].split("-")[1])
        assert suffix >= 1

        second = await c.post(
            "/api/v1/requirements",
            json={"projectId": proj.id, "title": "Second"},
            headers={"X-Workspace-Id": ws.id},
        )
        assert second.status_code == 201, second.text
        second_suffix = int(second.json()["public_id"].split("-")[1])
        assert second_suffix == suffix + 1


@pytest.mark.asyncio
async def test_post_requirement_cross_workspace_project_id_returns_404(api_db: ApiDb) -> None:
    """Project in another workspace → 404 (NOT 403) to avoid enumeration oracle."""
    user = await api_db.seed_user(email="req-xws@example.com")
    ws = await api_db.member_workspace(user, slug="req-xws-ws")
    other = await api_db.seed_workspace(slug="req-xws-other", name="Other")
    foreign = await _project(api_db, other.id, slug="req-xws-foreign")

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/requirements",
            json={"projectId": foreign.id, "title": "x"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_post_requirement_role_VIEWER_returns_403(api_db: ApiDb) -> None:
    """VIEWER cannot create requirements per docs/API.md role gate."""
    user = await api_db.seed_user(email="req-viewer@example.com")
    ws = await api_db.seed_workspace(slug="req-viewer-ws", name="ViewerWs")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER)
    proj = await _project(api_db, ws.id)

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/requirements",
            json={"projectId": proj.id, "title": "x"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_post_requirement_writes_audit_and_ws_event(api_db: ApiDb) -> None:
    """Create writes a ``requirement.created`` audit row (WS publisher is no-op in tests)."""
    user = await api_db.seed_user(email="req-audit@example.com")
    ws = await api_db.member_workspace(user, slug="req-audit-ws")
    proj = await _project(api_db, ws.id)

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/requirements",
            json={"projectId": proj.id, "title": "audited"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 201
    async with api_db.maker() as session:
        rows = (await session.scalars(select(AuditLog).where(AuditLog.workspace_id == ws.id))).all()
    actions = {r.action for r in rows}
    assert "requirement.created" in actions


# ---------------------------------------------------------------------------
# PATCH /requirements/:id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_requirement_updates_title_description(api_db: ApiDb) -> None:
    """PATCH applies only the sent fields; ``public_id`` + project stay unchanged."""
    user = await api_db.seed_user(email="req-patch@example.com")
    ws = await api_db.member_workspace(user, slug="req-patch-ws")
    proj = await _project(api_db, ws.id)
    req = Requirement(project_id=proj.id, public_id="REQ-P1", title="orig")
    await api_db.add_all([req])

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/requirements/{req.id}",
            json={"title": "renamed", "description": "now described"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "renamed"
    assert body["description"] == "now described"
    assert body["public_id"] == "REQ-P1"


@pytest.mark.asyncio
async def test_patch_requirement_role_VIEWER_403(api_db: ApiDb) -> None:
    """VIEWER cannot patch."""
    user = await api_db.seed_user(email="req-viewer-patch@example.com")
    ws = await api_db.seed_workspace(slug="req-viewer-patch-ws", name="ViewerWs")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER)
    proj = await _project(api_db, ws.id)
    req = Requirement(project_id=proj.id, public_id="REQ-P2", title="x")
    await api_db.add_all([req])

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/requirements/{req.id}",
            json={"title": "x"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_patch_requirement_cross_workspace_returns_404(api_db: ApiDb) -> None:
    """A requirement in another workspace is invisible — PATCH returns 404."""
    user = await api_db.seed_user(email="req-xws-patch@example.com")
    ws = await api_db.member_workspace(user, slug="req-xws-patch-ws")
    other = await api_db.seed_workspace(slug="req-xws-patch-other", name="O")
    foreign_proj = await _project(api_db, other.id, slug="req-xws-patch-p")
    foreign_req = Requirement(project_id=foreign_proj.id, public_id="REQ-XWS", title="x")
    await api_db.add_all([foreign_req])

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/requirements/{foreign_req.id}",
            json={"title": "x"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /requirements/:id + restore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_requirement_soft_deletes_and_then_404(api_db: ApiDb) -> None:
    """DELETE → 204; subsequent GET → 404; re-DELETE → 404 (idempotent semantics)."""
    user = await api_db.seed_user(email="req-del@example.com")
    ws = await api_db.member_workspace(user, slug="req-del-ws")
    proj = await _project(api_db, ws.id)
    req = Requirement(project_id=proj.id, public_id="REQ-D1", title="delme")
    await api_db.add_all([req])

    async with api_db.client(user) as c:
        first = await c.delete(
            f"/api/v1/requirements/{req.id}",
            headers={"X-Workspace-Id": ws.id},
        )
        assert first.status_code == 204, first.text
        get_after = await c.get(f"/api/v1/requirements/{req.id}", headers={"X-Workspace-Id": ws.id})
        assert get_after.status_code == 404
        second = await c.delete(
            f"/api/v1/requirements/{req.id}",
            headers={"X-Workspace-Id": ws.id},
        )
        assert second.status_code == 404


@pytest.mark.asyncio
async def test_restore_requirement_clears_tombstone(api_db: ApiDb) -> None:
    """POST /restore re-activates a tombstoned row + makes it visible again."""
    user = await api_db.seed_user(email="req-rest@example.com")
    ws = await api_db.member_workspace(user, slug="req-rest-ws")
    proj = await _project(api_db, ws.id)
    req = Requirement(project_id=proj.id, public_id="REQ-R1", title="restoreme")
    await api_db.add_all([req])

    async with api_db.client(user) as c:
        d = await c.delete(
            f"/api/v1/requirements/{req.id}",
            headers={"X-Workspace-Id": ws.id},
        )
        assert d.status_code == 204
        r = await c.post(
            f"/api/v1/requirements/{req.id}/restore",
            headers={"X-Workspace-Id": ws.id},
        )
        assert r.status_code == 204
        # Visible again.
        g = await c.get(f"/api/v1/requirements/{req.id}", headers={"X-Workspace-Id": ws.id})
        assert g.status_code == 200


@pytest.mark.asyncio
async def test_list_excludes_soft_deleted(api_db: ApiDb) -> None:
    """``GET /requirements?projectId=...`` filters tombstoned rows by default."""
    user = await api_db.seed_user(email="req-list@example.com")
    ws = await api_db.member_workspace(user, slug="req-list-ws")
    proj = await _project(api_db, ws.id)
    alive = Requirement(project_id=proj.id, public_id="REQ-L1", title="alive")
    dead = Requirement(project_id=proj.id, public_id="REQ-L2", title="dead")
    await api_db.add_all([alive, dead])

    async with api_db.client(user) as c:
        # Soft-delete one row.
        await c.delete(f"/api/v1/requirements/{dead.id}", headers={"X-Workspace-Id": ws.id})
        resp = await c.get(
            f"/api/v1/requirements?projectId={proj.id}",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200
    items = resp.json()["items"]
    pubs = {it["public_id"] for it in items}
    assert "REQ-L1" in pubs
    assert "REQ-L2" not in pubs


# ---------------------------------------------------------------------------
# POST /requirements/:id/links (+ CROSS_WORKSPACE_LINK)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_link_same_workspace_creates_join_row(api_db: ApiDb) -> None:
    """Link to a same-workspace case → 201 + a ``RequirementLink`` row in the DB."""
    user = await api_db.seed_user(email="req-link@example.com")
    ws = await api_db.member_workspace(user, slug="req-link-ws")
    proj = await _project(api_db, ws.id)
    case = await _suite_and_case(api_db, proj, case_public_id="TC-LL1")
    req = Requirement(project_id=proj.id, public_id="REQ-LL1", title="needs cov")
    await api_db.add_all([req])

    async with api_db.client(user) as c:
        resp = await c.post(
            f"/api/v1/requirements/{req.id}/links",
            json={"testCaseId": case.id},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 201, resp.text

    async with api_db.maker() as session:
        rows = (
            await session.scalars(
                select(RequirementLink).where(RequirementLink.requirement_id == req.id)
            )
        ).all()
    assert len(rows) == 1
    assert rows[0].case_id == case.id


@pytest.mark.asyncio
async def test_post_link_cross_workspace_returns_400_CROSS_WORKSPACE_LINK(
    api_db: ApiDb,
) -> None:
    """Case lives in a different workspace → 400 with both workspace ids."""
    user = await api_db.seed_user(email="req-xlink@example.com")
    ws = await api_db.member_workspace(user, slug="req-xlink-ws")
    proj = await _project(api_db, ws.id)
    req = Requirement(project_id=proj.id, public_id="REQ-X1", title="local")
    await api_db.add_all([req])
    # Case lives in a foreign workspace.
    other = await api_db.seed_workspace(slug="req-xlink-other", name="O")
    foreign_proj = await _project(api_db, other.id, slug="req-xlink-foreign")
    foreign_case = await _suite_and_case(api_db, foreign_proj, case_public_id="TC-XL1")

    async with api_db.client(user) as c:
        resp = await c.post(
            f"/api/v1/requirements/{req.id}/links",
            json={"testCaseId": foreign_case.id},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 400, resp.text
    envelope = resp.json()["detail"]["error"]
    assert envelope["code"] == "CROSS_WORKSPACE_LINK"
    assert envelope["details"]["requirementWorkspaceId"] == ws.id
    assert envelope["details"]["caseWorkspaceId"] == other.id


@pytest.mark.asyncio
async def test_post_link_idempotent_re_post(api_db: ApiDb) -> None:
    """POST link twice → second is a no-op (same row, no IntegrityError)."""
    user = await api_db.seed_user(email="req-idemp@example.com")
    ws = await api_db.member_workspace(user, slug="req-idemp-ws")
    proj = await _project(api_db, ws.id)
    case = await _suite_and_case(api_db, proj, case_public_id="TC-ID1")
    req = Requirement(project_id=proj.id, public_id="REQ-ID1", title="x")
    await api_db.add_all([req])

    async with api_db.client(user) as c:
        first = await c.post(
            f"/api/v1/requirements/{req.id}/links",
            json={"testCaseId": case.id},
            headers={"X-Workspace-Id": ws.id},
        )
        assert first.status_code == 201
        second = await c.post(
            f"/api/v1/requirements/{req.id}/links",
            json={"testCaseId": case.id},
            headers={"X-Workspace-Id": ws.id},
        )
        assert second.status_code == 201
        assert first.json()["id"] == second.json()["id"]

    async with api_db.maker() as session:
        rows = (
            await session.scalars(
                select(RequirementLink).where(RequirementLink.requirement_id == req.id)
            )
        ).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_get_requirement_returns_linked_case_public_ids(api_db: ApiDb) -> None:
    """``GET /requirements/:id`` surfaces linked case public ids after a link write."""
    user = await api_db.seed_user(email="req-getlinks@example.com")
    ws = await api_db.member_workspace(user, slug="req-getlinks-ws")
    proj = await _project(api_db, ws.id)
    case = await _suite_and_case(api_db, proj, case_public_id="TC-GL1")
    req = Requirement(project_id=proj.id, public_id="REQ-GL1", title="x")
    await api_db.add_all([req])

    async with api_db.client(user) as c:
        link_resp = await c.post(
            f"/api/v1/requirements/{req.id}/links",
            json={"testCaseId": case.id},
            headers={"X-Workspace-Id": ws.id},
        )
        assert link_resp.status_code == 201
        get_resp = await c.get(
            f"/api/v1/requirements/{req.id}",
            headers={"X-Workspace-Id": ws.id},
        )
    assert get_resp.status_code == 200
    assert get_resp.json()["case_public_ids"] == ["TC-GL1"]


@pytest.mark.asyncio
async def test_delete_link_removes_join_row(api_db: ApiDb) -> None:
    """DELETE link → 204 + the join row is gone; re-DELETE → 404."""
    user = await api_db.seed_user(email="req-dlink@example.com")
    ws = await api_db.member_workspace(user, slug="req-dlink-ws")
    proj = await _project(api_db, ws.id)
    case = await _suite_and_case(api_db, proj, case_public_id="TC-DL1")
    req = Requirement(project_id=proj.id, public_id="REQ-DL1", title="x")
    await api_db.add_all([req])

    async with api_db.client(user) as c:
        await c.post(
            f"/api/v1/requirements/{req.id}/links",
            json={"testCaseId": case.id},
            headers={"X-Workspace-Id": ws.id},
        )
        first = await c.delete(
            f"/api/v1/requirements/{req.id}/links/{case.id}",
            headers={"X-Workspace-Id": ws.id},
        )
        assert first.status_code == 204
        second = await c.delete(
            f"/api/v1/requirements/{req.id}/links/{case.id}",
            headers={"X-Workspace-Id": ws.id},
        )
        assert second.status_code == 404


@pytest.mark.asyncio
async def test_link_writes_audit_rows(api_db: ApiDb) -> None:
    """Create + delete link each writes an explicit ``requirement.link_*`` audit row."""
    user = await api_db.seed_user(email="req-linkaudit@example.com")
    ws = await api_db.member_workspace(user, slug="req-linkaudit-ws")
    proj = await _project(api_db, ws.id)
    case = await _suite_and_case(api_db, proj, case_public_id="TC-LA1")
    req = Requirement(project_id=proj.id, public_id="REQ-LA1", title="x")
    await api_db.add_all([req])

    async with api_db.client(user) as c:
        await c.post(
            f"/api/v1/requirements/{req.id}/links",
            json={"testCaseId": case.id},
            headers={"X-Workspace-Id": ws.id},
        )
        await c.delete(
            f"/api/v1/requirements/{req.id}/links/{case.id}",
            headers={"X-Workspace-Id": ws.id},
        )
    async with api_db.maker() as session:
        rows = (await session.scalars(select(AuditLog).where(AuditLog.workspace_id == ws.id))).all()
    actions = {r.action for r in rows}
    assert "requirement.link_created" in actions
    assert "requirement.link_deleted" in actions
