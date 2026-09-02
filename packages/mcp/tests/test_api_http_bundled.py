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
        "http.assert_pdf_text",
    }
    for t in tools:
        assert t.description, f"{t.name} must have a description"
        assert isinstance(t.input_schema, dict)
        assert t.input_schema["type"] == "object"


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
        "http.assert_pdf_text",
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


# ---------------------------------------------------------------------------
# PDF body assertions
# ---------------------------------------------------------------------------


def _sample_pdf() -> bytes:
    """A hand-rolled one-page PDF with two text lines — no writer library needed."""
    stream = b"BT /F1 12 Tf 50 800 Td (Inspection Report) Tj 0 -20 Td (No. 42/2026) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


@pytest_asyncio.fixture
async def pdf_result(server: ApiHttpServer) -> dict[str, object]:
    """Drive a real PDF response through ``http.request`` to get the envelope."""
    with respx.mock(assert_all_called=True) as router:
        router.get("https://example.test/report.pdf").mock(
            return_value=httpx.Response(
                200,
                content=_sample_pdf(),
                headers={"content-type": "application/pdf"},
            )
        )
        out = await server.call_tool(
            "http.request",
            {"method": "GET", "url": "https://example.test/report.pdf"},
        )
    return json.loads(_text(out))


async def test_request_carries_base64_body_for_binary_content(
    pdf_result: dict[str, object],
) -> None:
    assert isinstance(pdf_result["body_base64"], str)


async def test_request_omits_base64_body_for_json(server: ApiHttpServer) -> None:
    with respx.mock(assert_all_called=True) as router:
        router.get("https://example.test/ping").mock(
            return_value=httpx.Response(200, json={"pong": True})
        )
        out = await server.call_tool(
            "http.request", {"method": "GET", "url": "https://example.test/ping"}
        )
    assert "body_base64" not in json.loads(_text(out))


async def test_assert_pdf_text_contains_passes(
    server: ApiHttpServer, pdf_result: dict[str, object]
) -> None:
    out = await server.call_tool(
        "http.assert_pdf_text",
        {"result": pdf_result, "contains": ["Inspection Report"], "matches": r"No\.\s*\d+"},
    )
    assert json.loads(_text(out))["chars"] > 0


async def test_assert_pdf_text_missing_substring_raises(
    server: ApiHttpServer, pdf_result: dict[str, object]
) -> None:
    with pytest.raises(AssertionError, match="does not contain"):
        await server.call_tool(
            "http.assert_pdf_text", {"result": pdf_result, "contains": ["Nowhere"]}
        )


async def test_assert_pdf_text_page_out_of_range_raises(
    server: ApiHttpServer, pdf_result: dict[str, object]
) -> None:
    with pytest.raises(AssertionError, match="out of range"):
        await server.call_tool("http.assert_pdf_text", {"result": pdf_result, "page": 9})


async def test_assert_pdf_text_on_non_binary_body_raises(server: ApiHttpServer) -> None:
    with pytest.raises(AssertionError, match="no binary body"):
        await server.call_tool(
            "http.assert_pdf_text",
            {"result": {"status": 200, "headers": {}, "body_text": "{}"}, "contains": ["x"]},
        )
