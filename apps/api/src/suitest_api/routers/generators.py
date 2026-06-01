"""Generator endpoints (M2) — hosts the rule-based target classifier and, in
later tasks, the deterministic + LLM-driven generation endpoints.

``POST /generators/classify`` is pure rules (NO LLM) so it runs in every tier
(``TierFlag.ANY``). It returns the recommended :class:`TargetKind`, MCP provider
name + strategy. The provider ``id`` is resolved by name *within the caller's
workspace only* — if the named provider is registered in another workspace it
stays ``null`` (no cross-tenant leak).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_agent.generators.classifier import classify
from suitest_core.capabilities import TierFlag
from suitest_db.repositories.generator_runs import GeneratorRunRepo
from suitest_db.repositories.mcp_providers import McpProviderRepo
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.suites import SuiteRepo
from suitest_shared.domain.enums import Role
from suitest_shared.schemas.generator_input import (
    ClassificationResult,
    GenerationInput,
    GeneratorSseEvent,
    OpenApiGenerateRequest,
)

from suitest_api.auth.db import get_async_session
from suitest_api.deps.role import require_role
from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_tier
from suitest_api.services.generator_service import (
    GeneratorService,
    SuiteNotInWorkspaceError,
)

router = APIRouter(prefix="/api/v1", tags=["generators"])

# Generation mutates the workspace (creates DRAFT cases) → QA or higher.
_WRITER_ROLES: set[Role] = {Role.QA, Role.ADMIN, Role.OWNER}


def _format_sse(event: GeneratorSseEvent) -> str:
    """Render one event as a wire-format SSE frame (``event:``/``data:``/blank)."""
    return f"event: {event.kind}\ndata: {json.dumps(event.data)}\n\n"


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


def _build_generator_service(
    session: AsyncSession, http_client: httpx.AsyncClient
) -> GeneratorService:
    """Compose a :class:`GeneratorService` from a session + an HTTP client."""
    return GeneratorService(
        session,
        GeneratorRunRepo(session),
        SuiteRepo(session),
        ProjectRepo(session),
        http_client,
    )


# Deterministic OpenAPI → contract-suite generation. Pure rules (NO LLM) so it
# runs in every tier (``TierFlag.ANY``). Streams ``progress``/``case``/``complete``
# (or a single ``error``) over SSE. Generation creates DRAFT cases → QA+ gate.
@router.post("/generators/openapi")
@require_tier(TierFlag.ANY)
async def generate_openapi(
    payload: OpenApiGenerateRequest,
    ctx: TenantContext = Depends(require_role(_WRITER_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> StreamingResponse:
    """Generate a per-operation contract suite from an OpenAPI 3.0 spec (SSE)."""
    # Own HTTP client for the (optional) spec fetch — closed when the stream ends.
    http_client = httpx.AsyncClient(timeout=30.0)
    svc = _build_generator_service(session, http_client)

    # Resolve the suite up front so an unknown/cross-workspace target surfaces as
    # a real 404 (not an in-band SSE error). ``run_openapi`` re-checks, but doing
    # it here lets us answer before opening the event stream.
    if not await svc.suite_in_scope(payload.target_suite_id, ctx.workspace_id):
        await http_client.aclose()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="suite not found")

    async def stream() -> AsyncIterator[bytes]:
        try:
            async for event in svc.run_openapi(ctx.workspace_id, ctx.user_id, payload):
                yield _format_sse(event).encode()
        except SuiteNotInWorkspaceError:
            # Defensive — the up-front check already covers this; emit an error
            # frame rather than tearing the stream if state changed mid-flight.
            err = GeneratorSseEvent(
                kind="error",
                data={"code": "RESOURCE_NOT_FOUND", "message": "suite not found"},
            )
            yield _format_sse(err).encode()
        finally:
            await http_client.aclose()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
