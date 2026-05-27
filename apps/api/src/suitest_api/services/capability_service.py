"""CapabilityService — resolves the deployment tier + optional workspace overlay.

The deployment tier comes from env (``resolve_capabilities``). A workspace MAY
have a materialised ``WorkspaceCapability`` row that overrides the tier/features
(set during onboarding or by an admin). This service layers the overlay on top of
the env snapshot. Task 5 (capability endpoint) consumes this.
"""

from __future__ import annotations

from suitest_core.capabilities import TierFlag, resolve_capabilities
from suitest_db.repositories.workspace_capabilities import WorkspaceCapabilityRepo
from suitest_shared.schemas.responses import WorkspaceCapabilityOut

from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_tier


class CapabilityService:
    def __init__(self, ctx: TenantContext, repo: WorkspaceCapabilityRepo) -> None:
        self._ctx = ctx
        self._repo = repo

    @require_tier(TierFlag.ANY)
    async def resolve(self) -> WorkspaceCapabilityOut:
        snapshot = resolve_capabilities()
        tier = snapshot.tier
        features = dict(snapshot.features)
        overlay = await self._repo.get(self._ctx.workspace_id)
        overlay_applied = False
        if overlay is not None:
            tier = overlay.tier
            overlay_applied = True
            # Materialised feature flags win over the env-derived defaults.
            for key, value in overlay.features_json.items():
                if isinstance(value, bool):
                    features[key] = value
        return WorkspaceCapabilityOut(
            workspace_id=self._ctx.workspace_id,
            tier=tier,
            features=features,
            overlay_applied=overlay_applied,
        )
