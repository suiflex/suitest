"""Generator endpoints (M2) — hosts the rule-based target classifier and, in
later tasks, the deterministic + LLM-driven generation endpoints.

``POST /generators/classify`` is pure rules (no LLM). It returns the recommended
:class:`TargetKind`, MCP provider
name + strategy. The provider ``id`` is resolved by name *within the caller's
workspace only* — if the named provider is registered in another workspace it
stays ``null`` (no cross-tenant leak).
"""

from __future__ import annotations

import ipaddress
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_agent.generators.classifier import classify
from suitest_agent.generators.recorder import (
    RecorderSessionExpired,
    RecorderSessionManager,
    RecorderSessionNotFound,
)
from suitest_db.repositories.generator_runs import GeneratorRunRepo
from suitest_db.repositories.llm_configs import LLMConfigRepo
from suitest_db.repositories.mcp_providers import McpProviderRepo
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.recorder_sessions import RecorderSessionRepo
from suitest_db.repositories.suites import SuiteRepo
from suitest_mcp.invoker import McpInvoker, NullPublisher
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
    RecorderEvent,
    RecorderFinalizeRequest,
    RecorderSessionStartRequest,
    RecorderSessionStartResponse,
    UrlSemanticGenerateRequest,
)

from suitest_api.auth.db import async_session_maker, get_async_session
from suitest_api.deps.role import require_role
from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_llm_ready
from suitest_api.routers.test_cases import _detail_with_steps
from suitest_api.schemas.test_case import TestCaseDetail
from suitest_api.services.generator_service import (
    GeneratorService,
    SuiteNotInWorkspaceError,
)
from suitest_api.services.llm_credentials import resolve_for_config

router = APIRouter(prefix="/api/v1", tags=["generators"])

log = logging.getLogger(__name__)

# Generation mutates the workspace (creates DRAFT cases) → QA or higher.
_WRITER_ROLES: set[Role] = {Role.QA, Role.ADMIN, Role.OWNER}


def _format_sse(event: GeneratorSseEvent) -> str:
    """Render one event as a wire-format SSE frame (``event:``/``data:``/blank)."""
    return f"event: {event.kind}\ndata: {json.dumps(event.data)}\n\n"


# The deterministic classifier does not require an LLM or MCP execution.
@router.post("/generators/classify", response_model=ClassificationResult)
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


# Deterministic OpenAPI → contract-suite generation. Pure rules (no LLM).
# Streams ``progress``/``case``/``complete``
# (or a single ``error``) over SSE. Generation creates DRAFT cases → QA+ gate.
@router.post("/generators/openapi")
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
    llm_credential = None
    llm_model = None
    if payload.options.include_llm_edge_cases:
        config = await LLMConfigRepo(session).get_active(ctx.workspace_id)
        if config is not None:
            llm_credential = await resolve_for_config(session, config)
            llm_model = config.model

    async def stream() -> AsyncIterator[bytes]:
        try:
            async for event in svc.run_openapi(
                ctx.workspace_id,
                ctx.user_id,
                payload,
                llm_credential=llm_credential,
                llm_model=llm_model,
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


# LLM-driven PRD → test-case generation (M3-6). The readiness
# gate requires an active validated ``LLMConfig`` (409 ``LLM_NOT_READY`` otherwise). Streams
# ``progress``/``case``/``complete`` (or a single ``error``) over SSE. QA+ gate.
@router.post("/generators/prd", dependencies=[Depends(require_llm_ready)])
async def generate_prd(
    payload: PrdGenerateRequest,
    ctx: TenantContext = Depends(require_role(_WRITER_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> StreamingResponse:
    """Generate DRAFT cases from a PRD / user story via the LLM agent (SSE)."""
    # The readiness decorator guarantees an active validated workspace LLM.
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

    credential = await resolve_for_config(session, config)

    async def stream() -> AsyncIterator[bytes]:
        try:
            async for event in svc.run_prd(
                ctx.workspace_id,
                ctx.user_id,
                payload,
                credential=credential,
                model=config.model,
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


# LLM-driven semantic URL → FE_WEB journey generation (M3-7):
# readiness requires an active validated ``LLMConfig`` (409). Decomposes an intent into
# browser journeys driven by playwright-mcp. SSE. QA+ gate.
@router.post("/generators/url-semantic", dependencies=[Depends(require_llm_ready)])
async def generate_url_semantic(
    payload: UrlSemanticGenerateRequest,
    ctx: TenantContext = Depends(require_role(_WRITER_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> StreamingResponse:
    """Generate FE_WEB journey cases from a URL + natural-language intent (SSE)."""
    config = await LLMConfigRepo(session).get_active(ctx.workspace_id)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="no active LLM configured for this workspace",
        )

    http_client = httpx.AsyncClient(timeout=30.0)
    await http_client.aclose()
    svc = _build_generator_service(session, http_client)
    if not await svc.suite_in_scope(payload.target_suite_id, ctx.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="suite not found")

    credential = await resolve_for_config(session, config)

    async def stream() -> AsyncIterator[bytes]:
        try:
            async for event in svc.run_url_semantic(
                ctx.workspace_id,
                ctx.user_id,
                payload,
                credential=credential,
                model=config.model,
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


# LLM-driven MCP tool-discovery → test-case generation (M3-9):
# readiness requires an active validated ``LLMConfig`` (409). Targets a registered MCP
# provider and proposes cases from its persisted tool catalog. SSE. QA+ gate.
@router.post("/generators/mcp-discovery", dependencies=[Depends(require_llm_ready)])
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

    credential = await resolve_for_config(session, config)

    async def stream() -> AsyncIterator[bytes]:
        try:
            async for event in svc.run_mcp_discovery(
                ctx.workspace_id,
                ctx.user_id,
                payload,
                credential=credential,
                model=config.model,
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


def _build_mcp_invoker(
    workspace_id: str,
    request: Request,
) -> McpInvoker:
    """Compose a real :class:`McpInvoker` for generators (bundled builtins).

    Mirrors the runner's wiring (``apps/runner/.../worker.py``): a per-request
    registry seeded with bundled builtins (so ``playwright-mcp`` resolves),
    a fresh :class:`McpPool`, the app-wide ``ws_redis`` (falling back to
    :class:`NullPublisher` in local mode without Redis) for tool telemetry, and
    ``async_session_maker`` for audit rows. ``health=None`` (no monitor on the
    API process) treats every routable provider as healthy.
    """
    registry = McpRegistry()
    registry.register_builtin(workspace_id)
    redis_client = getattr(request.app.state, "ws_redis", None)
    if redis_client is None:
        redis_client = NullPublisher()
    return McpInvoker(
        registry=registry,
        pool=McpPool(),
        health=None,
        redis_client=redis_client,
        audit_session_factory=async_session_maker,
        # Execution-layer gate: crawler & recorder run in Tier ZERO without requiring LLM.
        llm_ready_guard=None,
    )


# Heuristic URL crawler → FE_WEB smoke + form suite. Drives ``playwright-mcp`` to BFS the
# site and streams ``progress``/``case``/``complete`` over SSE. QA+ gate (it
# creates DRAFT cases).
@router.post("/generators/crawler")
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
# Deterministic event→step mapping. A session opens
# a Playwright-MCP recording, events stream over the WS gateway (``recorder:<id>``
# room), and ``/finalize`` converts the captured log into a DRAFT TestCase. All
# three endpoints are QA+ (they create / mutate sessions + cases).


def _inject_recorder_script(
    html: str,
    session_id: str,
    workspace_id: str = "",
    target_url: str = "",
) -> str:
    """Inject base tag and inlined recorder agent script into target page HTML."""
    import re

    # Neutralize any meta CSP headers in the target HTML that would block recorder communication
    cleaned_html = re.sub(
        r'<meta[^>]*http-equiv=["\']?content-security-policy["\']?[^>]*>',
        "",
        html,
        flags=re.IGNORECASE,
    )

    base_tag = f'<base href="{target_url}">' if target_url else ""
    script_tag = (
        f'<script src="/recorder_agent.js" data-session-id="{session_id}"></script>\n'
        f'<script src="/api/v1/generators/recorder/agent.js" data-session-id="{session_id}"></script>'
    )
    agent_code = _get_agent_js()
    target_url_json = json.dumps(target_url) if target_url else '""'
    browse_endpoint = f"/api/v1/generators/recorder/sessions/{session_id}/browse"
    inlined_agent = (
        f'<script id="suitest-recorder-bootstrap">\n'
        f'  window.__SUITEST_SESSION_ID__ = "{session_id}";\n'
        f'  window.__SUITEST_WORKSPACE_ID__ = "{workspace_id}";\n'
        f'  window.__SUITEST_API_URL__ = "/api/v1";\n'
        f"  window.__SUITEST_TARGET_URL__ = {target_url_json};\n"
        f'  window.__SUITEST_BROWSE_ENDPOINT__ = "{browse_endpoint}";\n'
        f"  try {{\n"
        f"    var _origUrl = window.location.href;\n"
        f"    window.__SUITEST_BROWSE_ORIGINAL_URL__ = _origUrl;\n"
        f"    if ({target_url_json}) {{\n"
        f"      var _tUrl = new URL({target_url_json});\n"
        f'      var _tPath = (_tUrl.pathname || "/") + (_tUrl.search || "") + (_tUrl.hash || "");\n'
        f'      if (window.location.pathname.includes("/browse") && window.location.pathname !== _tPath) {{\n'
        f'        window.history.replaceState({{ __suitest_browse: _origUrl }}, "", window.location.origin + _tPath);\n'
        f"      }}\n"
        f"    }}\n"
        f'  }} catch (e) {{ console.debug("[Suitest Recorder] Failed to align SPA virtual path:", e); }}\n'
        f"</script>\n"
        f'<script id="suitest-recorder-agent">\n'
        f"{agent_code}\n"
        f"</script>"
    )
    injection = f"{base_tag}\n{script_tag}\n{inlined_agent}\n"

    lower_html = cleaned_html.lower()
    head_pos = lower_html.find("<head")
    if head_pos != -1:
        close_head_pos = lower_html.find(">", head_pos)
        if close_head_pos != -1:
            return (
                cleaned_html[: close_head_pos + 1]
                + f"\n{injection}"
                + cleaned_html[close_head_pos + 1 :]
            )

    body_pos = lower_html.find("<body")
    if body_pos != -1:
        close_body_pos = lower_html.find(">", body_pos)
        if close_body_pos != -1:
            return (
                cleaned_html[: close_body_pos + 1]
                + f"\n{injection}"
                + cleaned_html[close_body_pos + 1 :]
            )

    return f"{injection}{cleaned_html}"


class RecorderSessionDetailResponse(BaseModel):
    """Detailed response for an active or past recording session."""

    id: str
    workspace_id: str
    project_id: str
    start_url: str
    status: str
    ws_room: str
    browser_url: str | None = None
    captured_events_count: int
    captured_events: list[dict[str, Any]]
    expires_at: datetime
    started_at: datetime


_AGENT_JS_PATH = (
    Path(__file__).resolve().parents[5] / "apps" / "web" / "public" / "recorder_agent.js"
)
_AGENT_JS_CACHE: str | None = None


def _get_agent_js() -> str:
    if _AGENT_JS_PATH.is_file():
        return _AGENT_JS_PATH.read_text(encoding="utf-8")
    return "// Suitest recorder agent"


@router.get("/generators/recorder/agent.js", include_in_schema=False)
async def get_recorder_agent_script() -> Response:
    """Serve the client-side recorder agent JS directly from the backend."""
    return Response(
        content=_get_agent_js(),
        media_type="application/javascript",
        headers={"Access-Control-Allow-Origin": "*"},
    )


@router.post(
    "/generators/recorder/sessions",
    response_model=RecorderSessionStartResponse,
)
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
    api_base_url = str(request.base_url).rstrip("/") + "/api/v1"
    manager = RecorderSessionManager(
        invoker,
        RecorderSessionRepo(session),
        getattr(request.app.state, "ws_redis", None),
        api_base_url=api_base_url,
    )
    row, browser_url = await manager.start(ctx.workspace_id, ctx.user_id, payload)

    from suitest_agent.generators.browser_launcher import has_active_headed_browser

    is_headed = has_active_headed_browser(row.id)
    if not browser_url:
        encoded_url = quote(payload.start_url, safe="")
        browser_url = f"/api/v1/generators/recorder/sessions/{row.id}/browse?url={encoded_url}&workspaceId={ctx.workspace_id}"

    await session.commit()
    return RecorderSessionStartResponse(
        session_id=row.id,
        ws_room=row.ws_room,
        browser_url=browser_url,
        is_headed=is_headed,
        workspace_id=ctx.workspace_id,
        expires_at=row.expires_at,
    )


@router.get(
    "/generators/recorder/sessions/{session_id}",
    response_model=RecorderSessionDetailResponse,
)
async def get_recorder_session(
    session_id: str,
    ctx: TenantContext = Depends(require_role(_WRITER_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> RecorderSessionDetailResponse:
    """Retrieve details and captured events for a recording session."""
    repo = RecorderSessionRepo(session)
    row = await repo.get_by_id(session_id, workspace_id=ctx.workspace_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")

    encoded_url = quote(row.start_url, safe="")
    browser_url = f"/api/v1/generators/recorder/sessions/{row.id}/browse?url={encoded_url}&workspaceId={ctx.workspace_id}"

    return RecorderSessionDetailResponse(
        id=row.id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        start_url=row.start_url,
        status=row.status,
        ws_room=row.ws_room,
        browser_url=browser_url,
        captured_events_count=len(row.captured_events_json or []),
        captured_events=row.captured_events_json or [],
        expires_at=row.expires_at,
        started_at=row.started_at,
    )


def _is_restricted_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _validate_target_url(url: str) -> str:
    """Validate that target_url uses http(s) and does not point to private/loopback addresses."""
    target_url = url.strip()
    if not target_url.startswith(("http://", "https://")):
        target_url = "https://" + target_url

    parsed = urlparse(target_url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only http and https schemes are permitted",
        )
    hostname = parsed.hostname or ""
    if not hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid URL target host",
        )
    if hostname.lower() in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target host not allowed",
        )
    try:
        ip = ipaddress.ip_address(hostname)
        if _is_restricted_ip(ip):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Private network addresses are not allowed",
            )
    except ValueError:
        import socket

        try:
            addr_info = socket.getaddrinfo(hostname, None)
            for _, _, _, _, sockaddr in addr_info:
                ip_addr = ipaddress.ip_address(sockaddr[0])
                if _is_restricted_ip(ip_addr):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Target resolves to a restricted private/internal address",
                    )
        except socket.gaierror as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not resolve target hostname: {hostname}",
            ) from exc

    return target_url


def _check_browse_session(rec_session: Any) -> Response | None:
    """Verify recording session exists, is active, and is not expired."""
    if rec_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="recorder session not found"
        )
    if rec_session.status != "active":
        return HTMLResponse(
            f"<html><body style='font-family: sans-serif; padding: 40px; text-align: center; background: #0f172a; color: #f8fafc;'>"
            f"<h2>Session {rec_session.status}</h2>"
            f"<p>This recorder session is no longer active ({rec_session.status}).</p>"
            f"</body></html>",
            status_code=status.HTTP_410_GONE,
        )

    expires_at = rec_session.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < datetime.now(tz=UTC):
            return HTMLResponse(
                "<html><body style='font-family: sans-serif; padding: 40px; text-align: center; background: #0f172a; color: #f8fafc;'>"
                "<h2>Session Expired</h2>"
                "<p>This recorder session has expired.</p>"
                "</body></html>",
                status_code=status.HTTP_410_GONE,
            )
    return None


@router.api_route(
    "/generators/recorder/sessions/{session_id}/browse",
    methods=["GET", "HEAD"],
    include_in_schema=False,
)
async def browse_recorder_session(
    session_id: str,
    url: str,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    """Interactive zero-install web recorder proxy endpoint.

    Fetches the requested target URL, strips blocking CSP/frame headers, injects
    the recorder_agent.js script + <base> tag, and renders the page in the caller's browser.
    Authorized via the unguessable active session_id so standard browser tab navigations
    and page refreshes function seamlessly without custom HTTP headers.
    """
    repo = RecorderSessionRepo(session)
    rec_session = await repo.get_by_id(session_id)
    if rec_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="recorder session not found"
        )
    session_err = _check_browse_session(rec_session)
    if session_err is not None:
        return session_err

    target_url = _validate_target_url(url)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=False, verify=True) as client:
            curr_url = target_url
            for _ in range(5):
                resp = await client.request(request.method, curr_url, headers=headers)
                if resp.is_redirect and "location" in resp.headers:
                    next_url = str(resp.url.join(resp.headers["location"]))
                    curr_url = _validate_target_url(next_url)
                    continue
                break
    except HTTPException:
        raise
    except Exception as exc:
        return HTMLResponse(
            f"<html><body style='font-family: sans-serif; padding: 40px; background: #0f172a; color: #f8fafc;'>"
            f"<h2 style='color: #ef4444;'>Unable to load target site</h2>"
            f"<p>Could not connect to: <code>{target_url}</code></p>"
            f"<p style='color: #94a3b8;'>Error: {exc}</p>"
            f"<a href='javascript:location.reload()' style='color: #38bdf8;'>Retry</a>"
            f"</body></html>",
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    content_type = resp.headers.get("content-type", "")
    if "text/html" in content_type:
        html = resp.text
        modified_html = _inject_recorder_script(
            html, session_id, workspace_id=rec_session.workspace_id, target_url=str(resp.url)
        )
        return HTMLResponse(content=modified_html, status_code=resp.status_code)

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=content_type,
    )


@router.options("/generators/recorder/sessions/{session_id}/events")
async def options_recorder_session_event(session_id: str, request: Request) -> Response:
    """CORS preflight for recorder events from proxy, bookmarklet, or external origins."""
    origin = request.headers.get("origin") or "*"
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Private-Network": "true",
        },
    )


@router.post(
    "/generators/recorder/sessions/{session_id}/events",
    response_model=dict[str, Any],
)
async def append_recorder_session_event(
    session_id: str,
    payload: RecorderEvent,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Append one captured interaction event to an active recording session.

    Authorizes via the active recording session token: looks up the unguessable session_id,
    verifies it is active and not expired, and appends the event. Sets CORS headers so
    recording works across origins (in-browser proxy, bookmarklet, intranet tabs).
    """
    repo = RecorderSessionRepo(session)
    rec_session = await repo.get_by_id(session_id)
    if rec_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    if rec_session.status != "active":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"session is {rec_session.status}",
        )
    expires_at = rec_session.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < datetime.now(tz=UTC):
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="session has expired")

    ws_header = request.headers.get("x-workspace-id") or request.query_params.get("workspaceId")
    if ws_header and ws_header.strip() != rec_session.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session not found in specified workspace",
        )

    invoker = _build_mcp_invoker(rec_session.workspace_id, request)
    manager = RecorderSessionManager(invoker, repo, getattr(request.app.state, "ws_redis", None))
    try:
        await manager.append_event(session_id, rec_session.workspace_id, payload)
    except RecorderSessionNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RecorderSessionExpired as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(exc)) from exc

    await session.commit()
    origin = request.headers.get("origin") or "*"
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    return {"ok": True, "count": len(rec_session.captured_events_json or [])}


@router.post(
    "/generators/recorder/sessions/{session_id}/finalize",
    response_model=TestCaseDetail,
)
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
        invoker, RecorderSessionRepo(session), getattr(request.app.state, "ws_redis", None)
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
async def cancel_recorder_session(
    session_id: str,
    request: Request,
    ctx: TenantContext = Depends(require_role(_WRITER_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Cancel an active recording session (idempotent within its lifetime)."""
    invoker = _build_mcp_invoker(ctx.workspace_id, request)
    manager = RecorderSessionManager(
        invoker, RecorderSessionRepo(session), getattr(request.app.state, "ws_redis", None)
    )
    try:
        await manager.cancel(session_id, ctx.workspace_id)
    except RecorderSessionNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RecorderSessionExpired as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(exc)) from exc
    await session.commit()


# ---------------------------------------------------------------------------
# M6-1 — Diff-aware test selection
# ---------------------------------------------------------------------------
# LLM-driven diff → case selection (M6-3). It falls back to the full suite when
# no validated workspace LLM exists. Non-streaming JSON response.


class DiffSelectRequest(BaseModel):
    """POST /generators/diff-select request body."""

    suite_id: str
    diff_text: str  # raw unified diff, max 50 KB


class DiffSelectResponse(BaseModel):
    """POST /generators/diff-select response body."""

    selected_case_ids: list[str]
    rationale: str | None
    selection_mode: str  # "llm" | "fallback_full"
    parsed_files_count: int


@router.post(
    "/generators/diff-select",
    response_model=DiffSelectResponse,
)
async def diff_select(
    payload: DiffSelectRequest,
    ctx: TenantContext = Depends(require_role(_WRITER_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> DiffSelectResponse:
    """Select relevant test cases for a PR diff via LLM impact analysis (M6).

    With a validated workspace LLM the endpoint identifies cases most likely to
    catch regressions introduced by ``diff_text``. Otherwise it returns **all**
    cases in the suite so CI always has a safe fallback.

    ``diff_text`` must not exceed 50 000 characters; a 400 is returned if it
    does.  The suite must belong to the caller's workspace; a 404 is returned
    when the suite has no cases.
    """
    from suitest_agent.generators.diff_selector import parse_diff

    from suitest_api.services.diff_selection_service import (
        DiffSelectionService,
        DiffTooLargeError,
        SuiteNotFoundError,
    )

    _MAX_DIFF_CHARS = 50_000
    if len(payload.diff_text) > _MAX_DIFF_CHARS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"diff_text exceeds {_MAX_DIFF_CHARS} characters",
        )

    # Parse the diff upfront to return parsed_files_count even on fallback.
    changed_files = parse_diff(payload.diff_text)

    svc = DiffSelectionService(session)
    try:
        result = await svc.select(
            suite_id=payload.suite_id,
            diff_text=payload.diff_text,
            workspace_id=ctx.workspace_id,
        )
    except SuiteNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="suite not found",
        ) from exc
    except DiffTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return DiffSelectResponse(
        selected_case_ids=result.selected_case_ids,
        rationale=result.rationale if result.selection_mode == "llm" else None,
        selection_mode=result.selection_mode,
        parsed_files_count=len(changed_files),
    )
