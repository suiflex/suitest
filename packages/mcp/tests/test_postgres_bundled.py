"""Bundled ``postgres-mcp`` provider integration tests (M1c Task 8).

Boots a real Postgres testcontainer once per session and drives the bundled
in-process server through the generic :func:`suitest_mcp.client.open_session`
client — exercises the same code path the runner will use, including the
in-memory streams transport, the SDK ``ClientSession`` handshake, and the
``psycopg`` connection pool.

The SQL-injection test exists to make the parameterization guarantee
load-bearing: if someone ever swaps :class:`psycopg.sql.Identifier` for an
``f"..."`` formatter, the hostile column / value would execute the ``DROP
TABLE`` and the assertion would fail loudly.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterator

import psycopg
import pytest
import pytest_asyncio
from suitest_mcp.bundled.postgres import (
    PROVIDER_KIND,
    PROVIDER_NAME,
    close_all_pools,
)
from suitest_mcp.client import McpSession, open_session
from suitest_mcp.errors import McpToolFailed
from suitest_mcp.models import McpProviderConfig, McpTransport
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def postgres_dsn() -> Iterator[str]:
    """Boot a Postgres 16 testcontainer and yield a libpq DSN for psycopg.

    Uses the ``pgvector/pgvector:pg16`` image to match the rest of the repo so
    Docker layer caches stay warm.
    """
    with PostgresContainer("pgvector/pgvector:pg16") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(5432)
        dsn = (
            f"postgresql://{container.username}:{container.password}"
            f"@{host}:{port}/{container.dbname}"
        )
        yield dsn


@pytest.fixture
def schema(postgres_dsn: str) -> Iterator[None]:
    """Reset the ``widgets`` table around each test for isolation."""
    with psycopg.connect(postgres_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS widgets ("
            "id SERIAL PRIMARY KEY, name TEXT NOT NULL, qty INTEGER NOT NULL)"
        )
        cur.execute("TRUNCATE widgets RESTART IDENTITY")
    yield
    with psycopg.connect(postgres_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE widgets RESTART IDENTITY")


def _make_provider(dsn: str) -> McpProviderConfig:
    return McpProviderConfig(
        id=f"prov-postgres-{uuid.uuid4()}",
        workspace_id="ws-test",
        name=PROVIDER_NAME,
        kind=PROVIDER_KIND,
        transport=McpTransport.IN_PROCESS,
        endpoint="",
        config_json={"dsn": dsn},
        max_sessions=2,
        spawn_timeout_seconds=10.0,
        call_timeout_seconds=10.0,
    )


@pytest_asyncio.fixture
async def session(postgres_dsn: str) -> AsyncIterator[McpSession]:
    sess = await open_session(_make_provider(postgres_dsn))
    try:
        yield sess
    finally:
        await sess.cleanup()


@pytest_asyncio.fixture(autouse=True)
async def _pool_teardown() -> AsyncIterator[None]:
    """Close every pool the module opened after each test."""
    yield
    await close_all_pools()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_spec_metadata() -> None:
    """Spec metadata is the contract the registry / docs key on."""
    assert PROVIDER_NAME == "postgres-mcp"
    assert PROVIDER_KIND == "postgres-mcp"


async def test_lists_six_tools(session: McpSession, schema: None) -> None:
    tools = await session.list_tools()
    names = {t["name"] for t in tools}
    assert names == {
        "db.query",
        "db.exec",
        "db.insert",
        "db.delete",
        "db.assert_row_exists",
        "db.assert_row_count",
    }


async def test_query_select_one(session: McpSession, schema: None) -> None:
    result = await session.call_tool("db.query", {"sql": "SELECT 1 AS n"}, timeout_seconds=10.0)
    rows = json.loads(result.stdout)
    assert rows == [{"n": 1}]


async def test_insert_then_query_roundtrip(session: McpSession, schema: None) -> None:
    insert = await session.call_tool(
        "db.insert",
        {"table": "widgets", "row": {"name": "wrench", "qty": 3}},
        timeout_seconds=10.0,
    )
    assert json.loads(insert.stdout) == {"affected": 1}

    rows_result = await session.call_tool(
        "db.query",
        {"sql": "SELECT name, qty FROM widgets ORDER BY id"},
        timeout_seconds=10.0,
    )
    assert json.loads(rows_result.stdout) == [{"name": "wrench", "qty": 3}]


async def test_assert_row_exists_pass_and_fail(session: McpSession, schema: None) -> None:
    await session.call_tool(
        "db.insert",
        {"table": "widgets", "row": {"name": "hammer", "qty": 1}},
        timeout_seconds=10.0,
    )

    ok = await session.call_tool(
        "db.assert_row_exists",
        {"table": "widgets", "where": {"name": "hammer"}},
        timeout_seconds=10.0,
    )
    assert json.loads(ok.stdout)["ok"] is True

    with pytest.raises(McpToolFailed):
        await session.call_tool(
            "db.assert_row_exists",
            {"table": "widgets", "where": {"name": "missing-tool"}},
            timeout_seconds=10.0,
        )


async def test_assert_row_count_exact_match_and_mismatch(session: McpSession, schema: None) -> None:
    for qty in (1, 2, 3):
        await session.call_tool(
            "db.insert",
            {"table": "widgets", "row": {"name": "nut", "qty": qty}},
            timeout_seconds=10.0,
        )

    ok = await session.call_tool(
        "db.assert_row_count",
        {"table": "widgets", "where": {"name": "nut"}, "count": 3},
        timeout_seconds=10.0,
    )
    assert json.loads(ok.stdout) == {"ok": True, "count": 3}

    with pytest.raises(McpToolFailed):
        await session.call_tool(
            "db.assert_row_count",
            {"table": "widgets", "where": {"name": "nut"}, "count": 99},
            timeout_seconds=10.0,
        )


async def test_delete_removes_row(session: McpSession, schema: None) -> None:
    await session.call_tool(
        "db.insert",
        {"table": "widgets", "row": {"name": "screw", "qty": 7}},
        timeout_seconds=10.0,
    )
    delete = await session.call_tool(
        "db.delete",
        {"table": "widgets", "where": {"name": "screw"}},
        timeout_seconds=10.0,
    )
    assert json.loads(delete.stdout) == {"affected": 1}

    rows_result = await session.call_tool(
        "db.query",
        {"sql": "SELECT COUNT(*) AS n FROM widgets"},
        timeout_seconds=10.0,
    )
    assert json.loads(rows_result.stdout) == [{"n": 0}]


async def test_sql_injection_payload_is_parameterized(
    session: McpSession, schema: None, postgres_dsn: str
) -> None:
    """The hostile WHERE value must NOT drop the table."""
    # Seed a row we can verify is still present after the injection attempt.
    await session.call_tool(
        "db.insert",
        {"table": "widgets", "row": {"name": "canary", "qty": 1}},
        timeout_seconds=10.0,
    )
    hostile = "'; DROP TABLE widgets; --"

    # The injection-style value goes into the parameter slot, so the query is a
    # boring "name = $1" with no match. It must NOT raise and the table must
    # still exist afterwards.
    result = await session.call_tool(
        "db.delete",
        {"table": "widgets", "where": {"name": hostile}},
        timeout_seconds=10.0,
    )
    assert json.loads(result.stdout) == {"affected": 0}

    # And the assert_row_exists/count tools must also treat the payload as data.
    with pytest.raises(McpToolFailed):
        await session.call_tool(
            "db.assert_row_exists",
            {"table": "widgets", "where": {"name": hostile}},
            timeout_seconds=10.0,
        )

    # Out-of-band sanity check: the table is still there and the canary row survived.
    with psycopg.connect(postgres_dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT name FROM widgets WHERE name = %s", ("canary",))
        rows = cur.fetchall()
    assert rows == [("canary",)]
