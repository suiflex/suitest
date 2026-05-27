"""IntegrationService — workspace-scoped, REDACTS secrets in every response.

``IntegrationOut`` has no ``secrets_encrypted`` field, so the encrypted blob can
never be serialised. We additionally build the DTO explicitly (rather than
``model_validate``) so we never even touch the decrypting ``secrets_encrypted``
attribute — only a boolean ``has_secrets`` derived from whether a value is set.
"""

from __future__ import annotations

from suitest_core.capabilities import TierFlag
from suitest_db.models.integration import Integration
from suitest_db.repositories.integrations import IntegrationRepo
from suitest_shared.domain.enums import IntegrationKind
from suitest_shared.schemas.responses import IntegrationOut

from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_tier


def _to_out(row: Integration) -> IntegrationOut:
    """Map an Integration ORM row to a redacted DTO (no secret material)."""
    return IntegrationOut(
        id=row.id,
        workspace_id=row.workspace_id,
        kind=row.kind,
        name=row.name,
        config=row.config,
        status=row.status,
        has_secrets=row.secrets_encrypted is not None,
        last_synced_at=row.last_synced_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class IntegrationService:
    def __init__(self, ctx: TenantContext, repo: IntegrationRepo) -> None:
        self._ctx = ctx
        self._repo = repo

    @require_tier(TierFlag.ANY)
    async def list(self, *, kind: IntegrationKind | None = None) -> list[IntegrationOut]:
        rows = await self._repo.list_by_workspace(self._ctx.workspace_id, kind=kind)
        return [_to_out(r) for r in rows]

    @require_tier(TierFlag.ANY)
    async def get_by_id(self, integration_id: str) -> IntegrationOut | None:
        row = await self._repo.get_by_id(integration_id)
        if row is None or row.workspace_id != self._ctx.workspace_id:
            return None
        return _to_out(row)
