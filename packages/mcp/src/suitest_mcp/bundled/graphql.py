"""Bundled ``graphql-mcp`` provider (M2-10).

In-process MCP server for GraphQL targets (``target_kind=BE_GRAPHQL``). Backed by
``httpx.AsyncClient`` — a GraphQL request is a plain HTTP ``POST`` of
``{"query": ..., "variables": ...}``, so this carries no extra dependency beyond
the one ``api-http-mcp`` already uses.

Tools:

``graphql.query`` / ``graphql.mutate``
    POST a GraphQL document. Returns ``{status, data, errors}``. The two names
    are semantic aliases — the wire shape is identical — so test authors can
    read a step's intent from the tool name.

``graphql.assert_data``
    Run a query then assert a JSONPath over ``data`` resolves and (optionally)
    equals an expected value. Assertion failures raise :class:`AssertionError`,
    which the SDK surfaces as ``isError=true`` → :class:`McpToolFailed`.

Endpoint resolution: ``arguments['endpoint']`` wins, else ``config_json['endpoint']``,
else the provider's ``endpoint`` (the ``in-process://`` sentinel is rejected).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
from jsonpath_ng.ext import parse as jsonpath_parse
from mcp.types import TextContent, Tool

from suitest_mcp.bundled.in_process_runtime import BundledServer, register_bundled_builder

if TYPE_CHECKING:
    from suitest_mcp.models import McpProviderConfig

PROVIDER_NAME = "graphql-mcp"
_DEFAULT_TIMEOUT_SECONDS = 30.0


def _tool_catalog() -> list[Tool]:
    obj: dict[str, Any] = {"type": "object"}
    string: dict[str, Any] = {"type": "string"}
    doc_schema = {
        "type": "object",
        "required": ["query"],
        "properties": {
            "endpoint": string,
            "query": string,
            "variables": obj,
            "headers": obj,
        },
    }
    return [
        Tool(name="graphql.query", description="Execute a GraphQL query.", inputSchema=doc_schema),
        Tool(
            name="graphql.mutate",
            description="Execute a GraphQL mutation.",
            inputSchema=doc_schema,
        ),
        Tool(
            name="graphql.assert_data",
            description="Run a query and assert a JSONPath over the data payload.",
            inputSchema={
                "type": "object",
                "required": ["query", "jsonpath"],
                "properties": {
                    "endpoint": string,
                    "query": string,
                    "variables": obj,
                    "headers": obj,
                    "jsonpath": string,
                    "equals": {},
                },
            },
        ),
    ]


class GraphqlServer:
    """``BundledServer`` for GraphQL targets."""

    def __init__(self, provider: McpProviderConfig) -> None:
        self._provider = provider
        self._client: httpx.AsyncClient | None = None

    async def list_tools(self) -> list[Tool]:
        return _tool_catalog()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name in ("graphql.query", "graphql.mutate"):
            payload = await self._execute(arguments)
            return [TextContent(type="text", text=json.dumps(payload, default=str))]
        if name == "graphql.assert_data":
            return await self._assert_data(arguments)
        raise ValueError(f"unknown graphql-mcp tool: {name!r}")

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # -- internals -----------------------------------------------------------

    def _resolve_endpoint(self, args: dict[str, Any]) -> str:
        endpoint = args.get("endpoint") or self._provider.config_json.get("endpoint")
        endpoint = endpoint or self._provider.endpoint or ""
        if not endpoint or str(endpoint).startswith("in-process://"):
            raise ValueError("graphql-mcp requires an 'endpoint' (in args or config_json)")
        return str(endpoint)

    async def _execute(self, args: dict[str, Any]) -> dict[str, Any]:
        query = args.get("query")
        if not isinstance(query, str) or not query:
            raise ValueError("graphql tools require a non-empty 'query'")
        endpoint = self._resolve_endpoint(args)
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT_SECONDS)
        body: dict[str, Any] = {"query": query}
        if isinstance(args.get("variables"), dict):
            body["variables"] = args["variables"]
        headers = args.get("headers") if isinstance(args.get("headers"), dict) else {}
        resp = await self._client.post(endpoint, json=body, headers=headers)
        parsed: dict[str, Any]
        try:
            parsed = resp.json()
        except (ValueError, json.JSONDecodeError):
            parsed = {}
        return {
            "status": resp.status_code,
            "data": parsed.get("data"),
            "errors": parsed.get("errors"),
        }

    async def _assert_data(self, args: dict[str, Any]) -> list[TextContent]:
        path = args.get("jsonpath")
        if not isinstance(path, str) or not path:
            raise ValueError("graphql.assert_data requires 'jsonpath'")
        result = await self._execute(args)
        if result.get("errors"):
            raise AssertionError(f"graphql.assert_data: query returned errors {result['errors']!r}")
        matches = [m.value for m in jsonpath_parse(path).find(result.get("data") or {})]
        if not matches:
            raise AssertionError(f"graphql.assert_data: {path!r} matched nothing")
        if "equals" in args and matches[0] != args["equals"]:
            raise AssertionError(
                f"graphql.assert_data: {path!r} = {matches[0]!r}, expected {args['equals']!r}"
            )
        return [TextContent(type="text", text=json.dumps({"ok": True, "matched": matches[0]}))]


def build_graphql_server(provider: McpProviderConfig) -> BundledServer:
    return GraphqlServer(provider)


register_bundled_builder(PROVIDER_NAME, build_graphql_server)
