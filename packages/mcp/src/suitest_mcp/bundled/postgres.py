"""Bundled ``postgres-mcp`` provider (M1c Task 8).

In-process MCP server wrapping ``psycopg`` async — surfaces six tools the
deterministic runner uses for DATA-tier steps:

``db.query``
    Execute a parameterized statement. ``SELECT`` returns the row set as a
    ``list[dict]`` (column name → value); DML returns ``{"affected": rowcount}``.

``db.exec``
    Execute DDL / DML without expecting rows. Returns ``{"affected": rowcount}``.

``db.insert(table, row)``
    Parameterized ``INSERT`` whose identifiers go through
    :class:`psycopg.sql.Identifier` so a hostile ``table`` / column name
    cannot break out of the SQL string.

``db.delete(table, where)``
    Parameterized ``DELETE`` with the same identifier-safety contract.

``db.assert_row_exists(table, where)``
    ``SELECT COUNT(*)`` then assert ``count >= 1``. Failures surface as
    :class:`McpToolFailed` (``isError=true`` content) — the runner records the
    step as ``FAIL`` instead of ``ERROR``.

``db.assert_row_count(table, where, count)``
    Same as above but with an exact-match assertion.

Design notes
------------
* **Per-provider connection pool.** Each :class:`McpProviderConfig` keys a
  module-level :class:`psycopg_pool.AsyncConnectionPool` so repeated tool calls
  inside the same run reuse warm connections. Pools are torn down explicitly via
  :func:`close_all_pools` (tests do this between integration runs) — the
  :meth:`PostgresBundledServer.aclose` hook does *not* close the pool because
  multiple sessions can share it across one provider's lifetime.

* **SQL injection mitigation.** Identifiers (table name, column names from
  ``row``/``where`` JSON) are wrapped with :class:`psycopg.sql.Identifier`;
  values are passed as positional ``%s`` parameters. A ``where`` payload such
  as ``{"name": "Robert'); DROP TABLE students; --"}`` therefore lands as a
  bound value and never as in-band SQL.

* **DSN sourcing.** ``config_json["dsn"]`` wins; we fall back to
  :attr:`McpProviderConfig.endpoint` for legacy specs. The sentinel
  ``in-process://*`` endpoint (used by :data:`BUILTIN_SPECS`) is treated as
  "no DSN configured" and raises so the workspace operator notices.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import psycopg
import psycopg_pool
from mcp.types import TextContent, Tool
from psycopg import sql as psql

from suitest_mcp.bundled.in_process_runtime import (
    BundledServer,
    register_bundled_builder,
)

if TYPE_CHECKING:
    from suitest_mcp.models import McpProviderConfig


#: Registered name of the bundled provider — matches the entry in
#: :data:`suitest_mcp.providers.builtin_specs.BUILTIN_SPECS`.
PROVIDER_NAME = "postgres-mcp"

#: ``kind`` advertised by Task 8 spec metadata. Independent of the builtin
#: ``kind="db"`` value used for routing — kept distinct so the spec exposed by
#: this module can be introspected by tests and ZERO-tier UI without coupling
#: to routing semantics.
PROVIDER_KIND = "postgres-mcp"


# Module-level pool registry keyed on (provider.id, dsn) so two providers in
# the same workspace pointing at different DSNs don't collide and so
# re-importing the module under pytest doesn't double-open pools.
_POOLS: dict[str, psycopg_pool.AsyncConnectionPool] = {}


def _pool_key(provider_id: str, dsn: str) -> str:
    return f"{provider_id}:{dsn}"


def _resolve_dsn(provider: McpProviderConfig) -> str:
    """Extract the libpq DSN from ``provider.config_json`` / ``endpoint``.

    Raises:
        RuntimeError: no DSN configured (``in-process://*`` sentinel counts as
            unconfigured because the runner uses it to mean "bundled builtin
            with no live target yet").
    """
    dsn = provider.config_json.get("dsn") or provider.endpoint or ""
    if not dsn or dsn.startswith("in-process://"):
        raise RuntimeError(
            f"postgres-mcp provider {provider.name!r} requires config_json.dsn"
        )
    return dsn


async def _get_pool(provider: McpProviderConfig) -> psycopg_pool.AsyncConnectionPool:
    """Return (or lazily open) the shared pool for ``provider``."""
    dsn = _resolve_dsn(provider)
    key = _pool_key(provider.id, dsn)
    pool = _POOLS.get(key)
    if pool is None:
        pool = psycopg_pool.AsyncConnectionPool(
            dsn,
            min_size=0,
            max_size=max(1, provider.max_sessions),
            open=False,
        )
        await pool.open()
        _POOLS[key] = pool
    return pool


async def close_all_pools() -> None:
    """Close every pool the module has opened. Tests call this on teardown."""
    for pool in list(_POOLS.values()):
        with _ignoring_closed():
            await pool.close()
    _POOLS.clear()


class _ignoring_closed:
    """Swallow ``psycopg_pool.PoolClosed`` on double-close."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: type[BaseException] | None, *_: object) -> bool:
        return exc_type is not None and issubclass(exc_type, psycopg_pool.PoolClosed)


# ---------------------------------------------------------------------------
# SQL builders
# ---------------------------------------------------------------------------


def _build_insert(table: str, row: dict[str, Any]) -> tuple[psql.Composed, list[Any]]:
    """Build a parameterized ``INSERT`` using :class:`psql.Identifier`.

    Raises:
        ValueError: ``row`` is empty (nothing to insert).
    """
    if not row:
        raise ValueError("db.insert requires at least one column in row_json")
    columns = list(row.keys())
    stmt = psql.SQL("INSERT INTO {table} ({cols}) VALUES ({vals})").format(
        table=psql.Identifier(table),
        cols=psql.SQL(", ").join(psql.Identifier(c) for c in columns),
        vals=psql.SQL(", ").join(psql.Placeholder() for _ in columns),
    )
    return stmt, [row[c] for c in columns]


def _build_where(where: dict[str, Any]) -> tuple[psql.Composable, list[Any]]:
    """Build a parameterized ``WHERE`` clause from a JSON dict.

    Returns ``(empty_sql, [])`` when ``where`` is empty so callers can compose
    "match every row" semantics for ``db.delete`` / ``db.assert_row_count``.
    """
    if not where:
        return psql.SQL(""), []
    keys = list(where.keys())
    clauses = psql.SQL(" AND ").join(
        psql.SQL("{col} = {val}").format(col=psql.Identifier(k), val=psql.Placeholder())
        for k in keys
    )
    return clauses, [where[k] for k in keys]


def _build_delete(table: str, where: dict[str, Any]) -> tuple[psql.Composed, list[Any]]:
    where_sql, params = _build_where(where)
    if where:
        stmt = psql.SQL("DELETE FROM {table} WHERE {where}").format(
            table=psql.Identifier(table),
            where=where_sql,
        )
    else:
        stmt = psql.SQL("DELETE FROM {table}").format(table=psql.Identifier(table))
    return stmt, params


def _build_count(table: str, where: dict[str, Any]) -> tuple[psql.Composed, list[Any]]:
    where_sql, params = _build_where(where)
    if where:
        stmt = psql.SQL("SELECT COUNT(*) AS count FROM {table} WHERE {where}").format(
            table=psql.Identifier(table),
            where=where_sql,
        )
    else:
        stmt = psql.SQL("SELECT COUNT(*) AS count FROM {table}").format(
            table=psql.Identifier(table),
        )
    return stmt, params


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------


def _tool_schemas() -> list[Tool]:
    string_schema: dict[str, Any] = {"type": "string"}
    object_schema: dict[str, Any] = {"type": "object"}
    array_schema: dict[str, Any] = {"type": "array"}
    int_schema: dict[str, Any] = {"type": "integer"}
    return [
        Tool(
            name="db.query",
            description="Execute a parameterized SELECT; returns rows as list[dict].",
            inputSchema={
                "type": "object",
                "required": ["sql"],
                "properties": {
                    "sql": string_schema,
                    "params": array_schema,
                    "return_rows": {"type": "boolean"},
                },
            },
        ),
        Tool(
            name="db.exec",
            description="Execute a DML / DDL statement; returns affected rowcount.",
            inputSchema={
                "type": "object",
                "required": ["sql"],
                "properties": {"sql": string_schema, "params": array_schema},
            },
        ),
        Tool(
            name="db.insert",
            description="Parameterized INSERT keyed by column->value.",
            inputSchema={
                "type": "object",
                "required": ["table", "row"],
                "properties": {"table": string_schema, "row": object_schema},
            },
        ),
        Tool(
            name="db.delete",
            description="Parameterized DELETE keyed by column->value WHERE.",
            inputSchema={
                "type": "object",
                "required": ["table", "where"],
                "properties": {"table": string_schema, "where": object_schema},
            },
        ),
        Tool(
            name="db.assert_row_exists",
            description="Assert >=1 row matches the WHERE filter.",
            inputSchema={
                "type": "object",
                "required": ["table", "where"],
                "properties": {"table": string_schema, "where": object_schema},
            },
        ),
        Tool(
            name="db.assert_row_count",
            description="Assert an exact row count matches the WHERE filter.",
            inputSchema={
                "type": "object",
                "required": ["table", "where", "count"],
                "properties": {
                    "table": string_schema,
                    "where": object_schema,
                    "count": int_schema,
                },
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Bundled server
# ---------------------------------------------------------------------------


class PostgresBundledServer:
    """In-process MCP server backed by an :class:`AsyncConnectionPool`.

    Conforms to :class:`suitest_mcp.bundled.in_process_runtime.BundledServer`.
    """

    def __init__(self, provider: McpProviderConfig) -> None:
        self._provider = provider

    async def list_tools(self) -> list[Tool]:
        return _tool_schemas()

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> list[TextContent]:
        pool = await _get_pool(self._provider)
        async with pool.connection() as conn:
            if name == "db.query":
                return await self._tool_query(conn, arguments)
            if name == "db.exec":
                return await self._tool_exec(conn, arguments)
            if name == "db.insert":
                return await self._tool_insert(conn, arguments)
            if name == "db.delete":
                return await self._tool_delete(conn, arguments)
            if name == "db.assert_row_exists":
                return await self._tool_assert_row_exists(conn, arguments)
            if name == "db.assert_row_count":
                return await self._tool_assert_row_count(conn, arguments)
        raise ValueError(f"unknown postgres-mcp tool: {name!r}")

    async def aclose(self) -> None:
        # Pools are shared across sessions for a provider — see module docstring.
        return None

    # ------------------------------------------------------------------ tools

    async def _tool_query(
        self, conn: psycopg.AsyncConnection[Any], args: dict[str, Any]
    ) -> list[TextContent]:
        sql_text = self._require_str(args, "sql")
        params = args.get("params") or []
        return_rows = bool(args.get("return_rows", True))
        async with conn.cursor() as cur:
            await cur.execute(sql_text, params)
            if return_rows and cur.description is not None:
                cols = [c.name for c in cur.description]
                rows = [dict(zip(cols, row, strict=False)) for row in await cur.fetchall()]
                return [TextContent(type="text", text=json.dumps(rows, default=str))]
            return [
                TextContent(
                    type="text", text=json.dumps({"affected": cur.rowcount})
                )
            ]

    async def _tool_exec(
        self, conn: psycopg.AsyncConnection[Any], args: dict[str, Any]
    ) -> list[TextContent]:
        sql_text = self._require_str(args, "sql")
        params = args.get("params") or []
        async with conn.cursor() as cur:
            await cur.execute(sql_text, params)
            return [
                TextContent(
                    type="text", text=json.dumps({"affected": cur.rowcount})
                )
            ]

    async def _tool_insert(
        self, conn: psycopg.AsyncConnection[Any], args: dict[str, Any]
    ) -> list[TextContent]:
        table = self._require_str(args, "table")
        row = self._require_dict(args, "row")
        stmt, params = _build_insert(table, row)
        async with conn.cursor() as cur:
            await cur.execute(stmt, params)
            return [
                TextContent(
                    type="text", text=json.dumps({"affected": cur.rowcount})
                )
            ]

    async def _tool_delete(
        self, conn: psycopg.AsyncConnection[Any], args: dict[str, Any]
    ) -> list[TextContent]:
        table = self._require_str(args, "table")
        where = self._require_dict(args, "where")
        stmt, params = _build_delete(table, where)
        async with conn.cursor() as cur:
            await cur.execute(stmt, params)
            return [
                TextContent(
                    type="text", text=json.dumps({"affected": cur.rowcount})
                )
            ]

    async def _tool_assert_row_exists(
        self, conn: psycopg.AsyncConnection[Any], args: dict[str, Any]
    ) -> list[TextContent]:
        table = self._require_str(args, "table")
        where = self._require_dict(args, "where")
        count = await self._fetch_count(conn, table, where)
        if count < 1:
            raise AssertionError(
                f"db.assert_row_exists: no rows in {table!r} matching {where!r}"
            )
        return [TextContent(type="text", text=json.dumps({"ok": True, "count": count}))]

    async def _tool_assert_row_count(
        self, conn: psycopg.AsyncConnection[Any], args: dict[str, Any]
    ) -> list[TextContent]:
        table = self._require_str(args, "table")
        where = self._require_dict(args, "where")
        expected = args.get("count")
        if not isinstance(expected, int):
            raise ValueError("db.assert_row_count requires integer 'count'")
        actual = await self._fetch_count(conn, table, where)
        if actual != expected:
            raise AssertionError(
                f"db.assert_row_count: expected {expected} got {actual} "
                f"in {table!r} matching {where!r}"
            )
        return [TextContent(type="text", text=json.dumps({"ok": True, "count": actual}))]

    # ------------------------------------------------------------- helpers

    async def _fetch_count(
        self,
        conn: psycopg.AsyncConnection[Any],
        table: str,
        where: dict[str, Any],
    ) -> int:
        stmt, params = _build_count(table, where)
        async with conn.cursor() as cur:
            await cur.execute(stmt, params)
            row = await cur.fetchone()
            if row is None:
                return 0
            value = row[0]
            return int(value) if value is not None else 0

    @staticmethod
    def _require_str(args: dict[str, Any], key: str) -> str:
        value = args.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"missing or invalid {key!r} argument")
        return value

    @staticmethod
    def _require_dict(args: dict[str, Any], key: str) -> dict[str, Any]:
        value = args.get(key)
        if not isinstance(value, dict):
            raise ValueError(f"missing or invalid {key!r} argument (expected object)")
        return value


def build_postgres_server(provider: McpProviderConfig) -> BundledServer:
    """Factory used by :data:`BUNDLED_BUILDERS`."""
    return PostgresBundledServer(provider)


# Register on import — :mod:`suitest_mcp.bundled.in_process_runtime` looks the
# builder up keyed on ``provider.name`` when the client opens an in-process
# session.
register_bundled_builder(PROVIDER_NAME, build_postgres_server)
