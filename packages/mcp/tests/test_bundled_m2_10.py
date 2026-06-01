"""M2-10 bundled providers — catalogs, routing defaults, graphql execution."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from suitest_mcp.models import McpProviderConfig, McpTransport
from suitest_mcp.registry import McpRegistry
from suitest_mcp.routing import resolve_provider
from suitest_shared.domain.enums import TargetKind

_NEW = {
    "graphql-mcp": "suitest_mcp.bundled.graphql",
    "mysql-mcp": "suitest_mcp.bundled.mysql",
    "mongo-mcp": "suitest_mcp.bundled.mongo",
    "kubernetes-mcp": "suitest_mcp.bundled.kubernetes",
    "grpc-mcp": "suitest_mcp.bundled.grpc",
}


def _cfg(name: str) -> McpProviderConfig:
    return McpProviderConfig(
        id=f"builtin:{name}",
        workspace_id="_builtin_",
        name=name,
        kind="test",
        transport=McpTransport.IN_PROCESS,
        endpoint=f"in-process://{name}",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(_NEW))
async def test_bundled_provider_lists_tools(name: str) -> None:
    import importlib

    from suitest_mcp.bundled.in_process_runtime import get_bundled_builder

    importlib.import_module(_NEW[name])  # registers the builder
    server = get_bundled_builder(name)(_cfg(name))
    tools = await server.list_tools()
    assert len(tools) >= 2
    assert all(t.name for t in tools)


def test_routing_defaults_use_new_providers() -> None:
    reg = McpRegistry()
    reg.register_builtin("w1")
    assert (
        resolve_provider(
            reg, workspace_id="w1", target_kind=TargetKind.BE_GRAPHQL, explicit=None
        ).name
        == "graphql-mcp"
    )
    assert (
        resolve_provider(reg, workspace_id="w1", target_kind=TargetKind.BE_GRPC, explicit=None).name
        == "grpc-mcp"
    )
    assert (
        resolve_provider(reg, workspace_id="w1", target_kind=TargetKind.INFRA, explicit=None).name
        == "kubernetes-mcp"
    )


def test_registry_includes_eight_builtins() -> None:
    reg = McpRegistry()
    reg.register_builtin("w1")
    names = {p.name for p in reg.list_for_workspace("w1")}
    assert {
        "api-http-mcp",
        "playwright-mcp",
        "postgres-mcp",
        "graphql-mcp",
        "mysql-mcp",
        "mongo-mcp",
        "kubernetes-mcp",
        "grpc-mcp",
    } <= names


@pytest.mark.asyncio
async def test_graphql_query_and_assert() -> None:
    from suitest_mcp.bundled.graphql import GraphqlServer

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/graphql"
        body = json.loads(request.content)
        assert body["query"]
        return httpx.Response(200, json={"data": {"viewer": {"login": "maya"}}})

    server = GraphqlServer(_cfg("graphql-mcp"))
    server._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    out = await server.call_tool(
        "graphql.query",
        {"endpoint": "https://api.example/graphql", "query": "{ viewer { login } }"},
    )
    payload: dict[str, Any] = json.loads(out[0].text)
    assert payload["data"]["viewer"]["login"] == "maya"

    asserted = await server.call_tool(
        "graphql.assert_data",
        {
            "endpoint": "https://api.example/graphql",
            "query": "{ viewer { login } }",
            "jsonpath": "viewer.login",
            "equals": "maya",
        },
    )
    assert json.loads(asserted[0].text)["ok"] is True
    await server.aclose()
