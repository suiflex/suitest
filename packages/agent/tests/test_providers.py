"""M3-1 provider-layer tests. Mock + pure mappings only — no network, no litellm."""

from __future__ import annotations

import pytest
from suitest_agent.providers.base import ChatMessage, CompletionResult, ModelCall, ProviderError
from suitest_agent.providers.litellm_router import (
    LiteLLMProvider,
    get_provider,
    normalize_openai_base_url,
    seed_determinism,
    to_litellm_model,
)
from suitest_agent.providers.mock import MockProvider


def _call(text: str = "hello world", *, seed: int | None = None) -> ModelCall:
    return ModelCall(
        model="mock-1",
        messages=[ChatMessage(role="user", content=text)],
        seed=seed,
    )


@pytest.mark.asyncio
async def test_mock_is_deterministic_per_input() -> None:
    p = MockProvider()
    a = await p.complete(_call("same input", seed=7))
    b = await MockProvider().complete(_call("same input", seed=7))
    assert a.content == b.content
    assert a.content.startswith("MOCK:")


@pytest.mark.asyncio
async def test_mock_varies_with_input_and_seed() -> None:
    p = MockProvider()
    base = (await p.complete(_call("x", seed=1))).content
    assert base != (await MockProvider().complete(_call("y", seed=1))).content
    assert base != (await MockProvider().complete(_call("x", seed=2))).content


@pytest.mark.asyncio
async def test_mock_cost_and_tokens_nonzero() -> None:
    res = await MockProvider().complete(_call("a few words here"))
    assert res.tokens_in > 0
    assert res.tokens_out > 0
    assert res.cost_usd > 0


@pytest.mark.asyncio
async def test_mock_scripted_responses_in_order() -> None:
    scripted: list[CompletionResult | str] = [
        "first",
        CompletionResult(content="second", model="mock-1"),
    ]
    p = MockProvider(scripted=scripted)
    assert (await p.complete(_call())).content == "first"
    assert (await p.complete(_call())).content == "second"
    with pytest.raises(ProviderError) as exc:
        await p.complete(_call())
    assert exc.value.code == "MOCK_SCRIPT_EXHAUSTED"


@pytest.mark.asyncio
async def test_mock_stream_concatenates_to_content() -> None:
    p = MockProvider()
    streamed = ""
    done_seen = False
    async for chunk in p.stream_complete(_call("stream me")):
        streamed += chunk.delta
        done_seen = done_seen or chunk.done
    assert done_seen
    assert streamed.strip() == (await MockProvider().complete(_call("stream me"))).content


@pytest.mark.parametrize(
    ("provider", "model", "expected"),
    [
        ("anthropic", "claude-sonnet-4-5", "anthropic/claude-sonnet-4-5"),
        ("openai", "gpt-4o", "openai/gpt-4o"),
        ("vertex", "gemini-1.5-pro", "vertex_ai/gemini-1.5-pro"),
        ("vllm", "qwen2.5", "openai/qwen2.5"),
        ("lmstudio", "local-model", "openai/local-model"),
        # M4-1: all four validated LOCAL providers
        ("ollama", "llama3.1", "ollama/llama3.1"),
        ("llamacpp", "local-model", "openai/local-model"),
        # Sign in with Google reaches Vertex's OpenAI-compatible endpoint, which
        # is a different surface from the ``vertex`` service-account path above.
        ("google-vertex", "google/gemini-2.5-pro", "openai/google/gemini-2.5-pro"),
    ],
)
def test_to_litellm_model_mapping(provider: str, model: str, expected: str) -> None:
    assert to_litellm_model(provider, model) == expected


def test_chatgpt_does_not_ask_the_user_for_a_base_url() -> None:
    """Its endpoint comes from the resolved credential, not from the settings form."""
    from suitest_agent.providers.litellm_router import requires_base_url

    assert requires_base_url("chatgpt") is False


def test_extra_headers_reach_the_completion_call() -> None:
    """A credential that needs a header gets it onto the request."""
    from suitest_agent.providers.litellm_router import LiteLLMProvider

    provider = LiteLLMProvider(
        provider="google-vertex",
        api_key="access-token",
        base_url="https://us-central1-aiplatform.example/v1/x/openapi",
        extra_headers={"x-example": "1"},
    )
    kwargs = provider._kwargs(_call("hi"))

    assert kwargs["model"] == "openai/mock-1"
    assert kwargs["api_key"] == "access-token"
    assert kwargs["api_base"] == "https://us-central1-aiplatform.example/v1/x/openapi"
    assert kwargs["extra_headers"] == {"x-example": "1"}


def test_chatgpt_is_not_a_litellm_provider_any_more() -> None:
    """It serves the Responses API, so mapping it onto chat completions was the bug.

    ``get_provider`` routes it to its own class; nothing should reach here.
    """
    with pytest.raises(ProviderError) as exc:
        to_litellm_model("chatgpt", "gpt-5.6")
    assert exc.value.code == "UNKNOWN_PROVIDER"


def test_no_extra_headers_stay_out_of_the_call() -> None:
    """An API-key provider must send exactly what it sent before."""
    from suitest_agent.providers.litellm_router import LiteLLMProvider

    provider = LiteLLMProvider(provider="openai", api_key="sk-1")
    assert "extra_headers" not in provider._kwargs(_call("hi"))


@pytest.mark.parametrize("provider", ["ollama", "llamacpp", "vllm", "lmstudio"])
def test_local_providers_require_base_url(provider: str) -> None:
    from suitest_agent.providers.litellm_router import LOCAL_TIER_DEFAULTS, requires_base_url

    assert requires_base_url(provider) is True
    assert provider in LOCAL_TIER_DEFAULTS
    assert LOCAL_TIER_DEFAULTS[provider]["base_url"].startswith("http")


@pytest.mark.parametrize("provider", ["anthropic", "openai", "gemini", "google-vertex"])
def test_cloud_providers_do_not_require_base_url(provider: str) -> None:
    from suitest_agent.providers.litellm_router import requires_base_url

    assert requires_base_url(provider) is False


def test_to_litellm_model_rejects_unknown() -> None:
    with pytest.raises(ProviderError) as exc:
        to_litellm_model("not-a-provider", "x")
    assert exc.value.code == "UNKNOWN_PROVIDER"


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("openai", "deterministic"),
        ("groq", "deterministic"),
        ("mock", "deterministic"),
        ("anthropic", "best_effort"),
        ("gemini", "best_effort"),
    ],
)
def test_seed_determinism(provider: str, expected: str) -> None:
    assert seed_determinism(provider) == expected


def test_get_provider_returns_mock_for_mock_key() -> None:
    assert isinstance(get_provider("mock"), MockProvider)


def test_get_provider_returns_litellm_for_cloud_key() -> None:
    p = get_provider("anthropic", api_key="sk-test")
    assert isinstance(p, LiteLLMProvider)
    assert p.name == "anthropic"


# --- Custom [OI]-compatible endpoint: base URL normalization (root cause #1) ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Bare origin: the [OI] client appends /chat/completions, so the base
        # must name the resource root, not the server root.
        ("https://gw.example.com", "https://gw.example.com/v1"),
        # Trailing slash must not survive (it would produce //chat/completions).
        ("https://gw.example.com/", "https://gw.example.com/v1"),
        # Already-correct forms pass through unchanged.
        ("https://gw.example.com/v1", "https://gw.example.com/v1"),
        ("https://gw.example.com/v1/", "https://gw.example.com/v1"),
        # Version pasted twice: the classic "self-hosted gateway behind a
        # versioned reverse proxy" paste.
        ("https://gw.example.com/v1/v1", "https://gw.example.com/v1"),
        ("https://gw.example.com/v1/v1/", "https://gw.example.com/v1"),
        # Users paste the full endpoint URL straight out of a curl example.
        ("https://gw.example.com/v1/chat/completions", "https://gw.example.com/v1"),
        ("https://gw.example.com/v1/chat/completions/", "https://gw.example.com/v1"),
        # A gateway mounted at a non-default path is respected verbatim.
        ("https://gw.example.com/api/openai", "https://gw.example.com/api/openai"),
        ("https://gw.example.com/api/openai/", "https://gw.example.com/api/openai"),
    ],
)
def test_normalize_openai_base_url(raw: str, expected: str) -> None:
    assert normalize_openai_base_url(raw) == expected


def test_custom_provider_normalizes_base_url_into_kwargs() -> None:
    p = LiteLLMProvider(provider="custom", base_url="https://gw.example.com/v1/")
    kwargs = p._kwargs(_call())
    assert kwargs["api_base"] == "https://gw.example.com/v1"


def test_custom_provider_timeout_reaches_kwargs() -> None:
    """An unreachable endpoint must fail fast, not hang on the client default."""
    p = LiteLLMProvider(provider="custom", base_url="https://gw.example.com/v1", timeout=7.5)
    kwargs = p._kwargs(_call())
    assert kwargs["timeout"] == 7.5


def test_non_openai_shim_base_url_is_passed_through() -> None:
    """Ollama's native API is not [OI]-path-grammar; never rewritten."""
    p = LiteLLMProvider(provider="ollama", base_url="http://localhost:11434")
    kwargs = p._kwargs(_call())
    assert kwargs["api_base"] == "http://localhost:11434"
