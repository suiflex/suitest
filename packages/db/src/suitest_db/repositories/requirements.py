"""Requirement repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import func, select
from suitest_db.models.case import TestCase
from suitest_db.models.defect import Defect
from suitest_db.models.requirement import Requirement, RequirementLink
from suitest_db.public_id import set_workspace_id
from suitest_db.repositories.base import AsyncRepository

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime


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
        stmt = (
            select(Requirement)
            .where(Requirement.project_id == project_id)
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
    ) -> tuple[Sequence[Requirement], tuple[datetime, str] | None]:
        """Keyset page of a project's requirements (newest-first, id tiebreak)."""
        return await self.list_paginated(
            cursor=cursor, limit=limit, filters={"project_id": project_id}
        )

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
