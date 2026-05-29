"""Bundled ``api-http-mcp`` provider tests (M1c Task 6).

Exercises the in-process provider in two layers:

1. **Direct unit tests** on :class:`ApiHttpServer` (no MCP wire), proving the
   tool catalog and assertion helpers behave correctly. Outbound HTTP traffic
   is intercepted with ``respx`` so the suite stays hermetic — no network egress.
2. **Integration smoke** through :func:`suitest_mcp.client.open_session`,
   proving the in-process memory-stream transport and the bundled registry
   wiring round-trip cleanly (``tools/list``, ``tools/call``).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
import respx
from mcp.types import TextContent
from suitest_mcp.bundled.api_http import ApiHttpServer, build_api_http_server
from suitest_mcp.client import McpSession, open_session
from suitest_mcp.errors import McpToolFailed
from suitest_mcp.models import McpProviderConfig, McpTransport

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_provider() -> McpProviderConfig:
    return McpProviderConfig(
        id=f"prov-api-http-{uuid.uuid4()}",
        workspace_id="ws-test",
        name="api-http-mcp",
        kind="api-http-mcp",
        transport=McpTransport.IN_PROCESS,
        endpoint="in-process://api-http",
        max_sessions=2,
        spawn_timeout_seconds=10.0,
        call_timeout_seconds=10.0,
    )


@pytest.fixture
def server() -> ApiHttpServer:
    return build_api_http_server(_make_provider())


@pytest_asyncio.fixture
async def session() -> AsyncIterator[McpSession]:
    sess = await open_session(_make_provider())
    try:
        yield sess
    finally:
        await sess.cleanup()


def _text(blocks: list[TextContent]) -> str:
    """Concatenate the ``.text`` from one or more :class:`TextContent` blocks."""
    return "".join(b.text for b in blocks)


# ---------------------------------------------------------------------------
# Unit tests: tool catalog & dispatch
# ---------------------------------------------------------------------------


async def test_list_tools_advertises_four_http_tools(server: ApiHttpServer) -> None:
    tools = await server.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "http.request",
        "http.assert_status",
        "http.assert_json_path",
        "http.assert_header",
    }
    for t in tools:
        assert t.description, f"{t.name} must have a description"
        assert isinstance(t.inputSchema, dict)
        assert t.inputSchema["type"] == "object"


async def test_call_tool_unknown_raises(server: ApiHttpServer) -> None:
    with pytest.raises(ValueError, match="unknown tool"):
        await server.call_tool("http.bogus", {})


# ---------------------------------------------------------------------------
# http.request: end-to-end mock through respx
# ---------------------------------------------------------------------------


async def test_http_request_returns_envelope(server: ApiHttpServer) -> None:
    with respx.mock(assert_all_called=True) as router:
        router.get("https://example.test/v1/widgets").mock(
            return_value=httpx.Response(
                200,
                json={"items": [{"id": 1, "name": "wrench"}]},
                headers={"x-trace": "abc"},
            )
        )
        out = await server.call_tool(
            "http.request",
            {"method": "GET", "url": "https://example.test/v1/widgets"},
        )
    payload = json.loads(_text(out))
    assert payload["status"] == 200
    assert payload["body_json"] == {"items": [{"id": 1, "name": "wrench"}]}
    # httpx normalises header names to lowercase; verify presence
    assert any(k.lower() == "x-trace" for k in payload["headers"])
    assert payload["url"] == "https://example.test/v1/widgets"
    assert isinstance(payload["elapsed_ms"], int)


async def test_http_request_with_json_body_posts_payload(
    server: ApiHttpServer,
) -> None:
    seen_payloads: list[dict[str, object]] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(json.loads(request.content.decode()))
        return httpx.Response(201, json={"ok": True})

    with respx.mock(assert_all_called=True) as router:
        router.post("https://example.test/v1/widgets").mock(side_effect=_capture)
        out = await server.call_tool(
            "http.request",
            {
                "method": "POST",
                "url": "https://example.test/v1/widgets",
                "json": {"name": "wrench", "qty": 3},
            },
        )
    payload = json.loads(_text(out))
    assert payload["status"] == 201
    assert seen_payloads == [{"name": "wrench", "qty": 3}]


async def test_http_request_non_json_body_yields_none_body_json(
    server: ApiHttpServer,
) -> None:
    with respx.mock(assert_all_called=True) as router:
        router.get("https://example.test/plain").mock(
            return_value=httpx.Response(200, text="plain text body")
        )
        out = await server.call_tool(
            "http.request",
            {"method": "GET", "url": "https://example.test/plain"},
        )
    payload = json.loads(_text(out))
    assert payload["body_text"] == "plain text body"
    assert payload["body_json"] is None


# ---------------------------------------------------------------------------
# Assertion tools
# ---------------------------------------------------------------------------


async def test_assert_status_pass(server: ApiHttpServer) -> None:
    out = await server.call_tool(
        "http.assert_status",
        {"result": {"status": 200, "headers": {}}, "equals": 200},
    )
    assert _text(out) == "ok"


async def test_assert_status_mismatch_raises(server: ApiHttpServer) -> None:
    with pytest.raises(AssertionError, match=r"status 500 != 200"):
        await server.call_tool(
            "http.assert_status",
            {"result": {"status": 500, "headers": {}}, "equals": 200},
        )


async def test_assert_json_path_equals_simple(server: ApiHttpServer) -> None:
    out = await server.call_tool(
        "http.assert_json_path",
        {
            "result": {"status": 200, "headers": {}, "body_json": {"foo": "bar"}},
            "path": "$.foo",
            "equals": "bar",
        },
    )
    matched = json.loads(_text(out))
    assert matched == {"matched": "bar"}


async def test_assert_json_path_nested(server: ApiHttpServer) -> None:
    out = await server.call_tool(
        "http.assert_json_path",
        {
            "result": {
                "status": 200,
                "headers": {},
                "body_json": {"items": [{"id": 1}, {"id": 2}]},
            },
            "path": "$.items[1].id",
            "equals": 2,
        },
    )
    assert json.loads(_text(out)) == {"matched": 2}


async def test_assert_json_path_no_match_raises(server: ApiHttpServer) -> None:
    with pytest.raises(AssertionError, match="no match"):
        await server.call_tool(
            "http.assert_json_path",
            {
                "result": {"status": 200, "headers": {}, "body_json": {"foo": 1}},
                "path": "$.missing",
            },
        )


async def test_assert_json_path_regex_matches(server: ApiHttpServer) -> None:
    out = await server.call_tool(
        "http.assert_json_path",
        {
            "result": {
                "status": 200,
                "headers": {},
                "body_json": {"id": "req-1234"},
            },
            "path": "$.id",
            "matches": r"^req-\d+$",
        },
    )
    assert json.loads(_text(out)) == {"matched": "req-1234"}


async def test_assert_json_path_no_body_raises(server: ApiHttpServer) -> None:
    with pytest.raises(AssertionError, match="body is not JSON"):
        await server.call_tool(
            "http.assert_json_path",
            {
                "result": {"status": 200, "headers": {}, "body_json": None},
                "path": "$.foo",
            },
        )


async def test_assert_header_case_insensitive_pass(server: ApiHttpServer) -> None:
    out = await server.call_tool(
        "http.assert_header",
        {
            "result": {"status": 200, "headers": {"X-Trace": "abc"}},
            "name": "x-trace",
            "equals": "abc",
        },
    )
    assert _text(out) == "ok"


async def test_assert_header_mismatch_raises(server: ApiHttpServer) -> None:
    with pytest.raises(AssertionError, match="header"):
        await server.call_tool(
            "http.assert_header",
            {
                "result": {"status": 200, "headers": {"x-trace": "xyz"}},
                "name": "x-trace",
                "equals": "abc",
            },
        )


# ---------------------------------------------------------------------------
# Integration: drive the bundled provider through the generic client
# ---------------------------------------------------------------------------


async def test_in_process_session_lists_tools(session: McpSession) -> None:
    tools = await session.list_tools()
    names = {t["name"] for t in tools}
    assert names == {
        "http.request",
        "http.assert_status",
        "http.assert_json_path",
        "http.assert_header",
    }


async def test_in_process_session_http_request_round_trip(
    session: McpSession,
) -> None:
    with respx.mock(assert_all_called=True) as router:
        router.get("https://example.test/ping").mock(
            return_value=httpx.Response(200, json={"pong": True})
        )
        result = await session.call_tool(
            "http.request",
            {"method": "GET", "url": "https://example.test/ping"},
            timeout_seconds=10.0,
        )
    assert result.ok
    payload = json.loads(result.stdout)
    assert payload["status"] == 200
    assert payload["body_json"] == {"pong": True}


async def test_in_process_session_assertion_failure_surfaces_as_tool_failed(
    session: McpSession,
) -> None:
    with pytest.raises(McpToolFailed):
        await session.call_tool(
            "http.assert_status",
            {"result": {"status": 500, "headers": {}}, "equals": 200},
            timeout_seconds=10.0,
        )
