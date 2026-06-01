"""M3-7 URL semantic generator tests — deterministic via MockProvider."""

from __future__ import annotations

import json

import pytest
from suitest_agent.generators.url_semantic import UrlSemanticGenerator
from suitest_agent.providers.base import CompletionResult
from suitest_agent.providers.mock import MockProvider
from suitest_shared.domain.enums import CaseSource, TargetKind


def _scripted(payload: str) -> MockProvider:
    return MockProvider(
        scripted=[CompletionResult(content=payload, model="mock-1", tokens_in=40, tokens_out=22)]
    )


@pytest.mark.asyncio
async def test_semantic_maps_journey_cases() -> None:
    cases = {
        "cases": [
            {
                "title": "Checkout happy path",
                "priority": "P0",
                "steps": [
                    {"action": "navigate to /shop", "expected": "catalog visible"},
                    {"action": "add item and pay", "expected": "order confirmed"},
                ],
            },
            {
                "title": "Checkout abandoned cart",
                "priority": "P2",
                "steps": [{"action": "leave at payment", "expected": "cart persists"}],
            },
        ]
    }
    gen = UrlSemanticGenerator(_scripted(json.dumps(cases)), model="mock-1")
    result = await gen.run("https://shop.example", "checkout flow", seed=5)

    assert result.error is None
    assert len(result.drafts) == 2
    draft = result.drafts[0]
    assert draft.target_kind is TargetKind.FE_WEB
    assert draft.source is CaseSource.AI
    assert draft.steps[0].mcp_provider == "playwright-mcp"
    assert draft.steps[0].code == ""
    assert "url-semantic" in draft.tags
    assert result.usage is not None and result.usage.tokens_in == 40


@pytest.mark.asyncio
async def test_semantic_empty_intent_errors() -> None:
    gen = UrlSemanticGenerator(MockProvider(), model="mock-1")
    result = await gen.run("https://x.example", "   ")
    assert result.error == "EMPTY_INTENT"
    assert result.drafts == []


@pytest.mark.asyncio
async def test_semantic_non_json_yields_no_cases() -> None:
    gen = UrlSemanticGenerator(MockProvider(), model="mock-1")
    result = await gen.run("https://x.example", "login flow")
    assert result.error is None
    assert result.drafts == []
