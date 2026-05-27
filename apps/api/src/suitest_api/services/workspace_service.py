"""WorkspaceService — NOT workspace-scoped (workspaces are the scope boundary).

Listing returns only the workspaces the current user is a member of;
``get_by_id_for_user`` returns ``None`` if the user has no membership, so a
caller cannot read a workspace they do not belong to.
"""

from __future__ import annotations

import uuid

from suitest_core.capabilities import TierFlag
from suitest_db.repositories.workspaces import WorkspaceRepo
from suitest_shared.schemas.responses import WorkspaceOut

from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_tier


class WorkspaceService:
    def __init__(self, ctx: TenantContext, repo: WorkspaceRepo) -> None:
        self._ctx = ctx
        self._repo = repo

    @require_tier(TierFlag.ANY)
    async def list_for_user(self) -> list[WorkspaceOut]:
        rows = await self._repo.list_for_user(uuid.UUID(self._ctx.user_id))
        return [WorkspaceOut.model_validate(r) for r in rows]

    @require_tier(TierFlag.ANY)
    async def get_by_id_for_user(self, workspace_id: str) -> WorkspaceOut | None:
        rows = await self._repo.list_for_user(uuid.UUID(self._ctx.user_id))
        for r in rows:
            if r.id == workspace_id:
                return WorkspaceOut.model_validate(r)
        return None
