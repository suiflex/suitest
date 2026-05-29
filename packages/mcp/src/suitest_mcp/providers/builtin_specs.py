"""Bundled MCP provider specs (registered for every workspace by default).

These three providers ship in the runner / API image and are advertised to every
workspace at registry load time. Custom user-registered providers (rows in
``mcp_providers``) override them by ``name``.

Routing defaults (``is_default_for_target``) drive
:func:`suitest_mcp.routing.resolve_provider` — they may be overridden per
workspace via ``workspace_capabilities.features_json.routing_overrides``.
"""

from __future__ import annotations

from suitest_mcp.models import McpProviderConfig, McpTransport

BUILTIN_SPECS: list[McpProviderConfig] = [
    McpProviderConfig(
        id="builtin:api-http-mcp",
        workspace_id="_builtin_",
        name="api-http-mcp",
        kind="http",
        transport=McpTransport.IN_PROCESS,
        endpoint="in-process://api-http",
        config_json={
            "tools": [
                "http.request",
                "http.assert_status",
                "http.assert_json_path",
                "http.assert_header",
            ]
        },
        is_default_for_target={"BE_REST": True},
        max_sessions=8,
    ),
    McpProviderConfig(
        id="builtin:playwright-mcp",
        workspace_id="_builtin_",
        name="playwright-mcp",
        kind="browser",
        transport=McpTransport.STDIO,
        command=["npx", "-y", "@playwright/mcp@latest"],
        config_json={"version_pin": "@playwright/mcp@latest"},
        is_default_for_target={"FE_WEB": True},
        max_sessions=2,
        spawn_timeout_seconds=30.0,
    ),
    McpProviderConfig(
        id="builtin:postgres-mcp",
        workspace_id="_builtin_",
        name="postgres-mcp",
        kind="db",
        transport=McpTransport.IN_PROCESS,
        endpoint="in-process://postgres",
        config_json={
            "tools": [
                "db.query",
                "db.exec",
                "db.insert",
                "db.delete",
                "db.assert_row_exists",
                "db.assert_row_count",
            ]
        },
        is_default_for_target={"DATA": True},
        max_sessions=4,
    ),
]
