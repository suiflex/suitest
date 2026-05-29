"""Per-workspace MCP provider catalog.

For each workspace we keep an in-memory dict of ``name -> McpProviderConfig``,
seeded from the three bundled builtins (api-http-mcp, playwright-mcp,
postgres-mcp) and then overlaid with any DB-stored custom rows
(:class:`suitest_db.repositories.mcp_providers.McpProviderRepo`).

User rows override builtins by ``name`` so a workspace that registers its own
``playwright-mcp`` row pinned to a private MCP image wins over the bundled
``npx -y @playwright/mcp@latest``.

The registry is mutable but not thread-safe — callers (runner / API) own one
``McpRegistry`` per process and refresh per workspace under their own lock.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from suitest_mcp.errors import McpProviderUnavailable
from suitest_mcp.models import McpProviderConfig, McpTransport
from suitest_mcp.providers.builtin_specs import BUILTIN_SPECS

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from suitest_db.models.mcp_provider import McpProvider

log = structlog.get_logger(__name__)


# Maps the on-disk ``mcp_transport`` Postgres ENUM (stdio / sse / ws) to the
# richer client-side McpTransport enum. The DB layer never persists IN_PROCESS
# because that transport is bundling-only.
_TRANSPORT_MAP: dict[str, McpTransport] = {
    "stdio": McpTransport.STDIO,
    "sse": McpTransport.SSE,
    "ws": McpTransport.WS,
}


def _row_to_config(row: McpProvider) -> McpProviderConfig:
    """Convert a persisted ``McpProvider`` row into an in-memory config.

    Pulls bookkeeping knobs (max_sessions / idle_ttl_seconds / *_timeout) from
    ``config_json`` when present so admins can tune pooling without an Alembic
    migration.
    """
    cfg = row.config_json or {}
    transport_value = row.transport.value if hasattr(row.transport, "value") else str(row.transport)
    return McpProviderConfig(
        id=row.id,
        workspace_id=row.workspace_id,
        name=row.name,
        kind=row.kind,
        transport=_TRANSPORT_MAP.get(transport_value, McpTransport.STDIO),
        endpoint=row.endpoint or "",
        command=list(cfg.get("command", [])),
        env=dict(cfg.get("env", {})),
        config_json={k: v for k, v in cfg.items() if k not in {"command", "env"}},
        is_default_for_target={k: bool(v) for k, v in (row.is_default_for_target or {}).items()},
        max_sessions=int(cfg.get("max_sessions", 4)),
        idle_ttl_seconds=int(cfg.get("idle_ttl_seconds", 60)),
        spawn_timeout_seconds=float(cfg.get("spawn_timeout_seconds", 10.0)),
        call_timeout_seconds=float(cfg.get("call_timeout_seconds", 30.0)),
    )


class McpRegistry:
    """In-memory provider catalog scoped per workspace."""

    def __init__(self) -> None:
        self._by_workspace: dict[str, dict[str, McpProviderConfig]] = {}

    async def load_for_workspace(
        self,
        session: AsyncSession,
        workspace_id: str,
    ) -> None:
        """Refresh the cached catalog for ``workspace_id`` from the DB.

        Seeds with bundled builtins (workspace_id reattributed to the target
        workspace) then overlays custom rows by ``name``.
        """
        from suitest_db.repositories.mcp_providers import McpProviderRepo  # late import

        repo = McpProviderRepo(session)
        rows = await repo.list_by_workspace(workspace_id)
        providers: dict[str, McpProviderConfig] = {
            spec.name: spec.model_copy(update={"workspace_id": workspace_id})
            for spec in BUILTIN_SPECS
        }
        for row in rows:
            providers[row.name] = _row_to_config(row)
        self._by_workspace[workspace_id] = providers
        log.info(
            "mcp.registry.loaded",
            workspace_id=workspace_id,
            count=len(providers),
            custom=len(rows),
        )

    def register_builtin(self, workspace_id: str) -> None:
        """Seed the workspace catalog with bundled builtins only (no DB hit).

        Used by tests and by code paths that want bundled providers available
        without persisting custom rows (e.g. ephemeral CI runs).
        """
        self._by_workspace[workspace_id] = {
            spec.name: spec.model_copy(update={"workspace_id": workspace_id})
            for spec in BUILTIN_SPECS
        }

    def get(self, workspace_id: str, name: str) -> McpProviderConfig:
        """Return the provider config for ``name`` in ``workspace_id``.

        Raises:
            McpProviderUnavailable: workspace not loaded or name not registered.
        """
        try:
            return self._by_workspace[workspace_id][name]
        except KeyError as exc:
            raise McpProviderUnavailable(
                f"unknown provider {name!r} for workspace {workspace_id!r}"
            ) from exc

    def list_for_workspace(self, workspace_id: str) -> list[McpProviderConfig]:
        """List every provider currently registered for ``workspace_id``."""
        return list(self._by_workspace.get(workspace_id, {}).values())

    @property
    def workspace_ids(self) -> list[str]:
        """Workspaces with a loaded catalog (used by health monitor)."""
        return list(self._by_workspace.keys())
