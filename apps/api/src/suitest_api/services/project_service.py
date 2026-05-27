"""ProjectService — workspace-scoped CRUD reads."""

from __future__ import annotations

from suitest_core.capabilities import TierFlag
from suitest_db.repositories.projects import ProjectRepo
from suitest_shared.schemas.responses import ProjectOut

from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_tier


class ProjectService:
    def __init__(self, ctx: TenantContext, repo: ProjectRepo) -> None:
        self._ctx = ctx
        self._repo = repo

    @require_tier(TierFlag.ANY)
    async def list(self) -> list[ProjectOut]:
        rows = await self._repo.list_by_workspace(self._ctx.workspace_id)
        return [ProjectOut.model_validate(r) for r in rows]

    @require_tier(TierFlag.ANY)
    async def get_by_id(self, project_id: str) -> ProjectOut | None:
        row = await self._repo.get_by_id(project_id)
        if row is None or row.workspace_id != self._ctx.workspace_id:
            return None
        return ProjectOut.model_validate(row)
