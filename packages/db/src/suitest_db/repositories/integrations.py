"""Integration repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select
from suitest_db.models.integration import Integration
from suitest_db.repositories.base import AsyncRepository
from suitest_shared.domain.enums import IntegrationKind

if TYPE_CHECKING:
    from collections.abc import Sequence


class IntegrationCreate(BaseModel):
    workspace_id: str
    kind: IntegrationKind
    name: str
    config: dict[str, object]
    secrets_encrypted: str | None = None
    status: str = "active"


class IntegrationUpdate(BaseModel):
    name: str | None = None
    config: dict[str, object] | None = None
    secrets_encrypted: str | None = None
    status: str | None = None


class IntegrationRepo(AsyncRepository[Integration, IntegrationCreate, IntegrationUpdate]):
    model = Integration

    async def list_by_workspace(
        self, workspace_id: str, *, kind: IntegrationKind | None = None
    ) -> Sequence[Integration]:
        stmt = select(Integration).where(Integration.workspace_id == workspace_id)
        if kind is not None:
            stmt = stmt.where(Integration.kind == kind)
        stmt = stmt.order_by(Integration.created_at.desc(), Integration.id.desc())
        return (await self.session.scalars(stmt)).all()
