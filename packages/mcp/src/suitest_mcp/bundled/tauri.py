"""Bundled tauri-mcp provider — desktop testing for Tauri 2 applications.

Like :mod:`suitest_mcp.bundled.slint`, this is a **bridge, not a driver**: it
owns the application process and translates Suitest's stable ``tauri.*`` step
contract onto something the app already speaks. Unlike Slint, that something is
not a bespoke protocol — it is **W3C WebDriver**, served from inside the app by
`tauri-plugin-wdio-webdriver`. Two consequences worth knowing:

* It works on macOS. The standalone ``tauri-driver`` binary drives the
  platform's native WebDriver and exists only for Windows and Linux; an
  in-process server sidesteps that entirely, which is how the official
  ``@wdio/tauri-service`` supports macOS too.
* Nothing here is Companion-specific. Any Tauri app that registers the plugin
  is drivable by this provider, and the app's own code does not have to know it
  is under test.

The app under test must therefore be built with the plugin registered — the
same bargain Slint makes, where the app has to embed an MCP server. The
recommended shape is a cargo feature so a release build carries no server::

    [features]
    wdio = ["dep:tauri-plugin-wdio-webdriver"]

    #[cfg(feature = "wdio")]
    let builder = builder.plugin(tauri_plugin_wdio_webdriver::init());

Tool surface (mirrored in :mod:`suitest_mcp.providers.builtin_specs`):

* ``tauri.launch``          — spawn the binary, wait for the WebDriver server,
  open a session.
* ``tauri.close``           — end the session and stop the process.
* ``tauri.click``           — click the first element matching a selector.
* ``tauri.type_text``       — send text to an element.
* ``tauri.get_text``        — read an element's rendered text.
* ``tauri.assert_text``     — assert an element's text contains / equals.
* ``tauri.assert_visible``  — assert an element exists and is displayed.
* ``tauri.eval``            — run JavaScript in the webview and return its
  value. This is the seam onto the Rust side: the page's own
  ``window.__TAURI_INTERNALS__.invoke`` reaches real commands, so a step can
  assert on what the backend actually did rather than only on the DOM.
* ``tauri.screenshot``      — PNG of the window, returned as an image block so
  the runner files it as a SCREENSHOT artifact.

Assertion failures raise :class:`AssertionError`; the SDK's tool-call wrapper
turns those into an MCP error result, which the generic client surfaces as
:class:`suitest_mcp.client.McpToolFailed`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from typing import TYPE_CHECKING, Any, cast

import httpx
from mcp.types import EmbeddedResource, ImageContent, TextContent, Tool

from suitest_mcp.bundled.in_process_runtime import register_bundled_builder

if TYPE_CHECKING:
    from suitest_mcp.models import McpProviderConfig

PROVIDER_NAME = "tauri-mcp"

_HOST = "127.0.0.1"
#: Default port of `tauri-plugin-wdio-webdriver`; matches the plugin's own
#: default so a plain app build needs no extra configuration.
_DEFAULT_PORT = 4445
_DEFAULT_LAUNCH_TIMEOUT = 60.0
_DEFAULT_CALL_TIMEOUT = 30.0
#: The key a W3C WebDriver response uses to carry an element reference.
_ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"


class TauriServer:
    """``BundledServer`` implementation for the bundled tauri-mcp provider.

    One instance per in-process session. It holds at most one application
    process and one WebDriver session; ``tauri.launch`` twice replaces the
    first, and teardown always stops both.
    """

    def __init__(self, provider: McpProviderConfig) -> None:
        self._provider = provider
        self._proc: asyncio.subprocess.Process | None = None
        self._client: httpx.AsyncClient | None = None
        self._session_id: str | None = None
        self._base: str = f"http://{_HOST}:{_DEFAULT_PORT}"
        #: Set when launch spawned the process, so close only kills what it started.
        self._owns_process = False

    # -- BundledServer protocol ------------------------------------------------

    async def list_tools(self) -> list[Tool]:
        return _tool_catalog()

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> list[TextContent | ImageContent | EmbeddedResource]:
        if name == "tauri.launch":
            return [TextContent(type="text", text=await self._launch(arguments))]
        if name == "tauri.close":
            await self._stop()
            return [TextContent(type="text", text="application stopped")]
        if name == "tauri.screenshot":
            return [
                ImageContent(
                    type="image",
                    data=await self._screenshot(),
                    mimeType="image/png",
                )
            ]
        if name == "tauri.click":
            await self._click(arguments)
            return [TextContent(type="text", text="ok")]
        if name == "tauri.type_text":
            await self._type_text(arguments)
            return [TextContent(type="text", text="ok")]
        if name == "tauri.get_text":
            return [TextContent(type="text", text=await self._text_of(arguments))]
        if name == "tauri.assert_text":
            return [TextContent(type="text", text=await self._assert_text(arguments))]
        if name == "tauri.assert_visible":
            return [TextContent(type="text", text=await self._assert_visible(arguments))]
        if name == "tauri.eval":
            return [TextContent(type="text", text=json.dumps(await self._eval(arguments)))]
        raise AssertionError(f"unknown tool: {name}")

    async def aclose(self) -> None:
        await self._stop()

    # -- lifecycle -------------------------------------------------------------

    async def _launch(self, arguments: dict[str, Any]) -> str:
        """Start the app (unless one is already running) and open a session.

        ``command`` is optional: a suite can point the provider at an app that
        is already running — a ``tauri dev`` session during local development,
        say — by giving only ``port``.
        """
        await self._stop()

        port = int(arguments.get("port") or _DEFAULT_PORT)
        self._base = f"http://{_HOST}:{port}"
        timeout = float(arguments.get("timeout_seconds") or _DEFAULT_LAUNCH_TIMEOUT)
        self._client = httpx.AsyncClient(timeout=_DEFAULT_CALL_TIMEOUT)

        command = _command_of(arguments)
        if command:
            env = {
                **os.environ,
                **self._provider.env,
                **{str(k): str(v) for k, v in (arguments.get("env") or {}).items()},
            }
            self._proc = await asyncio.create_subprocess_exec(
                *command,
                env=env,
                cwd=arguments.get("cwd") or None,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            self._owns_process = True

        await self._await_ready(timeout)
        self._session_id = await self._open_session()
        return f"session {self._session_id} on {self._base}"

    async def _await_ready(self, budget_seconds: float) -> None:
        """Poll ``GET /status`` until the embedded server answers.

        A Tauri app has to create its window and start the plugin's listener
        before it can serve anything, and on a cold start that is not instant.
        Polling beats a fixed sleep, which would either be flaky or slow.
        """
        deadline = time.monotonic() + budget_seconds
        last: str = "no attempt made"
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.returncode is not None:
                raise AssertionError(
                    f"the application exited with code {self._proc.returncode} before "
                    f"its WebDriver server answered on {self._base}"
                )
            try:
                response = await self._http().get(f"{self._base}/status")
                if response.status_code == httpx.codes.OK:
                    return
                last = f"HTTP {response.status_code}"
            except httpx.HTTPError as exc:
                last = str(exc)
            await asyncio.sleep(0.25)
        raise AssertionError(
            f"no WebDriver server on {self._base} after {budget_seconds:g}s ({last}). "
            "Is the app built with the wdio plugin registered?"
        )

    async def _open_session(self) -> str:
        payload = await self._post("/session", {"capabilities": {"alwaysMatch": {}}})
        value = payload.get("value") or {}
        session_id = value.get("sessionId") or payload.get("sessionId")
        if not isinstance(session_id, str):
            raise AssertionError(f"WebDriver did not return a session id: {payload!r}")
        return session_id

    async def _stop(self) -> None:
        if self._session_id is not None and self._client is not None:
            # Best-effort: the app may already be gone, and failing to close a
            # session must not mask whatever actually ended the test.
            with contextlib.suppress(httpx.HTTPError):
                await self._client.delete(f"{self._base}/session/{self._session_id}")
            self._session_id = None
        if self._proc is not None and self._owns_process:
            if self._proc.returncode is None:
                self._proc.terminate()
                with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
                    await asyncio.wait_for(self._proc.wait(), timeout=5)
                if self._proc.returncode is None:
                    self._proc.kill()
                    await self._proc.wait()
            self._proc = None
            self._owns_process = False
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # -- WebDriver plumbing ----------------------------------------------------

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise AssertionError("call tauri.launch before any other tauri.* tool")
        return self._client

    def _session(self) -> str:
        if self._session_id is None:
            raise AssertionError("call tauri.launch before any other tauri.* tool")
        return self._session_id

    async def _post(
        self, path: str, body: dict[str, Any], *, allow_error: bool = False
    ) -> dict[str, Any]:
        response = await self._http().post(f"{self._base}{path}", json=body)
        return _unwrap(response, path, allow_error=allow_error)

    async def _get(self, path: str) -> dict[str, Any]:
        response = await self._http().get(f"{self._base}{path}")
        return _unwrap(response, path)

    async def _find(self, arguments: dict[str, Any]) -> str:
        """Resolve a selector to an element reference, retrying until it appears.

        A React app renders after the window is up, so the first look can lose a
        race the test did not intend to run. Retrying inside the provider keeps
        that timing detail out of every suite that uses it.
        """
        using, value = _selector_of(arguments)
        timeout = float(arguments.get("timeout_seconds") or 5.0)
        deadline = time.monotonic() + timeout
        while True:
            payload = await self._post(
                f"/session/{self._session()}/element",
                {"using": using, "value": value},
                allow_error=True,
            )
            element = (payload.get("value") or {}).get(_ELEMENT_KEY)
            if isinstance(element, str):
                return element
            if time.monotonic() >= deadline:
                raise AssertionError(f"no element matched {using} {value!r} within {timeout:g}s")
            await asyncio.sleep(0.15)

    # -- tools -----------------------------------------------------------------

    async def _click(self, arguments: dict[str, Any]) -> None:
        element = await self._find(arguments)
        await self._post(f"/session/{self._session()}/element/{element}/click", {})

    async def _type_text(self, arguments: dict[str, Any]) -> None:
        element = await self._find(arguments)
        text = str(arguments.get("text", ""))
        if arguments.get("clear", False):
            await self._post(f"/session/{self._session()}/element/{element}/clear", {})
        await self._post(
            f"/session/{self._session()}/element/{element}/value",
            {"text": text},
        )

    async def _text_of(self, arguments: dict[str, Any]) -> str:
        element = await self._find(arguments)
        payload = await self._get(f"/session/{self._session()}/element/{element}/text")
        return str(payload.get("value", ""))

    async def _assert_text(self, arguments: dict[str, Any]) -> str:
        actual = await self._text_of(arguments)
        if "equals" in arguments:
            expected = str(arguments["equals"])
            if actual != expected:
                raise AssertionError(f"text {actual!r} != {expected!r}")
        elif "contains" in arguments:
            needle = str(arguments["contains"])
            if needle not in actual:
                raise AssertionError(f"text {actual!r} does not contain {needle!r}")
        else:
            raise AssertionError("tauri.assert_text needs `equals` or `contains`")
        return "ok"

    async def _assert_visible(self, arguments: dict[str, Any]) -> str:
        """Assert an element is (or, with ``absent``, is not) displayed.

        The negative case is its own argument rather than a second tool because
        "this must not be on screen" is exactly as common an expectation as the
        positive one — an error bar that should not appear, for instance.
        """
        absent = bool(arguments.get("absent", False))
        try:
            element = await self._find(arguments)
        except AssertionError:
            if absent:
                return "ok"
            raise
        payload = await self._get(f"/session/{self._session()}/element/{element}/displayed")
        displayed = bool(payload.get("value", False))
        if absent and displayed:
            using, value = _selector_of(arguments)
            raise AssertionError(f"{using} {value!r} is displayed but was expected absent")
        if not absent and not displayed:
            using, value = _selector_of(arguments)
            raise AssertionError(f"{using} {value!r} exists but is not displayed")
        return "ok"

    async def _eval(self, arguments: dict[str, Any]) -> Any:
        script = str(arguments["script"])
        args = list(arguments.get("args") or [])
        payload = await self._post(
            f"/session/{self._session()}/execute/sync",
            {"script": script, "args": args},
        )
        return payload.get("value")

    async def _screenshot(self) -> str:
        payload = await self._get(f"/session/{self._session()}/screenshot")
        return str(payload.get("value", ""))


def _command_of(arguments: dict[str, Any]) -> list[str]:
    raw = arguments.get("command")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    return [str(part) for part in cast("list[Any]", raw)]


def _selector_of(arguments: dict[str, Any]) -> tuple[str, str]:
    """The element a step addressed, as a W3C ``(using, value)`` pair."""
    if "css" in arguments:
        return "css selector", str(arguments["css"])
    if "xpath" in arguments:
        return "xpath", str(arguments["xpath"])
    if "selector" in arguments:
        return "css selector", str(arguments["selector"])
    raise AssertionError("a selector is required: pass `css`, `xpath`, or `selector`")


def _unwrap(response: httpx.Response, path: str, *, allow_error: bool = False) -> dict[str, Any]:
    """Turn a WebDriver response into a payload dict, or raise its error.

    WebDriver reports failures in the body rather than only in the status line,
    so an unread error would surface later as a confusing missing key.
    """
    try:
        payload = cast("dict[str, Any]", response.json())
    except ValueError as exc:
        raise AssertionError(f"{path}: WebDriver returned non-JSON: {response.text[:200]}") from exc
    value = payload.get("value")
    if isinstance(value, dict) and "error" in value and not allow_error:
        message = value.get("message") or value["error"]
        raise AssertionError(f"{path}: {value['error']}: {message}")
    return payload


def build_tauri_server(provider: McpProviderConfig) -> TauriServer:
    """Factory matching the ``BundledBuilder`` callable signature."""
    return TauriServer(provider)


def _tool_catalog() -> list[Tool]:
    selector_props: dict[str, Any] = {
        "css": {"type": "string"},
        "xpath": {"type": "string"},
        "selector": {"type": "string"},
        "timeout_seconds": {"type": "number"},
    }
    return [
        Tool(
            name="tauri.launch",
            description=(
                "Start a Tauri application and open a WebDriver session against its "
                "embedded server. Omit `command` to attach to an app already running."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": ["string", "array"], "items": {"type": "string"}},
                    "cwd": {"type": "string"},
                    "env": {"type": "object"},
                    "port": {"type": "integer"},
                    "timeout_seconds": {"type": "number"},
                },
            },
        ),
        Tool(
            name="tauri.close",
            description="End the WebDriver session and stop the application.",
            input_schema={"type": "object", "properties": {}},
        ),
        Tool(
            name="tauri.click",
            description="Click the first element matching the selector.",
            input_schema={"type": "object", "properties": selector_props},
        ),
        Tool(
            name="tauri.type_text",
            description="Send text to the element matching the selector.",
            input_schema={
                "type": "object",
                "required": ["text"],
                "properties": {
                    **selector_props,
                    "text": {"type": "string"},
                    "clear": {"type": "boolean"},
                },
            },
        ),
        Tool(
            name="tauri.get_text",
            description="Return the rendered text of the matching element.",
            input_schema={"type": "object", "properties": selector_props},
        ),
        Tool(
            name="tauri.assert_text",
            description="Assert the matching element's text equals or contains a value.",
            input_schema={
                "type": "object",
                "properties": {
                    **selector_props,
                    "equals": {"type": "string"},
                    "contains": {"type": "string"},
                },
            },
        ),
        Tool(
            name="tauri.assert_visible",
            description=(
                "Assert the matching element is displayed, or with `absent` that no such "
                "element is on screen."
            ),
            input_schema={
                "type": "object",
                "properties": {**selector_props, "absent": {"type": "boolean"}},
            },
        ),
        Tool(
            name="tauri.eval",
            description=(
                "Run JavaScript in the webview and return its value. Reaches the Rust "
                "backend through the page's own window.__TAURI_INTERNALS__.invoke."
            ),
            input_schema={
                "type": "object",
                "required": ["script"],
                "properties": {"script": {"type": "string"}, "args": {"type": "array"}},
            },
        ),
        Tool(
            name="tauri.screenshot",
            description="PNG screenshot of the application window.",
            input_schema={"type": "object", "properties": {}},
        ),
    ]


register_bundled_builder(PROVIDER_NAME, build_tauri_server)
