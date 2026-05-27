"""SuiteService — suites are scoped through their parent project's workspace.

A suite has no ``workspace_id`` column; the scope is enforced by first checking
that the suite's project belongs to ``ctx.workspace_id`` (via ``ProjectRepo``).
"""

from __future__ import annotations

from suitest_core.capabilities import TierFlag
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.suites import SuiteRepo
from suitest_shared.schemas.responses import SuiteOut

from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_tier


class SuiteService:
    def __init__(self, ctx: TenantContext, repo: SuiteRepo, project_repo: ProjectRepo) -> None:
        self._ctx = ctx
        self._repo = repo
        self._project_repo = project_repo

    async def _project_in_scope(self, project_id: str) -> bool:
        project = await self._project_repo.get_by_id(project_id)
        return project is not None and project.workspace_id == self._ctx.workspace_id

    @require_tier(TierFlag.ANY)
    async def list(self, project_id: str) -> list[SuiteOut] | None:
        if not await self._project_in_scope(project_id):
            return None
        rows = await self._repo.list_by_project(project_id)
        return [SuiteOut.model_validate(r) for r in rows]

    @require_tier(TierFlag.ANY)
    async def get_by_id(self, suite_id: str) -> SuiteOut | None:
        row = await self._repo.get_by_id(suite_id)
        if row is None or not await self._project_in_scope(row.project_id):
            return None
        return SuiteOut.model_validate(row)
