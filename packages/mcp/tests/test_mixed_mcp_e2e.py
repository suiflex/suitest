"""M2-11 — mixed-MCP test case execution proven E2E.

Drives a single logical test case whose steps span **three different MCP
providers** through one :class:`McpInvoker`, exactly as the deterministic runner
does per-step (``step.mcp_provider`` routing). This is the signature capability
from MCP_PLUGINS §10.3 — a case that mixes DB, API, and browser surfaces:

    seed pg  ->  login api  ->  checkout (browser)  ->  verify api  ->  verify db

Real backends used:

* ``postgres-mcp`` (in-process) against a live Postgres — seed + verify rows.
* ``api-http-mcp`` (in-process) against a throwaway stdlib HTTP server — login +
  order verification over real HTTP.
* a stdio subprocess MCP (the ``echo`` mock) standing in for ``playwright-mcp``
  — proves a *subprocess* transport participates in the same case (no browser
  binaries needed in CI).

Skipped unless ``SUITEST_DATABASE_URL`` points at a reachable Postgres.
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any

import pytest
from suitest_mcp.invoker import InvokeContext, McpInvoker
from suitest_mcp.models import McpProviderConfig, McpTransport
from suitest_mcp.pool import McpPool
from suitest_mcp.registry import McpRegistry
from suitest_shared.domain.enums import TargetKind

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from mcp_server_mock import MockMcpServer

pytestmark = pytest.mark.asyncio


def _pg_dsn() -> str | None:
    raw = os.environ.get("SUITEST_DATABASE_URL")
    if not raw:
        return None
    # postgres-mcp uses psycopg (libpq), not the asyncpg driver URL.
    return raw.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgres+asyncpg://", "postgresql://"
    )


# --- minimal recording doubles (mirror test_invoker.py) -------------------


class _RecordingRedis:
    def __init__(self) -> None:
        self.published: dict[str, list[str]] = {}

    async def publish(self, channel: str, payload: str) -> int:
        self.published.setdefault(channel, []).append(payload)
        return 1

    async def aclose(self) -> None:
        return None


class _AuditSession:
    def __init__(self, sink: list[Any]) -> None:
        self._sink = sink

    def add(self, instance: object) -> None:
        self._sink.append(instance)

    async def commit(self) -> None:
        return None


class _AuditFactory:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[_AuditSession]:
        yield _AuditSession(self.rows)


# --- throwaway HTTP app (the "backend under test") ------------------------


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_: Any) -> None:  # silence stderr access log
        return None

    def _json(self, code: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
        if self.path == "/login":
            self._json(200, {"token": "tok_abc123"})
        else:
            self._json(404, {"error": "not found"})

    def do_GET(self) -> None:
        if self.path.startswith("/orders"):
            if self.headers.get("Authorization") != "Bearer tok_abc123":
                self._json(401, {"error": "unauthorized"})
                return
            self._json(200, {"items": [{"sku": "BOOK-01", "qty": 1}]})
        else:
            self._json(404, {"error": "not found"})


@pytest.fixture
def http_app() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        addr = server.server_address
        yield f"http://{addr[0]!s}:{addr[1]!s}"
    finally:
        server.shutdown()
        server.server_close()


# --- registry wiring ------------------------------------------------------


def _registry(dsn: str, mock_command: list[str]) -> McpRegistry:
    reg = McpRegistry()
    reg._by_workspace["ws"] = {
        "postgres-mcp": McpProviderConfig(
            id="builtin:postgres-mcp",
            workspace_id="ws",
            name="postgres-mcp",
            kind="db",
            transport=McpTransport.IN_PROCESS,
            endpoint="in-process://postgres",
            config_json={"dsn": dsn},
        ),
        "api-http-mcp": McpProviderConfig(
            id="builtin:api-http-mcp",
            workspace_id="ws",
            name="api-http-mcp",
            kind="http",
            transport=McpTransport.IN_PROCESS,
            endpoint="in-process://api-http",
        ),
        "playwright-mcp": McpProviderConfig(
            id="builtin:playwright-mcp",
            workspace_id="ws",
            name="playwright-mcp",
            kind="browser",
            transport=McpTransport.STDIO,
            command=mock_command,
            spawn_timeout_seconds=15.0,
        ),
    }
    return reg


def _ctx(step_id: str) -> InvokeContext:
    return InvokeContext(
        workspace_id="ws",
        target_kind=TargetKind.CUSTOM,
        run_id="run-mixed",
        step_id=step_id,
        actor_user_id="u1",
    )


async def test_mixed_mcp_case_executes_end_to_end(
    mock_mcp_server: MockMcpServer, http_app: str
) -> None:
    dsn = _pg_dsn()
    if dsn is None:
        pytest.skip("SUITEST_DATABASE_URL not set — mixed-MCP E2E needs live Postgres")

    from suitest_mcp.bundled.postgres import close_all_pools

    reg = _registry(dsn, mock_mcp_server.command)
    pool = McpPool()
    invoker = McpInvoker(
        registry=reg,
        pool=pool,
        health=None,
        redis_client=_RecordingRedis(),  # type: ignore[arg-type]
        audit_session_factory=_AuditFactory(),
    )

    try:
        # 1) DATA — seed inventory via postgres-mcp.
        await invoker.invoke(
            explicit_provider="postgres-mcp",
            tool="db.exec",
            arguments={
                "sql": "CREATE TABLE IF NOT EXISTS mixed_mcp_inventory "
                "(sku TEXT PRIMARY KEY, qty INT);"
            },
            ctx=_ctx("s1a"),
        )
        await invoker.invoke(
            explicit_provider="postgres-mcp",
            tool="db.exec",
            arguments={
                "sql": "INSERT INTO mixed_mcp_inventory (sku, qty) VALUES ('BOOK-01', 10) "
                "ON CONFLICT (sku) DO UPDATE SET qty = 10;"
            },
            ctx=_ctx("s1b"),
        )

        # 2) BE_REST — login via api-http-mcp; capture the token.
        login = await invoker.invoke(
            explicit_provider="api-http-mcp",
            tool="http.request",
            arguments={"method": "POST", "url": f"{http_app}/login", "json": {"email": "maya"}},
            ctx=_ctx("s2"),
        )
        login_body = json.loads(login.stdout)
        token = login_body["body_json"]["token"]
        assert token == "tok_abc123"

        # 3) FE_WEB — "checkout" through the stdio (browser stand-in) provider.
        checkout = await invoker.invoke(
            explicit_provider="playwright-mcp",
            tool="echo",
            arguments={"action": "checkout", "sku": "BOOK-01"},
            ctx=_ctx("s3"),
        )
        assert "BOOK-01" in checkout.stdout

        # checkout effect: decrement stock (DATA).
        await invoker.invoke(
            explicit_provider="postgres-mcp",
            tool="db.exec",
            arguments={
                "sql": "UPDATE mixed_mcp_inventory SET qty = qty - 1 WHERE sku = 'BOOK-01';"
            },
            ctx=_ctx("s3b"),
        )

        # 4) BE_REST — verify the order via api-http-mcp (auth header required).
        verify_api = await invoker.invoke(
            explicit_provider="api-http-mcp",
            tool="http.request",
            arguments={
                "method": "GET",
                "url": f"{http_app}/orders?latest=true",
                "headers": {"Authorization": f"Bearer {token}"},
            },
            ctx=_ctx("s4"),
        )
        orders = json.loads(verify_api.stdout)["body_json"]
        assert orders["items"][0]["sku"] == "BOOK-01"

        # 5) DATA — verify the persisted stock via postgres-mcp.
        verify_db = await invoker.invoke(
            explicit_provider="postgres-mcp",
            tool="db.query",
            arguments={"sql": "SELECT qty FROM mixed_mcp_inventory WHERE sku = 'BOOK-01';"},
            ctx=_ctx("s5"),
        )
        rows = json.loads(verify_db.stdout)
        assert rows[0]["qty"] == 9
    finally:
        await invoker.invoke(
            explicit_provider="postgres-mcp",
            tool="db.exec",
            arguments={"sql": "DROP TABLE IF EXISTS mixed_mcp_inventory;"},
            ctx=_ctx("cleanup"),
        )
        await pool.shutdown()
        await close_all_pools()
