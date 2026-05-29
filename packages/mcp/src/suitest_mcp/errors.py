"""MCP error hierarchy.

Every error carries a stable ``code`` string so the invoker / runner can
distinguish ``MCP_TOOL_TIMEOUT`` from ``MCP_POOL_EXHAUSTED`` without depending
on Python class identity (helpful when these propagate across the queue).
"""

from __future__ import annotations


class McpError(Exception):
    """Base for every error raised by the MCP layer."""

    code: str = "MCP_GENERIC"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class McpProviderUnavailable(McpError):
    """Provider id / name is not registered for the requested workspace."""

    code = "MCP_PROVIDER_UNAVAILABLE"


class McpProviderUnhealthy(McpError):
    """Provider is registered but currently marked DOWN / DEGRADED past threshold."""

    code = "MCP_PROVIDER_UNHEALTHY"


class McpToolTimeout(McpError):
    """Tool call exceeded ``McpProviderConfig.call_timeout_seconds``."""

    code = "MCP_TOOL_TIMEOUT"


class McpToolFailed(McpError):
    """Tool returned ``isError=true`` or raised before timeout fired."""

    code = "MCP_TOOL_FAILED"


class McpPoolExhausted(McpError):
    """Pool is at ``max_sessions`` and the queue wait exceeded ``queue_timeout``."""

    code = "MCP_POOL_EXHAUSTED"


class McpHandshakeFailed(McpError):
    """Handshake / initialize() failed or timed out at ``spawn_timeout_seconds``."""

    code = "MCP_HANDSHAKE_FAILED"
