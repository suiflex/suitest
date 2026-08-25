"""Code Assist provider tests — the translation LiteLLM cannot do for us."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from suitest_agent.providers.base import ChatMessage, ModelCall, ProviderError
from suitest_agent.providers.code_assist import CodeAssistProvider, build_request


def _call(**over: object) -> ModelCall:
    base: dict[str, object] = {
        "model": "gemini-2.5-pro",
        "messages": [ChatMessage(role="user", content="hi")],
    }
    return ModelCall(**{**base, **over})


def _provider(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    provider: str = "google-codeassist",
    extra_body: dict[str, object] | None = None,
) -> CodeAssistProvider:
    return CodeAssistProvider(
        provider=provider,
        api_key="ya29.live",
        base_url="https://cloudcode-pa.example",
        extra_headers={"User-Agent": "suitest-test"},
        extra_body=extra_body if extra_body is not None else {"project": "p-1"},
        transport=httpx.MockTransport(handler),
    )


def _answer(text: str = "hello") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 7},
        },
    )


def test_the_assistant_turn_is_called_model() -> None:
    """Gemini rejects the role "assistant"; getting this wrong fails every reply."""
    request = build_request(
        _call(
            messages=[
                ChatMessage(role="user", content="q"),
                ChatMessage(role="assistant", content="a"),
                ChatMessage(role="user", content="q2"),
            ]
        )
    )
    roles = [turn["role"] for turn in request["contents"]]  # type: ignore[index,union-attr]
    assert roles == ["user", "model", "user"]


def test_system_text_becomes_an_instruction_not_a_turn() -> None:
    """It is its own field in this API, and a turn with that role is invalid."""
    request = build_request(
        _call(
            messages=[
                ChatMessage(role="system", content="be brief"),
                ChatMessage(role="system", content="and kind"),
                ChatMessage(role="user", content="hi"),
            ]
        )
    )
    assert request["systemInstruction"] == {"parts": [{"text": "be brief\n\nand kind"}]}
    assert len(request["contents"]) == 1  # type: ignore[arg-type]


def test_a_tool_result_degrades_to_a_user_turn() -> None:
    """ChatMessage carries no call id, so a functionResponse cannot be rebuilt.

    The limit of the interface, recorded so it is not mistaken for a bug.
    """
    request = build_request(_call(messages=[ChatMessage(role="tool", content='{"ok": true}')]))
    assert request["contents"] == [{"role": "user", "parts": [{"text": '{"ok": true}'}]}]


def test_openai_shaped_tools_become_function_declarations() -> None:
    request = build_request(
        _call(
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "get_case",
                        "description": "Fetch a case",
                        "parameters": {"type": "object", "properties": {"id": {"type": "string"}}},
                    },
                }
            ]
        )
    )
    declarations = request["tools"][0]["functionDeclarations"]  # type: ignore[index,call-overload]
    assert declarations[0]["name"] == "get_case"
    assert declarations[0]["parameters"]["properties"]["id"]["type"] == "string"


def test_a_call_without_tools_sends_no_tools_field() -> None:
    """An empty tools array is not the same as omitting it."""
    assert "tools" not in build_request(_call())


@pytest.mark.asyncio
async def test_the_payload_is_wrapped_in_the_envelope_the_backend_wants() -> None:
    """Model and project sit outside `request`; that is the whole difference."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1internal:generateContent"
        assert request.headers["authorization"] == "Bearer ya29.live"
        assert request.headers["user-agent"] == "suitest-test"
        seen.update(json.loads(request.content))
        return _answer()

    await _provider(handler).complete(_call())

    assert seen["project"] == "p-1"
    assert seen["model"] == "gemini-2.5-pro"
    assert "contents" in seen["request"]  # type: ignore[operator]


@pytest.mark.asyncio
async def test_antigravity_carries_its_extra_envelope_fields() -> None:
    """One provider, two products — the difference arrives in the credential."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return _answer()

    await _provider(
        handler,
        provider="antigravity",
        extra_body={"project": "p-2", "userAgent": "antigravity", "requestType": "agent"},
    ).complete(_call())

    assert seen["userAgent"] == "antigravity"
    assert seen["requestType"] == "agent"

    # ...and the Code Assist envelope does not invent them.
    plain: dict[str, object] = {}

    def plain_handler(request: httpx.Request) -> httpx.Response:
        plain.update(json.loads(request.content))
        return _answer()

    await _provider(plain_handler).complete(_call())
    assert "userAgent" not in plain
    assert "requestType" not in plain


@pytest.mark.asyncio
async def test_usage_and_finish_reason_are_read_back() -> None:
    result = await _provider(lambda r: _answer("done")).complete(_call())

    assert result.content == "done"
    assert result.tokens_in == 11
    assert result.tokens_out == 7
    assert result.finish_reason == "stop"
    # Quota-based, not metered — zero is the answer, not a gap.
    assert result.cost_usd == 0.0


@pytest.mark.asyncio
async def test_a_function_call_comes_back_as_a_tool_call() -> None:
    """Arguments are handed on as a JSON string, the shape the rest expects."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "calling"},
                                {
                                    "functionCall": {
                                        "id": "fc_1",
                                        "name": "get_case",
                                        "args": {"id": "c-1"},
                                    }
                                },
                            ]
                        },
                        "finishReason": "TOOL_CALLS",
                    }
                ]
            },
        )

    result = await _provider(handler).complete(_call())

    assert result.content == "calling"
    assert result.tool_calls == [{"id": "fc_1", "name": "get_case", "arguments": '{"id": "c-1"}'}]
    assert result.finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_streaming_yields_deltas_then_a_done_chunk() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("alt") == "sse"
        body = "\n".join(
            [
                ": ping",
                'data: {"candidates":[{"content":{"parts":[{"text":"Hel"}]}}]}',
                "",
                'data: {"candidates":[{"content":{"parts":[{"text":"lo"}]}}]}',
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
    """So the settings page can say "sign in again" rather than "unknown error"."""

    def denied(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "expired"})

    with pytest.raises(ProviderError) as err:
        await _provider(denied).complete(_call())
    assert err.value.code == "PROVIDER_AUTH"


@pytest.mark.asyncio
async def test_an_empty_response_does_not_crash_the_call() -> None:
    """A blocked or filtered reply carries no candidates; that is not an exception."""

    def empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": []})

    result = await _provider(empty).complete(_call())
    assert result.content == ""
    assert result.tool_calls == []
