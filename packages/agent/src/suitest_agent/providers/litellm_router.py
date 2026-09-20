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
from urllib.parse import urlparse

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
# ``google-vertex`` (Sign in with Google) speaks the OpenAI protocol too, against
# Vertex's own OpenAI-compatible endpoint; its base URL names the caller's GCP
# project and region and comes from ``suitest_core.llm_credentials``. That is why
# it is here and not under the ``vertex`` prefix, which reaches Vertex's native
# API with service-account credentials instead.
# ``chatgpt`` is deliberately absent: the ChatGPT backend serves the Responses
# API, not chat completions, so it has its own provider rather than a shim.
_OPENAI_SHIM = frozenset({"llamacpp", "vllm", "lmstudio", "custom", "google-vertex"})

# Code Assist backends speak a Gemini payload inside their own envelope, which
# LiteLLM has no provider for — see providers/code_assist.py.
_CODE_ASSIST_PROVIDERS = frozenset({"google-codeassist", "antigravity"})

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


# OpenAI-shim providers whose endpoint the sign-in derives rather than the user
# typing it: ChatGPT's is fixed, and Vertex's is built from the project and
# region the Google sign-in collected.
_ENDPOINT_FROM_CREDENTIAL = frozenset({"chatgpt", "google-vertex", *_CODE_ASSIST_PROVIDERS})


def requires_base_url(provider: str) -> bool:
    """True when the *user* must supply a base URL — no endpoint to default to.

    An OAuth provider speaks the same OpenAI protocol but is not in this set:
    its base URL comes from the resolved credential, not from the person
    configuring it.
    """
    p = provider.strip().lower()
    return p == "ollama" or (p in _OPENAI_SHIM and p not in _ENDPOINT_FROM_CREDENTIAL)


def seed_determinism(provider: str) -> str:
    """Return ``"deterministic"`` or ``"best_effort"`` for replay metadata (§13.1)."""
    return "deterministic" if provider.strip().lower() in _DETERMINISTIC_SEED else "best_effort"


def normalize_openai_base_url(raw: str) -> str:
    """Normalize a user-supplied [OI]-compatible base URL.

    Users paste any of these into Settings and expect all of them to work:

    * ``https://gw.example.com``            — bare origin (served under ``/v1``)
    * ``https://gw.example.com/``           — trailing slash
    * ``https://gw.example.com/v1``         — already correct
    * ``https://gw.example.com/v1/``        — trailing slash after the version
    * ``https://gw.example.com/v1/v1``      — version pasted twice
    * ``https://gw.example.com/v1/chat/completions`` — the full endpoint URL

    The OpenAI client appends ``/chat/completions`` to whatever base it is
    given, so the normalized result always points at the resource root, never
    at a duplicate version segment or a doubled path. A URL with any other
    non-empty path (e.g. a gateway mounted at ``/api/openai``) is respected
    verbatim — only dangling slashes, the ``/chat/completions`` suffix, and a
    duplicated ``/v1`` are rewritten.

    Ollama's native API does not go through this function: it is keyed by
    provider, and only ``_OPENAI_SHIM`` providers speak the [OI] path grammar.
    """
    url = raw.strip().rstrip("/")
    if url.endswith("/chat/completions"):
        url = url[: -len("/chat/completions")].rstrip("/")
    while "/v1/v1" in url:
        url = url.replace("/v1/v1", "/v1", 1)
    if not urlparse(url).path:
        url = f"{url}/v1"
    return url


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
        extra_headers: dict[str, str] | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.name = provider.strip().lower()
        self._api_key = api_key
        # [OI]-shim providers speak the [OI] path grammar, so the pasted base
        # URL is normalized (trailing slash, /v1 duplication, full-endpoint
        # paste). Other providers' base URLs have provider-specific semantics
        # (ollama's native API, azure deployments) and are passed through.
        if base_url and self.name in _OPENAI_SHIM:
            self._base_url: str | None = normalize_openai_base_url(base_url)
        else:
            self._base_url = base_url
        self._workspace_id = workspace_id
        self._db_session_factory = db_session_factory
        self._extra_headers = extra_headers
        # Without an explicit timeout LiteLLM waits for its internal default
        # (600s); an unreachable custom endpoint then hangs the connection
        # test and every dependent request instead of failing fast.
        self._timeout = timeout
        self._configured = False

    def _ensure_configured(self) -> None:
        """Set LiteLLM module globals once. Lazy ``import litellm`` lives here."""
        if self._configured:
            return
        # Every other method reaches litellm through here first, so this is the
        # single place the dependency can be missing. It lives in the ``cloud``
        # extra: without this guard an install that skipped it raises
        # ModuleNotFoundError out of the request handler as a 500 rather than a
        # reportable "your LLM is not usable" answer.
        try:
            import litellm
        except ImportError as exc:
            raise ProviderError(
                "LLM_DEPS_MISSING",
                "The LLM client (litellm) is not installed in this Suitest runtime. "
                "Reinstall the local stack, or `pip install 'suitest-agent[cloud]'`.",
            ) from exc

        litellm.drop_params = True
        self._configured = True

    def _kwargs(self, call: ModelCall) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "model": to_litellm_model(self.name, call.model),
            "messages": [m.model_dump() for m in call.messages],
            "temperature": call.temperature,
            "max_tokens": call.max_tokens,
            "timeout": self._timeout,
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
        elif self.name in _OPENAI_SHIM:
            # LiteLLM's openai/* router checks for an api_key and raises OpenAIException - Missing credentials
            # if none is provided. For custom/local OpenAI-compatible endpoints that don't need auth,
            # provide a dummy placeholder.
            kwargs["api_key"] = "none"
        if self._base_url:
            kwargs["api_base"] = self._base_url
        if self._extra_headers:
            kwargs["extra_headers"] = self._extra_headers
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

        # _normalize is inside the try on purpose: a custom OpenAI-compatible
        # gateway can answer 200 with an empty ``choices`` or a body that is not
        # OpenAI-shaped at all, and an IndexError there used to reach the client
        # as a 500 instead of a reported provider failure.
        try:
            resp = await litellm.acompletion(**self._kwargs(effective_call))
            return self._normalize(resp, effective_call)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError("PROVIDER_CALL_FAILED", str(exc)) from exc

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
    extra_headers: dict[str, str] | None = None,
    extra_body: dict[str, object] | None = None,
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
        extra_headers: Per-request headers the credential requires — the
            ``chatgpt`` provider identifies its account this way. Resolved by
            ``suitest_core.llm_credentials``, never assembled by callers.
        extra_body: Request-body fields outside the payload, for a backend that
            wraps it — Code Assist names its billing project this way. Same
            provenance as ``extra_headers``.
    """
    key = provider.strip().lower()
    if key == "mock":
        from suitest_agent.providers.mock import MockProvider

        mock: MockProvider = MockProvider()
        return mock
    if key == "chatgpt":
        from suitest_agent.providers.chatgpt_responses import ChatGptResponsesProvider

        if not base_url:
            raise ProviderError("MISSING_BASE_URL", "chatgpt needs its backend endpoint")
        return ChatGptResponsesProvider(
            provider=key,
            api_key=api_key,
            base_url=base_url,
            extra_headers=extra_headers,
        )
    if key in _CODE_ASSIST_PROVIDERS:
        from suitest_agent.providers.code_assist import CodeAssistProvider

        if not base_url:
            raise ProviderError("MISSING_BASE_URL", f"{key} needs its backend endpoint")
        return CodeAssistProvider(
            provider=key,
            api_key=api_key,
            base_url=base_url,
            extra_headers=extra_headers,
            extra_body=extra_body,
        )
    return LiteLLMProvider(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        workspace_id=workspace_id,
        db_session_factory=db_session_factory,
        extra_headers=extra_headers,
    )
