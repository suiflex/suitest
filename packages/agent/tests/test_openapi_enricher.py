"""M3-8 OpenAPI edge-case enricher tests — deterministic via MockProvider."""

from __future__ import annotations

import json

import pytest
from suitest_agent.generators.openapi_enrich import OpenApiEnricher
from suitest_agent.providers.base import CompletionResult
from suitest_agent.providers.mock import MockProvider
from suitest_shared.domain.enums import CaseSource, TargetKind


def _scripted(payload: str) -> MockProvider:
    return MockProvider(
        scripted=[CompletionResult(content=payload, model="mock-1", tokens_in=20, tokens_out=10)]
    )


@pytest.mark.asyncio
async def test_enrich_maps_edge_cases() -> None:
    cases = {
        "cases": [
            {
                "title": "POST /pets with negative id",
                "priority": "P1",
                "steps": [{"action": "POST /pets id=-1", "expected": "422 validation error"}],
            }
        ]
    }
    enricher = OpenApiEnricher(_scripted(json.dumps(cases)), model="mock-1")
    result = await enricher.enrich(["POST /pets — create pet (params: id)"])

    assert result.error is None
    assert len(result.drafts) == 1
    draft = result.drafts[0]
    assert draft.target_kind is TargetKind.BE_REST
    assert draft.source is CaseSource.AI
    assert draft.steps[0].mcp_provider == "api-http-mcp"
    assert draft.steps[0].code == ""
    assert "edge-case" in draft.tags
    assert draft.generated_from["case_kind"] == "llm_edge"
    assert result.usage is not None
    assert result.usage.tokens_in == 20


@pytest.mark.asyncio
async def test_enrich_no_operations_short_circuits() -> None:
    enricher = OpenApiEnricher(MockProvider(), model="mock-1")
    result = await enricher.enrich([])
    assert result.drafts == []
    assert result.error is None


@pytest.mark.asyncio
async def test_enrich_non_json_yields_no_cases() -> None:
    # Plain mock echo returns "MOCK:<hash>" (not JSON) → zero cases, no crash.
    enricher = OpenApiEnricher(MockProvider(), model="mock-1")
    result = await enricher.enrich(["GET /pets — list pets"])
    assert result.drafts == []
    assert result.error is None
