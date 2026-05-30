"""Tests for ``GET /api/v1/audit-logs`` (M1d-27).

Covers the cursor-paginated, ADMIN-gated workspace audit log endpoint
(docs/API.md §146-158). The matrix mirrors plan-05b § M1d-27 tests:

* empty workspace → empty page, no cursor
* multi-page cursor pagination — exact 25 rows / page size 10
* action glob ``integration.*`` filter
* ``resource_type`` exact filter
* ``user_id`` exact filter
* ``from`` / ``to`` date range
* cross-workspace isolation (admin in WS-A cannot see WS-B rows)
* QA membership → 403
* ``limit`` > 200 → 400 INVALID_LIMIT
* malformed cursor → 400 INVALID_CURSOR
* composite cursor stability under mid-pagination inserts
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from suitest_db.models.audit import AuditLog
from suitest_shared.domain.enums import Role

if TYPE_CHECKING:
    from api_harness import ApiDb
    from suitest_db.models.user import User
    from suitest_db.models.workspace import Workspace


# ---- helpers -----------------------------------------------------------------


async def _admin_workspace(api_db: ApiDb, user: User, *, slug: str) -> Workspace:
    """Seed a workspace with the user as ADMIN (the audit-list role gate)."""
    ws = await api_db.seed_workspace(slug=slug, name=slug)
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.ADMIN)
    return ws


def _audit_rows(
    ws_id: str,
    *,
    count: int,
    base_ts: datetime,
    action: str = "case.updated",
    resource_type: str = "test_case",
    user_id: uuid.UUID | None = None,
) -> list[AuditLog]:
    """Build N audit rows whose ``created_at`` strictly decreases by 1 second.

    The cursor pagination assumes strict ordering on ``(created_at, id)`` so
    fixing distinct timestamps keeps the tests deterministic across DB clocks.
    """
    return [
        AuditLog(
            workspace_id=ws_id,
            action=action,
            resource_type=resource_type,
            resource_id=f"res_{i:03d}",
            user_id=user_id,
            created_at=base_ts + timedelta(seconds=i),
        )
        for i in range(count)
    ]


# ---- tests -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_audit_logs_empty_workspace_returns_no_items_or_cursor(
    api_db: ApiDb,
) -> None:
    user = await api_db.seed_user(email="audit-empty@example.com")
    ws = await _admin_workspace(api_db, user, slug="audit-empty-ws")
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/audit-logs", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"items": [], "next_cursor": None}


@pytest.mark.asyncio
async def test_get_audit_logs_cursor_pagination_3_pages(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="audit-pag@example.com")
    ws = await _admin_workspace(api_db, user, slug="audit-pag-ws")
    base = datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC)
    await api_db.add_all(_audit_rows(ws.id, count=25, base_ts=base))

    async with api_db.client(user) as c:
        first = await c.get("/api/v1/audit-logs?limit=10", headers={"X-Workspace-Id": ws.id})
        assert first.status_code == 200
        first_body = first.json()
        assert len(first_body["items"]) == 10
        assert first_body["next_cursor"] is not None
        # Newest-first ordering: ``res_024`` first, ``res_015`` last on page 1.
        assert first_body["items"][0]["resourceId"] == "res_024"
        assert first_body["items"][-1]["resourceId"] == "res_015"

        second = await c.get(
            f"/api/v1/audit-logs?limit=10&cursor={first_body['next_cursor']}",
            headers={"X-Workspace-Id": ws.id},
        )
        assert second.status_code == 200
        second_body = second.json()
        assert len(second_body["items"]) == 10
        assert second_body["next_cursor"] is not None
        assert second_body["items"][0]["resourceId"] == "res_014"
        assert second_body["items"][-1]["resourceId"] == "res_005"

        third = await c.get(
            f"/api/v1/audit-logs?limit=10&cursor={second_body['next_cursor']}",
            headers={"X-Workspace-Id": ws.id},
        )
        assert third.status_code == 200
        third_body = third.json()
        assert len(third_body["items"]) == 5
        assert third_body["next_cursor"] is None
        assert third_body["items"][0]["resourceId"] == "res_004"
        assert third_body["items"][-1]["resourceId"] == "res_000"

    # End-to-end: every row surfaced exactly once across the 3 pages.
    all_ids = (
        [r["resourceId"] for r in first_body["items"]]
        + [r["resourceId"] for r in second_body["items"]]
        + [r["resourceId"] for r in third_body["items"]]
    )
    assert len(all_ids) == 25
    assert len(set(all_ids)) == 25


@pytest.mark.asyncio
async def test_get_audit_logs_action_glob_integration_star(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="audit-glob@example.com")
    ws = await _admin_workspace(api_db, user, slug="audit-glob-ws")
    await api_db.add_all(
        [
            AuditLog(
                workspace_id=ws.id,
                action="integration.created",
                resource_type="integration",
                resource_id="int_1",
            ),
            AuditLog(
                workspace_id=ws.id,
                action="integration.updated",
                resource_type="integration",
                resource_id="int_1",
            ),
            AuditLog(
                workspace_id=ws.id,
                action="defect.created",
                resource_type="defect",
                resource_id="def_1",
            ),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get(
            "/api/v1/audit-logs?action=integration.*",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200
    actions = {r["action"] for r in resp.json()["items"]}
    assert actions == {"integration.created", "integration.updated"}


@pytest.mark.asyncio
async def test_get_audit_logs_resource_type_exact_filter(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="audit-rt@example.com")
    ws = await _admin_workspace(api_db, user, slug="audit-rt-ws")
    await api_db.add_all(
        [
            AuditLog(
                workspace_id=ws.id,
                action="case.updated",
                resource_type="test_case",
                resource_id="tc_1",
            ),
            AuditLog(
                workspace_id=ws.id,
                action="defect.updated",
                resource_type="defect",
                resource_id="def_1",
            ),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get(
            "/api/v1/audit-logs?resource_type=defect",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200
    rows = resp.json()["items"]
    assert [r["resourceType"] for r in rows] == ["defect"]


@pytest.mark.asyncio
async def test_get_audit_logs_user_id_exact_filter(api_db: ApiDb) -> None:
    actor = await api_db.seed_user(email="audit-uid-actor@example.com")
    other = await api_db.seed_user(email="audit-uid-other@example.com")
    ws = await _admin_workspace(api_db, actor, slug="audit-uid-ws")
    await api_db.add_all(
        [
            AuditLog(
                workspace_id=ws.id,
                action="case.updated",
                resource_type="test_case",
                resource_id="tc_self",
                user_id=actor.id,
            ),
            AuditLog(
                workspace_id=ws.id,
                action="case.updated",
                resource_type="test_case",
                resource_id="tc_other",
                user_id=other.id,
            ),
            AuditLog(
                workspace_id=ws.id,
                action="case.updated",
                resource_type="test_case",
                resource_id="tc_system",
                user_id=None,
            ),
        ]
    )
    async with api_db.client(actor) as c:
        resp = await c.get(
            f"/api/v1/audit-logs?user_id={actor.id}",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200
    rows = resp.json()["items"]
    assert [r["resourceId"] for r in rows] == ["tc_self"]
    assert rows[0]["userId"] == str(actor.id)
    assert rows[0]["userEmail"] == "audit-uid-actor@example.com"


@pytest.mark.asyncio
async def test_get_audit_logs_from_to_date_range(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="audit-date@example.com")
    ws = await _admin_workspace(api_db, user, slug="audit-date-ws")
    base = datetime(2026, 5, 30, 0, 0, 0, tzinfo=UTC)
    await api_db.add_all(
        [
            AuditLog(
                workspace_id=ws.id,
                action="case.updated",
                resource_type="test_case",
                resource_id=f"tc_{i}",
                created_at=base + timedelta(days=i),
            )
            for i in range(5)
        ]
    )
    # Window covers days 1, 2, 3 — inclusive on both bounds. Pass datetimes
    # via ``httpx`` params kwarg so ``+00:00`` survives URL-encoding (raw ``+``
    # in a query string is interpreted as space).
    async with api_db.client(user) as c:
        resp = await c.get(
            "/api/v1/audit-logs",
            params={
                "from": (base + timedelta(days=1)).isoformat(),
                "to": (base + timedelta(days=3)).isoformat(),
            },
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200
    ids = sorted(r["resourceId"] for r in resp.json()["items"])
    assert ids == ["tc_1", "tc_2", "tc_3"]


@pytest.mark.asyncio
async def test_get_audit_logs_cross_workspace_isolation(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="audit-iso@example.com")
    ws_a = await _admin_workspace(api_db, user, slug="audit-iso-a")
    ws_b = await api_db.seed_workspace(slug="audit-iso-b", name="WS B")
    await api_db.add_all(
        [
            AuditLog(
                workspace_id=ws_a.id,
                action="case.updated",
                resource_type="test_case",
                resource_id="tc_a",
            ),
            AuditLog(
                workspace_id=ws_b.id,
                action="case.updated",
                resource_type="test_case",
                resource_id="tc_b",
            ),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/audit-logs", headers={"X-Workspace-Id": ws_a.id})
    assert resp.status_code == 200
    rows = resp.json()["items"]
    assert [r["resourceId"] for r in rows] == ["tc_a"]


@pytest.mark.asyncio
async def test_get_audit_logs_qa_role_returns_403(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="audit-qa@example.com")
    # ``member_workspace`` default seeds QA.
    ws = await api_db.member_workspace(user, slug="audit-qa-ws")
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/audit-logs", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_audit_logs_viewer_role_returns_403(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="audit-viewer@example.com")
    ws = await api_db.seed_workspace(slug="audit-viewer-ws", name="audit-viewer-ws")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER)
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/audit-logs", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_audit_logs_owner_role_allowed(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="audit-owner@example.com")
    ws = await api_db.seed_workspace(slug="audit-owner-ws", name="audit-owner-ws")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.OWNER)
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/audit-logs", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_audit_logs_limit_above_max_returns_400(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="audit-lim@example.com")
    ws = await _admin_workspace(api_db, user, slug="audit-lim-ws")
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/audit-logs?limit=500", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 400
    assert "limit" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_audit_logs_malformed_cursor_returns_400(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="audit-cur@example.com")
    ws = await _admin_workspace(api_db, user, slug="audit-cur-ws")
    async with api_db.client(user) as c:
        resp = await c.get(
            "/api/v1/audit-logs?cursor=not-a-valid-base64-json",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_audit_logs_cross_workspace_cursor_returns_empty_page(
    api_db: ApiDb,
) -> None:
    """A cursor that decodes cleanly but came from another workspace is safe.

    The repo query is scoped to the caller's workspace so even if the cursor's
    ``(created_at, id)`` keyset is valid, no foreign rows leak — the response
    is an empty page with ``next_cursor=None``.
    """
    user = await api_db.seed_user(email="audit-curiso@example.com")
    ws = await _admin_workspace(api_db, user, slug="audit-curiso-ws")
    # Fabricate a cursor whose timestamp is in the past — repo will simply
    # produce zero rows for the empty workspace.
    cursor_payload = b'{"ts":"2026-05-30T00:00:00+00:00","id":"forged_from_other_ws"}'
    cursor = base64.urlsafe_b64encode(cursor_payload).decode()
    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/audit-logs?cursor={cursor}", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "next_cursor": None}


@pytest.mark.asyncio
async def test_get_audit_logs_cursor_stable_under_mid_pagination_inserts(
    api_db: ApiDb,
) -> None:
    """Inserting new rows after page 1 must not duplicate or skip page 2 rows.

    Keyset cursor encodes ``(created_at, id)``; new rows have a later
    ``created_at`` so they appear on a hypothetical "page 0", not on page 2.
    """
    user = await api_db.seed_user(email="audit-stable@example.com")
    ws = await _admin_workspace(api_db, user, slug="audit-stable-ws")
    # Seed in the far past so the server-defaulted ``NOW()`` of the late
    # arrival is unambiguously *after* every seeded row's ``created_at``.
    base = datetime(2020, 1, 1, 0, 0, 0, tzinfo=UTC)
    await api_db.add_all(_audit_rows(ws.id, count=15, base_ts=base))

    async with api_db.client(user) as c:
        first = await c.get("/api/v1/audit-logs?limit=10", headers={"X-Workspace-Id": ws.id})
        assert first.status_code == 200
        page1_ids = [r["resourceId"] for r in first.json()["items"]]
        cursor = first.json()["next_cursor"]
        assert cursor is not None

        # Mid-pagination insert: a fresh row written with NOW() (after base+15s).
        # Tests the strict ``(created_at, id) < cursor`` predicate.
        await api_db.add_all(
            [
                AuditLog(
                    workspace_id=ws.id,
                    action="case.updated",
                    resource_type="test_case",
                    resource_id="late_arrival",
                )
            ]
        )

        second = await c.get(
            f"/api/v1/audit-logs?limit=10&cursor={cursor}",
            headers={"X-Workspace-Id": ws.id},
        )
        assert second.status_code == 200
        page2_ids = [r["resourceId"] for r in second.json()["items"]]

    # Page 2 returns the original tail (5 rows) and does NOT include the late
    # arrival, since the cursor pins it to rows older than page-1's last entry.
    assert "late_arrival" not in page1_ids
    assert "late_arrival" not in page2_ids
    assert set(page1_ids).isdisjoint(set(page2_ids))
    assert len(page2_ids) == 5


@pytest.mark.asyncio
async def test_get_audit_logs_invalid_user_id_returns_400(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="audit-uidbad@example.com")
    ws = await _admin_workspace(api_db, user, slug="audit-uidbad-ws")
    async with api_db.client(user) as c:
        resp = await c.get(
            "/api/v1/audit-logs?user_id=not-a-uuid",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_audit_logs_membership_required_returns_403(api_db: ApiDb) -> None:
    """Without a membership row, ``require_workspace_membership`` 403s the call."""
    user = await api_db.seed_user(email="audit-nomember@example.com")
    other = await api_db.seed_workspace(slug="audit-nomember-other", name="Other")
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/audit-logs", headers={"X-Workspace-Id": other.id})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_audit_logs_action_glob_question_mark_single_char(
    api_db: ApiDb,
) -> None:
    """``?`` glob maps to single-char SQL ``_`` — matches one char exactly."""
    user = await api_db.seed_user(email="audit-q@example.com")
    ws = await _admin_workspace(api_db, user, slug="audit-q-ws")
    await api_db.add_all(
        [
            AuditLog(
                workspace_id=ws.id,
                action="case.a",
                resource_type="test_case",
                resource_id="r1",
            ),
            AuditLog(
                workspace_id=ws.id,
                action="case.bb",
                resource_type="test_case",
                resource_id="r2",
            ),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/audit-logs?action=case.?", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    actions = {r["action"] for r in resp.json()["items"]}
    assert actions == {"case.a"}
