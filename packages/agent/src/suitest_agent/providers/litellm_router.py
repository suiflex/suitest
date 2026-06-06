"""LiteLLM-backed provider — 100+ backends behind one client (M3-1).

``litellm`` is imported lazily (inside methods) so importing this module costs
nothing at ZERO tier and the test suite never needs the dependency. The real
provider is only constructed when a workspace has an active CLOUD/LOCAL
``LLMConfig`` and a non-``mock`` provider.

Provider-key → LiteLLM model-id mapping follows docs/AI_AGENT.md §3. Seed support
is provider-dependent; LiteLLM ``drop_params=True`` silently drops unsupported
params (e.g. ``seed`` for anthropic/gemini), so callers always pass the seed and
let LiteLLM normalize.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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
# LOCAL OpenAI-compatible shims (llamacpp/vllm/lmstudio) talk OpenAI protocol
# against a custom api_base.
_OPENAI_SHIM = frozenset({"llamacpp", "vllm", "lmstudio"})

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
    """Real provider. Constructed from an active workspace ``LLMConfig``."""

    def __init__(
        self,
        *,
        provider: str,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.name = provider.strip().lower()
        self._api_key = api_key
        self._base_url = base_url
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

    async def complete(self, call: ModelCall) -> CompletionResult:
        self._ensure_configured()
        import litellm

        try:
            resp = await litellm.acompletion(**self._kwargs(call))
        except Exception as exc:
            raise ProviderError("PROVIDER_CALL_FAILED", str(exc)) from exc
        return self._normalize(resp, call)

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
) -> LLMProvider:
    """Factory: return a :class:`MockProvider` for ``mock``, else LiteLLM-backed.

    This is the single seam the API/graph layers use; they never branch on the
    provider key themselves.
    """
    if provider.strip().lower() == "mock":
        from suitest_agent.providers.mock import MockProvider

        mock: MockProvider = MockProvider()
        return mock
    return LiteLLMProvider(provider=provider, api_key=api_key, base_url=base_url)
