"""M3-9 MCP tool-discovery generator tests — deterministic via MockProvider."""

from __future__ import annotations

import json

import pytest
from suitest_agent.generators.mcp_discovery import McpDiscoveryGenerator, _format_tools
from suitest_agent.providers.base import CompletionResult
from suitest_agent.providers.mock import MockProvider
from suitest_shared.domain.enums import CaseSource, TargetKind


def _scripted(payload: str) -> MockProvider:
    return MockProvider(
        scripted=[CompletionResult(content=payload, model="mock-1", tokens_in=30, tokens_out=15)]
    )


_TOOLS: list[dict[str, object]] = [
    {
        "name": "create_order",
        "description": "Create an order",
        "input_schema": {"properties": {"sku": {"type": "string"}, "qty": {"type": "integer"}}},
    },
    {"name": "get_order", "description": "Fetch an order", "argSchema": {"properties": {"id": {}}}},
]


def test_format_tools_renders_names_and_args() -> None:
    lines = _format_tools(_TOOLS)
    assert lines[0] == "create_order — Create an order (args: sku, qty)"
    assert lines[1] == "get_order — Fetch an order (args: id)"


def test_format_tools_skips_nameless() -> None:
    assert _format_tools([{"description": "x"}, {"name": ""}]) == []


@pytest.mark.asyncio
async def test_discovery_maps_cases() -> None:
    cases = {
        "cases": [
            {
                "title": "create_order happy path",
                "priority": "P1",
                "steps": [{"action": "call create_order sku=A qty=1", "expected": "order id"}],
            }
        ]
    }
    gen = McpDiscoveryGenerator(_scripted(json.dumps(cases)), model="mock-1")
    result = await gen.run(_TOOLS, target_kind=TargetKind.BE_REST, mcp_provider_name="orders-mcp")

    assert result.error is None
    assert len(result.drafts) == 1
    draft = result.drafts[0]
    assert draft.target_kind is TargetKind.BE_REST
    assert draft.source is CaseSource.AI
    assert draft.steps[0].mcp_provider == "orders-mcp"
    assert draft.steps[0].code == ""
    assert "mcp-discovery" in draft.tags
    assert result.usage is not None and result.usage.tokens_out == 15


@pytest.mark.asyncio
async def test_discovery_empty_catalog_errors() -> None:
    gen = McpDiscoveryGenerator(MockProvider(), model="mock-1")
    result = await gen.run([], target_kind=TargetKind.CUSTOM, mcp_provider_name="x")
    assert result.error == "EMPTY_CATALOG"
    assert result.drafts == []


@pytest.mark.asyncio
async def test_discovery_non_json_yields_no_cases() -> None:
    gen = McpDiscoveryGenerator(MockProvider(), model="mock-1")
    result = await gen.run(_TOOLS, target_kind=TargetKind.BE_REST, mcp_provider_name="orders-mcp")
    assert result.error is None
    assert result.drafts == []
