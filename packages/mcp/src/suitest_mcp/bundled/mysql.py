"""Bundled ``mysql-mcp`` provider (M2-10).

In-process MCP server for MySQL ``DATA``-tier steps. Mirrors the postgres-mcp tool
subset (``db.query`` / ``db.exec`` / ``db.assert_row_count``). The MySQL driver
(``aiomysql``) is imported lazily at call time so loading the registry / listing
tools never requires the driver to be installed — air-gapped images that don't
bundle MySQL support can still advertise the provider and fail cleanly only when
a step actually targets it.

DSN: ``config_json['dsn']`` (a ``mysql://user:pass@host:port/db`` URL) or the
provider ``endpoint``. The ``in-process://`` sentinel means "not configured".
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

PROVIDER_NAME = "mysql-mcp"


def _tool_catalog() -> list[Tool]:
    string: dict[str, Any] = {"type": "string"}
    array: dict[str, Any] = {"type": "array"}
    return [
        Tool(
            name="db.query",
            description="Execute a SELECT; returns rows as list[dict].",
            inputSchema={
                "type": "object",
                "required": ["sql"],
                "properties": {"sql": string, "params": array},
            },
        ),
        Tool(
            name="db.exec",
            description="Execute DML/DDL; returns affected rowcount.",
            inputSchema={
                "type": "object",
                "required": ["sql"],
                "properties": {"sql": string, "params": array},
            },
        ),
        Tool(
            name="db.assert_row_count",
            description="Assert COUNT(*) over a table matches an exact value.",
            inputSchema={
                "type": "object",
                "required": ["table", "count"],
                "properties": {"table": string, "where_sql": string, "count": {"type": "integer"}},
            },
        ),
    ]


def _require_aiomysql() -> Any:
    try:
        return importlib.import_module("aiomysql")
    except ImportError as exc:  # pragma: no cover - depends on image build
        raise RuntimeError(
            "mysql-mcp requires the 'aiomysql' driver (bundle it in the runner image)"
        ) from exc


class MysqlServer:
    """``BundledServer`` for MySQL targets (lazy aiomysql)."""

    def __init__(self, provider: McpProviderConfig) -> None:
        self._provider = provider

    async def list_tools(self) -> list[Tool]:
        return _tool_catalog()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> list[TextContent]:
        aiomysql = _require_aiomysql()
        conn = await self._connect(aiomysql)
        try:
            if name == "db.query":
                return await self._query(conn, arguments)
            if name == "db.exec":
                return await self._exec(conn, arguments)
            if name == "db.assert_row_count":
                return await self._assert_count(conn, arguments)
        finally:
            conn.close()
        raise ValueError(f"unknown mysql-mcp tool: {name!r}")

    async def aclose(self) -> None:
        return None

    async def _connect(self, aiomysql: Any) -> Any:
        dsn = self._provider.config_json.get("dsn") or self._provider.endpoint or ""
        if not dsn or str(dsn).startswith("in-process://"):
            raise RuntimeError("mysql-mcp requires config_json.dsn")
        parsed = urlparse(str(dsn))
        return await aiomysql.connect(
            host=parsed.hostname or "localhost",
            port=parsed.port or 3306,
            user=parsed.username or "root",
            password=parsed.password or "",
            db=parsed.path.lstrip("/") or None,
        )

    async def _query(self, conn: Any, args: dict[str, Any]) -> list[TextContent]:
        async with conn.cursor() as cur:
            await cur.execute(args["sql"], args.get("params") or [])
            cols = [c[0] for c in (cur.description or [])]
            rows = [dict(zip(cols, r, strict=False)) for r in await cur.fetchall()]
        return [TextContent(type="text", text=json.dumps(rows, default=str))]

    async def _exec(self, conn: Any, args: dict[str, Any]) -> list[TextContent]:
        async with conn.cursor() as cur:
            await cur.execute(args["sql"], args.get("params") or [])
            await conn.commit()
            affected = cur.rowcount
        return [TextContent(type="text", text=json.dumps({"affected": affected}))]

    async def _assert_count(self, conn: Any, args: dict[str, Any]) -> list[TextContent]:
        table = str(args["table"])
        expected = args.get("count")
        if not isinstance(expected, int):
            raise ValueError("db.assert_row_count requires integer 'count'")
        where = args.get("where_sql")
        sql = f"SELECT COUNT(*) FROM `{table}`"
        if isinstance(where, str) and where.strip():
            sql += f" WHERE {where}"
        async with conn.cursor() as cur:
            await cur.execute(sql)
            row = await cur.fetchone()
        actual = int(row[0]) if row else 0
        if actual != expected:
            raise AssertionError(f"db.assert_row_count: expected {expected} got {actual}")
        return [TextContent(type="text", text=json.dumps({"ok": True, "count": actual}))]


def build_mysql_server(provider: McpProviderConfig) -> BundledServer:
    return MysqlServer(provider)


register_bundled_builder(PROVIDER_NAME, build_mysql_server)
