"""Workspace LLM config — Settings → LLM (M3-2) + tier refresh (M3-3).

Surface (docs/API.md §3.14):

* ``GET    /workspaces/:id/llm-config``        — active config, key redacted
* ``PUT    /workspaces/:id/llm-config``        — set/rotate provider + key (ADMIN+)
* ``POST   /workspaces/:id/llm-config/test``   — provider round-trip health check
* ``DELETE /workspaces/:id/llm-config``        — clear config; tier → ZERO (ADMIN+)
* ``GET    /workspaces/:id/llm-config/models`` — model catalog for the provider

The write paths recompute ``workspace_capabilities`` (M3-3) so ``GET /capabilities``
reflects the new tier, and best-effort publish a ``capability.changed`` WS event.
Keys are write-only: requests accept ``apiKey``, responses only ever return a hint.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_shared.domain.enums import Role

from suitest_api.auth.db import get_async_session
from suitest_api.deps.role import require_role
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.services.llm_config_service import (
    LLMConfigError,
    LLMConfigService,
    api_key_hint,
    provider_tier,
)

if TYPE_CHECKING:
    from suitest_db.models.llm_config import LLMConfig

router = APIRouter(prefix="/api/v1", tags=["llm"])

_ADMIN_ROLES = {Role.ADMIN, Role.OWNER}
_NO_CONFIG = "no LLM config set for this workspace"


# --- model catalog ----------------------------------------------------------
# Curated, provider-keyed. Pricing in USD per 1M tokens. Unknown providers fall
# back to echoing the configured model only.
_MODEL_CATALOG: dict[str, list[dict[str, object]]] = {
    "anthropic": [
        {
            "id": "claude-opus-4-1",
            "name": "Claude Opus 4.1",
            "contextWindow": 200000,
            "maxOutput": 32000,
        },
        {
            "id": "claude-sonnet-4-5",
            "name": "Claude Sonnet 4.5",
            "contextWindow": 200000,
            "maxOutput": 8192,
        },
        {
            "id": "claude-haiku-4-5",
            "name": "Claude Haiku 4.5",
            "contextWindow": 200000,
            "maxOutput": 8192,
        },
    ],
    "openai": [
        {"id": "gpt-4o", "name": "GPT-4o", "contextWindow": 128000, "maxOutput": 16384},
        {"id": "gpt-4o-mini", "name": "GPT-4o mini", "contextWindow": 128000, "maxOutput": 16384},
    ],
    "gemini": [
        {
            "id": "gemini-1.5-pro",
            "name": "Gemini 1.5 Pro",
            "contextWindow": 2000000,
            "maxOutput": 8192,
        },
        {
            "id": "gemini-1.5-flash",
            "name": "Gemini 1.5 Flash",
            "contextWindow": 1000000,
            "maxOutput": 8192,
        },
    ],
    "groq": [
        {
            "id": "llama-3.3-70b-versatile",
            "name": "Llama 3.3 70B",
            "contextWindow": 128000,
            "maxOutput": 32768,
        },
    ],
    "openrouter": [
        {
            "id": "anthropic/claude-sonnet-4-5",
            "name": "Claude Sonnet 4.5 (OR)",
            "contextWindow": 200000,
            "maxOutput": 8192,
        },
    ],
    "deepseek": [
        {"id": "deepseek-chat", "name": "DeepSeek Chat", "contextWindow": 64000, "maxOutput": 8192},
    ],
}


# --- schemas ----------------------------------------------------------------


class LLMConfigPublic(BaseModel):
    """Active config, key redacted to a hint."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    provider: str
    model: str
    api_key_hint: str | None = Field(default=None, alias="apiKeyHint")
    config: dict[str, object] = Field(default_factory=dict)
    is_active: bool = Field(alias="isActive")
    tier: str
    last_validated_at: str | None = Field(default=None, alias="lastValidatedAt")


class LLMConfigWriteBody(BaseModel):
    """Set/rotate provider + key. ``apiKey`` is write-only."""

    model_config = ConfigDict(populate_by_name=True)

    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=120)
    api_key: str | None = Field(default=None, alias="apiKey", repr=False)
    config: dict[str, object] = Field(default_factory=dict)


class LLMTestError(BaseModel):
    code: str
    message: str


class LLMTestResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ok: bool
    latency_ms: int = Field(default=0, alias="latencyMs")
    model_echo: str | None = Field(default=None, alias="modelEcho")
    error: LLMTestError | None = None


class LLMModelsResponse(BaseModel):
    provider: str
    models: list[dict[str, object]] = Field(default_factory=list)


def _to_public(row: LLMConfig) -> LLMConfigPublic:
    return LLMConfigPublic(
        id=row.id,
        provider=row.provider,
        model=row.model,
        api_key_hint=api_key_hint(row.api_key_encrypted),
        config=dict(row.config_json or {}),
        is_active=row.is_active,
        tier=provider_tier(row.provider).value,
        last_validated_at=row.last_validated_at.isoformat() if row.last_validated_at else None,
    )


async def _publish_capability_changed(request: Request, workspace_id: str, tier: str) -> None:
    """Best-effort ``capability.changed`` WS event. Never raises into the request."""
    redis = getattr(request.app.state, "ws_redis", None)
    publish = getattr(redis, "publish", None)
    if publish is None:
        return
    payload = json.dumps({"event": "capability.changed", "tier": tier})
    try:
        await publish(f"workspace:{workspace_id}", payload)
    except Exception:
        return


# --- routes -----------------------------------------------------------------


@router.get("/workspaces/{workspaceId}/llm-config", response_model=LLMConfigPublic)
async def get_llm_config(
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> LLMConfigPublic:
    """Return the active LLM config (key redacted). 404 when none is set."""
    row = await LLMConfigService(session, ctx).get_active()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NO_CONFIG)
    return _to_public(row)


@router.put("/workspaces/{workspaceId}/llm-config", response_model=LLMConfigPublic)
async def put_llm_config(
    body: LLMConfigWriteBody,
    request: Request,
    ctx: TenantContext = Depends(require_role(_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> LLMConfigPublic:
    """Set/rotate the provider + key, then recompute capabilities (M3-3)."""
    service = LLMConfigService(session, ctx)
    try:
        row = await service.set_config(
            provider=body.provider, model=body.model, api_key=body.api_key, config=body.config
        )
    except LLMConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    await _publish_capability_changed(request, ctx.workspace_id, provider_tier(body.provider).value)
    return _to_public(row)


@router.post("/workspaces/{workspaceId}/llm-config/test", response_model=LLMTestResult)
async def test_llm_config(
    body: LLMConfigWriteBody,
    ctx: TenantContext = Depends(require_role(_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> LLMTestResult:
    """Round-trip a 1-token completion against the (proposed) provider."""
    base_url = body.config.get("base_url")
    ok, latency, echo, code, msg = await LLMConfigService(session, ctx).test_connection(
        provider=body.provider,
        model=body.model,
        api_key=body.api_key,
        base_url=base_url if isinstance(base_url, str) else None,
    )
    if ok:
        return LLMTestResult(ok=True, latency_ms=latency, model_echo=echo)
    return LLMTestResult(
        ok=False,
        latency_ms=latency,
        error=LLMTestError(code=code or "PROVIDER_ERROR", message=msg or ""),
    )


@router.delete("/workspaces/{workspaceId}/llm-config", status_code=status.HTTP_204_NO_CONTENT)
async def delete_llm_config(
    request: Request,
    ctx: TenantContext = Depends(require_role(_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Clear the active config; tier downgrades to ZERO. 404 when none set."""
    cleared = await LLMConfigService(session, ctx).clear_config()
    if not cleared:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NO_CONFIG)
    await _publish_capability_changed(request, ctx.workspace_id, "ZERO")


@router.get("/workspaces/{workspaceId}/llm-config/models", response_model=LLMModelsResponse)
async def list_llm_models(
    provider: str,
    ctx: TenantContext = Depends(require_workspace_membership),
) -> LLMModelsResponse:
    """List the curated model catalog for ``provider`` (query param)."""
    models = _MODEL_CATALOG.get(provider.strip().lower(), [])
    return LLMModelsResponse(provider=provider, models=models)
