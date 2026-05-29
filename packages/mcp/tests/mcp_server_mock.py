"""Mock MCP server spawnable as a subprocess.

The mock advertises two tools:

* ``echo`` — returns its arguments serialised as text.
* ``boom`` — raises ``RuntimeError``, so the wrapping ``CallToolResult`` lands
  with ``isError=True`` and the client raises :class:`McpToolFailed`.

The server source is written to a tempfile per test session and spawned via
``[sys.executable, <path>]`` — keeps test isolation away from the project's
import graph and away from any installed binary.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT = """
import asyncio, json, sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool


app: Server = Server("mock-mcp")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="echo", description="echo", inputSchema={"type": "object"}),
        Tool(name="boom", description="raises", inputSchema={"type": "object"}),
    ]


@app.call_tool()
async def call_tool(name, arguments):
    if name == "boom":
        raise RuntimeError("boom")
    return [TextContent(type="text", text="ECHO:" + json.dumps(arguments, sort_keys=True))]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
"""


class MockMcpServer:
    """Subprocess-spawnable mock MCP server.

    Writes the source to ``tmp_path/mock_mcp_server.py`` and exposes a ready-to-run
    ``command`` (``[sys.executable, <path>]``) compatible with
    :class:`suitest_mcp.models.McpProviderConfig.command`.
    """

    def __init__(self, tmp_path: Path) -> None:
        self.script = tmp_path / "mock_mcp_server.py"
        self.script.write_text(_SCRIPT)

    @property
    def command(self) -> list[str]:
        return [sys.executable, str(self.script)]
