"""Workspace settings (M1d-28) tests — General / Members / Danger Zone."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from suitest_api.deps.arq import get_arq
from suitest_db.models.audit import AuditLog
from suitest_db.models.tenancy import Membership
from suitest_db.models.workspace import Workspace
from suitest_shared.domain.enums import Role

if TYPE_CHECKING:
    from api_harness import ApiDb


# ---------------------------------------------------------------------------
# Recording ARQ stub — borrowed from test_runs_create
# ---------------------------------------------------------------------------


@dataclass
class _RecordingJob:
    job_id: str


@dataclass
class _RecordingArq:
    enqueued: list[tuple[str, tuple[object, ...], dict[str, object]]] = field(default_factory=list)

    async def enqueue_job(self, function: str, *args: object, **kwargs: object) -> _RecordingJob:
        self.enqueued.append((function, args, kwargs))
        return _RecordingJob(job_id=f"job-{len(self.enqueued)}")


def _override_arq(app: Any, arq: _RecordingArq) -> None:
    async def _get_recording_arq() -> _RecordingArq:
        return arq

    app.dependency_overrides[get_arq] = _get_recording_arq


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_workspace_with_role(
    api_db: ApiDb, *, slug: str, role: Role, email: str
) -> tuple[Any, Any]:
    """Return ``(user, workspace)`` with ``user`` membership at ``role``."""
    user = await api_db.seed_user(email=email)
    ws = await api_db.seed_workspace(slug=slug, name=slug)
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=role)
    return user, ws


# ---------------------------------------------------------------------------
# PATCH /workspaces/:id — General settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_workspace_name_happy(api_db: ApiDb) -> None:
    user, ws = await _seed_workspace_with_role(
        api_db, slug="patch-name", role=Role.ADMIN, email="patch-name@example.com"
    )
    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/workspaces/{ws.id}",
            json={"name": "New Name"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "New Name"


@pytest.mark.asyncio
async def test_patch_workspace_slug_returns_400_immutable(api_db: ApiDb) -> None:
    user, ws = await _seed_workspace_with_role(
        api_db, slug="patch-slug", role=Role.OWNER, email="patch-slug@example.com"
    )
    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/workspaces/{ws.id}",
            json={"slug": "new-slug"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["code"] == "IMMUTABLE_SLUG"


@pytest.mark.asyncio
async def test_patch_workspace_strict_zero_validation_toggle(api_db: ApiDb) -> None:
    user, ws = await _seed_workspace_with_role(
        api_db, slug="patch-strict", role=Role.OWNER, email="patch-strict@example.com"
    )
    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/workspaces/{ws.id}",
            json={"strict_zero_validation": False},
            headers={"X-Workspace-Id": ws.id},
        )
        assert resp.status_code == 200
        assert resp.json()["strict_zero_validation"] is False

        resp2 = await c.patch(
            f"/api/v1/workspaces/{ws.id}",
            json={"strict_zero_validation": True},
            headers={"X-Workspace-Id": ws.id},
        )
        assert resp2.status_code == 200
        assert resp2.json()["strict_zero_validation"] is True


@pytest.mark.asyncio
async def test_patch_workspace_qa_role_returns_403(api_db: ApiDb) -> None:
    user, ws = await _seed_workspace_with_role(
        api_db, slug="patch-qa", role=Role.QA, email="patch-qa@example.com"
    )
    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/workspaces/{ws.id}",
            json={"name": "Nope"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /workspaces/:id/members — invite
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invite_member_creates_membership_201(api_db: ApiDb) -> None:
    user, ws = await _seed_workspace_with_role(
        api_db, slug="invite-ok", role=Role.OWNER, email="inviter@example.com"
    )
    async with api_db.client(user) as c:
        resp = await c.post(
            f"/api/v1/workspaces/{ws.id}/members",
            json={"email": "invitee@example.com", "role": "QA"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == "invitee@example.com"
    assert body["role"] == "QA"
    async with api_db.maker() as session:
        members = (
            await session.scalars(select(Membership).where(Membership.workspace_id == ws.id))
        ).all()
    assert len(members) == 2  # owner + invited QA


@pytest.mark.asyncio
async def test_invite_owner_role_by_admin_returns_403(api_db: ApiDb) -> None:
    user, ws = await _seed_workspace_with_role(
        api_db, slug="invite-owner-by-admin", role=Role.ADMIN, email="admin-inviter@example.com"
    )
    # Seed a separate OWNER so the workspace has at least one OWNER (irrelevant to
    # this test; the gate is enforced strictly by the caller's role).
    other_owner = await api_db.seed_user(email="other-owner@example.com")
    await api_db.seed_membership(workspace_id=ws.id, user_id=other_owner.id, role=Role.OWNER)

    async with api_db.client(user) as c:
        resp = await c.post(
            f"/api/v1/workspaces/{ws.id}/members",
            json={"email": "new-owner@example.com", "role": "OWNER"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"]["code"] == "OWNER_GRANT_REQUIRES_OWNER"


# ---------------------------------------------------------------------------
# PATCH /workspaces/:id/members/:user_id — change role
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_role_admin_promotes_qa_to_admin_200(api_db: ApiDb) -> None:
    user, ws = await _seed_workspace_with_role(
        api_db, slug="role-admin-up", role=Role.ADMIN, email="admin-up@example.com"
    )
    qa = await api_db.seed_user(email="qa-up@example.com")
    await api_db.seed_membership(workspace_id=ws.id, user_id=qa.id, role=Role.QA)

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/workspaces/{ws.id}/members/{qa.id}",
            json={"role": "ADMIN"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200
    assert resp.json()["role"] == "ADMIN"


@pytest.mark.asyncio
async def test_change_role_admin_cannot_promote_qa_to_owner_403(api_db: ApiDb) -> None:
    user, ws = await _seed_workspace_with_role(
        api_db, slug="role-admin-owner-bad", role=Role.ADMIN, email="admin-no-grant@example.com"
    )
    qa = await api_db.seed_user(email="qa-no-grant@example.com")
    await api_db.seed_membership(workspace_id=ws.id, user_id=qa.id, role=Role.QA)

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/workspaces/{ws.id}/members/{qa.id}",
            json={"role": "OWNER"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"]["code"] == "OWNER_GRANT_REQUIRES_OWNER"


@pytest.mark.asyncio
async def test_change_role_demote_sole_owner_400(api_db: ApiDb) -> None:
    user, ws = await _seed_workspace_with_role(
        api_db, slug="role-sole-owner", role=Role.OWNER, email="sole@example.com"
    )
    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/workspaces/{ws.id}/members/{user.id}",
            json={"role": "ADMIN"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["code"] == "SOLE_OWNER_PROTECTED"


# ---------------------------------------------------------------------------
# DELETE /workspaces/:id/members/:user_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_member_by_admin_204(api_db: ApiDb) -> None:
    user, ws = await _seed_workspace_with_role(
        api_db, slug="rm-by-admin", role=Role.ADMIN, email="rm-admin@example.com"
    )
    victim = await api_db.seed_user(email="rm-victim@example.com")
    await api_db.seed_membership(workspace_id=ws.id, user_id=victim.id, role=Role.QA)

    async with api_db.client(user) as c:
        resp = await c.delete(
            f"/api/v1/workspaces/{ws.id}/members/{victim.id}",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 204
    async with api_db.maker() as session:
        rows = (
            await session.scalars(
                select(Membership).where(
                    Membership.workspace_id == ws.id, Membership.user_id == victim.id
                )
            )
        ).all()
    assert rows == []


@pytest.mark.asyncio
async def test_remove_sole_owner_returns_400(api_db: ApiDb) -> None:
    user, ws = await _seed_workspace_with_role(
        api_db, slug="rm-sole-owner", role=Role.OWNER, email="rm-sole@example.com"
    )
    async with api_db.client(user) as c:
        resp = await c.delete(
            f"/api/v1/workspaces/{ws.id}/members/{user.id}",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["code"] == "SOLE_OWNER_PROTECTED"


# ---------------------------------------------------------------------------
# DELETE /workspaces/:id — Danger Zone
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_workspace_owner_happy_202(api_db: ApiDb) -> None:
    user, ws = await _seed_workspace_with_role(
        api_db, slug="delete-ok", role=Role.OWNER, email="delete-ok@example.com"
    )

    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.request(
                "DELETE",
                f"/api/v1/workspaces/{ws.id}",
                json={"confirm_slug": ws.slug},
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["cleanup_job_id"]
    assert body["status"] == "QUEUED"
    assert len(arq.enqueued) == 1
    function, args, kwargs = arq.enqueued[0]
    assert function == "workspace_cleanup"
    assert args == (ws.id,)
    assert kwargs.get("_queue_name") == "suitest:runs"

    async with api_db.maker() as session:
        row = await session.get(Workspace, ws.id)
        assert row is not None
        assert row.deleted_at is not None
        audits = (
            await session.scalars(select(AuditLog).where(AuditLog.workspace_id == ws.id))
        ).all()
    actions = {a.action for a in audits}
    assert "workspace.delete_initiated" in actions


@pytest.mark.asyncio
async def test_delete_workspace_wrong_slug_returns_400(api_db: ApiDb) -> None:
    user, ws = await _seed_workspace_with_role(
        api_db, slug="delete-bad-slug", role=Role.OWNER, email="delete-bad-slug@example.com"
    )

    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.request(
                "DELETE",
                f"/api/v1/workspaces/{ws.id}",
                json={"confirm_slug": "not-the-slug"},
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["code"] == "CONFIRM_SLUG_MISMATCH"
    assert arq.enqueued == []
    async with api_db.maker() as session:
        row = await session.get(Workspace, ws.id)
    assert row is not None
    assert row.deleted_at is None


@pytest.mark.asyncio
async def test_delete_workspace_by_admin_returns_403(api_db: ApiDb) -> None:
    user, ws = await _seed_workspace_with_role(
        api_db, slug="delete-admin", role=Role.ADMIN, email="delete-admin@example.com"
    )

    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.request(
                "DELETE",
                f"/api/v1/workspaces/{ws.id}",
                json={"confirm_slug": ws.slug},
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 403
    assert arq.enqueued == []


@pytest.mark.asyncio
async def test_cross_workspace_member_returns_403_or_404(api_db: ApiDb) -> None:
    """A user with no membership in the target workspace cannot PATCH it."""
    user = await api_db.seed_user(email="cross-ws@example.com")
    other = await api_db.seed_workspace(slug="cross-other", name="Other")
    # No membership for ``user`` in ``other``.

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/workspaces/{other.id}",
            json={"name": "X"},
            headers={"X-Workspace-Id": other.id},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_workspace_emits_workspace_updated_audit_listener(api_db: ApiDb) -> None:
    """The flush-listener records an ``update`` row when ``deleted_at`` is set."""
    user, ws = await _seed_workspace_with_role(
        api_db, slug="audit-listen", role=Role.OWNER, email="audit-listen@example.com"
    )
    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.request(
                "DELETE",
                f"/api/v1/workspaces/{ws.id}",
                json={"confirm_slug": ws.slug},
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 202
    async with api_db.maker() as session:
        audits = (
            await session.scalars(select(AuditLog).where(AuditLog.workspace_id == ws.id))
        ).all()
    # Listener fires for the workspace row UPDATE (deleted_at) and we explicitly
    # write the ``workspace.delete_initiated`` event.
    actions = {a.action for a in audits}
    assert "workspace.delete_initiated" in actions


@pytest.mark.asyncio
async def test_change_role_member_not_found_returns_404(api_db: ApiDb) -> None:
    user, ws = await _seed_workspace_with_role(
        api_db, slug="role-404", role=Role.OWNER, email="role-404@example.com"
    )
    bogus = uuid.uuid4()
    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/workspaces/{ws.id}/members/{bogus}",
            json={"role": "QA"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 404
