"""TestCaseService — cases are scoped via suite -> project -> workspace.

``list`` lists cases within a suite but first proves that suite belongs to a
project in ``ctx.workspace_id``; ``get_by_id_with_steps`` walks the same chain and
returns ``None`` (router maps to 404) when the case lives in another workspace.
"""

from __future__ import annotations

from suitest_core.capabilities import TierFlag
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.suites import SuiteRepo
from suitest_db.repositories.test_cases import TestCaseRepo
from suitest_shared.domain.enums import CaseSource, CaseStatus, Priority
from suitest_shared.schemas.responses import TestCaseDetailOut, TestCaseOut, TestStepOut

from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_tier


class TestCaseService:
    __test__ = False  # not a pytest test class

    def __init__(
        self,
        ctx: TenantContext,
        repo: TestCaseRepo,
        suite_repo: SuiteRepo,
        project_repo: ProjectRepo,
    ) -> None:
        self._ctx = ctx
        self._repo = repo
        self._suite_repo = suite_repo
        self._project_repo = project_repo

    async def _suite_in_scope(self, suite_id: str) -> bool:
        suite = await self._suite_repo.get_by_id(suite_id)
        if suite is None:
            return False
        project = await self._project_repo.get_by_id(suite.project_id)
        return project is not None and project.workspace_id == self._ctx.workspace_id

    @require_tier(TierFlag.ANY)
    async def list(
        self,
        suite_id: str,
        *,
        status: CaseStatus | None = None,
        source: CaseSource | None = None,
        priority: Priority | None = None,
        tag: str | None = None,
        q: str | None = None,
        limit: int = 20,
    ) -> list[TestCaseOut] | None:
        # Scope gate: WHERE suites.project.workspace_id = ctx.workspace_id.
        if not await self._suite_in_scope(suite_id):
            return None
        rows, _ = await self._repo.list_by_suite_filtered(
            suite_id,
            status=status,
            source=source,
            priority=priority,
            tag=tag,
            q=q,
            limit=limit,
        )
        return [TestCaseOut.model_validate(r) for r in rows]

    @require_tier(TierFlag.ANY)
    async def get_by_id_with_steps(self, case_id: str) -> TestCaseDetailOut | None:
        row = await self._repo.get_by_id(case_id)
        if row is None or not await self._suite_in_scope(row.suite_id):
            return None
        steps = await self._repo.get_steps(case_id)
        detail = TestCaseDetailOut.model_validate(row)
        detail.steps = [TestStepOut.model_validate(s) for s in steps]
        return detail
