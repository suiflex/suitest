"""WorkspaceCapability repository — single materialized row per workspace."""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import select
from suitest_db.models.workspace_capability import WorkspaceCapability
from suitest_db.repositories.base import AsyncRepository
from suitest_shared.domain.enums import AutonomyLevel, Tier


class WorkspaceCapabilityCreate(BaseModel):
    workspace_id: str
    tier: Tier
    autonomy_level: AutonomyLevel = AutonomyLevel.MANUAL
    features_json: dict[str, object] | None = None


class WorkspaceCapabilityUpdate(BaseModel):
    tier: Tier | None = None
    autonomy_level: AutonomyLevel | None = None
    features_json: dict[str, object] | None = None


class WorkspaceCapabilityRepo(
    AsyncRepository[WorkspaceCapability, WorkspaceCapabilityCreate, WorkspaceCapabilityUpdate]
):
    model = WorkspaceCapability

    async def get(self, workspace_id: str) -> WorkspaceCapability | None:
        stmt = select(WorkspaceCapability).where(WorkspaceCapability.workspace_id == workspace_id)
        result: WorkspaceCapability | None = await self.session.scalar(stmt)
        return result

    async def upsert(
        self,
        workspace_id: str,
        tier: Tier,
        autonomy: AutonomyLevel,
        features: dict[str, object],
    ) -> WorkspaceCapability:
        """Insert the capability row for a workspace, or update it in place.

        ``workspace_id`` carries a unique constraint, so there is at most one row;
        the second call mutates the existing row rather than inserting a duplicate.
        """
        row = await self.get(workspace_id)
        if row is None:
            row = WorkspaceCapability(
                workspace_id=workspace_id,
                tier=tier,
                autonomy_level=autonomy,
                features_json=features,
            )
            self.session.add(row)
        else:
            row.tier = tier
            row.autonomy_level = autonomy
            row.features_json = features
        await self.session.flush()
        return row
