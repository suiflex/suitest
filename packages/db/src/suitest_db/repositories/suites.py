"""Suite repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select
from suitest_db.models.project import Suite
from suitest_db.repositories.base import AsyncRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


class SuiteCreate(BaseModel):
    project_id: str
    name: str
    description: str | None = None
    order: int = 0


class SuiteUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    order: int | None = None


class SuiteRepo(AsyncRepository[Suite, SuiteCreate, SuiteUpdate]):
    model = Suite

    async def list_by_project(self, project_id: str) -> Sequence[Suite]:
        stmt = (
            select(Suite)
            .where(Suite.project_id == project_id)
            .order_by(Suite.order.asc(), Suite.created_at.desc(), Suite.id.desc())
        )
        return (await self.session.scalars(stmt)).all()
