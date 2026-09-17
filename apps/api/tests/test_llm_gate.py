from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_autonomy, require_llm_ready
from suitest_shared.domain.enums import AutonomyLevel, Role


class _LlmRepo:
    config: object | None = None

    def __init__(self, _session: AsyncSession) -> None:
        pass

    async def get_active(self, _workspace_id: str) -> object | None:
        return self.config


class _CapabilityRepo:
    level = AutonomyLevel.MANUAL

    def __init__(self, _session: AsyncSession) -> None:
        pass

    async def get(self, _workspace_id: str) -> object:
        return SimpleNamespace(autonomy_level=self.level)


@pytest.mark.asyncio
async def test_llm_and_autonomy_gates_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("suitest_api.deps.tier.LLMConfigRepo", _LlmRepo)
    monkeypatch.setattr("suitest_api.deps.tier.WorkspaceCapabilityRepo", _CapabilityRepo)
    ctx = TenantContext(workspace_id="ws-1", user_id="user-1", role=Role.OWNER)
    session = AsyncSession()

    with pytest.raises(HTTPException) as missing:
        await require_llm_ready(ctx=ctx, session=session)
    assert missing.value.status_code == 409

    _LlmRepo.config = SimpleNamespace(last_validated_at=None)
    with pytest.raises(HTTPException) as unvalidated:
        await require_llm_ready(ctx=ctx, session=session)
    assert unvalidated.value.detail["llmStatus"] == "validation_required"

    _LlmRepo.config = SimpleNamespace(last_validated_at=datetime.now(UTC))
    assert await require_llm_ready(ctx=ctx, session=session) == ctx

    autonomy_checker = require_autonomy(AutonomyLevel.ASSIST)
    with pytest.raises(HTTPException):
        await autonomy_checker(ctx=ctx, session=session)
    _CapabilityRepo.level = AutonomyLevel.ASSIST
    assert await autonomy_checker(ctx=ctx, session=session) == ctx
    await session.close()
