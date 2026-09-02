"""Bundled slint-mcp provider — desktop testing for Slint applications (M14).

Slint 1.17 embeds an MCP server *inside the application under test*: build with
``--features slint/mcp`` and run with ``SLINT_EMIT_DEBUG_INFO=1`` and
``SLINT_MCP_PORT=<port>``, and the process serves MCP over Streamable HTTP on
``127.0.0.1:<port>/mcp``. Its tools are ``find_elements_by_id``,
``get_element_properties``, ``click_element``, ``drag_element``,
``set_element_value``, ``dispatch_key_event``, ``invoke_accessibility_action``,
``take_screenshot``, ``start_event_recording``/``stop_event_recording`` and
friends.

So this provider is a **bridge, not a driver**. It owns the app process and
translates Suitest's stable ``slint.*`` step contract onto whatever the running
Slint release calls its tools. Test steps therefore survive Slint renaming its
own surface, which is the whole reason not to point the runner at the app's
endpoint directly.

Tool surface (mirrored in :mod:`suitest_mcp.providers.builtin_specs`):

* ``slint.launch``         — start the app, wait for its MCP port, handshake.
* ``slint.click``          — click the element with the given id.
* ``slint.drag``           — press on an element, drag to another element or to
  a point, release: the gesture behind range selections, sliders and reorders.
* ``slint.set_property``   — set an element's value (text inputs, sliders, ...).
* ``slint.get_property``   — read an element's properties.
* ``slint.element_tree``   — flat dump of the window's elements, for authoring
  steps against an app whose ids you don't know yet.
* ``slint.start_recording`` / ``slint.stop_recording`` — the events Slint
  actually received, and whether it accepted or ignored each one.
* ``slint.start_video`` / ``slint.stop_video`` — sample the window while a
  gesture runs and hand back an MP4, so a run shows the interaction rather than
  its end state.
* ``slint.accessibility_action`` — invoke an accessible action (``Default_``,
  ``Increment``, ``Decrement``, ...) on an element.
* ``slint.press_key``      — send a key/text event to the focused element.
* ``slint.assert_visible`` — element exists and is not fully transparent.
* ``slint.assert_text``    — element's label/value equals or contains a string.
* ``slint.assert_checked`` — element's checked state matches.
* ``slint.assert_value``   — element's value equals a string.
* ``slint.screenshot``     — PNG of the window, returned as an MCP image block
  so the runner stores it as a ``SCREENSHOT`` artifact.
* ``slint.close``          — stop the app.

Assertion failures raise :class:`AssertionError`; the SDK's tool-call wrapper
turns those into ``isError=true``, which the generic client surfaces as
:class:`McpToolFailed`.

Element addressing uses Slint's own ``Component::element-id`` ids, which the
compiler keeps when ``SLINT_EMIT_DEBUG_INFO=1`` is set — no accessibility
annotations are needed in the application. Note that ``find_elements_by_id``
searches *descendants*, so a window's own root id never matches; the root is
reached through ``get_window_properties`` instead.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import shutil
import socket
from typing import TYPE_CHECKING, Any, cast

import httpx
from mcp.types import BlobResourceContents, EmbeddedResource, ImageContent, TextContent, Tool

from suitest_mcp.bundled._video import VIDEO_INTERVAL_MS, VIDEO_MAX_FRAMES, encode_video
from suitest_mcp.bundled.in_process_runtime import BundledServer, register_bundled_builder

if TYPE_CHECKING:
    from collections.abc import Callable

    from suitest_mcp.models import McpProviderConfig

PROVIDER_NAME = "slint-mcp"

_DEFAULT_READY_TIMEOUT = 60.0
_RPC_TIMEOUT = 30.0
# How long a step waits for its target to appear. A UI settles asynchronously —
# a click that opens a pane returns before the pane has rendered — so resolving
# an element has to be a poll, not a single look, or every test is a race.
_DEFAULT_WAIT_SECONDS = 15.0
# Slint's HTTP transport only accepts localhost origins, and binding the probe
# socket to the same interface is what makes "is it up yet" meaningful.
_HOST = "127.0.0.1"
# Video sampling. Slint serves single frames, not a stream, so a "video" here is
# screenshots on a timer stitched by ffmpeg. 5 fps is enough to read a drag or a
# panel opening, and cheap enough not to perturb what it is filming.


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((_HOST, 0))
        return cast("int", sock.getsockname()[1])


def _selector(arguments: dict[str, Any]) -> tuple[str | None, str | None, int]:
    """The element a step addressed: ``(id, label, index)``.

    Follows the selector grammar in ``docs/DESKTOP_TESTING.md`` — id first,
    then accessible label. Slint ids are component-scoped, so one id like
    ``PrimaryButton::ta`` matches every instance of that component on screen;
    ``label`` picks between them by what the user actually sees, and ``index``
    is the blunt fallback when neither is unique.
    """
    element_id = next(
        (
            arguments[k]
            for k in ("id", "element_id", "elementId", "selector")
            if isinstance(arguments.get(k), str) and arguments[k]
        ),
        None,
    )
    label = next(
        (
            arguments[k]
            for k in ("label", "accessible_label", "accessibleLabel", "text")
            if isinstance(arguments.get(k), str) and arguments[k]
        ),
        None,
    )
    if element_id is None and label is None:
        raise AssertionError(
            "no element given — pass `id` as `Component::element-id` "
            "(e.g. `ConnPicker::add-ta`) and/or `label` as its visible text"
        )
    raw_index = arguments.get("index", 0)
    return element_id, label, int(raw_index) if isinstance(raw_index, int) else 0


def _as_text(value: Any) -> str:
    """Compare properties as text: a step writes `equals: 263`, and the app may
    report 263, 263.0 or "263" for the same thing."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _drag_destination(arguments: dict[str, Any]) -> dict[str, Any]:
    """Where a drag ends: an explicit point, or another element's selector.

    Parsed before anything touches the application, so a step that forgot the
    far end of the gesture says so instead of failing later on a lookup.
    """
    x, y = arguments.get("x"), arguments.get("y")
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        return {"x": float(x), "y": float(y)}
    destination = {
        key[3:]: arguments[key] for key in ("to_id", "to_label", "to_index") if key in arguments
    }
    if not destination:
        raise AssertionError(
            "no drag destination — pass `to_id`/`to_label` for another "
            "element, or `x` and `y` for a point"
        )
    return destination


class SlintServer:
    """``BundledServer`` implementation for the bundled slint-mcp provider.

    One instance owns at most one application process for the lifetime of the
    session. ``slint.launch`` starts it, every other tool talks to it, and both
    ``slint.close`` and session teardown stop it — a failed run must not leave a
    window on the operator's screen or a port bound.
    """

    def __init__(self, provider: McpProviderConfig) -> None:
        self._provider = provider
        self._proc: asyncio.subprocess.Process | None = None
        self._port: int | None = None
        self._client: httpx.AsyncClient | None = None
        self._rpc_id = 0
        self._window: dict[str, Any] | None = None
        # One RPC at a time: the video sampler shares this client with the step
        # that is running, and a frame competing with a connect starved the
        # lookup that step was waiting on.
        self._rpc_lock = asyncio.Lock()
        self._video_task: asyncio.Task[None] | None = None
        self._filming = False
        self._video_frames: list[bytes] = []
        self._video_interval_ms = VIDEO_INTERVAL_MS

    # ---------------------------------------------------------------- plumbing

    @property
    def _url(self) -> str:
        return f"http://{_HOST}:{self._port}/mcp"

    async def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        async with self._rpc_lock:
            return await self._rpc_locked(method, params)

    async def _rpc_locked(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """One JSON-RPC round trip to the app's embedded server.

        The transport may answer as plain JSON or as a single SSE ``data:``
        frame depending on negotiation, so both shapes are accepted.
        """
        if self._client is None or self._port is None:
            raise AssertionError("no application running — call `slint.launch` first")
        self._rpc_id += 1
        response = await self._client.post(
            self._url,
            json={
                "jsonrpc": "2.0",
                "id": self._rpc_id,
                "method": method,
                "params": params or {},
            },
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            timeout=_RPC_TIMEOUT,
        )
        response.raise_for_status()
        body = response.text
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            frame = next(
                (line[6:] for line in body.splitlines() if line.startswith("data: ")),
                None,
            )
            if frame is None:
                raise AssertionError(f"unparseable response from the app: {body[:200]}") from None
            payload = json.loads(frame)
        if "error" in payload:
            raise AssertionError(f"{method} failed: {payload['error']}")
        return payload.get("result")

    async def _call(self, tool: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        """Invoke a tool on the app and return its raw content blocks."""
        result = await self._rpc("tools/call", {"name": tool, "arguments": arguments})
        blocks = cast("list[dict[str, Any]]", (result or {}).get("content", []))
        if (result or {}).get("isError"):
            detail = next((b.get("text", "") for b in blocks if b.get("type") == "text"), "")
            raise AssertionError(f"{tool} failed: {detail[:300]}")
        # The server also reports argument errors as a plain text block.
        for block in blocks:
            text = block.get("text", "")
            if block.get("type") == "text" and text.startswith("Error:"):
                raise AssertionError(f"{tool} failed: {text[:300]}")
        return blocks

    async def _call_json(self, tool: str, arguments: dict[str, Any]) -> Any:
        blocks = await self._call(tool, arguments)
        for block in blocks:
            if block.get("type") == "text":
                try:
                    return json.loads(block.get("text", ""))
                except json.JSONDecodeError:
                    return block.get("text")
        return None

    async def _window_handle(self) -> dict[str, Any]:
        if self._window is None:
            payload = await self._call_json("list_windows", {})
            handles = (payload or {}).get("windowHandles") or []
            if not handles:
                raise AssertionError("the application reported no windows")
            self._window = cast("dict[str, Any]", handles[0])
        return self._window

    async def _tree(self) -> list[dict[str, Any]]:
        """Flat element list for the whole window, used for label lookups."""
        window = await self._window_handle()
        props = await self._call_json("get_window_properties", {"windowHandle": window})
        root = (props or {}).get("rootElementHandle")
        if root is None:
            raise AssertionError("the window reported no root element")
        payload = await self._call_json(
            "get_element_tree", {"elementHandle": root, "maxElements": 10000}
        )
        return cast("list[dict[str, Any]]", (payload or {}).get("elements") or [])

    @staticmethod
    def _labels_of(element: dict[str, Any]) -> list[str]:
        return [
            v
            for k in ("accessibleLabel", "accessibleValue", "accessibleDescription")
            if isinstance(v := element.get(k), str) and v
        ]

    async def _element(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Resolve the addressed element, waiting for it to appear.

        ``timeout_s: 0`` opts out, for a step that means to assert absence.
        """
        # Validate the selector once, up front: a step that names no element at
        # all is an authoring mistake, and waiting 15s to say so helps nobody.
        _selector(arguments)
        raw_timeout = arguments.get("timeout_s", _DEFAULT_WAIT_SECONDS)
        timeout = (
            float(raw_timeout) if isinstance(raw_timeout, (int, float)) else _DEFAULT_WAIT_SECONDS
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            try:
                return await self._resolve(arguments)
            except AssertionError:
                if loop.time() >= deadline:
                    raise
                await asyncio.sleep(0.25)

    async def _resolve(self, arguments: dict[str, Any]) -> dict[str, Any]:
        element_id, label, index = _selector(arguments)

        if label is None:
            payload = await self._call_json(
                "find_elements_by_id",
                {"windowHandle": await self._window_handle(), "elementsId": element_id},
            )
            handles = (payload or {}).get("elementHandles") or []
            if not handles:
                raise AssertionError(
                    f"no element with id {element_id!r}. Ids are "
                    "`Component::element-id` and only exist when the app was built "
                    "with SLINT_EMIT_DEBUG_INFO=1"
                )
            if index >= len(handles):
                raise AssertionError(
                    f"{element_id!r} matched {len(handles)} element(s), asked for #{index}"
                )
            return cast("dict[str, Any]", handles[index])

        if element_id is not None:
            # Both given: start from the id index and keep the ones carrying the
            # label. The tree walk below also sees elements the id index does
            # not — including ones that are not on screen — so with an id in
            # hand the index is the more faithful source, and a click that
            # landed on an off-screen twin is exactly the bug this avoids.
            payload = await self._call_json(
                "find_elements_by_id",
                {"windowHandle": await self._window_handle(), "elementsId": element_id},
            )
            candidates = (payload or {}).get("elementHandles") or []
            labelled: list[dict[str, Any]] = []
            for handle in candidates:
                props = await self._call_json("get_element_properties", {"elementHandle": handle})
                if label in self._labels_of(cast("dict[str, Any]", props or {})):
                    labelled.append(cast("dict[str, Any]", handle))
            if labelled:
                if index >= len(labelled):
                    raise AssertionError(
                        f"{label!r} matched {len(labelled)} element(s), asked for #{index}"
                    )
                return labelled[index]

        # Label-only lookup walks the tree, since Slint only indexes by id.
        matches = [
            el
            for el in await self._tree()
            if label in self._labels_of(el)
            and (
                element_id is None
                or any(d.get("id") == element_id for d in el.get("typeNamesAndIds") or [])
            )
        ]
        if not matches:
            where = f" with id {element_id!r}" if element_id else ""
            raise AssertionError(f"no element labelled {label!r}{where}")
        if index >= len(matches):
            raise AssertionError(f"{label!r} matched {len(matches)} element(s), asked for #{index}")
        handle = matches[index].get("handle")
        if handle is None:
            raise AssertionError(f"element labelled {label!r} exposes no handle")
        return cast("dict[str, Any]", handle)

    async def _await_text(
        self, arguments: dict[str, Any], matches: Callable[[str], bool]
    ) -> tuple[bool, str]:
        """Poll an element's text until it matches, or the timeout expires.

        Reading once is a race: the click that changed the text returns before
        the property behind it has settled, so a correct assertion failed
        depending on how fast the runner got there. Same deadline the element
        lookup already uses.
        """
        raw_timeout = arguments.get("timeout_s", _DEFAULT_WAIT_SECONDS)
        timeout = (
            float(raw_timeout) if isinstance(raw_timeout, (int, float)) else _DEFAULT_WAIT_SECONDS
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        actual = ""
        while True:
            try:
                actual = self._text_of(await self._properties(arguments))
            except AssertionError:
                # No readable text *yet*. Only worth reporting if it never
                # arrives — an element gains its label a frame after the
                # interaction that gave it one.
                if loop.time() >= deadline:
                    raise
                await asyncio.sleep(0.25)
                continue
            if matches(actual):
                return True, actual
            if loop.time() >= deadline:
                return False, actual
            await asyncio.sleep(0.25)

    async def _properties(self, arguments: dict[str, Any]) -> dict[str, Any]:
        handle = await self._element(arguments)
        payload = await self._call_json("get_element_properties", {"elementHandle": handle})
        return cast("dict[str, Any]", payload or {})

    async def _act_on_element(
        self, tool: str, arguments: dict[str, Any], payload: dict[str, Any]
    ) -> None:
        """Call a handle-taking tool, re-resolving once if the handle went stale.

        A list recycles the element under a handle as it scrolls or repaints, and
        the app answers "refers to element that was destroyed". Re-resolving and
        trying again is what a person does without thinking about it; failing the
        step instead made a correct test flaky.
        """
        handle = await self._element(arguments)
        try:
            await self._call(tool, {**payload, "elementHandle": handle})
        except AssertionError as exc:
            if "destroyed" not in str(exc):
                raise
            handle = await self._element(arguments)
            await self._call(tool, {**payload, "elementHandle": handle})

    async def _centre(self, handle: dict[str, Any]) -> dict[str, float]:
        """Logical centre of an element, the point a drag aims at.

        ``drag_element`` presses at the source element's own centre, so aiming
        at the destination's centre keeps a step readable as "drag A onto B"
        instead of asking the author for pixels. ``absolutePosition`` comes back
        empty for an element at the origin, hence the 0.0 defaults.
        """
        payload = await self._call_json("get_element_properties", {"elementHandle": handle})
        props = cast("dict[str, Any]", payload or {})
        position = props.get("absolutePosition") or {}
        size = props.get("size") or {}

        def number(source: dict[str, Any], key: str) -> float:
            value = source.get(key)
            return float(value) if isinstance(value, (int, float)) else 0.0

        return {
            "x": number(position, "x") + number(size, "width") / 2,
            "y": number(position, "y") + number(size, "height") / 2,
        }

    async def _drag_target(self, destination: dict[str, Any]) -> dict[str, float]:
        """Resolve a destination from :func:`_drag_destination` to a point."""
        if "x" in destination and "y" in destination:
            return {"x": float(destination["x"]), "y": float(destination["y"])}
        return await self._centre(await self._element(destination))

    # ------------------------------------------------------------------- tools

    async def _launch(self, arguments: dict[str, Any]) -> str:
        if self._proc is not None:
            raise AssertionError("an application is already running in this session")

        command = arguments.get("command") or self._provider.config_json.get("command")
        if not command:
            raise AssertionError("`command` is required — the app binary and its args")
        if isinstance(command, str):
            command = [command]
        binary = shutil.which(command[0]) or command[0]
        if not await asyncio.to_thread(os.path.exists, binary):
            raise AssertionError(f"binary not found: {command[0]}")

        port = int(arguments.get("port") or _free_port())
        env = {
            **os.environ,
            **self._provider.env,
            **(arguments.get("env") or {}),
            # Both are what turn an ordinary Slint binary into a drivable one:
            # the port starts the server, the debug info is what gives elements
            # the ids this provider addresses them by.
            "SLINT_MCP_PORT": str(port),
            "SLINT_EMIT_DEBUG_INFO": "1",
        }
        self._proc = await asyncio.create_subprocess_exec(
            binary,
            *command[1:],
            cwd=arguments.get("cwd") or None,
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._port = port
        self._client = httpx.AsyncClient()

        deadline = float(arguments.get("ready_timeout_s") or _DEFAULT_READY_TIMEOUT)
        loop = asyncio.get_running_loop()
        started = loop.time()
        while loop.time() - started < deadline:
            if self._proc.returncode is not None:
                await self._stop()
                raise AssertionError(
                    f"the application exited with code {self._proc.returncode} "
                    "before its MCP port opened"
                )
            try:
                await self._rpc(
                    "initialize",
                    {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "suitest-slint-mcp", "version": "1"},
                    },
                )
                return f"application started on port {port}"
            except Exception:  # not up yet; keep polling
                await asyncio.sleep(0.25)

        await self._stop()
        raise AssertionError(
            f"the application did not open its MCP port within {deadline:g}s. "
            "Was it built with `--features slint/mcp`?"
        )

    async def _stop(self) -> None:
        await self._stop_sampling()
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self._proc is not None:
            if self._proc.returncode is None:
                self._proc.terminate()
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=5)
                except TimeoutError:
                    self._proc.kill()
                    await self._proc.wait()
            self._proc = None
        self._port = None
        self._window = None

    # ------------------------------------------------------------------- video

    async def _sample_frames(self) -> None:
        """Screenshot the window on a timer until cancelled."""
        while True:
            try:
                blocks = await self._call(
                    "take_screenshot", {"windowHandle": await self._window_handle()}
                )
            except Exception:  # a frame lost to a busy UI must not end the recording
                blocks = []
            for block in blocks:
                if block.get("type") == "image" and isinstance(block.get("data"), str):
                    with contextlib.suppress(ValueError, TypeError):
                        self._video_frames.append(base64.b64decode(block["data"], validate=False))
                    break
            if len(self._video_frames) >= VIDEO_MAX_FRAMES:
                return
            await asyncio.sleep(self._video_interval_ms / 1000)

    async def _stop_sampling(self) -> None:
        # A sampler that finished on its own must not read as "never started".
        self._filming = False
        task, self._video_task = self._video_task, None
        if task is None:
            return
        task.cancel()
        # Teardown must not raise: a cancelled sampler, or one that died on a
        # busy UI, still has to leave the session closable.
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    @staticmethod
    def _text_of(properties: dict[str, Any]) -> str:
        for key in ("accessibleValue", "accessibleLabel", "accessibleDescription"):
            value = properties.get(key)
            if isinstance(value, str):
                return value
        raise AssertionError(
            "element exposes no readable text "
            f"(properties: {sorted(properties)}). Give it an accessible-label "
            "or accessible-value in the .slint source."
        )

    # ---------------------------------------------------------- BundledServer

    async def list_tools(self) -> list[Tool]:
        element = {
            "id": {
                "type": "string",
                "description": "Element id, `Component::element-id`.",
            },
            "label": {
                "type": "string",
                "description": (
                    "Visible/accessible label. Ids are component-scoped, so one "
                    "id matches every instance of that component — use this to "
                    "pick between them."
                ),
            },
            "index": {
                "type": "integer",
                "description": "Which match to use when several remain. Default 0.",
            },
            "timeout_s": {
                "type": "number",
                "description": (
                    "Seconds to wait for the element to appear. Default 15; 0 fails immediately."
                ),
            },
        }

        def tool(name: str, description: str, props: dict[str, Any], req: list[str]) -> Tool:
            return Tool(
                name=name,
                description=description,
                inputSchema={
                    "type": "object",
                    "properties": props,
                    "required": req,
                },
            )

        return [
            tool(
                "slint.launch",
                "Start the Slint application and wait for its embedded MCP "
                "server. The app must be built with `--features slint/mcp`.",
                {
                    "command": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Binary and arguments.",
                    },
                    "cwd": {"type": "string"},
                    "env": {"type": "object"},
                    "port": {"type": "integer", "description": "Default: free port."},
                    "ready_timeout_s": {"type": "number"},
                },
                [],
            ),
            tool(
                "slint.click",
                "Click an element. `double: true` for a double-click, which is "
                "how a list row is usually opened.",
                {**element, "double": {"type": "boolean"}},
                ["id"],
            ),
            tool(
                "slint.drag",
                "Press on an element, drag, release. Name a destination "
                "element with `to_id`/`to_label`, or a point with `x`/`y`. "
                "This is the gesture a click cannot stand in for: range "
                "selection across a grid, sliders, reordering.",
                {
                    **element,
                    "to_id": {
                        "type": "string",
                        "description": "Destination element id; the drag ends at its centre.",
                    },
                    "to_label": {
                        "type": "string",
                        "description": "Destination element's visible/accessible label.",
                    },
                    "to_index": {
                        "type": "integer",
                        "description": "Which destination match to use. Default 0.",
                    },
                    "x": {"type": "number", "description": "Destination x, logical pixels."},
                    "y": {"type": "number", "description": "Destination y, logical pixels."},
                    "button": {
                        "type": "string",
                        "description": "Left (default), Right, or Middle.",
                    },
                },
                ["id"],
            ),
            tool(
                "slint.set_property",
                "Set an element's value.",
                {**element, "value": {"type": "string"}},
                ["id", "value"],
            ),
            tool(
                "slint.get_property",
                "Read an element's properties.",
                dict(element),
                ["id"],
            ),
            tool(
                "slint.press_key",
                "Send text or a key to the focused element. Use Slint key names "
                "for non-printing keys, e.g. `Return`, `Tab`, `Backspace`.",
                {"text": {"type": "string"}},
                ["text"],
            ),
            tool(
                "slint.assert_visible",
                "Assert an element exists and is not fully transparent.",
                dict(element),
                ["id"],
            ),
            tool(
                "slint.assert_text",
                "Assert an element's text. `equals` by default, `contains` for a substring.",
                {
                    **element,
                    "equals": {"type": "string"},
                    "contains": {"type": "string"},
                },
                ["id"],
            ),
            tool(
                "slint.assert_checked",
                "Assert an element's checked state.",
                {**element, "checked": {"type": "boolean"}},
                ["id", "checked"],
            ),
            tool(
                "slint.assert_property",
                "Assert any property the element exposes, by dotted path — "
                "`size.width`, `absolutePosition.x`, `accessibleRole`. The way "
                "to check something the named assertions do not cover, such as "
                "a row not having moved.",
                {
                    **element,
                    "path": {
                        "type": "string",
                        "description": "Dotted path into the element's properties.",
                    },
                    "equals": {"description": "Expected value; compared as text."},
                },
                ["id", "path", "equals"],
            ),
            tool(
                "slint.assert_value",
                "Assert an element's value equals a string.",
                {**element, "equals": {"type": "string"}},
                ["id", "equals"],
            ),
            tool(
                "slint.screenshot",
                "PNG of the window, stored as a run artifact.",
                {},
                [],
            ),
            tool(
                "slint.element_tree",
                "Flat list of the window's elements — ids, labels and handles. "
                "Use it to find what to address in an app whose ids you don't "
                "know yet; every other tool takes those ids.",
                {
                    "max_elements": {
                        "type": "integer",
                        "description": "Cap on elements returned. Default 200.",
                    },
                },
                [],
            ),
            tool(
                "slint.start_recording",
                "Start recording the events the application receives. Pair it "
                "with `slint.stop_recording` around an interaction to see what "
                "the app actually got.",
                {},
                [],
            ),
            tool(
                "slint.stop_recording",
                "Stop recording and return the events since the last start, "
                "each with the result Slint gave it: `Accepted` when something "
                "handled it, `Ignored` when nothing did. This is what separates "
                '"the step never arrived" from "the app ignored it".',
                {},
                [],
            ),
            tool(
                "slint.start_video",
                "Start filming the window: screenshots on a timer, stitched "
                "into an MP4 by `slint.stop_video`. Wrap the interaction you "
                "want a reviewer to watch, not the whole run.",
                {
                    "interval_ms": {
                        "type": "integer",
                        "description": "Milliseconds between frames. Default 200 (5 fps).",
                    },
                },
                [],
            ),
            tool(
                "slint.stop_video",
                "Stop filming and attach the MP4 to the run, so the case shows "
                "the interaction instead of only its end state. Needs ffmpeg.",
                {},
                [],
            ),
            tool(
                "slint.accessibility_action",
                "Invoke an accessible action on an element, e.g. `Default_` "
                "(the element's primary action), `Increment`, `Decrement`. "
                "Reaches controls that respond to assistive tech rather than "
                "to a raw click.",
                {**element, "action": {"type": "string"}},
                ["id", "action"],
            ),
            tool("slint.close", "Stop the application.", {}, []),
        ]

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> list[TextContent | ImageContent | EmbeddedResource]:
        if name == "slint.launch":
            return [TextContent(type="text", text=await self._launch(arguments))]

        if name == "slint.close":
            await self._stop()
            return [TextContent(type="text", text="application stopped")]

        if name == "slint.screenshot":
            blocks = await self._call(
                "take_screenshot", {"windowHandle": await self._window_handle()}
            )
            # Passed through untouched: the runner turns image blocks into
            # SCREENSHOT artifacts, which is what surfaces them in the web UI.
            out: list[TextContent | ImageContent | EmbeddedResource] = []
            for block in blocks:
                if block.get("type") == "image":
                    out.append(
                        ImageContent(
                            type="image",
                            data=block.get("data", ""),
                            mimeType=block.get("mimeType", "image/png"),
                        )
                    )
                elif block.get("type") == "text":
                    out.append(TextContent(type="text", text=block.get("text", "")))
            return out

        if name == "slint.press_key":
            text = arguments.get("text")
            if not isinstance(text, str) or not text:
                raise AssertionError("`text` is required")
            await self._call(
                "dispatch_key_event",
                {"windowHandle": await self._window_handle(), "text": text},
            )
            return [TextContent(type="text", text=f"sent {text!r}")]

        if name == "slint.start_video":
            if self._filming:
                raise AssertionError("already filming — call `slint.stop_video` first")
            raw_interval = arguments.get("interval_ms", VIDEO_INTERVAL_MS)
            self._video_interval_ms = (
                int(raw_interval)
                if isinstance(raw_interval, int) and raw_interval > 0
                else VIDEO_INTERVAL_MS
            )
            self._video_frames = []
            await self._window_handle()  # fail here, not inside the sampler
            self._filming = True
            self._video_task = asyncio.create_task(self._sample_frames())
            return [TextContent(type="text", text="filming the window")]

        if name == "slint.stop_video":
            if not self._filming:
                raise AssertionError("not filming — call `slint.start_video` first")
            await self._stop_sampling()
            frames, self._video_frames = self._video_frames, []
            if not frames:
                raise AssertionError("no frames were captured")
            video = await asyncio.to_thread(
                encode_video, frames, self._video_interval_ms, tool="slint.stop_video"
            )
            return [
                TextContent(type="text", text=f"captured {len(frames)} frame(s)"),
                EmbeddedResource(
                    type="resource",
                    resource=BlobResourceContents(
                        uri="slint://window/recording.mp4",
                        mimeType="video/mp4",
                        blob=base64.b64encode(video).decode(),
                    ),
                ),
            ]

        if name == "slint.start_recording":
            await self._call("start_event_recording", {})
            return [TextContent(type="text", text="recording events")]

        if name == "slint.stop_recording":
            recorded = await self._call_json("stop_event_recording", {})
            return [TextContent(type="text", text=json.dumps(recorded or {}, indent=2))]

        if name == "slint.element_tree":
            raw_cap = arguments.get("max_elements", 200)
            cap = int(raw_cap) if isinstance(raw_cap, int) and raw_cap > 0 else 200
            elements = [
                {
                    "ids": [d.get("id") for d in el.get("typeNamesAndIds") or []],
                    "labels": self._labels_of(el),
                    "handle": el.get("handle"),
                }
                for el in (await self._tree())[:cap]
            ]
            return [TextContent(type="text", text=json.dumps(elements, indent=2))]

        target = _selector(arguments)[0] or _selector(arguments)[1] or "element"

        if name == "slint.click":
            double = bool(arguments.get("double"))
            how_args = {"action": "DoubleClick"} if double else {}
            await self._act_on_element("click_element", arguments, how_args)
            how = "double-clicked" if double else "clicked"
            return [TextContent(type="text", text=f"{how} {target}")]

        if name == "slint.drag":
            # Both ends are validated before either is resolved, so a step that
            # named only one of them is told that, not that the app is missing.
            wanted = _drag_destination(arguments)
            # Destination first: resolving it costs a lookup, and a handle goes
            # stale the moment the row under it is recycled. The source handle
            # is the one `drag_element` dereferences, so it is taken last.
            destination = await self._drag_target(wanted)
            payload: dict[str, Any] = {"target": destination}
            button = arguments.get("button")
            if isinstance(button, str) and button:
                payload["button"] = button
            await self._act_on_element("drag_element", arguments, payload)
            return [
                TextContent(
                    type="text",
                    text=f"dragged {target} to ({destination['x']:.0f}, {destination['y']:.0f})",
                )
            ]

        if name == "slint.accessibility_action":
            action = arguments.get("action")
            if not isinstance(action, str) or not action:
                raise AssertionError("`action` is required")
            await self._call(
                "invoke_accessibility_action",
                {"elementHandle": await self._element(arguments), "action": action},
            )
            return [TextContent(type="text", text=f"invoked {action} on {target}")]

        if name == "slint.set_property":
            value = arguments.get("value")
            if not isinstance(value, str):
                raise AssertionError("`value` is required")
            await self._call(
                "set_element_value",
                {"elementHandle": await self._element(arguments), "value": value},
            )
            return [TextContent(type="text", text=f"set {target} to {value!r}")]

        if name == "slint.get_property":
            props = await self._properties(arguments)
            return [TextContent(type="text", text=json.dumps(props, indent=2))]

        if name == "slint.assert_visible":
            props = await self._properties(arguments)
            opacity = props.get("computedOpacity", 1.0)
            if not isinstance(opacity, (int, float)) or opacity <= 0:
                raise AssertionError(f"{target} is not visible (opacity {opacity})")
            return [TextContent(type="text", text=f"{target} is visible")]

        if name == "slint.assert_text":
            if "contains" in arguments:
                needle = str(arguments["contains"])
                ok, actual = await self._await_text(arguments, lambda text: needle in text)
                if not ok:
                    raise AssertionError(
                        f"{target}: expected text containing {needle!r}, got {actual!r}"
                    )
            else:
                expected = str(arguments.get("equals", ""))
                ok, actual = await self._await_text(arguments, lambda text: text == expected)
                if not ok:
                    raise AssertionError(f"{target}: expected text {expected!r}, got {actual!r}")
            return [TextContent(type="text", text=f"{target} text matched")]

        if name == "slint.assert_property":
            path = str(arguments.get("path") or "")
            if not path:
                raise AssertionError("`path` is required, e.g. `absolutePosition.x`")
            found: Any = await self._properties(arguments)
            for part in path.split("."):
                if not isinstance(found, dict) or part not in found:
                    raise AssertionError(
                        f"{target} exposes no {path!r} (has: {sorted(found)})"
                        if isinstance(found, dict)
                        else f"{target}: {path!r} runs past a leaf value"
                    )
                found = found[part]
            actual = _as_text(found)
            expected = _as_text(arguments.get("equals"))
            if actual != expected:
                raise AssertionError(f"{target}: {path} is {actual!r}, expected {expected!r}")
            return [TextContent(type="text", text=f"{target} {path} == {actual}")]

        if name == "slint.assert_value":
            expected = str(arguments.get("equals", ""))
            ok, actual = await self._await_text(arguments, lambda text: text == expected)
            if not ok:
                raise AssertionError(f"{target}: expected value {expected!r}, got {actual!r}")
            return [TextContent(type="text", text=f"{target} value matched")]

        if name == "slint.assert_checked":
            props = await self._properties(arguments)
            if "accessibleChecked" not in props:
                raise AssertionError(f"{target} exposes no checked state")
            is_checked = bool(props["accessibleChecked"])
            want_checked = bool(arguments.get("checked"))
            if is_checked != want_checked:
                raise AssertionError(f"{target}: expected checked={want_checked}, got {is_checked}")
            return [TextContent(type="text", text=f"{target} checked matched")]

        raise AssertionError(f"unknown tool: {name}")

    async def aclose(self) -> None:
        await self._stop()


def build_slint_server(provider: McpProviderConfig) -> BundledServer:
    return SlintServer(provider)


register_bundled_builder(PROVIDER_NAME, build_slint_server)
