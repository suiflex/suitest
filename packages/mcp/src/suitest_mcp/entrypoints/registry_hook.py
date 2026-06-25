"""Inject discovered custom MCP providers into McpRegistry (M9-1).

:func:`register_discovered_providers` is called once at process startup
(in the API lifespan or runner bootstrap) to load all entry_point providers
and make them available to every workspace under the sentinel workspace
``_custom_ep_``.

Custom entrypoint providers use the ``in_process`` transport — they are
invoked directly (not over stdio/http) via
:meth:`CustomMcpProviderBase.invoke`.  The registry holds a synthetic
:class:`McpProviderConfig` so routing and health-check code can treat them
uniformly alongside bundled providers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from suitest_mcp.entrypoints.loader import discover_custom_mcp_providers
from suitest_mcp.models import McpProviderConfig, McpTransport

if TYPE_CHECKING:
    from suitest_mcp.registry import McpRegistry

log = structlog.get_logger(__name__)

# Sentinel workspace ID used to store entrypoint providers in the registry.
# On per-workspace load the registry_hook injects them before DB rows overlay.
_EP_WORKSPACE = "_custom_ep_"


def register_discovered_providers(registry: McpRegistry) -> int:
    """Discover entry_point providers and register them in *registry*.

    Creates synthetic :class:`McpProviderConfig` entries with transport
    ``in_process`` under the sentinel workspace ``_custom_ep_`` so the invoker
    can look them up by name.

    :param registry: The live :class:`McpRegistry` instance to mutate.
    :returns: Number of successfully registered providers.
    """
    classes = discover_custom_mcp_providers()
    if not classes:
        log.info("mcp.registry_hook.no_custom_providers")
        return 0

    # Ensure the sentinel workspace bucket exists.
    if _EP_WORKSPACE not in registry._by_workspace:
        registry._by_workspace[_EP_WORKSPACE] = {}

    registered = 0
    for cls in classes:
        spec = cls.spec
        config = McpProviderConfig(
            id=f"ep:{spec.name}",
            workspace_id=_EP_WORKSPACE,
            name=spec.name,
            kind="custom_ep",
            transport=McpTransport.IN_PROCESS,
            endpoint=spec.base_url or "",
            command=spec.command or [],
            max_sessions=1,
            idle_ttl_seconds=0,
            spawn_timeout_seconds=10.0,
            call_timeout_seconds=30.0,
        )
        registry._by_workspace[_EP_WORKSPACE][spec.name] = config
        log.info(
            "mcp.registry_hook.registered",
            provider=spec.name,
            version=spec.version,
            transport=spec.transport,
        )
        registered += 1

    return registered
