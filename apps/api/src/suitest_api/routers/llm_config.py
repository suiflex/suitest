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
from contextlib import contextmanager
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_core.chatgpt_oauth import ChatGptOAuthError
from suitest_core.google_oauth import GoogleOAuthError
from suitest_shared.domain.enums import Role

from suitest_api.auth.db import get_async_session
from suitest_api.deps.role import require_role
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.services.chatgpt_oauth_service import (
    ChatGptLoginError,
    ChatGptOAuthService,
    CredentialMode,
    LoginMode,
)
from suitest_api.services.google_oauth_service import (
    GoogleOAuthService,
)
from suitest_api.services.google_oauth_service import (
    LoginMode as GoogleLoginMode,
)
from suitest_api.services.llm_config_service import (
    LLMConfigError,
    LLMConfigService,
    api_key_hint,
    provider_tier,
)
from suitest_api.services.oauth_flows import OAuthLoginError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from suitest_db.models.llm_config import LLMConfig

router = APIRouter(prefix="/api/v1", tags=["llm"])

_ADMIN_ROLES = {Role.ADMIN, Role.OWNER}
_NO_CONFIG = "no LLM config set for this workspace"


# --- model catalog ----------------------------------------------------------
# Curated, provider-keyed. Pricing in USD per 1M tokens. Unknown providers fall
# back to echoing the configured model only.
_MODEL_CATALOG: dict[str, list[dict[str, object]]] = {
    # Vertex's OpenAI-compatible surface namespaces the model by publisher, so
    # these ids carry the ``google/`` prefix the endpoint expects.
    "google-vertex": [
        {
            "id": "google/gemini-2.5-pro",
            "name": "Gemini 2.5 Pro",
            "contextWindow": 1048576,
            "maxOutput": 65536,
        },
        {
            "id": "google/gemini-2.5-flash",
            "name": "Gemini 2.5 Flash",
            "contextWindow": 1048576,
            "maxOutput": 65536,
        },
    ],
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
    #: ``api_key`` or ``oauth`` — how this config authenticates.
    auth_method: str = Field(alias="authMethod")
    #: Signed-in ChatGPT account, when the config came from an OAuth login.
    oauth_account: str | None = Field(default=None, alias="oauthAccount")


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


class LoginStartBody(BaseModel):
    """``auto`` resolves to the browser redirect on localhost, device code elsewhere."""

    mode: LoginMode = "auto"


class LoginStart(BaseModel):
    """What the UI has to show: a code to type, or a URL to open."""

    model_config = ConfigDict(populate_by_name=True)

    flow_id: str = Field(alias="flowId")
    mode: str
    verification_url: str | None = Field(default=None, alias="verificationUrl")
    user_code: str | None = Field(default=None, alias="userCode")
    authorize_url: str | None = Field(default=None, alias="authorizeUrl")
    #: Seconds the UI should wait between polls.
    interval_s: int = Field(default=5, alias="intervalS")


class LoginStatus(BaseModel):
    """``pending`` until the user approves, then ``ready`` (or ``error``)."""

    status: str
    account: str | None = None
    code: str | None = None
    message: str | None = None


class GoogleLoginStartBody(BaseModel):
    """``auto`` resolves to the loopback redirect on localhost, paste elsewhere."""

    mode: GoogleLoginMode = "auto"


class GoogleLoginStatus(BaseModel):
    """``pending`` until the redirect lands, then ``ready`` (or ``error``)."""

    model_config = ConfigDict(populate_by_name=True)

    status: str
    email: str | None = None
    has_refresh_token: bool = Field(default=False, alias="hasRefreshToken")
    code: str | None = None
    message: str | None = None


class GoogleCallbackBody(BaseModel):
    """The URL the user copied out of the address bar in ``paste`` mode."""

    model_config = ConfigDict(populate_by_name=True)

    callback_url: str = Field(alias="callbackUrl", min_length=1, max_length=4096)


class GoogleProjectOut(BaseModel):
    """One GCP project the signed-in user can pick."""

    model_config = ConfigDict(populate_by_name=True)

    project_id: str = Field(alias="projectId")
    name: str


class GoogleProjectsResponse(BaseModel):
    """Empty when the list could not be read — the UI then asks for the id."""

    projects: list[GoogleProjectOut] = Field(default_factory=list)


class GoogleLoginFinishBody(BaseModel):
    """Vertex needs a project and region: they are what its endpoint is built from."""

    model_config = ConfigDict(populate_by_name=True)

    model: str = Field(min_length=1, max_length=120)
    project: str = Field(min_length=1, max_length=120, alias="gcpProject")
    location: str = Field(min_length=1, max_length=64, alias="gcpLocation")


class LoginFinishBody(BaseModel):
    """``api_key`` exchanges for a platform key; ``subscription`` keeps the tokens."""

    model_config = ConfigDict(populate_by_name=True)

    credential_mode: CredentialMode = Field(alias="credentialMode")
    model: str = Field(min_length=1, max_length=120)


@contextmanager
def _login_errors() -> Iterator[None]:
    """Map a login/protocol failure onto 422 with its own error code."""
    try:
        yield
    except (ChatGptLoginError, ChatGptOAuthError, OAuthLoginError, GoogleOAuthError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


def _to_public(row: LLMConfig) -> LLMConfigPublic:
    tokens = row.oauth_tokens
    return LLMConfigPublic(
        id=row.id,
        provider=row.provider,
        model=row.model,
        api_key_hint=api_key_hint(row.api_key_encrypted),
        config=dict(row.config_json or {}),
        is_active=row.is_active,
        tier=provider_tier(row.provider).value,
        last_validated_at=row.last_validated_at.isoformat() if row.last_validated_at else None,
        auth_method=row.auth_method,
        oauth_account=tokens.email if tokens is not None else None,
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


@router.post("/workspaces/{workspaceId}/llm-config/chatgpt/login", response_model=LoginStart)
async def start_chatgpt_login(
    body: LoginStartBody,
    request: Request,
    ctx: TenantContext = Depends(require_role(_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> LoginStart:
    """Begin a Sign in with ChatGPT flow and return what to show the user."""
    service = ChatGptOAuthService(session, ctx)
    with _login_errors():
        started = await service.start(mode=body.mode, request_host=request.url.hostname or "")
    return LoginStart.model_validate(started)


@router.get(
    "/workspaces/{workspaceId}/llm-config/chatgpt/login/{flowId}", response_model=LoginStatus
)
async def poll_chatgpt_login(
    flowId: str,
    ctx: TenantContext = Depends(require_role(_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> LoginStatus:
    """Advance the flow one step: ``pending`` until the user approves it."""
    service = ChatGptOAuthService(session, ctx)
    with _login_errors():
        state = await service.poll(flowId)
    return LoginStatus.model_validate(state)


@router.post(
    "/workspaces/{workspaceId}/llm-config/chatgpt/login/{flowId}/finish",
    response_model=LLMConfigPublic,
)
async def finish_chatgpt_login(
    flowId: str,
    body: LoginFinishBody,
    request: Request,
    ctx: TenantContext = Depends(require_role(_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> LLMConfigPublic:
    """Store the approved sign-in as the active config, then refresh the tier."""
    service = ChatGptOAuthService(session, ctx)
    with _login_errors():
        row = await service.finish(flowId, credential_mode=body.credential_mode, model=body.model)
    await _publish_capability_changed(request, ctx.workspace_id, provider_tier(row.provider).value)
    return _to_public(row)


@router.delete(
    "/workspaces/{workspaceId}/llm-config/chatgpt/login/{flowId}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_chatgpt_login(
    flowId: str,
    ctx: TenantContext = Depends(require_role(_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Abandon a flow and release its callback listener."""
    ChatGptOAuthService(session, ctx).cancel(flowId)


@router.post("/workspaces/{workspaceId}/llm-config/google/login", response_model=LoginStart)
async def start_google_login(
    body: GoogleLoginStartBody,
    request: Request,
    ctx: TenantContext = Depends(require_role(_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> LoginStart:
    """Begin a Sign in with Google flow and return the URL to open."""
    service = GoogleOAuthService(session, ctx)
    with _login_errors():
        started = await service.start(mode=body.mode, request_host=request.url.hostname or "")
    return LoginStart.model_validate(started)


@router.get(
    "/workspaces/{workspaceId}/llm-config/google/login/{flowId}",
    response_model=GoogleLoginStatus,
)
async def poll_google_login(
    flowId: str,
    ctx: TenantContext = Depends(require_role(_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> GoogleLoginStatus:
    """Advance the flow one step: ``pending`` until the redirect lands."""
    service = GoogleOAuthService(session, ctx)
    with _login_errors():
        state = await service.poll(flowId)
    return GoogleLoginStatus.model_validate(state)


@router.post(
    "/workspaces/{workspaceId}/llm-config/google/login/{flowId}/callback",
    response_model=GoogleLoginStatus,
)
async def submit_google_callback(
    flowId: str,
    body: GoogleCallbackBody,
    ctx: TenantContext = Depends(require_role(_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> GoogleLoginStatus:
    """Accept the pasted callback URL — the fallback where loopback cannot reach."""
    service = GoogleOAuthService(session, ctx)
    with _login_errors():
        state = await service.submit_callback_url(flowId, url=body.callback_url)
    return GoogleLoginStatus.model_validate(state)


@router.get(
    "/workspaces/{workspaceId}/llm-config/google/login/{flowId}/projects",
    response_model=GoogleProjectsResponse,
)
async def list_google_projects(
    flowId: str,
    ctx: TenantContext = Depends(require_role(_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> GoogleProjectsResponse:
    """The GCP projects the approved sign-in can see, for the project picker."""
    service = GoogleOAuthService(session, ctx)
    with _login_errors():
        found = await service.projects(flowId)
    return GoogleProjectsResponse(
        projects=[GoogleProjectOut(project_id=p.project_id, name=p.name) for p in found]
    )


@router.post(
    "/workspaces/{workspaceId}/llm-config/google/login/{flowId}/finish",
    response_model=LLMConfigPublic,
)
async def finish_google_login(
    flowId: str,
    body: GoogleLoginFinishBody,
    request: Request,
    ctx: TenantContext = Depends(require_role(_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> LLMConfigPublic:
    """Store the approved sign-in as the active config, then refresh the tier."""
    service = GoogleOAuthService(session, ctx)
    with _login_errors():
        row = await service.finish(
            flowId, model=body.model, project=body.project, location=body.location
        )
    await _publish_capability_changed(request, ctx.workspace_id, provider_tier(row.provider).value)
    return _to_public(row)


@router.delete(
    "/workspaces/{workspaceId}/llm-config/google/login/{flowId}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_google_login(
    flowId: str,
    ctx: TenantContext = Depends(require_role(_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Abandon a flow and release its callback listener."""
    GoogleOAuthService(session, ctx).cancel(flowId)


@router.get("/workspaces/{workspaceId}/llm-config/models", response_model=LLMModelsResponse)
async def list_llm_models(
    provider: str,
    ctx: TenantContext = Depends(require_workspace_membership),
) -> LLMModelsResponse:
    """List the curated model catalog for ``provider`` (query param)."""
    models = _MODEL_CATALOG.get(provider.strip().lower(), [])
    return LLMModelsResponse(provider=provider, models=models)
