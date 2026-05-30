"""Requirement repository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import func, select
from suitest_db.models.case import TestCase
from suitest_db.models.defect import Defect
from suitest_db.models.project import Project
from suitest_db.models.requirement import Requirement, RequirementLink
from suitest_db.public_id import set_workspace_id
from suitest_db.repositories.base import AsyncRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


class RequirementCreate(BaseModel):
    project_id: str
    title: str
    # Optional: filled by the ``before_insert`` listener
    # (suitest_db.public_id) from the per-workspace ``REQ`` sequence.
    public_id: str | None = None
    description: str | None = None
    source: str | None = None
    external_url: str | None = None


class RequirementUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    source: str | None = None
    external_url: str | None = None


class RequirementRepo(AsyncRepository[Requirement, RequirementCreate, RequirementUpdate]):
    model = Requirement

    async def create(  # type: ignore[override]
        self, dto: RequirementCreate, *, workspace_id: str
    ) -> Requirement:
        """Create a requirement, deferring ``public_id`` to the ``before_insert`` listener.

        See :meth:`TestCaseRepo.create` for the rationale on the LSP override.
        """
        row = Requirement(**dto.model_dump(exclude_unset=True))
        set_workspace_id(row, workspace_id)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_by_project(self, project_id: str) -> Sequence[Requirement]:
        """Active requirements for a project, newest-first."""
        stmt = (
            select(Requirement)
            .where(Requirement.project_id == project_id)
            .where(Requirement.deleted_at.is_(None))
            .order_by(Requirement.created_at.desc(), Requirement.id.desc())
        )
        return (await self.session.scalars(stmt)).all()

    async def with_links(self, req_id: str) -> Sequence[RequirementLink]:
        stmt = select(RequirementLink).where(RequirementLink.requirement_id == req_id)
        return (await self.session.scalars(stmt)).all()

    async def list_by_project_paginated(
        self,
        project_id: str,
        *,
        cursor: tuple[datetime, str] | None = None,
        limit: int = 20,
        include_deleted: bool = False,
    ) -> tuple[Sequence[Requirement], tuple[datetime, str] | None]:
        """Keyset page of a project's requirements (newest-first, id tiebreak).

        ``include_deleted=False`` (default) hides soft-deleted rows — used by the
        public LIST endpoint. ``True`` is reserved for an ADMIN-only ``?includeDeleted``
        query param (out of scope for M1d-6).
        """
        # ``list_paginated`` doesn't support per-call WHERE composition; build the
        # query inline so we can append ``deleted_at IS NULL`` (which hits the
        # M1d-6 partial index ``ix_requirements_project_active``).
        from sqlalchemy import tuple_

        stmt = select(Requirement).where(Requirement.project_id == project_id)
        if not include_deleted:
            stmt = stmt.where(Requirement.deleted_at.is_(None))
        if cursor is not None:
            stmt = stmt.where(tuple_(Requirement.created_at, Requirement.id) < cursor)
        stmt = stmt.order_by(Requirement.created_at.desc(), Requirement.id.desc()).limit(limit + 1)
        rows = list((await self.session.scalars(stmt)).all())
        return self._paginate(rows, limit)

    async def link_counts(self, requirement_ids: Sequence[str]) -> dict[str, int]:
        """Map requirement id → number of linked cases (one grouped query)."""
        if not requirement_ids:
            return {}
        stmt = (
            select(RequirementLink.requirement_id, func.count(RequirementLink.case_id))
            .where(RequirementLink.requirement_id.in_(requirement_ids))
            .group_by(RequirementLink.requirement_id)
        )
        counts: dict[str, int] = {}
        for req_id, count in (await self.session.execute(stmt)).all():
            counts[req_id] = count
        return counts

    # ------------------------------------------------------------------
    # M1d-6 write helpers
    # ------------------------------------------------------------------

    async def update_metadata(self, req_id: str, dto: RequirementUpdate) -> Requirement | None:
        """Patch metadata; only ``model_dump(exclude_unset=True)`` keys apply."""
        row = await self.get_by_id(req_id)
        if row is None or row.deleted_at is not None:
            return None
        for field, value in dto.model_dump(exclude_unset=True).items():
            setattr(row, field, value)
        await self.session.flush()
        return row

    async def mark_deleted(self, req_id: str, *, deleted_at: datetime | None = None) -> bool:
        """Set ``deleted_at`` to NOW(); return ``True`` if a row existed + was active."""
        row = await self.get_by_id(req_id)
        if row is None or row.deleted_at is not None:
            return False
        row.deleted_at = deleted_at if deleted_at is not None else datetime.now(tz=UTC)
        await self.session.flush()
        return True

    async def clear_deleted(self, req_id: str) -> bool:
        """Clear the ``deleted_at`` tombstone (restore); idempotent."""
        row = await self.get_by_id(req_id)
        if row is None:
            return False
        if row.deleted_at is not None:
            row.deleted_at = None
            await self.session.flush()
        return True

    async def get_workspace_id(self, req_id: str) -> str | None:
        """Resolve the workspace id of a requirement via its parent project.

        Used by the cross-workspace link guard (``CROSS_WORKSPACE_LINK``). Returns
        ``None`` when the requirement does not exist.
        """
        stmt = (
            select(Project.workspace_id)
            .join(Requirement, Requirement.project_id == Project.id)
            .where(Requirement.id == req_id)
        )
        result = await self.session.scalar(stmt)
        return result

    # --- link helpers --------------------------------------------------

    async def find_link(self, req_id: str, case_id: str) -> RequirementLink | None:
        """Look up the join row for ``(requirement_id, case_id)``."""
        stmt = select(RequirementLink).where(
            RequirementLink.requirement_id == req_id,
            RequirementLink.case_id == case_id,
        )
        result: RequirementLink | None = await self.session.scalar(stmt)
        return result

    async def create_link(self, req_id: str, case_id: str) -> RequirementLink:
        """Insert a ``RequirementLink`` row. Callers must enforce ws/scope first."""
        link = RequirementLink(requirement_id=req_id, case_id=case_id)
        self.session.add(link)
        await self.session.flush()
        return link

    async def delete_link(self, req_id: str, case_id: str) -> bool:
        """Delete a link row; return ``True`` when a row was removed."""
        link = await self.find_link(req_id, case_id)
        if link is None:
            return False
        await self.session.delete(link)
        await self.session.flush()
        return True

    async def linked_case_public_ids(self, requirement_id: str) -> list[str]:
        """Public ids (e.g. ``TC-1045``) of cases linked to a requirement."""
        stmt = (
            select(TestCase.public_id)
            .join(RequirementLink, RequirementLink.case_id == TestCase.id)
            .where(RequirementLink.requirement_id == requirement_id)
            .order_by(TestCase.public_id.asc())
        )
        return list((await self.session.scalars(stmt)).all())

    async def linked_defect_public_ids(self, requirement_id: str) -> list[str]:
        """Public ids of defects whose ``requirement_id`` references this requirement."""
        stmt = (
            select(Defect.public_id)
            .where(Defect.requirement_id == requirement_id)
            .order_by(Defect.public_id.asc())
        )
        return list((await self.session.scalars(stmt)).all())

    async def links_by_project(self, project_id: str) -> Sequence[RequirementLink]:
        """All requirement->case links for a project's requirements (matrix build)."""
        stmt = (
            select(RequirementLink)
            .join(Requirement, Requirement.id == RequirementLink.requirement_id)
            .where(Requirement.project_id == project_id)
        )
        return (await self.session.scalars(stmt)).all()
