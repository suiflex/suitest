"""Code Assist provider — Gemini behind a sign-in rather than a key.

LiteLLM cannot reach this backend. Its Gemini provider posts to
``…/models/{model}:generateContent`` with the model in the URL; Code Assist
takes ``…/v1internal:generateContent`` with the model in an envelope that also
names the billing project::

    {**envelope, "model": "gemini-2.5-pro", "request": {<GenerateContentRequest>}}

This class is deliberately blind to *which* Code Assist product it is talking
to. Gemini Code Assist and Antigravity differ in host, credentials and two
envelope fields, all of which arrive through the resolved credential — so there
is one provider here, not two. ``suitest_agent`` also does not depend on
``suitest_core``, which is what makes that separation load-bearing rather than
merely tidy.

The Gemini payload shape follows https://ai.google.dev/api/generate-content.
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
#: Gemini names the assistant turn "model"; sending "assistant" is rejected.
_ROLE_MAP = {"user": "user", "assistant": "model", "tool": "user", "system": "system"}


class CodeAssistProvider:
    """Calls a Code Assist backend for one workspace's stored credential."""

    def __init__(
        self,
        *,
        provider: str,
        api_key: str | None,
        base_url: str,
        extra_headers: dict[str, str] | None = None,
        extra_body: dict[str, object] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.name = provider.strip().lower()
        self._token = api_key or ""
        self._base_url = base_url.rstrip("/")
        self._headers = dict(extra_headers or {})
        #: ``project`` plus whatever else this product puts beside it.
        self._envelope = dict(extra_body or {})
        self._transport = transport

    # --- request ------------------------------------------------------------

    def _payload(self, call: ModelCall) -> dict[str, object]:
        """Wrap a Gemini request in the Code Assist envelope."""
        return {**self._envelope, "model": call.model, "request": build_request(call)}

    def _request_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            **self._headers,
        }

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=_TIMEOUT, transport=self._transport)

    # --- completion ---------------------------------------------------------

    async def complete(self, call: ModelCall) -> CompletionResult:
        async with self._client() as client:
            try:
                response = await client.post(
                    f"{self._base_url}/v1internal:generateContent",
                    headers=self._request_headers(),
                    json=self._payload(call),
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
        return self._normalize(body if isinstance(body, dict) else {}, call)

    def _normalize(self, body: dict[str, Any], call: ModelCall) -> CompletionResult:
        text, tool_calls, finish = read_candidate(body)
        usage = body.get("usageMetadata")
        usage_map: dict[str, Any] = usage if isinstance(usage, dict) else {}
        return CompletionResult(
            content=text,
            model=call.model,
            tokens_in=_as_int(usage_map.get("promptTokenCount")),
            tokens_out=_as_int(usage_map.get("candidatesTokenCount")),
            # Quota-based, not metered per token. Zero is the right answer here,
            # not a value nobody filled in.
            cost_usd=0.0,
            finish_reason=finish,
            tool_calls=tool_calls,
        )

    # --- streaming ----------------------------------------------------------

    async def stream_complete(self, call: ModelCall) -> AsyncIterator[StreamChunk]:
        payload = self._payload(call)
        url = f"{self._base_url}/v1internal:streamGenerateContent?alt=sse"
        async with self._client() as client:
            try:
                async with client.stream(
                    "POST", url, headers=self._request_headers(), json=payload
                ) as response:
                    if response.status_code >= 400:
                        raise ProviderError(
                            "PROVIDER_CALL_FAILED",
                            f"{self.name} returned status {response.status_code}",
                        )
                    async for line in response.aiter_lines():
                        chunk = _sse_payload(line)
                        if chunk is None:
                            continue
                        text, _, _ = read_candidate(chunk)
                        if text:
                            yield StreamChunk(delta=text)
            except httpx.HTTPError as exc:
                raise ProviderError("PROVIDER_CALL_FAILED", str(exc)) from exc
        yield StreamChunk(done=True)

    def cost_usd(self, result: CompletionResult) -> float:
        return result.cost_usd


# --- payload translation ----------------------------------------------------


def build_request(call: ModelCall) -> dict[str, object]:
    """Translate a :class:`ModelCall` into a Gemini ``GenerateContentRequest``."""
    request: dict[str, object] = {
        "contents": _contents(call.messages),
        "generationConfig": {
            "temperature": call.temperature,
            "maxOutputTokens": call.max_tokens,
        },
    }
    system = "\n\n".join(m.content for m in call.messages if m.role == "system" and m.content)
    if system:
        # System text is its own field here, not a turn in the conversation.
        request["systemInstruction"] = {"parts": [{"text": system}]}
    declarations = _function_declarations(call.tools)
    if declarations:
        request["tools"] = [{"functionDeclarations": declarations}]
    return request


def _contents(messages: list[ChatMessage]) -> list[dict[str, object]]:
    """Turns, excluding system messages, with roles Gemini accepts.

    A ``tool`` message degrades to a user turn. Reconstructing a Gemini
    ``functionResponse`` needs the id of the call it answers, and
    :class:`ChatMessage` carries only a role and a string — so this is the limit
    of the interface, not an oversight. Tool *results* therefore reach the model
    as plain text; tool *calls* coming back are read faithfully.
    """
    turns: list[dict[str, object]] = []
    for message in messages:
        if message.role == "system" or not message.content:
            continue
        role = _ROLE_MAP.get(message.role, "user")
        turns.append({"role": role, "parts": [{"text": message.content}]})
    return turns


def _function_declarations(tools: list[dict[str, object]] | None) -> list[dict[str, object]]:
    """Map OpenAI-shaped tool definitions onto Gemini function declarations."""
    if not tools:
        return []
    declarations: list[dict[str, object]] = []
    for tool in tools:
        fn = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        if not isinstance(fn, dict):
            continue
        name = fn.get("name")
        if not isinstance(name, str) or not name:
            continue
        declaration: dict[str, object] = {"name": name}
        description = fn.get("description")
        if isinstance(description, str) and description:
            declaration["description"] = description
        parameters = fn.get("parameters")
        if isinstance(parameters, dict):
            declaration["parameters"] = parameters
        declarations.append(declaration)
    return declarations


def read_candidate(body: dict[str, Any]) -> tuple[str, list[dict[str, object]], str]:
    """Return ``(text, tool_calls, finish_reason)`` from one response body."""
    candidates = body.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return "", [], "stop"
    first = candidates[0]
    if not isinstance(first, dict):
        return "", [], "stop"

    content = first.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    texts: list[str] = []
    tool_calls: list[dict[str, object]] = []
    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text:
                texts.append(text)
            fn = part.get("functionCall")
            if isinstance(fn, dict) and isinstance(fn.get("name"), str):
                tool_calls.append(
                    {
                        "id": fn.get("id") if isinstance(fn.get("id"), str) else "",
                        "name": fn["name"],
                        # The rest of Suitest expects arguments as a JSON string,
                        # the way the OpenAI shape delivers them.
                        "arguments": json.dumps(fn.get("args") or {}),
                    }
                )

    finish = first.get("finishReason")
    return (
        "".join(texts),
        tool_calls,
        finish.lower() if isinstance(finish, str) and finish else "stop",
    )


def _sse_payload(line: str) -> dict[str, Any] | None:
    """Parse one ``data:`` line of an SSE stream, ignoring everything else."""
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
