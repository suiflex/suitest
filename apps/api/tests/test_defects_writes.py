"""M1d-9 — defect write endpoint tests (docs/API.md §3.6).

Covers ``POST /defects`` (manual file with ``SUIT-N`` public id),
``PATCH /defects/:id`` (status transition matrix + assignee + severity), and
``POST /defects/:id/sync-external`` (501 ``ADAPTER_NOT_REGISTERED`` placeholder
until the adapter registry lands in M1d-11+).

The status transition matrix enforced by ``DefectService._validate_status_transition``:

* ``OPEN``        → ``IN_PROGRESS``, ``WONT_FIX``, ``CLOSED``
* ``IN_PROGRESS`` → ``RESOLVED``, ``OPEN``, ``WONT_FIX``
* ``RESOLVED``    → ``CLOSED``, ``OPEN``
* ``CLOSED``      → ∅ (terminal)
* ``WONT_FIX``    → ``OPEN``

Backwards edges outside this set require ``"force": true`` on the PATCH body
(role-gated to QA+ upstream). ``resolved_at`` flips ``UTCNOW`` on entry into
``RESOLVED`` and clears on transition out of ``RESOLVED`` to anything except
``CLOSED``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import select
from suitest_db.models.audit import AuditLog
from suitest_db.models.case import TestCase
from suitest_db.models.defect import Defect
from suitest_db.models.project import Project, Suite
from suitest_db.models.run import Run
from suitest_shared.domain.enums import (
    CaseSource,
    DefectStatus,
    DiagnosisKind,
    Role,
    RunStatus,
    RunTrigger,
    Severity,
    Tier,
)

if TYPE_CHECKING:
    from api_harness import ApiDb


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


async def _project_suite(api_db: ApiDb, ws_id: str, *, slug: str = "def-proj") -> Suite:
    project = Project(workspace_id=ws_id, slug=slug, name="P")
    await api_db.add_all([project])
    suite = Suite(project_id=project.id, name="S", order=0)
    await api_db.add_all([suite])
    return suite


async def _seed_case(api_db: ApiDb, suite_id: str, *, public_id: str = "TC-D1") -> TestCase:
    case = TestCase(suite_id=suite_id, public_id=public_id, name="case", source=CaseSource.MANUAL)
    await api_db.add_all([case])
    return case


async def _seed_run(api_db: ApiDb, project_id: str, *, public_id: str = "R-D1") -> Run:
    run = Run(
        project_id=project_id,
        public_id=public_id,
        name="seed-run",
        status=RunStatus.PASS,
        trigger=RunTrigger.MANUAL,
        tier_at_runtime=Tier.ZERO,
    )
    await api_db.add_all([run])
    return run


async def _seed_defect(
    api_db: ApiDb,
    ws_id: str,
    *,
    public_id: str,
    status: DefectStatus = DefectStatus.OPEN,
    severity: Severity = Severity.HIGH,
    created_by: str = "user:seed",
    test_case_id: str | None = None,
    run_id: str | None = None,
) -> Defect:
    defect = Defect(
        public_id=public_id,
        workspace_id=ws_id,
        title="seeded bug",
        severity=severity,
        status=status,
        created_by=created_by,
        test_case_id=test_case_id,
        run_id=run_id,
        agent_diagnosis_kind=DiagnosisKind.MANUAL_TRIAGE,
    )
    await api_db.add_all([defect])
    return defect


def _create_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": "Login button unresponsive",
        "description": "click does nothing on Safari 17",
        "severity": "HIGH",
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# POST /defects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_defect_returns_201_with_SUIT_public_id_and_created_by_user(
    api_db: ApiDb,
) -> None:
    """Happy path — 201, ``SUIT-<n>`` public id, ``created_by='user:<uuid>'``."""
    user = await api_db.seed_user(email="def-post@example.com")
    ws = await api_db.member_workspace(user, slug="def-post-ws")

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/defects",
            json=_create_body(),
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["public_id"].startswith("SUIT-")
    assert body["title"] == "Login button unresponsive"
    assert body["severity"] == "HIGH"
    assert body["status"] == "OPEN"
    assert body["created_by"] == f"user:{user.id}"
    assert body["agent_diagnosis_kind"] == "MANUAL_TRIAGE"
    assert body["resolved_at"] is None


@pytest.mark.asyncio
async def test_post_defect_without_title_returns_422(api_db: ApiDb) -> None:
    """Missing ``title`` → Pydantic 422 (required field)."""
    user = await api_db.seed_user(email="def-422@example.com")
    ws = await api_db.member_workspace(user, slug="def-422-ws")

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/defects",
            json={"severity": "HIGH"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_post_defect_with_run_and_case_links_FKs(api_db: ApiDb) -> None:
    """``runId`` + ``testCaseId`` resolve to public ids in the detail response."""
    user = await api_db.seed_user(email="def-links@example.com")
    ws = await api_db.member_workspace(user, slug="def-links-ws")
    suite = await _project_suite(api_db, ws.id, slug="def-links-proj")
    case = await _seed_case(api_db, suite.id, public_id="TC-LINK")
    run = await _seed_run(api_db, suite.project_id, public_id="R-LINK")

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/defects",
            json=_create_body(testCaseId=case.id, runId=run.id),
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["test_case_public_id"] == "TC-LINK"
    assert body["run_public_id"] == "R-LINK"


@pytest.mark.asyncio
async def test_post_defect_writes_audit_row_action_defect_created(api_db: ApiDb) -> None:
    """``defect.created`` audit row appended in the same transaction."""
    user = await api_db.seed_user(email="def-audit@example.com")
    ws = await api_db.member_workspace(user, slug="def-audit-ws")

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/defects",
            json=_create_body(),
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 201
    defect_id = resp.json()["id"]
    async with api_db.maker() as session:
        rows = list(
            (
                await session.scalars(
                    select(AuditLog).where(
                        AuditLog.resource_id == defect_id,
                        AuditLog.action == "defect.created",
                    )
                )
            ).all()
        )
    assert len(rows) == 1
    metadata = rows[0].metadata_json or {}
    assert metadata.get("manual") is True
    assert metadata.get("severity") == "HIGH"


@pytest.mark.asyncio
async def test_post_defect_role_VIEWER_returns_403(api_db: ApiDb) -> None:
    """VIEWER cannot file defects per the role table."""
    user = await api_db.seed_user(email="def-viewer@example.com")
    ws = await api_db.seed_workspace(slug="def-viewer-ws", name="ViewerWs")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER)

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/defects",
            json=_create_body(),
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_post_defect_cross_workspace_test_case_returns_404(api_db: ApiDb) -> None:
    """``testCaseId`` from another workspace → 404 LINKED_RESOURCE_NOT_FOUND (no leak)."""
    user = await api_db.seed_user(email="def-x@example.com")
    ws = await api_db.member_workspace(user, slug="def-x-ws")
    other = await api_db.seed_workspace(slug="def-x-other", name="Other")
    suite = await _project_suite(api_db, other.id, slug="def-x-other-proj")
    case = await _seed_case(api_db, suite.id, public_id="TC-XW")

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/defects",
            json=_create_body(testCaseId=case.id),
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 404
    envelope = resp.json()["detail"]["error"]
    assert envelope["code"] == "LINKED_RESOURCE_NOT_FOUND"


# ---------------------------------------------------------------------------
# PATCH /defects/:id  -- status transitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_defect_status_open_to_in_progress_returns_200(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="def-flow1@example.com")
    ws = await api_db.member_workspace(user, slug="def-flow1-ws")
    defect = await _seed_defect(api_db, ws.id, public_id="SUIT-F1")

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/defects/{defect.id}",
            json={"status": "IN_PROGRESS"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "IN_PROGRESS"


@pytest.mark.asyncio
async def test_patch_defect_status_in_progress_to_resolved_sets_resolved_at(
    api_db: ApiDb,
) -> None:
    """Entering RESOLVED stamps ``resolved_at`` to UTCNOW."""
    user = await api_db.seed_user(email="def-resolve@example.com")
    ws = await api_db.member_workspace(user, slug="def-resolve-ws")
    defect = await _seed_defect(
        api_db, ws.id, public_id="SUIT-RES", status=DefectStatus.IN_PROGRESS
    )

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/defects/{defect.id}",
            json={"status": "RESOLVED"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "RESOLVED"
    assert body["resolved_at"] is not None


@pytest.mark.asyncio
async def test_patch_defect_status_in_progress_to_closed_returns_400_invalid_transition(
    api_db: ApiDb,
) -> None:
    """IN_PROGRESS → CLOSED skips RESOLVED → 400 ``INVALID_STATUS_TRANSITION``."""
    user = await api_db.seed_user(email="def-skip@example.com")
    ws = await api_db.member_workspace(user, slug="def-skip-ws")
    defect = await _seed_defect(
        api_db, ws.id, public_id="SUIT-SKIP", status=DefectStatus.IN_PROGRESS
    )

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/defects/{defect.id}",
            json={"status": "CLOSED"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 400, resp.text
    envelope = resp.json()["detail"]["error"]
    assert envelope["code"] == "INVALID_STATUS_TRANSITION"
    assert envelope["details"]["from"] == "IN_PROGRESS"
    assert envelope["details"]["to"] == "CLOSED"


@pytest.mark.asyncio
async def test_patch_defect_backwards_without_force_returns_400(api_db: ApiDb) -> None:
    """``CLOSED`` is terminal; ``CLOSED → OPEN`` without force → 400."""
    user = await api_db.seed_user(email="def-back@example.com")
    ws = await api_db.member_workspace(user, slug="def-back-ws")
    defect = await _seed_defect(api_db, ws.id, public_id="SUIT-BACK", status=DefectStatus.CLOSED)

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/defects/{defect.id}",
            json={"status": "OPEN"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 400
    envelope = resp.json()["detail"]["error"]
    assert envelope["code"] == "INVALID_STATUS_TRANSITION"


@pytest.mark.asyncio
async def test_patch_defect_backwards_with_force_true_returns_200(api_db: ApiDb) -> None:
    """QA + ``force=true`` lets the reopen edge through (CLOSED → OPEN)."""
    user = await api_db.seed_user(email="def-force@example.com")
    ws = await api_db.member_workspace(user, slug="def-force-ws")
    defect = await _seed_defect(api_db, ws.id, public_id="SUIT-FORCE", status=DefectStatus.CLOSED)

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/defects/{defect.id}",
            json={"status": "OPEN", "force": True},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "OPEN"


@pytest.mark.asyncio
async def test_patch_defect_resolved_to_open_clears_resolved_at(api_db: ApiDb) -> None:
    """RESOLVED → OPEN (allowed reopen) clears ``resolved_at``."""
    user = await api_db.seed_user(email="def-reopen@example.com")
    ws = await api_db.member_workspace(user, slug="def-reopen-ws")
    defect = await _seed_defect(
        api_db, ws.id, public_id="SUIT-REOPEN", status=DefectStatus.RESOLVED
    )
    # stamp resolved_at by hand to mirror the real lifecycle entry.
    from datetime import UTC, datetime

    async with api_db.maker() as session:
        from sqlalchemy import update

        await session.execute(
            update(Defect).where(Defect.id == defect.id).values(resolved_at=datetime.now(UTC))
        )
        await session.commit()

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/defects/{defect.id}",
            json={"status": "OPEN"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "OPEN"
    assert body["resolved_at"] is None


@pytest.mark.asyncio
async def test_patch_defect_resolved_to_closed_keeps_resolved_at(api_db: ApiDb) -> None:
    """RESOLVED → CLOSED is a forward edge — ``resolved_at`` stays stamped."""
    user = await api_db.seed_user(email="def-close@example.com")
    ws = await api_db.member_workspace(user, slug="def-close-ws")
    defect = await _seed_defect(api_db, ws.id, public_id="SUIT-CLOSE", status=DefectStatus.RESOLVED)
    from datetime import UTC, datetime

    async with api_db.maker() as session:
        from sqlalchemy import update

        await session.execute(
            update(Defect).where(Defect.id == defect.id).values(resolved_at=datetime.now(UTC))
        )
        await session.commit()

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/defects/{defect.id}",
            json={"status": "CLOSED"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "CLOSED"
    assert body["resolved_at"] is not None


@pytest.mark.asyncio
async def test_patch_defect_severity_and_assignee(api_db: ApiDb) -> None:
    """Severity + assignee can be patched without touching status."""
    user = await api_db.seed_user(email="def-meta@example.com")
    ws = await api_db.member_workspace(user, slug="def-meta-ws")
    assignee = await api_db.seed_user(email="def-meta-assignee@example.com")
    defect = await _seed_defect(api_db, ws.id, public_id="SUIT-META")

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/defects/{defect.id}",
            json={"severity": "CRITICAL", "assigneeId": str(assignee.id)},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["severity"] == "CRITICAL"
    assert body["assignee_id"] == str(assignee.id)


@pytest.mark.asyncio
async def test_patch_defect_writes_audit_with_status_from_to(api_db: ApiDb) -> None:
    """Status edits write an audit row carrying ``statusFrom`` / ``statusTo``."""
    user = await api_db.seed_user(email="def-aud-st@example.com")
    ws = await api_db.member_workspace(user, slug="def-aud-st-ws")
    defect = await _seed_defect(api_db, ws.id, public_id="SUIT-AUD")

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/defects/{defect.id}",
            json={"status": "IN_PROGRESS"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200
    async with api_db.maker() as session:
        rows = list(
            (
                await session.scalars(
                    select(AuditLog).where(
                        AuditLog.resource_id == defect.id,
                        AuditLog.action == "defect.updated",
                    )
                )
            ).all()
        )
    assert len(rows) == 1
    md = rows[0].metadata_json or {}
    assert md.get("statusFrom") == "OPEN"
    assert md.get("statusTo") == "IN_PROGRESS"


@pytest.mark.asyncio
async def test_patch_defect_cross_workspace_returns_404(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="def-px@example.com")
    ws = await api_db.member_workspace(user, slug="def-px-ws")
    other = await api_db.seed_workspace(slug="def-px-other", name="Other")
    defect = await _seed_defect(api_db, other.id, public_id="SUIT-PX")

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/defects/{defect.id}",
            json={"status": "IN_PROGRESS"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_defect_role_VIEWER_returns_403(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="def-pv@example.com")
    ws = await api_db.seed_workspace(slug="def-pv-ws", name="ViewerWs")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER)
    defect = await _seed_defect(api_db, ws.id, public_id="SUIT-PV")

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/defects/{defect.id}",
            json={"status": "IN_PROGRESS"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /defects/:id/sync-external
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_sync_external_returns_501_adapter_not_registered(
    api_db: ApiDb,
) -> None:
    """No adapter registry yet → 501 ``ADAPTER_NOT_REGISTERED`` per M1d-9 contract."""
    user = await api_db.seed_user(email="def-sync@example.com")
    ws = await api_db.member_workspace(user, slug="def-sync-ws")
    defect = await _seed_defect(api_db, ws.id, public_id="SUIT-SYNC")

    async with api_db.client(user) as c:
        resp = await c.post(
            f"/api/v1/defects/{defect.id}/sync-external",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 501, resp.text
    envelope = resp.json()["detail"]["error"]
    assert envelope["code"] == "ADAPTER_NOT_REGISTERED"
    assert envelope["details"]["defectId"] == defect.id


@pytest.mark.asyncio
async def test_post_sync_external_cross_workspace_returns_404(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="def-syx@example.com")
    ws = await api_db.member_workspace(user, slug="def-syx-ws")
    other = await api_db.seed_workspace(slug="def-syx-other", name="Other")
    defect = await _seed_defect(api_db, other.id, public_id="SUIT-SYX")

    async with api_db.client(user) as c:
        resp = await c.post(
            f"/api/v1/defects/{defect.id}/sync-external",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_post_sync_external_role_VIEWER_returns_403(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="def-syv@example.com")
    ws = await api_db.seed_workspace(slug="def-syv-ws", name="ViewerWs")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER)
    defect = await _seed_defect(api_db, ws.id, public_id="SUIT-SYV")

    async with api_db.client(user) as c:
        resp = await c.post(
            f"/api/v1/defects/{defect.id}/sync-external",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 403
