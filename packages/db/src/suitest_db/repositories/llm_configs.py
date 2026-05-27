"""LLMConfig repository."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import select
from suitest_db.models.llm_config import LLMConfig
from suitest_db.repositories.base import AsyncRepository


class LLMConfigCreate(BaseModel):
    workspace_id: str
    provider: str
    model: str
    api_key_encrypted: str | None = None
    config_json: dict[str, object] | None = None
    is_active: bool = False


class LLMConfigUpdate(BaseModel):
    provider: str | None = None
    model: str | None = None
    api_key_encrypted: str | None = None
    config_json: dict[str, object] | None = None
    is_active: bool | None = None
    last_validated_at: datetime | None = None


class LLMConfigRepo(AsyncRepository[LLMConfig, LLMConfigCreate, LLMConfigUpdate]):
    model = LLMConfig

    async def get_active(self, workspace_id: str) -> LLMConfig | None:
        stmt = (
            select(LLMConfig)
            .where(LLMConfig.workspace_id == workspace_id, LLMConfig.is_active.is_(True))
            .order_by(LLMConfig.created_at.desc(), LLMConfig.id.desc())
            .limit(1)
        )
        result: LLMConfig | None = await self.session.scalar(stmt)
        return result
