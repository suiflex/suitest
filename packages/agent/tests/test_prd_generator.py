"""M3-6 PRD generator tests — deterministic via the scripted MockProvider."""

from __future__ import annotations

import json

import pytest
from suitest_agent.generators.prd import PrdGenerator, mcp_for_target_kind
from suitest_agent.providers.base import CompletionResult
from suitest_agent.providers.mock import MockProvider
from suitest_shared.domain.enums import CaseSource, Priority, TargetKind


def _scripted(payload: str) -> MockProvider:
    return MockProvider(
        scripted=[CompletionResult(content=payload, model="mock-1", tokens_in=12, tokens_out=8)]
    )


@pytest.mark.asyncio
async def test_prd_maps_cases_to_drafts() -> None:
    cases = {
        "cases": [
            {
                "title": "Checkout happy path",
                "priority": "P0",
                "steps": [
                    {"action": "add item to cart", "expected": "cart shows 1 item"},
                    {"action": "pay with card", "expected": "order confirmed"},
                ],
            },
            {
                "title": "Checkout declined card",
                "priority": "P1",
                "steps": [{"action": "pay with declined card", "expected": "error shown"}],
            },
        ]
    }
    gen = PrdGenerator(
        _scripted(json.dumps(cases)), model="mock-1", default_target_kind=TargetKind.FE_WEB
    )
    result = await gen.run("Users can buy products", seed=7)

    assert result.error is None
    assert len(result.drafts) == 2
    first = result.drafts[0]
    assert first.name == "Checkout happy path"
    assert first.priority is Priority.P0
    assert first.source is CaseSource.AI
    assert first.target_kind is TargetKind.FE_WEB
    assert [s.order for s in first.steps] == [1, 2]
    # Agentic steps carry no code — translated at execution time (M3-10).
    assert all(s.code == "" for s in first.steps)
    assert all(s.mcp_provider == "playwright-mcp" for s in first.steps)


@pytest.mark.asyncio
async def test_prd_reports_usage() -> None:
    cases = {"cases": [{"title": "X", "priority": "P2", "steps": [{"action": "do it"}]}]}
    gen = PrdGenerator(_scripted(json.dumps(cases)), model="mock-1")
    result = await gen.run("something", seed=1)

    assert result.usage is not None
    assert result.usage.tokens_in == 12
    assert result.usage.tokens_out == 8
    assert result.usage.model == "mock-1"


@pytest.mark.asyncio
async def test_prd_empty_input_errors() -> None:
    gen = PrdGenerator(MockProvider(), model="mock-1")
    result = await gen.run("   ")
    assert result.error == "EMPTY_INPUT"
    assert result.drafts == []


@pytest.mark.asyncio
async def test_prd_skips_unusable_cases() -> None:
    cases = {
        "cases": [
            {"title": "", "priority": "P0", "steps": [{"action": "x"}]},  # no title
            {"title": "No steps", "priority": "P1", "steps": []},  # no usable steps
            {"title": "Good", "priority": "P2", "steps": [{"action": "click"}]},
        ]
    }
    gen = PrdGenerator(_scripted(json.dumps(cases)), model="mock-1")
    result = await gen.run("text")
    assert [d.name for d in result.drafts] == ["Good"]


@pytest.mark.asyncio
async def test_prd_bad_priority_defaults_p2() -> None:
    cases = {"cases": [{"title": "T", "priority": "URGENT", "steps": [{"action": "x"}]}]}
    gen = PrdGenerator(_scripted(json.dumps(cases)), model="mock-1")
    result = await gen.run("text")
    assert result.drafts[0].priority is Priority.P2


def test_mcp_for_target_kind() -> None:
    assert mcp_for_target_kind(TargetKind.BE_REST) == "api-http-mcp"
    assert mcp_for_target_kind(TargetKind.FE_WEB) == "playwright-mcp"
    assert mcp_for_target_kind(TargetKind.DATA) == "postgres-mcp"
