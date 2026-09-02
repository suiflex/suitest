"""Bundled tauri-mcp provider — contract checks that need no Tauri app.

Driving a real application is covered by the desktop suite; what matters here is
that the provider is wired into the bundled registry, advertises exactly the
catalog its builtin spec promises, fails understandably when a step runs before
anything was launched, and speaks W3C WebDriver correctly against a stub.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from suitest_mcp.bundled.in_process_runtime import get_bundled_builder
from suitest_mcp.bundled.tauri import (
    PROVIDER_NAME,
    TauriServer,
    build_tauri_server,
)
from suitest_mcp.models import McpProviderConfig, McpTransport
from suitest_mcp.providers.builtin_specs import BUILTIN_SPECS

_ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"


def _config() -> McpProviderConfig:
    return McpProviderConfig(
        id="builtin:tauri-mcp",
        workspace_id="_builtin_",
        name=PROVIDER_NAME,
        kind="desktop",
        transport=McpTransport.IN_PROCESS,
        endpoint="in-process://tauri",
    )


def test_provider_resolves_through_the_bundled_registry() -> None:
    """The lazy-import entry is what lets the runtime find us without the
    bundled package importing every provider eagerly."""
    assert get_bundled_builder(PROVIDER_NAME) is not None


@pytest.mark.asyncio
async def test_tool_catalog_matches_the_builtin_spec() -> None:
    """The advertised tools and the spec's `config_json` must not drift — the
    spec is what routing and the docs are written against."""
    spec = next(s for s in BUILTIN_SPECS if s.name == PROVIDER_NAME)
    advertised = {t.name for t in await build_tauri_server(_config()).list_tools()}
    assert advertised == set(spec.config_json["tools"])


@pytest.mark.asyncio
async def test_tools_before_launch_say_so() -> None:
    """A step that forgets `tauri.launch` should name the missing step, not
    fail somewhere deep in the HTTP client."""
    server = build_tauri_server(_config())
    with pytest.raises(AssertionError, match=r"tauri\.launch"):
        await server.call_tool("tauri.click", {"css": ".add-btn"})


@pytest.mark.asyncio
async def test_missing_selector_is_reported_as_such() -> None:
    server = _attached(_FakeDriver())
    with pytest.raises(AssertionError, match="a selector is required"):
        await server.call_tool("tauri.click", {})


@pytest.mark.asyncio
async def test_unknown_tool_is_named() -> None:
    server = build_tauri_server(_config())
    with pytest.raises(AssertionError, match=r"unknown tool: tauri\.levitate"):
        await server.call_tool("tauri.levitate", {})


# ---------------------------------------------------------------------------
# WebDriver protocol behaviour, against a stub transport.
# ---------------------------------------------------------------------------


class _FakeDriver:
    """The subset of W3C WebDriver the provider speaks.

    Answers like the embedded server does — including reporting failures in the
    body rather than the status line, which is the case a naive client gets
    wrong.
    """

    def __init__(self, *, text: str = "Nota baru", displayed: bool = True) -> None:
        self.text = text
        self.displayed = displayed
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        #: Selectors that should resolve; anything else answers "no such element".
        self.known = {".note-title", ".add-btn", ".search", ".error-bar"}
        self.missing: set[str] = set()

    async def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body: dict[str, Any] = {}
        if request.content:
            body = json.loads(request.content)
        self.calls.append((request.method, path, body))

        if path == "/status":
            return httpx.Response(200, json={"value": {"ready": True}})
        if path == "/session" and request.method == "POST":
            return httpx.Response(200, json={"value": {"sessionId": "s-1"}})
        if path.endswith("/element") and request.method == "POST":
            value = str(body.get("value", ""))
            if value in self.known and value not in self.missing:
                return httpx.Response(200, json={"value": {_ELEMENT_KEY: "e-1"}})
            return httpx.Response(
                404,
                json={"value": {"error": "no such element", "message": "Unable to locate element"}},
            )
        if path.endswith("/text"):
            return httpx.Response(200, json={"value": self.text})
        if path.endswith("/displayed"):
            return httpx.Response(200, json={"value": self.displayed})
        if path.endswith("/screenshot"):
            return httpx.Response(200, json={"value": "iVBORw0KGgo="})
        if path.endswith("/execute/sync"):
            return httpx.Response(200, json={"value": ["Rapat/2026-08-28/meet-abc-1400.md"]})
        return httpx.Response(200, json={"value": None})


def _attached(driver: _FakeDriver) -> TauriServer:
    """A server already 'launched' against the stub, with no process to own."""
    server = build_tauri_server(_config())
    server._client = httpx.AsyncClient(transport=httpx.MockTransport(driver.handler))
    server._session_id = "s-1"
    return server


@pytest.mark.asyncio
async def test_click_resolves_the_element_then_clicks_it() -> None:
    driver = _FakeDriver()
    server = _attached(driver)
    await server.call_tool("tauri.click", {"css": ".add-btn"})
    paths = [path for _, path, _ in driver.calls]
    assert paths == ["/session/s-1/element", "/session/s-1/element/e-1/click"]


@pytest.mark.asyncio
async def test_type_text_clears_first_only_when_asked() -> None:
    driver = _FakeDriver()
    server = _attached(driver)
    await server.call_tool("tauri.type_text", {"css": ".search", "text": "a"})
    assert not any(path.endswith("/clear") for _, path, _ in driver.calls)

    driver.calls.clear()
    await server.call_tool("tauri.type_text", {"css": ".search", "text": "a", "clear": True})
    assert any(path.endswith("/clear") for _, path, _ in driver.calls)


@pytest.mark.asyncio
async def test_assert_text_contains_and_equals() -> None:
    server = _attached(_FakeDriver(text="Gate review"))
    await server.call_tool("tauri.assert_text", {"css": ".note-title", "contains": "Gate"})
    await server.call_tool("tauri.assert_text", {"css": ".note-title", "equals": "Gate review"})
    with pytest.raises(AssertionError, match="does not contain"):
        await server.call_tool("tauri.assert_text", {"css": ".note-title", "contains": "Retro"})


@pytest.mark.asyncio
async def test_assert_text_without_a_comparison_says_so() -> None:
    server = _attached(_FakeDriver())
    with pytest.raises(AssertionError, match="needs `equals` or `contains`"):
        await server.call_tool("tauri.assert_text", {"css": ".note-title"})


@pytest.mark.asyncio
async def test_assert_visible_absent_passes_when_nothing_matches() -> None:
    """ "This must not be on screen" is as common an expectation as its
    opposite — an error bar that should not appear, for instance."""
    driver = _FakeDriver()
    driver.missing = {".error-bar"}
    server = _attached(driver)
    await server.call_tool("tauri.assert_visible", {"css": ".error-bar", "absent": True})


@pytest.mark.asyncio
async def test_assert_visible_absent_fails_when_the_element_is_there() -> None:
    server = _attached(_FakeDriver(displayed=True))
    with pytest.raises(AssertionError, match="expected absent"):
        await server.call_tool("tauri.assert_visible", {"css": ".error-bar", "absent": True})


@pytest.mark.asyncio
async def test_a_missing_element_names_the_selector() -> None:
    driver = _FakeDriver()
    server = _attached(driver)
    with pytest.raises(AssertionError, match=r"no element matched css selector '\.nope'"):
        await server.call_tool("tauri.click", {"css": ".nope", "timeout_seconds": 0.1})


@pytest.mark.asyncio
async def test_eval_returns_the_scripts_value() -> None:
    """The seam onto Rust: a step asserts on what the backend did, not only on
    what the DOM shows."""
    server = _attached(_FakeDriver())
    blocks = await server.call_tool(
        "tauri.eval",
        {"script": "return window.__TAURI_INTERNALS__.invoke('list_vault')"},
    )
    assert json.loads(blocks[0].text) == ["Rapat/2026-08-28/meet-abc-1400.md"]  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_screenshot_comes_back_as_an_image_block() -> None:
    """The runner turns image blocks into SCREENSHOT artifacts; a text block
    would land as an unreadable blob instead."""
    server = _attached(_FakeDriver())
    blocks = await server.call_tool("tauri.screenshot", {})
    assert blocks[0].type == "image"
    # the field is aliased: constructed as `mimeType`, read as `mime_type`
    assert blocks[0].mime_type == "image/png"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_launch_refuses_a_port_someone_else_is_serving() -> None:
    """Attaching to a stranger's window is worse than failing: the spawned
    process never binds, nobody notices, and every later step drives the wrong
    app."""
    server = build_tauri_server(_config())
    server._client = httpx.AsyncClient(transport=httpx.MockTransport(_FakeDriver().handler))
    with pytest.raises(AssertionError, match="already serving WebDriver"):
        await server.call_tool("tauri.launch", {"command": ["/bin/true"], "timeout_seconds": 1})


@pytest.mark.asyncio
async def test_launch_without_a_server_explains_the_likely_cause() -> None:
    """The usual reason is an app built without the plugin, so say that rather
    than leaving a bare connection error."""
    server = build_tauri_server(_config())
    with pytest.raises(AssertionError, match="wdio plugin"):
        await server.call_tool("tauri.launch", {"port": 1, "timeout_seconds": 0.3})
