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
        # Browser automation needs generous timeouts: the first spawn may `npx`-
        # fetch the package and launch (download) a browser, and real page loads
        # / interactions routinely exceed the 30s default. Under-budgeting these
        # surfaced as ``MCP_TOOL_TIMEOUT: browser_navigate ... 30.0s`` on a cold run.
        spawn_timeout_seconds=120.0,
        call_timeout_seconds=90.0,
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
    # M2-10 — additive bundled providers. All in-process; their backend drivers
    # are imported lazily at call time so listing tools / loading the registry
    # never drags heavy deps into the import graph.
    McpProviderConfig(
        id="builtin:graphql-mcp",
        workspace_id="_builtin_",
        name="graphql-mcp",
        kind="api",
        transport=McpTransport.IN_PROCESS,
        endpoint="in-process://graphql",
        config_json={"tools": ["graphql.query", "graphql.mutate", "graphql.assert_data"]},
        is_default_for_target={"BE_GRAPHQL": True},
        max_sessions=8,
    ),
    McpProviderConfig(
        id="builtin:mysql-mcp",
        workspace_id="_builtin_",
        name="mysql-mcp",
        kind="db",
        transport=McpTransport.IN_PROCESS,
        endpoint="in-process://mysql",
        config_json={
            "tools": ["db.query", "db.exec", "db.assert_row_count"],
        },
        max_sessions=4,
    ),
    McpProviderConfig(
        id="builtin:mongo-mcp",
        workspace_id="_builtin_",
        name="mongo-mcp",
        kind="db",
        transport=McpTransport.IN_PROCESS,
        endpoint="in-process://mongo",
        config_json={
            "tools": ["mongo.find", "mongo.insert_one", "mongo.delete", "mongo.assert_count"],
        },
        max_sessions=4,
    ),
    McpProviderConfig(
        id="builtin:kubernetes-mcp",
        workspace_id="_builtin_",
        name="kubernetes-mcp",
        kind="infra",
        transport=McpTransport.IN_PROCESS,
        endpoint="in-process://kubernetes",
        config_json={"tools": ["k8s.get", "k8s.list", "k8s.assert_condition"]},
        is_default_for_target={"INFRA": True},
        max_sessions=2,
    ),
    McpProviderConfig(
        id="builtin:grpc-mcp",
        workspace_id="_builtin_",
        name="grpc-mcp",
        kind="api",
        transport=McpTransport.IN_PROCESS,
        endpoint="in-process://grpc",
        config_json={"tools": ["grpc.call", "grpc.assert_response"]},
        is_default_for_target={"BE_GRPC": True},
        max_sessions=4,
    ),
]
