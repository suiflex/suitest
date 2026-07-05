"""Server->client ``sampling/createMessage`` (MCP).

When the connected MCP client advertises the ``sampling`` capability, the server
can ask it to run an inference against the user's own model subscription — no
OpenAI/Anthropic key held by the lifecycle. This module builds the request,
correlates the reply by id (via :mod:`suitest_lifecycle.mcp_server`'s response
table), and enforces a timeout. Stdlib only.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass

from suitest_lifecycle import mcp_server

# Start high so server-sent request ids never collide with client request ids.
_request_ids = itertools.count(10_000)


class SamplingError(RuntimeError):
    """Sampling failed (timeout, client error, empty content). Never fatal —
    callers fall back to the next LLM tier or the deterministic baseline."""


@dataclass
class SamplingResult:
    text: str
    model: str


def create_message(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 4096,
    timeout: float = 180.0,
) -> SamplingResult:
    req_id = next(_request_ids)
    params: dict[str, object] = {
        "messages": [{"role": "user", "content": {"type": "text", "text": prompt}}],
        "maxTokens": max_tokens,
    }
    if system is not None:
        params["systemPrompt"] = system
    mcp_server._write_message(
        {"jsonrpc": "2.0", "id": req_id, "method": "sampling/createMessage", "params": params}
    )

    deadline = time.monotonic() + timeout
    with mcp_server._client_response_event:
        while req_id not in mcp_server._client_responses:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SamplingError(f"sampling timeout after {timeout}s")
            mcp_server._client_response_event.wait(remaining)
        response = mcp_server._client_responses.pop(req_id)

    if "error" in response:
        raise SamplingError(str(response["error"]))
    result = response.get("result") or {}
    if not isinstance(result, dict):
        raise SamplingError("sampling returned a malformed result")
    content = result.get("content") or {}
    text = str(content.get("text", "")) if isinstance(content, dict) else ""
    if not text:
        raise SamplingError("sampling returned empty content")
    return SamplingResult(text=text, model=str(result.get("model", "unknown")))
