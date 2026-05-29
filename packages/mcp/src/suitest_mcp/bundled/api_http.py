"""Bundled api-http-mcp provider (M1c Task 6).

In-process MCP server exposing ``http.*`` tools backed by ``httpx.AsyncClient``.
Speaks the :class:`BundledServer` protocol from
:mod:`suitest_mcp.bundled.in_process_runtime`, which adapts it onto the SDK's
:class:`mcp.server.Server` so the generic :class:`suitest_mcp.client.McpSession`
can talk to it over connected memory streams with zero subprocess overhead.

Tool surface (mirrored in :mod:`suitest_mcp.providers.builtin_specs`):

* ``http.request``           — execute one HTTP request, return a structured
  envelope: ``{status, headers, body_text, body_json, elapsed_ms, url}``.
* ``http.assert_status``     — assert a previous response's status code.
* ``http.assert_json_path``  — assert a JSONPath expression resolves and
  (optionally) equals / regex-matches an expected value.
* ``http.assert_header``     — assert a response header equals a value
  (case-insensitive name match).

Assertion failures raise :class:`AssertionError`; the SDK's tool-call wrapper
catches them and emits an MCP ``CallToolResult`` with ``isError=true``, which
the generic client surfaces as :class:`McpToolFailed`.

The provider holds a single shared :class:`httpx.AsyncClient` for the lifetime
of the session, instantiated lazily on first ``http.request`` and released by
:meth:`aclose` on session teardown.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, cast

import httpx
from jsonpath_ng.ext import parse as jsonpath_parse
from mcp.types import TextContent, Tool

if TYPE_CHECKING:
    from suitest_mcp.models import McpProviderConfig

_DEFAULT_TIMEOUT_SECONDS = 30.0


class ApiHttpServer:
    """``BundledServer`` implementation for the bundled api-http-mcp provider.

    See module docstring for the tool surface. The instance is created per
    in-process session by :func:`build_api_http_server`; concurrent calls into
    the same session share the underlying :class:`httpx.AsyncClient` and its
    connection pool.
    """

    def __init__(self, provider: McpProviderConfig) -> None:
        # ``provider`` is currently unused at runtime — the http tools are
        # stateless and read all knobs (URL, headers, timeout) from per-call
        # arguments. We hold a reference so future workspace-scoped knobs
        # (egress allow-list, default headers, mTLS) can plug in without
        # changing the builder signature.
        self._provider = provider
        self._client: httpx.AsyncClient | None = None

    # -- BundledServer protocol ------------------------------------------------

    async def list_tools(self) -> list[Tool]:
        return _tool_catalog()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name == "http.request":
            return await self._do_request(arguments)
        if name == "http.assert_status":
            return _assert_status(arguments)
        if name == "http.assert_json_path":
            return _assert_json_path(arguments)
        if name == "http.assert_header":
            return _assert_header(arguments)
        raise ValueError(f"unknown tool {name!r}")

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # -- internal --------------------------------------------------------------

    async def _do_request(self, args: dict[str, Any]) -> list[TextContent]:
        method = str(args["method"]).upper()
        url = str(args["url"])
        timeout = float(cast("float", args.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)))
        follow_redirects = bool(args.get("follow_redirects", True))

        headers_obj = args.get("headers")
        headers: dict[str, str] | None
        if headers_obj is None:
            headers = None
        else:
            headers = {str(k): str(v) for k, v in dict(headers_obj).items()}

        json_body = args.get("json")
        raw_body = args.get("body")
        content: str | bytes | None
        if raw_body is None:
            content = None
        elif isinstance(raw_body, str | bytes):
            content = raw_body
        else:
            content = str(raw_body)

        # Per-request client: keeps timeouts/follow_redirects honoured per call
        # without leaking state between unrelated calls. The connection pool
        # cost is negligible for the runner's call rate and keeps semantics
        # easy to reason about.
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=follow_redirects) as client:
            response = await client.request(
                method,
                url,
                headers=headers,
                json=json_body,
                content=content,
            )

        try:
            body_json: Any = response.json()
        except ValueError:
            # httpx raises json.JSONDecodeError (a ValueError subclass) when the
            # body is not JSON. Capture as ValueError so the bundled provider
            # stays robust to either branch of that hierarchy.
            body_json = None

        payload: dict[str, Any] = {
            "status": response.status_code,
            "headers": dict(response.headers),
            "body_text": response.text,
            "body_json": body_json,
            "elapsed_ms": int(response.elapsed.total_seconds() * 1000),
            "url": str(response.url),
        }
        return [TextContent(type="text", text=json.dumps(payload))]


def build_api_http_server(provider: McpProviderConfig) -> ApiHttpServer:
    """Factory matching the ``BundledBuilder`` callable signature."""
    return ApiHttpServer(provider)


# ---------------------------------------------------------------------------
# Tool catalog & stateless assertions.
# ---------------------------------------------------------------------------


def _tool_catalog() -> list[Tool]:
    return [
        Tool(
            name="http.request",
            description="Execute an HTTP request via httpx.AsyncClient.",
            inputSchema={
                "type": "object",
                "required": ["method", "url"],
                "properties": {
                    "method": {"type": "string"},
                    "url": {"type": "string"},
                    "headers": {"type": "object"},
                    "json": {"type": "object"},
                    "body": {"type": "string"},
                    "timeout_seconds": {"type": "number"},
                    "follow_redirects": {"type": "boolean"},
                },
            },
        ),
        Tool(
            name="http.assert_status",
            description="Assert a response status code equals an expected integer.",
            inputSchema={
                "type": "object",
                "required": ["result", "equals"],
                "properties": {
                    "result": {"type": "object"},
                    "equals": {"type": "integer"},
                },
            },
        ),
        Tool(
            name="http.assert_json_path",
            description=(
                "Assert a JSONPath expression resolves on the response body and "
                "optionally equals / matches an expected value."
            ),
            inputSchema={
                "type": "object",
                "required": ["result", "path"],
                "properties": {
                    "result": {"type": "object"},
                    "path": {"type": "string"},
                    "equals": {},
                    "matches": {"type": "string"},
                },
            },
        ),
        Tool(
            name="http.assert_header",
            description=(
                "Assert a response header equals an expected value "
                "(header name match is case-insensitive)."
            ),
            inputSchema={
                "type": "object",
                "required": ["result", "name", "equals"],
                "properties": {
                    "result": {"type": "object"},
                    "name": {"type": "string"},
                    "equals": {"type": "string"},
                },
            },
        ),
    ]


def _assert_status(args: dict[str, Any]) -> list[TextContent]:
    result = _require_result(args)
    actual = int(result["status"])
    expected = int(args["equals"])
    if actual != expected:
        raise AssertionError(f"status {actual} != {expected}")
    return [TextContent(type="text", text="ok")]


def _assert_json_path(args: dict[str, Any]) -> list[TextContent]:
    result = _require_result(args)
    body = result.get("body_json")
    if body is None:
        raise AssertionError("body is not JSON")
    path = str(args["path"])
    matches = [m.value for m in jsonpath_parse(path).find(body)]
    if not matches:
        raise AssertionError(f"jsonpath {path} produced no match")
    actual = matches[0]
    if "equals" in args and actual != args["equals"]:
        raise AssertionError(f"jsonpath {path}: {actual!r} != {args['equals']!r}")
    if "matches" in args:
        pattern = str(args["matches"])
        if re.match(pattern, str(actual)) is None:
            raise AssertionError(f"jsonpath {path}: {actual!r} !~ /{pattern}/")
    return [TextContent(type="text", text=json.dumps({"matched": actual}))]


def _assert_header(args: dict[str, Any]) -> list[TextContent]:
    result = _require_result(args)
    headers_raw = result.get("headers", {})
    if not isinstance(headers_raw, dict):
        raise AssertionError("response headers missing or malformed")
    target = str(args["name"]).lower()
    found: str | None = None
    for key, value in headers_raw.items():
        if str(key).lower() == target:
            found = str(value)
            break
    expected = str(args["equals"])
    if found != expected:
        raise AssertionError(f"header {args['name']}: {found!r} != {expected!r}")
    return [TextContent(type="text", text="ok")]


def _require_result(args: dict[str, Any]) -> dict[str, Any]:
    """Coerce the ``result`` argument into a dict or raise ``AssertionError``.

    Tools that assert against a previous response accept the structured
    envelope produced by ``http.request``. Callers that forget to pass it
    (or pass a stringified JSON instead) get a clear error rather than an
    opaque ``KeyError`` deeper in the call.
    """
    raw = args.get("result")
    if isinstance(raw, dict):
        return cast("dict[str, Any]", raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"`result` is not valid JSON: {exc}") from exc
        if isinstance(parsed, dict):
            return cast("dict[str, Any]", parsed)
    raise AssertionError("`result` must be the http.request response envelope")
