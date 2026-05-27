"""DefectService — defects carry ``workspace_id`` directly, so scoping is direct."""

from __future__ import annotations

import uuid

from suitest_core.capabilities import TierFlag
from suitest_db.repositories.defects import DefectRepo
from suitest_shared.domain.enums import DefectStatus, Severity
from suitest_shared.schemas.responses import DefectOut

from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_tier


class DefectService:
    def __init__(self, ctx: TenantContext, repo: DefectRepo) -> None:
        self._ctx = ctx
        self._repo = repo

    @require_tier(TierFlag.ANY)
    async def list(
        self,
        *,
        status: DefectStatus | None = None,
        severity: Severity | None = None,
        assignee_id: uuid.UUID | None = None,
        component: str | None = None,
        limit: int = 20,
    ) -> list[DefectOut]:
        rows, _ = await self._repo.list_by_workspace(
            self._ctx.workspace_id,
            status=status,
            severity=severity,
            assignee_id=assignee_id,
            component=component,
            limit=limit,
        )
        return [DefectOut.model_validate(r) for r in rows]

    @require_tier(TierFlag.ANY)
    async def get_by_id(self, defect_id: str) -> DefectOut | None:
        row = await self._repo.get_by_id(defect_id)
        if row is None or row.workspace_id != self._ctx.workspace_id:
            return None
        return DefectOut.model_validate(row)
