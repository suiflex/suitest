"""GeneratorRun repository — deterministic generator traceability (M2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select
from suitest_db.models.generator_run import GeneratorRun
from suitest_db.repositories.base import AsyncRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


class GeneratorRunCreate(BaseModel):
    workspace_id: str
    source: str
    input_meta_json: dict[str, object] = {}
    output_case_ids_json: list[str] = []
    duration_ms: int | None = None
    created_by_user_id: str | None = None


class GeneratorRunUpdate(BaseModel):
    output_case_ids_json: list[str] | None = None
    duration_ms: int | None = None


class GeneratorRunRepo(AsyncRepository[GeneratorRun, GeneratorRunCreate, GeneratorRunUpdate]):
    model = GeneratorRun

    async def list_by_workspace(self, workspace_id: str) -> Sequence[GeneratorRun]:
        stmt = (
            select(GeneratorRun)
            .where(GeneratorRun.workspace_id == workspace_id)
            .order_by(GeneratorRun.created_at.desc(), GeneratorRun.id.desc())
        )
        return (await self.session.scalars(stmt)).all()
