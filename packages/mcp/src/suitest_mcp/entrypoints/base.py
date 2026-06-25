"""CustomMcpProviderBase ABC and CustomMcpSpec Pydantic model (M9-1).

Third-party packages subclass :class:`CustomMcpProviderBase`, attach a
class-level :class:`CustomMcpSpec`, and register the class under the
``suitest.mcp_providers`` entry_points group so the loader can discover them.

Example ``pyproject.toml`` entry::

    [project.entry-points."suitest.mcp_providers"]
    my-db-mcp = "my_package.mcp:MyDbMcpProvider"

The class is then discovered by :func:`suitest_mcp.entrypoints.loader.discover_custom_mcp_providers`
and injected into the live registry by
:func:`suitest_mcp.entrypoints.registry_hook.register_discovered_providers`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class CustomMcpSpec(BaseModel):
    """Static descriptor for a custom MCP provider.

    Attach one as a class-level attribute on every
    :class:`CustomMcpProviderBase` subclass.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="Unique provider name, e.g. 'my-db-mcp'.",
    )
    display_name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    version: str = Field(
        ...,
        pattern=r"^\d+\.\d+\.\d+",
        description="Semver string, e.g. '1.0.0'.",
    )
    # "stdio" | "http" | "in_process"
    transport: str = Field(
        ...,
        description="Transport type: 'stdio', 'http', or 'in_process'.",
    )
    # For stdio transport: argv of the MCP server process.
    command: list[str] | None = None
    # For http transport: base URL of the MCP server.
    base_url: str | None = None
    author: str | None = None


class CustomMcpProviderBase(ABC):
    """Abstract base class for custom MCP providers.

    Subclasses MUST:

    * Set a class-level :attr:`spec` with a valid :class:`CustomMcpSpec`.
    * Implement :meth:`invoke` to dispatch a tool call.

    The provider is stateless per contract — the invoker may call
    :meth:`invoke` from any coroutine and the implementation must not hold
    per-call mutable state at the class level.
    """

    # Subclasses must override this at class level.
    spec: CustomMcpSpec

    @abstractmethod
    async def invoke(
        self,
        tool: str,
        args: dict[str, object],
    ) -> dict[str, object]:
        """Invoke a named tool on this custom MCP provider.

        :param tool: Tool name as advertised by the provider.
        :param args: Free-form arguments dict forwarded verbatim.
        :returns: Free-form result dict (content / metadata).
        :raises McpToolFailed: On tool-level error from the provider.
        :raises McpToolTimeout: When the provider takes too long.
        """
