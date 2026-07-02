"""LiteLLM-backed provider — 100+ backends behind one client (M3-1).

``litellm`` is imported lazily (inside methods) so importing this module costs
nothing at ZERO tier and the test suite never needs the dependency. The real
provider is only constructed when a workspace has an active CLOUD/LOCAL
``LLMConfig`` and a non-``mock`` provider.

Provider-key → LiteLLM model-id mapping follows docs/AI_AGENT.md §3. Seed support
is provider-dependent; LiteLLM ``drop_params=True`` silently drops unsupported
params (e.g. ``seed`` for anthropic/gemini), so callers always pass the seed and
let LiteLLM normalize.

M7-2 auto-downgrade: if a workspace has ``LLMConfig.config_json.auto_downgrade_threshold_usd``
set and today's spend exceeds it, :meth:`LiteLLMProvider.complete` transparently
switches to a cheaper model alias before calling the backend.  The actual model
used is recorded in the returned :class:`CompletionResult`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from suitest_agent.providers.base import (
    CompletionResult,
    LLMProvider,
    ModelCall,
    ProviderError,
    StreamChunk,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from suitest_agent.providers.mock import MockProvider

_log = logging.getLogger(__name__)


class _DbSessionFactory(Protocol):
    """Minimal protocol for an async session factory (async context manager factory).

    Typed as a Protocol so ``suitest_agent`` never imports SQLAlchemy directly —
    the concrete implementation (``async_sessionmaker[AsyncSession]``) is only
    constructed in the API layer which already has the DB dependency.
    """

    def __call__(self) -> object:
        """Return an async context manager that yields an AsyncSession."""
        ...


# Provider keys whose LiteLLM model id is ``<prefix>/<model>``.
_PREFIX: dict[str, str] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "gemini": "gemini",
    "groq": "groq",
    "openrouter": "openrouter",
    "azure": "azure",
    "bedrock": "bedrock",
    "vertex": "vertex_ai",
    "deepseek": "deepseek",
    "ollama": "ollama",
}
# OpenAI-compatible shims talk OpenAI protocol against a custom api_base:
# LOCAL servers (llamacpp/vllm/lmstudio) plus ``custom`` — any hosted
# OpenAI-compatible gateway/router (e.g. LiteLLM proxy, 9router) the user
# points at via base URL + API key. ``custom`` resolves to CLOUD tier.
_OPENAI_SHIM = frozenset({"llamacpp", "vllm", "lmstudio", "custom"})

# Seed support per docs/AI_AGENT.md §13.1 — drives the replay determinism label.
_DETERMINISTIC_SEED = frozenset({"openai", "groq", "vllm", "llamacpp", "mock"})

# M4-1: default base URLs + example models for each validated LOCAL provider.
# Reference defaults the Settings UI / CLI can pre-fill; a workspace still sets
# its own ``config.base_url``. Validated against Ollama, llama.cpp server, vLLM
# (OpenAI server), LM Studio — see scripts/validate_local_tier.py.
LOCAL_TIER_DEFAULTS: dict[str, dict[str, str]] = {
    "ollama": {"base_url": "http://localhost:11434", "example_model": "llama3.1"},
    "llamacpp": {"base_url": "http://localhost:8080/v1", "example_model": "local-model"},
    "vllm": {"base_url": "http://localhost:8000/v1", "example_model": "Qwen/Qwen2.5-7B-Instruct"},
    "lmstudio": {"base_url": "http://localhost:1234/v1", "example_model": "local-model"},
}


def requires_base_url(provider: str) -> bool:
    """True for LOCAL providers — no public endpoint, so a base URL is required."""
    p = provider.strip().lower()
    return p == "ollama" or p in _OPENAI_SHIM


def seed_determinism(provider: str) -> str:
    """Return ``"deterministic"`` or ``"best_effort"`` for replay metadata (§13.1)."""
    return "deterministic" if provider.strip().lower() in _DETERMINISTIC_SEED else "best_effort"


def to_litellm_model(provider: str, model: str) -> str:
    """Map a workspace provider key + bare model name to a LiteLLM model id."""
    p = provider.strip().lower()
    if p in _OPENAI_SHIM:
        return f"openai/{model}"
    prefix = _PREFIX.get(p)
    if prefix is None:
        raise ProviderError("UNKNOWN_PROVIDER", f"No LiteLLM mapping for provider {provider!r}")
    return f"{prefix}/{model}"


class LiteLLMProvider:
    """Real provider. Constructed from an active workspace ``LLMConfig``.

    Optional M7-2 fields:
      ``workspace_id`` + ``db_session_factory`` — when both are provided the
      provider will query today's spend before each ``complete()`` call and
      auto-downgrade the model if spend exceeds ``auto_downgrade_threshold_usd``
      from the LLMConfig.  Both fields default to ``None`` (feature disabled)
      so all existing call sites are unaffected.
    """

    def __init__(
        self,
        *,
        provider: str,
        api_key: str | None = None,
        base_url: str | None = None,
        workspace_id: str | None = None,
        db_session_factory: _DbSessionFactory | None = None,
    ) -> None:
        self.name = provider.strip().lower()
        self._api_key = api_key
        self._base_url = base_url
        self._workspace_id = workspace_id
        self._db_session_factory = db_session_factory
        self._configured = False

    def _ensure_configured(self) -> None:
        """Set LiteLLM module globals once. Lazy ``import litellm`` lives here."""
        if self._configured:
            return
        import litellm

        litellm.drop_params = True
        self._configured = True

    def _kwargs(self, call: ModelCall) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "model": to_litellm_model(self.name, call.model),
            "messages": [m.model_dump() for m in call.messages],
            "temperature": call.temperature,
            "max_tokens": call.max_tokens,
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._base_url:
            kwargs["api_base"] = self._base_url
        if call.tools:
            kwargs["tools"] = call.tools
        if call.seed is not None:
            kwargs["seed"] = call.seed
        return kwargs

    async def _maybe_downgrade_model(self, model: str) -> str:
        """Return a cheaper model if M7-2 auto-downgrade is triggered, else unchanged.

        Only active when both ``workspace_id`` and ``db_session_factory`` are set.
        Failures are logged and swallowed so a DB error never blocks an LLM call.
        """
        if self._workspace_id is None or self._db_session_factory is None:
            return model
        try:
            # Late import to keep suitest_agent independent of DB/API at ZERO tier.
            from suitest_api.services.cost_service import CostService, get_cheaper_model

            factory = self._db_session_factory
            ctx = factory()  # returns async context manager
            async with ctx as session:  # type: ignore[attr-defined]
                svc = CostService(session, self._workspace_id)
                threshold = await svc.auto_downgrade_threshold()
                if threshold is None:
                    return model
                today_spend = await svc.workspace_today_spend()
                cheaper = get_cheaper_model(model, today_spend, threshold)
                return cheaper if cheaper is not None else model
        except Exception as exc:
            _log.warning("auto_downgrade check failed (using original model): %s", exc)
            return model

    async def complete(self, call: ModelCall) -> CompletionResult:
        self._ensure_configured()
        import litellm

        # M7-2: check for auto-downgrade before sending the request.
        effective_model = await self._maybe_downgrade_model(call.model)
        effective_call = (
            call
            if effective_model == call.model
            else call.model_copy(update={"model": effective_model})
        )

        try:
            resp = await litellm.acompletion(**self._kwargs(effective_call))
        except Exception as exc:
            raise ProviderError("PROVIDER_CALL_FAILED", str(exc)) from exc
        return self._normalize(resp, effective_call)

    def _normalize(self, resp: object, call: ModelCall) -> CompletionResult:
        import litellm

        choices = getattr(resp, "choices", [])
        choice = choices[0]
        message = choice.message
        content = message.content or ""
        usage = getattr(resp, "usage", None)
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
        try:
            cost = float(litellm.completion_cost(completion_response=resp) or 0.0)
        except Exception:
            cost = 0.0
        raw_tool_calls = getattr(message, "tool_calls", None) or []
        tool_calls: list[dict[str, object]] = [
            {
                "id": getattr(tc, "id", ""),
                "name": getattr(getattr(tc, "function", None), "name", ""),
                "arguments": getattr(getattr(tc, "function", None), "arguments", ""),
            }
            for tc in raw_tool_calls
        ]
        return CompletionResult(
            content=content,
            model=to_litellm_model(self.name, call.model),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            finish_reason=str(getattr(choice, "finish_reason", "stop") or "stop"),
            tool_calls=tool_calls,
        )

    async def stream_complete(self, call: ModelCall) -> AsyncIterator[StreamChunk]:
        self._ensure_configured()
        import litellm

        try:
            stream = await litellm.acompletion(**self._kwargs(call), stream=True)
        except Exception as exc:
            raise ProviderError("PROVIDER_CALL_FAILED", str(exc)) from exc
        async for part in stream:
            delta = getattr(part, "choices", [])[0].delta
            piece = getattr(delta, "content", None)
            if piece:
                yield StreamChunk(delta=piece)
        yield StreamChunk(done=True)

    def cost_usd(self, result: CompletionResult) -> float:
        return result.cost_usd


def get_provider(
    provider: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    workspace_id: str | None = None,
    db_session_factory: _DbSessionFactory | None = None,
) -> LLMProvider:
    """Factory: return a :class:`MockProvider` for ``mock``, else LiteLLM-backed.

    This is the single seam the API/graph layers use; they never branch on the
    provider key themselves.

    Args:
        provider: LiteLLM provider key (e.g. ``"anthropic"``, ``"openai"``).
        api_key: Decrypted API key, or ``None`` for local providers.
        base_url: Custom base URL for LOCAL-tier providers.
        workspace_id: Workspace scope for M7-2 auto-downgrade (optional).
        db_session_factory: Async session factory for M7-2 spend queries
            (optional).  When omitted, auto-downgrade is disabled.
    """
    if provider.strip().lower() == "mock":
        from suitest_agent.providers.mock import MockProvider

        mock: MockProvider = MockProvider()
        return mock
    return LiteLLMProvider(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        workspace_id=workspace_id,
        db_session_factory=db_session_factory,
    )
