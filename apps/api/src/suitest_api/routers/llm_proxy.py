"""LLM completion proxy for the lifecycle/MCP client (docs/API.md §4).

``POST /api/v1/llm/complete`` runs a one-shot completion against the
workspace's ACTIVE LLM config. Auth accepts an API key (``sk_suitest_…``) or a
session — the ``suitest test`` lifecycle uses its publish API key, so the
provider key NEVER leaves the server (CLAUDE.md: all AI calls go through
``packages/agent``; LLM providers are per-workspace, AES-encrypted).

Tier gating is implicit: a workspace with no active LLM config *is* ZERO tier
and gets a 409 — the lifecycle degrades to its deterministic baseline.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_agent.providers.base import ChatMessage, ModelCall, ProviderError
from suitest_agent.providers.litellm_router import get_provider
from suitest_db.repositories.llm_configs import LLMConfigRepo

from suitest_api.auth.db import get_async_session
from suitest_api.deps.api_key import tenant_via_api_key_or_session
from suitest_api.deps.scope import TenantContext

router = APIRouter(prefix="/api/v1", tags=["llm"])


class LlmCompleteRequest(BaseModel):
    """One-shot completion request. Kept deliberately small — this is a proxy
    for lifecycle codegen/enrichment, not a chat surface (that's /agent/chat)."""

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    prompt: str = Field(min_length=1, max_length=200_000)
    system: str | None = Field(default=None, max_length=50_000)
    max_tokens: int = Field(default=4096, ge=1, le=32_000, alias="maxTokens")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


class LlmCompleteResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    content: str
    model: str
    tokens_in: int = Field(serialization_alias="tokensIn")
    tokens_out: int = Field(serialization_alias="tokensOut")
    cost_usd: float = Field(serialization_alias="costUsd")


@router.post("/llm/complete", response_model=LlmCompleteResponse)
async def llm_complete(
    body: LlmCompleteRequest,
    ctx: TenantContext = Depends(tenant_via_api_key_or_session),
    session: AsyncSession = Depends(get_async_session),
) -> LlmCompleteResponse:
    """Proxy one completion through the workspace's active LLM provider."""
    config = await LLMConfigRepo(session).get_active(ctx.workspace_id)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="no active LLM configured for this workspace",
        )
    base_url = config.config_json.get("base_url")
    provider = get_provider(
        config.provider,
        api_key=config.api_key_encrypted,
        base_url=base_url if isinstance(base_url, str) else None,
    )
    messages: list[ChatMessage] = []
    if body.system:
        messages.append(ChatMessage(role="system", content=body.system))
    messages.append(ChatMessage(role="user", content=body.prompt))
    call = ModelCall(
        model=config.model,
        messages=messages,
        max_tokens=body.max_tokens,
        temperature=body.temperature,
    )
    try:
        result = await provider.complete(call)
    except ProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM provider error: {exc}",
        ) from exc
    return LlmCompleteResponse(
        content=result.content,
        model=result.model,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        cost_usd=result.cost_usd,
    )
