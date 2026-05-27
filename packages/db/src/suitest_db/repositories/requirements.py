"""Requirement repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select
from suitest_db.models.requirement import Requirement, RequirementLink
from suitest_db.repositories.base import AsyncRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


class RequirementCreate(BaseModel):
    project_id: str
    public_id: str
    title: str
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
