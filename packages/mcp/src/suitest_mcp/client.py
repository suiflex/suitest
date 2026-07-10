"""Generic async MCP client.

Thin wrapper around the official ``mcp`` SDK that supports four transports:

* ``stdio``  — subprocess + pipes (the canonical MCP transport)
* ``sse``    — Server-Sent Events over HTTP (one-way write + server stream)
* ``ws``     — full-duplex WebSocket
* ``in_process`` — connected memory streams (bundled api-http / postgres)

A single :class:`McpSession` is opaque to callers. Use :func:`open_session` to
construct one; the returned ``McpSession`` exposes ``list_tools()`` /
``call_tool(...)`` and an awaitable ``cleanup`` that tears the session down.

Lifecycle: the SDK's stdio_client (and SSE/WS) wraps anyio task groups whose
cancel scopes must enter/exit on the same task. We drive each session from a
dedicated background task instead of opening the context managers inline —
that lets pool / health probe code own a session without inheriting the
spawning task's cancel scope. The runner task owns one ``AsyncExitStack``
whose teardown happens entirely inside the task — no cross-task scope leak.

OpenTelemetry: every ``call_tool`` opens an ``mcp.invoke`` span tagged with
``mcp.provider`` and ``mcp.tool``. Spawn handshake itself is bounded by
``provider.spawn_timeout_seconds``; each tool call is bounded by the
``timeout_seconds`` argument the pool / invoker passes through.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.websocket import websocket_client
from opentelemetry import trace

from mcp import ClientSession, StdioServerParameters
from suitest_mcp.errors import McpHandshakeFailed, McpToolFailed, McpToolTimeout
from suitest_mcp.proc import resolve_command
from suitest_mcp.models import McpArtifact, McpProviderConfig, McpToolResult, McpTransport

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

log = structlog.get_logger(__name__)
tracer = trace.get_tracer("suitest.mcp.client")


@dataclass
class McpSession:
    """Single open MCP session (one underlying transport + ClientSession)."""

    provider: McpProviderConfig
    session: ClientSession
    cleanup: Callable[[], Awaitable[None]]
    created_at: float
    last_used_at: float
    invocations: int = 0
    # Version string from the MCP ``initialize`` handshake (serverInfo.version),
    # recorded for provenance pins (MCP_PLUGINS §13). ``None`` when the server
    # did not advertise one.
    server_version: str | None = None

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return advertised tools as plain dicts (name / description / input_schema)."""
        result = await self.session.list_tools()
        return [
            {
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.inputSchema or {},
            }
            for t in result.tools
        ]

    async def call_tool(
        self,
        tool: str,
        arguments: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> McpToolResult:
        """Invoke ``tool`` and normalize the response into :class:`McpToolResult`.

        Raises:
            McpToolTimeout: hard timeout enforced by :func:`asyncio.wait_for`.
            McpToolFailed: tool returned ``isError=true``.
        """
        self.invocations += 1
        self.last_used_at = time.monotonic()
        start = time.perf_counter()
        with tracer.start_as_current_span("mcp.invoke") as span:
            span.set_attribute("mcp.provider", self.provider.name)
            span.set_attribute("mcp.tool", tool)
            try:
                result = await asyncio.wait_for(
                    self.session.call_tool(name=tool, arguments=arguments),
                    timeout=timeout_seconds,
                )
            except TimeoutError as exc:
                raise McpToolTimeout(
                    f"tool {tool} on {self.provider.name} timed out after {timeout_seconds}s"
                ) from exc
            duration_ms = int((time.perf_counter() - start) * 1000)
            stdout = ""
            output: dict[str, Any] = {}
            artifacts: list[McpArtifact] = []
            for idx, content in enumerate(result.content):
                ctype = getattr(content, "type", "")
                if ctype == "text":
                    stdout += getattr(content, "text", "") + "\n"
                elif ctype == "image":
                    # Upstream MCP ImageContent carries a base64 ``data`` payload
                    # plus a ``mimeType``. Surface it as a SCREENSHOT artifact so
                    # the runner orchestrator's upload pipeline persists the
                    # bytes to S3/MinIO and the API exposes a row in
                    # ``/runs/<id>/artifacts``. Without this the runner would
                    # silently drop every screenshot block.
                    mime = getattr(content, "mimeType", None) or "image/png"
                    data_b64 = getattr(content, "data", None)
                    raw: bytes | None = None
                    if isinstance(data_b64, str):
                        try:
                            raw = base64.b64decode(data_b64, validate=False)
                        except (ValueError, TypeError):
                            raw = None
                    if raw is not None:
                        ext = "png"
                        if "/" in mime:
                            ext = mime.split("/", 1)[1].split("+", 1)[0] or "png"
                        artifacts.append(
                            McpArtifact(
                                kind="SCREENSHOT",
                                filename=f"screenshot-{idx}.{ext}",
                                content_type=mime,
                                bytes=raw,
                            )
                        )
                    else:
                        output.setdefault("blocks", []).append({"type": ctype, "data": data_b64})
                else:
                    output.setdefault("blocks", []).append(
                        {"type": ctype, "data": getattr(content, "data", None)}
                    )
            if result.isError:
                raise McpToolFailed(stdout.strip() or "isError=true")
            return McpToolResult(
                ok=True,
                output=output,
                stdout=stdout.strip(),
                stderr="",
                artifacts=artifacts,
                duration_ms=duration_ms,
            )


def _transport_context(provider: McpProviderConfig) -> Any:
    """Resolve a transport-specific async context manager for ``provider``.

    Returns the unentered context. Caller must drive it with ``async with``.
    """
    if provider.transport == McpTransport.STDIO:
        if not provider.command:
            raise McpHandshakeFailed(f"stdio provider {provider.name} has no command configured")
        params = StdioServerParameters(
            command=resolve_command(provider.command[0]),
            args=list(provider.command[1:]),
            env={**provider.env} if provider.env else None,
        )
        return stdio_client(params)
    if provider.transport == McpTransport.SSE:
        headers = provider.config_json.get("headers", {})
        return sse_client(provider.endpoint, headers=headers)
    if provider.transport == McpTransport.WS:
        return websocket_client(provider.endpoint)
    if provider.transport == McpTransport.IN_PROCESS:
        # Late import: the bundled runtime depends on mcp.server which we do
        # not want to load for stdio/SSE/WS code paths.
        from suitest_mcp.bundled.in_process_runtime import in_process_client

        return in_process_client(provider)
    raise McpHandshakeFailed(f"unknown transport {provider.transport!r}")  # pragma: no cover


async def _drive_session(
    provider: McpProviderConfig,
    ready: asyncio.Future[McpSession],
    stop: asyncio.Event,
    done: asyncio.Event,
) -> None:
    """Background runner that owns the transport context for one session.

    Opens the transport context, performs handshake bounded by
    ``spawn_timeout_seconds``, publishes the session on ``ready``, then waits
    for ``stop`` to be set before tearing the stack down. Anything that goes
    wrong before ``ready`` is set propagates through ``ready.set_exception``.
    """
    try:
        try:
            ctx = _transport_context(provider)
        except McpHandshakeFailed as exc:
            if not ready.done():
                ready.set_exception(exc)
            return

        try:
            async with AsyncExitStack() as stack:
                # NOTE: do NOT wrap the SDK's stdio_client / sse_client / ws_client
                # context entry in anyio.fail_after — those contexts open inner
                # anyio task groups whose cancel scopes must own the surrounding
                # frame, and a wrapping fail_after scope leaks past the inner
                # __aexit__ and triggers "exit a cancel scope that isn't the
                # current task's current cancel scope". Bound the slow piece
                # (initialize) with asyncio.wait_for instead.
                streams = await stack.enter_async_context(ctx)
                read_stream, write_stream = streams[0], streams[1]
                session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
                init_result = await asyncio.wait_for(
                    session.initialize(), timeout=provider.spawn_timeout_seconds
                )
                server_version = getattr(getattr(init_result, "serverInfo", None), "version", None)
                now = time.monotonic()

                async def _cleanup() -> None:
                    stop.set()
                    await done.wait()

                ms = McpSession(
                    provider=provider,
                    session=session,
                    cleanup=_cleanup,
                    created_at=now,
                    last_used_at=now,
                    server_version=server_version,
                )
                if not ready.done():
                    ready.set_result(ms)
                await stop.wait()
        except TimeoutError:
            if not ready.done():
                ready.set_exception(
                    McpHandshakeFailed(
                        f"handshake with {provider.name} timed out after "
                        f"{provider.spawn_timeout_seconds}s"
                    )
                )
            else:
                log.warning("mcp.session.timeout_after_ready", provider=provider.name)
        except McpHandshakeFailed as exc:
            if not ready.done():
                ready.set_exception(exc)
        except Exception as exc:
            if not ready.done():
                ready.set_exception(
                    McpHandshakeFailed(f"handshake with {provider.name} failed: {exc}")
                )
            else:
                log.warning(
                    "mcp.session.background_error",
                    provider=provider.name,
                    error=str(exc),
                )
    finally:
        done.set()


async def open_session(provider: McpProviderConfig) -> McpSession:
    """Open + initialize an MCP session against ``provider``.

    The session's transport context is driven by a dedicated background task
    via :func:`_drive_session`. Pool / health code can hand the returned
    session between tasks freely; the only requirement is to ``await
    session.cleanup()`` exactly once.

    Raises:
        McpHandshakeFailed: spawn / initialize exceeded ``spawn_timeout_seconds``
            or any transport setup error.
    """
    ready: asyncio.Future[McpSession] = asyncio.get_running_loop().create_future()
    stop = asyncio.Event()
    done = asyncio.Event()
    task = asyncio.create_task(
        _drive_session(provider, ready, stop, done),
        name=f"mcp-session:{provider.name}",
    )
    try:
        return await ready
    except BaseException:
        stop.set()
        with contextlib.suppress(Exception):
            await done.wait()
        with contextlib.suppress(BaseException):
            await task
        raise
