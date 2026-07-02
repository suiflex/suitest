"""LLM config service (M3-2 + M3-3).

Owns the workspace BYO-LLM lifecycle: validate provider/key, persist the active
``LLMConfig`` (key AES-GCM encrypted), test the connection through the provider
layer, and — the M3-3 half — recompute the materialised ``WorkspaceCapability``
row so ``GET /capabilities`` flips tier the moment a key is set or cleared.

Never imports LiteLLM directly: connection tests go through
``suitest_agent.providers`` so ZERO tier and the test suite stay import-clean.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from suitest_agent.providers.base import ChatMessage, ModelCall, ProviderError
from suitest_agent.providers.litellm_router import get_provider
from suitest_core.capabilities import (
    AutonomyLevel as CoreAutonomy,
)
from suitest_core.capabilities import (
    Tier as CoreTier,
)
from suitest_core.capabilities import (
    compute_autonomy,
    compute_features,
    resolve_embeddings,
)
from suitest_db.audit import write_audit
from suitest_db.repositories.llm_configs import LLMConfigCreate, LLMConfigRepo, LLMConfigUpdate
from suitest_db.repositories.workspace_capabilities import WorkspaceCapabilityRepo
from suitest_shared.domain.enums import AutonomyLevel, Tier

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from suitest_db.models.llm_config import LLMConfig

    from suitest_api.deps.scope import TenantContext

_LOCAL_PROVIDERS = frozenset({"ollama", "llamacpp", "vllm", "lmstudio"})
_CLOUD_PROVIDERS = frozenset(
    {
        "anthropic",
        "openai",
        "gemini",
        "groq",
        "openrouter",
        "azure",
        "bedrock",
        "vertex",
        "deepseek",
        "mock",
    }
)
# CLOUD providers that authenticate without SUITEST_LLM_API_KEY (IAM / canned creds).
_KEYLESS = frozenset({"bedrock", "vertex", "mock"})
# ``custom`` = any hosted OpenAI-compatible endpoint (gateway/router/proxy) the
# user points at via base URL. CLOUD tier; API key optional (gateway-dependent);
# base URL required — there is no default endpoint to fall back to.
_CUSTOM = "custom"


class LLMConfigError(Exception):
    """Validation failure on an LLM config write. ``code`` is the API error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def known_providers() -> frozenset[str]:
    return _LOCAL_PROVIDERS | _CLOUD_PROVIDERS | {_CUSTOM}


def provider_tier(provider: str) -> CoreTier:
    """Map a provider key to the resolved :class:`Tier` (DATA_MODEL §4.1)."""
    p = provider.strip().lower()
    if p in {"", "none", "disabled"}:
        return CoreTier.ZERO
    if p in _LOCAL_PROVIDERS:
        return CoreTier.LOCAL
    return CoreTier.CLOUD


def api_key_hint(plaintext: str | None) -> str | None:
    """Render a redacted key hint (``sk-a…last4``). ``None`` when no key stored."""
    if not plaintext:
        return None
    if len(plaintext) <= 8:
        return "…" + plaintext[-2:]
    return f"{plaintext[:4]}…{plaintext[-4:]}"


class LLMConfigService:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._session = session
        self._ctx = ctx
        self._llm = LLMConfigRepo(session)
        self._caps = WorkspaceCapabilityRepo(session)

    async def get_active(self) -> LLMConfig | None:
        return await self._llm.get_active(self._ctx.workspace_id)

    def _validate(
        self, provider: str, model: str, api_key: str | None, base_url: str | None
    ) -> None:
        p = provider.strip().lower()
        if p not in known_providers():
            raise LLMConfigError("UNKNOWN_PROVIDER", f"unsupported provider {provider!r}")
        if not model.strip():
            raise LLMConfigError("INVALID_MODEL", "model is required")
        if p in _LOCAL_PROVIDERS and not base_url:
            raise LLMConfigError("MISSING_BASE_URL", f"LOCAL provider {p} requires config.base_url")
        if p == _CUSTOM and not base_url:
            raise LLMConfigError(
                "MISSING_BASE_URL", "custom provider requires config.base_url"
            )
        if p in _CLOUD_PROVIDERS and p not in _KEYLESS and not api_key:
            raise LLMConfigError("MISSING_API_KEY", f"CLOUD provider {p} requires an api key")

    async def set_config(
        self,
        *,
        provider: str,
        model: str,
        api_key: str | None,
        config: dict[str, object],
    ) -> LLMConfig:
        """Create/rotate the active config, then recompute capabilities (M3-3)."""
        base_url = config.get("base_url") if isinstance(config.get("base_url"), str) else None
        self._validate(provider, model, api_key, base_url if isinstance(base_url, str) else None)

        existing = await self.get_active()
        if existing is not None:
            await self._llm.update(
                existing.id,
                LLMConfigUpdate(
                    provider=provider,
                    model=model,
                    api_key_encrypted=api_key,
                    config_json=config,
                    is_active=True,
                ),
            )
            row = existing
        else:
            row = await self._llm.create(
                LLMConfigCreate(
                    workspace_id=self._ctx.workspace_id,
                    provider=provider,
                    model=model,
                    api_key_encrypted=api_key,
                    config_json=config,
                    is_active=True,
                )
            )
        await self._refresh_capability(provider_tier(provider))
        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="llm_config.set",
            resource_type="llm_config",
            resource_id=row.id,
            metadata={"provider": provider, "model": model},
        )
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def clear_config(self) -> bool:
        """Deactivate the active config; tier returns to env/ZERO. Returns found."""
        existing = await self.get_active()
        if existing is None:
            return False
        await self._llm.update(existing.id, LLMConfigUpdate(is_active=False))
        await self._refresh_capability(CoreTier.ZERO)
        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="llm_config.clear",
            resource_type="llm_config",
            resource_id=existing.id,
            metadata={"provider": existing.provider},
        )
        await self._session.commit()
        return True

    async def _refresh_capability(self, tier: CoreTier) -> None:
        """Recompute the materialised ``WorkspaceCapability`` for ``tier`` (M3-3).

        Preserves non-flag entries in ``features_json`` (notably the M2-9
        ``routing_overrides``) while overwriting the boolean feature flags. ZERO
        forces autonomy back to MANUAL.
        """
        embeddings = resolve_embeddings()
        flags = compute_features(tier, embeddings)
        current = await self._caps.get(self._ctx.workspace_id)
        merged: dict[str, object] = dict(current.features_json) if current else {}
        merged.update(flags)

        if tier is CoreTier.ZERO:
            autonomy = AutonomyLevel.MANUAL
        elif current is not None and current.autonomy_level is not AutonomyLevel.MANUAL:
            autonomy = current.autonomy_level
        else:
            default = compute_autonomy(tier).default
            autonomy = AutonomyLevel(CoreAutonomy(default).value)

        await self._caps.upsert(
            self._ctx.workspace_id,
            tier=Tier(tier.value),
            autonomy=autonomy,
            features=merged,
        )

    async def test_connection(
        self, *, provider: str, model: str, api_key: str | None, base_url: str | None
    ) -> tuple[bool, int, str, str | None, str | None]:
        """Round-trip a 1-token completion. Returns (ok, latency_ms, echo, code, msg)."""
        impl = get_provider(provider, api_key=api_key, base_url=base_url)
        call = ModelCall(
            model=model,
            messages=[ChatMessage(role="user", content="ping")],
            max_tokens=1,
            temperature=0.0,
        )
        start = time.perf_counter()
        try:
            result = await impl.complete(call)
        except ProviderError as exc:
            latency = int((time.perf_counter() - start) * 1000)
            code = "PROVIDER_AUTH" if "auth" in exc.message.lower() else exc.code
            return (False, latency, "", code, exc.message)
        latency = int((time.perf_counter() - start) * 1000)
        active = await self.get_active()
        if active is not None:
            await self._llm.update(
                active.id, LLMConfigUpdate(last_validated_at=datetime.now(tz=UTC))
            )
            await self._session.commit()
        return (True, latency, result.model, None, None)
