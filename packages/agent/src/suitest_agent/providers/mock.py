"""Deterministic in-process LLM provider (M3-1).

Backs the ``mock`` provider key (classified CLOUD-tier by the per-workspace LLM
config; see ``apps/api/.../capabilities._provider_to_tier``) and every test that
exercises the agent graphs without a network call. Output is a pure function of
the request, so
``seed`` makes it fully reproducible (``determinism="deterministic"``).

Two modes:

* **scripted** — construct with ``MockProvider(scripted=[...])`` and each
  ``complete`` pops the next canned :class:`CompletionResult` (or raw string).
  Used by graph tests that need specific structured JSON back.
* **echo** (default) — returns ``"MOCK:" + sha256(last_user_msg+seed)[:16]`` so
  the content is stable and unique per input.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from suitest_agent.providers.base import (
    ChatMessage,
    CompletionResult,
    ModelCall,
    ProviderError,
    StreamChunk,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# Synthetic per-token price so cost_usd is non-zero and reproducible in tests.
_MOCK_PRICE_PER_TOKEN_USD = 0.000001


def _last_user(messages: list[ChatMessage]) -> str:
    for msg in reversed(messages):
        if msg.role == "user":
            return msg.content
    return messages[-1].content if messages else ""


def _word_tokens(text: str) -> int:
    return max(1, len(text.split()))


class MockProvider:
    """Deterministic provider. See module docstring."""

    name = "mock"

    def __init__(self, scripted: list[CompletionResult | str] | None = None) -> None:
        self._scripted = list(scripted or [])
        self._cursor = 0

    def _deterministic(self, call: ModelCall) -> CompletionResult:
        basis = f"{_last_user(call.messages)}|seed={call.seed}|model={call.model}"
        digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
        content = f"MOCK:{digest}"
        tokens_in = sum(_word_tokens(m.content) for m in call.messages)
        tokens_out = _word_tokens(content)
        return CompletionResult(
            content=content,
            model=call.model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=(tokens_in + tokens_out) * _MOCK_PRICE_PER_TOKEN_USD,
        )

    async def complete(self, call: ModelCall) -> CompletionResult:
        if self._scripted:
            if self._cursor >= len(self._scripted):
                raise ProviderError(
                    "MOCK_SCRIPT_EXHAUSTED",
                    f"MockProvider ran out of scripted responses after {self._cursor}",
                )
            item = self._scripted[self._cursor]
            self._cursor += 1
            if isinstance(item, str):
                tokens_out = _word_tokens(item)
                return CompletionResult(
                    content=item,
                    model=call.model,
                    tokens_in=sum(_word_tokens(m.content) for m in call.messages),
                    tokens_out=tokens_out,
                    cost_usd=tokens_out * _MOCK_PRICE_PER_TOKEN_USD,
                )
            return item
        return self._deterministic(call)

    async def stream_complete(self, call: ModelCall) -> AsyncIterator[StreamChunk]:
        result = await self.complete(call)
        for word in result.content.split(" "):
            yield StreamChunk(delta=word + " ")
        yield StreamChunk(done=True, tokens_out=result.tokens_out)

    def cost_usd(self, result: CompletionResult) -> float:
        return result.cost_usd
