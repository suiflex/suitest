"""Workspace LLM configuration and validation service.

Owns the workspace BYO-LLM lifecycle: validate provider/key, persist the active
``LLMConfig`` (key AES-GCM encrypted), test the connection through the provider
layer, and recompute the materialised ``WorkspaceCapability`` row whenever LLM
readiness changes.

Never imports LiteLLM directly: connection tests go through the stored workspace
configuration and ``suitest_agent.providers``.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from suitest_agent.providers.base import ChatMessage, ModelCall, ProviderError
from suitest_core.capabilities import (
    AutonomyLevel as CoreAutonomy,
)
from suitest_core.capabilities import (
    compute_autonomy,
    compute_features,
    resolve_embeddings,
)
from suitest_core.code_assist import (
    CODE_ASSIST_VARIANTS,
)
from suitest_core.llm_credentials import (
    CHATGPT_PROVIDER,
    GOOGLE_VERTEX_PROVIDER,
    CredentialError,
)
from suitest_core.oauth import StoredOAuthTokens
from suitest_db.audit import write_audit
from suitest_db.models.llm_config import AUTH_METHOD_API_KEY, AUTH_METHOD_OAUTH
from suitest_db.repositories.llm_configs import LLMConfigCreate, LLMConfigRepo, LLMConfigUpdate
from suitest_db.repositories.workspace_capabilities import WorkspaceCapabilityRepo
from suitest_shared.domain.enums import AutonomyLevel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from suitest_db.models.llm_config import LLMConfig

    from suitest_api.deps.scope import TenantContext

_BASE_URL_REQUIRED_PROVIDERS = frozenset({"ollama", "llamacpp", "vllm", "lmstudio"})
_SUPPORTED_PROVIDERS = frozenset(
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
        CHATGPT_PROVIDER,
        GOOGLE_VERTEX_PROVIDER,
        *CODE_ASSIST_VARIANTS,
    }
)
# Providers that authenticate without a pasted API key (IAM, OAuth, or mock).
_KEYLESS = frozenset(
    {"bedrock", "vertex", "mock", CHATGPT_PROVIDER, GOOGLE_VERTEX_PROVIDER, *CODE_ASSIST_VARIANTS}
)
# ``custom`` = any hosted OpenAI-compatible endpoint (gateway/router/proxy) the
# user points at via base URL. Its API key is optional (gateway-dependent);
# base URL required — there is no default endpoint to fall back to.
_CUSTOM = "custom"


class LLMConfigError(Exception):
    """Validation failure on an LLM config write. ``code`` is the API error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def known_providers() -> frozenset[str]:
    return _BASE_URL_REQUIRED_PROVIDERS | _SUPPORTED_PROVIDERS | {_CUSTOM}


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
        self,
        provider: str,
        model: str,
        api_key: str | None,
        base_url: str | None,
        *,
        auth_method: str = AUTH_METHOD_API_KEY,
        oauth_tokens: StoredOAuthTokens | None = None,
        config: dict[str, object] | None = None,
    ) -> None:
        p = provider.strip().lower()
        if p not in known_providers():
            raise LLMConfigError("UNKNOWN_PROVIDER", f"unsupported provider {provider!r}")
        if not model.strip():
            raise LLMConfigError("INVALID_MODEL", "model is required")
        # ``chatgpt`` carries a token set, never a key — there is nothing else to
        # authenticate it with, so a config without tokens could never run.
        if p == CHATGPT_PROVIDER and (auth_method != AUTH_METHOD_OAUTH or oauth_tokens is None):
            raise LLMConfigError(
                "MISSING_OAUTH_TOKENS",
                f"provider {CHATGPT_PROVIDER} requires signing in with ChatGPT",
            )
        # Vertex-as-the-signed-in-user needs both halves: the tokens to
        # authenticate, and the endpoint that names the project and region they
        # authenticate against. Neither is recoverable from the other.
        if p == GOOGLE_VERTEX_PROVIDER:
            if auth_method != AUTH_METHOD_OAUTH or oauth_tokens is None:
                raise LLMConfigError(
                    "MISSING_OAUTH_TOKENS",
                    f"provider {GOOGLE_VERTEX_PROVIDER} requires signing in with Google",
                )
            if not base_url:
                raise LLMConfigError(
                    "MISSING_BASE_URL",
                    f"provider {GOOGLE_VERTEX_PROVIDER} requires config.base_url",
                )
        # A Code Assist config carries the project its sign-in discovered; the
        # request envelope cannot be built without it.
        if p in CODE_ASSIST_VARIANTS:
            if auth_method != AUTH_METHOD_OAUTH or oauth_tokens is None:
                raise LLMConfigError(
                    "MISSING_OAUTH_TOKENS", f"provider {p} requires signing in with Google"
                )
            if not (config or {}).get("project"):
                raise LLMConfigError("MISSING_PROJECT", f"provider {p} requires config.project")
        if p in _BASE_URL_REQUIRED_PROVIDERS and not base_url:
            raise LLMConfigError("MISSING_BASE_URL", f"provider {p} requires config.base_url")
        if p == _CUSTOM and not base_url:
            raise LLMConfigError("MISSING_BASE_URL", "custom provider requires config.base_url")
        if p in _SUPPORTED_PROVIDERS and p not in _KEYLESS and not api_key:
            raise LLMConfigError("MISSING_API_KEY", f"provider {p} requires an api key")

    async def set_config(
        self,
        *,
        provider: str,
        model: str,
        api_key: str | None,
        config: dict[str, object],
        auth_method: str = AUTH_METHOD_API_KEY,
        oauth_tokens: StoredOAuthTokens | None = None,
        audit_action: str = "llm_config.set",
    ) -> LLMConfig:
        """Create/rotate the active config, then recompute capabilities (M3-3).

        ``auth_method`` / ``oauth_tokens`` carry a Sign in with ChatGPT session
        (see :mod:`suitest_api.services.chatgpt_oauth_service`); left at their
        defaults the write behaves exactly like a pasted-key rotation.
        """
        base_url = config.get("base_url") if isinstance(config.get("base_url"), str) else None
        self._validate(
            provider,
            model,
            api_key,
            base_url if isinstance(base_url, str) else None,
            auth_method=auth_method,
            oauth_tokens=oauth_tokens,
            config=config,
        )
        # Whichever credential the caller brought, the other one must not linger.
        tokens_json = oauth_tokens.model_dump_json() if oauth_tokens is not None else None

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
                    auth_method=auth_method,
                    oauth_tokens_encrypted=tokens_json,
                ),
            )
            row = existing
            # ``AsyncRepository.update`` skips ``None`` values, so the credential
            # the caller did not bring has to be cleared by hand — otherwise
            # switching auth method leaves the previous one encrypted in the row
            # and the provider layer could still pick it up.
            row.api_key_encrypted = api_key
            row.oauth_tokens_encrypted = tokens_json
            row.last_validated_at = None
        else:
            row = await self._llm.create(
                LLMConfigCreate(
                    workspace_id=self._ctx.workspace_id,
                    provider=provider,
                    model=model,
                    api_key_encrypted=api_key,
                    config_json=config,
                    is_active=True,
                    auth_method=auth_method,
                    oauth_tokens_encrypted=tokens_json,
                )
            )
        await self._refresh_capability(llm_ready=False)
        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action=audit_action,
            resource_type="llm_config",
            resource_id=row.id,
            metadata={"provider": provider, "model": model, "auth_method": auth_method},
        )
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def clear_config(self) -> bool:
        """Deactivate the active config. Returns whether one existed."""
        existing = await self.get_active()
        if existing is None:
            return False
        await self._llm.update(existing.id, LLMConfigUpdate(is_active=False))
        await self._refresh_capability(llm_ready=False)
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

    async def _refresh_capability(self, *, llm_ready: bool) -> None:
        """Recompute feature and autonomy state after an LLM status change.

        Preserves non-flag entries in ``features_json`` (notably the M2-9
        ``routing_overrides``) while overwriting the boolean feature flags. An
        unavailable LLM forces autonomy back to MANUAL.
        """
        embeddings = resolve_embeddings()
        flags = compute_features(llm_ready, embeddings)
        current = await self._caps.get(self._ctx.workspace_id)
        merged: dict[str, object] = dict(current.features_json) if current else {}
        merged.update(flags)

        if not llm_ready:
            autonomy = AutonomyLevel.MANUAL
        elif current is not None and current.autonomy_level is not AutonomyLevel.MANUAL:
            autonomy = current.autonomy_level
        else:
            default = compute_autonomy(True).default
            autonomy = AutonomyLevel(CoreAutonomy(default).value)

        await self._caps.upsert(
            self._ctx.workspace_id,
            autonomy=autonomy,
            features=merged,
        )

    async def test_connection(self) -> tuple[bool, int, str, str | None, str | None]:
        """Validate the saved active config with a 1-token completion."""
        active = await self.get_active()
        if active is None:
            return (
                False,
                0,
                "",
                "CONFIG_NOT_SAVED",
                "Save the LLM configuration before testing it.",
            )

        from suitest_api.services.llm_credentials import provider_for_config

        start = time.perf_counter()
        try:
            impl = await provider_for_config(self._session, active)
        except CredentialError as exc:
            latency = int((time.perf_counter() - start) * 1000)
            return (False, latency, "", exc.code, exc.message)
        call = ModelCall(
            model=active.model,
            messages=[ChatMessage(role="user", content="ping")],
            max_tokens=1,
            temperature=0.0,
        )
        try:
            result = await impl.complete(call)
        except ProviderError as exc:
            latency = int((time.perf_counter() - start) * 1000)
            code = "PROVIDER_AUTH" if "auth" in exc.message.lower() else exc.code
            return (False, latency, "", code, exc.message)
        latency = int((time.perf_counter() - start) * 1000)
        await self._llm.update(active.id, LLMConfigUpdate(last_validated_at=datetime.now(tz=UTC)))
        await self._refresh_capability(llm_ready=True)
        await self._session.commit()
        return (True, latency, result.model, None, None)
