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
    max_tokens: int = 4096,
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
        max_tokens=max_tokens,
    )
    return await provider.complete(call)


# Test-case generation output cap. Reasoning models (e.g. deepseek-v4-pro behind an
# OpenAI-compatible gateway) write their reasoning into ``content`` and sometimes
# ran past the old 4096 default, cutting the JSON off. 8192 is the smallest output
# limit among current hosted models Suitest targets.
GENERATION_MAX_TOKENS = 8192
TRUNCATED = "LLM_OUTPUT_TRUNCATED"


def truncated_without_cases(result: CompletionResult) -> bool:
    """True when the model hit its token limit before emitting a usable case list.

    Callers report :data:`TRUNCATED` instead of silently returning zero drafts.
    """
    if result.finish_reason != "length":
        return False
    cases = parse_json_object(result.content).get("cases")
    return not (isinstance(cases, list) and cases)
