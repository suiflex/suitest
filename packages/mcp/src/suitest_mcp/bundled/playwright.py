"""Bundled playwright-mcp provider metadata (M1c Task 7).

Wraps the upstream ``@playwright/mcp`` Node package as a stdio subprocess. The
actual subprocess + stdio plumbing is handled by :func:`suitest_mcp.client.open_session`
when ``McpProviderConfig.transport == McpTransport.STDIO`` — this module is a
pure metadata layer that:

* exposes :data:`PLAYWRIGHT_SPEC`, the template ``McpProviderConfig`` used to
  describe the bundled provider (kind/transport/command/env), and
* exposes :data:`DECLARED_TOOLS`, an *informational* catalog of the tools the
  upstream MCP server advertises. The authoritative list still comes from
  ``McpSession.list_tools()`` at runtime — :data:`DECLARED_TOOLS` is for docs,
  UI hints, and ZERO-tier capability listing only.

Spawn contract
--------------
The provider spawns via ``npx -y @playwright/mcp@latest``. The ``-y`` flag is
intentional: it tells ``npx`` to assume yes when installing the package on the
first call, which keeps the handshake non-interactive (the stdio transport in
:func:`suitest_mcp.client._drive_session` would otherwise deadlock on an
``Are you ok to proceed? (y)`` prompt). Browser auto-detection is handled by
Playwright itself; we deliberately pass an empty ``env`` so the subprocess
inherits the parent ``PATH`` / ``HOME`` without leaking Suitest secrets.

Docker auto-install (deferred to M1c Task 10 — runner scaffold — or M2 polish)
-----------------------------------------------------------------------------
For air-gapped / cold-start deployments the runner image SHOULD pre-install
the Node package and the Chromium browser at build time so the first run does
not pay the ``npx`` install cost::

    # Dockerfile.runner / Dockerfile.api
    RUN npm install -g @playwright/mcp@latest \\
     && npx -y playwright install --with-deps chromium

That change does not belong to this task — Task 7 only adds the metadata
layer. The Dockerfile update is tracked separately.

Tool catalog
------------
:data:`DECLARED_TOOLS` mirrors the upstream ``@playwright/mcp`` advertised
surface. The package moved from dotted names (``browser.navigate``) to
underscore names (``browser_navigate``), so this catalog tracks the current
runtime contract while the runner keeps a small compatibility shim for legacy
stored steps.
"""

from __future__ import annotations

from suitest_mcp.models import McpProviderConfig, McpToolSchema, McpTransport

#: ``npx`` argv used to spawn the bundled provider. ``-y`` is required to
#: keep the install handshake non-interactive (see module docstring).
#: ``--browser chromium`` pins the Playwright-managed chromium build: the
#: default Chrome channel binary does not exist on linux/arm64 runner images,
#: while chromium is preinstalled on every platform (Dockerfile.runner).
PLAYWRIGHT_COMMAND: list[str] = ["npx", "-y", "@playwright/mcp@latest", "--browser", "chromium"]


#: Informational tool catalog. Authoritative list comes from
#: ``McpSession.list_tools()`` at runtime; this is for docs / UI hints only.
DECLARED_TOOLS: list[McpToolSchema] = [
    McpToolSchema(name="browser_navigate", description="Navigate to a URL"),
    McpToolSchema(name="browser_click", description="Click on a DOM element"),
    McpToolSchema(name="browser_type", description="Type into a focused field"),
    McpToolSchema(name="browser_take_screenshot", description="Capture a screenshot artifact"),
    McpToolSchema(name="browser_evaluate", description="Evaluate JS in the page context"),
    McpToolSchema(name="browser_wait_for", description="Wait for a selector / state"),
    McpToolSchema(name="browser_snapshot", description="Return an accessibility snapshot"),
    McpToolSchema(name="browser_hover", description="Hover a DOM element"),
    McpToolSchema(name="browser_press_key", description="Press a keyboard key"),
    McpToolSchema(name="browser_select_option", description="Select an option in a form control"),
]


#: Template :class:`McpProviderConfig` for the bundled playwright-mcp provider.
#:
#: ``id`` and ``workspace_id`` carry the ``builtin:`` / ``_builtin_`` sentinel
#: values used by the registry; call :func:`bootstrap_playwright_provider` to
#: rebind ``workspace_id`` for a specific workspace at registry load time.
PLAYWRIGHT_SPEC: McpProviderConfig = McpProviderConfig(
    id="builtin:playwright-mcp",
    workspace_id="_builtin_",
    name="playwright-mcp",
    kind="playwright-mcp",
    transport=McpTransport.STDIO,
    command=PLAYWRIGHT_COMMAND,
    env={},
    config_json={
        "version_pin": "@playwright/mcp@latest",
        "declared_tools": [t.name for t in DECLARED_TOOLS],
    },
    is_default_for_target={"FE_WEB": True},
    max_sessions=2,
    spawn_timeout_seconds=30.0,
)


def bootstrap_playwright_provider(workspace_id: str) -> McpProviderConfig:
    """Build a workspace-bound :class:`McpProviderConfig` from :data:`PLAYWRIGHT_SPEC`.

    The registry loader calls this for every workspace at startup so the
    bundled provider appears on the workspace's provider list with the right
    ``workspace_id`` — the underlying spec template stays unchanged.

    Args:
        workspace_id: Target workspace's ID. Must be non-empty; the
            :class:`McpProviderConfig` validator enforces ``min_length=1``.

    Returns:
        A fresh :class:`McpProviderConfig` cloned from :data:`PLAYWRIGHT_SPEC`
        with ``workspace_id`` rebound. ``id`` is namespaced to the workspace
        so two workspaces never collide in the registry index.

    Raises:
        pydantic.ValidationError: ``workspace_id`` is empty / whitespace-only.
    """
    # ``model_copy(update=...)`` deliberately skips validation, so route the
    # rebound config through ``model_validate`` to enforce the ``min_length=1``
    # invariant on ``workspace_id`` / ``id`` for callers that pass user input.
    return McpProviderConfig.model_validate(
        PLAYWRIGHT_SPEC.model_copy(
            update={
                "id": f"builtin:playwright-mcp:{workspace_id}",
                "workspace_id": workspace_id,
            }
        ).model_dump()
    )
