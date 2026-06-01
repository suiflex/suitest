"""Tests for ``GET/PUT /api/v1/workspaces/:id/autonomy`` (M3-15 / M3-16)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select
from suitest_db.models.audit import AuditLog
from suitest_db.models.workspace_capability import WorkspaceCapability
from suitest_shared.domain.enums import AutonomyLevel, Role, Tier

if TYPE_CHECKING:
    from api_harness import ApiDb


async def _capability(api_db: ApiDb, ws_id: str, *, tier: Tier) -> None:
    await api_db.add_all(
        [
            WorkspaceCapability(
                workspace_id=ws_id,
                tier=tier,
                autonomy_level=AutonomyLevel.MANUAL,
                features_json={},
            )
        ]
    )


@pytest.mark.asyncio
async def test_get_defaults_manual(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="auto-get@example.com")
    ws = await api_db.member_workspace(user, slug="auto-get-ws")
    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/workspaces/{ws.id}/autonomy", headers={"X-Workspace-Id": ws.id}
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["level"] == "manual"
    assert "effective" in body and body["effective"]["defect_auto_file"] is False
    assert "auto_pr_fix" in body["knownOverrideKeys"]


@pytest.mark.asyncio
async def test_zero_tier_rejects_non_manual(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="auto-zero@example.com")
    ws = await api_db.member_workspace(user, slug="auto-zero-ws")
    await _capability(api_db, ws.id, tier=Tier.ZERO)
    async with api_db.client(user) as c:
        resp = await c.put(
            f"/api/v1/workspaces/{ws.id}/autonomy",
            headers={"X-Workspace-Id": ws.id},
            json={"level": "semi_auto", "overrides": {}},
        )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "AUTONOMY_REQUIRES_LLM"


@pytest.mark.asyncio
async def test_set_level_and_overrides_persists_and_audits(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="auto-set@example.com")
    ws = await api_db.member_workspace(user, slug="auto-set-ws")
    await _capability(api_db, ws.id, tier=Tier.CLOUD)
    async with api_db.client(user) as c:
        resp = await c.put(
            f"/api/v1/workspaces/{ws.id}/autonomy",
            headers={"X-Workspace-Id": ws.id},
            json={
                "level": "semi_auto",
                "overrides": {"defect_close_flaky": True},
                "reason": "CI pipeline",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["level"] == "semi_auto"
        assert body["overrides"]["defect_close_flaky"] is True
        # semi_auto default for defect_close_flaky is False; override flips it on.
        assert body["effective"]["defect_close_flaky"] is True
        assert body["effective"]["gen_finalize_p2p3"] is True  # semi_auto default

        # GET reflects the persisted state.
        get = await c.get(f"/api/v1/workspaces/{ws.id}/autonomy", headers={"X-Workspace-Id": ws.id})
        assert get.json()["level"] == "semi_auto"

    async with api_db.maker() as session:
        cap = await session.scalar(
            select(WorkspaceCapability).where(WorkspaceCapability.workspace_id == ws.id)
        )
        assert cap is not None
        assert cap.autonomy_level is AutonomyLevel.SEMI_AUTO
        assert cap.features_json["autonomy_overrides"] == {"defect_close_flaky": True}
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.workspace_id == ws.id, AuditLog.action == "autonomy.update"
            )
        )
        assert audit is not None


@pytest.mark.asyncio
async def test_unknown_override_key_rejected(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="auto-unknown@example.com")
    ws = await api_db.member_workspace(user, slug="auto-unknown-ws")
    await _capability(api_db, ws.id, tier=Tier.CLOUD)
    async with api_db.client(user) as c:
        resp = await c.put(
            f"/api/v1/workspaces/{ws.id}/autonomy",
            headers={"X-Workspace-Id": ws.id},
            json={"level": "assist", "overrides": {"bogus_key": True}},
        )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "UNKNOWN_OVERRIDE_KEY"


@pytest.mark.asyncio
async def test_viewer_cannot_set(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="auto-viewer@example.com")
    ws = await api_db.seed_workspace(slug="auto-viewer-ws", name="V")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER)
    await _capability(api_db, ws.id, tier=Tier.CLOUD)
    async with api_db.client(user) as c:
        resp = await c.put(
            f"/api/v1/workspaces/{ws.id}/autonomy",
            headers={"X-Workspace-Id": ws.id},
            json={"level": "auto", "overrides": {}},
        )
    assert resp.status_code == 403, resp.text
