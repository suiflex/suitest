"""AgentDefinitionRepo — CRUD repository for workspace agent plugin definitions (M8).

Follows the project's repository pattern (AsyncRepository base + domain helpers).
All queries are workspace-scoped and respect the ``is_active`` soft-delete flag.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select
from suitest_db.models.agent_definition import AgentDefinition
from suitest_db.repositories.base import AsyncRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


class AgentDefinitionCreate(BaseModel):
    """DTO for inserting a new agent definition row."""

    workspace_id: str
    name: str
    spec_yaml: str
    spec_version: str
    created_by: str | None = None


class AgentDefinitionUpdate(BaseModel):
    """DTO for updating spec fields (all optional)."""

    spec_yaml: str | None = None
    spec_version: str | None = None


class AgentDefinitionRepo(
    AsyncRepository[AgentDefinition, AgentDefinitionCreate, AgentDefinitionUpdate]
):
    """Async CRUD repository for :class:`~suitest_db.models.agent_definition.AgentDefinition`."""

    model = AgentDefinition

    async def get_active_by_name(self, workspace_id: str, name: str) -> AgentDefinition | None:
        """Return the active definition for ``name`` in ``workspace_id``, or ``None``."""
        stmt = select(AgentDefinition).where(
            AgentDefinition.workspace_id == workspace_id,
            AgentDefinition.name == name,
            AgentDefinition.is_active.is_(True),
        )
        result: AgentDefinition | None = await self.session.scalar(stmt)
        return result

    async def list_active(self, workspace_id: str) -> Sequence[AgentDefinition]:
        """Return all active definitions for ``workspace_id``, newest first."""
        stmt = (
            select(AgentDefinition)
            .where(
                AgentDefinition.workspace_id == workspace_id,
                AgentDefinition.is_active.is_(True),
            )
            .order_by(AgentDefinition.created_at.desc(), AgentDefinition.id.desc())
        )
        return (await self.session.scalars(stmt)).all()

    async def deactivate(self, workspace_id: str, name: str) -> bool:
        """Soft-delete by setting ``is_active=False``.

        Returns ``True`` iff a matching active row was found and updated.
        """
        row = await self.get_active_by_name(workspace_id, name)
        if row is None:
            return False
        row.is_active = False
        row.updated_at = datetime.now(UTC)
        await self.session.flush()
        return True

    async def update_spec(
        self,
        workspace_id: str,
        name: str,
        spec_yaml: str,
        spec_version: str,
    ) -> AgentDefinition | None:
        """Update the YAML spec and version for an active definition.

        Returns the updated row, or ``None`` when no active row exists.
        """
        row = await self.get_active_by_name(workspace_id, name)
        if row is None:
            return None
        row.spec_yaml = spec_yaml
        row.spec_version = spec_version
        row.updated_at = datetime.now(UTC)
        await self.session.flush()
        return row
