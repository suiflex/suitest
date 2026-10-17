"""Workspace & Suite variables repositories."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from pydantic import BaseModel, Field
from sqlalchemy import select
from suitest_db.models.variable import SuiteVariable, WorkspaceVariable
from suitest_db.repositories.base import AsyncRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


class WorkspaceVariableCreate(BaseModel):
    workspace_id: str
    key: str = Field(min_length=1, max_length=120)
    value: str | None = None
    is_secret: bool = False
    description: str | None = None


class WorkspaceVariableUpdate(BaseModel):
    key: str | None = Field(default=None, min_length=1, max_length=120)
    value: str | None = None
    is_secret: bool | None = None
    description: str | None = None


class WorkspaceVariableRepo(
    AsyncRepository[WorkspaceVariable, WorkspaceVariableCreate, WorkspaceVariableUpdate]
):
    model = WorkspaceVariable

    async def list_by_workspace(self, workspace_id: str) -> Sequence[WorkspaceVariable]:
        stmt = (
            select(WorkspaceVariable)
            .where(WorkspaceVariable.workspace_id == workspace_id)
            .order_by(WorkspaceVariable.key.asc())
        )
        return list((await self.session.scalars(stmt)).all())

    async def get_by_key(self, workspace_id: str, key: str) -> WorkspaceVariable | None:
        stmt = select(WorkspaceVariable).where(
            WorkspaceVariable.workspace_id == workspace_id,
            WorkspaceVariable.key == key,
        )
        return cast("WorkspaceVariable | None", await self.session.scalar(stmt))

    async def delete(self, id: str) -> bool:
        row = await self.get_by_id(id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True


class SuiteVariableCreate(BaseModel):
    suite_id: str
    key: str = Field(min_length=1, max_length=120)
    value: str | None = None
    is_secret: bool = False
    description: str | None = None


class SuiteVariableUpdate(BaseModel):
    key: str | None = Field(default=None, min_length=1, max_length=120)
    value: str | None = None
    is_secret: bool | None = None
    description: str | None = None


class SuiteVariableRepo(AsyncRepository[SuiteVariable, SuiteVariableCreate, SuiteVariableUpdate]):
    model = SuiteVariable

    async def list_by_suite(self, suite_id: str) -> Sequence[SuiteVariable]:
        stmt = (
            select(SuiteVariable)
            .where(SuiteVariable.suite_id == suite_id)
            .order_by(SuiteVariable.key.asc())
        )
        return list((await self.session.scalars(stmt)).all())

    async def get_by_key(self, suite_id: str, key: str) -> SuiteVariable | None:
        stmt = select(SuiteVariable).where(
            SuiteVariable.suite_id == suite_id,
            SuiteVariable.key == key,
        )
        return cast("SuiteVariable | None", await self.session.scalar(stmt))

    async def delete(self, id: str) -> bool:
        row = await self.get_by_id(id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True
