"""Tests for ``GET /api/v1/audit-logs`` (CRITICAL C4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_db.models.audit import AuditLog

if TYPE_CHECKING:
    from api_harness import ApiDb


@pytest.mark.asyncio
async def test_audit_logs_filter_by_action_prefix(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="audit-list@example.com")
    ws = await api_db.member_workspace(user, slug="audit-list-ws")
    await api_db.add_all(
        [
            AuditLog(
                workspace_id=ws.id,
                action="agent.generate",
                resource_type="test_case",
                resource_id="tc_1",
            ),
            AuditLog(
                workspace_id=ws.id,
                action="agent.diagnose",
                resource_type="run",
                resource_id="run_1",
            ),
            AuditLog(
                workspace_id=ws.id,
                action="case.create",
                resource_type="test_case",
                resource_id="tc_2",
            ),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get(
            "/api/v1/audit-logs?action=agent.*&limit=5",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200
    body = resp.json()
    actions = {row["action"] for row in body["items"]}
    assert actions == {"agent.generate", "agent.diagnose"}


@pytest.mark.asyncio
async def test_audit_logs_unfiltered_returns_all_for_workspace(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="audit-all@example.com")
    ws = await api_db.member_workspace(user, slug="audit-all-ws")
    other = await api_db.seed_workspace(slug="audit-all-other", name="Other")
    await api_db.add_all(
        [
            AuditLog(
                workspace_id=ws.id,
                action="case.update",
                resource_type="test_case",
                resource_id="tc_1",
            ),
            AuditLog(
                workspace_id=other.id,
                action="case.update",
                resource_type="test_case",
                resource_id="tc_2",
            ),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/audit-logs", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["resourceId"] == "tc_1"


@pytest.mark.asyncio
async def test_audit_logs_limit_clamped(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="audit-limit@example.com")
    ws = await api_db.member_workspace(user, slug="audit-limit-ws")
    await api_db.add_all(
        [
            AuditLog(
                workspace_id=ws.id,
                action="case.update",
                resource_type="test_case",
                resource_id=f"tc_{i}",
            )
            for i in range(10)
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get(
            "/api/v1/audit-logs?limit=3",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 3
