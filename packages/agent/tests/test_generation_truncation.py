"""Truncated LLM output must surface ``LLM_OUTPUT_TRUNCATED``, never zero silent drafts.

Regression: deepseek-v4-pro behind an OpenAI-compatible gateway wrote its reasoning
into ``content``, hit the 4096-token default (``finish_reason="length"``), and the
PRD generator returned 0 cases with no error.
"""

from __future__ import annotations

import json

import pytest
from suitest_agent.generators.mcp_discovery import McpDiscoveryGenerator
from suitest_agent.generators.openapi_enrich import OpenApiEnricher
from suitest_agent.generators.prd import PrdGenerator
from suitest_agent.generators.url_semantic import UrlSemanticGenerator
from suitest_agent.graphs._util import GENERATION_MAX_TOKENS, TRUNCATED
from suitest_agent.providers.base import CompletionResult, ModelCall
from suitest_agent.providers.mock import MockProvider
from suitest_shared.domain.enums import TargetKind

_CUT = "We need answer in JSON only. Let's reason about the login flow...\nSteps:\n- action:"
_FULL = json.dumps({"cases": [{"title": "Login ok", "steps": [{"action": "a", "expected": "b"}]}]})


class _Recording(MockProvider):
    """Scripted provider that also records the ModelCall it received."""

    def __init__(self, content: str, finish_reason: str) -> None:
        super().__init__(
            scripted=[CompletionResult(content=content, model="m", finish_reason=finish_reason)]
        )
        self.calls: list[ModelCall] = []

    async def complete(self, call: ModelCall) -> CompletionResult:
        self.calls.append(call)
        return await super().complete(call)


async def _run_all(provider: MockProvider) -> list[str | None]:
    prd = await PrdGenerator(provider, model="m").run("User can log in")
    url = await UrlSemanticGenerator(provider, model="m").run("https://x.test", "log in")
    mcp = await McpDiscoveryGenerator(provider, model="m").run(
        [{"name": "login", "description": "Log in"}],
        target_kind=TargetKind.CUSTOM,
        mcp_provider_name="custom-mcp",
    )
    enrich = await OpenApiEnricher(provider, model="m").enrich(["POST /login"])
    return [prd.error, url.error, mcp.error, enrich.error]


@pytest.mark.asyncio
async def test_every_llm_generator_reports_truncation() -> None:
    provider = MockProvider(
        scripted=[CompletionResult(content=_CUT, model="m", finish_reason="length")] * 4
    )
    assert await _run_all(provider) == [TRUNCATED] * 4


@pytest.mark.asyncio
async def test_length_stop_with_complete_json_keeps_drafts() -> None:
    # The cap was hit after the JSON closed: the drafts are usable, not an error.
    provider = MockProvider(
        scripted=[CompletionResult(content=_FULL, model="m", finish_reason="length")] * 4
    )
    assert await _run_all(provider) == [None] * 4


@pytest.mark.asyncio
async def test_generation_requests_raised_output_cap() -> None:
    provider = _Recording(_FULL, "stop")
    result = await PrdGenerator(provider, model="m").run("User can log in")
    assert result.error is None
    assert provider.calls[0].max_tokens == GENERATION_MAX_TOKENS == 8192
