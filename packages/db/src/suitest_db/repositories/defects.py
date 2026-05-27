"""Defect repository with filtered keyset listing + synthetic timeline."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select
from suitest_db.models.audit import AuditLog
from suitest_db.models.defect import Defect, ExternalIssue
from suitest_db.models.requirement import Requirement
from suitest_db.repositories.base import AsyncRepository
from suitest_shared.domain.enums import DefectStatus, DiagnosisKind, Severity

if TYPE_CHECKING:
    from collections.abc import Sequence


class DefectCreate(BaseModel):
    public_id: str
    workspace_id: str
    title: str
    severity: Severity
    created_by: str
    description: str | None = None
    status: DefectStatus = DefectStatus.OPEN
    component: str | None = None
    test_case_id: str | None = None
    run_id: str | None = None
    requirement_id: str | None = None
    agent_diagnosis_kind: DiagnosisKind = DiagnosisKind.MANUAL_TRIAGE


class DefectUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    severity: Severity | None = None
    status: DefectStatus | None = None
    component: str | None = None
    assignee_id: uuid.UUID | None = None
    resolved_at: datetime | None = None


class DefectTimelineEntry(BaseModel):
    """One ordered event in a defect's history (creation + every audit row)."""

    at: datetime
    action: str
    actor_id: uuid.UUID | None = None


class DefectRepo(AsyncRepository[Defect, DefectCreate, DefectUpdate]):
    model = Defect

    async def list_by_workspace(
        self,
        workspace_id: str,
        *,
        status: DefectStatus | None = None,
        severity: Severity | None = None,
        assignee_id: uuid.UUID | None = None,
        component: str | None = None,
        cursor: tuple[datetime, str] | None = None,
        limit: int = 20,
    ) -> tuple[Sequence[Defect], tuple[datetime, str] | None]:
        stmt = select(Defect).where(Defect.workspace_id == workspace_id)
        if status is not None:
            stmt = stmt.where(Defect.status == status)
        if severity is not None:
            stmt = stmt.where(Defect.severity == severity)
        if assignee_id is not None:
            stmt = stmt.where(Defect.assignee_id == assignee_id)
        if component is not None:
            stmt = stmt.where(Defect.component == component)
        if cursor is not None:
            cursor_ts, cursor_id = cursor
            stmt = stmt.where(
                (Defect.created_at < cursor_ts)
                | ((Defect.created_at == cursor_ts) & (Defect.id < cursor_id))
            )
        stmt = stmt.order_by(Defect.created_at.desc(), Defect.id.desc()).limit(limit + 1)

        rows = list((await self.session.scalars(stmt)).all())
        if len(rows) > limit:
            page = rows[:limit]
            last = page[-1]
            next_cursor: tuple[datetime, str] | None = (last.created_at, last.id)
        else:
            page = rows
            next_cursor = None
        return page, next_cursor

    async def resolve_link_public_ids(
        self, defect: Defect
    ) -> tuple[str | None, str | None, str | None]:
        """Return ``(case_public_id, run_public_id, requirement_public_id)``.

        Each is ``None`` when the corresponding FK is unset. One scalar query per
        present link — at most three, and only for set FKs.
        """
        from suitest_db.models.case import TestCase
        from suitest_db.models.requirement import Requirement
        from suitest_db.models.run import Run

        case_public: str | None = None
        run_public: str | None = None
        req_public: str | None = None
        if defect.test_case_id is not None:
            case_public = await self.session.scalar(
                select(TestCase.public_id).where(TestCase.id == defect.test_case_id)
            )
        if defect.run_id is not None:
            run_public = await self.session.scalar(
                select(Run.public_id).where(Run.id == defect.run_id)
            )
        if defect.requirement_id is not None:
            req_public = await self.session.scalar(
                select(Requirement.public_id).where(Requirement.id == defect.requirement_id)
            )
        return case_public, run_public, req_public

    async def list_by_requirement_project(self, project_id: str) -> Sequence[Defect]:
        """Defects whose ``requirement_id`` points at a requirement in the project.

        Used by the traceability matrix — the ``defects`` array lists every defect
        referenced through the project's requirements.
        """
        stmt = (
            select(Defect)
            .join(Requirement, Requirement.id == Defect.requirement_id)
            .where(Requirement.project_id == project_id)
            .order_by(Defect.public_id.asc())
        )
        return (await self.session.scalars(stmt)).all()

    async def get_external_issues(self, defect_id: str) -> Sequence[ExternalIssue]:
        """External issue links (Jira/Linear/etc) for a defect."""
        stmt = (
            select(ExternalIssue)
            .where(ExternalIssue.defect_id == defect_id)
            .order_by(ExternalIssue.synced_at.asc())
        )
        return (await self.session.scalars(stmt)).all()

    async def timeline(self, defect_id: str) -> Sequence[DefectTimelineEntry]:
        """Synthesise an ascending event timeline for a defect.

        The first entry is the defect's own creation; the remainder are audit_log
        rows whose ``resource_id`` references the defect. Ordered by ``created_at``
        ascending so the UI renders oldest-first.
        """
        defect = await self.get_by_id(defect_id)
        if defect is None:
            return []
        entries: list[DefectTimelineEntry] = [
            DefectTimelineEntry(at=defect.created_at, action="created")
        ]
        audit_stmt = (
            select(AuditLog)
            .where(AuditLog.resource_id == defect_id)
            .order_by(AuditLog.created_at.asc())
        )
        for log in (await self.session.scalars(audit_stmt)).all():
            entries.append(
                DefectTimelineEntry(at=log.created_at, action=log.action, actor_id=log.user_id)
            )
        entries.sort(key=lambda e: e.at)
        return entries
