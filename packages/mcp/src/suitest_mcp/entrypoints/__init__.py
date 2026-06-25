"""Custom MCP provider entrypoint layer (M9-1).

Third-party packages expose custom MCP providers via the
``suitest.mcp_providers`` entry_points group.  The loader discovers them at
process startup; the registry hook injects them into the live
:class:`~suitest_mcp.registry.McpRegistry`.
"""
