"""PromptExperiment repository (M5-4).

Manages prompt A/B tests: :meth:`get_active` is what the resolver consults to
decide whether a prompt is under experiment; :meth:`record_impression` and
:meth:`record_outcome` accumulate per-variant counters for the live dashboard.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel
from sqlalchemy import select
from suitest_db.models.prompt_experiment import PromptExperiment
from suitest_db.repositories.base import AsyncRepository

if TYPE_CHECKING:
    from collections.abc import Sequence

Variant = Literal["A", "B"]


class PromptExperimentCreate(BaseModel):
    workspace_id: str
    prompt_name: str
    variant_a_override_id: str | None = None
    variant_b_override_id: str | None = None
    split_pct: int = 50
    created_by: uuid.UUID | None = None


class PromptExperimentUpdate(BaseModel):
    status: str | None = None
    split_pct: int | None = None


class PromptExperimentRepo(
    AsyncRepository[PromptExperiment, PromptExperimentCreate, PromptExperimentUpdate]
):
    model = PromptExperiment

    async def get_active(self, workspace_id: str, prompt_name: str) -> PromptExperiment | None:
        stmt = (
            select(PromptExperiment)
            .where(
                PromptExperiment.workspace_id == workspace_id,
                PromptExperiment.prompt_name == prompt_name,
                PromptExperiment.status == "active",
            )
            .order_by(PromptExperiment.created_at.desc())
        )
        row: PromptExperiment | None = await self.session.scalar(stmt)
        return row

    async def list_for_workspace(self, workspace_id: str) -> Sequence[PromptExperiment]:
        stmt = (
            select(PromptExperiment)
            .where(PromptExperiment.workspace_id == workspace_id)
            .order_by(PromptExperiment.created_at.desc())
        )
        return (await self.session.scalars(stmt)).all()

    async def record_impression(self, experiment_id: str, variant: Variant) -> None:
        row = await self.get_by_id(experiment_id)
        if row is None:
            return
        if variant == "A":
            row.a_impressions += 1
        else:
            row.b_impressions += 1
        await self.session.flush()

    async def record_outcome(
        self, experiment_id: str, variant: Variant, *, success: bool
    ) -> PromptExperiment | None:
        row = await self.get_by_id(experiment_id)
        if row is None:
            return None
        if success:
            if variant == "A":
                row.a_successes += 1
            else:
                row.b_successes += 1
        await self.session.flush()
        return row

    async def stop(self, workspace_id: str, experiment_id: str) -> PromptExperiment | None:
        row = await self.get_by_id(experiment_id)
        if row is None or row.workspace_id != workspace_id:
            return None
        row.status = "stopped"
        await self.session.flush()
        return row
