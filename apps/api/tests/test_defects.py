"""Task 7f — defect read endpoint tests (docs/API.md §3.6)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_db.models.audit import AuditLog
from suitest_db.models.case import TestCase
from suitest_db.models.defect import Defect, ExternalIssue
from suitest_db.models.project import Project, Suite
from suitest_shared.domain.enums import CaseSource, DefectStatus, Severity

if TYPE_CHECKING:
    from api_harness import ApiDb


def _defect(
    ws_id: str,
    public_id: str,
    *,
    severity: Severity = Severity.HIGH,
    status: DefectStatus = DefectStatus.OPEN,
    test_case_id: str | None = None,
) -> Defect:
    return Defect(
        public_id=public_id,
        workspace_id=ws_id,
        title="bug",
        severity=severity,
        status=status,
        created_by="seed",
        test_case_id=test_case_id,
    )


@pytest.mark.asyncio
async def test_list_defects_filter_status_open(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="def-status@example.com")
    ws = await api_db.member_workspace(user, slug="def-status-ws")
    await api_db.add_all(
        [
            _defect(ws.id, "SUIT-O1", status=DefectStatus.OPEN),
            _defect(ws.id, "SUIT-O2", status=DefectStatus.OPEN),
            _defect(ws.id, "SUIT-C1", status=DefectStatus.CLOSED),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/defects?status=OPEN", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 2


@pytest.mark.asyncio
async def test_list_defects_filter_severity_critical(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="def-sev@example.com")
    ws = await api_db.member_workspace(user, slug="def-sev-ws")
    await api_db.add_all(
        [
            _defect(ws.id, "SUIT-CR1", severity=Severity.CRITICAL),
            _defect(ws.id, "SUIT-LO1", severity=Severity.LOW),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/defects?severity=CRITICAL", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert {d["public_id"] for d in items} == {"SUIT-CR1"}


@pytest.mark.asyncio
async def test_get_defect_detail_includes_external_issues(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="def-ext@example.com")
    ws = await api_db.member_workspace(user, slug="def-ext-ws")
    proj = Project(workspace_id=ws.id, slug="def-proj", name="P")
    await api_db.add_all([proj])
    suite = Suite(project_id=proj.id, name="S", order=0)
    await api_db.add_all([suite])
    case = TestCase(suite_id=suite.id, public_id="TC-DEF1", name="c", source=CaseSource.MANUAL)
    await api_db.add_all([case])
    defect = _defect(ws.id, "SUIT-EXT", test_case_id=case.id)
    await api_db.add_all([defect])
    await api_db.add_all(
        [
            ExternalIssue(
                defect_id=defect.id,
                provider="jira",
                external_id="PROJ-42",
                external_url="https://jira.example/PROJ-42",
            )
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/defects/{defect.id}", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    data = resp.json()
    assert data["test_case_public_id"] == "TC-DEF1"
    assert len(data["external_issues"]) == 1
    assert data["external_issues"][0]["external_id"] == "PROJ-42"


@pytest.mark.asyncio
async def test_get_defect_timeline_includes_creation_and_audit_rows(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="def-tl@example.com")
    ws = await api_db.member_workspace(user, slug="def-tl-ws")
    defect = _defect(ws.id, "SUIT-TL")
    await api_db.add_all([defect])
    await api_db.add_all(
        [
            AuditLog(
                workspace_id=ws.id,
                action="defect.updated",
                resource_type="defects",
                resource_id=defect.id,
                user_id=user.id,
            )
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/defects/{defect.id}/timeline", headers={"X-Workspace-Id": ws.id}
        )
    assert resp.status_code == 200
    entries = resp.json()
    actions = [e["action"] for e in entries]
    assert actions[0] == "created"
    assert "defect.updated" in actions


@pytest.mark.asyncio
async def test_get_defect_404_cross_workspace(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="def-x@example.com")
    ws = await api_db.member_workspace(user, slug="def-x-ws")
    other = await api_db.seed_workspace(slug="def-x-other", name="Other")
    defect = _defect(other.id, "SUIT-XX")
    await api_db.add_all([defect])

    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/defects/{defect.id}", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 404
