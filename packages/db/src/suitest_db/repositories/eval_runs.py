"""EvalRun repository (M5-2).

Backs the score-regression dashboard: :meth:`list_by_workspace` returns a
workspace's eval runs newest-first (optionally filtered to one suite) so the UI
can plot pass-rate over time and spot regressions between consecutive runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select
from suitest_db.models.eval_run import EvalRun
from suitest_db.repositories.base import AsyncRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


class EvalRunCreate(BaseModel):
    workspace_id: str
    eval_suite_name: str
    fixtures_count: int
    passed: int
    failed: int
    model_id: str
    prompt_version_id: str | None = None
    results_json: dict[str, object]


class EvalRunUpdate(BaseModel):
    """Eval runs are immutable snapshots — no updatable fields."""


class EvalRunRepo(AsyncRepository[EvalRun, EvalRunCreate, EvalRunUpdate]):
    model = EvalRun

    async def list_by_workspace(
        self,
        workspace_id: str,
        *,
        suite_name: str | None = None,
        limit: int = 50,
    ) -> Sequence[EvalRun]:
        """Return a workspace's eval runs newest-first, optionally one suite.

        Bounded read (``limit`` ≤ 100) for the regression chart — no cursor.
        """
        stmt = select(EvalRun).where(EvalRun.workspace_id == workspace_id)
        if suite_name is not None:
            stmt = stmt.where(EvalRun.eval_suite_name == suite_name)
        stmt = stmt.order_by(EvalRun.run_at.desc(), EvalRun.id.desc()).limit(limit)
        return (await self.session.scalars(stmt)).all()
