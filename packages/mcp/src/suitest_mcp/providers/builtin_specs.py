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
                "http.assert_pdf_text",
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
        command=["npx", "-y", "@playwright/mcp@latest", "--browser", "chromium"],
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
    # M14 — desktop (FE_DESKTOP). ``computer-use-mcp`` and ``electron-mcp`` are
    # external stdio binaries that are NOT distributed in the runner image: each
    # resolves its real path via registration / ``command_pin`` (e.g.
    # ``command_pin = /opt/suitest/computer-use-mcp``). The ``command`` below is
    # only a discoverability hint (a binary that must exist on PATH once
    # installed). ``slint-mcp`` needs none of that — see its own note below.
    #
    # ``computer-use-mcp`` is the generic catch-all: OS-level screenshot+click
    # control, so it routes as the FE_DESKTOP default. ``slint-mcp`` and
    # ``electron-mcp`` drive apps through their own accessible-tree / DOM seams
    # and are pinned explicitly per step (or via a workspace routing override)
    # — far more deterministic than screen control, so preferred when the app is
    # Slint or Electron. See docs/DESKTOP_TESTING.md.
    McpProviderConfig(
        id="builtin:computer-use-mcp",
        workspace_id="_builtin_",
        name="computer-use-mcp",
        kind="desktop",
        transport=McpTransport.STDIO,
        command=["computer-use-mcp"],
        config_json={
            "tools": [
                "desktop.screenshot",
                "desktop.click",
                "desktop.type_text",
                "desktop.scroll",
                "desktop.move",
                "desktop.assert_visible",
            ]
        },
        is_default_for_target={"FE_DESKTOP": True},
        max_sessions=2,
        # OS control can be slow on first connect (screen capture server).
        spawn_timeout_seconds=60.0,
        call_timeout_seconds=45.0,
    ),
    McpProviderConfig(
        id="builtin:electron-mcp",
        workspace_id="_builtin_",
        name="electron-mcp",
        kind="desktop",
        transport=McpTransport.STDIO,
        command=["electron-mcp"],
        config_json={
            "tools": [
                "electron.launch",
                "electron.click",
                "electron.type_text",
                "electron.get_property",
                "electron.assert_text",
                "electron.assert_visible",
                "electron.screenshot",
                "electron.close",
            ]
        },
        max_sessions=2,
        spawn_timeout_seconds=120.0,
        call_timeout_seconds=60.0,
    ),
    # Bundled in-process, unlike its two neighbours: Slint 1.17 puts an MCP
    # server *inside* the application under test, so there is no separate binary
    # to install or pin. The provider is a bridge that owns the app process and
    # maps these tools onto the app's own — see suitest_mcp.bundled.slint.
    McpProviderConfig(
        id="builtin:slint-mcp",
        workspace_id="_builtin_",
        name="slint-mcp",
        kind="desktop",
        transport=McpTransport.IN_PROCESS,
        endpoint="in-process://slint",
        config_json={
            "tools": [
                "slint.launch",
                "slint.click",
                "slint.drag",
                "slint.set_property",
                "slint.get_property",
                "slint.press_key",
                "slint.assert_visible",
                "slint.assert_text",
                "slint.assert_checked",
                "slint.assert_property",
                "slint.assert_value",
                "slint.screenshot",
                "slint.element_tree",
                "slint.start_video",
                "slint.stop_video",
                "slint.start_recording",
                "slint.stop_recording",
                "slint.accessibility_action",
                "slint.close",
            ]
        },
        max_sessions=2,
        # A Rust Slint harness compiles/link-checks at spawn and file loads can
        # be slow on a cold run; give it room like playwright.
        spawn_timeout_seconds=120.0,
        call_timeout_seconds=60.0,
    ),
    # Bundled in-process for the same reason as slint-mcp: the WebDriver server
    # lives inside the application under test (tauri-plugin-wdio-webdriver), so
    # there is no binary to install or pin. Unlike slint the wire protocol is a
    # standard — W3C WebDriver — which is also why this works on macOS, where
    # the standalone tauri-driver does not exist.
    McpProviderConfig(
        id="builtin:tauri-mcp",
        workspace_id="_builtin_",
        name="tauri-mcp",
        kind="desktop",
        transport=McpTransport.IN_PROCESS,
        endpoint="in-process://tauri",
        config_json={
            "tools": [
                "tauri.launch",
                "tauri.close",
                "tauri.click",
                "tauri.type_text",
                "tauri.get_text",
                "tauri.assert_text",
                "tauri.assert_visible",
                "tauri.eval",
                "tauri.screenshot",
                "tauri.start_video",
                "tauri.stop_video",
            ]
        },
        max_sessions=2,
        # Cold-starting a bundled desktop app plus its webview is slow enough
        # that the playwright-sized budget is the right order of magnitude.
        spawn_timeout_seconds=120.0,
        call_timeout_seconds=60.0,
    ),
]
