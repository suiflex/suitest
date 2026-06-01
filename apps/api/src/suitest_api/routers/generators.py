"""Generator endpoints (M2) — hosts the rule-based target classifier and, in
later tasks, the deterministic + LLM-driven generation endpoints.

``POST /generators/classify`` is pure rules (NO LLM) so it runs in every tier
(``TierFlag.ANY``). It returns the recommended :class:`TargetKind`, MCP provider
name + strategy. The provider ``id`` is resolved by name *within the caller's
workspace only* — if the named provider is registered in another workspace it
stays ``null`` (no cross-tenant leak).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_agent.generators.classifier import classify
from suitest_core.capabilities import TierFlag
from suitest_db.repositories.mcp_providers import McpProviderRepo
from suitest_shared.domain.enums import Role
from suitest_shared.schemas.generator_input import ClassificationResult, GenerationInput

from suitest_api.auth.db import get_async_session
from suitest_api.deps.role import require_role
from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_tier

router = APIRouter(prefix="/api/v1", tags=["generators"])


# Deterministic classifier runs in every tier. ``require_tier`` is a no-op
# recorder in M1a (it stamps the required ``TierFlag`` on the wrapped coroutine
# so M3 enforcement finds the gate) — it wraps the handler rather than acting as
# a FastAPI ``Depends`` dependency.
@router.post("/generators/classify", response_model=ClassificationResult)
@require_tier(TierFlag.ANY)
async def classify_input(
    payload: GenerationInput,
    ctx: TenantContext = Depends(require_role({Role.QA, Role.ADMIN, Role.OWNER})),
    session: AsyncSession = Depends(get_async_session),
) -> ClassificationResult:
    """Classify a generation input into a target kind + recommended strategy/MCP."""
    result = classify(payload)
    provider = await McpProviderRepo(session).get_by_name(
        workspace_id=ctx.workspace_id, name=result.recommended_mcp.name
    )
    if provider is not None:
        result.recommended_mcp.id = provider.id
    return result
