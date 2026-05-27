"""RequirementService + TraceabilityService — scoped via project -> workspace."""

from __future__ import annotations

from suitest_core.capabilities import TierFlag
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.requirements import RequirementRepo
from suitest_shared.schemas.responses import (
    RequirementOut,
    TraceabilityMatrixOut,
    TraceabilityRow,
)

from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_tier


class RequirementService:
    def __init__(
        self, ctx: TenantContext, repo: RequirementRepo, project_repo: ProjectRepo
    ) -> None:
        self._ctx = ctx
        self._repo = repo
        self._project_repo = project_repo

    async def _project_in_scope(self, project_id: str) -> bool:
        project = await self._project_repo.get_by_id(project_id)
        return project is not None and project.workspace_id == self._ctx.workspace_id

    @require_tier(TierFlag.ANY)
    async def list(self, project_id: str) -> list[RequirementOut] | None:
        if not await self._project_in_scope(project_id):
            return None
        rows = await self._repo.list_by_project(project_id)
        return [RequirementOut.model_validate(r) for r in rows]

    @require_tier(TierFlag.ANY)
    async def get_by_id(self, requirement_id: str) -> RequirementOut | None:
        row = await self._repo.get_by_id(requirement_id)
        if row is None or not await self._project_in_scope(row.project_id):
            return None
        return RequirementOut.model_validate(row)


class TraceabilityService:
    def __init__(
        self, ctx: TenantContext, repo: RequirementRepo, project_repo: ProjectRepo
    ) -> None:
        self._ctx = ctx
        self._repo = repo
        self._project_repo = project_repo

    @require_tier(TierFlag.ANY)
    async def matrix(self, project_id: str) -> TraceabilityMatrixOut | None:
        project = await self._project_repo.get_by_id(project_id)
        if project is None or project.workspace_id != self._ctx.workspace_id:
            return None
        requirements = await self._repo.list_by_project(project_id)
        rows: list[TraceabilityRow] = []
        for req in requirements:
            links = await self._repo.with_links(req.id)
            case_ids = [link.case_id for link in links]
            rows.append(
                TraceabilityRow(
                    requirement_id=req.id,
                    public_id=req.public_id,
                    title=req.title,
                    case_ids=case_ids,
                    covered=bool(case_ids),
                )
            )
        return TraceabilityMatrixOut(project_id=project_id, rows=rows)
