"""Bundled ``mongo-mcp`` provider (M2-10).

In-process MCP server for MongoDB ``DATA``-tier steps. The async driver (``motor``)
is imported lazily so the registry / tool listing never requires it. DSN from
``config_json['dsn']`` (``mongodb://...``) or the provider ``endpoint``; the
target database from ``config_json['database']`` or the DSN path.

Tools: ``mongo.find`` / ``mongo.insert_one`` / ``mongo.delete`` / ``mongo.assert_count``.
"""

from __future__ import annotations

import importlib
import json
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from mcp.types import TextContent, Tool

from suitest_mcp.bundled.in_process_runtime import BundledServer, register_bundled_builder

if TYPE_CHECKING:
    from suitest_mcp.models import McpProviderConfig

PROVIDER_NAME = "mongo-mcp"


def _tool_catalog() -> list[Tool]:
    string: dict[str, Any] = {"type": "string"}
    obj: dict[str, Any] = {"type": "object"}
    return [
        Tool(
            name="mongo.find",
            description="Find documents in a collection by filter.",
            inputSchema={
                "type": "object",
                "required": ["collection"],
                "properties": {"collection": string, "filter": obj, "limit": {"type": "integer"}},
            },
        ),
        Tool(
            name="mongo.insert_one",
            description="Insert a single document.",
            inputSchema={
                "type": "object",
                "required": ["collection", "document"],
                "properties": {"collection": string, "document": obj},
            },
        ),
        Tool(
            name="mongo.delete",
            description="Delete documents matching a filter.",
            inputSchema={
                "type": "object",
                "required": ["collection", "filter"],
                "properties": {"collection": string, "filter": obj},
            },
        ),
        Tool(
            name="mongo.assert_count",
            description="Assert the document count matching a filter.",
            inputSchema={
                "type": "object",
                "required": ["collection", "count"],
                "properties": {"collection": string, "filter": obj, "count": {"type": "integer"}},
            },
        ),
    ]


def _require_motor() -> Any:
    try:
        return importlib.import_module("motor.motor_asyncio")
    except ImportError as exc:  # pragma: no cover - depends on image build
        raise RuntimeError(
            "mongo-mcp requires the 'motor' driver (bundle it in the runner image)"
        ) from exc


class MongoServer:
    """``BundledServer`` for MongoDB targets (lazy motor)."""

    def __init__(self, provider: McpProviderConfig) -> None:
        self._provider = provider

    async def list_tools(self) -> list[Tool]:
        return _tool_catalog()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> list[TextContent]:
        db = self._db()
        coll = db[str(arguments["collection"])]
        if name == "mongo.find":
            cursor = coll.find(arguments.get("filter") or {})
            limit = arguments.get("limit")
            if isinstance(limit, int):
                cursor = cursor.limit(limit)
            docs = [self._clean(d) for d in await cursor.to_list(length=limit or 100)]
            return [TextContent(type="text", text=json.dumps(docs, default=str))]
        if name == "mongo.insert_one":
            res = await coll.insert_one(dict(arguments["document"]))
            return [
                TextContent(type="text", text=json.dumps({"inserted_id": str(res.inserted_id)}))
            ]
        if name == "mongo.delete":
            res = await coll.delete_many(dict(arguments["filter"]))
            return [TextContent(type="text", text=json.dumps({"deleted": res.deleted_count}))]
        if name == "mongo.assert_count":
            expected = arguments.get("count")
            if not isinstance(expected, int):
                raise ValueError("mongo.assert_count requires integer 'count'")
            actual = await coll.count_documents(arguments.get("filter") or {})
            if actual != expected:
                raise AssertionError(f"mongo.assert_count: expected {expected} got {actual}")
            return [TextContent(type="text", text=json.dumps({"ok": True, "count": actual}))]
        raise ValueError(f"unknown mongo-mcp tool: {name!r}")

    async def aclose(self) -> None:
        return None

    def _db(self) -> Any:
        motor = _require_motor()
        dsn = self._provider.config_json.get("dsn") or self._provider.endpoint or ""
        if not dsn or str(dsn).startswith("in-process://"):
            raise RuntimeError("mongo-mcp requires config_json.dsn")
        client = motor.AsyncIOMotorClient(str(dsn))
        database = self._provider.config_json.get("database") or urlparse(str(dsn)).path.lstrip("/")
        if not database:
            raise RuntimeError("mongo-mcp requires config_json.database or a DSN path")
        return client[str(database)]

    @staticmethod
    def _clean(doc: dict[str, Any]) -> dict[str, Any]:
        return {k: (str(v) if k == "_id" else v) for k, v in doc.items()}


def build_mongo_server(provider: McpProviderConfig) -> BundledServer:
    return MongoServer(provider)


register_bundled_builder(PROVIDER_NAME, build_mongo_server)
