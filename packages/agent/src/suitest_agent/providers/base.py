"""Provider-agnostic LLM call contract (M3-1).

The graphs (M3-4) and the API LLM-config service (M3-2) talk to an
:class:`LLMProvider` — never to LiteLLM directly. Two implementations exist:
``LiteLLMProvider`` (real, 100+ backends) and ``MockProvider`` (deterministic,
no network) used by ZERO/`mock` tier and the whole test suite.

No ``litellm`` import here — this module is import-safe at ZERO tier.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class ChatMessage(BaseModel):
    """One turn in a chat completion. ``role`` ∈ system|user|assistant|tool."""

    role: str
    content: str


class ModelCall(BaseModel):
    """A single completion request, provider-independent.

    ``seed`` is best-effort: providers that do not support it (anthropic, gemini)
    silently drop it via LiteLLM ``drop_params=True``. ``cache_control`` enables
    Anthropic prompt-caching headers when the backend supports them.
    """

    model: str
    messages: list[ChatMessage]
    temperature: float = 0.2
    max_tokens: int = 4096
    tools: list[dict[str, object]] | None = None
    seed: int | None = None
    cache_control: bool = True


class CompletionResult(BaseModel):
    """Normalized completion response shared across providers."""

    content: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    finish_reason: str = "stop"
    tool_calls: list[dict[str, object]] = Field(default_factory=list)


class StreamChunk(BaseModel):
    """One streamed delta. ``done`` marks the final chunk (carries usage)."""

    delta: str = ""
    done: bool = False
    tokens_out: int = 0


@runtime_checkable
class LLMProvider(Protocol):
    """Interface every provider implements. Name is the canonical provider key."""

    name: str

    async def complete(self, call: ModelCall) -> CompletionResult: ...

    def stream_complete(self, call: ModelCall) -> AsyncIterator[StreamChunk]: ...

    def cost_usd(self, result: CompletionResult) -> float: ...


class ProviderError(RuntimeError):
    """Raised when a provider call fails (auth, network, bad model)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
