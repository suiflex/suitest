"""ChatGPT-plan provider tests — the Responses API, not chat completions."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from suitest_agent.providers.base import ChatMessage, ModelCall, ProviderError
from suitest_agent.providers.chatgpt_responses import ChatGptResponsesProvider, build_payload


def _call(**over: object) -> ModelCall:
    base: dict[str, object] = {
        "model": "gpt-5.6",
        "messages": [ChatMessage(role="user", content="hi")],
    }
    return ModelCall(**{**base, **over})


def _provider(handler: Callable[[httpx.Request], httpx.Response]) -> ChatGptResponsesProvider:
    return ChatGptResponsesProvider(
        provider="chatgpt",
        api_key="access-token",
        base_url="https://chatgpt.example/backend-api/codex",
        extra_headers={"chatgpt-account-id": "acc_1"},
        transport=httpx.MockTransport(handler),
    )


def _answer(text: str = "hello") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": 9, "output_tokens": 4},
        },
    )


@pytest.mark.asyncio
async def test_it_posts_to_responses_not_chat_completions() -> None:
    """The whole point: the backend serves one of those paths and not the other."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/responses")
        assert "/chat/completions" not in str(request.url)
        assert request.headers["chatgpt-account-id"] == "acc_1"
        seen.update(json.loads(request.content))
        return _answer()

    await _provider(handler).complete(_call())

    assert seen["model"] == "gpt-5.6"
    assert seen["stream"] is False
    # `input` items, not `messages`.
    assert "messages" not in seen
    assert seen["input"] == [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]}
    ]


def test_system_text_travels_as_instructions() -> None:
    payload = build_payload(
        _call(
            messages=[
                ChatMessage(role="system", content="be brief"),
                ChatMessage(role="user", content="hi"),
            ]
        ),
        stream=False,
    )
    assert payload["instructions"] == "be brief"
    assert len(payload["input"]) == 1  # type: ignore[arg-type]


def test_an_assistant_turn_carries_output_text() -> None:
    """Input and output parts are different types on this API."""
    payload = build_payload(
        _call(
            messages=[
                ChatMessage(role="user", content="q"),
                ChatMessage(role="assistant", content="a"),
            ]
        ),
        stream=False,
    )
    items = payload["input"]
    assert items[0]["content"][0]["type"] == "input_text"  # type: ignore[index]
    assert items[1]["content"][0]["type"] == "output_text"  # type: ignore[index]
    assert items[1]["role"] == "assistant"  # type: ignore[index]


def test_tools_are_flat_here_not_nested_under_function() -> None:
    """The chat API nests them; the Responses API does not."""
    payload = build_payload(
        _call(
            tools=[
                {
                    "type": "function",
                    "function": {"name": "get_case", "parameters": {"type": "object"}},
                }
            ]
        ),
        stream=False,
    )
    assert payload["tools"] == [
        {"type": "function", "name": "get_case", "parameters": {"type": "object"}}
    ]


@pytest.mark.asyncio
async def test_usage_uses_this_apis_field_names() -> None:
    """input_tokens/output_tokens here, not prompt_tokens/completion_tokens."""
    result = await _provider(lambda r: _answer("done")).complete(_call())

    assert result.content == "done"
    assert result.tokens_in == 9
    assert result.tokens_out == 4
    # A plan, not metered API billing.
    assert result.cost_usd == 0.0


@pytest.mark.asyncio
async def test_a_function_call_item_becomes_a_tool_call() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "ok"}]},
                    {
                        "type": "function_call",
                        "call_id": "call_1",
                        "name": "get_case",
                        "arguments": '{"id":"c-1"}',
                    },
                ]
            },
        )

    result = await _provider(handler).complete(_call())

    assert result.content == "ok"
    # Already a JSON string on this API, so it is passed through untouched.
    assert result.tool_calls == [{"id": "call_1", "name": "get_case", "arguments": '{"id":"c-1"}'}]
    assert result.finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_streaming_reads_only_the_text_delta_events() -> None:
    """The stream is a typed event feed; most of it is bookkeeping."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = "\n".join(
            [
                'data: {"type":"response.created"}',
                "",
                'data: {"type":"response.output_text.delta","delta":"Hel"}',
                "",
                'data: {"type":"response.output_text.delta","delta":"lo"}',
                "",
                'data: {"type":"response.completed"}',
                "",
                "data: [DONE]",
                "",
            ]
        )
        return httpx.Response(200, text=body)

    chunks = [c async for c in _provider(handler).stream_complete(_call())]

    assert "".join(c.delta for c in chunks) == "Hello"
    assert chunks[-1].done is True


@pytest.mark.asyncio
async def test_a_rejected_credential_is_reported_as_auth() -> None:
    def denied(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "expired"})

    with pytest.raises(ProviderError) as err:
        await _provider(denied).complete(_call())
    assert err.value.code == "PROVIDER_AUTH"
