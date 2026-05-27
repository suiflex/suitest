"""Project repository (workspace-scoped via per-method ``workspace_id``)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select
from suitest_db.models.project import Project
from suitest_db.repositories.base import AsyncRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


class ProjectCreate(BaseModel):
    workspace_id: str
    slug: str
    name: str
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class ProjectRepo(AsyncRepository[Project, ProjectCreate, ProjectUpdate]):
    model = Project

    async def list_by_workspace(self, workspace_id: str) -> Sequence[Project]:
        stmt = (
            select(Project)
            .where(Project.workspace_id == workspace_id)
            .order_by(Project.created_at.desc(), Project.id.desc())
        )
        return (await self.session.scalars(stmt)).all()

    async def get_by_slug(self, workspace_id: str, slug: str) -> Project | None:
        stmt = select(Project).where(Project.workspace_id == workspace_id, Project.slug == slug)
        result: Project | None = await self.session.scalar(stmt)
        return result
