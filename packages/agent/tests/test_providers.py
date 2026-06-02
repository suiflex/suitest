"""M3-1 provider-layer tests. Mock + pure mappings only — no network, no litellm."""

from __future__ import annotations

import pytest
from suitest_agent.providers.base import ChatMessage, CompletionResult, ModelCall, ProviderError
from suitest_agent.providers.litellm_router import (
    LiteLLMProvider,
    get_provider,
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
    ],
)
def test_to_litellm_model_mapping(provider: str, model: str, expected: str) -> None:
    assert to_litellm_model(provider, model) == expected


@pytest.mark.parametrize("provider", ["ollama", "llamacpp", "vllm", "lmstudio"])
def test_local_providers_require_base_url(provider: str) -> None:
    from suitest_agent.providers.litellm_router import LOCAL_TIER_DEFAULTS, requires_base_url

    assert requires_base_url(provider) is True
    assert provider in LOCAL_TIER_DEFAULTS
    assert LOCAL_TIER_DEFAULTS[provider]["base_url"].startswith("http")


@pytest.mark.parametrize("provider", ["anthropic", "openai", "gemini"])
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
