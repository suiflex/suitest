"""Shared helpers for the agent graphs (M3-4)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from suitest_agent.providers.base import ChatMessage, ModelCall

if TYPE_CHECKING:
    from suitest_agent.providers.base import CompletionResult, LLMProvider


def parse_json_object(text: str) -> dict[str, object]:
    """Parse the first JSON object in ``text``. Returns ``{}`` on failure.

    LLMs occasionally wrap JSON in prose or ```` ```json ```` fences; this slices
    from the first ``{`` to the last ``}`` before parsing so the graphs stay
    robust without a strict-output guarantee from every provider.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def complete_with_prompt(
    provider: LLMProvider,
    *,
    model: str,
    system: str,
    user: str,
    seed: int | None = None,
    temperature: float = 0.2,
) -> CompletionResult:
    """Run a one-shot system+user completion through ``provider``."""
    call = ModelCall(
        model=model,
        messages=[
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content=user),
        ],
        seed=seed,
        temperature=temperature,
    )
    return await provider.complete(call)
