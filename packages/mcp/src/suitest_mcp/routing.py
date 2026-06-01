"""target_kind -> provider routing with workspace overrides.

Routing is a three-tier lookup:

1. Explicit ``mcp_provider`` on the step wins (the user pinned the provider).
2. Workspace override (``workspace_capabilities.features_json.routing_overrides``)
   wins next: an admin can pin BE_REST -> ``vendor-x-http`` for one workspace
   without touching the bundled defaults.
3. The bundled default mapping below resolves the primary; if the primary is
   missing for the workspace and a fallback is configured, the fallback is
   used. Missing both raises :class:`McpProviderUnavailable`.

Overrides format::

    {"BE_REST": {"primary": "vendor-x-http", "fallback": "api-http-mcp"}}

Both ``primary`` and ``fallback`` are provider names (matching
``McpProviderConfig.name``), not ids — admins configure these in the UI by
selecting from the workspace's known providers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from suitest_shared.domain.enums import TargetKind

from suitest_mcp.errors import McpProviderUnavailable

if TYPE_CHECKING:
    from suitest_mcp.models import McpProviderConfig
    from suitest_mcp.registry import McpRegistry

log = structlog.get_logger(__name__)


# Default routing per target_kind. ``(primary, fallback)``. ``fallback`` may be
# ``None`` when no second-choice is meaningful.
DEFAULT_ROUTING: dict[TargetKind, tuple[str, str | None]] = {
    TargetKind.BE_REST: ("api-http-mcp", None),
    # M2-10: graphql-mcp / grpc-mcp bundled. GraphQL falls back to the raw-HTTP
    # builtin for simple POST flows; gRPC has no HTTP-shaped fallback.
    TargetKind.BE_GRAPHQL: ("graphql-mcp", "api-http-mcp"),
    TargetKind.BE_GRPC: ("grpc-mcp", None),
    TargetKind.FE_WEB: ("playwright-mcp", None),
    # appium-mcp ships later (M12) — until then, FE_MOBILE falls back to playwright.
    TargetKind.FE_MOBILE: ("playwright-mcp", None),
    TargetKind.DATA: ("postgres-mcp", None),
    # M2-10: kubernetes-mcp bundled for INFRA assertions.
    TargetKind.INFRA: ("kubernetes-mcp", None),
    TargetKind.CUSTOM: ("", None),
}


def _resolve_override(
    registry: McpRegistry,
    workspace_id: str,
    target_kind: TargetKind,
    overrides: dict[str, Any] | None,
) -> McpProviderConfig | None:
    """Apply a workspace override rule, if any, for ``target_kind``.

    Returns the resolved primary, or its fallback if the primary is missing,
    or ``None`` when no override applies.
    """
    if not overrides:
        return None
    rule = overrides.get(target_kind.value)
    if not isinstance(rule, dict):
        return None
    primary = rule.get("primary")
    if not primary:
        return None
    try:
        return registry.get(workspace_id, str(primary))
    except McpProviderUnavailable:
        fallback = rule.get("fallback")
        if fallback:
            return registry.get(workspace_id, str(fallback))
        raise


def resolve_provider(
    registry: McpRegistry,
    *,
    workspace_id: str,
    target_kind: TargetKind,
    explicit: str | None,
    overrides: dict[str, Any] | None = None,
) -> McpProviderConfig:
    """Resolve which provider should service this step.

    Order: explicit -> workspace override -> bundled default (primary, fallback).

    Raises:
        McpProviderUnavailable: every option exhausted (or CUSTOM target_kind
            with no explicit provider).
    """
    if explicit:
        return registry.get(workspace_id, explicit)

    override_provider = _resolve_override(registry, workspace_id, target_kind, overrides)
    if override_provider is not None:
        return override_provider

    primary, fallback = DEFAULT_ROUTING.get(target_kind, ("", None))
    if not primary:
        raise McpProviderUnavailable(f"no default routing for target_kind {target_kind.value}")
    try:
        return registry.get(workspace_id, primary)
    except McpProviderUnavailable:
        if fallback:
            return registry.get(workspace_id, fallback)
        raise
