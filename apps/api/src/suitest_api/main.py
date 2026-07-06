"""FastAPI application factory."""

import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from suitest_api import __version__
from suitest_api.capabilities import build_base_capabilities
from suitest_api.middleware.audit import AuditContextMiddleware
from suitest_api.middleware.observability import SpanAttributesMiddleware
from suitest_api.middleware.ratelimit import build_limiter
from suitest_api.observability import setup_observability
from suitest_api.settings import Settings, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application startup / shutdown hooks.

    Builds the immutable ZERO base
    :class:`~suitest_shared.schemas.capabilities.Capabilities` exactly once and
    stashes it on ``app.state.capabilities``. LLM/embeddings are configured
    per-workspace from the web UI, so the base needs no env and never fails to boot
    on tier misconfig. Also records ``app.state.started_at`` for the
    ``/capabilities/health`` uptime.

    Also boots the WebSocket connection manager (:mod:`suitest_api.ws.manager`)
    if a Redis-compatible client has been pre-wired onto ``app.state.ws_redis``
    by the bootstrap path. Tests inject ``fakeredis.aioredis.FakeRedis`` here;
    production wires a real :class:`redis.asyncio.Redis` from ``SUITEST_REDIS_URL``.
    """
    from suitest_shared.domain.enums import IntegrationKind

    from suitest_api.integrations.jira_adapter import _IdentityCrypto
    from suitest_api.integrations.registry import adapter_registry, notifier_factories
    from suitest_api.integrations.slack_adapter import SlackAdapter
    from suitest_api.ws.manager import WsConnectionManager

    if not getattr(app.state, "settings", None):
        app.state.settings = get_settings()
    app.state.started_at = time.monotonic()
    app.state.capabilities = build_base_capabilities()
    if app.state.settings.superadmin_email and app.state.settings.superadmin_password:
        from suitest_api.auth.db import async_session_maker
        from suitest_api.services.bootstrap import bootstrap_first_install_superadmin

        async with async_session_maker() as session:
            created = await bootstrap_first_install_superadmin(session, app.state.settings)
            if created:
                await session.commit()

    # Issue-tracker adapter registry (M1d-11). The singleton is constructed at
    # import time; lifespan only stashes it on ``app.state`` so request handlers
    # can resolve it via ``request.app.state.adapter_registry`` (or the
    # ``get_adapter_registry`` Depends helper in :mod:`suitest_api.deps.integrations`).
    # PR-12..15 register concrete adapters (Jira / Linear / GitHub / Slack)
    # by appending ``adapter_registry.register(...)`` lines below this one.
    app.state.adapter_registry = adapter_registry

    # Issue-tracker adapter FACTORY registry (M1d-12..15). Concrete adapters
    # (JiraAdapter, LinearAdapter, GitHubAdapter, …) carry per-:class:`Integration`-row
    # state (workspace_id, decrypted credentials, App installation id) so the
    # ``IntegrationService.sync_external`` call site builds one fresh per
    # request instead of registering a singleton instance on the M1d-11
    # ``adapter_registry``. ``app.state.adapter_factories`` maps
    # :class:`IntegrationKind` → callable returning a constructed adapter for
    # a given ``Integration`` row. Wired here so request handlers can resolve
    # the factory via ``request.app.state.adapter_factories[kind]`` without
    # touching module-level state directly.
    app.state.adapter_factories = _build_adapter_factories()
    # Default crypto seam — ``EncryptedBytes`` already returns plaintext on
    # read so the production path uses an identity callable. KMS-backed crypto
    # can replace this without touching the adapter code.
    app.state.integration_crypto = _IdentityCrypto()

    # Notifier-adapter factory map (M1d-15). Notifier adapters are constructed
    # per-integration-row (each row carries its own webhook secret), so the map
    # stores callables rather than singletons. The Slack factory builds a
    # :class:`~suitest_api.integrations.slack_adapter.SlackAdapter` from the
    # integration row plus the shared httpx client.
    notifier_factories[IntegrationKind.SLACK] = SlackAdapter
    app.state.notifier_factories = notifier_factories

    ws_manager: WsConnectionManager | None = None
    ws_redis = getattr(app.state, "ws_redis", None)
    if ws_redis is None:
        ws_redis = _build_default_ws_redis()
        if ws_redis is not None:
            app.state.ws_redis = ws_redis
    if ws_redis is not None:
        # ``ws_redis`` is duck-typed as ``object`` so :mod:`redis.asyncio` stays
        # off the import path of CLI entrypoints. Tests inject ``fakeredis``
        # (a subclass of ``redis.asyncio.client.Redis``) and prod injects a real
        # ``Redis`` — both satisfy WsConnectionManager's runtime use.
        ws_manager = WsConnectionManager(ws_redis)  # type: ignore[arg-type]
        await ws_manager.start()
        app.state.ws_manager = ws_manager
    try:
        yield
    finally:
        if ws_manager is not None:
            await ws_manager.stop()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construct the FastAPI app. Pure factory — no side effects at import."""
    from suitest_api.auth.router import router as auth_router
    from suitest_api.routers.admin_users import router as admin_users_router
    from suitest_api.routers.agent_chat import router as agent_chat_router
    from suitest_api.routers.agent_plugins import router as agent_plugins_router
    from suitest_api.routers.analytics import router as analytics_router
    from suitest_api.routers.api_keys import router as api_keys_router
    from suitest_api.routers.audit_logs import router as audit_logs_router
    from suitest_api.routers.auth_me import router as auth_me_router
    from suitest_api.routers.autonomy import router as autonomy_router
    from suitest_api.routers.capabilities import router as capabilities_router
    from suitest_api.routers.cost import router as cost_router
    from suitest_api.routers.defects import router as defects_router
    from suitest_api.routers.documents import router as documents_router
    from suitest_api.routers.eval_runs import router as eval_runs_router
    from suitest_api.routers.files import router as files_router
    from suitest_api.routers.generators import router as generators_router
    from suitest_api.routers.inbox import router as inbox_router
    from suitest_api.routers.ingest import router as ingest_router
    from suitest_api.routers.integrations import router as integrations_router
    from suitest_api.routers.invitations import router as invitations_router
    from suitest_api.routers.llm_config import router as llm_config_router
    from suitest_api.routers.llm_proxy import router as llm_proxy_router
    from suitest_api.routers.mcp_providers import router as mcp_providers_router
    from suitest_api.routers.plugins import router as plugins_router
    from suitest_api.routers.projects import router as projects_router
    from suitest_api.routers.prompts import router as prompts_router
    from suitest_api.routers.requirements import requirements_router, traceability_router
    from suitest_api.routers.runs import router as runs_router
    from suitest_api.routers.suites import router as suites_router
    from suitest_api.routers.test_cases import router as test_cases_router
    from suitest_api.routers.webhooks import router as webhooks_router
    from suitest_api.routers.workspaces import router as workspaces_router
    from suitest_api.routers.ws import router as ws_router

    resolved = settings or get_settings()

    app = FastAPI(
        title="Suitest API",
        version=__version__,
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    if settings is not None:
        app.state.settings = settings

    # Rate limiter: per-audience buckets (Bearer / cookie / IP) with default 600/min.
    # Stashed on app.state for SlowAPIMiddleware + the 429 handler to pick up.
    # See suitest_api.middleware.ratelimit for the audience key contract.
    app.state.limiter = build_limiter()

    def _ratelimit_exceeded(request: Request, exc: Exception) -> Response:
        """Adapt slowapi's typed handler to Starlette's ``(Request, Exception)`` shape."""
        assert isinstance(exc, RateLimitExceeded)  # narrows for mypy strict
        return _rate_limit_exceeded_handler(request, exc)

    app.add_exception_handler(RateLimitExceeded, _ratelimit_exceeded)

    # ORDER MATTERS — Starlette wraps ``add_middleware`` calls inside-out: the
    # last call becomes the OUTERMOST layer. Target request flow:
    #   CORS → FastAPIInstrumentor (OTel) → SlowAPIMiddleware
    #     → AuditContextMiddleware → SpanAttributesMiddleware → handler.
    #
    # SpanAttributesMiddleware must run AFTER AuditContextMiddleware populates
    # the ContextVar, AND inside the OTel span so ``set_attributes`` lands on the
    # right span — so we add SpanAttributesMiddleware first (innermost), then
    # AuditContextMiddleware, then SlowAPIMiddleware. ``setup_observability()``
    # below installs the FastAPI instrumentor. ``CORSMiddleware`` is added LAST
    # (outermost) so OPTIONS preflights short-circuit before the rate limiter
    # sees them (Issue I2).
    app.add_middleware(SpanAttributesMiddleware, fastapi_app=app)
    # Binds the per-request audit attribution (ip/ua/workspace) so the global
    # SQLAlchemy after_flush listener can write AuditLog rows.
    app.add_middleware(AuditContextMiddleware)
    # Enforces per-audience rate limits (docs/API.md §5). Reads app.state.limiter,
    # short-circuits with 429 + Retry-After when the bucket is exhausted. Exempt
    # routes (``/health``, ``/metrics``, ``/openapi.json``, ``/docs``,
    # ``/capabilities/health``) are wired via :func:`_exempt_anonymous_routes`
    # below — see :mod:`suitest_api.middleware.ratelimit` for the contract.
    app.add_middleware(SlowAPIMiddleware)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        """Liveness probe — no DB / Redis touch."""
        return {"status": "ok", "service": "api", "version": __version__}

    # Exempt the liveness probe from the rate limiter so Kubernetes probes /
    # uptime monitors don't share the anonymous IP bucket with public traffic
    # (Issue I1). We register the handler name directly rather than using
    # ``@limiter.exempt`` as a decorator — same effect (slowapi's exempt
    # decorator's only side effect is ``_exempt_routes.add(name)``) but keeps
    # the handler's typed signature intact for mypy strict.
    app.state.limiter._exempt_routes.add(f"{health.__module__}.{health.__name__}")

    app.include_router(capabilities_router)
    app.include_router(auth_router)
    app.include_router(admin_users_router)
    app.include_router(auth_me_router)
    app.include_router(invitations_router)
    app.include_router(workspaces_router)
    app.include_router(projects_router)
    app.include_router(suites_router)
    app.include_router(test_cases_router)
    app.include_router(ingest_router)
    app.include_router(files_router)
    app.include_router(requirements_router)
    app.include_router(traceability_router)
    app.include_router(runs_router)
    app.include_router(defects_router)
    app.include_router(integrations_router)
    app.include_router(documents_router)
    app.include_router(eval_runs_router)
    app.include_router(analytics_router)
    app.include_router(api_keys_router)
    app.include_router(audit_logs_router)
    app.include_router(inbox_router)
    app.include_router(mcp_providers_router)
    app.include_router(llm_config_router)
    app.include_router(autonomy_router)
    app.include_router(cost_router)
    app.include_router(agent_chat_router)
    app.include_router(llm_proxy_router)
    app.include_router(prompts_router)
    app.include_router(generators_router)
    app.include_router(agent_plugins_router)
    app.include_router(plugins_router)
    app.include_router(webhooks_router)
    # WebSocket gateway — mounted at root (NOT /api/v1) so the path stays
    # ``GET /ws?token=...``. CORS preflight does not apply to WebSocket upgrades;
    # cross-origin enforcement lives in the JWT check (Task 14).
    app.include_router(ws_router)

    # Observability is wired BEFORE CORS so:
    #   1. FastAPIInstrumentor sees every non-preflight request (CORS short-circuits
    #      OPTIONS before tracing — acceptable, preflights carry no app payload).
    #   2. Prometheus `/metrics` route is appended after all real routes (clean
    #      route order in the router).
    # Skipped automatically when SUITEST_OTEL_DISABLED=true; idempotent via
    # `app.state.otel_setup` guard.
    from suitest_api.auth.db import engine as auth_engine

    setup_observability(app, engine=auth_engine)

    # Exempt anonymous / probe routes (``/openapi.json``, ``/docs``,
    # ``/metrics``, ``/capabilities/health``) AFTER ``setup_observability`` so
    # the ``/metrics`` route exists. ``/health`` is already exempted via the
    # ``@limiter.exempt`` decorator on its inline handler above.
    _exempt_anonymous_routes(app)

    # CORS is added LAST so it becomes the OUTERMOST middleware (Starlette LIFO).
    # OPTIONS preflights then short-circuit before SlowAPIMiddleware sees them —
    # otherwise every preflight would burn one slot in the anonymous IP bucket
    # (Issue I2).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved.web_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Local bundle: serve the built web dashboard as SPA. Mounted LAST so every
    # /api/* + /auth/* router is matched first; the catch-all only handles the
    # frontend routes. No-op in server mode (web served separately). env:
    # SUITEST_WEB_DIST -> folder containing index.html.
    web_dist = os.environ.get("SUITEST_WEB_DIST", "").strip()
    if web_dist and (Path(web_dist) / "index.html").is_file():
        from fastapi.staticfiles import StaticFiles
        from starlette.exceptions import HTTPException as StarletteHTTPException
        from starlette.types import Scope

        class _SpaStaticFiles(StaticFiles):
            """StaticFiles that falls back to index.html for unknown paths (SPA deep links)."""

            async def get_response(self, path: str, scope: Scope) -> Response:
                try:
                    return await super().get_response(path, scope)
                except StarletteHTTPException as exc:
                    if exc.status_code == 404:
                        return await super().get_response("index.html", scope)
                    raise

        app.mount("/", _SpaStaticFiles(directory=web_dist, html=True), name="web")

    return app


def _exempt_anonymous_routes(app: FastAPI) -> None:
    """Mark library-registered anonymous routes as rate-limit exempt (Issue I1).

    ``slowapi``'s :meth:`Limiter.exempt` decorator works by adding the handler's
    ``<module>.<qualname>`` to ``Limiter._exempt_routes``; the middleware then
    skips any request whose resolved handler matches that set. We can't decorate
    handlers registered by libraries (FastAPI's auto-generated ``/openapi.json`` +
    ``/docs``, Prometheus's ``/metrics``), so we walk ``app.routes`` post-wiring
    and insert their handler names directly.

    Endpoints exempted:
      * ``/openapi.json`` — ~75KB; would otherwise burn the anonymous bucket on
        every docs / SDK regen.
      * ``/docs`` — Swagger UI shell; same DoS surface as ``/openapi.json``.
      * ``/metrics`` — Prometheus scrape target; scrapers (every 15-30s) share
        the anonymous IP bucket with public traffic without this.
      * ``/capabilities/health`` — public k8s readiness probe; defined in
        :mod:`suitest_api.routers.capabilities` whose router is shared across
        ``create_app`` calls, so we exempt it here (per-app) rather than at
        import time.
    """
    exempt_paths = {"/openapi.json", "/docs", "/metrics", "/capabilities/health"}
    limiter = app.state.limiter
    for route in app.routes:
        path = getattr(route, "path", None)
        if path not in exempt_paths:
            continue
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        name = f"{endpoint.__module__}.{endpoint.__name__}"
        limiter._exempt_routes.add(name)


def _build_adapter_factories() -> dict[object, object]:
    """Return the :class:`IntegrationKind` → adapter-factory map (M1d-12..15).

    Each value is a callable accepting keyword args
    ``integration`` / ``mcp_client`` / ``crypto`` / ``http_client`` and returning
    a fully-constructed :class:`IssueTrackerAdapter`. The call site (e.g.
    :meth:`IntegrationService.sync_external`) builds the adapter once per
    request — keeping per-row state (decrypted credentials, App installation
    id, token cache) bounded to that request's lifetime.

    The return annotation is ``dict[object, object]`` rather than
    ``dict[IntegrationKind, AdapterFactory]`` so this helper can ship before
    every adapter lands without forcing each call site to know the union of
    constructor signatures.
    """
    import httpx as _httpx
    from suitest_db.models.integration import Integration as _IntegrationModel
    from suitest_shared.domain.enums import IntegrationKind

    from suitest_api.integrations.github_adapter import GitHubAdapter
    from suitest_api.integrations.jira_adapter import JiraAdapter
    from suitest_api.integrations.linear_adapter import LinearAdapter

    def _linear_factory(
        *, integration: _IntegrationModel, http_client: _httpx.AsyncClient
    ) -> LinearAdapter:
        """Build a per-:class:`Integration` :class:`LinearAdapter`."""
        return LinearAdapter(integration=integration, http_client=http_client)

    return {
        IntegrationKind.JIRA: JiraAdapter,
        IntegrationKind.LINEAR: _linear_factory,
        IntegrationKind.GITHUB: GitHubAdapter,
    }


def _build_default_ws_redis() -> object | None:
    """Lazily construct a :class:`redis.asyncio.Redis` from ``SUITEST_REDIS_URL``.

    Returns ``None`` when the env var is unset OR points at an in-memory backend
    (``memory://``) — in those cases the WS gateway stays inert (the endpoint
    closes with ``4401`` "unavailable" if a client tries to connect) so dev /
    test runs that opt out of Redis don't pay the connect cost. Tests inject a
    ``fakeredis`` client on ``app.state.ws_redis`` BEFORE entering the lifespan.

    The return type is ``object | None`` so the import of :mod:`redis.asyncio`
    stays local — main.py is imported at startup by every CLI script (incl.
    the openapi exporter) and we don't want to drag the redis async client
    into modules that never serve a WS. The lifespan casts via
    ``# type: ignore[arg-type]`` when handing it to ``WsConnectionManager``.
    """
    import os

    url = os.environ.get("SUITEST_REDIS_URL")
    if not url or url.startswith("memory://"):
        return None
    try:
        from redis.asyncio import Redis
    except ImportError:  # pragma: no cover — redis is a hard dep via slowapi/arq
        return None
    client: object = Redis.from_url(url, decode_responses=False)
    return client


# Intentionally NO module-level ``app = create_app()``.
# Importing this module must be side-effect free: a module-level instance would
# (a) trigger OTel BatchSpanProcessor / Prometheus collector registration on
# every import (tooling like ``scripts/export-openapi.py`` would double-instrument
# the process), and (b) leak a background thread per import in dev/test runs.
# Production / dev uvicorn invocations use ``--factory suitest_api.main:create_app``
# (see ``apps/api/src/suitest_api/__main__.py`` and the API Dockerfile CMD).
