"""Connect to an MCP provider, handshake, and list its tools (M2-7).

The custom-MCP registration flow (docs/MCP_PLUGINS.md §5.3) validates a provider
before persisting it: open a session against the supplied transport, perform the
MCP ``initialize`` handshake, invoke ``tools/list``, and capture the advertised
tool catalog + server version. A failure anywhere surfaces as
:class:`McpDiscoveryError` so the API layer can reject the registration with a
structured error instead of writing a dead row.

This module is intentionally transport-agnostic — it leans on
:func:`suitest_mcp.client.open_session`, so the same code path validates stdio,
SSE, and WebSocket providers.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from suitest_mcp.client import open_session
from suitest_mcp.errors import McpError

if TYPE_CHECKING:
    from suitest_mcp.models import McpProviderConfig, McpToolResult

log = structlog.get_logger(__name__)


class McpDiscoveryError(McpError):
    """Raised when a provider cannot be connected to or advertises no tools."""


@dataclass
class DiscoveredTool:
    """One tool advertised by ``tools/list``."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiscoveryResult:
    """Outcome of a successful discovery probe."""

    tools: list[DiscoveredTool]
    server_version: str | None = None


async def discover_provider(
    provider: McpProviderConfig,
    *,
    timeout_seconds: float = 30.0,
) -> DiscoveryResult:
    """Open a session against ``provider``, run ``tools/list``, return the catalog.

    Raises:
        McpDiscoveryError: handshake failed, the probe timed out, or the server
            advertised zero tools (we treat an empty catalog as a misconfigured
            provider — a healthy MCP server exposes at least one tool).
    """
    try:
        session = await asyncio.wait_for(open_session(provider), timeout=timeout_seconds)
    except TimeoutError as exc:
        raise McpDiscoveryError(
            f"connection to {provider.name!r} timed out after {timeout_seconds}s"
        ) from exc
    except Exception as exc:
        raise McpDiscoveryError(f"could not connect to {provider.name!r}: {exc}") from exc

    try:
        raw = await asyncio.wait_for(session.list_tools(), timeout=timeout_seconds)
    except Exception as exc:
        raise McpDiscoveryError(f"tools/list failed for {provider.name!r}: {exc}") from exc
    finally:
        await session.cleanup()

    if not raw:
        raise McpDiscoveryError(f"{provider.name!r} advertised no tools")

    tools = [
        DiscoveredTool(
            name=str(t["name"]),
            description=str(t.get("description", "")),
            input_schema=dict(t.get("input_schema", {})),
        )
        for t in raw
    ]
    log.info("mcp.discovery.ok", provider=provider.name, tool_count=len(tools))
    return DiscoveryResult(tools=tools, server_version=session.server_version)


async def invoke_tool(
    provider: McpProviderConfig,
    tool: str,
    arguments: dict[str, Any],
    *,
    timeout_seconds: float = 30.0,
) -> McpToolResult:
    """Open a one-shot session and invoke ``tool`` (the M2-8 tool-browser path).

    Unlike :class:`suitest_mcp.invoker.McpInvoker` (the pooled, audited runner
    path), this spins up a fresh session, calls one tool, and tears it down —
    suitable for the developer "Try it" form. Audit + role gating live in the
    API layer.

    Raises:
        McpDiscoveryError: the session could not be opened.
        McpToolTimeout / McpToolFailed: surfaced verbatim from the tool call.
    """
    try:
        session = await asyncio.wait_for(open_session(provider), timeout=timeout_seconds)
    except TimeoutError as exc:
        raise McpDiscoveryError(
            f"connection to {provider.name!r} timed out after {timeout_seconds}s"
        ) from exc
    except Exception as exc:
        raise McpDiscoveryError(f"could not connect to {provider.name!r}: {exc}") from exc

    try:
        return await session.call_tool(tool, arguments, timeout_seconds=timeout_seconds)
    finally:
        await session.cleanup()
