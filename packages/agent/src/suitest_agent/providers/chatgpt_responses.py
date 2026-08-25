"""ChatGPT-plan provider — the Responses API, not chat completions.

Signing in with ChatGPT and spending the result on the subscription reaches the
backend Codex talks to, and that backend takes the **Responses API**:
``POST {base}/responses`` with ``input`` items, not ``POST {base}/chat/completions``
with ``messages``. Routing it through the OpenAI shim aimed it at a path that
backend does not serve.

Shapes below follow ``codex-rs``: ``CompactionInput`` in
``codex-rs/codex-api/src/common.rs`` for the request keys, and ``ResponseItem`` /
``ContentItem`` in ``codex-rs/protocol/src/models.rs`` for the item shapes. They
match the public Responses API, which is what Codex is speaking.

Like the ChatGPT backend itself, none of this is a documented public surface —
see the risk notice the settings page carries.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx

from suitest_agent.providers.base import (
    ChatMessage,
    CompletionResult,
    ModelCall,
    ProviderError,
    StreamChunk,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_TIMEOUT = 120.0
#: Assistant turns carry output_text; everything the caller sends is input_text.
_OUTPUT_ROLES = frozenset({"assistant"})


class ChatGptResponsesProvider:
    """Calls the ChatGPT backend for a subscription credential."""

    def __init__(
        self,
        *,
        provider: str,
        api_key: str | None,
        base_url: str,
        extra_headers: dict[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.name = provider.strip().lower()
        self._token = api_key or ""
        self._base_url = base_url.rstrip("/")
        # Carries chatgpt-account-id, resolved from the stored credential.
        self._headers = dict(extra_headers or {})
        self._transport = transport

    def _request_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            **self._headers,
        }

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=_TIMEOUT, transport=self._transport)

    async def complete(self, call: ModelCall) -> CompletionResult:
        async with self._client() as client:
            try:
                response = await client.post(
                    f"{self._base_url}/responses",
                    headers=self._request_headers(),
                    json=build_payload(call, stream=False),
                )
            except httpx.HTTPError as exc:
                raise ProviderError("PROVIDER_CALL_FAILED", str(exc)) from exc

        if response.status_code >= 400:
            raise ProviderError(
                "PROVIDER_AUTH" if response.status_code in (401, 403) else "PROVIDER_CALL_FAILED",
                f"{self.name} returned status {response.status_code}",
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderError("PROVIDER_CALL_FAILED", "backend returned non-JSON") from exc

        text, tool_calls = read_output(body if isinstance(body, dict) else {})
        usage = body.get("usage") if isinstance(body, dict) else None
        usage_map: dict[str, Any] = usage if isinstance(usage, dict) else {}
        return CompletionResult(
            content=text,
            model=call.model,
            tokens_in=_as_int(usage_map.get("input_tokens")),
            tokens_out=_as_int(usage_map.get("output_tokens")),
            # A subscription draws on a plan, not on metered API billing.
            cost_usd=0.0,
            finish_reason="tool_calls" if tool_calls else "stop",
            tool_calls=tool_calls,
        )

    async def stream_complete(self, call: ModelCall) -> AsyncIterator[StreamChunk]:
        async with self._client() as client:
            try:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/responses",
                    headers=self._request_headers(),
                    json=build_payload(call, stream=True),
                ) as response:
                    if response.status_code >= 400:
                        raise ProviderError(
                            "PROVIDER_CALL_FAILED",
                            f"{self.name} returned status {response.status_code}",
                        )
                    async for line in response.aiter_lines():
                        event = _sse_payload(line)
                        if event is None:
                            continue
                        # The Responses stream is a typed event feed; only the
                        # text deltas are content, the rest is bookkeeping.
                        if event.get("type") == "response.output_text.delta":
                            delta = event.get("delta")
                            if isinstance(delta, str) and delta:
                                yield StreamChunk(delta=delta)
            except httpx.HTTPError as exc:
                raise ProviderError("PROVIDER_CALL_FAILED", str(exc)) from exc
        yield StreamChunk(done=True)

    def cost_usd(self, result: CompletionResult) -> float:
        return result.cost_usd


# --- payload translation ----------------------------------------------------


def build_payload(call: ModelCall, *, stream: bool) -> dict[str, object]:
    """Translate a :class:`ModelCall` into a Responses API request."""
    payload: dict[str, object] = {
        "model": call.model,
        "input": _input_items(call.messages),
        "stream": stream,
    }
    instructions = "\n\n".join(m.content for m in call.messages if m.role == "system" and m.content)
    if instructions:
        # System text is its own field here, not a turn in the input.
        payload["instructions"] = instructions
    tools = _tools(call.tools)
    if tools:
        payload["tools"] = tools
    return payload


def _input_items(messages: list[ChatMessage]) -> list[dict[str, object]]:
    """Message items, excluding system text which travels as instructions.

    A ``tool`` message degrades to a user turn: reconstructing a
    ``function_call_output`` needs the id of the call it answers, and
    :class:`ChatMessage` carries only a role and a string. That is the limit of
    the interface, not an oversight — the same one the Code Assist provider hits.
    """
    items: list[dict[str, object]] = []
    for message in messages:
        if message.role == "system" or not message.content:
            continue
        kind = "output_text" if message.role in _OUTPUT_ROLES else "input_text"
        items.append(
            {
                "type": "message",
                "role": "assistant" if message.role == "assistant" else "user",
                "content": [{"type": kind, "text": message.content}],
            }
        )
    return items


def _tools(tools: list[dict[str, object]] | None) -> list[dict[str, object]]:
    """Flatten OpenAI chat-shaped tools into the Responses API's flat shape."""
    if not tools:
        return []
    flattened: list[dict[str, object]] = []
    for tool in tools:
        fn = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        if not isinstance(fn, dict):
            continue
        name = fn.get("name")
        if not isinstance(name, str) or not name:
            continue
        entry: dict[str, object] = {"type": "function", "name": name}
        description = fn.get("description")
        if isinstance(description, str) and description:
            entry["description"] = description
        parameters = fn.get("parameters")
        if isinstance(parameters, dict):
            entry["parameters"] = parameters
        flattened.append(entry)
    return flattened


def read_output(body: dict[str, Any]) -> tuple[str, list[dict[str, object]]]:
    """Return ``(text, tool_calls)`` from a Responses API body."""
    output = body.get("output")
    if not isinstance(output, list):
        return "", []

    texts: list[str] = []
    tool_calls: list[dict[str, object]] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "message":
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("type") == "output_text":
                    text = part.get("text")
                    if isinstance(text, str) and text:
                        texts.append(text)
        elif kind == "function_call":
            name = item.get("name")
            if isinstance(name, str) and name:
                arguments = item.get("arguments")
                tool_calls.append(
                    {
                        "id": item.get("call_id") if isinstance(item.get("call_id"), str) else "",
                        "name": name,
                        # Already a JSON string on this API, unlike Gemini's.
                        "arguments": arguments if isinstance(arguments, str) else "{}",
                    }
                )
    return "".join(texts), tool_calls


def _sse_payload(line: str) -> dict[str, Any] | None:
    if not line.startswith("data:"):
        return None
    raw = line[len("data:") :].strip()
    if not raw or raw == "[DONE]":
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0
    return int(value)
