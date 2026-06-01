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
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_agent.generators.classifier import classify
from suitest_agent.generators.recorder import (
    RecorderSessionExpired,
    RecorderSessionManager,
    RecorderSessionNotFound,
)
from suitest_core.capabilities import TierFlag
from suitest_db.repositories.generator_runs import GeneratorRunRepo
from suitest_db.repositories.llm_configs import LLMConfigRepo
from suitest_db.repositories.mcp_providers import McpProviderRepo
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.recorder_sessions import RecorderSessionRepo
from suitest_db.repositories.suites import SuiteRepo
from suitest_mcp.invoker import McpInvoker
from suitest_mcp.pool import McpPool
from suitest_mcp.registry import McpRegistry
from suitest_shared.domain.enums import Role, TargetKind
from suitest_shared.schemas.generator_input import (
    ClassificationResult,
    CrawlerGenerateRequest,
    GenerationInput,
    GeneratorSseEvent,
    McpDiscoveryGenerateRequest,
    OpenApiGenerateRequest,
    PrdGenerateRequest,
    RecorderFinalizeRequest,
    RecorderSessionStartRequest,
    RecorderSessionStartResponse,
)

from suitest_api.auth.db import async_session_maker, get_async_session
from suitest_api.deps.role import require_role
from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_tier
from suitest_api.routers.test_cases import _detail_with_steps
from suitest_api.schemas.test_case import TestCaseDetail
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

    # M3-8: resolve the workspace's active LLM only when edge-case enrichment is
    # requested. Absence is NOT an error — the deterministic suite still runs and
    # the service emits an ``llm_enrich_skipped`` frame (ZERO-first).
    llm_provider = llm_model = llm_api_key = llm_base_url = None
    if payload.options.include_llm_edge_cases:
        config = await LLMConfigRepo(session).get_active(ctx.workspace_id)
        if config is not None:
            llm_provider = config.provider
            llm_model = config.model
            llm_api_key = config.api_key_encrypted
            raw_base = config.config_json.get("base_url")
            llm_base_url = raw_base if isinstance(raw_base, str) else None

    async def stream() -> AsyncIterator[bytes]:
        try:
            async for event in svc.run_openapi(
                ctx.workspace_id,
                ctx.user_id,
                payload,
                llm_provider=llm_provider,
                llm_model=llm_model,
                llm_api_key=llm_api_key,
                llm_base_url=llm_base_url,
            ):
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


# LLM-driven PRD → test-case generation (M3-6). CLOUD/LOCAL only: the real tier
# gate is an active ``LLMConfig`` (409 ``LLM_NOT_CONFIGURED`` when absent). Streams
# ``progress``/``case``/``complete`` (or a single ``error``) over SSE. QA+ gate.
@router.post("/generators/prd")
@require_tier(TierFlag.CLOUD | TierFlag.LOCAL)
async def generate_prd(
    payload: PrdGenerateRequest,
    ctx: TenantContext = Depends(require_role(_WRITER_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> StreamingResponse:
    """Generate DRAFT cases from a PRD / user story via the LLM agent (SSE)."""
    # Tier gate: an LLM must be configured + active for this workspace. Without
    # one the workspace is effectively ZERO → reject before opening the stream.
    config = await LLMConfigRepo(session).get_active(ctx.workspace_id)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="no active LLM configured for this workspace",
        )

    # PRD generation never fetches over HTTP, but GeneratorService's constructor
    # requires a client; give it a closed-on-exit one.
    http_client = httpx.AsyncClient(timeout=30.0)
    await http_client.aclose()
    svc = _build_generator_service(session, http_client)
    if not await svc.suite_in_scope(payload.target_suite_id, ctx.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="suite not found")

    base_url = config.config_json.get("base_url")
    base_url = base_url if isinstance(base_url, str) else None

    async def stream() -> AsyncIterator[bytes]:
        try:
            async for event in svc.run_prd(
                ctx.workspace_id,
                ctx.user_id,
                payload,
                provider_name=config.provider,
                model=config.model,
                api_key=config.api_key_encrypted,
                base_url=base_url,
            ):
                yield _format_sse(event).encode()
        except SuiteNotInWorkspaceError:
            err = GeneratorSseEvent(
                kind="error",
                data={"code": "RESOURCE_NOT_FOUND", "message": "suite not found"},
            )
            yield _format_sse(err).encode()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _provider_target_kind(is_default_for_target: dict[str, object]) -> TargetKind:
    """Pick the provider's primary :class:`TargetKind` from its routing map.

    First key flagged ``True`` that names a valid ``TargetKind`` wins; otherwise
    ``CUSTOM`` (the provider routes nothing by default, so cases stay generic).
    """
    for key, value in is_default_for_target.items():
        if value:
            try:
                return TargetKind(key)
            except ValueError:
                continue
    return TargetKind.CUSTOM


# LLM-driven MCP tool-discovery → test-case generation (M3-9). CLOUD/LOCAL only:
# the real tier gate is an active ``LLMConfig`` (409). Targets a registered MCP
# provider and proposes cases from its persisted tool catalog. SSE. QA+ gate.
@router.post("/generators/mcp-discovery")
@require_tier(TierFlag.CLOUD | TierFlag.LOCAL)
async def generate_mcp_discovery(
    payload: McpDiscoveryGenerateRequest,
    ctx: TenantContext = Depends(require_role(_WRITER_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> StreamingResponse:
    """Generate DRAFT cases by exploring a registered MCP provider's tools (SSE)."""
    config = await LLMConfigRepo(session).get_active(ctx.workspace_id)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="no active LLM configured for this workspace",
        )

    provider_repo = McpProviderRepo(session)
    mcp_provider = await provider_repo.get_by_id(payload.mcp_provider_id)
    # Workspace-owned or a bundled builtin (workspace_id NULL); never another tenant's.
    if mcp_provider is None or mcp_provider.workspace_id not in (ctx.workspace_id, None):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="provider not found")

    raw_tools = mcp_provider.config_json.get("tools", [])
    mcp_tools = [t for t in raw_tools if isinstance(t, dict)] if isinstance(raw_tools, list) else []
    target_kind = _provider_target_kind(mcp_provider.is_default_for_target or {})

    http_client = httpx.AsyncClient(timeout=30.0)
    await http_client.aclose()
    svc = _build_generator_service(session, http_client)
    if not await svc.suite_in_scope(payload.target_suite_id, ctx.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="suite not found")

    base_url = config.config_json.get("base_url")
    base_url = base_url if isinstance(base_url, str) else None

    async def stream() -> AsyncIterator[bytes]:
        try:
            async for event in svc.run_mcp_discovery(
                ctx.workspace_id,
                ctx.user_id,
                payload,
                provider_name=config.provider,
                model=config.model,
                api_key=config.api_key_encrypted,
                base_url=base_url,
                mcp_provider_name=mcp_provider.name,
                mcp_target_kind=target_kind,
                mcp_tools=mcp_tools,
            ):
                yield _format_sse(event).encode()
        except SuiteNotInWorkspaceError:
            err = GeneratorSseEvent(
                kind="error",
                data={"code": "RESOURCE_NOT_FOUND", "message": "suite not found"},
            )
            yield _format_sse(err).encode()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _build_mcp_invoker(workspace_id: str, request: Request) -> McpInvoker:
    """Compose a real :class:`McpInvoker` for the crawler (bundled providers).

    Mirrors the runner's wiring (``apps/runner/.../worker.py``): a per-request
    registry seeded with the bundled builtins (so ``playwright-mcp`` resolves),
    a fresh :class:`McpPool`, the app-wide ``ws_redis`` for tool telemetry, and
    ``async_session_maker`` for audit rows. ``health=None`` (no monitor on the
    API process) treats every routable provider as healthy.
    """
    registry = McpRegistry()
    registry.register_builtin(workspace_id)
    redis_client = getattr(request.app.state, "ws_redis", None)
    if redis_client is None:  # pragma: no cover - prod wires ws_redis at lifespan
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="mcp transport unavailable",
        )
    return McpInvoker(
        registry=registry,
        pool=McpPool(),
        health=None,
        redis_client=redis_client,
        audit_session_factory=async_session_maker,
    )


# Heuristic URL crawler → FE_WEB smoke + form suite. Pure heuristics (NO LLM) so
# it runs in every tier (``TierFlag.ANY``). Drives ``playwright-mcp`` to BFS the
# site and streams ``progress``/``case``/``complete`` over SSE. QA+ gate (it
# creates DRAFT cases).
@router.post("/generators/crawler")
@require_tier(TierFlag.ANY)
async def generate_crawler(
    payload: CrawlerGenerateRequest,
    request: Request,
    ctx: TenantContext = Depends(require_role(_WRITER_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> StreamingResponse:
    """Generate a smoke + form suite by crawling a start URL (SSE)."""
    # Crawler never fetches specs over HTTP itself, but GeneratorService's
    # constructor requires a client; give it one scoped to the request.
    http_client = httpx.AsyncClient(timeout=30.0)
    invoker = _build_mcp_invoker(ctx.workspace_id, request)
    svc = GeneratorService(
        session,
        GeneratorRunRepo(session),
        SuiteRepo(session),
        ProjectRepo(session),
        http_client,
        mcp_invoker=invoker,
    )

    # Resolve the suite up front so an unknown/cross-workspace target is a real
    # 404 before any event byte is sent (run_crawler re-checks defensively).
    if not await svc.suite_in_scope(payload.target_suite_id, ctx.workspace_id):
        await http_client.aclose()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="suite not found")

    async def stream() -> AsyncIterator[bytes]:
        try:
            async for event in svc.run_crawler(ctx.workspace_id, ctx.user_id, payload):
                yield _format_sse(event).encode()
        except SuiteNotInWorkspaceError:
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


# ---------------------------------------------------------------------------
# M2 Task 4 — live browser recorder
# ---------------------------------------------------------------------------
#
# Deterministic event→step mapping (NO LLM) → ``TierFlag.ANY``. A session opens
# a Playwright-MCP recording, events stream over the WS gateway (``recorder:<id>``
# room), and ``/finalize`` converts the captured log into a DRAFT TestCase. All
# three endpoints are QA+ (they create / mutate sessions + cases).


@router.post("/generators/recorder/sessions", response_model=RecorderSessionStartResponse)
@require_tier(TierFlag.ANY)
async def start_recorder_session(
    payload: RecorderSessionStartRequest,
    request: Request,
    ctx: TenantContext = Depends(require_role(_WRITER_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> RecorderSessionStartResponse:
    """Open a live browser-recording session. Returns the WS room to subscribe."""
    project = await ProjectRepo(session).get_by_id(payload.project_id)
    if project is None or project.workspace_id != ctx.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")

    invoker = _build_mcp_invoker(ctx.workspace_id, request)
    manager = RecorderSessionManager(
        invoker, RecorderSessionRepo(session), request.app.state.ws_redis
    )
    row, browser_url = await manager.start(ctx.workspace_id, ctx.user_id, payload)
    await session.commit()
    return RecorderSessionStartResponse(
        session_id=row.id,
        ws_room=row.ws_room,
        browser_url=browser_url,
        expires_at=row.expires_at,
    )


@router.post(
    "/generators/recorder/sessions/{session_id}/finalize",
    response_model=TestCaseDetail,
)
@require_tier(TierFlag.ANY)
async def finalize_recorder_session(
    session_id: str,
    payload: RecorderFinalizeRequest,
    request: Request,
    ctx: TenantContext = Depends(require_role(_WRITER_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> TestCaseDetail:
    """Convert a session's captured events into a DRAFT TestCase + return it."""
    # The recorder finalize never fetches over HTTP, but GeneratorService's
    # constructor requires a client; give it a closed-on-exit one.
    http_client = httpx.AsyncClient(timeout=30.0)
    await http_client.aclose()
    svc = GeneratorService(
        session,
        GeneratorRunRepo(session),
        SuiteRepo(session),
        ProjectRepo(session),
        http_client,
    )
    if not await svc.suite_in_scope(payload.target_suite_id, ctx.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="suite not found")

    invoker = _build_mcp_invoker(ctx.workspace_id, request)
    manager = RecorderSessionManager(
        invoker, RecorderSessionRepo(session), request.app.state.ws_redis
    )
    try:
        _row, draft = await manager.finalize(session_id, ctx.workspace_id, ctx.user_id, payload)
    except RecorderSessionNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RecorderSessionExpired as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(exc)) from exc

    case_id = await svc.persist_recorder_case(
        draft, suite_id=payload.target_suite_id, workspace_id=ctx.workspace_id
    )
    await manager.mark_finalized(session_id, ctx.workspace_id, case_id)
    await session.commit()
    return await _detail_with_steps(request, session, ctx.workspace_id, case_id)


@router.delete(
    "/generators/recorder/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
@require_tier(TierFlag.ANY)
async def cancel_recorder_session(
    session_id: str,
    request: Request,
    ctx: TenantContext = Depends(require_role(_WRITER_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Cancel an active recording session (idempotent within its lifetime)."""
    invoker = _build_mcp_invoker(ctx.workspace_id, request)
    manager = RecorderSessionManager(
        invoker, RecorderSessionRepo(session), request.app.state.ws_redis
    )
    try:
        await manager.cancel(session_id, ctx.workspace_id)
    except RecorderSessionNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RecorderSessionExpired as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(exc)) from exc
    await session.commit()
